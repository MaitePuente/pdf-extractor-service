import { extract, trends, thresholds, summary } from './common.js';

export const options = {
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
  summaryTrendStats: trends, summaryTimeUnit: 'ms', thresholds,
};
export default extract;
export const handleSummary = summary;
