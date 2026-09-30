#!/usr/bin/env bash
# Disposable synthetic stack only. No credentials, real models or paid requests.
set -euo pipefail
[[ "${1:-}" == "--confirm-disposable-stack" ]] || { echo 'Require --confirm-disposable-stack' >&2; exit 2; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PROJECT="loose_provider_smoke_${GITHUB_RUN_ID:-local}_$$"
OUT="${2:-$(mktemp -d "${TMPDIR:-/tmp}/loose-thread-provider-report.XXXXXXXX")}"
mkdir -p "$OUT"
chmod 700 "$OUT"
FIXTURE="$(mktemp -d "${TMPDIR:-/tmp}/loose-thread-provider-fixture.XXXXXXXX")"
chmod 700 "$FIXTURE"
# Never fall back to an operator's repository .env during fixture validation.
: > "$FIXTURE/compose.env"
export FAILURELENS_PROVIDER_ID=synthetic-provider-fixture
export FAILURELENS_PROVIDER_ALLOWED_PROJECT_IDS=provider-smoke-project
export FAILURELENS_PROVIDER_ENDPOINT=https://provider.fixture.invalid/v1/chat/completions
export FAILURELENS_PROVIDER_MODEL=test-fixture-not-a-model
export FAILURELENS_PROVIDER_PROXY_HOST=provider.fixture.invalid
export FAILURELENS_PROVIDER_DATABASE_PASSWORD=synthetic-database-canary-684
export FAILURELENS_PROVIDER_DATABASE_URL=postgresql+psycopg://failurelens:synthetic-database-canary-684@db:5432/failurelens
export FAILURELENS_PROVIDER_WORKER_ENV_FILE="$FIXTURE/worker.env"
export FAILURELENS_PROVIDER_API_ENV_FILE="$FIXTURE/api.env"
printf '%s\n' 'FAILURELENS_BOOTSTRAP_ADMIN_USERNAME=provider-bootstrap@example.test' 'FAILURELENS_BOOTSTRAP_ADMIN_PASSWORD=synthetic-bootstrap-canary-592' > "$FAILURELENS_PROVIDER_API_ENV_FILE"
chmod 600 "$FAILURELENS_PROVIDER_API_ENV_FILE"
printf '%s\n' 'FAILURELENS_PROVIDER_TOKEN=synthetic-worker-only-canary-534' > "$FAILURELENS_PROVIDER_WORKER_ENV_FILE"
chmod 600 "$FAILURELENS_PROVIDER_WORKER_ENV_FILE"
# JSON is valid YAML. Paths are data, never interpolated executable expressions.
python - "$ROOT" "$FIXTURE/compose.fixture.json" <<'PY'
import json, pathlib, sys
root, destination = sys.argv[1:]
mount = str(pathlib.Path(root) / 'integrations/provider') + ':/fixture:ro'
value = {'services': {
    'api': {'volumes': [mount]},
    'provider-worker': {'volumes': [mount], 'command': ['python', '/fixture/fixture_worker.py', '--confirm-disposable-stack']},
    'provider-proxy': {'volumes': [mount], 'environment': {'PYTHONPATH': '/app'},
        'extra_hosts': ['provider.fixture.invalid:127.0.0.1'],
        'command': ['python', '/fixture/fixture_proxy.py', '--confirm-disposable-stack']},
}}
pathlib.Path(destination).write_text(json.dumps(value))
PY
compose() { docker compose --env-file "$FIXTURE/compose.env" -f compose.yaml -f compose.provider.yaml -f "$FIXTURE/compose.fixture.json" --profile provider -p "$PROJECT" "$@"; }
cleanup() {
  local result=$?
  compose logs --no-color > "$OUT/compose.log" 2>&1 || true
  # Logs are retained, including on failure; never echo request/exception details.
  if [[ "$result" != 0 ]]; then echo 'Provider fixture gate failed; retained scoped evidence' >&2; fi
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf -- "$FIXTURE"
}
trap cleanup EXIT
compose config --quiet
# Actual Compose must reject missing and empty operator DB values before startup.
# Only quiet validation is permitted; never emit expanded connection credentials.
for required in FAILURELENS_PROVIDER_DATABASE_URL FAILURELENS_PROVIDER_DATABASE_PASSWORD; do
  if (unset "$required"; compose config --quiet) >/dev/null 2>&1; then
    echo 'Missing operator database setting unexpectedly accepted' >&2
    exit 1
  fi
  if (export "$required="; compose config --quiet) >/dev/null 2>&1; then
    echo 'Empty operator database setting unexpectedly accepted' >&2
    exit 1
  fi
done
compose up --build --wait --wait-timeout 180
for service in api worker provider-worker provider-proxy; do
  [[ "$(compose exec -T "$service" id -u)" != "0" ]] || { echo 'Runtime UID gate failed' >&2; exit 1; }
done
# Check the actual container networks, not just the YAML declaration.
for service in api worker provider-worker provider-proxy db; do
  docker inspect "$(compose ps -q "$service")" > "$FIXTURE/$service.json"
done
python - "$PROJECT" "$FIXTURE" "$OUT/topology.json" <<'PY'
import json, pathlib, subprocess, sys
project, source, output = sys.argv[1:]
expected = {'db': {'failurelens'}, 'api': {'failurelens'}, 'worker': {'failurelens'},
    'provider-worker': {'failurelens', 'provider-egress'},
    'provider-proxy': {'provider-egress', 'provider-outbound'}}
result = {}
for service, names in expected.items():
    item = json.loads((pathlib.Path(source) / (service + '.json')).read_text())[0]
    actual = item['NetworkSettings']['Networks']
    assert set(actual) == {project + '_' + name for name in names}, 'unexpected runtime networks'
    environment = item['Config']['Env']
    has_token = any(x.startswith('FAILURELENS_PROVIDER_TOKEN=') for x in environment)
    assert has_token == (service == 'provider-worker'), 'provider credential isolation failed'
    has_bootstrap = any(x.startswith('FAILURELENS_BOOTSTRAP_ADMIN_PASSWORD=') for x in environment)
    assert has_bootstrap == (service == 'api'), 'bootstrap credential isolation failed'
    if service in {'api', 'worker', 'provider-worker'}:
        assert 'FAILURELENS_DEMO_MODE=false' in environment
        assert 'FAILURELENS_SESSION_COOKIE_SECURE=true' in environment
        assert 'FAILURELENS_DATABASE_URL=postgresql+psycopg://failurelens:synthetic-database-canary-684@db:5432/failurelens' in environment
    if service == 'db':
        assert 'POSTGRES_PASSWORD=synthetic-database-canary-684' in environment
    assert not any(x.startswith(('HTTP_PROXY=', 'HTTPS_PROXY=', 'ALL_PROXY=')) for x in environment)
    if service == 'provider-proxy':
        assert item['HostConfig']['PortBindings'] in (None, {}), 'proxy port published'
        (pathlib.Path(source) / 'proxy-addresses.json').write_text(json.dumps([x['IPAddress'] for x in actual.values()]))
    result[service] = {'networks': sorted(names), 'provider_token_present': has_token}
for name in ('failurelens', 'provider-egress'):
    network = json.loads(subprocess.check_output(['docker', 'network', 'inspect', project + '_' + name]))[0]
    assert network['Internal'] is True, 'runtime network is not internal'
pathlib.Path(output).write_text(json.dumps({'status': 'passed', 'actual_containers': result}, sort_keys=True))
PY
PROXY_ADDRESSES="$(cat "$FIXTURE/proxy-addresses.json")"
# The original default Internet denial remains mandatory for API and both workers.
# Direct proxy IP checks detect cross-bridge leakage even when DNS hides its name.
for service in api worker provider-worker; do
  compose exec -T "$service" python - "$service" "$PROXY_ADDRESSES" <<'PY'
import json, os, socket, sys
service, addresses = sys.argv[1], json.loads(sys.argv[2])
def denied(host, port):
    try:
        connection = socket.create_connection((host, port), timeout=2)
    except OSError:
        return
    connection.close()
    raise AssertionError('runtime network boundary failed')
denied('1.1.1.1', 443)
if service != 'provider-worker':
    assert 'FAILURELENS_PROVIDER_TOKEN' not in os.environ
    denied('provider-proxy', 8080)
    for address in addresses:
        denied(address, 8080)
        denied(address, 8081)
else:
    def request(port, authority):
        connection = socket.create_connection(('provider-proxy', port), timeout=3)
        connection.sendall(('CONNECT ' + authority + ' HTTP/1.1\r\nHost: ' + authority + '\r\n\r\n').encode())
        return connection, connection.recv(4096)
    connection, response = request(8080, 'unknown.fixture.invalid:443')
    with connection:
        assert b'403 Forbidden' in response
    # This listener uses real OS resolution of /etc/hosts and the production
    # address validator. Its configured authority resolves to loopback.
    connection, response = request(8081, 'provider.fixture.invalid:443')
    with connection:
        assert b'403 Forbidden' in response
    # Only this fixture listener replaces the connector with a socket pair.
    connection, response = request(8080, 'provider.fixture.invalid:443')
    with connection:
        assert b'200 Connection Established' in response
        connection.sendall(b'synthetic-tunnel-canary-904')
        assert connection.recv(4096) == b'synthetic-tunnel-canary-904'
print('runtime_provider_network_checks_passed')
PY
done
compose exec -T api python /fixture/fixture_check.py --confirm-disposable-stack > "$OUT/result.json"
# The normal durable worker remains able to ingest while optional work is enabled.
for phase in enabled stopped; do
  if [[ "$phase" == stopped ]]; then compose stop provider-worker provider-proxy; fi
  compose exec -T api python - "$phase" <<'PY' > "$OUT/ordinary-worker-$phase.json"
import json, sys, time
import httpx
phase = sys.argv[1]
with httpx.Client(base_url='http://127.0.0.1:8000', timeout=5, trust_env=False) as client:
    login = client.post('/api/v1/auth/login', json={'username': 'provider-fixture@example.test', 'password': 'disposable-fixture-only-593'})
    login.raise_for_status()
    assert login.json()['principal']['demo_mode'] is False
    client.headers['Authorization'] = 'Bearer ' + login.json()['access_token']
    response = client.post('/api/v1/projects/provider-smoke-project/ingestions',
        params={'external_id': 'ordinary-worker-provider-' + phase, 'filename': 'report.xml'},
        headers={'content-type': 'application/xml'},
        content=b'<testsuite><testcase name="ordinary-offline-worker"><failure>Timeout waiting for selector</failure></testcase></testsuite>')
    response.raise_for_status()
    ingestion_id = response.json()['id']
    deadline = time.monotonic() + 45
    while True:
        result = client.get('/api/v1/ingestions/' + ingestion_id)
        result.raise_for_status()
        state = result.json()['state']
        if state == 'succeeded':
            break
        assert state not in {'failed', 'dead_lettered', 'cancelled'}
        assert time.monotonic() < deadline
        time.sleep(.1)
    client.get('/api/v1/overview').raise_for_status()
print(json.dumps({'status': 'passed', 'ordinary_ingestion': state, 'provider_services': phase}))
PY
done
compose logs --no-color > "$OUT/compose.log"
python - "$OUT/compose.log" <<'PY'
import pathlib, sys
raw = pathlib.Path(sys.argv[1]).read_text()
canaries = ('synthetic-worker-only-canary-534', 'synthetic-evidence-canary-935',
    'synthetic-transport-canary-716', 'synthetic-tunnel-canary-904', 'disposable-fixture-only-593',
    'synthetic-bootstrap-canary-592', 'synthetic-database-canary-684')
assert not any(x in raw for x in canaries), 'sensitive-canary exclusion failed'
PY
# Losing the optional worker/proxy never removes core application readiness.
curl --fail --silent http://127.0.0.1:8000/health/ready > "$OUT/provider-down-readiness.json"
cat "$OUT/result.json"
