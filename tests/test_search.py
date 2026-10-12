from fastapi.testclient import TestClient
from app.main import create_app


def test_index_search_reindex_and_persistence(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        ids = []
        for filename, content in [('a.txt', 'Factura de alojamiento Azure.'),
                                  ('azure.txt', 'Acta de la reunion semanal.')]:
            response = client.post('/documents', files={'file': (filename, content.encode())})
            ids.append(response.json()['id'])
        assert client.get('/search', params={'q': 'Azure'}).json()['count'] == 0
        for doc_id in ids:
            assert client.post(f'/documents/{doc_id}/index').status_code == 200
        client.post(f'/documents/{ids[0]}/index')
        result = client.get('/search', params={'q': 'factura AZURE'}).json()
        assert result['count'] == 1
        assert result['results'][0]['id'] == ids[0]
        assert client.get('/search', params={'q': 'noexiste'}).json()['results'] == []
        for query in ['"', 'OR', '*', 'a:b', '   ']:
            assert client.get('/search', params={'q': query}).status_code in (200, 422)
        assert client.get('/search', params={'q': 'Azure', 'limit': 0}).status_code == 422
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/search', params={'q': 'azure'}).json()['count'] == 1
