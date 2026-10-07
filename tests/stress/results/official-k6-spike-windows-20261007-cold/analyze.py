"""Recompute the recorded native spike report; no network, Docker or load calls."""
from collections import Counter, defaultdict
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_text('utf-8'))


def distribution(values):
    values = sorted(values)
    if not values:
        return None
    def quantile(fraction):
        position = (len(values) - 1) * fraction
        lower = int(position)
        return values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (position - lower)
    return dict(count=len(values), min=values[0], p50=quantile(.5), p90=quantile(.9),
                p95=quantile(.95), max=values[-1])


summary = read('summary.json')
metrics = summary['metrics']
responses = []
events = []
for line in (ROOT / 'k6.log').read_text('utf-8').splitlines():
    try:
        row = json.loads(json.loads(line).get('msg', ''))
    except (ValueError, TypeError):
        continue
    if 'audit_id' in row:
        responses.append(row)
    elif 'event' in row:
        events.append(row)

started = Counter()
request_ids = set()
http_points = []
vus = []
for line in (ROOT / 'metrics.jsonl').open(encoding='utf-8'):
    row = json.loads(line)
    if row['type'] != 'Point':
        continue
    data = row['data']
    if row['metric'] == 'spike_requests_started':
        started[data['tags']['pdf']] += data['value']
        request_ids.add(data['tags']['audit_id'])
    elif row['metric'] == 'http_req_duration':
        http_points.append(data)
    elif row['metric'] == 'vus':
        vus.append(dict(time=data['time'], value=data['value']))

responded_ids = {r['audit_id'] for r in responses}
interrupted_ids = request_ids - responded_ids
assert len(http_points) == len(responses) == metrics['http_reqs']['values']['count'] == 179
assert len(request_ids) == metrics['spike_requests_started']['values']['count'] == 279
assert len(interrupted_ids) == 100
assert all(r['valid'] for r in responses if r['status'] == 200)

profiles = []
for number in (1, 2):
    for line in (ROOT / f'extractor-{number}.log').read_text('utf-8').splitlines():
        if line.startswith('PROFILE '):
            row = json.loads(line[8:])
            if str(row.get('audit_id', '')).startswith(ROOT.name + '-'):
                profiles.append(row)

resources = defaultdict(lambda: dict(max_cpu_percent=0, max_memory_mib=0))
execution = read('execution.json')
samples = execution['samples']
cpu_intervals = []
previous_time = 0
previous_cpu = read('generator-before.json')['sample']['cpu_seconds']
for sample in samples:
    for line in sample.get('stats', '').splitlines():
        row = json.loads(line)
        resource = resources[row['Name']]
        resource['max_cpu_percent'] = max(resource['max_cpu_percent'], float(row['CPUPerc'].rstrip('%')))
        memory = row['MemUsage'].split(' / ')[0]
        factors = {'MiB': 1, 'GiB': 1024, 'KiB': 1 / 1024, 'B': 1 / 1048576}
        unit = next(u for u in factors if memory.endswith(u))
        resource['max_memory_mib'] = max(resource['max_memory_mib'], float(memory[:-len(unit)]) * factors[unit])
    native = sample.get('native_generator')
    if native and native['cpu_seconds'] is not None:
        cpu_intervals.append((native['cpu_seconds'] - previous_cpu) / (sample['elapsed_s'] - previous_time) * 100)
        previous_time, previous_cpu = sample['elapsed_s'], native['cpu_seconds']

