import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.retrieval import chunk_text


def test_chunks_overlap_and_termination():
    words = [str(i) for i in range(250)]
    chunks = chunk_text(' '.join(words))
    assert len(chunks) == 3
    assert chunks[0].split()[-20:] == chunks[1].split()[:20]
    assert chunks[-1].split()[-1] == '249'
    assert len(chunk_text(' '.join(words[:120]))) == 1
    assert chunk_text('  ') == []
    with pytest.raises(ValueError):
        chunk_text('text', overlap=120)


def test_retrieve_chunks_reindex_and_restart(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        text = ' '.join(['inicio'] * 150 + ['Cosmos', 'particiones'] + ['final'] * 150)
        doc_id = client.post('/documents', files={'file': ('tema.txt', text.encode())}).json()['id']
        for _ in range(2):
            assert client.post(f'/documents/{doc_id}/index').json()['chunks'] == 3
        result = client.get('/retrieve', params={'q': 'Cosmos particiones'}).json()
        assert result['count'] == 1
        assert result['generated_answer'] is None
        source = result['sources'][0]
        assert source['document_id'] == doc_id
        assert source['chunk_number'] == 1
        assert 'Cosmos particiones' in source['text']
        assert client.get('/retrieve', params={'q': 'ausente'}).json()['sources'] == []
        assert client.get('/retrieve', params={'q': '   '}).status_code == 422
        assert client.get('/retrieve', params={'q': 'Cosmos', 'top_k': 11}).status_code == 422
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/retrieve', params={'q': 'Cosmos'}).json()['count'] == 1
