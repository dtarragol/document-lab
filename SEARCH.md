# Búsqueda por contenido, local y sin Azure

Reinicia la API y recarga Swagger. Sube un TXT o DOCX y ejecuta
POST /documents/{id}/index. No necesita análisis ni aprobación previos.
Luego GET /search con q=Azure devuelve los documentos cuyo texto contiene esa palabra.
El nombre del archivo no se indexa. Las coincidencias aparecen entre corchetes en excerpt.

El índice SQLite FTS5 guarda una copia del texto extraído, independiente del original.
Persiste en documents.db. Reindexar sustituye la entrada, sin duplicarla.
Los documentos antiguos no se indexan automáticamente: utiliza /index para cada uno.
El límite predeterminado es 10 resultados y el máximo 50; count es el número devuelto,
no el total de coincidencias. No hay paginación en esta fase.

Varios términos se combinan con AND. No distingue mayúsculas y el tokenizador unicode61
normaliza diacríticos latinos habituales. No admite operadores de consulta del usuario,
sinónimos, embeddings, búsqueda semántica ni respuestas generadas. Ordena por BM25.
Puede encontrar términos presentes en documentos que todavía no se han aprobado;
la revisión no actúa como filtro de acceso en esta práctica local.

Conceptos: extracción convierte el archivo en texto; indexación prepara ese texto;
consulta recupera documentos y fragmentos. Este es el paso de recuperación previo
a una futura práctica RAG, todavía sin un modelo de lenguaje ni Azure AI Search.
Requiere Python con SQLite FTS5 habilitado (incluido en el entorno utilizado para pruebas).

## Recuperación de fragmentos

POST /documents/{id}/index también divide el texto en fragmentos de 120 palabras,
con 20 palabras de solapamiento. Reindexa los documentos indexados antes de esta mejora.
Los números de fragmento empiezan en 0; la fragmentación normaliza los espacios.

GET /retrieve?q=Cosmos&top_k=3 devuelve hasta tres fragmentos ordenados por BM25,
con document_id, filename, chunk_number y text. La respuesta conserva las fuentes
para poder construir referencias después. Un documento puede aportar varios fragmentos.
No devuelve páginas ni posiciones originales, ni elimina fragmentos solapados.

Los términos de la consulta deben estar en el mismo fragmento; /search permite
que estén en lugares diferentes del documento. Utiliza palabras clave, no preguntas
largas: esta recuperación es léxica con AND, no semántica. El tamaño se mide en palabras,
no tokens de un modelo. top_k es la cantidad máxima de fragmentos recuperados.

Esto implementa recuperación y fragmentación, no RAG completo. generated_answer es null:
no se llama a un LLM. No hay embeddings, búsqueda vectorial ni control de acceso por revisión.
