# Práctica real de Service Bus

## Caducidad del bloqueo

Con la cola vacía y sin otros consumidores:

```powershell
python -m app.servicebus_lab send
python -m app.servicebus_lab expire
python -m app.servicebus_lab receive
```

expire recibe un mensaje en PeekLock, espera hasta locked_until_utc más tres segundos
sin renovar, e intenta complete. Debe mostrar MessageLockLostError. Puede tardar
alrededor de un minuto con el bloqueo predeterminado; espera a que termine.
receive debe mostrar el mismo message_id y un delivery_count mayor antes de confirmar.
No hagas varios expire seguidos: cuentan para maxDeliveryCount y pueden llevarlo a DLQ.
El reloj del equipo debe estar sincronizado. Ante otros errores de red o autorización,
el script los muestra como errores, no como prueba de caducidad.

LockDuration limita cuánto tiempo conserva un consumidor su bloqueo. TTL limita
la vida del mensaje: son conceptos distintos. Para un procesamiento largo se puede
renovar el bloqueo, pero sigue siendo necesario tolerar duplicados.

### Renovar antes de caducar

```powershell
python -m app.servicebus_lab send
python -m app.servicebus_lab renew
python -m app.servicebus_lab peek
```

renew espera aproximadamente la mitad del bloqueo inicial, llama a
renew_message_lock y muestra la nueva fecha de caducidad. Después espera hasta
superar el plazo original y confirma dentro del plazo renovado. Puede tardar
aproximadamente un minuto. El último peek debe encontrar vacía una cola que solo
contenía este mensaje. No hay procesamiento de IA: las esperas representan trabajo.
Esta renovación es manual y única; para tareas largas existe AutoLockRenewer.
Renovar no equivale a confirmar, no amplía TTL y puede fallar por pérdida de
conexión o bloqueo. No garantiza ausencia de entregas duplicadas.

El script app/servicebus_lab.py es independiente de FastAPI y SQLite. Todos los
mensajes se guardan en Azure. Los identificadores de documento son ficticios:
esta práctica estudia transporte y confirmación, no llama a modelos ni analiza archivos.
Utiliza una cola exclusiva de laboratorio y no ejecutes otros consumidores durante el ejercicio.

Conservando las variables $bus y $grupo de la creación:

```powershell
python -m pip install -r requirements-servicebus.txt
$env:SERVICEBUS_NAMESPACE = "$bus.servicebus.windows.net"
$env:SERVICEBUS_QUEUE = "documentos"
$busId = az servicebus namespace show --resource-group $grupo --name $bus --query id -o tsv
$usuarioId = az ad signed-in-user show --query id -o tsv
az role assignment create --assignee-object-id $usuarioId --assignee-principal-type User --role "Azure Service Bus Data Sender" --scope $busId
az role assignment create --assignee-object-id $usuarioId --assignee-principal-type User --role "Azure Service Bus Data Receiver" --scope $busId
```

Los permisos de datos pueden tardar unos minutos en propagarse. Ser propietario
del recurso no sustituye estos permisos. Usa az login si ha caducado tu sesión.

```powershell
python -m app.servicebus_lab send
python -m app.servicebus_lab peek
python -m app.servicebus_lab receive
python -m app.servicebus_lab peek
```

Observa que peek conserva el mensaje y complete lo retira. El consumidor utiliza
PeekLock: recibir bloquea temporalmente; confirmar es una operación posterior.

```powershell
python -m app.servicebus_lab send
python -m app.servicebus_lab fail
python -m app.servicebus_lab fail
python -m app.servicebus_lab fail
python -m app.servicebus_lab dlq
```

Con maxDeliveryCount=3, los abandonos repetidos deben llevar el mensaje a la DLQ.
Inspecciona el motivo MaxDeliveryCountExceeded. Si aún no aparece, consulta otra vez
y comprueba la configuración y que no había mensajes anteriores en la cola.
delivery_count es el contador del SDK; observa cómo cambia, sin equipararlo a un
contador de llamadas a tu función. DLQ usa peek: no consume ni elimina mensajes.

Qué debes poder explicar: receive no implica complete; abandon permite otra entrega;
un bloqueo vencido también puede producir otra entrega; el consumidor debe tolerar
duplicados. La DLQ permite investigar fallos, no los corrige automáticamente.

Al finalizar toda la práctica puedes borrar únicamente este namespace:
az servicebus namespace delete --resource-group $grupo --name $bus
No borres el grupo compartido con los otros ejercicios.

## Recuperar un mensaje de la DLQ

```powershell
python -m app.servicebus_lab replay
python -m app.servicebus_lab peek
python -m app.servicebus_lab receive
python -m app.servicebus_lab dlq
```

replay recibe un único mensaje de la DLQ en PeekLock. Copia cuerpo, message_id,
content_type, correlation_id y propiedades de aplicación a un mensaje nuevo de la
cola principal; después confirma el original. Conserva el identificador para poder
relacionar ambos. La nueva entrega empieza su propio contador; no traslada el
contador ni el motivo de dead-letter. Solo admite los cuerpos DATA de este laboratorio.

No es una transacción: si el envío funciona pero complete falla, queda una copia
en la cola principal y el original en la DLQ. Repetir puede duplicar el trabajo.
Con Basic no dependemos de detección de duplicados. La aplicación debe tolerarlos.
No se preservan TTL, programación ni otras opciones avanzadas: no es una herramienta
general de recuperación para producción. Aquí el fallo era simulado; con un fallo
real hay que corregir su causa antes de reenviar, o volverá a acabar en la DLQ.
