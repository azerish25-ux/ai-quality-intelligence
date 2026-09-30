"""HTTP adapter accounting and fail-closed network boundary regressions."""

import json
import threading
import time
from dataclasses import replace

import httpx
import pytest
from failurelens.providers import HTTPModelProvider, ProviderBoundaryError, RunBudget
from test_providers import CONFIG, EVIDENCE, call, response


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        4,
        "string",
        {"choices": [1]},
        {"choices": [{"finish_reason": "stop", "message": 1}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": 1}}]},
    ],
)
def test_malformed_shapes_fail_closed(value):
    result, calls = call(lambda _: httpx.Response(200, content=json.dumps(value)))
    assert result.status == "fallback" and len(calls) == 1


@pytest.mark.parametrize(
    "choice",
    [
        1,
        {"finish_reason": "length", "message": {}},
        {"finish_reason": "stop", "message": {"content": "not JSON"}},
        {
            "finish_reason": "stop",
            "message": {"tool_calls": [{"private": "do not persist"}]},
        },
    ],
)
def test_usage_is_allowlisted_before_proposal_validation(choice):
    result, _ = call(
        lambda _: response(
            choices=[choice],
            usage={
                "prompt_tokens": 12,
                "completion_tokens": 7,
                "secret": "private-extra-usage",
            },
        )
    )
    assert result.status == "fallback"
    assert result.usage == {"prompt_tokens": 12, "completion_tokens": 7}
    assert "private" not in str(result)


@pytest.mark.parametrize(
    "usage",
    [
        {"prompt_tokens": True, "completion_tokens": 1},
        {"prompt_tokens": 1.5, "completion_tokens": 2},
        {"prompt_tokens": -1, "completion_tokens": 2},
        {"prompt_tokens": 1_000_001, "completion_tokens": 2},
        {"prompt_tokens": 3},
        [],
    ],
)
def test_invalid_usage_is_unknown(usage):
    result, _ = call(lambda _: response(usage=usage))
    assert (
        result.status == "proposed"
        and result.usage is None
        and result.cost_status == "unknown"
    )


def test_http_rejection_retains_valid_usage_but_no_body():
    result, _ = call(
        lambda _: httpx.Response(
            429,
            json={
                "usage": {"prompt_tokens": 12, "completion_tokens": 7},
                "error": "private raw body",
            },
        )
    )
    assert result.reason == "http_429" and result.usage == {
        "prompt_tokens": 12,
        "completion_tokens": 7,
    }
    assert "private" not in str(result)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_run_reserved_tokens", float("inf")),
        ("max_run_reserved_tokens", 1.5),
        ("max_run_reserved_tokens", True),
        ("max_run_reserved_tokens", 1_000_000_001),
        ("max_run_requests", True),
        ("max_attempts", 1.0),
        ("concurrency", 2.0),
        ("timeout_seconds", float("nan")),
        ("timeout_seconds", True),
        ("min_interval_seconds", float("inf")),
        ("enabled", 1),
    ],
)
def test_nonfinite_or_wrong_type_configuration_rejected(field, value):
    with pytest.raises(ValueError):
        replace(CONFIG, **{field: value})


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://@provider.example",
        "https://provider.example:",
        "https://provider.example:0",
        "https://provider.example:65536",
        "https://provider.example:notaport",
        "https://provider.example/with space",
        "https://provider.example/\tpath",
        "https://provider.example/\x7fpath",
        "https://provider.example\\@evil.example",
        "https://[notipv6]",
    ],
)
def test_malformed_endpoints_rejected(endpoint):
    with pytest.raises(ValueError):
        replace(CONFIG, endpoint=endpoint)


@pytest.mark.parametrize(
    "changes",
    [
        {"pricing_source": "token=abcdef123456"},
        {"pricing_source": "line\nbreak"},
        {"pricing_date": "2026-02-30"},
        {"currency": "USDX"},
        {"input_price_per_million": float("nan")},
        {"output_price_per_million": True},
    ],
)
def test_pricing_requires_safe_auditable_metadata(changes):
    values = {
        "input_price_per_million": 2,
        "output_price_per_million": 4,
        "pricing_source": "controlled fixture",
        "pricing_date": "2026-09-30",
        "currency": "USD",
    }
    with pytest.raises(ValueError):
        replace(CONFIG, **(values | changes))


def test_transport_ignores_ambient_environment_and_configuration_is_readonly(
    monkeypatch,
):
    original = httpx.Client
    captured = []

    def client(*args, **kwargs):
        captured.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    provider = HTTPModelProvider(
        CONFIG, transport=httpx.MockTransport(lambda _: response())
    )
    try:
        assert (
            captured[0]["trust_env"] is False
            and captured[0]["follow_redirects"] is False
        )
        with pytest.raises(AttributeError):
            provider.config = replace(CONFIG, model="cannot-change-mid-flight")
    finally:
        provider.close()


def test_budget_boundary_failure_prevents_transport():
    class RejectBudget(RunBudget):
        def reserve(self, config, reserved_tokens):
            raise ProviderBoundaryError("immutable_input_changed")

    result, calls = call(budget=RejectBudget())
    assert result.reason == "immutable_input_changed" and not calls


def test_cancellation_after_reservation_counts_without_transport():
    cancel = threading.Event()

    class CancelBudget(RunBudget):
        def reserve(self, config, reserved_tokens):
            number = super().reserve(config, reserved_tokens)
            cancel.set()
            return number

    budget = CancelBudget()
    result, calls = call(budget=budget, cancel=cancel)
    assert result.reason == "cancelled" and not calls
    assert budget.requests == 1 and budget.reserved_tokens > 0


def test_total_deadline_bounds_missing_headers_and_prevents_new_threads():
    release, finished, entered = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def handler(request):
        calls.append(request)
        entered.set()
        try:
            assert release.wait(3)
            return httpx.Response(200, content=b"")
        finally:
            finished.set()

    provider = HTTPModelProvider(
        replace(CONFIG, timeout_seconds=0.08, max_attempts=3),
        transport=httpx.MockTransport(handler),
    )
    budget = RunBudget()
    try:
        start = time.monotonic()
        result = provider.propose(
            deterministic_category="product_defect", evidence=EVIDENCE, budget=budget
        )
        assert entered.is_set() and time.monotonic() - start < 1
        assert result.reason == "transport_deadline_exceeded"
        assert budget.requests == 1
        result = provider.propose(
            deterministic_category="product_defect", evidence=EVIDENCE, budget=budget
        )
        assert (
            result.reason == "provider_closed"
            and len(calls) == 1
            and budget.requests == 1
        )
    finally:
        release.set()
        assert finished.wait(3)
        provider.close()


def test_stream_reads_are_explicitly_chunk_bounded(monkeypatch):
    original = httpx.Response.iter_bytes
    sizes = []

    def bounded(self, chunk_size=None):
        sizes.append(chunk_size)
        yield from original(self, chunk_size=chunk_size)

    monkeypatch.setattr(httpx.Response, "iter_bytes", bounded)
    result, _ = call()
    assert result.status == "proposed" and 16384 in sizes


def test_compressed_body_is_rejected_before_decompression():
    import gzip

    def handler(request):
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            content=gzip.compress(b"x" * 100_000),
        )

    result, requests = call(handler)
    assert result.reason == "unsupported_content_encoding" and result.proposal is None
    assert len(requests) == 1
