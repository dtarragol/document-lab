import httpx
from fastapi.testclient import TestClient
from app.main import create_app


def test_azure_rag_opt_in_no_sources_and_persistent_budget(tmp_path, monkeypatch):
    calls = []
    def generate(messages):
        calls.append(messages)
        return {'answer': 'Usa particiones [S1].', 'usage': {'total_tokens': 100}, 'finish_reason': 'stop'}
    monkeypatch.setattr('app.azure_llm.generate', generate)
    monkeypatch.delenv('ENABLE_AZURE_LLM', raising=False)
    monkeypatch.setenv('LLM_DAILY_CALL_LIMIT', '1')
    request = {'question': 'Como organiza Cosmos los datos?', 'search_query': 'Cosmos'}
    with TestClient(create_app(tmp_path)) as client:
        assert client.post('/rag/ask', json=request).status_code == 503
        monkeypatch.setenv('ENABLE_AZURE_LLM', 'true')
        assert client.post('/rag/ask', json=request).json()['status'] == 'no_sources'
        assert not calls
        doc_id = client.post('/documents', files={'file': ('tema.txt', b'Cosmos usa particiones.')}).json()['id']
        client.post(f'/documents/{doc_id}/index')
        response = client.post('/rag/ask', json=request)
        assert response.status_code == 200
        assert response.json()['sources'][0]['citation'] == 'S1'
        assert response.json()['usage']['total_tokens'] == 100
    with TestClient(create_app(tmp_path)) as client:
        assert client.post('/rag/ask', json=request).status_code == 429
    assert len(calls) == 1


def test_failed_attempt_also_consumes_budget(tmp_path, monkeypatch):
    monkeypatch.setenv('ENABLE_AZURE_LLM', 'true')
    monkeypatch.setenv('LLM_DAILY_CALL_LIMIT', '1')
    def fail(messages):
        raise httpx.ReadTimeout('timeout')
    monkeypatch.setattr('app.azure_llm.generate', fail)
    with TestClient(create_app(tmp_path)) as client:
        doc_id = client.post('/documents', files={'file': ('tema.txt', b'Cosmos particiones')}).json()['id']
        client.post(f'/documents/{doc_id}/index')
        request = {'question': 'Explica Cosmos', 'search_query': 'Cosmos'}
        assert client.post('/rag/ask', json=request).status_code == 503
        assert client.post('/rag/ask', json=request).status_code == 429
