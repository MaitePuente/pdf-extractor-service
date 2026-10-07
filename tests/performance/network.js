// ONE diagnostic request, still through Traefik. Preserve Host: localhost
// while resolving it to Traefik's address on pdf-network.
import { extract, trends, thresholds, summary } from './common.js';

if (!__ENV.TRAEFIK_IP) throw new Error('TRAEFIK_IP is required');
export const options = {
  hosts: { localhost: __ENV.TRAEFIK_IP },
  scenarios: {
    controlled: { executor: 'per-vu-iterations', vus: 1, iterations: 1, maxDuration: '2m' },
  },
  summaryTrendStats: trends,
  summaryTimeUnit: 'ms',
  thresholds,
};
export default extract;
export const handleSummary = summary;
