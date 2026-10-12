import httpx
from app.compare_search import compare


def test_comparison_only_calls_retrieval_and_preserves_sources():
    modes = []
    def handler(request):
        assert request.method == 'GET'
        assert request.url.path == '/retrieve'
        mode = request.url.params['mode']
        modes.append(mode)
        if mode == 'lexical':
            return httpx.Response(200, json={'sources': [], 'retrieval_mode': 'azure_lexical'})
        if mode == 'vector':
            return httpx.Response(429, json={'detail': 'Quota reached'})
        return httpx.Response(200, json={'sources': [{'document_id': 'id', 'filename': 'tema.txt',
            'chunk_number': 0, 'text': 'texto completo'}], 'retrieval_mode': 'azure_hybrid'})
    with httpx.Client(base_url='http://localhost', transport=httpx.MockTransport(handler)) as client:
        result = compare(client, 'significado parecido', 3)
    assert modes == ['lexical', 'vector', 'hybrid']
    assert result['results'][0]['sources'] == []
    assert result['results'][1]['http_status'] == 429
    assert result['results'][2]['sources'][0]['text'] == 'texto completo'
