// Bounded HOT tests on pdf-network, through Traefik with Host: localhost.
import { extract, trends, thresholds, summary } from './common.js';

const vus = Number(__ENV.VUS || 1);
const total = Number(__ENV.ITERATIONS_TOTAL || 20);
if (!__ENV.TRAEFIK_IP || ![1, 2, 5].includes(vus) || total % vus !== 0 || total > 25 || total < 1) {
  throw new Error('Require Traefik IP, 1/2/5 VUs, and 1..25 total iterations divisible by VUs');
}
export const options = {
  hosts: { localhost: __ENV.TRAEFIK_IP },
  scenarios: {
    controlled: {
      executor: 'per-vu-iterations', vus, iterations: total / vus,
      maxDuration: '30s', gracefulStop: '0s',
    },
  },
  summaryTrendStats: trends,
  summaryTimeUnit: 'ms',
  thresholds,
};
export default extract;
export const handleSummary = summary;
