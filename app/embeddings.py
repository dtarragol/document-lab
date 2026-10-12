"""Embeddings Azure con caché local y contador persistente de intentos."""
import hashlib
import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.azure_llm import post_azure

DIMENSIONS = 1536


def embed(texts):
    if os.getenv('ENABLE_AZURE_EMBEDDINGS', 'false').lower() != 'true':
        raise ValueError('Activa ENABLE_AZURE_EMBEDDINGS=true para llamadas facturables de embeddings')
    if not texts or len(texts) > 30 or any(not text.strip() or len(text) > 4000 for text in texts):
        raise ValueError('Admite de 1 a 30 textos, cada uno con un máximo de 4000 caracteres')
    if sum(map(len, texts)) > 60000:
        raise ValueError('El lote supera 60000 caracteres')
    deployment = os.getenv('AZURE_EMBEDDING_DEPLOYMENT', 'embeddings-practicas')
    namespace = os.getenv('AZURE_OPENAI_ENDPOINT', '') + '|' + deployment + f'|{DIMENSIONS}|'
    keys = [hashlib.sha256((namespace + text).encode()).hexdigest() for text in texts]
    root = Path(os.getenv('DATA_DIR', 'data')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(root / 'embeddings.db', timeout=30)
    try:
        connection.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, vector TEXT NOT NULL)')
        connection.execute('CREATE TABLE IF NOT EXISTS calls (day TEXT NOT NULL, usage TEXT)')
        connection.commit()
        cached = {}
        for key in set(keys):
            row = connection.execute('SELECT vector FROM cache WHERE key=?', (key,)).fetchone()
            if row:
                cached[key] = json.loads(row[0])
        missing = {key: text for key, text in zip(keys, texts) if key not in cached}
        if missing:
            day = datetime.now(timezone.utc).date().isoformat()
            limit = int(os.getenv('EMBEDDING_DAILY_CALL_LIMIT', '30'))
            connection.execute('BEGIN IMMEDIATE')
            count = connection.execute('SELECT COUNT(*) FROM calls WHERE day=?', (day,)).fetchone()[0]
            if count >= limit:
                connection.rollback()
                raise ValueError('Límite diario de embeddings alcanzado')
            row_id = connection.execute('INSERT INTO calls (day) VALUES (?)', (day,)).lastrowid
            connection.commit()
            result = post_azure(deployment, 'embeddings',
                                {'input': list(missing.values()), 'dimensions': DIMENSIONS, 'encoding_format': 'float'})
            data = sorted(result['data'], key=lambda item: item['index'])
            if [item['index'] for item in data] != list(range(len(missing))):
                raise ValueError('Respuesta de embeddings incompleta')
            for key, item in zip(missing, data):
                vector = item['embedding']
                if len(vector) != DIMENSIONS or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in vector):
                    raise ValueError('Vector con dimensiones o valores no válidos')
                cached[key] = vector
            with connection:
                connection.executemany('INSERT OR REPLACE INTO cache VALUES (?, ?)',
                                       [(key, json.dumps(cached[key])) for key in missing])
                connection.execute('UPDATE calls SET usage=? WHERE rowid=?',
                                   (json.dumps(result.get('usage', {})), row_id))
        return [cached[key] for key in keys]
    finally:
        connection.close()
