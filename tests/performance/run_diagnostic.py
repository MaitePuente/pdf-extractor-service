"""Exactly one BYPASS request: Windows direct, or Docker k6 through Traefik."""
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
    parser.add_argument('--mode', choices=['direct', 'network'], required=True)
    parser.add_argument('--pdf', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.name):
        parser.error('Use a simple, unique run name')
    service = Path(__file__).resolve().parents[2]
    results = args.results.resolve()
    results.mkdir(parents=True, exist_ok=True)
    if any(results.glob(args.name + '.*')):
        parser.error('Run name already exists; preserve previous evidence')
    pdf = args.pdf.resolve()
    os.chdir(service)
    ids = docker('ps', '-q', '--filter', 'label=com.docker.compose.project=pdf-extractor').splitlines()
    initial = json.loads(docker('inspect', *ids))
    if not initial or any(c['State'].get('Health', {}).get('Status') != 'healthy' for c in initial):
        raise RuntimeError('All project containers must be healthy')
    summary = results / (args.name + '.summary.json')
    env = os.environ.copy()
    settings = dict(PDF_PATH=str(pdf), EXPECT_CACHE='BYPASS', VUS='1', ITERATIONS_PER_VU='1',
                    EXPECTED_CONTENT_SHA256=args.sha256, REQUEST_TIMEOUT='30s',
                    RUN_ID=args.name, RESULT_FILE=str(summary))
    scripts = service / 'tests/performance'
    if args.mode == 'direct':
        # The common checks retain their historical metric tag; this is a direct diagnostic.
        replica = next(c for c in initial if c['Name'] == '/pdf-extractor-extractor-1')
        port = replica['NetworkSettings']['Ports']['8000/tcp'][0]['HostPort']
        settings['EXTRACT_URL'] = f'http://localhost:{port}/extract'
        env.update(settings)
        command = ['k6', 'run', '--no-color', '--log-format', 'json', str(scripts / 'baseline.js')]
    else:
        proxy = next(c for c in initial if c['Name'] == '/pdf-extractor-traefik-1')
        settings.update(PDF_PATH='/input.pdf', RESULT_FILE='/results/' + summary.name,
                        EXTRACT_URL='http://localhost/extract',
                        TRAEFIK_IP=proxy['NetworkSettings']['Networks']['pdf-network']['IPAddress'])
        command = ['docker', 'run', '--rm', '--name', 'pdf-extractor-k6-' + args.name,
                   '--network', 'pdf-network', '--cpus', '1', '--memory', '256m',
                   '--mount', f'type=bind,source={pdf},target=/input.pdf,readonly',
                   '--mount', f'type=bind,source={scripts},target=/scripts,readonly',
                   '--mount', f'type=bind,source={results},target=/results']
        for key, value in settings.items():
            command.extend(['-e', f'{key}={value}'])
        command.extend(['grafana/k6:2.2.0', 'run', '--no-color', '--log-format', 'json', '/scripts/network.js'])
    began = datetime.now(timezone.utc).isoformat()
    start = time.perf_counter()
    samples, aborted = [], None
    with (results / (args.name + '.log')).open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        while process.poll() is None:
            raw = docker('stats', '--no-stream', '--format', '{{json .}}')
            samples.append(dict(elapsed_s=time.perf_counter() - start,
                                containers=[json.loads(line) for line in raw.splitlines() if line]))
            states = json.loads(docker('inspect', *ids))
            if any(c['State'].get('OOMKilled') or not c['State']['Running'] or
                   c['State'].get('Health', {}).get('Status') == 'unhealthy' for c in states):
                aborted = 'Unsafe API/Redis/Traefik state'
                if args.mode == 'network':
                    docker('stop', 'pdf-extractor-k6-' + args.name)
                process.terminate()
                break
        code = process.wait()
    report = dict(mode=args.mode, command=command, environment=settings, started_utc=began,
                  exit_code=code, wall_seconds=time.perf_counter() - start,
                  aborted=aborted, samples=samples,
                  final_states=[dict(name=c['Name'], state=c['State'], restarts=c['RestartCount'])
                                for c in json.loads(docker('inspect', *ids))])
    (results / (args.name + '.resources.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(name=args.name, exit_code=code, aborted=aborted)))
    print((results / (args.name + '.log')).read_text(encoding='utf-8')[-5000:])
    raise SystemExit(code)


if __name__ == '__main__':
    main()
