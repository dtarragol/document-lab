"""Primera práctica AI-200: API local con persistencia y análisis simulado."""
import hashlib
import json
import logging
import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

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


def create_app(data_dir: Path | None = None) -> FastAPI:
    if data_dir is None and os.getenv("STORAGE_BACKEND", "local") == "azure":
        from app.azure_api import create_azure_app
        return create_azure_app(Document, Analysis, MAX_BYTES)
    root = Path(data_dir or os.getenv("DATA_DIR", "data")).resolve()

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
        return {"status": "ok", "analysis_mode": "simulated"}

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
        name = document["filename"].lower()
        category = "invoice" if any(word in name for word in ("invoice", "factura")) else "other"
        result = Analysis(category=category, confidence=0.72, requires_review=True)
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
            connection.execute("INSERT OR IGNORE INTO jobs VALUES (?, 'Pending')", (str(document_id),))
            connection.execute("UPDATE documents SET status='Queued' WHERE id=?", (str(document_id),))
        return {"document_id": str(document_id), "status": "Pending"}

    return app


app = create_app()
