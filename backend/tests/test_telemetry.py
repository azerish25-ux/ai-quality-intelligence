import json
import logging
from unittest.mock import Mock

import pytest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import select

from failurelens import telemetry as t
from failurelens.config import get_settings
from failurelens.models import Ingestion, Job
from failurelens.jobs import process_next


@pytest.fixture
def spans(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource({'service.name': 'test-fixture'}), sampler=ALWAYS_ON)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(t, '_provider', provider)
    monkeypatch.setattr(t, '_stats', {})
    monkeypatch.setattr(t, '_categories', {})
    monkeypatch.setattr(t, '_http_statuses', {})
    monkeypatch.setattr(t, '_provider_outcomes', {})
    monkeypatch.setattr(t, '_result_counts', {})
    monkeypatch.setattr(t, '_exporter', None)
    yield exporter
    provider.shutdown()


def test_stage_hides_exception_text_and_preserves_trace_parent(spans):
    with t.stage('http') as root:
        carrier = t.trace_context()
        root_id = root.get_span_context().trace_id
    with pytest.raises(RuntimeError):
        with t.stage('job', parent=carrier['traceparent']) as child:
            assert child.get_span_context().trace_id == root_id
            raise RuntimeError('token=private-canary-928 person@example.invalid')
    encoded = '\n'.join(span.to_json() for span in spans.get_finished_spans())
    assert 'private-canary' not in encoded and 'person@example' not in encoded
    assert all(not span.events for span in spans.get_finished_spans())
    assert t.metrics_snapshot()['stage_counts']['job']['exception_calls'] == 1
    assert t.correlation_id.get() is None


def test_formatter_redacts_declared_classes_and_drops_unknown_extras():
    token = t.correlation_id.set('person@example.invalid')
    try:
        record = logging.LogRecord('failurelens', logging.ERROR, __file__, 1,
            'token=private-canary-928 person@example.invalid', (), None)
        record.private_payload = 'never-export-this-extra'
        result = t.JsonFormatter().format(record)
        assert 'private-canary-928' not in result and 'person@example.invalid' not in result
        assert 'never-export-this-extra' not in result
        assert json.loads(result)['correlation_id'] is None
    finally:
        t.correlation_id.reset(token)


def test_unbounded_stage_names_are_rejected(spans):
    for index in range(20):
        with pytest.raises(ValueError):
            with t.stage(f'untrusted-{index}'):
                pass
    assert t.metrics_snapshot()['stage_counts'] == {}


def test_default_ignores_generic_otlp_environment_and_performs_no_export(monkeypatch):
    monkeypatch.setattr(t, '_provider', None)
    monkeypatch.setenv('FAILURELENS_TELEMETRY_EXPORT_ENABLED', 'false')
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_ENDPOINT', 'https://never-contact.example.invalid')
    get_settings.cache_clear()
    forbidden = Mock(side_effect=AssertionError('unapproved exporter created'))
    monkeypatch.setattr(t, 'BoundedOTLPExporter', forbidden)
    provider = t.configure_telemetry()
    with t.stage('analysis'):
        pass
    forbidden.assert_not_called()
    assert t.metrics_snapshot()['export_enabled'] is False
    provider.shutdown()
    get_settings.cache_clear()


@pytest.mark.parametrize('endpoint', [None, 'http://outside.example.invalid/v1/traces',
    'https://<user>:<password>@example.invalid', 'https://example.invalid/?secret=<redacted>', 'https://example.invalid/#fragment'])
def test_invalid_or_credential_shaped_endpoints_are_rejected(endpoint):
    with pytest.raises(ValueError):
        t.validate_endpoint(endpoint)


@pytest.mark.parametrize('endpoint', ['http://127.0.0.1:4318/v1/traces', 'http://otel-collector:4318/v1/traces', 'https://collector.example.invalid/v1/traces'])
def test_explicit_operator_endpoints_are_accepted(endpoint):
    assert t.validate_endpoint(endpoint) == endpoint


