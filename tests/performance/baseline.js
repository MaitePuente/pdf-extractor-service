import { extract, trends, thresholds, summary } from './common.js';

export const options = {
  scenarios: {
    controlled: {
      executor: 'per-vu-iterations',
      vus: Number(__ENV.VUS || 1),
      iterations: Number(__ENV.ITERATIONS_PER_VU || 1),
      maxDuration: '30m',
    },
  },
  summaryTrendStats: trends,
  summaryTimeUnit: 'ms',
  thresholds,
};
export default extract;
export const handleSummary = summary;
