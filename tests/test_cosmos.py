from copy import deepcopy
from uuid import uuid4

import pytest
from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from fastapi.testclient import TestClient

from app.azure_api import create_azure_app
from app.main import Analysis, Document
from app.metadata import CosmosMetadata
from test_azure_api import FakeContainer


class FakeCosmos:
    def __init__(self):
        self.items = {}
        self.race = False

    def read(self):
        return {'partitionKey': {'paths': ['/id']}}

    def create_item(self, body):
        self.items[body['id']] = dict(deepcopy(body), _etag='1')

    def read_item(self, item, partition_key):
        assert item == partition_key
        if item not in self.items:
            raise CosmosResourceNotFoundError(status_code=404, message='missing')
        return deepcopy(self.items[item])

    def replace_item(self, item, body, etag, match_condition):
        assert match_condition == MatchConditions.IfNotModified
        if self.race:
            self.items[item].update(analysis={'category': 'other', 'confidence': 0.9,
                'requires_review': False, 'simulated': True}, status='Analyzed', _etag='2')
        if self.items[item]['_etag'] != etag:
            raise CosmosHttpResponseError(status_code=412, message='conflict')
        self.items[item] = dict(deepcopy(body), _etag='2')
        return deepcopy(self.items[item])


@pytest.mark.parametrize('race', [False, True])
def test_cosmos_api_persistence_and_concurrency(monkeypatch, race):
    monkeypatch.setenv('METADATA_BACKEND', 'cosmos')
    storage, cosmos = FakeContainer(), FakeCosmos()
    repository = CosmosMetadata(cosmos)
    def app():
        return create_azure_app(Document, Analysis, 8, storage, repository)
    with TestClient(app()) as client:
        assert client.get('/health').json()['metadata_backend'] == 'cosmos'
        assert client.get(f'/documents/{uuid4()}').status_code == 404
        response = client.post('/documents', files={'file': ('factura.txt', b'demo')})
        assert response.status_code == 201
        doc_id = response.json()['id']
        cosmos.race = race
        url = f'/documents/{doc_id}'
        analyzed = client.post(url + '/analyze')
        assert analyzed.status_code == 200
        assert analyzed.json()['analysis']['confidence'] == (0.9 if race else 0.72)
    with TestClient(app()) as client:
        assert client.get(url).json() == analyzed.json()
        assert client.post(url + '/analyze').json() == analyzed.json()
        def unavailable(**kwargs):
            raise CosmosHttpResponseError(status_code=503, message='unavailable')
        cosmos.read_item = unavailable
        assert client.get(url).status_code == 503
    assert list(storage.data) == [f'originals/{doc_id}']


def test_cosmos_partition_validation():
    cosmos = FakeCosmos()
    cosmos.read = lambda: {'partitionKey': {'paths': ['/category']}}
    with pytest.raises(RuntimeError, match='/id'):
        CosmosMetadata(cosmos).check()