def test_real_api_to_durable_worker_propagates_only_trace_context(client, session, spans):
    project = client.post('/api/v1/projects', json={'slug': 'trace-project', 'name': 'Trace fixture'}).json()['id']
    response = client.post(f'/api/v1/projects/{project}/ingestions', params={
        'external_id': 'trace-run', 'filename': 'report.xml'}, content=b'<testsuite><testcase name="case"><failure>Timeout waiting for selector</failure></testcase></testsuite>',
        headers={'content-type': 'application/xml', 'baggage': 'private_canary=never-export-this'})
    assert response.status_code == 202, response.text
    ingestion = session.get(Ingestion, response.json()['id'])
    job = session.get(Job, ingestion.job_id)
    assert set(job.payload) == {'ingestion_id', 'job_schema', 'traceparent'}
    trace_id = int(job.payload['traceparent'].split('-')[1], 16)
    assert process_next(session, 'trace-worker', settings=get_settings())
    recorded = [span for span in spans.get_finished_spans() if span.context.trace_id == trace_id]
    names = {span.name for span in recorded}
    assert {'failurelens.http', 'failurelens.job', 'failurelens.ingestion', 'failurelens.parsing', 'failurelens.evidence', 'failurelens.analysis', 'failurelens.persistence'}.issubset(names)
    encoded = '\n'.join(span.to_json() for span in recorded)
    assert 'never-export-this' not in encoded and 'Timeout waiting' not in encoded
    assert not any('case' in str(span.attributes) for span in recorded)


def test_metrics_require_system_admin_and_contain_no_resource_identifiers(client, session, spans):
    allowed = client.get('/api/v1/operations/telemetry')
    assert allowed.status_code == 200
    body = allowed.json()
    assert body['scope'] == 'current_process_completed_calls'
    assert body['queue']['states']['queued'] == 0
    from failurelens.auth import create_user
    create_user(session, username='telemetry-viewer', display_name='Viewer', password='synthetic-test-password')
    session.commit()
    assert client.post('/api/v1/auth/login', json={'username': 'telemetry-viewer', 'password': 'synthetic-test-password'}).status_code == 200
    assert client.get('/api/v1/operations/telemetry').status_code == 403


def test_explicit_local_otlp_export_uses_bounded_schema_and_no_environment_secrets(monkeypatch):
    import gzip
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    received = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers['Content-Length'])
            assert length < 1_000_000
            data = self.rfile.read(length)
            if self.headers.get('Content-Encoding') == 'gzip':
                data = gzip.decompress(data)
            received.append((dict(self.headers), ExportTraceServiceRequest.FromString(data)))
            self.send_response(200); self.end_headers()
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    monkeypatch.setattr(t, '_provider', None)
    monkeypatch.setattr(t, '_export_enabled', False)
    monkeypatch.setenv('FAILURELENS_TELEMETRY_EXPORT_ENABLED', 'true')
    monkeypatch.setenv('FAILURELENS_TELEMETRY_ENDPOINT', f'http://127.0.0.1:{server.server_port}/v1/traces')
    monkeypatch.setenv('OTEL_TRACES_SAMPLER', 'always_on')
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_HEADERS', 'private-canary=never-export-this')
    monkeypatch.setenv('OTEL_RESOURCE_ATTRIBUTES', 'private-canary=never-export-this')
    get_settings.cache_clear()
    provider = None
    try:
        provider = t.configure_telemetry()
        with t.stage('analysis'):
            pass
        assert provider.force_flush(timeout_millis=5000)
        assert received
        headers, request = received[0]
        assert 'never-export-this' not in str(headers)
        assert 'never-export-this' not in str(request)
        spans = [span for resource in request.resource_spans for scope in resource.scope_spans for span in scope.spans]
        assert any(span.name == 'failurelens.analysis' for span in spans)
        assert all(not span.events for span in spans)
    finally:
        if provider:
            provider.shutdown()
        server.shutdown(); server.server_close(); thread.join(timeout=2)
        get_settings.cache_clear()


@pytest.mark.parametrize('status,body,success', [(200, b'', True), (302, b'', False),
    (503, b'', False), (200, b'x' * 65537, False)])
