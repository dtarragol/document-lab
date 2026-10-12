# Búsqueda vectorial e híbrida en Azure

Se utiliza text-embedding-3-small (embeddings-practicas), 1536 dimensiones, mismo
modelo para fragmentos y consultas. Índice separado document-chunks-vector-v1,
HNSW con distancia coseno. El índice textual anterior permanece intacto.

Conserva las variables de la práctica RAG y añade, antes de arrancar la API:

```powershell
$env:SEARCH_BACKEND = "azure"
$env:AZURE_SEARCH_ENDPOINT = "https://search-ai200-418352.search.windows.net"
$env:AZURE_OPENAI_ENDPOINT = "https://ai200-modelo-418352.openai.azure.com"
$env:AZURE_SEARCH_INDEX = "document-chunks-vector-v1"
$env:AZURE_SEARCH_VECTORS = "true"
$env:ENABLE_AZURE_EMBEDDINGS = "true"
$env:AZURE_EMBEDDING_DEPLOYMENT = "embeddings-practicas"
$env:EMBEDDING_DAILY_CALL_LIMIT = "30"
$env:AZURE_SEARCH_MODE = "hybrid"
.\.venv\Scripts\python.exe -m app.azure_search
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Mantén STORAGE_BACKEND=local y DATA_DIR=data-queue. La API y la caché siguen locales.
Sube e indexa un documento pequeño: como máximo 30 fragmentos por documento en esta
práctica vectorial por lote, cada uno <=4000 caracteres, total por lote <=60000 caracteres.
Se divide automáticamente: máximo 120 fragmentos y 120000 caracteres por documento.
Un documento de 103 fragmentos necesita cuatro llamadas si cada lote cabe en el límite
de caracteres y aún no hay caché. Estos lotes consumen intentos del límite diario.
Se valida el tamaño completo antes de realizar llamadas.

GET /retrieve acepta mode=lexical, vector o hybrid. En /rag/ask y /rag/prepare usa
retrieval_mode con los mismos valores. Si se omite, usa AZURE_SEARCH_MODE.
La consulta vectorial admite frases naturales; la híbrida combina palabras y vectores.
La fusión de ranking la hace Azure Search. No se utiliza semantic ranker.

Embeddings se factura al indexar texto nuevo y al buscar consultas nuevas. La caché
embeddings.db reutiliza vectores para entradas idénticas, endpoint, despliegue y dimensiones.
El contador limita 30 intentos de API por día UTC, incluyendo fallos, no 30 textos ni euros.
No se comparte con las 20 llamadas de generación. Borrar la carpeta/base de datos reinicia
el contador. La caché no detecta cambios del modelo detrás del mismo despliegue: si cambias
modelo, utiliza otro nombre de despliegue e índice. No hay reintentos automáticos.

Una búsqueda vectorial puede devolver los vecinos más próximos aunque ninguno responda
la pregunta: top_k no es una garantía de relevancia. No hay umbral ni evaluación automática
de relevancia en esta fase. Compara las fuentes, no solo la respuesta del modelo.
Para volver al índice anterior: AZURE_SEARCH_INDEX=document-chunks-v1,
AZURE_SEARCH_VECTORS=false y AZURE_SEARCH_MODE=lexical. Reinicia la API.

## Comparar los tres modos automáticamente

Con la API Azure arrancada y documentos indexados en el índice vectorial, ejecuta
en otra terminal desde document-lab:

```powershell
.\.venv\Scripts\python.exe -m app.compare_search --query "cómo encontrar documentos con significado parecido"
```

Consulta /retrieve tres veces, sin llamar a /rag/ask. Muestra fuentes, fragmentos y
tiempos, y guarda el detalle completo en reports/search-<fecha>.json. La consulta
vectorial e híbrida comparten el embedding en caché: normalmente requieren una sola
llamada nueva de embeddings, ninguna si ya está en caché. No incluye el consumo de
embeddings en el informe: el contador y usage permanecen en embeddings.db.

El informe no calcula precisión ni detecta alucinaciones. Revisa si cada fragmento
responde a la consulta. Tener más resultados no equivale a mayor relevancia.
Los tiempos incluyen red, autenticación y creación/lectura de caché; no son una
medición aislada del buscador y la primera consulta vectorial puede tardar más.
Los informes contienen extractos de tus documentos y se excluyen de Git.
