from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import create_app


def test_upload_analysis_and_restart(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/health").status_code == 200
        response = client.post("/documents", files={"file": ("../../factura.txt", b"factura", "text/plain")})
        assert response.status_code == 201
        document = response.json()
        assert document["filename"] == "factura.txt"
        assert document["size_bytes"] == 7
        url = f"/documents/{document['id']}"
        analyzed = client.post(url + "/analyze").json()
        assert analyzed["analysis"] == {"category": "invoice", "confidence": 0.72,
                                        "requires_review": True, "simulated": True}
        assert client.post(url + "/analyze").json() == analyzed
    with TestClient(create_app(tmp_path)) as restarted:
        assert restarted.get(url).json() == analyzed
    assert (tmp_path / "files" / document["id"]).read_bytes() == b"factura"


def test_errors_and_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.MAX_BYTES", 8)
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(f"/documents/{uuid4()}").status_code == 404
        assert client.post(f"/documents/{uuid4()}/analyze").status_code == 404
        assert client.get("/documents/invalid").status_code == 422
        assert client.post("/documents").status_code == 422
        assert client.post("/documents", files={"file": ("empty.txt", b"")}).status_code == 400
        assert client.post("/documents", files={"file": ("big.txt", b"123456789")}).status_code == 413
    assert list((tmp_path / "files").iterdir()) == []
