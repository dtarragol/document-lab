"""Evalúa recuperación con respuestas esperadas; no genera respuestas."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import httpx


def evaluate(client, cases, modes, top_k):
    results = []
    for mode in modes:
        rows = []
        for case in cases:
            response = client.get('/retrieve', params={'q': case['query'], 'top_k': top_k, 'mode': mode})
            row = dict(query=case['query'], expected_filename=case['expected_filename'], http_status=response.status_code)
            if response.is_success:
                sources = response.json()['sources']
                rank = next((i for i, source in enumerate(sources, 1)
                             if source['filename'] == case['expected_filename']), None)
                row.update(rank=rank, reciprocal_rank=1 / rank if rank else 0,
                           retrieved_filenames=[s['filename'] for s in sources])
            else:
                row.update(rank=None, reciprocal_rank=0, error=response.text[:500])
            rows.append(row)
        results.append(dict(mode=mode, cases=rows, errors=sum(r['http_status'] != 200 for r in rows),
                            hit_rate=sum(r['rank'] is not None for r in rows) / len(rows),
                            mrr=sum(r['reciprocal_rank'] for r in rows) / len(rows)))
    return dict(top_k=top_k, created_at=datetime.now(timezone.utc).isoformat(), results=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', required=True, type=Path)
    parser.add_argument('--modes', nargs='+', choices=['lexical', 'vector', 'hybrid'], default=['lexical'])
    parser.add_argument('--top-k', type=int, choices=range(1, 11), default=3)
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    url = urlparse(args.url)
    if url.scheme != 'http' or url.hostname not in ('localhost', '127.0.0.1') or url.username or url.password:
        parser.error('Utiliza la URL HTTP de tu API local')
    try:
        cases = json.loads(args.cases.read_text(encoding='utf-8-sig'))
        if not isinstance(cases, list) or not 1 <= len(cases) <= 20:
            raise ValueError('Se requieren entre 1 y 20 casos')
        for case in cases:
            if (not isinstance(case, dict) or not isinstance(case.get('query'), str)
                    or not 1 <= len(case['query'].strip()) <= 200
                    or not isinstance(case.get('expected_filename'), str) or not case['expected_filename'].strip()):
                raise ValueError('Cada caso requiere query (1–200 caracteres) y expected_filename')
    except (OSError, ValueError) as error:
        parser.error(str(error))
    try:
        with httpx.Client(base_url=args.url, timeout=90, follow_redirects=False) as client:
            report = evaluate(client, cases, list(dict.fromkeys(args.modes)), args.top_k)
    except httpx.HTTPError as error:
        parser.exit(1, f'Error de conexión: {type(error).__name__}. Comprueba la API.\n')
    directory = Path('reports')
    directory.mkdir(exist_ok=True)
    target = directory / ('evaluation-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f') + '.json')
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for result in report['results']:
        print(f"{result['mode']}: aciertos={result['hit_rate']:.0%}, MRR={result['mrr']:.3f}, errores={result['errors']}")
        for case in result['cases']:
            print(f"  Consulta: {case['query']}")
            print(f"    Esperado: {case['expected_filename']}")
            if 'error' in case:
                print(f"    Error HTTP {case['http_status']}: {case['error']}")
            elif case['rank'] is not None:
                print(f"    Encontrado en posición {case['rank']}")
            else:
                found = ', '.join(dict.fromkeys(case['retrieved_filenames'])) or '(ningún fragmento)'
                print(f"    No encontrado. Devueltos: {found}")
    print(f'Informe: {target.resolve()}')
    print('Sin generación. Vector/hybrid pueden consumir embeddings. Los errores cuentan como fallos.')
    if any(r['errors'] for r in report['results']):
        parser.exit(1)


if __name__ == '__main__':
    main()