native = read('generator-after.json')['sample']
before = read('generator-before.json')['sample']
after_containers = read('after-load-containers.json')
final_containers = read('final-containers.json')
access = [json.loads(line) for line in (ROOT / 'traefik-access-final.jsonl').read_text('utf-8').splitlines()]
assert len(access) == len({r['request_X-Audit-Id'] for r in access}) == len(request_ids)
assert {r['request_X-Audit-Id'] for r in access} == request_ids
assert max(v['value'] for v in vus) == 100
assert '000/100 VUs, 179 complete and 100 interrupted iterations' in (ROOT / 'k6.log').read_text('utf-8')
report = dict(
    completed_nominal_40_seconds=True, nominal_profile_seconds=40,
    measured_test_seconds=summary['state']['testRunDurationMs'] / 1000,
    launcher_wall_seconds=execution['wall_seconds'], exit_code=execution['exit_code'], aborted=execution['aborted'],
    requests_initiated=len(request_ids), initiated_by_pdf=dict(started),
    completed_http_requests=metrics['http_reqs']['values']['count'],
    completed_http_requests_per_second=metrics['http_reqs']['values']['rate'],
    interrupted_iterations=len(interrupted_ids),
    http_status=dict(Counter(str(r['status']) for r in responses)),
    http_req_failed=metrics['http_req_failed']['values'], checks=metrics['checks']['values'],
    http_latency_ms=metrics['http_req_duration']['values'],
    valid_successes=sum(r['valid'] for r in responses),
    success_throughput_per_second=sum(r['valid'] for r in responses) / (summary['state']['testRunDurationMs'] / 1000),
    unsuccessful_or_interrupted_fraction=(len(request_ids) - sum(r['valid'] for r in responses)) / len(request_ids),
    timeouts_observed=sum(r['tags'].get('error_code') == '1050' for r in http_points),
    connection_errors_observed=sum(str(r['tags'].get('error_code', '')).startswith(('11', '12', '13')) for r in http_points),
    cache_headers=dict(Counter(r['cache'] for r in responses)),
    cache_status_unknown_responses=sum(r['cache'] == 'ABSENT' for r in responses),
    client_timing_ms={key: distribution([r[key] for r in responses]) for key in
                      ('duration_ms', 'sending_ms', 'waiting_ms', 'receiving_ms', 'blocked_ms')},
    latency_200_only_ms=distribution([r['duration_ms'] for r in responses if r['status'] == 200]),
    responses_by_pdf={str(index): dict(status=dict(Counter(str(r['status']) for r in responses if r['pdf'] == index)),
                                      cache=dict(Counter(r['cache'] for r in responses if r['pdf'] == index)))
                      for index in range(1, 5)},
    data_sent_bytes=metrics['data_sent']['values']['count'], data_received_bytes=metrics['data_received']['values']['count'],
    initial_proxy_access_snapshot=read('balance.json'), final_proxy_access=read('balance-final.json'),
    interrupted_proxy_status=dict(Counter(str(r['DownstreamStatus']) for r in access if r['request_X-Audit-Id'] in interrupted_ids)),
    server_profiles=dict(count=len(profiles), cache_counts=dict(Counter(r.get('cache') for r in profiles)),
                         timing_ms={key: distribution([r[key] for r in profiles if key in r]) for key in
                                    ('receive_body_ms', 'redis_get_ms', 'extraction_ms', 'worker_ms', 'total_server_ms')},
                         warning='Profiles include work continuing after client cancellation; not the same population as HTTP results.'),
    docker_resource_maxima_sampled=dict(resources), telemetry_samples=len(samples),
    native_generator=dict(pid=read('generator-after.json')['pid'],
                          peak_working_set_bytes=native['process']['peak_working_set'],
                          peak_commit_bytes=native['process']['peak_pagefile'],
                          total_cpu_seconds=native['cpu_seconds'], max_sampled_cpu_one_core_percent=max(cpu_intervals),
                          page_faults=native['process']['page_faults'],
                          total_physical_bytes=before['host']['total_physical'],
                          available_physical_before_bytes=before['host']['available_physical'],
                          min_sampled_available_physical_bytes=min(s['native_generator']['host']['available_physical'] for s in samples),
                          min_sampled_available_commit_bytes=min(s['native_generator']['host']['available_commit'] for s in samples),
                          note='Windows peak process counters; page faults include soft faults, not a count of disk paging alone.'),
    oom_after_load={c['Name'].lstrip('/'): c['State']['OOMKilled'] for c in after_containers},
    final_health={c['Name'].lstrip('/'): c['State']['Health']['Status'] for c in final_containers},
    restoration=read('restoration.json'), tests=read('tests.json'), cache_integrity=read('cache-after.json'),
    events=events,
    professor=dict(requests=1037, requests_per_second=25.35, error_fraction=0,
                   p50_ms=1880, p90_ms=7830, p95_ms=8800, max_ms=13940),
    limitations=['HTTP metrics/checks exclude the 100 interrupted iterations; zero graceful times are unchanged.',
                 'No timeout/connection error observed in 179 results; canceled requests did not wait for the 180s timeout.',
                 'Final proxy logs include late completion and restoration effects, not only responses received by k6.',
                 'Started cold, then mixed MISS/HIT: HIT latency is not extraction time.',
                 'Host physical memory pressure and paging can influence latency; no isolated component bottleneck proven.'])
(ROOT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
(ROOT / 'responses.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in responses), 'utf-8')
(ROOT / 'server-profiles.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in profiles), 'utf-8')
(ROOT / 'vus.json').write_text(json.dumps(vus, indent=2) + '\n', 'utf-8')
print(json.dumps({k: report[k] for k in ('completed_nominal_40_seconds', 'http_status', 'http_latency_ms',
                                       'interrupted_proxy_status', 'native_generator', 'latency_200_only_ms')}, indent=2))
