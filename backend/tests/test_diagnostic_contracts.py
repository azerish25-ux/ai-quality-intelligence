"""M6.4 development regressions; not an independent held-out benchmark."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest
from sqlalchemy import select

from failurelens.analysis import EvidenceView, analyze_failure
from failurelens.config import get_settings
from failurelens.contract_evidence import CLAIM_TEXT, CONTRACT_CATEGORY, inspect_contract, parse_contract_observation
from failurelens.evidence_validation import validate_decision, validate_evidence_records, validated_evidence_views
from failurelens.models import Category, Failure
from failurelens.service import analyze_and_persist, select_failure_evidence
from test_contract_evidence import bundle, ingest

KINDS = ("atomic_transfer", "tenant_isolation", "status_expectation", "runner_memory_limit")


def diagnostic(kind="atomic_transfer", establishes=True):
    measurements = {
        "atomic_transfer": dict(kind=kind, atomicity_policy="both_effects_or_neither",
            observation_scope="isolated_logical_request", request_digest="a"*64, receipt_request_digest="a"*64,
            source_account_digest="b"*64, destination_account_digest="c"*64, currency="CAD", amount_minor=25,
            receipt_outcome="committed", concurrent_writers=0, before_source_minor=100, before_destination_minor=50,
            after_source_minor=75, after_destination_minor=50 if establishes else 75),
        "tenant_isolation": dict(kind=kind, access_policy="same_tenant_resource_access", principal_scope="tenant_member",
            actor_tenant_digest="a"*64, resource_tenant_digest="b"*64, requested_resource_digest="c"*64,
            returned_resource_digest="c"*64 if establishes else None, response_status=200 if establishes else 403),
        "status_expectation": dict(kind=kind, assertion_scope="response_status_equality",
            contract_source="versioned_api_contract", contract_digest="a"*64, served_contract_digest="a"*64,
            allowed_statuses=[200], observed_status=200, asserted_status=201 if establishes else 200),
        "runner_memory_limit": dict(kind=kind, process_role="test_runner", counter_scope="isolated_runner_cgroup",
            runner_process_digest="a"*64, killed_process_digest="a"*64, memory_limit_bytes=1048576,
            peak_memory_bytes=1048576, oom_kills_before=3, oom_kills_after=4 if establishes else 3,
            termination_signal=9 if establishes else 15),
    }
    return dict(schema_version="contract-observations-v1", test_identity="measurement::result", attempt=0,
                browser=None, measurement=measurements[kind])


def decide(*values, message="Observed relationship mismatch", details=None):
    return analyze_failure(message=message, exception_type="AssertionError", details=details or {},
        evidence=[EvidenceView(str(i), "contract_observation", json.dumps(v), {"contract_observation": v})
                  for i, v in enumerate(values)])


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("establishes", [True, False])
def test_numeric_relationship_not_verdict_or_trigger_word(kind, establishes):
    record = diagnostic(kind, establishes)
    assert parse_contract_observation(json.dumps(record).encode()) == record
    assert inspect_contract(record).status == ("violated" if establishes else "conforms")
    result = decide(record)
    assert result.category.value == (CONTRACT_CATEGORY[kind] if establishes else "insufficient_evidence")
    if establishes:
        assert result.claims[0]["text"] == CLAIM_TEXT[kind]
        assert result.claims[0]["predicate"] == {"kind": "contract_violation", "contract": kind}
    else:
        assert result.claims == ()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("field", ["expected_category", "oracle", "fault_enabled", "root_cause"])
def test_diagnostics_reject_answer_fields(kind, field):
    value = diagnostic(kind)
    value["measurement"][field] = "product_defect"
    with pytest.raises(ValueError):
        parse_contract_observation(json.dumps(value).encode())
    assert decide(value).category == Category.insufficient_evidence


@pytest.mark.parametrize("bad", [True, False, 25.0, "25", -1, 0, 10**13])
def test_minor_unit_amount_is_strict_positive_and_bounded(bad):
    record = diagnostic()
    record["measurement"]["amount_minor"] = bad
    assert inspect_contract(record).status == "invalid"


@pytest.mark.parametrize("changes, status", [
    ({"receipt_request_digest": "d"*64}, "conflicting"),
    ({"destination_account_digest": "b"*64}, "conflicting"),
    ({"concurrent_writers": 1}, "conflicting"),
    ({"receipt_outcome": "unresolved"}, "incomplete"),
    ({"before_source_minor": None}, "incomplete"),
    ({"after_destination_minor": None}, "incomplete"),
])
def test_atomicity_requires_isolation_correlation_and_complete_snapshots(changes, status):
    value = diagnostic(); value["measurement"].update(changes)
    assert inspect_contract(value).status == status
    assert decide(value).category == Category.insufficient_evidence


def test_conservation_alone_cannot_hide_wrong_transfer_amount():
    value = diagnostic(); value["measurement"].update(after_source_minor=90, after_destination_minor=60)
    assert inspect_contract(value).status == "violated"


def test_rolled_back_receipt_requires_both_balances_unchanged():
    value = diagnostic(); value["measurement"].update(receipt_outcome="rolled_back", after_source_minor=100, after_destination_minor=50)
    assert inspect_contract(value).status == "conforms"
    value["measurement"]["after_source_minor"] = 75
    assert inspect_contract(value).status == "violated"


@pytest.mark.parametrize("changes,status", [
    ({"returned_resource_digest": None}, "incomplete"),
    ({"returned_resource_digest": "d"*64}, "conflicting"),
    ({"response_status": None}, "incomplete"),
    ({"actor_tenant_digest": "b"*64}, "conforms"),
    ({"response_status": 403}, "violated"),
])
def test_tenant_diagnosis_requires_actual_correlated_content(changes, status):
    value = diagnostic("tenant_isolation"); value["measurement"].update(changes)
    assert inspect_contract(value).status == status


@pytest.mark.parametrize("changes,status", [
    ({"served_contract_digest": "b"*64}, "conflicting"),
    ({"allowed_statuses": [200, 200]}, "conflicting"),
    ({"allowed_statuses": [200, 201]}, "incomplete"),
    ({"observed_status": 500}, "conflicting"),
    ({"observed_status": None}, "incomplete"),
    ({"asserted_status": None}, "incomplete"),
])
def test_test_blame_requires_matching_contract_and_conforming_response(changes, status):
    value = diagnostic("status_expectation"); value["measurement"].update(changes)
    assert inspect_contract(value).status == status
    assert decide(value).category == Category.insufficient_evidence


@pytest.mark.parametrize("changes,status", [
    ({"killed_process_digest": "b"*64}, "conflicting"),
    ({"killed_process_digest": None}, "incomplete"),
    ({"peak_memory_bytes": 100}, "conflicting"),
    ({"peak_memory_bytes": None}, "incomplete"),
    ({"oom_kills_after": 2}, "conflicting"),
    ({"oom_kills_after": 3}, "incomplete"),
    ({"termination_signal": 15}, "conflicting"),
    ({"process_role": "application"}, "invalid"),
    ({"counter_scope": "whole_host"}, "invalid"),
])
def test_oom_requires_runner_scoped_correlated_measurements(changes, status):
    value = diagnostic("runner_memory_limit"); value["measurement"].update(changes)
    assert inspect_contract(value).status == status
    assert decide(value).category == Category.insufficient_evidence


@pytest.mark.parametrize("kind", ["status_expectation", "runner_memory_limit"])
def test_typed_nonproduct_diagnosis_never_overrides_product_risk(kind):
    result = decide(diagnostic(kind), message="double charge", details={"runner_diagnostic": True})
    assert result.category == Category.insufficient_evidence
    assert "dangerous_downgrade_blocked" in result.policy_flags
    assert decide(diagnostic(kind), diagnostic()).category == Category.insufficient_evidence


@pytest.mark.parametrize("kind", KINDS)
def test_conflicting_duplicate_diagnostics_are_not_cherry_picked(kind):
    assert decide(diagnostic(kind), diagnostic(kind, False)).category == Category.insufficient_evidence


@pytest.mark.parametrize("kind", KINDS)
def test_published_api_worker_diagnosis_binds_one_execution(client, session, kind):
    state = ingest(client, session, bundle(diagnostic(kind), extra=True))
    assert state["state"] == "succeeded"
    failures = list(session.scalars(select(Failure).where(Failure.run_id == state["run_id"])))
    for failure in failures:
        result = analyze_and_persist(session, failure)
        if failure.execution.test_identity == "measurement::result":
            assert result.category.value == CONTRACT_CATEGORY[kind]
            assert result.claims[0]["validation_status"] == "verified"
            assert result.validation_results["diagnostic_gap"] is None
            assert result.validation_results["diagnostic_findings"][0]["contract"] == kind
        else:
            assert result.category == Category.insufficient_evidence
            assert result.validation_results["diagnostic_findings"] == []


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("change", ["category", "text", "predicate", "reference"])
def test_publisher_recomputes_category_wording_and_evidence(client, session, kind, change):
    state = ingest(client, session, bundle(diagnostic(kind)))
    failure = session.scalar(select(Failure).where(Failure.run_id == state["run_id"]))
    rows = select_failure_evidence(session, failure)
    checks = validate_evidence_records(failure, rows)
    result = analyze_failure(message=failure.message, exception_type=None, details={}, evidence=validated_evidence_views(rows, checks))
    claim = deepcopy(result.claims[0])
    if change == "category": result = replace(result, category=Category.known_flake)
    if change == "text": claim["text"] += " This proves the product is healthy."
    if change == "predicate": claim["predicate"]["contract"] = "weekly_recurrence"
    if change == "reference": claim["evidence_ids"] = ["another-project"]
    published = validate_decision(failure=failure, decision=replace(result, claims=(claim,)), evidence_rows=rows,
                                 evidence_validation=checks, historical={})
    assert published.category == Category.insufficient_evidence and not published.claims
    assert published.validation_results["diagnostic_gap"] == "publication_rejection"


def test_missing_and_conflicting_observations_have_distinct_explanations(client, session):
    value = diagnostic(); value["measurement"]["after_source_minor"] = None
    state = ingest(client, session, bundle(value))
    failure = session.scalar(select(Failure).where(Failure.run_id == state["run_id"]))
    result = analyze_and_persist(session, failure)
    assert result.validation_results["diagnostic_gap"] == "missing_or_invalid_observations"
    assert "before/after" in result.validation_results["diagnostic_findings"][0]["reason"]
