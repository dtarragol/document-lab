"""Índice de fragmentos en Azure AI Search, sin claves. Setup: python -m app.azure_search."""
import json
import os
import re
from urllib.parse import urlparse

import httpx
from azure.identity import AzureCliCredential
from app.embeddings import DIMENSIONS, embed


def vectors_enabled():
    return os.getenv('AZURE_SEARCH_VECTORS', 'false').lower() == 'true'


def _request(method, path, body=None, headers=None):
    endpoint = os.getenv('AZURE_SEARCH_ENDPOINT', '').rstrip('/')
    parsed = urlparse(endpoint)
    if (parsed.scheme != 'https' or not (parsed.hostname or '').endswith('.search.windows.net')
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
            or parsed.port not in (None, 443)):
        raise ValueError('Configura AZURE_SEARCH_ENDPOINT con la URL HTTPS del servicio')
    with AzureCliCredential() as credential:
        token = credential.get_token('https://search.azure.com/.default').token
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            response = client.request(method, endpoint + path, params={'api-version': '2024-07-01'},
                headers=dict(headers or {}, Authorization=f'Bearer {token}'), json=body)
            response.raise_for_status()
            return response.json()


def _index_path():
    name = os.getenv('AZURE_SEARCH_INDEX', 'document-chunks-v1')
    if not re.fullmatch('[a-z0-9][a-z0-9-]{1,126}', name):
        raise ValueError('AZURE_SEARCH_INDEX no es un nombre válido')
    return f'/indexes/{name}'


def setup_index():
    path = _index_path()
    try:
        existing = _request('GET', path)
        fields = {field['name']: field['type'] for field in existing.get('fields', [])}
        expected = {'id': 'Edm.String', 'document_id': 'Edm.String', 'filename': 'Edm.String',
                    'chunk_number': 'Edm.Int32', 'content': 'Edm.String'}
        if any(fields.get(name) != kind for name, kind in expected.items()):
            raise ValueError('El índice existente tiene un esquema incompatible; usa otro nombre')
        if vectors_enabled():
            vector = next((field for field in existing['fields'] if field['name'] == 'vector'), {})
            if vector.get('dimensions') != DIMENSIONS or not vector.get('vectorSearchProfile'):
                raise ValueError('Se necesita un índice vectorial nuevo de 1536 dimensiones')
        return existing
    except httpx.HTTPStatusError as error:
        if error.response.status_code != 404:
            raise
    schema = {'name': path.rsplit('/', 1)[-1], 'fields': [
        {'name': 'id', 'type': 'Edm.String', 'key': True, 'searchable': False},
        {'name': 'document_id', 'type': 'Edm.String', 'filterable': True, 'searchable': False},
        {'name': 'filename', 'type': 'Edm.String', 'searchable': False},
        {'name': 'chunk_number', 'type': 'Edm.Int32', 'searchable': False},
        {'name': 'content', 'type': 'Edm.String', 'searchable': True}
    ]}
    if vectors_enabled():
        schema['fields'].append({'name': 'vector', 'type': 'Collection(Edm.Single)',
            'searchable': True, 'retrievable': False, 'dimensions': DIMENSIONS, 'vectorSearchProfile': 'vector-profile'})
        schema['vectorSearch'] = {'algorithms': [{'name': 'hnsw-config', 'kind': 'hnsw',
            'hnswParameters': {'metric': 'cosine'}}],
            'profiles': [{'name': 'vector-profile', 'algorithm': 'hnsw-config'}]}
    return _request('PUT', path, schema, headers={'If-None-Match': '*'})


def index_chunks(document_id, filename, chunks):
    # Los originales son inmutables y la fragmentación v1 es fija: claves deterministas.
    documents = [dict(id=f'{document_id}-{number}', document_id=str(document_id), filename=filename,
                      chunk_number=number, content=text, **{'@search.action': 'upload'})
                 for number, text in enumerate(chunks)]
    body = {'value': documents}
    if len(documents) > 1000 or len(json.dumps(body).encode()) > 8 * 1024 * 1024:
        raise ValueError('Documento demasiado grande para esta práctica de indexación Azure')
    if vectors_enabled():
        if len(chunks) > 120 or sum(map(len, chunks)) > 120000 or any(len(text) > 4000 for text in chunks):
            raise ValueError('Esta práctica admite hasta 120 fragmentos, 120000 caracteres en total y 4000 por fragmento')
        vectors = []
        batch = []
        batch_chars = 0
        for chunk in chunks:
            if batch and (len(batch) == 30 or batch_chars + len(chunk) > 60000):
                vectors.extend(embed(batch))
                batch, batch_chars = [], 0
            batch.append(chunk)
            batch_chars += len(chunk)
        if batch:
            vectors.extend(embed(batch))
        for document, vector in zip(documents, vectors):
            document['vector'] = vector
        if len(json.dumps(body).encode()) > 8 * 1024 * 1024:
            raise ValueError('El lote vectorial supera 8 MiB')
    response = _request('POST', _index_path() + '/docs/index', body)
    results = response.get('value', [])
    if len(results) != len(documents) or any(not item.get('status') for item in results):
        raise RuntimeError('Azure Search rechazó uno o más fragmentos; puedes repetir la indexación')


def retrieve_chunks(q, top_k, mode=None):
    # Los operadores de consulta se eliminan: palabras clave literales con AND.
    terms = re.findall(r'\w+', q, flags=re.UNICODE)
    if not terms:
        raise ValueError('Introduce al menos una palabra')
    mode = mode or os.getenv('AZURE_SEARCH_MODE', 'lexical')
    if mode not in ('lexical', 'vector', 'hybrid'):
        raise ValueError('Modo de búsqueda no válido')
    body = {
        'search': ' '.join(terms), 'queryType': 'simple', 'searchMode': 'all',
        'searchFields': 'content', 'select': 'document_id,filename,chunk_number,content', 'top': top_k}
    if mode != 'lexical':
        if not vectors_enabled():
            raise ValueError('Activa AZURE_SEARCH_VECTORS y utiliza un índice vectorial')
        body['vectorQueries'] = [{'kind': 'vector', 'vector': embed([q])[0], 'fields': 'vector', 'k': max(top_k, 10)}]
        if mode == 'vector':
            for field in ('search', 'searchFields', 'searchMode', 'queryType'):
                body.pop(field)
    response = _request('POST', _index_path() + '/docs/search', body)
    return [dict(document_id=item['document_id'], filename=item['filename'],
                 chunk_number=item['chunk_number'], text=item['content']) for item in response['value']]


if __name__ == '__main__':
    result = setup_index()
    print(f'Índice listo: {result["name"]}')
