"""Modo Azure: originales en blobs; metadatos en blobs o Cosmos DB."""
import hashlib
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from app.metadata import BlobMetadata, CosmosMetadata

logger = logging.getLogger("document_lab")


def create_azure_app(document_model, analysis_model, max_bytes, container_client=None, metadata_store=None):
    metadata_backend = os.getenv("METADATA_BACKEND", "blob")
    if metadata_backend not in ("blob", "cosmos"):
        raise ValueError("METADATA_BACKEND debe ser blob o cosmos")

    @asynccontextmanager
    async def lifespan(app):
        if container_client is not None:
            app.state.container = container_client
            app.state.metadata = metadata_store or BlobMetadata(container_client)
            app.state.metadata.check()
            yield
            return
        account = os.environ.get("AZURE_STORAGE_ACCOUNT")
        if not account:
            raise RuntimeError("Configura AZURE_STORAGE_ACCOUNT para el modo Azure")
        credential = DefaultAzureCredential()
        service = BlobServiceClient(f"https://{account}.blob.core.windows.net", credential=credential)
        cosmos_client = None
        try:
            app.state.container = service.get_container_client(os.getenv("AZURE_STORAGE_CONTAINER", "documents"))
            # El contenedor y los permisos se aprovisionan antes de arrancar.
            app.state.container.get_container_properties()
            if metadata_backend == "cosmos":
                from azure.cosmos import CosmosClient
                endpoint = os.getenv("AZURE_COSMOS_ENDPOINT")
                if not endpoint:
                    raise RuntimeError("Configura AZURE_COSMOS_ENDPOINT para usar Cosmos DB")
                cosmos_client = CosmosClient(endpoint, credential=credential)
                database = cosmos_client.get_database_client(os.getenv("AZURE_COSMOS_DATABASE", "document-lab"))
                app.state.metadata = CosmosMetadata(database.get_container_client(os.getenv("AZURE_COSMOS_CONTAINER", "documents")))
            else:
                app.state.metadata = BlobMetadata(app.state.container)
            app.state.metadata.check()
            yield
        finally:
            if cosmos_client is not None:
                cosmos_client.close()
            service.close()
            credential.close()

    app = FastAPI(title="Document Lab · AI-200 · Azure", version="0.3.0",
                  description="Blob Storage privado. Análisis simulado. API sin autenticación: uso local de aprendizaje.",
                  lifespan=lifespan)

    @app.exception_handler(AzureError)
    async def storage_error(request, error):
        logger.error("storage_operation_failed type=%s", type(error).__name__)
        return JSONResponse(status_code=503, content={"detail": "Error de almacenamiento Azure. Revisa conectividad y permisos."})

    def blob(name):
        return app.state.container.get_blob_client(name)

    def fetch(document_id):
        try:
            return app.state.metadata.get(document_id)
        except ResourceNotFoundError:
            raise HTTPException(404, "Documento no encontrado")

    @app.get("/", include_in_schema=False)
    def home():
        return RedirectResponse("/docs")

    @app.get("/health", tags=["Sistema"])
    def health():
        app.state.container.get_container_properties()
        app.state.metadata.check()
        return {"status": "ok", "storage_backend": "azure", "metadata_backend": metadata_backend, "analysis_mode": "simulated"}

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
            # Original y metadatos se guardan sin una transacción conjunta.
            # No borrar aquí: un timeout podría ocurrir después de guardar los metadatos.
            app.state.metadata.create(item)
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
        return app.state.metadata.save_analysis(document_id, result.model_dump())

    return app
