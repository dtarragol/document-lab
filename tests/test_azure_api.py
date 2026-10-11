import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError, ServiceRequestError
from fastapi.testclient import TestClient
from app.azure_api import create_azure_app
from app.main import Document, Analysis


class FakeContainer:
    def __init__(self):
        self.data = {}

    def get_container_properties(self):
        return {}

    def get_blob_client(self, name):
        def upload_blob(data, **kwargs):
            if name in self.data:
                raise ResourceExistsError("exists")
            self.data[name] = data.read() if hasattr(data, "read") else data

        def download_blob():
            if name not in self.data:
                raise ResourceNotFoundError("missing")
            return SimpleNamespace(readall=lambda: self.data[name])
        return SimpleNamespace(upload_blob=upload_blob, download_blob=download_blob)


def test_azure_persistence_and_racing_result():
    storage = FakeContainer()
    with TestClient(create_azure_app(Document, Analysis, 8, storage)) as client:
        assert client.get('/health').json()['storage_backend'] == 'azure'
        response = client.post('/documents', files={'file': ('factura.txt', b'demo')})
        assert response.status_code == 201
        doc_id = response.json()['id']
        url = f'/documents/{doc_id}'
        # Simular otra réplica creando el resultado entre lectura y escritura.
        original = storage.get_blob_client
        def racing(name):
            client_blob = original(name)
            if name == f'results/{doc_id}.json':
                upload = client_blob.upload_blob
                def race(data, **kwargs):
                    storage.data[name] = json.dumps({'category': 'other', 'confidence': 0.9,
                        'requires_review': False, 'simulated': True}).encode()
                    upload(data, **kwargs)
                client_blob.upload_blob = race
            return client_blob
        storage.get_blob_client = racing
        result = client.post(url + '/analyze')
        assert result.status_code == 200
        assert result.json()['analysis']['confidence'] == 0.9
    with TestClient(create_azure_app(Document, Analysis, 8, storage)) as client:
        assert client.get(url).json() == result.json()
        assert client.post(url + '/analyze').json() == result.json()
    assert storage.data[f'originals/{doc_id}'] == b'demo'


def test_azure_errors():
    storage = FakeContainer()
    with TestClient(create_azure_app(Document, Analysis, 8, storage)) as client:
        assert client.get(f'/documents/{uuid4()}').status_code == 404
        assert client.post('/documents', files={'file': ('x', b'')}).status_code == 400
        assert client.post('/documents', files={'file': ('x', b'123456789')}).status_code == 413
        assert not storage.data
        def fail():
            raise ServiceRequestError('network')
        storage.get_container_properties = fail
        assert client.get('/health').status_code == 503
