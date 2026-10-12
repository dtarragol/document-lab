"""Compara recuperación, sin llamar al modelo generador: python -m app.compare_search."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from urllib.parse import urlparse

import httpx


def compare(client, query, top_k):
    results = []
    for mode in ('lexical', 'vector', 'hybrid'):
        start = perf_counter()
        response = client.get('/retrieve', params={'q': query, 'top_k': top_k, 'mode': mode})
        elapsed = round(perf_counter() - start, 3)
        result = {'mode': mode, 'http_status': response.status_code, 'seconds': elapsed}
        if response.is_success:
            data = response.json()
            result.update(sources=data['sources'], retrieval_mode=data['retrieval_mode'])
        else:
            result['error'] = response.json().get('detail', 'Error de API')
        results.append(result)
    return {'query': query, 'top_k': top_k, 'created_at': datetime.now(timezone.utc).isoformat(),
            'results': results}


def main():
    parser = argparse.ArgumentParser(description='Comparación de búsqueda textual, vectorial e híbrida')
    parser.add_argument('--query', required=True, help='La misma consulta para los tres modos')
    parser.add_argument('--top-k', type=int, default=3, choices=range(1, 11))
    parser.add_argument('--url', default='http://127.0.0.1:8000', help='API local ya arrancada')
    args = parser.parse_args()
    parsed = urlparse(args.url)
    if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1'):
        parser.error('--url debe apuntar a tu API HTTP local')
    if not args.query.strip() or len(args.query) > 200:
        parser.error('--query debe contener entre 1 y 200 caracteres')
    try:
        with httpx.Client(base_url=args.url, timeout=90) as client:
            health = client.get('/health')
            health.raise_for_status()
            if health.json().get('search_backend') != 'azure':
                parser.error('Arranca la API con SEARCH_BACKEND=azure')
            report = compare(client, args.query, args.top_k)
    except httpx.HTTPError as error:
        parser.exit(1, f'No se pudo consultar la API local: {type(error).__name__}. Comprueba que esté arrancada.\n')
    for result in report['results']:
        print(f'\n{result["mode"]}: HTTP {result["http_status"]}, {result["seconds"]} segundos')
        if 'error' in result:
            print(f'  Error: {result["error"]}')
        for number, source in enumerate(result.get('sources', []), 1):
            print(f'  {number}. {source["filename"]}, fragmento {source["chunk_number"]}')
            print('     ' + source['text'][:220].replace('\n', ' '))
        if not result.get('sources') and 'error' not in result:
            print('  Sin coincidencias.')
    directory = Path('reports')
    directory.mkdir(exist_ok=True)
    target = directory / ('search-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f') + '.json')
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\nInforme con los fragmentos completos: {target.resolve()}')
    print('No se han generado respuestas. Las consultas vectoriales nuevas pueden consumir embeddings.')


if __name__ == '__main__':
    main()