def test_export_response_boundaries_never_retry_or_follow_redirects(status, body, success):
    import httpx
    from opentelemetry.sdk.trace.export import SpanExportResult
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, stream=httpx.ByteStream(body), headers={'location': 'https://never-follow.example.invalid'})
    exporter = t.BoundedOTLPExporter('http://127.0.0.1:4318/v1/traces')
    exporter.client.close()
    exporter.client = httpx.Client(transport=httpx.MockTransport(respond), trust_env=False, follow_redirects=False)
    try:
        result = exporter.export([])
        assert (result is SpanExportResult.SUCCESS) == success
        assert len(requests) == 1
    finally:
        exporter.shutdown()


def test_unhandled_http_failure_is_counted_and_has_safe_status(spans):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from failurelens.api import private_api_responses
    app = FastAPI()
    app.middleware('http')(private_api_responses)

    @app.get('/failure/{resource_id}')
    def fail(resource_id: str):
        raise RuntimeError('private-exception-canary')

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get('/failure/private-id-canary').status_code == 500
    recorded = spans.get_finished_spans()
    assert len(recorded) == 1
    assert recorded[0].attributes['http.route'] == '/failure/{resource_id}'
    assert recorded[0].attributes['http.response.status_code'] == 500
    assert recorded[0].status.status_code.name == 'ERROR'
    assert t.metrics_snapshot()['http_response_classes'] == {'5xx': 1}
    assert 'private-' not in recorded[0].to_json()


def test_app_lifespan_drains_and_supports_restart(monkeypatch):
    import asyncio
    import failurelens.api as api
    monkeypatch.setattr(api, 'initialize_database', lambda: None)
    monkeypatch.setattr(t, '_provider', None)
    monkeypatch.setattr(t, '_exporter', None)
    monkeypatch.setenv('FAILURELENS_TELEMETRY_EXPORT_ENABLED', 'false')
    get_settings.cache_clear()
    providers = []

    async def exercise():
        for _ in range(2):
            async with api.lifespan(api.app):
                provider = t.configure_telemetry()
                spy = Mock(wraps=provider.shutdown)
                monkeypatch.setattr(provider, 'shutdown', spy)
                providers.append(provider)
                with t.stage('analysis'):
                    pass
            spy.assert_called_once()
            assert t._provider is None
            assert t._export_enabled is False
        assert providers[0] is not providers[1]

    try:
        asyncio.run(exercise())
    finally:
        get_settings.cache_clear()


def test_span_specific_environment_cannot_relax_bounds(monkeypatch):
    monkeypatch.setattr(t, '_provider', None)
    monkeypatch.setenv('FAILURELENS_TELEMETRY_EXPORT_ENABLED', 'false')
    monkeypatch.setenv('OTEL_TRACES_SAMPLER', 'always_on')
    monkeypatch.setenv('OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT', '9999')
    monkeypatch.setenv('OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT', '99999')
    monkeypatch.setenv('OTEL_EVENT_ATTRIBUTE_COUNT_LIMIT', 'not-a-number')
    monkeypatch.setenv('OTEL_LINK_ATTRIBUTE_COUNT_LIMIT', 'not-a-number')
    get_settings.cache_clear()
    provider = t.configure_telemetry()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        with t.stage('analysis') as span:
            for index in range(20):
                span.set_attribute(f'field{index}', 'x' * 1000)
            span.add_event('private-event', {'private': 'never-export'})
        recorded = exporter.get_finished_spans()[0]
        assert len(recorded.attributes) == 8
        assert all(len(value) <= 160 for value in recorded.attributes.values())
        assert not recorded.events and not recorded.links
    finally:
        provider.shutdown()
        get_settings.cache_clear()


