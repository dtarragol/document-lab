"""Cola local persistente. Ejecutar: python -m app.worker --once."""
import argparse
import json
import os
import sqlite3
import time
from pathlib import Path


def process_one(root: Path, simulate_failure: bool = False) -> bool:
    connection = sqlite3.connect(root / 'documents.db', timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        # Solo para este análisis simulado y breve: trabajo y confirmación atómicos.
        # Un fallo antes del commit revierte todo y deja el mensaje pendiente.
        connection.execute('BEGIN IMMEDIATE')
        job = connection.execute("SELECT document_id, attempts FROM jobs WHERE status='Pending' ORDER BY attempts, rowid LIMIT 1").fetchone()
        if job is None:
            connection.rollback()
            return False
        doc_id = job['document_id']
        if simulate_failure:
            attempts = job['attempts'] + 1
            status = 'DeadLetter' if attempts >= 3 else 'Pending'
            connection.execute('UPDATE jobs SET attempts=?, status=?, last_error=? WHERE document_id=?',
                               (attempts, status, 'Fallo simulado de análisis', doc_id))
            connection.execute('UPDATE documents SET status=? WHERE id=?',
                               ('Failed' if status == 'DeadLetter' else 'Queued', doc_id))
            connection.commit()
            print(f'Fallo simulado: {doc_id}, intento={attempts}, estado={status}', flush=True)
            return True
        document = connection.execute('SELECT filename, analysis FROM documents WHERE id=?', (doc_id,)).fetchone()
        if document['analysis'] is None:
            name = document['filename'].lower()
            result = dict(category='invoice' if any(w in name for w in ('invoice', 'factura')) else 'other',
                          confidence=0.72, requires_review=True, simulated=True)
            connection.execute("UPDATE documents SET status='Analyzed', analysis=? WHERE id=?",
                               (json.dumps(result), doc_id))
        connection.execute("UPDATE jobs SET status='Completed', attempts=attempts+1, last_error=NULL WHERE document_id=?", (doc_id,))
        connection.commit()
        print(f'Trabajo completado: {doc_id}', flush=True)
        return True
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description='Worker local de análisis simulado')
    parser.add_argument('--once', action='store_true', help='Procesar como máximo un trabajo y salir')
    parser.add_argument('--simulate-failure', action='store_true', help='Provocar un fallo controlado en el siguiente trabajo (requiere --once)')
    args = parser.parse_args()
    if args.simulate_failure and not args.once:
        parser.error('--simulate-failure requiere --once para observar cada intento')
    if os.getenv('STORAGE_BACKEND', 'local') != 'local':
        parser.error('Esta práctica necesita STORAGE_BACKEND=local')
    root = Path(os.getenv('DATA_DIR', 'data')).resolve()
    if not (root / 'documents.db').exists():
        parser.error('Arranca primero la API local para crear la base de datos')
    if args.once:
        process_one(root, simulate_failure=args.simulate_failure)
    else:
        try:
            while True:
                if not process_one(root):
                    time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
