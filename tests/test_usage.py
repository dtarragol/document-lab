import json
import sqlite3
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from app.main import create_app


def test_usage_totals_failures_and_previous_days(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('LLM_DAILY_CALL_LIMIT', '2')
    day = datetime.now(timezone.utc).date().isoformat()
    with TestClient(create_app(tmp_path)) as client:
        initial = client.get('/usage').json()
        assert initial['generation']['attempts'] == 0
        assert initial['embeddings']['attempts'] == 0
        with sqlite3.connect(tmp_path / 'documents.db') as connection:
            connection.executemany('INSERT INTO llm_calls VALUES (?, ?, ?, ?)', [
                ('one', day, 'Completed', json.dumps({'total_tokens': 100})),
                ('two', day, 'Failed', None),
                ('old', '2000-01-01', 'Completed', json.dumps({'total_tokens': 1000}))])
        with sqlite3.connect(tmp_path / 'embeddings.db') as connection:
            connection.execute('CREATE TABLE calls (day TEXT, usage TEXT)')
            connection.execute('INSERT INTO calls VALUES (?, ?)', (day, json.dumps({'total_tokens': 25})))
        result = client.get('/usage').json()
        assert result['generation']['attempts'] == 2
        assert result['generation']['remaining_attempts'] == 0
        assert result['generation']['reported_total_tokens'] == 100
        assert result['generation']['attempts_without_token_usage'] == 1
        assert result['embeddings']['reported_total_tokens'] == 25
        assert result['azure_invoice'] is None
