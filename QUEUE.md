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
las garantías de reentrega de Service Bus. No ejecutes este worker contra el modo Azure.

## Fallos controlados y cola de errores

Reinicia primero la API: actualiza automáticamente la tabla jobs existente con
attempts y last_error. Detén cualquier worker continuo para que no recoja tu trabajo.
Sube un documento nuevo y ejecuta enqueue. En otra terminal, con las mismas variables:

```powershell
.\.venv\Scripts\python.exe -m app.worker --once --simulate-failure
```

Consulta GET /jobs/{document_id}: attempts=1, status=Pending y last_error explica el fallo.
Repite dos veces el comando: al tercer fallo pasa a DeadLetter y el documento a Failed.
Los workers omiten estos trabajos; enqueue devuelve 409. Para esta práctica usa un nuevo
documento si quieres empezar de nuevo, o usa la recuperación manual descrita abajo. Los trabajos de error se conservan en la misma
tabla, diferenciados por estado; no son una cola Azure real.

También prueba un solo fallo seguido de --once sin --simulate-failure: el segundo
intento completa el trabajo y limpia last_error. Aquí los reintentos son manuales,
sin backoff. Solo los fallos controlados cuentan para este límite: un error inesperado
de SQLite o una interrupción revierte la transacción y detiene el proceso.

## Recuperar un trabajo apartado

Detén el worker continuo. Consulta GET /jobs/{id} y revisa last_error antes de recuperar.
Ejecuta POST /jobs/{id}/retry para un trabajo DeadLetter: vuelve a Pending,
reinicia attempts a 0 y limpia last_error. El documento vuelve a Queued.
Ejecuta el worker con --once, sin --simulate-failure: quedará Completed / Analyzed.
La recuperación solo admite DeadLetter; otros estados devuelven 409 y un ID sin trabajo 404.
Esta práctica reinicia el contador y no conserva un historial de errores de ciclos anteriores.
