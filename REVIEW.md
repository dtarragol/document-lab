# Revisión humana local

Reinicia la API local y recarga Swagger. Sube y analiza un documento (directamente
o mediante enqueue y worker). GET /documents/{id}/review devuelve Pending hasta
registrar una decisión, incluso si aún no se ha analizado.

POST /documents/{id}/review recibe {"decision": "Approved"} o {"decision": "Rejected"}.
Solo admite documentos ya analizados. GET de la misma ruta permite consultar
la decisión y fecha guardadas en SQLite, tabla reviews.

Repetir la misma decisión conserva la fecha original. Una decisión diferente
devuelve 409; un valor no admitido devuelve 422. No se modifica el resultado de IA:
requires_review es la recomendación del análisis y la decisión humana es otro registro.
El estado del documento permanece Analyzed, el del trabajo Completed.

Es una práctica local sin autenticación ni identificación del revisor. No se implementan
notificaciones, permisos de aprobación, plazo, temporizador ni Durable Functions.
En una orquestación futura, esta acción enviaría un evento externo con el ID de
instancia correcto; aquí solo guarda la decisión en una transacción local.
