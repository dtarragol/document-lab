# Práctica: API, cola persistente y worker local

No necesita Cosmos ni nuevos recursos Azure. Ejecutar desde document-lab.
La aplicación desplegada en Azure no cambia. Esta cola solo existe en el modo local.

## 1. Terminal de la API

```powershell
$env:STORAGE_BACKEND = "local"
$env:DATA_DIR = "data-queue"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Si el puerto está ocupado, detén la API anterior con Ctrl+C o utiliza 8001.
Abre http://localhost:8000/docs (8001 si cambiaste el puerto).
Sube examples/factura.txt mediante POST /documents. Copia su id.
Ejecuta POST /documents/{document_id}/enqueue: devuelve 202 Accepted.
Consulta GET /documents/{document_id}: debe mostrar Queued y analysis=null.
Repite enqueue: no duplica el trabajo.

## 2. Segunda terminal, misma carpeta

```powershell
$env:STORAGE_BACKEND = "local"
$env:DATA_DIR = "data-queue"
.\.venv\Scripts\python.exe -m app.worker --once
```

Consulta de nuevo el documento: ahora aparece Analyzed con el resultado.
Ejecuta otra vez el worker: no repite el trabajo completado.
Sin --once queda escuchando; Ctrl+C lo detiene.

## Qué observar

- La API acepta el trabajo; el 202 no significa que haya terminado.
- La tabla jobs conserva el trabajo aunque cierres ambos procesos.
- La API y el worker comparten DATA_DIR: son procesos independientes.
- El ID del documento evita duplicados en esta práctica.
- El worker confirma el resultado y el trabajo en una transacción SQLite.
  Si termina antes de confirmar, SQLite revierte los cambios y el trabajo sigue pendiente.

El análisis sigue siendo simulado. Aquí se mantiene una transacción de escritura
durante el cálculo porque es inmediato; esto serializa los workers y bloquea otras
escrituras brevemente. No uses este patrón para llamadas lentas a IA.
Service Bus requiere otra implementación: recepción, bloqueo, complete, abandon,
reentregas y dead-letter queue. Esta práctica no reproduce esas garantías ni tiene
reintentos limitados o cola de errores. No ejecutes este worker contra el modo Azure.
