"""Bounded manual stage telemetry. No raw input/claims or automatic egress."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
import json
import logging
import re
import threading
import time
from urllib.parse import urlsplit

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanLimits, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from .config import get_settings
from .redaction import redact_text

STAGES = frozenset({'http', 'job', 'ingestion', 'validation', 'redaction', 'parsing',
                    'clustering', 'analysis', 'evidence', 'persistence', 'publication', 'provider', 'history'})
CATEGORIES = frozenset({'product_defect', 'test_defect', 'infrastructure_failure', 'known_flake', 'insufficient_evidence'})
BUCKETS_MS = (5, 25, 100, 500, 2000, 10000)
correlation_id: ContextVar[str | None] = ContextVar('correlation_id', default=None)
_lock = threading.RLock()
_provider: TracerProvider | None = None
_export_enabled = False
_exporter: BoundedOTLPExporter | None = None
_stats: dict[str, dict] = {}
_categories: dict[str, int] = {}
_http_statuses: dict[str, int] = {}
_provider_outcomes: dict[str, int] = {}
_result_counts: dict[str, dict[str, int]] = {}
RESULT_LABELS = {
    "evidence_records": frozenset({"accepted", "rejected"}),
    "validation_calls": frozenset({"passed", "degraded"}),
    "provider_cost_calls": frozenset({"estimated", "unknown"}),
    "redaction_operations": frozenset({"changed", "unchanged"}),
    "redaction_classes": frozenset({"observed"}),
    "worker_events": frozenset({"recovered_lease"}),
}
_propagator = TraceContextTextMapPropagator()
_TRACEPARENT = re.compile(r'^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$')


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Unknown extras and exception text are deliberately excluded.
        return json.dumps({'timestamp': datetime.now(UTC).isoformat(),
            'level': record.levelname, 'logger': redact_text(record.name).text[:100],
            'message': redact_text(record.getMessage()).text[:1000],
            'correlation_id': correlation_id.get() if re.fullmatch(r'[0-9a-f]{32}', correlation_id.get() or '') else None}, separators=(',', ':'))


_HTTP_METHODS = frozenset({'GET', 'POST', 'PATCH', 'DELETE', 'PUT', 'HEAD', 'OPTIONS'})
_SERVER_EVENTS = {
    'Started server process [%d]': 'server_started',
    'Finished server process [%d]': 'server_stopped',
    'Waiting for application startup.': 'application_starting',
    'Application startup complete.': 'application_started',
    'Shutting down': 'server_stopping',
    'Waiting for application shutdown.': 'application_stopping',
    'Application shutdown complete.': 'application_stopped',
    'Exception in ASGI application\n': 'application_error',
    'Invalid HTTP request received.': 'invalid_http_request',
    'Exceeded concurrency limit.': 'concurrency_limit',
}
_LOG_LEVELS = {logging.DEBUG: 'DEBUG', logging.INFO: 'INFO', logging.WARNING: 'WARNING',
               logging.ERROR: 'ERROR', logging.CRITICAL: 'CRITICAL'}


class UvicornJsonFormatter(logging.Formatter):
    """Never interpolate server logs: their arguments can be arbitrary requests.

    Uvicorn's pinned HTTP access format supplies client, method, URL, protocol and
    status in that order. Unknown shapes fail closed rather than stringify data.
    Server/error logs retain only fixed event names; traceback/stack/extras and
    arguments (including websocket URLs and peer addresses) are never emitted.
    """
    def format(self, record: logging.LogRecord) -> str:
        access = record.name == 'uvicorn.access' or record.name.startswith('uvicorn.access.')
        payload = {
            'timestamp': datetime.now(UTC).isoformat(),
            'level': _LOG_LEVELS.get(record.levelno, 'OTHER'),
            'logger': 'uvicorn.access' if access else 'uvicorn.error',
        }
        if access:
            method, status = 'OTHER', None
            if isinstance(record.args, tuple) and len(record.args) == 5:
                candidate_method, candidate_status = record.args[1], record.args[4]
                if type(candidate_method) is str and candidate_method in _HTTP_METHODS:
                    method = candidate_method
                if type(candidate_status) is int and 100 <= candidate_status < 600:
                    status = candidate_status
            payload.update({'message': 'http_request', 'http.request.method': method,
                            'http.response.status_code': status})
        else:
            event = _SERVER_EVENTS.get(record.msg) if type(record.msg) is str else None
            payload['message'] = event or ('server_exception' if record.exc_info else 'server_log')
        return json.dumps(payload, separators=(',', ':'))


def configure_logging() -> None:
    # Uvicorn installs ordinary handlers before importing the app. Replace, rather
    # than append to, every existing handler in our two logger trees: an unsafe
    # child or parent handler must not duplicate a redacted record as raw text.
    roots = {'failurelens': JsonFormatter(), 'uvicorn': UvicornJsonFormatter(),
             'uvicorn.access': UvicornJsonFormatter(), 'uvicorn.error': UvicornJsonFormatter()}
    with _lock:
        for name in roots:
            logging.getLogger(name)
        for name, logger in list(logging.root.manager.loggerDict.items()):
            if not isinstance(logger, logging.Logger):
                continue
            if name not in roots and not name.startswith(('failurelens.', 'uvicorn.')):
                continue
            logger.handlers[:] = []
            logger.propagate = name not in roots
            if name in roots:
                handler = logging.StreamHandler()
                handler._failurelens_safe = True
                handler.setLevel(logging.INFO)
                handler.setFormatter(roots[name])
                logger.addHandler(handler)
                logger.setLevel(logging.INFO)


def validate_endpoint(endpoint: str | None) -> str:
    if not endpoint:
        raise ValueError('Explicit telemetry endpoint is required when export is enabled')
    try:
        parts = urlsplit(endpoint)
        port = parts.port
        hostname = parts.hostname
    except ValueError:
        raise ValueError('Invalid telemetry endpoint') from None
    local = hostname in {'localhost', '127.0.0.1', '::1', 'otel-collector'}
    if (any(ord(char) <= 32 or ord(char) == 127 for char in endpoint) or
            parts.username is not None or parts.password is not None or
            parts.query or parts.fragment or not hostname or port == 0 or
            not (parts.scheme == 'https' or (parts.scheme == 'http' and local))):
        raise ValueError('Telemetry requires HTTPS or an explicit local collector, without embedded credentials/query')
    return endpoint


class BoundedOTLPExporter(SpanExporter):
    """Explicit transport with one in-flight request and a total export deadline.

    httpx timeouts bound individual reads, not a trickling response or DNS. One
    daemon transport task enforces the caller's deadline even for those cases.
    A timed-out task closes this exporter permanently, so it cannot accumulate
    stuck transport threads or requests. Normal transport failures may recover.
    """
    timeout_seconds = 2.0

    def __init__(self, endpoint: str):
        import httpx
        self.endpoint = validate_endpoint(endpoint)
        self.client = httpx.Client(timeout=self.timeout_seconds, trust_env=False, follow_redirects=False)
        self._inflight = threading.Lock()
        self._closed = False
        self._shutdown_deadline: float | None = None

    def _send(self, payload: bytes) -> SpanExportResult:
        import httpx
        try:
            with self.client.stream('POST', self.endpoint, content=payload,
                    headers={'Content-Type': 'application/x-protobuf'}) as response:
                if response.status_code != 200:
                    return SpanExportResult.FAILURE
                size = 0
                for chunk in response.iter_raw(chunk_size=16384):
                    size += len(chunk)
                    if size > 65536 or self._closed:
                        return SpanExportResult.FAILURE
            return SpanExportResult.SUCCESS
        except (httpx.HTTPError, RuntimeError):
            return SpanExportResult.FAILURE

    def export(self, spans):
        from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
        timeout = self.timeout_seconds
        if self._shutdown_deadline is not None:
            timeout = min(timeout, self._shutdown_deadline - time.monotonic())
        if self._closed or timeout <= 0 or not self._inflight.acquire(blocking=False):
            return SpanExportResult.FAILURE
        done = threading.Event()
        result = [SpanExportResult.FAILURE]
        try:
            payload = encode_spans(spans).SerializeToString()
            if len(payload) > 1_000_000:
                self._inflight.release()
                return SpanExportResult.FAILURE
        except Exception:
            self._inflight.release()
            return SpanExportResult.FAILURE

        def send():
            try:
                result[0] = self._send(payload)
            except Exception:
                # Transport failures must not log collector data or exceptions.
                pass
            finally:
                self._inflight.release()
                done.set()

        threading.Thread(target=send, name='failurelens-otlp-request', daemon=True).start()
        if not done.wait(timeout):
            self.shutdown()
            return SpanExportResult.FAILURE
        return result[0]

    def begin_shutdown(self, timeout_seconds: float = 2.0):
        # All remaining batches share this budget; SDK flush timeouts alone do
        # not bound blocking exporters in the pinned SDK version.
        self._shutdown_deadline = time.monotonic() + max(0.0, timeout_seconds)

    def shutdown(self):
        self._closed = True
        self.client.close()

    def force_flush(self, timeout_millis=30000):
        return not self._closed


def configure_telemetry() -> TracerProvider:
    global _provider, _export_enabled, _exporter
    with _lock:
        if _provider is not None:
            return _provider
        settings = get_settings()
        endpoint = validate_endpoint(settings.telemetry_endpoint) if settings.telemetry_export_enabled else None
        provider = TracerProvider(resource=Resource({'service.name': 'loose-thread',
            'telemetry.policy': 'bounded-stages-v1'}),
            span_limits=SpanLimits(max_attributes=8, max_span_attributes=8,
                max_attribute_length=160, max_span_attribute_length=160,
                max_event_attributes=0, max_link_attributes=0, max_events=0, max_links=0))
        if settings.telemetry_export_enabled:
            _exporter = BoundedOTLPExporter(endpoint)
            provider.add_span_processor(BatchSpanProcessor(_exporter, max_queue_size=256,
                max_export_batch_size=64, schedule_delay_millis=1000, export_timeout_millis=2500))
        _export_enabled = settings.telemetry_export_enabled
        _provider = provider
        configure_logging()
        return provider


def shutdown_telemetry() -> None:
    """Drain within a shared export budget and allow a later app lifespan."""
    global _provider, _export_enabled, _exporter
    with _lock:
        provider, exporter = _provider, _exporter
        _provider = None
        _exporter = None
        _export_enabled = False
    if exporter is not None:
        exporter.begin_shutdown()
    if provider is not None:
        provider.shutdown()


def observe_result(group: str, label: str, count: int = 1) -> None:
    if label not in RESULT_LABELS.get(group, ()) or not isinstance(count, int) or count < 0:
        raise ValueError('Unrecognized telemetry result')
    with _lock:
        row = _result_counts.setdefault(group, {})
        row[label] = row.get(label, 0) + count


def trace_context() -> dict[str, str]:
    carrier: dict[str, str] = {}
    _propagator.inject(carrier)
    parent = carrier.get('traceparent')
    return {'traceparent': parent} if isinstance(parent, str) and _TRACEPARENT.fullmatch(parent) else {}


@contextmanager
def stage(name: str, *, parent: str | None = None, kind=SpanKind.INTERNAL):
    if name not in STAGES:
        raise ValueError('Unrecognized telemetry stage')
    context = _propagator.extract({'traceparent': parent}) if isinstance(parent, str) and _TRACEPARENT.fullmatch(parent) else None
    if context is None:
        inherited = trace.get_current_span().get_span_context()
        if inherited.is_valid and inherited.trace_state:
            # Preserve local parent/sampling identity, but never inherit vendor
            # tracestate from ambient instrumentation into our exported spans.
            clean_parent = trace.SpanContext(inherited.trace_id, inherited.span_id,
                inherited.is_remote, inherited.trace_flags, trace.TraceState())
            context = trace.set_span_in_context(trace.NonRecordingSpan(clean_parent))
    tracer = configure_telemetry().get_tracer('failurelens.stages', '1')
    started = time.perf_counter()
    error = False
    with tracer.start_as_current_span('failurelens.' + name, context=context, kind=kind,
            record_exception=False, set_status_on_exception=False) as span:
        span_context = span.get_span_context()
        token = correlation_id.set(f'{span_context.trace_id:032x}' if span_context.is_valid else None)
        try:
            yield span
        except BaseException:
            error = True
            span.set_status(Status(StatusCode.ERROR))
            raise
        finally:
            elapsed = max(0.0, (time.perf_counter() - started) * 1000)
            with _lock:
                row = _stats.setdefault(name, {'completed_calls': 0, 'exception_calls': 0,
                    'duration_ms_sum': 0.0, 'duration_ms_max': 0.0, 'buckets': [0] * (len(BUCKETS_MS) + 1)})
                row['completed_calls'] += 1
                row['exception_calls'] += int(error)
                row['duration_ms_sum'] += elapsed
                row['duration_ms_max'] = max(row['duration_ms_max'], elapsed)
                index = next((i for i, bound in enumerate(BUCKETS_MS) if elapsed <= bound), len(BUCKETS_MS))
                row['buckets'][index] += 1
            logging.getLogger('failurelens.stages').info('%s %s', name, 'failed' if error else 'completed')
            correlation_id.reset(token)


def instrument(name: str):
    if name not in STAGES:
        raise ValueError('Unrecognized telemetry stage')
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with stage(name) as span:
                result = function(*args, **kwargs)
                category = getattr(getattr(result, 'category', None), 'value', None)
                if name == 'analysis' and category in CATEGORIES:
                    span.set_attribute('analysis.category', category)
                    with _lock:
                        _categories[category] = _categories.get(category, 0) + 1
                if name == 'provider':
                    outcome = getattr(result, 'status', None)
                    if outcome in {'proposed', 'fallback'}:
                        span.set_attribute('provider.outcome', outcome)
                        with _lock:
                            _provider_outcomes[outcome] = _provider_outcomes.get(outcome, 0) + 1
                    cost_status = getattr(result, 'cost_status', None)
                    if cost_status in {'unknown', 'estimated'}:
                        span.set_attribute('provider.cost_status', cost_status)
                        observe_result('provider_cost_calls', cost_status)
                if name == 'evidence':
                    for label, field in (('accepted', 'accepted_ids'), ('rejected', 'rejected_ids')):
                        values = getattr(result, field, None)
                        if isinstance(values, (tuple, list)):
                            span.set_attribute('evidence.' + label + '_count', len(values))
                            observe_result('evidence_records', label, len(values))
                if name == 'validation':
                    validation = getattr(result, 'validation_results', None)
                    outcome = validation.get('status') if isinstance(validation, dict) else None
                    if outcome in {'passed', 'degraded'}:
                        span.set_attribute('validation.outcome', outcome)
                        observe_result('validation_calls', outcome)
                if name == 'redaction' and isinstance(result, tuple) and len(result) == 2:
                    classes = result[1]
                    if isinstance(classes, (set, frozenset)):
                        span.set_attribute('redaction.class_count', len(classes))
                        observe_result('redaction_classes', 'observed', len(classes))
                        observe_result('redaction_operations', 'changed' if classes else 'unchanged')
                if name == 'publication':
                    outcome = getattr(result, 'status', None)
                    if outcome in {'created', 'updated', 'unchanged', 'stale'}:
                        span.set_attribute('publication.outcome', outcome)
                return result
        return wrapped
    return decorate


def observe_http_status(status: int) -> None:
    label = f"{status // 100}xx" if 100 <= status < 600 else 'other'
    with _lock:
        _http_statuses[label] = _http_statuses.get(label, 0) + 1


def metrics_snapshot() -> dict:
    with _lock:
        rows = json.loads(json.dumps(_stats))
        categories = dict(_categories)
        statuses = dict(_http_statuses)
        provider_outcomes = dict(_provider_outcomes)
        results = {group: dict(counts) for group, counts in _result_counts.items()}
    return {'schema_version': 'bounded-telemetry-v1', 'scope': 'current_process_completed_calls',
            'export_enabled': _export_enabled, 'stage_counts': rows,
            'histogram_upper_bounds_ms': list(BUCKETS_MS) + ['infinity'],
            'analysis_call_categories': categories, 'http_response_classes': statuses,
            'provider_call_outcomes': provider_outcomes,
            'result_counts': results,
            'limitations': ['Process-local counters reset on restart and are not unique analysis counts',
                            'No raw artifacts, prompts, test names, credentials or user identifiers are recorded']}
