# RAG con recuperación en Azure AI Search Free

Servicio search-ai200-418352 en North Europe, nivel Free, autenticación RBAC sin claves.
Índice document-chunks-v1: un registro por fragmento con clave determinista id-fragmento.
Tu usuario tiene Search Service Contributor y Search Index Data Contributor.

Desde document-lab, con la sesión az login activa y dependencias instaladas:

```powershell
$env:STORAGE_BACKEND = "local"
$env:DATA_DIR = "data-queue"
$env:SEARCH_BACKEND = "azure"
$env:AZURE_SEARCH_ENDPOINT = "https://search-ai200-418352.search.windows.net"
$env:AZURE_SEARCH_INDEX = "document-chunks-v1"
.\.venv\Scripts\python.exe -m app.azure_search
$env:AZURE_OPENAI_ENDPOINT = "https://ai200-modelo-418352.openai.azure.com"
$env:AZURE_OPENAI_DEPLOYMENT = "chat-practicas"
$env:ENABLE_AZURE_LLM = "true"
$env:LLM_DAILY_CALL_LIMIT = "20"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

GET /health confirma search_backend=azure (no comprueba conectividad remota).
Ejecuta POST /documents/{id}/index para subir los fragmentos a Search; los antiguos
no se migran solos. GET /retrieve recupera de Azure y /rag/ask genera con Azure OpenAI.
La visibilidad de los fragmentos puede tardar unos segundos después de indexarlos.
GET /search conserva la búsqueda local por documento: usa /retrieve para esta práctica.

Los originales, metadatos, cola y decisiones continúan en tu equipo. Esta fase mueve
solo la recuperación y generación a Azure, no despliega la API en ACA.
SEARCH_BACKEND=local restaura la recuperación SQLite. En modo Azure, indexar también
actualiza la copia local; no hay transacción entre Azure y SQLite ni fallback silencioso.
Un fallo puede dejar una carga parcial: repetir /index converge para originales
inmutables con la fragmentación v1 fija. Si cambias la fragmentación usa un índice nuevo;
no se eliminan automáticamente fragmentos antiguos. Máximo 1000 fragmentos y 8 MiB
por documento en esta práctica, sujeto también a la capacidad disponible del nivel Free.

Los documentos comparten índice: distintos DATA_DIR no aíslan sus resultados en Azure.
No hay filtro de autorización o aprobación; no es una configuración multiusuario.
La búsqueda usa palabras clave, AND y ranking textual; no usa embeddings ni semantic ranker.
El límite de gasto de inferencia conserva las limitaciones descritas en RAG.md.
