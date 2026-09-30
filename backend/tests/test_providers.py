import json
import threading
from dataclasses import replace

import httpx
import pytest
from failurelens.providers import HTTPModelProvider, ProviderConfig, RunBudget

CONFIG = ProviderConfig(
    endpoint="https://provider.example/v1/chat/completions",
    model="test-fixture-not-a-model",
    token="fake-token",
    enabled=True,
    min_interval_seconds=0,
    max_attempts=1,
)
EVIDENCE = [{"id": "e1", "excerpt": "Observed response status 500", "approved": True}]
PROPOSAL = {
    "category": "product_defect",
    "hypotheses": [
        {"text": "Investigate the observed server response", "evidence_ids": ["e1"]}
    ],
    "contradictory_evidence_ids": [],
    "missing_evidence": [],
}


def response(proposal=None, **kwargs):
    value = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": json.dumps(proposal or PROPOSAL)},
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }
    value.update(kwargs)
    return httpx.Response(200, json=value)


def call(handler=lambda _: response(), config=CONFIG, **kwargs):
    requests = []

    def handle(req):
        requests.append(req)
        return handler(req)

    provider = HTTPModelProvider(config, transport=httpx.MockTransport(handle))
    try:
        result = provider.propose(
            **(
                {
                    "deterministic_category": "product_defect",
                    "evidence": EVIDENCE,
                    "budget": RunBudget(),
                }
                | kwargs
            )
        )
    finally:
        provider.close()
    return result, requests


def test_fixture_proposal_is_unverified_and_deterministic_preserved():
    result, requests = call()
    assert result.status == "proposed"
    assert result.validation_status == "unverified_hypotheses_only"
    assert result.deterministic_category == "product_defect"
    assert result.cost_status == "unknown" and result.estimated_cost is None
    payload = json.loads(requests[0].content)
    assert "tools" not in payload
    assert payload["model"] == "test-fixture-not-a-model"
    assert "fake-token" not in repr(CONFIG)


def test_disabled_mode_has_zero_egress():
    result, requests = call(config=replace(CONFIG, enabled=False))
    assert result.reason == "disabled" and not requests


@pytest.mark.parametrize(
    "evidence",
    [
        [{"id": "x", "excerpt": "secret", "approved": False}],
        [],
        EVIDENCE * 2,
        [{"id": "x", "excerpt": 99, "approved": True}],
    ],
)
def test_unapproved_or_invalid_context_never_sent(evidence):
    result, requests = call(evidence=evidence)
    assert result.status == "fallback" and not requests


def test_context_limit_and_cancellation():
    result, requests = call(
        evidence=[{"id": "x", "excerpt": "x" * 40_000, "approved": True}]
    )
    assert result.reason == "context_limit" and not requests
    event = threading.Event()
    event.set()
    result, requests = call(cancel=event)
    assert result.reason == "cancelled" and not requests


def test_sensitive_input_is_redacted_before_transport():
    _result, requests = call(
        evidence=[
            {
                "id": "e1",
                "excerpt": "token=abcdef123456 person@example.com",
                "approved": True,
            }
        ]
    )
    assert b"abcdef123456" not in requests[0].content
    assert b"person@example.com" not in requests[0].content


@pytest.mark.parametrize(
    "category",
    ["known_flake", "test_defect", "infrastructure_failure", "insufficient_evidence"],
)
def test_product_downgrade_cannot_replace_deterministic_risk(category):
    result, _ = call(lambda _: response(PROPOSAL | {"category": category}))
    assert result.reason == "product_risk_downgrade"
    assert result.deterministic_category == "product_defect"


def test_unknown_citations_rejected():
    result, _ = call(
        lambda _: response(PROPOSAL | {"contradictory_evidence_ids": ["foreign"]})
    )
    assert result.reason == "unknown_evidence_reference"


@pytest.mark.parametrize(
    "text",
    [
        "safe to merge",
        "release approved",
        "delete the test",
        "token=abcdef123456",
        "person@example.com",
    ],
)
def test_prohibited_or_sensitive_output_is_withheld(text):
    result, _ = call(
        lambda _: response(
            PROPOSAL | {"hypotheses": [{"text": text, "evidence_ids": ["e1"]}]}
        )
    )
    assert result.status == "fallback"
    assert result.proposal is None


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
def test_http_failure_is_explicit_without_response_leak(status):
    result, requests = call(
        lambda _: httpx.Response(status, text="private-token-response")
    )
    assert result.reason == f"http_{status}"
    assert "private-token" not in str(result)
    assert len(requests) == 1


