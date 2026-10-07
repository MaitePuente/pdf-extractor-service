// Official four-document spike; failures are measurements, never an early abort.
import http from 'k6/http';
import { check } from 'k6';
import crypto from 'k6/crypto';
import exec from 'k6/execution';
import { Counter, Rate } from 'k6/metrics';

const paths = (__ENV.PDF_PATHS || '').split('|');
const pages = (__ENV.PDF_PAGES || '').split(',').map(Number);
const hashes = (__ENV.EXPECTED_CONTENT_SHA256S || '').split(',');
const characters = (__ENV.PDF_CHARACTERS || '').split(',').map(Number);
if (!__ENV.EXTRACT_URL || paths.length !== 4 || pages.length !== 4 ||
    hashes.length !== 4 || characters.length !== 4 || !__ENV.RESULT_FILE) {
  throw new Error('Require Traefik URL, four PDF paths/pages/content hashes/lengths and RESULT_FILE');
}
// Load each binary once in init; reuse its ArrayBuffer without per-request reads.
// k6 keeps a copy per VU: monitor the native generator's memory as well as Docker.
const files = paths.map((path) => open(path, 'b'));
const sizes = files.map((file) => file.byteLength);
const startedIterations = new Counter('spike_iterations_started');
const startedRequests = new Counter('spike_requests_started');
const responses = new Counter('spike_responses');
const logicalErrors = new Rate('extract_errors');

export const options = {
  hosts: __ENV.TRAEFIK_IP ? { localhost: __ENV.TRAEFIK_IP } : {},
  scenarios: {
    official_spike: {
      executor: 'ramping-vus', startVUs: 0,
      stages: [
        { duration: '10s', target: 100 },
        { duration: '20s', target: 100 },
        { duration: '10s', target: 0 },
      ],
      gracefulRampDown: '0s', gracefulStop: '0s',
    },
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'max'],
  summaryTimeUnit: 'ms',
  thresholds: {
    checks: ['rate==1'],
    http_req_failed: ['rate==0'],
    extract_errors: ['rate==0'],
    http_req_duration: ['p(95)<400'],
  },
};

export function setup() {
  console.log(JSON.stringify({ event: 'spike_start', cache: 'COLD CACHE AL INICIO',
    profile: '0->100 in 10s; 100 for 20s; 100->0 in 10s', pdf_bytes: sizes }));
}

export default async function () {
  const iteration = exec.scenario.iterationInTest;
  const index = iteration % files.length;
  const auditId = `${__ENV.RUN_ID || 'official-spike'}-${__VU}-${__ITER}`;
  const tags = { pdf: String(index + 1), audit_id: auditId };
  startedIterations.add(1, tags);
  const body = files[index];
  startedRequests.add(1, tags);
  const response = http.post(__ENV.EXTRACT_URL, body, {
    headers: { 'Content-Type': 'application/pdf', 'Host': __ENV.TRAEFIK_HOST || 'localhost',
      'X-Audit-Id': auditId, 'Accept-Encoding': 'identity' },
    // Preserve the existing spike's default HTTP timeout and zero graceful stop.
    timeout: __ENV.REQUEST_TIMEOUT || '180s',
    tags: { ...tags, name: 'POST /extract via Traefik' },
  });
  let data = null;
  try { data = response.json(); } catch (_) { /* Retain failed/invalid responses. */ }
  const content = data && typeof data.content === 'string' ? data.content : null;
  const sha = content === null ? null : crypto.sha256(content, 'hex');
  const cache = response.headers['X-Cache'] || 'ABSENT';
  const valid = check(response, {
    'HTTP 200': (r) => r.status === 200,
    'expected page_count': () => data !== null && data.page_count === pages[index],
    'content is Markdown string': () => content !== null,
    'same Markdown length and SHA-256': () => content !== null &&
      content.length === characters[index] && sha === hashes[index],
    'recognized X-Cache': () => ['MISS', 'HIT', 'ERROR', 'BYPASS'].includes(cache),
  }, { pdf: tags.pdf });
  logicalErrors.add(!valid);
  responses.add(1, { status: String(response.status), cache });
  console.log(JSON.stringify({ audit_id: auditId, pdf: index + 1, status: response.status,
    cache, error: response.error || null, error_code: response.error_code || 0,
    valid, page_count: data && data.page_count, characters: content && content.length,
    content_sha256: sha, duration_ms: response.timings.duration,
    sending_ms: response.timings.sending, waiting_ms: response.timings.waiting,
    receiving_ms: response.timings.receiving, blocked_ms: response.timings.blocked }));
}

export function teardown() {
  console.log(JSON.stringify({ event: 'spike_finished' }));
}

export function handleSummary(data) {
  return { [__ENV.RESULT_FILE]: JSON.stringify(data, null, 2) };
}
