import json
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app import invoice


@pytest.mark.parametrize('state', ['extracted', 'refused', 'incomplete', 'invalid_output'])
def test_structured_invoice_responses(monkeypatch, state):
    data = {'numero_factura': 'F-1', 'proveedor': 'Ejemplo', 'fecha': '2026-10-12', 'total': 120.5, 'moneda': 'EUR'}
    message = {'content': json.dumps(data)}
    reason = 'stop'
    if state == 'refused':
        message['refusal'] = 'refused'
    elif state == 'incomplete':
        reason = 'length'
    elif state == 'invalid_output':
        message['content'] = json.dumps(dict(data, fecha='2026-02-31'))
    def post(deployment, operation, payload):
        assert payload['response_format']['json_schema']['strict']
        assert payload['response_format']['json_schema']['schema']['additionalProperties'] is False
        return {'choices': [{'message': message, 'finish_reason': reason}], 'usage': {'total_tokens': 20}}
    monkeypatch.setattr(invoice, 'post_azure', post)
    result = invoice.extract_invoice('Factura')
    assert result['status'] == state
    assert result['usage']['total_tokens'] == 20
    assert (result['data'] is not None) == (state == 'extracted')


def test_invoice_cache_and_shared_budget(tmp_path, monkeypatch):
    monkeypatch.setenv('ENABLE_AZURE_LLM', 'true')
    monkeypatch.setenv('LLM_DAILY_CALL_LIMIT', '1')
    monkeypatch.setattr(invoice, 'extract_invoice', lambda text: {
        'status': 'extracted', 'data': {'numero_factura': None, 'proveedor': None, 'fecha': None, 'total': None, 'moneda': None},
        'usage': {'total_tokens': 30}, 'requires_review': True})
    with TestClient(create_app(tmp_path)) as client:
        doc_id = client.post('/documents', files={'file': ('factura.txt', b'Factura')}).json()['id']
        url = f'/documents/{doc_id}/extract'
        assert client.post(url).json()['cached'] is False
        assert client.post(url).json()['cached'] is True
        assert client.get('/usage').json()['generation']['attempts'] == 1
        second = client.post('/documents', files={'file': ('otra.txt', b'Factura')}).json()['id']
        assert client.post(f'/documents/{second}/extract').status_code == 429