def test_invalid_json_extra_fields_and_incomplete_outputs():
    for handler in [
        lambda _: httpx.Response(200, text="not json"),
        lambda _: response(PROPOSAL | {"action": "merge"}),
        lambda _: response(
            choices=[{"finish_reason": "length", "message": {"content": "{}"}}]
        ),
    ]:
        result, _ = call(handler)
        assert result.status == "fallback"


def test_bounded_response():
    result, _ = call(lambda _: httpx.Response(200, content=b"x" * 50_000))
    assert result.reason == "response_limit"


def test_shared_run_budget_and_circuit_breaker():
    requests = []

    def handle(req):
        requests.append(req)
        return httpx.Response(503)

    provider = HTTPModelProvider(
        replace(CONFIG, failure_threshold=1), transport=httpx.MockTransport(handle)
    )
    try:
        first = provider.propose(
            deterministic_category="product_defect",
            evidence=EVIDENCE,
            budget=RunBudget(),
        )
        second = provider.propose(
            deterministic_category="product_defect",
            evidence=EVIDENCE,
            budget=RunBudget(),
        )
        assert first.reason == "http_503"
        assert second.reason == "circuit_open" and len(requests) == 1
    finally:
        provider.close()
    result, requests = call(budget=RunBudget(requests=CONFIG.max_run_requests))
    assert result.reason == "run_budget_exhausted" and not requests
    result, requests = call(
        budget=RunBudget(reserved_tokens=CONFIG.max_run_reserved_tokens)
    )
    assert result.reason == "run_budget_exhausted" and not requests


def test_known_pricing_is_estimate_not_actual_spend():
    config = replace(
        CONFIG,
        input_price_per_million=2,
        output_price_per_million=4,
        pricing_source="operator test fixture",
        pricing_date="2026-09-30",
        currency="USD",
    )
    result, _ = call(config=config)
    assert result.cost_status == "estimated"
    assert result.estimated_cost == pytest.approx(0.0004)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://provider.example",
        "https://user:pass@provider.example",
        "https://provider.example?token=x",
        "https://provider.example/#fragment",
    ],
)
def test_endpoint_requires_trusted_configuration(endpoint):
    with pytest.raises(ValueError):
        replace(CONFIG, endpoint=endpoint)


def test_cost_metadata_must_be_complete():
    with pytest.raises(ValueError):
        replace(CONFIG, input_price_per_million=2)


def test_database_bridge_revalidates_derivative_and_never_changes_analysis(session):
    from failurelens.demo import seed_demo
    from failurelens.models import Analysis, Evidence
    from failurelens.provider_service import propose_for_analysis
    from sqlalchemy import select

    seed_demo(session)
    analysis = session.scalar(
        select(Analysis).where(Analysis.category == "product_defect")
    )
    before = analysis.summary, analysis.category, analysis.revision
    calls = []

    def handler(request):
        calls.append(request)
        payload = json.loads(request.content)
        context = json.loads(payload["messages"][1]["content"])
        proposal = PROPOSAL | {
            "hypotheses": [
                {
                    "text": "Inspect the measured effect",
                    "evidence_ids": [context["evidence"][0]["id"]],
                }
            ]
        }
        return response(proposal)

    provider = HTTPModelProvider(CONFIG, transport=httpx.MockTransport(handler))
    try:
        result = propose_for_analysis(session, analysis, provider, budget=RunBudget())
        assert result["status"] == "proposed"
        assert (analysis.summary, analysis.category, analysis.revision) == before
        for evidence in session.scalars(
            select(Evidence).where(Evidence.id.in_(analysis.supporting_evidence_ids))
        ):
            evidence.derivative.restricted = True
        session.commit()
        result = propose_for_analysis(session, analysis, provider, budget=RunBudget())
        assert result["status"] == "fallback"
        assert len(calls) == 1
    finally:
        provider.close()
