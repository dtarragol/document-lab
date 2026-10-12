"""Práctica completa aislada: python -m app.demo (dependencias de desarrollo)."""
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from app.main import create_app


def main():
    with TemporaryDirectory(prefix='document-lab-demo-') as folder:
        root = Path(folder)
        environment = dict(os.environ, STORAGE_BACKEND='local', DATA_DIR=str(root))
        with TestClient(create_app(root)) as client:
            cases = [
                ('documento-a.txt', 'Factura 2026-001. Total: 120 EUR.', 'invoice', 'Approved'),
                ('factura-b.txt', 'Acta de la reunion semanal del equipo.', 'other', 'Rejected'),
            ]
            documents = []
            for filename, text, category, decision in cases:
                response = client.post('/documents', files={'file': (filename, text.encode(), 'text/plain')})
                response.raise_for_status()
                doc_id = response.json()['id']
                response = client.post(f'/documents/{doc_id}/enqueue')
                response.raise_for_status()
                documents.append((doc_id, filename, category, decision))
            print('\n1. API: dos documentos subidos y encolados.', flush=True)
            print('2. Worker: procesamiento en procesos Python separados.', flush=True)
            for _ in documents:
                subprocess.run([sys.executable, '-m', 'app.worker', '--once'],
                               env=environment, cwd=Path(__file__).resolve().parents[1],
                               check=True, timeout=30)
            print('\n3. Comprobación del análisis y registro de decisiones:', flush=True)
            for doc_id, filename, category, decision in documents:
                response = client.get(f'/documents/{doc_id}')
                response.raise_for_status()
                document = response.json()
                if document['status'] != 'Analyzed' or document['analysis']['category'] != category:
                    raise RuntimeError(f'Resultado inesperado: {document}')
                response = client.post(f'/documents/{doc_id}/review', json={'decision': decision})
                response.raise_for_status()
                print(f'   {filename}: {category} -> {response.json()["decision"]}', flush=True)
        print('\n4. Reinicio de la API y verificación de persistencia:', flush=True)
        with TestClient(create_app(root)) as client:
            for doc_id, filename, _, decision in documents:
                response = client.get(f'/documents/{doc_id}/review')
                response.raise_for_status()
                if response.json()['decision'] != decision:
                    raise RuntimeError('La decisión no se ha conservado')
                print(f'   {filename}: decisión conservada.', flush=True)
        print('\nPráctica completada. Datos temporales eliminados al salir; tus datos habituales no cambian.', flush=True)


if __name__ == '__main__':
    main()
