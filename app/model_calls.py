"""Contador diario compartido por RAG y extracción."""
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from azure.core.exceptions import AzureError
from fastapi import HTTPException


def call_model(root, operation, *args):
    if os.getenv('ENABLE_AZURE_LLM', 'false').lower() != 'true':
        raise HTTPException(503, 'Activa ENABLE_AZURE_LLM=true para realizar llamadas facturables')
    try:
        limit = int(os.getenv('LLM_DAILY_CALL_LIMIT', '20'))
    except ValueError:
        raise HTTPException(503, 'LLM_DAILY_CALL_LIMIT debe ser un entero')
    call_id = str(uuid4())
    day = datetime.now(timezone.utc).date().isoformat()
    connection = sqlite3.connect(root / 'documents.db', timeout=30)
    try:
        with connection:
            connection.execute('BEGIN IMMEDIATE')
            count = connection.execute('SELECT COUNT(*) FROM llm_calls WHERE day=?', (day,)).fetchone()[0]
            if count >= limit:
                raise HTTPException(429, 'Límite diario de llamadas alcanzado')
            connection.execute('INSERT INTO llm_calls VALUES (?, ?, ?, NULL)', (call_id, day, 'Reserved'))
        try:
            result = operation(*args)
        except (ValueError, AzureError, httpx.HTTPError, KeyError, IndexError) as error:
            with connection:
                connection.execute("UPDATE llm_calls SET status='Failed' WHERE id=?", (call_id,))
            logging.getLogger('document_lab').warning('llm_call_failed id=%s type=%s', call_id, type(error).__name__)
            raise HTTPException(503, 'Falló la llamada al modelo: revisa endpoint, az login, permisos y cuota') from error
        with connection:
            connection.execute("UPDATE llm_calls SET status='Completed', usage=? WHERE id=?",
                               (json.dumps(result.get('usage', {})), call_id))
        return dict(result, call_id=call_id)
    finally:
        connection.close()
