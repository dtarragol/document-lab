from fastapi.testclient import TestClient
from app.main import create_app


def test_review_requires_analysis_and_preserves_first_decision(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        doc_id = client.post('/documents', files={'file': ('factura.txt', b'demo')}).json()['id']
        url = f'/documents/{doc_id}/review'
        assert client.get(url).json()['decision'] == 'Pending'
        assert client.post(url, json={'decision': 'Approved'}).status_code == 409
        assert client.post(url, json={'decision': 'invalid'}).status_code == 422
        client.post(f'/documents/{doc_id}/analyze')
        decision = client.post(url, json={'decision': 'Approved'})
        assert decision.status_code == 200
        assert client.post(url, json={'decision': 'Approved'}).json() == decision.json()
        assert client.post(url, json={'decision': 'Rejected'}).status_code == 409
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(url).json() == decision.json()
