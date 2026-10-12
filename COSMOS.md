# Fase 3 Metadatos en Cosmos DB

Esta fase está preparada para cuando Azure habilite la región. No cambia el
despliegue actual ni crea recursos automáticamente.

## Arquitectura

- Originales: Blob Storage `documents/originals/<id>`.
- Metadatos y análisis: un documento JSON en Cosmos DB for NoSQL.
- Clave de partición: `/id`. Las lecturas puntuales usan el mismo ID como valor de partición.
- Identidad: DefaultAzureCredential, sin claves en el código.
- Concurrencia: reemplazo condicional mediante ETag; un análisis concurrente no pisa el resultado ganador.

`app/metadata.py` separa BlobMetadata (modo anterior) de CosmosMetadata.
`app/azure_api.py` selecciona el repositorio al arrancar. Por defecto continúa
utilizando blobs. `app/main.py` conserva el modo local con SQLite.

## Pruebas sin cuenta de Cosmos DB

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:STORAGE_BACKEND = "local"
$env:METADATA_BACKEND = "blob"
.\.venv\Scripts\python.exe -m pytest -q
```

Las pruebas de Cosmos utilizan un doble en memoria del SDK. Comprueban rutas,
persistencia entre instancias de API, errores, clave de partición y concurrencia.
No sustituyen la prueba real de autenticación, permisos, red y consumo de RU.

## Conexión real cuando exista la cuenta

Primero crea `document-lab/documents` con partición `/id`. Da a tu usuario y
a `id-document-lab` el rol de datos Cosmos DB Built-in Data Contributor mediante
`az cosmosdb sql role assignment create`, con alcance `/dbs/document-lab/colls/documents`.
Es RBAC de datos de Cosmos: el rol Azure Contributor por sí solo no basta.
Mantén también el permiso existente de Blob Storage.

Después configura la API local (sustituye ambos nombres):

```powershell
$env:STORAGE_BACKEND = "azure"
$env:METADATA_BACKEND = "cosmos"
$env:AZURE_STORAGE_ACCOUNT = "TU_CUENTA_STORAGE"
$env:AZURE_COSMOS_ENDPOINT = "https://TU_CUENTA_COSMOS.documents.azure.com:443/"
$env:AZURE_COSMOS_DATABASE = "document-lab"
$env:AZURE_COSMOS_CONTAINER = "documents"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Usa `az login` para tu sesión local. Si heredaste AZURE_CLIENT_ID del despliegue,
no representa tu identidad local; DefaultAzureCredential podrá usar Azure CLI.
En ACA mantén AZURE_CLIENT_ID de la identidad administrada.

Health debe mostrar `metadata_backend: cosmos`. Sube un documento NUEVO, analízalo,
reinicia y vuelve a consultarlo. Verifica el JSON en Cosmos y el original en Blob Storage.

No se migran automáticamente los documentos previos. Si cambias el backend, los IDs
del backend anterior no aparecen; sus datos se conservan. Usa `METADATA_BACKEND=blob`
para volver a acceder a ellos.

Archivo y registro Cosmos no forman una transacción: un fallo de subida puede
dejar un original huérfano. La idempotencia de subida y reconciliación siguen pendientes.
El análisis sigue siendo simulado. No desplegar v3 hasta probar la conexión real.

## Conceptos de examen

Sigue `create_item`, `read_item` y `replace_item` en CosmosMetadata.
Observa cómo `/id` permite una lectura puntual, cómo `_etag` protege la escritura
y por qué Blob Storage y Cosmos DB tienen permisos independientes.
Consultas SQL, medición de RU, políticas de índices, change feed y vectores vendrán
en prácticas posteriores; esta fase solo prepara CRUD y concurrencia.
