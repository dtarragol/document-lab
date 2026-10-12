"""Índice de fragmentos en Azure AI Search, sin claves. Setup: python -m app.azure_search."""
import json
import os
import re
from urllib.parse import urlparse

import httpx
from azure.identity import AzureCliCredential


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
        return existing
    except httpx.HTTPStatusError as error:
        if error.response.status_code != 404:
            raise
    return _request('PUT', path, {'name': path.rsplit('/', 1)[-1], 'fields': [
        {'name': 'id', 'type': 'Edm.String', 'key': True, 'searchable': False},
        {'name': 'document_id', 'type': 'Edm.String', 'filterable': True, 'searchable': False},
        {'name': 'filename', 'type': 'Edm.String', 'searchable': False},
        {'name': 'chunk_number', 'type': 'Edm.Int32', 'searchable': False},
        {'name': 'content', 'type': 'Edm.String', 'searchable': True}
    ]}, headers={'If-None-Match': '*'})


def index_chunks(document_id, filename, chunks):
    # Los originales son inmutables y la fragmentación v1 es fija: claves deterministas.
    documents = [dict(id=f'{document_id}-{number}', document_id=str(document_id), filename=filename,
                      chunk_number=number, content=text, **{'@search.action': 'upload'})
                 for number, text in enumerate(chunks)]
    body = {'value': documents}
    if len(documents) > 1000 or len(json.dumps(body).encode()) > 8 * 1024 * 1024:
        raise ValueError('Documento demasiado grande para esta práctica de indexación Azure')
    response = _request('POST', _index_path() + '/docs/index', body)
    results = response.get('value', [])
    if len(results) != len(documents) or any(not item.get('status') for item in results):
        raise RuntimeError('Azure Search rechazó uno o más fragmentos; puedes repetir la indexación')


def retrieve_chunks(q, top_k):
    # Los operadores de consulta se eliminan: palabras clave literales con AND.
    terms = re.findall(r'\w+', q, flags=re.UNICODE)
    if not terms:
        raise ValueError('Introduce al menos una palabra')
    response = _request('POST', _index_path() + '/docs/search', {
        'search': ' '.join(terms), 'queryType': 'simple', 'searchMode': 'all',
        'searchFields': 'content', 'select': 'document_id,filename,chunk_number,content', 'top': top_k})
    return [dict(document_id=item['document_id'], filename=item['filename'],
                 chunk_number=item['chunk_number'], text=item['content']) for item in response['value']]


if __name__ == '__main__':
    result = setup_index()
    print(f'Índice listo: {result["name"]}')
