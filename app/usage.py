"""Resumen de los contadores locales; no consulta la factura de Azure."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _rows(path, sql, day):
    if not path.exists():
        return []
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=30)
    try:
        table = 'llm_calls' if path.name == 'documents.db' else 'calls'
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            return []
        return connection.execute(sql, (day,)).fetchall()
    finally:
        connection.close()


def _summarize(rows, limit):
    reported_tokens = 0
    with_usage = 0
    states = {}
    for state, raw_usage in rows:
        states[state] = states.get(state, 0) + 1
        if raw_usage:
            usage = json.loads(raw_usage)
            if 'total_tokens' in usage:
                reported_tokens += usage['total_tokens']
                with_usage += 1
    return dict(attempts=len(rows), daily_limit=limit, remaining_attempts=max(0, limit - len(rows)),
                reported_total_tokens=reported_tokens, attempts_with_token_usage=with_usage,
                attempts_without_token_usage=len(rows) - with_usage, states=states)


def daily_usage(root: Path):
    day = datetime.now(timezone.utc).date().isoformat()
    generation = _rows(root / 'documents.db', 'SELECT status, usage FROM llm_calls WHERE day=?', day)
    embeddings_root = Path(os.getenv('DATA_DIR', 'data')).resolve()
    embeddings = _rows(embeddings_root / 'embeddings.db',
                       "SELECT CASE WHEN usage IS NULL THEN 'Unreported' ELSE 'Completed' END, usage FROM calls WHERE day=?", day)
    return {'day_utc': day, 'scope': 'local_application_counters',
            'generation': _summarize(generation, int(os.getenv('LLM_DAILY_CALL_LIMIT', '20'))),
            'embeddings': _summarize(embeddings, int(os.getenv('EMBEDDING_DAILY_CALL_LIMIT', '30'))),
            'azure_invoice': None,
            'note': 'Solo incluye intentos registrados en estas bases locales. No es la factura de Azure; '
                    'los intentos sin usage pueden haber generado consumo. Los aciertos de caché no cuentan como llamadas.'}
