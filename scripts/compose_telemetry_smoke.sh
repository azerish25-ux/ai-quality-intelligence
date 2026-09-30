#!/usr/bin/env bash
# Actual disposable PostgreSQL/API/worker -> local OTLP collector -> viewer check.
set -euo pipefail
[[ "${1:-}" == "--confirm-disposable-stack" ]] || { echo 'Require --confirm-disposable-stack' >&2; exit 2; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PROJECT="loose_telemetry_smoke_${GITHUB_RUN_ID:-local}_$$"
OUT="${2:-$(mktemp -d "${TMPDIR:-/tmp}/loose-thread-telemetry.XXXXXXXX")}"
mkdir -p "$OUT"
chmod 700 "$OUT"
compose() { docker compose -f compose.yaml -f compose.telemetry.yaml --profile telemetry -p "$PROJECT" "$@"; }
cleanup() {
  local result=$?
  compose logs --no-color > "$OUT/compose.log" 2>&1 || true
  if [[ "$result" != 0 ]]; then tail -200 "$OUT/compose.log" >&2; fi
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT
compose config --quiet
compose up --build --wait --wait-timeout 180
# Collector has no shell; inspect declared runtime UID and actual isolated network.
[[ "$(docker inspect --format '{{.Config.User}}' "$(compose ps -q otel-collector)")" == '10001:10001' ]]
compose exec -T api python - <<'PY' > "$OUT/result.json"
import json, socket, time
import httpx
base = 'http://127.0.0.1:8000'
query = 'http://otel-collector:16686'
trace_id = '1234567890abcdef1234567890abcdef'
required = {'http', 'job', 'ingestion', 'parsing', 'analysis', 'evidence', 'persistence'}
with httpx.Client(timeout=5, trust_env=False) as client:
    project = client.post(base + '/api/v1/projects', json={'slug': 'telemetry-smoke', 'name': 'Synthetic tracing verification'})
    project.raise_for_status()
    response = client.post(base + '/api/v1/projects/' + project.json()['id'] + '/ingestions',
        params={'external_id': 'telemetry-synthetic-run', 'filename': 'report.xml'},
        headers={'content-type': 'application/xml', 'traceparent': '00-' + trace_id + '-1234567890abcdef-01',
                 'baggage': 'private_canary=must-never-export-852'},
        content=b'<testsuite><testcase name="private-canary-624"><failure>Timeout waiting for selector token=secret-canary-935</failure></testcase></testsuite>')
    response.raise_for_status()
    ingestion_id = response.json()['id']
    for _ in range(60):
        state = client.get(base + '/api/v1/ingestions/' + ingestion_id).json()['state']
        if state == 'succeeded':
            break
        assert state not in {'failed', 'dead_lettered', 'cancelled'}, state
        time.sleep(.5)
    assert state == 'succeeded', state
    names = set()
    for _ in range(60):
        response = client.get(query + '/api/traces/' + trace_id)
        if response.status_code == 200:
            raw = response.text
            assert not any(secret in raw for secret in ['must-never-export-852', 'private-canary-624', 'secret-canary-935'])
            data = response.json().get('data', [])
            names = {span['operationName'].removeprefix('failurelens.') for item in data for span in item['spans']}
            if required <= names:
                break
        time.sleep(.5)
    assert required <= names, sorted(names)
    metrics = client.get(base + '/api/v1/operations/telemetry')
    metrics.raise_for_status()
    assert metrics.json()['export_enabled'] is True
    try:
        socket.create_connection(('1.1.1.1', 443), timeout=2)
    except OSError:
        pass
    else:
        raise AssertionError('Enabling local telemetry enabled runtime Internet access')
    print(json.dumps({'status': 'passed', 'scope': 'synthetic_actual_local_collector',
        'durable_job': state, 'trace_stages': sorted(names), 'sensitive_canaries_absent': True,
        'runtime_external_network_blocked': True}))
PY
curl --fail --silent http://127.0.0.1:16686/ > "$OUT/viewer.html"
curl --fail --silent http://127.0.0.1:16686/api/services > "$OUT/services.json"
python - "$OUT/services.json" <<'PY'
import json, sys
assert 'loose-thread' in json.load(open(sys.argv[1]))['data']
PY
# Collector loss must never disable core requests or worker operation.
compose stop otel-collector
curl --fail --silent http://127.0.0.1:8000/health/ready > "$OUT/collector-down-readiness.json"
curl --fail --silent http://127.0.0.1:8000/api/v1/overview > "$OUT/collector-down-overview.json"
cat "$OUT/result.json"
