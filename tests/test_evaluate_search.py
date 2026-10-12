import httpx
import pytest
from app.evaluate_search import evaluate


def test_metrics_include_missing_and_http_failures():
    def handle(request):
        query = request.url.params['q']
        if query == 'error':
            return httpx.Response(429, json={'detail': 'quota'})
        filenames = ['other.txt', 'expected.txt'] if query == 'hit' else []
        return httpx.Response(200, json={'sources': [{'filename': f} for f in filenames]})
    cases = [dict(query=q, expected_filename='expected.txt') for q in ['hit', 'miss', 'error']]
    with httpx.Client(base_url='http://test', transport=httpx.MockTransport(handle)) as client:
        report = evaluate(client, cases, ['lexical'], 3)['results'][0]
    assert report['hit_rate'] == pytest.approx(1/3)
    assert report['mrr'] == pytest.approx(1/6)
    assert report['errors'] == 1
    assert report['cases'][0]['rank'] == 2
