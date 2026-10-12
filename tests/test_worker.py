from fastapi.testclient import TestClient
from app.main import create_app
from app.worker import process_one


def test_queue_survives_restart_and_duplicate_requests(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        doc_id = client.post('/documents', files={'file': ('factura.txt', b'demo')}).json()['id']
        url = f'/documents/{doc_id}'
        for _ in range(2):
            assert client.post(url + '/enqueue').status_code == 202
        assert client.get(url).json()['status'] == 'Queued'
        assert client.post(url + '/analyze').status_code == 409
    assert process_one(tmp_path)
    assert not process_one(tmp_path)
    with TestClient(create_app(tmp_path)) as client:
        item = client.get(url).json()
        assert item['status'] == 'Analyzed'
        assert item['analysis']['category'] == 'invoice'
        assert client.post(url + '/enqueue').json()['status'] == 'AlreadyAnalyzed'
    assert not process_one(tmp_path)
