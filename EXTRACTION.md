# Extracción estructurada de facturas con Azure

Reinicia la API, sube examples/factura-estructurada.txt y ejecuta
POST /documents/{id}/extract. No necesita indexación ni embeddings. Usa el texto completo
TXT/DOCX (máximo 12000 caracteres, sin truncar) y el modelo chat-practicas.

Solicita Structured Outputs con JSON Schema estricto y valida con Pydantic los campos
numero_factura, proveedor, fecha, total y moneda. Todos son obligatorios pero admiten null
si no hay información. Un documento que no es factura debe producir campos null.
La forma correcta no garantiza datos correctos: requiere revisión humana.

La respuesta incluye status, data, requires_review, usage, call_id y cached.
status puede ser extracted, refused, incomplete o invalid_output. Solo extracted se
guarda en extractions, tabla local de SQLite. Repetir devuelve la caché sin llamar
al modelo; peticiones simultáneas antes de guardar pueden generar llamadas duplicadas.
Reiniciar conserva la caché. No modifica el análisis simulado ni registra una aprobación.

Reutiliza ENABLE_AZURE_LLM y el límite diario compartido con /rag/ask. /usage incluye
ambas operaciones en generation. Errores sin respuesta cuentan como intentos; negativas
o respuestas inválidas conservan el consumo reportado. No hay reintentos automáticos.
No hay OCR, PDF ni despliegue de esta fase en ACA.
