import http from 'k6/http';
import { check } from 'k6';
export const options = { vus: 1, iterations: 3, thresholds: { http_req_failed: ['rate==0'] } };
export default function () {
  const control = http.get('http://127.0.0.1:8779/ok');
  check(control, { 'control is 200': r => r.status === 200 });
  const intervention = http.get('http://127.0.0.1:8779/down');
  check(intervention, { 'intervention is 503': r => r.status === 503 });
}
export function handleSummary(data) {
  return { [`${__ENV.PRODUCER_OUTPUT}/k6.json`]: JSON.stringify(data, null, 2) };
}
