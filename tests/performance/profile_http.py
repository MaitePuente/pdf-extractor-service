"""Sequential Windows HTTP profiling with existing server logs and exact output checks.

Run from the repository root. PDFs remain outside the repository. This script
does not configure Docker, modify Redis, or execute k6/Vegeta.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import http.client
import json
from pathlib import Path
import subprocess
import threading
from time import perf_counter_ns, sleep
from urllib.parse import urlsplit


EXPECTED = 'c636e1997422a5a99c45dc6ff9f2d2228f062d1e432b2948b373aa4328c1cdbc'


def stats(values):
    values = sorted(values)
    def q(f):
        p = (len(values) - 1) * f
        i = int(p)
        return values[i] + (values[min(i + 1, len(values) - 1)] - values[i]) * (p - i)
    return dict(n=len(values), min=values[0], p50=q(.5), p90=q(.9), p95=q(.95), max=values[-1])


def docker(*args):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout


def main(args):
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / (args.name + '.json')
    if path.exists():
        raise SystemExit(f'Refusing to overwrite {path}')
    body = args.pdf.read_bytes()
    url = urlsplit(args.url)
    connection = http.client.HTTPConnection(url.hostname, url.port, timeout=60)
    prefix = args.name + '-' + datetime.now(timezone.utc).strftime('%H%M%S')
    started_at = datetime.now(timezone.utc).isoformat()
    measured, warmup, health = [], [], []
    resource_samples = []
    stop = threading.Event()
    def resources():
        while not stop.is_set():
            result = subprocess.run(['docker', 'stats', '--no-stream', '--format', '{{json .}}',
                                     'pdf-extractor-extractor-1', 'pdf-extractor-extractor-2',
                                     'pdf-extractor-traefik-1', 'pdf-extractor-redis-1'],
                                    capture_output=True, text=True, encoding='utf-8')
            resource_samples.append(dict(at=datetime.now(timezone.utc).isoformat(),
                                         output=result.stdout, error=result.stderr, code=result.returncode))
            stop.wait(2)
    sampler = threading.Thread(target=resources)
    sampler.start()
    try:
        for index in range(args.warmup + args.repeat):
            audit = f'{prefix}-{index:03d}'
            sent = perf_counter_ns()
            connection.request('POST', '/extract', body=body, headers={
                'Content-Type': 'application/pdf', 'Host': 'localhost', 'X-Audit-Id': audit})
            sent_body = perf_counter_ns()
            response = connection.getresponse()
            headers_at = perf_counter_ns()
            raw = response.read()
            done = perf_counter_ns()
            payload = json.loads(raw)
            digest = hashlib.sha256(payload['content'].encode()).hexdigest()
            assert response.status == 200, response.status
            assert response.getheader('X-Cache') == args.cache, response.getheader('X-Cache')
            assert payload['page_count'] == 279
            assert len(payload['content']) == 427008
            assert digest == EXPECTED
            # Exact hash plus ordered, unique headings ensures no lost pages.
            import re
            assert re.findall(r'^## Página (\d+)$', payload['content'], re.M) == [str(i) for i in range(1, 280)]
            row = dict(audit_id=audit, status=response.status, cache=response.getheader('X-Cache'),
                       characters=len(payload['content']), page_count=payload['page_count'], sha256=digest,
                       response_bytes=len(raw), total_ms=(done-sent)/1e6,
                       client_send_ms=(sent_body-sent)/1e6,
                       wait_headers_ms=(headers_at-sent_body)/1e6,
                       response_read_ms=(done-headers_at)/1e6)
            (warmup if index < args.warmup else measured).append(row)
        if args.health_probe:
            # One additional conversion outside measured runs; GET while POST waits.
            errors = []
            finished = threading.Event()
            def post():
                try:
                    connection.request('POST', '/extract', body, {'Content-Type': 'application/pdf',
                                       'Host': 'localhost', 'X-Audit-Id': prefix + '-health-post'})
                    reply = connection.getresponse()
                    assert reply.status == 200
                    reply.read()
                except BaseException as exc:
                    errors.append(repr(exc))
                finally:
                    finished.set()
            thread = threading.Thread(target=post)
            thread.start()
            sleep(.06)
            while not finished.is_set():
                probe = http.client.HTTPConnection(url.hostname, url.port, timeout=2)
                begin = perf_counter_ns()
                probe.request('GET', '/health', headers={'Host': 'localhost'})
                reply = probe.getresponse()
                content = json.loads(reply.read())
                health.append(dict(ms=(perf_counter_ns()-begin)/1e6, status=reply.status,
                                   post_in_flight=not finished.is_set()))
                assert reply.status == 200 and content == {'status': 'ok', 'service': 'extractor'}
                probe.close()
                sleep(.03)
            thread.join()
            assert not errors, errors
    finally:
        connection.close()
        stop.set()
        sampler.join()
        records = []
        for name in ['pdf-extractor-extractor-1', 'pdf-extractor-extractor-2', 'pdf-extractor-traefik-1']:
            raw = docker('logs', '--since', started_at, name)
            (args.output / (args.name + '-' + name + '.log')).write_text(raw, encoding='utf-8')
            if 'extractor-extractor' in name:
                for line in raw.splitlines():
                    if line.startswith('PROFILE '):
                        record = json.loads(line[8:])
                        record['instance'] = name
                        records.append(record)
        by_id = {r['audit_id']: r for r in records}
        for row in warmup + measured:
            row['server'] = by_id.get(row['audit_id'])
        summary = {field: stats([r[field] for r in measured]) for field in
                   ['total_ms', 'client_send_ms', 'wait_headers_ms', 'response_read_ms']} if measured else {}
        if measured and all(r['server'] for r in measured):
            for field in ['receive_body_ms', 'sha256_ms', 'worker_ms', 'algorithm_ms',
                          'get_text_ms', 'markdown_build_ms', 'serialization_ms', 'total_server_ms',
                          'redis_get_ms', 'cache_decode_ms', 'cache_set_ms']:
                values = [r['server'][field] for r in measured if field in r['server']]
                if values:
                    summary[field] = stats(values)
            ipc = [r['server']['worker_ms'] - r['server'].get('algorithm_ms', 0) for r in measured
                   if 'worker_ms' in r['server']]
            if ipc:
                summary['worker_overhead_ms'] = stats(ipc)
        report = dict(url=args.url, client='Windows Python http.client; sequential keep-alive',
                      args=vars(args) | {'pdf': str(args.pdf), 'output': str(args.output)},
                      pdf_bytes=len(body), pdf_sha256=hashlib.sha256(body).hexdigest(),
                      warmup=warmup, measured=measured, summary=summary,
                      distribution=dict(Counter(r['server']['instance'] for r in measured if r.get('server'))),
                      health=health, resources=resource_samples,
                      final_inspect=json.loads(docker('inspect', 'pdf-extractor-extractor-1',
                                           'pdf-extractor-extractor-2', 'pdf-extractor-redis-1', 'pdf-extractor-traefik-1')))
        path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(dict(name=args.name, completed=len(measured), summary=summary,
                              distribution=report['distribution'], health=health)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', type=Path, required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--cache', choices=['HIT', 'BYPASS', 'MISS'], required=True)
    parser.add_argument('--repeat', type=int, default=20)
    parser.add_argument('--warmup', type=int, default=4)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--health-probe', action='store_true')
    main(parser.parse_args())
