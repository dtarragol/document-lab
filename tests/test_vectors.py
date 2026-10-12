import pytest
from app import embeddings, azure_search


def test_embedding_cache_and_daily_limit(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('ENABLE_AZURE_EMBEDDINGS', 'true')
    monkeypatch.setenv('EMBEDDING_DAILY_CALL_LIMIT', '1')
    calls = []
    def post(deployment, operation, payload):
        calls.append(payload)
        return {'data': [{'index': i, 'embedding': [0.1] * 1536} for i, _ in enumerate(payload['input'])],
                'usage': {'total_tokens': 10}}
    monkeypatch.setattr(embeddings, 'post_azure', post)
    assert len(embeddings.embed(['text', 'text'])) == 2
    assert len(calls) == 1
    assert calls[0]['input'] == ['text']
    assert len(embeddings.embed(['text'])[0]) == 1536
    with pytest.raises(ValueError, match='Límite diario'):
        embeddings.embed(['different'])
    with pytest.raises(ValueError, match='30 textos'):
        embeddings.embed(['x'] * 31)


def test_vector_and_hybrid_requests(monkeypatch):
    monkeypatch.setenv('AZURE_SEARCH_VECTORS', 'true')
    monkeypatch.setattr(azure_search, 'embed', lambda texts: [[0.1] * 1536 for _ in texts])
    requests = []
    def request(method, path, body):
        requests.append(body)
        return {'value': []}
    monkeypatch.setattr(azure_search, '_request', request)
    azure_search.retrieve_chunks('mensajes entre aplicaciones', 3, 'vector')
    assert 'search' not in requests[-1]
    assert len(requests[-1]['vectorQueries'][0]['vector']) == 1536
    azure_search.retrieve_chunks('mensajes entre aplicaciones', 3, 'hybrid')
    assert requests[-1]['search'] == 'mensajes entre aplicaciones'
    assert requests[-1]['vectorQueries']
    azure_search.retrieve_chunks('mensajes', 3, 'lexical')
    assert 'vectorQueries' not in requests[-1]


def test_index_103_chunks_in_bounded_batches(monkeypatch):
    monkeypatch.setenv('AZURE_SEARCH_VECTORS', 'true')
    batches = []
    def embed(texts):
        batches.append(list(texts))
        return [[0.1] * 1536 for _ in texts]
    monkeypatch.setattr(azure_search, 'embed', embed)
    def request(method, path, body):
        assert len(body['value']) == 103
        assert all(len(item['vector']) == 1536 for item in body['value'])
        return {'value': [{'status': True} for _ in body['value']]}
    monkeypatch.setattr(azure_search, '_request', request)
    azure_search.index_chunks('id', 'dossier.docx', ['text'] * 103)
    assert list(map(len, batches)) == [30, 30, 30, 13]
    batches.clear()
    with pytest.raises(ValueError, match='120 fragmentos'):
        azure_search.index_chunks('id', 'large.docx', ['text'] * 121)
    assert not batches
