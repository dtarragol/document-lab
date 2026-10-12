# Document Lab — primera práctica AI-200

**Contexto para RAG:** [RAG.md](RAG.md), preparación de mensajes y fuentes citables.

**Búsqueda por contenido:** [SEARCH.md](SEARCH.md), índice local FTS5 y recuperación de fragmentos.

## Práctica completa en un comando

Con requirements-dev.txt instalado, ejecuta `python -m app.demo` desde esta carpeta.
Usa la API local mediante TestClient, dos procesos worker y una carpeta temporal.
Comprueba subida, cola, clasificación por contenido, aprobación, rechazo y persistencia
tras reiniciar la API. No necesita servidor, puertos ni Azure. No modifica data-queue;
los documentos de la demo se eliminan al salir y no aparecen en tu Swagger habitual.

**Actualización del modo local:** TXT UTF-8 y DOCX se clasifican por su contenido,
no por el nombre. GET /documents/{id}/text muestra hasta 4000 caracteres extraídos.
No hay OCR ni soporte de extracción PDF. Los resultados anteriores se conservan;
sube un documento nuevo para probarlo. El modo Azure aún clasifica por nombre.

**Práctica sin esperar a Azure:** [QUEUE.md](QUEUE.md), cola persistente y worker local.

**Revisión humana:** [REVIEW.md](REVIEW.md), aprobar o rechazar después del análisis.

API Python para subir documentos, consultar su estado y ejecutar un análisis simulado.
FastAPI ofrece la interfaz interactiva en http://localhost:8000/docs.

**Fase 2 disponible:** consulta [AZURE.md](AZURE.md) para utilizar Blob Storage
con tu sesión de Azure, sin SQLite ni archivos persistentes locales. El resto de
esta guía describe el modo local (predeterminado).

**Fase 3 preparada:** [COSMOS.md](COSMOS.md) explica la opción de metadatos
en Cosmos DB y cómo probarla mientras se habilita el acceso a la región.

## Arrancar con Docker

Abre Docker Desktop y espera a que el motor esté listo. Desde esta carpeta:

```powershell
docker compose up --build
```

Abre http://localhost:8000/docs. Para parar, pulsa Ctrl+C y ejecuta `docker compose down`.
El volumen `document_data` conserva los archivos y SQLite entre reinicios.
`docker compose down -v` elimina ese volumen y todos los documentos: úsalo solo para reiniciar la práctica desde cero.

## Arrancar sin Docker

Necesitas Python 3.12 o superior. Desde esta carpeta:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Primera prueba en el navegador

1. Abre `/docs` y comprueba `GET /health` con **Try it out → Execute**.
2. En `POST /documents`, selecciona `examples/factura.txt` y pulsa **Execute**.
3. Copia el campo `id` de la respuesta (HTTP 201).
4. Úsalo en `GET /documents/{document_id}`: verás `Uploaded`.
5. Ejecuta `POST /documents/{document_id}/analyze`: verás `Analyzed` y el resultado.
6. Repite el análisis: devuelve el mismo resultado.
7. Reinicia la aplicación y consulta el mismo ID: los datos siguen ahí.
8. Prueba un UUID inexistente: devuelve 404. Un ID mal formado devuelve 422.

## Pruebas automatizadas

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Las pruebas usan directorios temporales. Verifican persistencia entre instancias,
repetición de análisis, nombres de archivo seguros, documentos vacíos, límite de tamaño y errores HTTP.

## Código y datos

- `app/main.py`: modelos de respuesta, inicialización de SQLite y endpoints.
- `data/documents.db`: metadatos y resultados (local).
- `data/files/<id>`: archivo original, sin usar el nombre proporcionado como ruta.
- `DATA_DIR`: carpeta de persistencia; por defecto `data`.
- `MAX_UPLOAD_BYTES`: límite por documento; por defecto 10 MiB.

El análisis es deliberadamente simulado: el texto que contenga `factura` o `invoice`
se clasifica como `invoice`; el resto como `other`. La confianza fija es 0.72 y siempre
requiere revisión. Extrae texto de TXT y del cuerpo principal de DOCX; no interpreta PDF ni llama a un modelo de IA.
Admite archivos no vacíos hasta el límite configurado; el tipo MIME es metadato declarado por el cliente.

Esta fase no utiliza Azure, Durable Functions ni autenticación. Está pensada para tu equipo;
antes de publicarla habrá que añadir autenticación, almacenamiento en Azure y límites de petición.
La repetición segura del análisis es local; no sustituye a una estrategia distribuida de idempotencia.

## Qué aprender y siguiente fase

Sigue una solicitud desde HTTP hasta SQLite, distingue los códigos 201/400/404/413/422,
observa los registros de Uvicorn y los eventos sin contenido de documentos, entiende el
Dockerfile y comprueba por qué el volumen permite conservar datos.

Siguiente fase: versionar la imagen en Azure Container Registry, construirla con ACR Tasks
y desplegar en App Service, adaptando la persistencia a almacenamiento externo.
