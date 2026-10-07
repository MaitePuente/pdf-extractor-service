import http from 'k6/http';
import { check } from 'k6';
import crypto from 'k6/crypto';
import exec from 'k6/execution';
import { Rate } from 'k6/metrics';

if (!__ENV.EXTRACT_URL || !__ENV.PDF_PATH) {
  throw new Error('EXTRACT_URL (Traefik) and PDF_PATH are required');
}
const paths = (__ENV.PDF_PATHS || __ENV.PDF_PATH).split('|');
const pages = (__ENV.PDF_PAGES || '279').split(',').map(Number);
if (pages.length !== paths.length) throw new Error('PDF_PAGES must match PDF_PATHS');
const files = paths.map((path) => open(path, 'b'));
const expectedCache = __ENV.EXPECT_CACHE || 'BYPASS';
if (!['BYPASS', 'HIT', 'MISS'].includes(expectedCache)) throw new Error('Invalid EXPECT_CACHE');
const logicalErrors = new Rate('extract_errors');

export function extract() {
  const index = __ITER % files.length;
  const auditId = `${__ENV.RUN_ID || 'baseline'}-${__VU}-${__ITER}`;
  const response = http.post(__ENV.EXTRACT_URL, files[index], {
    headers: { 'Content-Type': 'application/pdf', 'X-Audit-Id': auditId },
    timeout: __ENV.REQUEST_TIMEOUT || '180s',
    tags: { cache_mode: expectedCache, name: 'POST /extract via Traefik' },
  });
  let data = null;
  try { data = response.json(); } catch (_) { /* Report a logical error below. */ }
  const valid = check(response, {
    'HTTP 200': (r) => r.status === 200,
    'expected page_count': () => data !== null && data.page_count === pages[index],
    'content is Markdown string': () => data !== null && typeof data.content === 'string',
    'expected X-Cache': (r) => r.headers['X-Cache'] === expectedCache,
    'same Markdown SHA-256': () => !__ENV.EXPECTED_CONTENT_SHA256 ||
      (data !== null && typeof data.content === 'string' && crypto.sha256(data.content, 'hex') === __ENV.EXPECTED_CONTENT_SHA256),
  });
  logicalErrors.add(!valid);
  console.log(JSON.stringify({
    audit_id: auditId, status: response.status, cache: response.headers['X-Cache'],
    page_count: data && data.page_count, characters: data && data.content && data.content.length,
    content_sha256: data && typeof data.content === 'string' ? crypto.sha256(data.content, 'hex') : null,
    duration_ms: response.timings.duration, sending_ms: response.timings.sending,
    waiting_ms: response.timings.waiting, receiving_ms: response.timings.receiving,
    blocked_ms: response.timings.blocked, error: response.error || null,
  }));
  if (!valid) exec.test.abort(`Invalid extraction response: ${auditId}`);
}

export const trends = ['avg', 'min', 'med', 'p(90)', 'p(95)', 'max'];
export const thresholds = {
  checks: ['rate==1'],
  http_req_failed: ['rate==0'],
  extract_errors: ['rate==0'],
  http_req_duration: ['p(95)<400'],
};

export function summary(data) {
  if (!__ENV.RESULT_FILE) throw new Error('RESULT_FILE is required to retain evidence');
  return { [__ENV.RESULT_FILE]: JSON.stringify(data, null, 2) };
}
