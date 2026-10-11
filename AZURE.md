# Fase 2 Conectar la API local con Blob Storage

Requisito: cuenta de almacenamiento y contenedor privado `documents` creados,
sesión `az login` y rol Storage Blob Data Contributor sobre esa cuenta.

Detén el servidor con Ctrl+C. En la carpeta del proyecto:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:STORAGE_BACKEND = "azure"
$env:AZURE_STORAGE_ACCOUNT = "SUSTITUYE_POR_TU_CUENTA"
$env:AZURE_STORAGE_CONTAINER = "documents"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Si aún conservas `$almacen` de los comandos anteriores, puedes utilizar:

```powershell
$env:AZURE_STORAGE_ACCOUNT = $almacen
```

Abre http://localhost:8000/docs. Health devuelve `storage_backend: azure`.
Sube un archivo NUEVO, copia su ID, analízalo y reinicia el servidor. Al consultar
ese mismo ID, el resultado continúa disponible en Azure.

Comprueba los blobs desde la terminal:

```powershell
az storage blob list --account-name $env:AZURE_STORAGE_ACCOUNT --container-name documents --auth-mode login --query "[].name" --output table
```

- `originals/<id>`: bytes del archivo.
- `metadata/<id>.json`: nombre original, hash, fecha y demás metadatos.
- `results/<id>.json`: análisis simulado, creado sin sobrescribir resultados previos.

En modo Azure no se utiliza SQLite. Es una fase sencilla sin base de datos:
los metadatos se guardan como JSON en blobs privados. Más adelante los moveremos
a Cosmos DB para consultar, indexar y procesar change feed.

No se migran los documentos locales ni el blob manual `prueba/factura.txt`.
Esos archivos no tienen los registros que espera la API: sube uno desde `/docs`.

DefaultAzureCredential utiliza credenciales del entorno: localmente puede usar Azure CLI;
en Container Apps configuraremos identidad administrada y su permiso correspondiente.
No se incluyen claves ni tokens en el código.

Si el arranque falla: comprueba nombre de cuenta, contenedor, `az login`, permisos y
conectividad. Los nuevos permisos pueden tardar unos minutos en aplicarse.
Los fallos de almacenamiento durante una petición devuelven HTTP 503.

Limitación: archivo y metadatos son dos escrituras independientes. Un fallo entre ellas
puede dejar un original sin metadatos; una respuesta perdida puede dejar un documento
completo cuyo ID no llegó al cliente. Añadiremos idempotencia de subida y reconciliación
en una fase posterior. El análisis simulado sí conserva el primer resultado creado
cuando varias réplicas intentan guardarlo a la vez.

El tamaño se valida por archivo en la API. El proxy de producción también necesitará
límites de petición. La API todavía carece de autenticación: mantener uso local.

Para volver al modo local, detén el servidor y configura:

```powershell
$env:STORAGE_BACKEND = "local"
```

Vuelve a arrancarlo. Los datos locales originales siguen en `data`.

Para ejecutar las pruebas, usa modo local; las pruebas de Azure utilizan un doble
de almacenamiento y no realizan operaciones en tu suscripción:

```powershell
$env:STORAGE_BACKEND = "local"
.\.venv\Scripts\python.exe -m pytest -q
```

Tras probar la conexión real, construye la nueva imagen, sin reemplazar v1:

```powershell
az acr build --registry acrai200672612 --image document-lab:v2 --file Dockerfile .
```

Construir la imagen no la despliega. La siguiente fase será configurar la identidad
administrada y desplegarla en Container Apps con las variables de entorno anteriores.
