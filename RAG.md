# Preparación de contexto para RAG

Reinicia la API local, sube un TXT/DOCX e indéxalo con POST /documents/{id}/index.
POST /rag/prepare recibe:

```json
{
  "question": "¿Cómo organiza Cosmos los datos?",
  "search_query": "Cosmos particiones",
  "top_k": 3
}
```

question es la pregunta para el modelo; search_query son palabras clave para FTS5.
Separarlas evita exigir que todos los términos de una pregunta larga aparezcan
en el fragmento. La recuperación sigue siendo léxica, no semántica.

La respuesta contiene sources con etiquetas S1, S2, etc., y messages listo para
adaptarlo al cliente de un modelo. El mensaje system exige responder con fuentes,
citar y abstenerse si falta información; el mensaje user contiene la pregunta y
las fuentes como JSON. Es una instrucción al modelo, no una garantía de precisión
ni una protección completa ante inyección de instrucciones en documentos.

status=no_sources significa que no hubo coincidencias; ready significa que hay
contexto disponible, no que contenga necesariamente la respuesta. Este endpoint no
llama a ningún modelo, no consume tokens facturados y no genera una respuesta.
El límite de diez fragmentos acota el contexto por palabras, no por tokens.
Las referencias identifican documento y fragmento, no páginas del original.

## Generación real en Azure, desde tu API local

El modelo chat-practicas está desplegado en ai200-modelo-418352 (Sweden Central).
Tu usuario tiene Cognitive Services OpenAI User en ese recurso. El cliente usa
AzureCliCredential: az login, sin claves. Esta integración no está desplegada en ACA.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:STORAGE_BACKEND = "local"
$env:DATA_DIR = "data-queue"
$env:AZURE_OPENAI_ENDPOINT = "https://ai200-modelo-418352.openai.azure.com"
$env:AZURE_OPENAI_DEPLOYMENT = "chat-practicas"
$env:ENABLE_AZURE_LLM = "true"
$env:LLM_DAILY_CALL_LIMIT = "20"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

POST /rag/ask acepta el mismo JSON que /rag/prepare. Con fuentes realiza una llamada
real y facturable a Azure; sin fuentes devuelve no_sources sin llamar al modelo.
Devuelve answer, sources, usage, finish_reason y call_id. Las citas son generadas
por el modelo: no se verifica automáticamente que respalden todas las afirmaciones.
finish_reason=length indica que alcanzó el límite; no hay continuación automática.

Límites: hasta 3 fragmentos, 12000 caracteres de mensajes y 500 tokens de salida;
no hay reintentos de inferencia automáticos. El límite diario reserva intentos en
llm_calls antes de llamar, incluyendo fallos y timeouts. Persiste al reiniciar y se
reinicia por día UTC. Borrar la base de datos o utilizar otra carpeta crea otro
contador: NO es un límite de gasto global de Azure ni una cifra en euros.
Las peticiones realizadas fuera de esta aplicación no se cuentan. No guarda preguntas
ni respuestas en llm_calls; solo fecha, estado y consumo reportado por Azure.

Esta API no tiene autenticación: mantener el servidor en 127.0.0.1. No publicar
esta fase en ACA hasta integrar autenticación, almacenamiento e identidad administrada.
Desactiva llamadas con ENABLE_AZURE_LLM=false. /rag/prepare continúa siendo gratuito.