def test_export_total_deadline_and_single_stuck_transport(monkeypatch):
    import httpx
    import threading
    import time
    from opentelemetry.sdk.trace.export import SpanExportResult
    started, release = threading.Event(), threading.Event()
    requests = []

    def blocked(request):
        requests.append(request)
        started.set()
        release.wait(3)
        return httpx.Response(200)

    exporter = t.BoundedOTLPExporter('http://127.0.0.1:4318/v1/traces')
    exporter.client.close()
    exporter.client = httpx.Client(transport=httpx.MockTransport(blocked), trust_env=False)
    monkeypatch.setattr(exporter, 'timeout_seconds', 0.05)
    before = time.monotonic()
    try:
        assert exporter.export([]) is SpanExportResult.FAILURE
        assert started.is_set() and time.monotonic() - before < 0.5
        for _ in range(10):
            assert exporter.export([]) is SpanExportResult.FAILURE
        assert len(requests) == 1 and exporter.client.is_closed
    finally:
        release.set()
        exporter.shutdown()


def test_loopback_trickling_headers_cannot_extend_export_deadline(monkeypatch):
    import socketserver
    import threading
    import time
    from opentelemetry.sdk.trace.export import SpanExportResult
    stopped = threading.Event()

    class Trickle(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.recv(20000)
            try:
                self.request.sendall(b'HTTP/1.1 200 OK\r\n')
                for _ in range(50):
                    if stopped.wait(0.01):
                        break
                    self.request.sendall(b'X-Trickle: header\r\n')
                self.request.sendall(b'Content-Length: 0\r\n\r\n')
            except OSError:
                pass

    server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), Trickle)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    exporter = t.BoundedOTLPExporter(f'http://127.0.0.1:{server.server_address[1]}/v1/traces')
    monkeypatch.setattr(exporter, 'timeout_seconds', 0.08)
    before = time.monotonic()
    try:
        assert exporter.export([]) is SpanExportResult.FAILURE
        assert time.monotonic() - before < 0.5
    finally:
        stopped.set()
        exporter.shutdown()
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_shutdown_uses_one_budget_for_all_pending_batches(monkeypatch):
    import httpx
    import threading
    import time
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    release = threading.Event()
    exporter = t.BoundedOTLPExporter('http://127.0.0.1:4318/v1/traces')
    exporter.client.close()
    exporter.client = httpx.Client(transport=httpx.MockTransport(
        lambda request: (release.wait(3), httpx.Response(200))[1]), trust_env=False)
    monkeypatch.setattr(exporter, 'timeout_seconds', 0.05)
    provider = TracerProvider(resource=Resource({}), sampler=ALWAYS_ON)
    provider.add_span_processor(BatchSpanProcessor(exporter, max_queue_size=256,
        max_export_batch_size=64, schedule_delay_millis=100000))
    monkeypatch.setattr(t, '_provider', provider)
    monkeypatch.setattr(t, '_exporter', exporter)
    for _ in range(100):
        with t.stage('analysis'):
            pass
    before = time.monotonic()
    try:
        t.shutdown_telemetry()
        assert time.monotonic() - before < 0.5
        assert t._provider is None and exporter.client.is_closed
    finally:
        release.set()
        provider.shutdown()


@pytest.mark.parametrize('endpoint', ['https://example.invalid:bad', 'https://example.invalid:0',
    'https://@example.invalid', 'https://example.invalid/\npath', 'https://[not-ipv6'])
def test_malformed_endpoint_rejected_before_transport(endpoint):
    with pytest.raises(ValueError):
        t.BoundedOTLPExporter(endpoint)


def test_result_metrics_have_fixed_labels_and_do_not_emit_result_content(spans):
    from types import SimpleNamespace

    def record(stage, result):
        return t.instrument(stage)(lambda: result)()

    record('evidence', SimpleNamespace(accepted_ids=('private-accepted',),
        rejected_ids=('private-rejected-1', 'private-rejected-2')))
    for outcome in ('passed', 'degraded', 'private-invalid-outcome'):
        record('validation', SimpleNamespace(validation_results={'status': outcome}))
    for outcome, cost in [('proposed', 'estimated'), ('fallback', 'unknown'), ('private-status', 'private-cost')]:
        record('provider', SimpleNamespace(status=outcome, cost_status=cost))
    record('redaction', ('private-text', {'private-class-one', 'private-class-two'}))
    record('redaction', ('unchanged-private-text', set()))
    result = t.metrics_snapshot()
    assert result['result_counts'] == {
        'evidence_records': {'accepted': 1, 'rejected': 2},
        'validation_calls': {'passed': 1, 'degraded': 1},
        'provider_cost_calls': {'estimated': 1, 'unknown': 1},
        'redaction_operations': {'changed': 1, 'unchanged': 1},
        'redaction_classes': {'observed': 2},
    }
    assert result['provider_call_outcomes'] == {'proposed': 1, 'fallback': 1}
    encoded = json.dumps(result) + '\n'.join(span.to_json() for span in spans.get_finished_spans())
    assert 'private-' not in encoded
    with pytest.raises(ValueError):
        t.observe_result('unbounded-group', 'private-label')
    with pytest.raises(ValueError):
        t.observe_result('evidence_records', 'private-label')


