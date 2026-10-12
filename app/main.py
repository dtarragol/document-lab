"""Primera práctica AI-200: API local con persistencia y análisis simulado."""
import hashlib
import json
import logging
import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from app.text import TextError, analyze_text, extract_text
from app.retrieval import chunk_text, literal_query
from app.rag import prepare_messages

logger = logging.getLogger("document_lab")
logging.basicConfig(level=logging.INFO)
MAX_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))


class Analysis(BaseModel):
    category: str
    confidence: float
    requires_review: bool
    simulated: bool = True


class Document(BaseModel):
    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: str
    status: str
    analysis: Analysis | None = None


class ReviewRequest(BaseModel):
    decision: Literal['Approved', 'Rejected']


class RagRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    search_query: str = Field(min_length=1, max_length=200)
    top_k: int = Field(default=3, ge=1, le=10)
    retrieval_mode: Literal['lexical', 'vector', 'hybrid'] | None = None


def create_app(data_dir: Path | None = None) -> FastAPI:
    if data_dir is None and os.getenv("STORAGE_BACKEND", "local") == "azure":
        from app.azure_api import create_azure_app
        return create_azure_app(Document, Analysis, MAX_BYTES)
    root = Path(data_dir or os.getenv("DATA_DIR", "data")).resolve()
    search_backend = os.getenv('SEARCH_BACKEND', 'local')
    if search_backend not in ('local', 'azure'):
        raise ValueError('SEARCH_BACKEND debe ser local o azure')

    def search_operation(operation, *args):
        import httpx
        from azure.core.exceptions import AzureError
        try:
            return operation(*args)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            detail = f'Azure devolvió HTTP {status}. '
            if status == 429:
                detail += 'Cuota temporal alcanzada; espera antes de volver a intentarlo.'
            elif status in (401, 403):
                detail += 'Revisa az login y los permisos del recurso.'
            elif status == 404:
                detail += 'Comprueba el nombre del índice o del despliegue del modelo.'
            else:
                detail += 'Revisa que el esquema del índice coincida con la configuración.'
            logger.warning('azure_search_failed status=%s', status)
            raise HTTPException(429 if status == 429 else 503, detail) from error
        except (httpx.HTTPError, AzureError, ValueError, RuntimeError, KeyError) as error:
            logger.warning('azure_search_failed type=%s', type(error).__name__)
            raise HTTPException(503, 'Error de Azure Search: revisa índice, permisos, tamaño y conectividad') from error

    @contextmanager
    def database():
        connection = sqlite3.connect(root / "documents.db", timeout=30)
        try:
            connection.row_factory = sqlite3.Row
            with connection:
                yield connection
        finally:
            connection.close()

    @asynccontextmanager
    async def lifespan(app):
        (root / "files").mkdir(parents=True, exist_ok=True)
        with database() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, filename TEXT NOT NULL,
                content_type TEXT NOT NULL, size_bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
                status TEXT NOT NULL, analysis TEXT)""")
            connection.execute("""CREATE TABLE IF NOT EXISTS jobs (
                document_id TEXT PRIMARY KEY, status TEXT NOT NULL)""")
            columns = {row['name'] for row in connection.execute('PRAGMA table_info(jobs)')}
            if 'attempts' not in columns:
                connection.execute('ALTER TABLE jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0')
            if 'last_error' not in columns:
                connection.execute('ALTER TABLE jobs ADD COLUMN last_error TEXT')
            connection.execute('''CREATE TABLE IF NOT EXISTS reviews (
                document_id TEXT PRIMARY KEY, decision TEXT NOT NULL, decided_at TEXT NOT NULL)''')
            connection.execute('''CREATE VIRTUAL TABLE IF NOT EXISTS document_search
                USING fts5(document_id UNINDEXED, content, tokenize='unicode61')''')
            connection.execute('''CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks
                USING fts5(document_id UNINDEXED, chunk_number UNINDEXED, content, tokenize='unicode61')''')
            connection.execute('''CREATE TABLE IF NOT EXISTS llm_calls (
                id TEXT PRIMARY KEY, day TEXT NOT NULL, status TEXT NOT NULL, usage TEXT)''')
        yield

    app = FastAPI(title="Document Lab · AI-200", version="0.1.0",
                  description="API de aprendizaje. Análisis simulado, sin llamadas a IA. "
                              "Uso local sin autenticación.", lifespan=lifespan)

    def fetch(document_id: UUID):
        with database() as connection:
            row = connection.execute("SELECT * FROM documents WHERE id = ?",
                                     (str(document_id),)).fetchone()
        if row is None:
            raise HTTPException(404, "Documento no encontrado")
        item = dict(row)
        item["analysis"] = json.loads(item["analysis"]) if item["analysis"] else None
        return item

    @app.get("/", include_in_schema=False)
    def home():
        return RedirectResponse("/docs")

    @app.get("/health", tags=["Sistema"])
    def health():
        with database() as connection:
            connection.execute("SELECT 1").fetchone()
        return {"status": "ok", "analysis_mode": "simulated", "search_backend": search_backend}

    @app.post("/documents", response_model=Document, status_code=201, tags=["Documentos"])
    def upload(file: UploadFile = File(...)):
        document_id = uuid4()
        target = root / "files" / str(document_id)
        # El nombre del usuario es solo metadato, nunca una ruta de almacenamiento.
        filename = (file.filename or "document").replace("\\", "/").rsplit("/", 1)[-1]
        digest = hashlib.sha256()
        size = 0
        try:
            with target.open("xb") as output:
                while chunk := file.file.read(64 * 1024):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise HTTPException(413, "Documento demasiado grande")
                    digest.update(chunk)
                    output.write(chunk)
            if size == 0:
                raise HTTPException(400, "El documento está vacío")
            with database() as connection:
                connection.execute("INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(document_id), filename, file.content_type or "application/octet-stream",
                     size, digest.hexdigest(), datetime.now(timezone.utc).isoformat(), "Uploaded", None))
        except Exception:
            target.unlink(missing_ok=True)
            raise
        finally:
            file.file.close()
        logger.info("document_uploaded id=%s bytes=%s", document_id, size)
        return fetch(document_id)

    @app.get("/documents/{document_id}", response_model=Document, tags=["Documentos"])
    def get_document(document_id: UUID):
        return fetch(document_id)

    @app.post("/documents/{document_id}/analyze", response_model=Document, tags=["Documentos"])
    def analyze(document_id: UUID):
        document = fetch(document_id)
        # Repetir esta operación devuelve el resultado existente.
        if document["analysis"] is not None:
            return document
        try:
            text = extract_text(root / 'files' / str(document_id), document['filename'])
        except TextError as error:
            raise HTTPException(422, str(error)) from error
        result = Analysis(**analyze_text(text))
        with database() as connection:
            if connection.execute("SELECT 1 FROM jobs WHERE document_id=? AND status='Pending'",
                                  (str(document_id),)).fetchone():
                raise HTTPException(409, "Análisis en cola: ejecuta el worker")
            connection.execute("UPDATE documents SET status = ?, analysis = ? WHERE id = ? AND analysis IS NULL",
                               ("Analyzed", result.model_dump_json(), str(document_id)))
        logger.info("document_analyzed id=%s simulated=true", document_id)
        return fetch(document_id)

    @app.post("/documents/{document_id}/enqueue", status_code=202, tags=["Cola local"])
    def enqueue(document_id: UUID):
        fetch(document_id)
        with database() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT analysis FROM documents WHERE id=?', (str(document_id),)).fetchone()
            if row['analysis'] is not None:
                return {"document_id": str(document_id), "status": "AlreadyAnalyzed"}
            job = connection.execute('SELECT status FROM jobs WHERE document_id=?', (str(document_id),)).fetchone()
            if job and job['status'] == 'DeadLetter':
                raise HTTPException(409, 'Trabajo en cola de errores; revisa GET /jobs/{document_id}')
            connection.execute("INSERT OR IGNORE INTO jobs (document_id, status) VALUES (?, 'Pending')", (str(document_id),))
            connection.execute("UPDATE documents SET status='Queued' WHERE id=?", (str(document_id),))
        return {"document_id": str(document_id), "status": "Pending"}

    @app.get('/documents/{document_id}/text', tags=['Extracción local'])
    def get_text(document_id: UUID):
        document = fetch(document_id)
        try:
            text = extract_text(root / 'files' / str(document_id), document['filename'])
        except TextError as error:
            raise HTTPException(422, str(error)) from error
        return {'document_id': str(document_id), 'characters': len(text),
                'text': text[:4000], 'truncated': len(text) > 4000}

    @app.get('/jobs/{document_id}', tags=['Cola local'])
    def get_job(document_id: UUID):
        with database() as connection:
            row = connection.execute('SELECT * FROM jobs WHERE document_id=?', (str(document_id),)).fetchone()
        if row is None:
            raise HTTPException(404, 'Trabajo no encontrado')
        return dict(row)

    @app.post('/documents/{document_id}/index', tags=['Indexación'])
    def index_document(document_id: UUID):
        document = fetch(document_id)
        try:
            text = extract_text(root / 'files' / str(document_id), document['filename'])
        except TextError as error:
            raise HTTPException(422, str(error)) from error
        chunks = chunk_text(text)
        if search_backend == 'azure':
            from app.azure_search import index_chunks
            search_operation(index_chunks, str(document_id), document['filename'], chunks)
        with database() as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('DELETE FROM document_search WHERE document_id=?', (str(document_id),))
            connection.execute('INSERT INTO document_search (document_id, content) VALUES (?, ?)',
                               (str(document_id), text))
            connection.execute('DELETE FROM document_chunks WHERE document_id=?', (str(document_id),))
            connection.executemany('INSERT INTO document_chunks (document_id, chunk_number, content) VALUES (?, ?, ?)',
                                   [(str(document_id), number, chunk) for number, chunk in enumerate(chunks)])
        return {'document_id': str(document_id), 'indexed_characters': len(text), 'chunks': len(chunks),
                'search_backend': search_backend}

    @app.get('/search', tags=['Búsqueda local'])
    def search(q: str = Query(min_length=1, max_length=200), limit: int = Query(default=10, ge=1, le=50)):
        # Cada término es literal: no exponemos operadores ni sintaxis de FTS al usuario.
        try:
            expression = literal_query(q)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        with database() as connection:
            rows = connection.execute('''SELECT d.id, d.filename,
                snippet(document_search, 1, '[', ']', '...', 32) AS excerpt
                FROM document_search JOIN documents d ON d.id=document_search.document_id
                WHERE document_search MATCH ? ORDER BY bm25(document_search), d.id LIMIT ?''',
                (expression, limit)).fetchall()
        return {'query': q, 'count': len(rows), 'results': [dict(row) for row in rows]}

    @app.get('/retrieve', tags=['Recuperación'])
    def retrieve(q: str = Query(min_length=1, max_length=200), top_k: int = Query(default=3, ge=1, le=10),
                 mode: Literal['lexical', 'vector', 'hybrid'] | None = None):
        try:
            expression = literal_query(q)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        if search_backend == 'azure':
            from app.azure_search import retrieve_chunks
            sources = search_operation(retrieve_chunks, q, top_k) if mode is None else search_operation(retrieve_chunks, q, top_k, mode)
            return {'query': q, 'count': len(sources), 'sources': sources,
                    'retrieval_mode': 'azure_' + (mode or os.getenv('AZURE_SEARCH_MODE', 'lexical')), 'generated_answer': None}
        if mode not in (None, 'lexical'):
            raise HTTPException(422, 'La búsqueda vectorial requiere SEARCH_BACKEND=azure')
        with database() as connection:
            rows = connection.execute('''SELECT d.id AS document_id, d.filename,
                CAST(document_chunks.chunk_number AS INTEGER) AS chunk_number,
                document_chunks.content AS text
                FROM document_chunks JOIN documents d ON d.id=document_chunks.document_id
                WHERE document_chunks MATCH ?
                ORDER BY bm25(document_chunks), d.id, CAST(document_chunks.chunk_number AS INTEGER) LIMIT ?''',
                (expression, top_k)).fetchall()
        return {'query': q, 'count': len(rows), 'sources': [dict(row) for row in rows],
                'retrieval_mode': 'lexical', 'generated_answer': None}

    @app.post('/rag/prepare', tags=['RAG local'])
    def prepare_rag(request: RagRequest):
        if not request.question.strip():
            raise HTTPException(422, 'Introduce una pregunta')
        retrieved = retrieve(request.search_query, request.top_k, request.retrieval_mode)
        return prepare_messages(request.question, retrieved['sources'])

    @app.post('/rag/ask', tags=['RAG con Azure'])
    def ask_rag(request: RagRequest):
        from app.azure_llm import generate
        import httpx
        from azure.core.exceptions import AzureError
        if os.getenv('ENABLE_AZURE_LLM', 'false').lower() != 'true':
            raise HTTPException(503, 'Activa ENABLE_AZURE_LLM=true para realizar llamadas facturables')
        if request.top_k > 3:
            raise HTTPException(422, 'Esta práctica admite como máximo 3 fragmentos por llamada al modelo')
        context = prepare_rag(request)
        if not context['sources']:
            return {'answer': 'No se han encontrado fuentes para responder.', 'sources': [], 'status': 'no_sources', 'usage': {}}
        if sum(len(message['content']) for message in context['messages']) > 12000:
            raise HTTPException(422, 'Contexto demasiado largo: reduce top_k o utiliza fragmentos más cortos')
        try:
            limit = int(os.getenv('LLM_DAILY_CALL_LIMIT', '20'))
        except ValueError:
            raise HTTPException(503, 'LLM_DAILY_CALL_LIMIT debe ser un entero')
        call_id = str(uuid4())
        day = datetime.now(timezone.utc).date().isoformat()
        with database() as connection:
            connection.execute('BEGIN IMMEDIATE')
            count = connection.execute('SELECT COUNT(*) FROM llm_calls WHERE day=?', (day,)).fetchone()[0]
            if count >= limit:
                raise HTTPException(429, 'Límite diario de llamadas alcanzado')
            connection.execute('INSERT INTO llm_calls VALUES (?, ?, ?, NULL)', (call_id, day, 'Reserved'))
        try:
            result = generate(context['messages'])
        except (ValueError, AzureError, httpx.HTTPError, KeyError, IndexError) as error:
            with database() as connection:
                connection.execute("UPDATE llm_calls SET status='Failed' WHERE id=?", (call_id,))
            logger.warning('llm_call_failed id=%s type=%s', call_id, type(error).__name__)
            raise HTTPException(503, 'Falló la llamada al modelo: revisa endpoint, az login, permisos y cuota') from error
        with database() as connection:
            connection.execute("UPDATE llm_calls SET status='Completed', usage=? WHERE id=?",
                               (json.dumps(result['usage']), call_id))
        return dict(result, sources=context['sources'], status='generated', call_id=call_id)

    @app.post('/documents/{document_id}/review', tags=['Revisión humana local'])
    def review(document_id: UUID, request: ReviewRequest):
        with database() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT analysis FROM documents WHERE id=?', (str(document_id),)).fetchone()
            if row is None:
                raise HTTPException(404, 'Documento no encontrado')
            if row['analysis'] is None:
                raise HTTPException(409, 'Primero debes analizar el documento')
            existing = connection.execute('SELECT * FROM reviews WHERE document_id=?', (str(document_id),)).fetchone()
            if existing:
                if existing['decision'] != request.decision:
                    raise HTTPException(409, 'El documento ya tiene una decisión diferente')
                return dict(existing)
            result = dict(document_id=str(document_id), decision=request.decision,
                          decided_at=datetime.now(timezone.utc).isoformat())
            connection.execute('INSERT INTO reviews VALUES (?, ?, ?)', tuple(result.values()))
        return result

    @app.get('/documents/{document_id}/review', tags=['Revisión humana local'])
    def get_review(document_id: UUID):
        fetch(document_id)
        with database() as connection:
            row = connection.execute('SELECT * FROM reviews WHERE document_id=?', (str(document_id),)).fetchone()
        if row is None:
            return {'document_id': str(document_id), 'decision': 'Pending', 'decided_at': None}
        return dict(row)

    @app.post('/jobs/{document_id}/retry', status_code=202, tags=['Cola local'])
    def retry_job(document_id: UUID):
        with database() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT status FROM jobs WHERE document_id=?', (str(document_id),)).fetchone()
            if row is None:
                raise HTTPException(404, 'Trabajo no encontrado')
            if row['status'] != 'DeadLetter':
                raise HTTPException(409, 'Solo se pueden recuperar trabajos en DeadLetter')
            document = connection.execute('SELECT analysis FROM documents WHERE id=?', (str(document_id),)).fetchone()
            if document is None or document['analysis'] is not None:
                raise HTTPException(409, 'El documento no existe o ya está analizado')
            connection.execute("UPDATE jobs SET status='Pending', attempts=0, last_error=NULL WHERE document_id=?",
                               (str(document_id),))
            connection.execute("UPDATE documents SET status='Queued' WHERE id=?", (str(document_id),))
        return {'document_id': str(document_id), 'status': 'Pending'}

    return app


app = create_app()
