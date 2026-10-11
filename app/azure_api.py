"""Modo Azure: originales, metadatos y resultados en blobs privados.

No usa SQLite. Cada resultado es inmutable y se crea una sola vez.
"""
import hashlib
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

from azure.core.exceptions import AzureError, ResourceExistsError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse

logger = logging.getLogger("document_lab")


def create_azure_app(document_model, analysis_model, max_bytes, container_client=None):
    @asynccontextmanager
    async def lifespan(app):
        if container_client is not None:
            app.state.container = container_client
            yield
            return
        account = os.environ.get("AZURE_STORAGE_ACCOUNT")
        if not account:
            raise RuntimeError("Configura AZURE_STORAGE_ACCOUNT para el modo Azure")
        credential = DefaultAzureCredential()
        service = BlobServiceClient(f"https://{account}.blob.core.windows.net", credential=credential)
        try:
            app.state.container = service.get_container_client(os.getenv("AZURE_STORAGE_CONTAINER", "documents"))
            # El contenedor y los permisos se aprovisionan antes de arrancar.
            app.state.container.get_container_properties()
            yield
        finally:
            service.close()
            credential.close()

    app = FastAPI(title="Document Lab · AI-200 · Azure", version="0.2.0",
                  description="Blob Storage privado. Análisis simulado. API sin autenticación: uso local de aprendizaje.",
                  lifespan=lifespan)

    @app.exception_handler(AzureError)
    async def storage_error(request, error):
        logger.error("storage_operation_failed type=%s", type(error).__name__)
        return JSONResponse(status_code=503, content={"detail": "Error de almacenamiento Azure. Revisa conectividad y permisos."})

    def blob(name):
        return app.state.container.get_blob_client(name)

    def read_json(name):
        return json.loads(blob(name).download_blob().readall())

    def write_json(name, value):
        blob(name).upload_blob(json.dumps(value).encode("utf-8"), overwrite=False,
                               content_settings=ContentSettings(content_type="application/json"))

    def fetch(document_id):
        try:
            item = read_json(f"metadata/{document_id}.json")
        except ResourceNotFoundError:
            raise HTTPException(404, "Documento no encontrado")
        try:
            item["analysis"] = read_json(f"results/{document_id}.json")
            item["status"] = "Analyzed"
        except ResourceNotFoundError:
            pass
        return item

    @app.get("/", include_in_schema=False)
    def home():
        return RedirectResponse("/docs")

    @app.get("/health", tags=["Sistema"])
    def health():
        app.state.container.get_container_properties()
        return {"status": "ok", "storage_backend": "azure", "analysis_mode": "simulated"}

    @app.post("/documents", response_model=document_model, status_code=201, tags=["Documentos"])
    def upload(file: UploadFile = File(...)):
        document_id = str(uuid4())
        digest = hashlib.sha256()
        size = 0
        try:
            while chunk := file.file.read(64 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, "Documento demasiado grande")
                digest.update(chunk)
            if not size:
                raise HTTPException(400, "El documento está vacío")
            file.file.seek(0)
            item = {"id": document_id,
                    "filename": (file.filename or "document").replace("\\", "/").rsplit("/", 1)[-1],
                    "content_type": file.content_type or "application/octet-stream",
                    "size_bytes": size, "sha256": digest.hexdigest(),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "status": "Uploaded", "analysis": None}
            blob(f"originals/{document_id}").upload_blob(file.file, length=size, overwrite=False,
                content_settings=ContentSettings(content_type="application/octet-stream"))
            # Dos escrituras independientes: no hay transacción entre blobs.
            # No borrar aquí: un timeout podría ocurrir después de guardar los metadatos.
            write_json(f"metadata/{document_id}.json", item)
            logger.info("document_uploaded id=%s backend=azure", document_id)
            return item
        finally:
            file.file.close()

    @app.get("/documents/{document_id}", response_model=document_model, tags=["Documentos"])
    def get_document(document_id: UUID):
        return fetch(document_id)

    @app.post("/documents/{document_id}/analyze", response_model=document_model, tags=["Documentos"])
    def analyze(document_id: UUID):
        item = fetch(document_id)
        if item["analysis"] is not None:
            return item
        name = item["filename"].lower()
        result = analysis_model(category="invoice" if any(w in name for w in ("factura", "invoice")) else "other",
                                confidence=0.72, requires_review=True)
        try:
            write_json(f"results/{document_id}.json", result.model_dump())
        except ResourceExistsError:
            # Otra réplica puede haber creado el resultado: recuperar el ganador.
            pass
        return fetch(document_id)

    return app
