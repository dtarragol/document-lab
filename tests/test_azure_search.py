import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app import azure_search


def test_azure_index_and_rag_retrieval(tmp_path, monkeypatch):
    monkeypatch.setenv('SEARCH_BACKEND', 'azure')
    stored = []
    def index(doc_id, filename, chunks):
        stored[:] = [dict(document_id=doc_id, filename=filename, chunk_number=i, text=text)
                     for i, text in enumerate(chunks)]
    monkeypatch.setattr(azure_search, 'index_chunks', index)
    monkeypatch.setattr(azure_search, 'retrieve_chunks', lambda q, top_k: stored[:top_k])
    with TestClient(create_app(tmp_path)) as client:
        doc_id = client.post('/documents', files={'file': ('tema.txt', b'Cosmos particiones')}).json()['id']
        assert client.post(f'/documents/{doc_id}/index').json()['search_backend'] == 'azure'
        assert client.get('/retrieve', params={'q': 'Cosmos'}).json()['retrieval_mode'] == 'azure_lexical'
        result = client.post('/rag/prepare', json={'question': 'Explica Cosmos', 'search_query': 'Cosmos'}).json()
        assert result['sources'][0]['document_id'] == doc_id
        def fail(*args):
            raise RuntimeError('partial upload')
        monkeypatch.setattr(azure_search, 'index_chunks', fail)
        assert client.post(f'/documents/{doc_id}/index').status_code == 503


def test_partial_index_failure_and_query_parameters(monkeypatch):
    requests = []
    def request(method, path, body):
        requests.append(body)
        if path.endswith('/docs/index'):
            return {'value': [{'status': False}]}
        return {'value': []}
    monkeypatch.setattr(azure_search, '_request', request)
    with pytest.raises(RuntimeError):
        azure_search.index_chunks('id', 'tema.txt', ['text'])
    assert azure_search.retrieve_chunks('Cosmos +particiones*', 3) == []
    assert requests[-1]['search'] == 'Cosmos particiones'
    assert requests[-1]['searchMode'] == 'all'
    with pytest.raises(ValueError):
        azure_search.index_chunks('id', 'tema.txt', ['x'] * 1001)