def test_recovered_lease_only_counted_after_successful_reclaim(session, spans):
    from datetime import UTC, datetime, timedelta
    from failurelens.jobs import claim_next, complete
    from failurelens.models import JobState
    from failurelens.service import create_project
    project = create_project(session, 'recovery-telemetry', 'Recovery telemetry')
    job = Job(project_id=project.id, kind='noop', payload={})
    session.add(job); session.commit()
    assert claim_next(session, 'private-original-worker', 30).id == job.id
    assert 'worker_events' not in t.metrics_snapshot()['result_counts']
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    reclaimed = claim_next(session, 'private-new-worker', 30)
    assert reclaimed.id == job.id and reclaimed.state is JobState.running
    assert t.metrics_snapshot()['result_counts']['worker_events'] == {'recovered_lease': 1}
    complete(session, reclaimed)
    assert claim_next(session, 'private-new-worker', 30) is None
    assert t.metrics_snapshot()['result_counts']['worker_events'] == {'recovered_lease': 1}
    encoded = '\n'.join(span.to_json() for span in spans.get_finished_spans())
    assert 'private-' not in encoded and job.id not in encoded


def test_worker_sigterm_finishes_current_iteration_and_shuts_down(monkeypatch):
    import os
    import signal
    import failurelens.jobs as jobs
    import failurelens.retention as retention
    from contextlib import nullcontext
    original = signal.getsignal(signal.SIGTERM)
    cleanup = Mock()
    monkeypatch.setattr('sys.argv', ['failurelens-worker', '--poll-seconds', '100'])
    monkeypatch.setattr(jobs, 'initialize_database', lambda: None)
    monkeypatch.setattr(jobs, 'configure_telemetry', lambda: None)
    monkeypatch.setattr(jobs, 'shutdown_telemetry', cleanup)
    monkeypatch.setattr(jobs, 'SessionLocal', lambda: nullcontext(None))
    monkeypatch.setattr(retention, 'schedule_due', lambda session: None)
    ran = []

    def run(worker_id):
        ran.append(worker_id)
        os.kill(os.getpid(), signal.SIGTERM)
        ran.append('finished')
        return False

    monkeypatch.setattr(jobs, 'run_once', run)
    jobs.main()
    assert ran[-1] == 'finished' and len(ran) == 2
    cleanup.assert_called_once()
    assert signal.getsignal(signal.SIGTERM) == original


def test_ambient_tracestate_is_not_exported_or_persisted(spans):
    from opentelemetry import trace
    from opentelemetry.context import attach, detach
    context = trace.SpanContext(trace_id=123, span_id=456, is_remote=False,
        trace_flags=trace.TraceFlags(1), trace_state=trace.TraceState([('vendor', 'private-canary')]))
    token = attach(trace.set_span_in_context(trace.NonRecordingSpan(context)))
    try:
        with t.stage('analysis') as span:
            assert span.get_span_context().trace_id == 123
            assert t.trace_context() == {'traceparent': f'00-{123:032x}-{span.get_span_context().span_id:016x}-01'}
    finally:
        detach(token)
    recorded = spans.get_finished_spans()[0]
    assert recorded.parent.span_id == 456
    assert not recorded.context.trace_state
    assert 'private-canary' not in recorded.to_json()
