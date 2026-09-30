"""Unexpected failures retain containment without putting exception data in logs."""

import logging
import threading

import pytest
from failurelens import jobs, telemetry
from failurelens.models import Job, JobState
from failurelens.providers import HTTPModelProvider, ProviderConfig, RunBudget
from failurelens.service import create_project
from opentelemetry.exporter.otlp.proto.common import trace_encoder
from opentelemetry.sdk.trace.export import SpanExportResult


class CaptureRecords(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def captured_logs(monkeypatch):
    # Public instrumented boundaries initialize their normal logging handlers.
    # Capture after that initialization so the test observes the real boundary.
    telemetry.configure_telemetry()
    sink = CaptureRecords()
    for name in ("failurelens.jobs", "failurelens.providers", "failurelens.telemetry"):
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "handlers", [sink])
        monkeypatch.setattr(logger, "propagate", False)
        monkeypatch.setattr(logger, "disabled", False)
        monkeypatch.setattr(logger, "level", logging.ERROR)
    yield sink.records
    telemetry.shutdown_telemetry()


def assert_private_diagnostic(records, code):
    assert len(records) == 1
    record = records[0]
    assert record.getMessage() == code
    assert record.args == ()
    assert record.exc_info is False
    assert record.exc_text is None
    assert record.stack_info is None
    # Privacy must hold even under an ordinary downstream formatter.
    assert "private-boundary-canary" not in logging.Formatter().format(record)


def test_telemetry_encoding_failure_releases_slot_without_exception_data(
    monkeypatch, captured_logs
):
    def fail_encoding(_spans):
        raise RuntimeError("private-boundary-canary")

    monkeypatch.setattr(trace_encoder, "encode_spans", fail_encoding)
    exporter = telemetry.BoundedOTLPExporter("http://127.0.0.1:4318/v1/traces")
    try:
        assert exporter.export([]) is SpanExportResult.FAILURE
        assert exporter._inflight.acquire(blocking=False)
        exporter._inflight.release()
        assert_private_diagnostic(captured_logs, "telemetry_encoding_error")
    finally:
        exporter.shutdown()


def test_telemetry_transport_failure_releases_slot_without_exception_data(
    monkeypatch, captured_logs
):
    exporter = telemetry.BoundedOTLPExporter("http://127.0.0.1:4318/v1/traces")

    def fail_transport(_payload):
        raise RuntimeError("private-boundary-canary")

    monkeypatch.setattr(exporter, "_send", fail_transport)
    try:
        assert exporter.export([]) is SpanExportResult.FAILURE
        assert exporter._inflight.acquire(blocking=False)
        exporter._inflight.release()
        assert_private_diagnostic(captured_logs, "telemetry_transport_error")
    finally:
        exporter.shutdown()


def test_provider_thread_preserves_base_exception_and_releases_transport_slot(
    monkeypatch, captured_logs
):
    class TransportAbort(BaseException):
        pass

    provider = HTTPModelProvider(
        ProviderConfig(
            endpoint="https://provider.example/v1/chat/completions",
            model="test-fixture",
            token="test",
            enabled=True,
            concurrency=1,
        )
    )
    abort = TransportAbort("private-boundary-canary")

    def fail_transport(*_args):
        raise abort

    monkeypatch.setattr(provider, "_send", fail_transport)
    budget = RunBudget()
    try:
        with pytest.raises(TransportAbort) as raised:
            provider.propose(
                deterministic_category="product_defect",
                evidence=[
                    {"id": "observed", "excerpt": "Observed failure", "approved": True}
                ],
                budget=budget,
                cancel=threading.Event(),
            )
        assert raised.value is abort
        assert budget.requests == 1
        assert budget.reserved_tokens > 0
        assert provider._transport_slots.acquire(blocking=False)
        provider._transport_slots.release()
        assert provider.semaphore.acquire(blocking=False)
        provider.semaphore.release()
        assert_private_diagnostic(captured_logs, "provider_transport_error")
    finally:
        provider.close()


def test_worker_unexpected_failure_keeps_terminal_accounting_and_private_logs(
    session, monkeypatch, captured_logs
):
    project = create_project(session, "boundary-worker", "Boundary worker")
    job = Job(project_id=project.id, kind="test-boundary", payload={}, max_attempts=1)
    session.add(job)
    session.commit()

    def fail_processing(*_args):
        raise RuntimeError("private-boundary-canary")

    monkeypatch.setattr(jobs, "process_claimed", fail_processing)
    assert jobs.process_next(session, "boundary-worker")
    session.refresh(job)
    assert job.state is JobState.dead_lettered
    assert job.attempts == 1
    assert job.lease_owner is None
    assert_private_diagnostic(captured_logs, "worker_boundary_error")
