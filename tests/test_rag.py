import json
from fastapi.testclient import TestClient
from app.main import create_app


def test_prepare_grounded_context_and_no_sources(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        doc_id = client.post('/documents', files={'file': ('tema.txt', b'Cosmos usa particiones.')}).json()['id']
        client.post(f'/documents/{doc_id}/index')
        request = {'question': 'Como organiza Cosmos los datos?', 'search_query': 'Cosmos'}
        result = client.post('/rag/prepare', json=request)
        assert result.status_code == 200
        data = result.json()
        assert data['status'] == 'ready'
        assert data['sources'][0]['citation'] == 'S1'
        assert data['sources'][0]['document_id'] == doc_id
        payload = json.loads(data['messages'][1]['content'])
        assert payload['question'] == request['question']
        assert payload['sources'] == data['sources']
        request['search_query'] = 'inexistente'
        assert client.post('/rag/prepare', json=request).json()['status'] == 'no_sources'
        request['question'] = '   '
        assert client.post('/rag/prepare', json=request).status_code == 422
