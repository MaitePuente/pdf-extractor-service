"""Bounded Docker k6 through Traefik; preserve metrics, resources and stop conditions."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from run_k6 import docker


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--cache', choices=['MISS', 'HIT'], required=True)
    parser.add_argument('--vus', type=int, default=1)
    parser.add_argument('--iterations-total', type=int, default=20)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    permitted = {1: [1, 20], 2: [20], 5: [25]}
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.name) or args.iterations_total not in permitted.get(args.vus, []):
        parser.error('Use a unique simple name and only 1x1, 1x20, 2x10 or 5x5 iterations')
    if args.cache == 'MISS' and (args.vus != 1 or args.iterations_total != 1):
        parser.error('MISS is only permitted for one preload request')
    service = Path(__file__).resolve().parents[2]
    results = args.results.resolve()
    results.mkdir(parents=True, exist_ok=True)
    if any(results.glob(args.name + '.*')):
        parser.error('Run name already exists; preserve previous evidence')
    pdf = args.pdf.resolve()
    os.chdir(service)
    ids = docker('ps', '-q', '--filter', 'label=com.docker.compose.project=pdf-extractor').splitlines()
    initial = json.loads(docker('inspect', *ids))
    replicas = [c for c in initial if c['Config']['Labels']['com.docker.compose.service'] == 'extractor']
    if len(replicas) != 5 or any(c['State'].get('Health', {}).get('Status') != 'healthy' for c in initial):
        raise RuntimeError('Require five healthy extractors, Redis and Traefik')
    if any('CACHE_ENABLED=true' not in c['Config']['Env'] for c in replicas):
        raise RuntimeError('All replicas must have cache enabled')
    proxy = next(c for c in initial if c['Config']['Labels']['com.docker.compose.service'] == 'traefik')
    settings = dict(PDF_PATH='/input.pdf', RESULT_FILE='/results/' + args.name + '.summary.json',
                    EXTRACT_URL='http://localhost/extract',
                    TRAEFIK_IP=proxy['NetworkSettings']['Networks']['pdf-network']['IPAddress'],
                    EXPECT_CACHE=args.cache, EXPECTED_CONTENT_SHA256=args.sha256,
                    RUN_ID=args.name, VUS=str(args.vus), ITERATIONS_TOTAL=str(args.iterations_total),
                    REQUEST_TIMEOUT='30s' if args.cache == 'MISS' else '5s')
    client = 'pdf-extractor-k6-' + args.name
    if docker('ps', '-aq', '--filter', 'name=^/' + client + '$'):
        raise RuntimeError('Client container name already exists; preserve it and choose another name')
    scripts = service / 'tests/performance'
    command = ['docker', 'run', '--name', client, '--network', 'pdf-network',
               '--cpus', '1', '--memory', '512m',
               '--mount', f'type=bind,source={pdf},target=/input.pdf,readonly',
               '--mount', f'type=bind,source={scripts},target=/scripts,readonly',
               '--mount', f'type=bind,source={results},target=/results']
    for key, value in settings.items():
        command.extend(['-e', f'{key}={value}'])
    command.extend(['grafana/k6:2.2.0', 'run', '--no-color', '--log-format', 'json', '/scripts/network_hot.js'])
    began = datetime.now(timezone.utc).isoformat()
    start = time.perf_counter()
    samples, aborted, client_state = [], None, None
    with (results / (args.name + '.log')).open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            while process.poll() is None:
                raw = docker('stats', '--no-stream', '--format', '{{json .}}')
                samples.append(dict(elapsed_s=time.perf_counter() - start,
                                    containers=[json.loads(line) for line in raw.splitlines() if line]))
                states = json.loads(docker('inspect', *ids))
                if any(c['State'].get('OOMKilled') or not c['State']['Running'] or
                       c['State'].get('Health', {}).get('Status') == 'unhealthy' for c in states):
                    aborted = 'Unsafe API/Redis/Traefik state'
                elif args.cache == 'HIT':
                    for replica in replicas:
                        messages = subprocess.check_output(['docker', 'logs', '--since', began, replica['Id']],
                                                           text=True, encoding='utf-8', stderr=subprocess.STDOUT)
                        if any(marker in messages for marker in ['CACHE MISS', 'CACHE BYPASS', 'CACHE ERROR']):
                            aborted = 'Unexpected cache operation in ' + replica['Name']
                            break
                if aborted:
                    docker('stop', '--time', '1', client)
                    break
            code = process.wait(timeout=10)
            client_state = json.loads(docker('inspect', client))[0]
            if client_state['State'].get('OOMKilled'):
                aborted = 'k6 client OOM'
        finally:
            if process.poll() is None:
                docker('stop', '--time', '1', client)
                process.wait(timeout=10)
    final = json.loads(docker('inspect', *ids))
    report = dict(command=command, environment=settings, started_utc=began, exit_code=code,
                  wall_seconds=time.perf_counter() - start, aborted=aborted, samples=samples,
                  initial_containers=[dict(name=c['Name'], id=c['Id'], networks=c['NetworkSettings']['Networks']) for c in initial],
                  client_inspect=client_state,
                  final_states=[dict(name=c['Name'], state=c['State'], restarts=c['RestartCount']) for c in final])
    (results / (args.name + '.resources.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
    # Remove only the short-lived client created by this run, after recording OOM/mount/network state.
    docker('rm', client)
    summary = results / (args.name + '.summary.json')
    print(json.dumps(dict(name=args.name, exit_code=code, aborted=aborted)))
    if summary.exists():
        metrics = json.loads(summary.read_text(encoding='utf-8'))['metrics']
        print(json.dumps({k: metrics[k]['values'] for k in [
            'http_req_duration', 'http_req_sending', 'http_req_waiting', 'http_req_receiving',
            'http_req_failed', 'checks', 'extract_errors', 'iterations'] if k in metrics}))
    else:
        print((results / (args.name + '.log')).read_text(encoding='utf-8')[-2000:])
    raise SystemExit(2 if aborted else code)


if __name__ == '__main__':
    main()
