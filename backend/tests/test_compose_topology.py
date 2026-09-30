from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_only_fixed_route_gateway_can_reach_edge_network():
    config = yaml.safe_load((ROOT / "compose.yaml").read_text())
    assert config["networks"]["failurelens"]["internal"] is True
    for service in ("db", "api", "worker"):
        assert config["services"][service]["networks"] == ["failurelens"]
        assert not config["services"][service].get("ports")
    gateway = config["services"]["dashboard"]
    assert set(gateway["networks"]) == {"failurelens", "edge"}
    assert set(gateway["ports"]) == {"127.0.0.1:8080:8080", "127.0.0.1:8000:8000"}
    nginx = (ROOT / "frontend/nginx.conf").read_text()
    assert "listen 8000;" in nginx and "listen 8080;" in nginx
    assert "proxy_pass http://api:8000;" in nginx
    assert "proxy_pass $" not in nginx


def test_recovery_gate_keeps_real_failure_assertions_and_disposable_scope():
    script = (ROOT / "scripts/compose_recovery_smoke.sh").read_text()
    assert "--confirm-disposable-stack" in script
    assert 'docker compose -p "$PROJECT"' in script
    assert "Runtime external-network isolation failed" in script
    assert "pg_restore" in script and "--single-transaction --exit-on-error" in script
    assert "report_snapshot(session,runs[0])" in script


def test_restore_extracts_before_application_import_initializes_storage():
    script = (ROOT / "scripts/compose_recovery_smoke.sh").read_text()
    restore = script.split("--entrypoint python api -c", 1)[1]
    assert restore.index("root.mkdir()") < restore.index("archive.extractall(")
    assert restore.index("archive.extractall(") < restore.index("from failurelens.")
    # Existing destinations must still be rejected, never overwritten silently.
    assert "root.mkdir(exist_ok=True)" not in restore


def test_application_images_keep_locked_dependencies_and_nonroot_gateway():
    backend = (ROOT / "backend/Dockerfile").read_text()
    frontend = (ROOT / "frontend/Dockerfile").read_text()
    assert "--require-hashes -r /app/backend/requirements-runtime.lock" in backend
    assert "USER failurelens" in backend
    assert "nginxinc/nginx-unprivileged:1.27-alpine" in frontend
    smoke = (ROOT / "scripts/compose_recovery_smoke.sh").read_text()
    assert "for service in api worker dashboard" in smoke
    assert "runs as root" in smoke


def test_optional_telemetry_is_local_bounded_and_never_exposed_as_otlp_ingress():
    base = yaml.safe_load((ROOT / "compose.yaml").read_text())
    overlay = yaml.safe_load((ROOT / "compose.telemetry.yaml").read_text())
    for service in ("api", "worker"):
        assert (
            "FAILURELENS_TELEMETRY_EXPORT_ENABLED"
            not in base["services"][service]["environment"]
        )
        settings = overlay["services"][service]["environment"]
        assert settings["FAILURELENS_TELEMETRY_EXPORT_ENABLED"] == "true"
        assert (
            settings["FAILURELENS_TELEMETRY_ENDPOINT"]
            == "http://otel-collector:4318/v1/traces"
        )
    collector = overlay["services"]["otel-collector"]
    assert collector["profiles"] == ["telemetry"]
    assert collector["networks"] == ["failurelens"] and not collector.get("ports")
    assert collector["user"] == "10001:10001" and collector["read_only"] is True
    assert collector["mem_limit"] == "256m" and collector["cap_drop"] == ["ALL"]
    viewer = overlay["services"]["telemetry-viewer"]
    assert viewer["profiles"] == ["telemetry"]
    assert viewer["ports"] == ["127.0.0.1:16686:8080"]
    proxy = (ROOT / "integrations/telemetry/viewer.conf").read_text()
    assert "proxy_pass http://otel-collector:16686;" in proxy
    assert (
        "proxy_pass $" not in proxy and "limit_except GET HEAD { deny all; }" in proxy
    )
    config = yaml.safe_load((ROOT / "integrations/telemetry/jaeger.yaml").read_text())
    assert set(config["exporters"]) == {"jaeger_storage_exporter"}
    assert set(config["extensions"]) == {"jaeger_storage", "jaeger_query"}
    assert config["processors"]["batch"]["send_batch_max_size"] == 64
    assert (
        config["extensions"]["jaeger_storage"]["backends"]["local_memory"]["memory"][
            "max_traces"
        ]
        == 1000
    )
    assert (
        config["receivers"]["otlp"]["protocols"]["http"]["max_request_body_size"]
        == 1048576
    )


def test_telemetry_smoke_requires_actual_durable_trace_and_collector_failure_check():
    script = (ROOT / "scripts/compose_telemetry_smoke.sh").read_text()
    assert "--confirm-disposable-stack" in script
    assert (
        'docker compose -f compose.yaml -f compose.telemetry.yaml --profile telemetry -p "$PROJECT"'
        in script
    )
    assert "query + '/api/traces/' + trace_id" in script
    assert "assert required <= names" in script
    assert "assert state == 'succeeded'" in script
    assert "compose stop otel-collector" in script
    assert "collector-down-readiness.json" in script
    assert "http://127.0.0.1:16686/api/v3/services" in script
    assert "json.load(open(sys.argv[1]))['services']" in script


def test_gateway_logs_use_only_allowlisted_method_and_status():
    for name in ("frontend/nginx.conf", "integrations/telemetry/viewer.conf"):
        source = (ROOT / name).read_text()
        format_line = next(
            line for line in source.splitlines() if line.startswith("log_format ")
        )
        assert "escape=json" in format_line
        assert "$failurelens_method" in format_line and "$status" in format_line
        assert all(
            field not in format_line
            for field in ("$request_uri", "$request ", "$remote_addr", "$http_")
        )
        assert (
            "map $request_method $failurelens_method {" in source
            and "default OTHER;" in source
        )
        assert "error_log /dev/null;" in source
        # A sibling http-level access_log adds to the vendor's existing log;
        # overriding at server scope is required to prevent duplicate raw output.
        prefix, *servers = source.split("server {")
        assert "access_log " not in prefix and "error_log /dev/null;" not in prefix
        assert len(servers) == (2 if name.startswith("frontend/") else 1)
        for server in servers:
            assert "access_log /dev/stdout failurelens_" in server
            assert "error_log /dev/null;" in server
            assert "proxy_connect_timeout 2s;" in server
    smoke = (ROOT / "scripts/compose_recovery_smoke.sh").read_text()
    assert "synthetic-gateway-query-canary-762" in smoke
    assert "synthetic-gateway-error-canary-941" in smoke
    assert 'case "$PROXY_ERROR_STATUS" in 502|504)' in smoke
    assert "curl --max-time 10" in smoke
    assert "Gateway or application logs exposed synthetic query canary" in smoke
