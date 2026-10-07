"""Official k6 spike, external PDFs, empty benchmark DB, unchanged services."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
# Reuse only PDF discovery/reference generation; this never invokes Vegeta.
sys.path.insert(0, str(ROOT / 'tests/performance/vegeta'))
from run import discover_pdfs

COMPOSE = ['docker', 'compose', '-f', 'compose.yaml', '-f', 'compose.traefik.yaml']
IMAGE = 'grafana/k6:2.2.0'


class WindowsGenerator:
    """Read native process/host memory and CPU with Windows APIs, no dependencies."""

    def __init__(self, pid):
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        class Memory(ctypes.Structure):
            _fields_ = [('length', wintypes.DWORD), ('load_percent', wintypes.DWORD)] + [
                (name, ctypes.c_ulonglong) for name in
                ('total_physical', 'available_physical', 'total_commit_limit',
                 'available_commit', 'total_virtual', 'available_virtual', 'extended_virtual')]
        class ProcessMemory(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('page_faults', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in
                ('peak_working_set', 'working_set', 'peak_paged_pool', 'paged_pool',
                 'peak_nonpaged_pool', 'nonpaged_pool', 'pagefile', 'peak_pagefile', 'private_bytes')]
        self.Memory, self.ProcessMemory = Memory, ProcessMemory
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.psapi = ctypes.WinDLL('psapi', use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(ctypes.c_ulonglong)] * 4
        self.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemory), wintypes.DWORD]
        self.handle = self.kernel.OpenProcess(0x1000 | 0x10, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def sample(self):
        c = self.ctypes
        host, process = self.Memory(), self.ProcessMemory()
        host.length, process.cb = c.sizeof(host), c.sizeof(process)
        if not self.kernel.GlobalMemoryStatusEx(c.byref(host)):
            raise c.WinError(c.get_last_error())
        memory_ok = self.psapi.GetProcessMemoryInfo(self.handle, c.byref(process), process.cb)
        created, ended, kernel, user = (c.c_ulonglong() for _ in range(4))
        times_ok = self.kernel.GetProcessTimes(self.handle, *(c.byref(v) for v in (created, ended, kernel, user)))
        return dict(host={name: getattr(host, name) for name, _ in host._fields_},
                    process={name: getattr(process, name) for name, _ in process._fields_} if memory_ok else None,
                    cpu_seconds=(kernel.value + user.value) / 10_000_000 if times_ok else None)

    def close(self):
        self.kernel.CloseHandle(self.handle)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf-dir', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--redis-db', type=int, choices=range(1, 16), required=True)
    parser.add_argument('--k6', type=Path, help='Use this native Windows executable instead of the historical Docker client')
    args = parser.parse_args()
    if not args.name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in args.name):
        parser.error('Use a simple unique evidence name')
    os.chdir(ROOT)
    destination = ROOT / 'tests/stress/results' / args.name
    if destination.exists():
        parser.error('Evidence already exists; use another name')
    commands = []

    def command(argv, *, env=None, output=None, timeout=180):
        commands.append(argv)
        result = subprocess.run(argv, env=env, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=timeout)
        if output:
            (destination / output).write_text(result.stdout + result.stderr, encoding='utf-8')
        if result.returncode:
            raise RuntimeError(f'Command failed ({result.returncode}): {argv}: {result.stderr}')
        return result.stdout.strip()

    def save(name, value):
        (destination / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')

    def states(ids=None):
        return json.loads(command(['docker', 'inspect', *(ids or command(COMPOSE + ['ps', '-q']).splitlines())], timeout=15))

    def redis(db):
        return int(command(COMPOSE + ['exec', '-T', 'redis', 'redis-cli', '--raw', '-n', str(db), 'DBSIZE']))

    def require(containers, db):
        apis = [c for c in containers if c['Config']['Labels']['com.docker.compose.service'] == 'extractor']
        assert len(containers) == 4 and len(apis) == 2, 'Require two APIs, Redis and Traefik'
        assert all(c['State'].get('Health', {}).get('Status') == 'healthy' for c in containers)
        for c in containers:
            role = c['Config']['Labels']['com.docker.compose.service']
            memory, cpu = {'extractor': (768, 1_000_000_000), 'redis': (256, 500_000_000),
                           'traefik': (512, 500_000_000)}[role]
            assert c['HostConfig']['Memory'] == memory * 1024 * 1024 and c['HostConfig']['NanoCpus'] == cpu
        for c in apis:
            assert not c['HostConfig'].get('PortBindings')
            assert {'CACHE_ENABLED=true', f'REDIS_URL=redis://redis:6379/{db}'}.issubset(c['Config']['Env'])
        return apis

    assert command(['git', 'branch', '--show-current']) == 'main'
    if args.k6:
        assert os.name == 'nt' and args.k6.is_file(), 'Require a native Windows k6 executable'
        args.k6 = args.k6.resolve()
        native_version = command([str(args.k6), 'version'])
    pdfs = discover_pdfs(args.pdf_dir.resolve())
    initial = states()
    require(initial, 0)
    assert redis(args.redis_db) == 0, 'Select an empty DB; never delete cache to prepare a run'
    client = 'pdf-extractor-k6-' + args.name
    assert not command(['docker', 'ps', '-aq', '--filter', f'name=^/{client}$'])
    destination.mkdir(parents=True)
    save('pdfs.json', pdfs)
    save('initial-containers.json', initial)
    save('environment.json', dict(docker=command(['docker', 'version', '--format', '{{.Server.Version}}']),
                                 compose=command(['docker', 'compose', 'version']),
                                 resources=command(['docker', 'info', '--format', 'CPUs={{.NCPU}} Memory={{.MemTotal}}']),
                                 generator='native Windows' if args.k6 else 'Docker',
                                 k6_version=native_version if args.k6 else IMAGE,
                                 python=sys.version,
                                 cache_start='COLD CACHE AL INICIO; no PDF preload',
                                 benchmark_db=args.redis_db, normal_db_initial_keys=redis(0)))
    up = ['up', '-d', '--no-deps', '--no-build', '--scale', 'extractor=2', '--wait', '--wait-timeout', '150', 'extractor']
    env = dict(os.environ, EXTRACTOR_BENCHMARK_REDIS_DB=str(args.redis_db))
    process, began, abort, client_state, native_monitor = None, None, None, None, None
    try:
        command(COMPOSE + ['-f', 'compose.cache-benchmark.yaml'] + up, env=env, output='isolated-up.log')
        isolated = states()
        apis = require(isolated, args.redis_db)
        assert redis(args.redis_db) == 0
        save('benchmark-containers.json', isolated)
        proxy = next(c for c in isolated if c['Config']['Labels']['com.docker.compose.service'] == 'traefik')
        proxy_ip = proxy['NetworkSettings']['Networks']['pdf-network']['IPAddress']
        servers = {c['NetworkSettings']['Networks']['pdf-network']['IPAddress'] + ':8000': c['Name'].lstrip('/') for c in apis}
        port = command(COMPOSE + ['port', 'traefik', '80']).rsplit(':', 1)[1]
        health_attempts = []
        for attempt in range(10):
            # Docker health and provider discovery do not converge at the same instant.
            prefix = f'{args.name}-health-{attempt}-'
            checks = []
            for n in range(6):
                req = urllib.request.Request(f'http://127.0.0.1:{port}/health',
                                             headers={'Host': 'localhost', 'X-Audit-Id': prefix + str(n)})
                with urllib.request.urlopen(req, timeout=10) as response:
                    body = json.load(response)
                    assert response.status == 200 and body == {'status': 'ok', 'service': 'extractor'}
                    checks.append(dict(status=response.status, body=body))
            time.sleep(0.2)
            health_logs = []
            for line in command(['docker', 'logs', proxy['Id']]).splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if str(row.get('request_X-Audit-Id', '')).startswith(prefix):
                    health_logs.append(row)
            distribution = Counter(servers.get(row.get('ServiceAddr'), 'UNKNOWN') for row in health_logs)
            health_attempts.append(dict(checks=checks, logs=health_logs, distribution=dict(distribution)))
            save('health-before.json', dict(checks=checks, logs=health_logs, distribution=dict(distribution),
                                           attempts=health_attempts))
            if len(health_logs) == 6 and set(distribution) == set(servers.values()):
                break
            time.sleep(2)
        else:
            raise RuntimeError('Traefik has not discovered both healthy replicas; do not start load')
        settings = dict(PDF_PATHS='|'.join(f'/pdfs/{n}.pdf' for n in range(1, 5)),
                        PDF_PAGES=','.join(str(p['page_count']) for p in pdfs),
                        PDF_CHARACTERS=','.join(str(p['content_characters']) for p in pdfs),
                        EXPECTED_CONTENT_SHA256S=','.join(p['content_sha256'] for p in pdfs),
                        EXTRACT_URL='http://localhost/extract', TRAEFIK_IP=proxy_ip,
                        TRAEFIK_HOST='localhost', RUN_ID=args.name, RESULT_FILE='/results/summary.json',
                        REQUEST_TIMEOUT='180s')
        mounts = ['--mount', f'type=bind,source={ROOT / "tests/performance"},target=/scripts,readonly',
                  '--mount', f'type=bind,source={destination},target=/results']
        for n, pdf in enumerate(pdfs, 1):
            mounts += ['--mount', f'type=bind,source={pdf["path"]},target=/pdfs/{n}.pdf,readonly']
        options = []
        for key, value in settings.items():
            options += ['-e', f'{key}={value}']
        native_env = None
        if args.k6:
            settings.update(PDF_PATHS='|'.join(p['path'] for p in pdfs),
                            EXTRACT_URL=f'http://127.0.0.1:{port}/extract', TRAEFIK_IP='',
                            RESULT_FILE=str(destination / 'summary.json'))
            native_env = dict(os.environ, **settings)
            inspect_command = [str(args.k6), 'inspect', '--include-system-env-vars', str(ROOT / 'tests/performance/spike.js')]
        else:
            inspect_command = ['docker', 'run', '--rm', '--network', 'none', '--cpus', '1', '--memory', '512m',
                               *mounts, *options, IMAGE, 'inspect', '--include-system-env-vars', '/scripts/spike.js']
        inspected = json.loads(command(inspect_command, env=native_env, output='k6-inspect.json'))
        scenario = inspected['scenarios']['official_spike']
        assert scenario['startVUs'] == 0 and [s['target'] for s in scenario['stages']] == [100, 100, 0]
        assert [s['duration'] for s in scenario['stages']] == ['10s', '20s', '10s']
        # k6 inspect performs no HTTP requests and does not populate Redis.
        assert redis(args.redis_db) == 0
        if args.k6:
            attack = [str(args.k6), 'run', '--no-color', '--log-format', 'json',
                      '--out', f'json={destination / "metrics.jsonl"}', str(ROOT / 'tests/performance/spike.js')]
        else:
            attack = ['docker', 'run', '--name', client, '--network', 'pdf-network', '--cpus', '1', '--memory', '512m',
                      *mounts, *options, IMAGE, 'run', '--no-color', '--log-format', 'json',
                      '--out', 'json=/results/metrics.jsonl', '/scripts/spike.js']
        save('k6-settings.json', dict(command=attack, environment=settings, image=None if args.k6 else IMAGE,
                                    generator='native Windows' if args.k6 else 'Docker',
                                    generator_limits=None if args.k6 else dict(cpus=1, memory_mib=512),
                                    script_sha256=hashlib.sha256((ROOT / 'tests/performance/spike.js').read_bytes()).hexdigest()))
        began = datetime.now(timezone.utc).isoformat()
        clock = time.perf_counter()
        samples = []
        print(json.dumps(dict(started_utc=began, profile='0->100 in 10s; 100 for 20s; 100->0 in 10s',
                              cache='COLD CACHE AL INICIO', command=attack)), flush=True)
        with (destination / 'k6.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(attack, env=native_env, stdout=log, stderr=subprocess.STDOUT)
            if args.k6:
                native_monitor = WindowsGenerator(process.pid)
                save('generator-before.json', dict(pid=process.pid, sample=native_monitor.sample()))
            while process.poll() is None:
                try:
                    live = states([c['Id'] for c in isolated])
                    current_client = None if args.k6 else json.loads(command(['docker', 'inspect', client], timeout=15))[0]
                    stats = command(['docker', 'stats', '--no-stream', '--format', '{{json .}}',
                                     *[c['Id'] for c in isolated], *([] if args.k6 else [client])], timeout=15)
                    samples.append(dict(elapsed_s=time.perf_counter() - clock,
                                        states=[dict(name=c['Name'], state=c['State']) for c in live],
                                        client_state=current_client['State'] if current_client else None,
                                        native_generator=native_monitor.sample() if native_monitor else None, stats=stats))
                    if any(c['State'].get('OOMKilled') for c in live) or (current_client and current_client['State'].get('OOMKilled')):
                        abort = 'OOM in a service or the k6 generator'
                        if args.k6:
                            process.terminate()
                        else:
                            command(['docker', 'stop', '--time', '1', client])
                        break
                except (RuntimeError, subprocess.TimeoutExpired) as exc:
                    try:
                        command(['docker', 'info', '--format', '{{.ServerVersion}}'], timeout=10)
                    except (RuntimeError, subprocess.TimeoutExpired):
                        abort = 'Docker unavailable: ' + str(exc)
                        process.terminate()
                        break
                    samples.append(dict(elapsed_s=time.perf_counter() - clock, telemetry_error=str(exc)))
                time.sleep(1)
            code = process.wait()
        if args.k6:
            save('generator-after.json', dict(pid=process.pid, exit_code=code, sample=native_monitor.sample()))
        else:
            client_state = json.loads(command(['docker', 'inspect', client]))[0]
            if client_state['State'].get('OOMKilled'):
                abort = 'k6 generator OOM'
            save('client-inspect.json', client_state)
        save('execution.json', dict(started_utc=began, exit_code=code, aborted=abort,
                                    wall_seconds=time.perf_counter() - clock, samples=samples))
        save('after-load-containers.json', states([c['Id'] for c in isolated]))
        for role, containers in [('traefik', [proxy]), ('extractor', apis)]:
            for n, container in enumerate(containers, 1):
                command(['docker', 'logs', '--since', began, container['Id']], output=f'{role}-{n}.log')
        access = []
        for line in (destination / 'traefik-1.log').read_text('utf-8').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if str(row.get('request_X-Audit-Id', '')).startswith(args.name + '-'):
                access.append(row)
        save('balance.json', dict(records=len(access), distribution=dict(Counter(servers.get(r.get('ServiceAddr'), 'UNKNOWN') for r in access)),
                                  status_codes=dict(Counter(str(r['DownstreamStatus']) for r in access))))
        (destination / 'traefik-access.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in access), 'utf-8')
        assert all(hashlib.sha256(Path(p['path']).read_bytes()).hexdigest() == p['sha256'] for p in pdfs)
        print(json.dumps(dict(exit_code=code, aborted=abort, wall_seconds=time.perf_counter() - clock,
                              summary_present=(destination / 'summary.json').exists())), flush=True)
    finally:
        if process is not None and process.poll() is None:
            if args.k6:
                process.terminate()
            else:
                command(['docker', 'stop', '--time', '1', client])
            process.wait(timeout=15)
        if native_monitor:
            native_monitor.close()
        if client_state is not None:
            command(['docker', 'rm', client])  # Only this new temporary client, after saving its state.
        for c in initial:
            if c['Config']['Labels']['com.docker.compose.service'] != 'extractor':
                now = states([c['Id']])[0]
                if not now['State']['Running']:
                    save(c['Name'].lstrip('/') + '-failure.json', now)
                    command(['docker', 'start', c['Id']])
        deadline = time.monotonic() + 150
        infra_ids = [c['Id'] for c in initial if c['Config']['Labels']['com.docker.compose.service'] != 'extractor']
        while not all(c['State'].get('Health', {}).get('Status') == 'healthy' for c in states(infra_ids)):
            if time.monotonic() > deadline:
                raise RuntimeError('Infrastructure has not recovered after the spike')
            time.sleep(1)
        command(COMPOSE + up, output='restore-up.log')
        final = states()
        require(final, 0)
        for old in initial:
            now = next(c for c in final if c['Name'] == old['Name'])
            assert now['Image'] == old['Image'] and sorted(now['Config']['Env']) == sorted(old['Config']['Env'])
        save('restored-containers.json', final)
        save('restoration.json', dict(restored=True, normal_db_keys=redis(0), benchmark_db_keys=redis(args.redis_db)))
        save('commands.json', commands)


if __name__ == '__main__':
    main()
