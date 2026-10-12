# Evaluar recuperación

## Práctica con tres servicios

Sube los tres archivos examples/practica-service-bus.txt,
examples/practica-event-grid.txt y examples/practica-event-hubs.txt mediante
POST /documents. Ejecuta POST /documents/{id}/index para cada identificador.
Después ejecuta:

```powershell
python -m app.evaluate_search --cases examples/evaluation-messaging.json --modes lexical vector hybrid
```

Los tres primeros casos buscan nombres explícitos. Los siguientes describen necesidades
sin nombrar el servicio. Compara los resultados: la búsqueda léxica actual exige todos
los términos, por lo que las preguntas largas pueden no coincidir. La vectorial puede
encontrar equivalencias semánticas; no garantiza acertar. Si conservas otros documentos
en el índice también compiten por las primeras posiciones. No se exige un 100%.

El evaluador muestra en consola el archivo esperado y los encontrados para cada fallo.
Esta práctica utiliza fragmentos didácticos, no preguntas oficiales del examen.

## Tus propios documentos

Con la API arrancada y tus documentos indexados, ajusta examples/evaluation.json:
query es una pregunta de prueba y expected_filename el nombre exacto del documento
que debería aparecer. El ejemplo usa el dossier de Cosmos; cámbialo si subiste otro.

```powershell
python -m app.evaluate_search --cases examples/evaluation.json --modes lexical vector hybrid
```

Para búsqueda local utiliza solo --modes lexical. Vector e hybrid necesitan la API
configurada con Azure Search y vectores. No se llama al modelo generador; sí puede
haber consumo de embeddings en consultas nuevas. Máximo 20 casos por ejecución.

Aciertos indica la proporción de consultas que recuperan el archivo esperado dentro
de top_k (3 por defecto). MRR promedia 1/posición: primero=1, segundo=0.5,
tercero=0.333, ausente=0. Se cuentan posiciones de fragmentos, incluyendo varios del
mismo archivo. Errores HTTP cuentan como fallos y se muestran por separado: resuelve
los errores antes de comparar calidad. El informe JSON queda en reports/.

Esto evalúa localizar el documento esperado, no la calidad factual de una respuesta
ni si el fragmento contiene toda la información. Usa preguntas representativas,
sin adaptar todas al vocabulario exacto del texto; con dos casos no puedes sacar
conclusiones generales. No modifica documentos ni índices.
