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


def test_failures_dead_letter_and_recovery_on_next_attempt(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        def enqueue():
            doc_id = client.post('/documents', files={'file': ('factura.txt', b'demo')}).json()['id']
            client.post(f'/documents/{doc_id}/enqueue')
            return doc_id
        first = enqueue()
        for attempt in range(1, 4):
            assert process_one(tmp_path, simulate_failure=True)
            job = client.get(f'/jobs/{first}').json()
            assert job['attempts'] == attempt
            assert job['status'] == ('DeadLetter' if attempt == 3 else 'Pending')
        assert not process_one(tmp_path)
        assert client.get(f'/documents/{first}').json()['status'] == 'Failed'
        assert client.post(f'/documents/{first}/enqueue').status_code == 409
        second = enqueue()
        assert process_one(tmp_path, simulate_failure=True)
        assert process_one(tmp_path)
        job = client.get(f'/jobs/{second}').json()
        assert job['status'] == 'Completed'
        assert job['attempts'] == 2
        assert job['last_error'] is None
        assert client.post(f'/jobs/{second}/retry').status_code == 409
        assert client.post(f'/jobs/{first}/retry').status_code == 202
        assert client.post(f'/jobs/{first}/retry').status_code == 409
        recovered = client.get(f'/jobs/{first}').json()
        assert recovered['attempts'] == 0
        assert recovered['last_error'] is None
        assert client.get(f'/documents/{first}').json()['status'] == 'Queued'
        assert process_one(tmp_path)
        assert client.get(f'/documents/{first}').json()['status'] == 'Analyzed'
