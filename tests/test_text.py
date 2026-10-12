from io import BytesIO
from zipfile import ZipFile
from fastapi.testclient import TestClient
from app.main import create_app
from app.worker import process_one


def test_content_and_docx_extraction(tmp_path):
    content = BytesIO()
    with ZipFile(content, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Factura total 100 EUR</w:t></w:r></w:p></w:body></w:document>')
    with TestClient(create_app(tmp_path)) as client:
        doc_id = client.post('/documents', files={'file': ('neutral.docx', content.getvalue())}).json()['id']
        url = f'/documents/{doc_id}'
        assert client.get(url + '/text').json()['text'] == 'Factura total 100 EUR'
        assert client.post(url + '/analyze').json()['analysis']['category'] == 'invoice'
        other = client.post('/documents', files={'file': ('factura.txt', b'reunion del equipo')}).json()['id']
        assert client.post(f'/documents/{other}/analyze').json()['analysis']['category'] == 'other'


def test_invalid_docx_goes_to_dead_letter(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        doc_id = client.post('/documents', files={'file': ('broken.docx', b'not a zip')}).json()['id']
        url = f'/documents/{doc_id}'
        assert client.get(url + '/text').status_code == 422
        assert client.post(url + '/analyze').status_code == 422
        client.post(url + '/enqueue')
        for _ in range(3):
            assert process_one(tmp_path)
        job = client.get(f'/jobs/{doc_id}').json()
        assert job['status'] == 'DeadLetter'
        assert 'leer el documento' in job['last_error']
