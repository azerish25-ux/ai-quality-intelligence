"""Finality diagnostics: bounded observations, not proof of a database defect."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from failurelens.analysis import analyze_failure
from failurelens.contract_evidence import (
    CLAIM_TEXT,
    ContractObservation,
    inspect_contract,
    parse_contract_observation,
)
from failurelens.evidence_validation import (
    validate_decision,
    validate_evidence_records,
    validated_evidence_views,
)
from failurelens.models import Category, Failure
from failurelens.service import analyze_and_persist, select_failure_evidence
from sqlalchemy import select
from test_contract_evidence import bundle, ingest
from test_diagnostic_contracts import decide, diagnostic

from evaluation.campaign_harness import independent_contract
from integrations.ledgerguard.rollback import synthetic_observation

KIND = "transaction_finality"
MEASUREMENTS = (
    "before_source_minor",
    "before_destination_minor",
    "after_source_minor",
    "after_destination_minor",
    "new_transfer_count",
    "new_journal_entry_count",
    "new_debit_minor",
    "new_credit_minor",
)


@pytest.mark.parametrize("effects", [True, False])
def test_finality_diagnoses_observed_effects_not_generic_http_error(effects):
    value = synthetic_observation(effects=effects)
    assert parse_contract_observation(json.dumps(value).encode()) == value
    assert inspect_contract(value).status == ("violated" if effects else "conforms")
    result = decide(value)
    assert result.category == (
        Category.product_defect if effects else Category.insufficient_evidence
    )
    if effects:
        assert result.claims[0]["text"] == CLAIM_TEXT[KIND]
        assert result.claims[0]["predicate"] == {
            "kind": "contract_violation",
            "contract": KIND,
        }
    else:
        assert not result.claims
    assert independent_contract(value) == (KIND if effects else None)


@pytest.mark.parametrize("field", MEASUREMENTS)
def test_each_required_measurement_missing_preserves_abstention(field):
    value = synthetic_observation()
    value["measurement"][field] = None
    assert inspect_contract(value).status == "incomplete"
    assert decide(value).category == Category.insufficient_evidence
    assert independent_contract(value) is None


@pytest.mark.parametrize(
    "changes,status",
    [
        ({"receipt_request_digest": "f" * 64}, "conflicting"),
        ({"served_contract_digest": "f" * 64}, "conflicting"),
        ({"concurrent_writers": 1}, "conflicting"),
        ({"response_basis": "transport_only"}, "incomplete"),
        ({"response_basis": "unresolved"}, "incomplete"),
        ({"response_status": 503, "response_code": "OUTCOME_UNKNOWN"}, "incomplete"),
        (
            {"response_status": 422, "response_code": "DEPENDENCY_UNAVAILABLE"},
            "incomplete",
        ),
        ({"response_status": None}, "incomplete"),
        ({"response_code": None}, "incomplete"),
        ({"snapshot_basis": "replica"}, "invalid"),
        ({"observation_scope": "whole_run"}, "invalid"),
        ({"finality_policy": "every_error_rolls_back"}, "invalid"),
    ],
)
def test_no_reassurance_from_ambiguous_or_unbound_observations(changes, status):
    value = synthetic_observation()
    value["measurement"].update(changes)
    assert inspect_contract(value).status == status
    assert decide(value).category == Category.insufficient_evidence
    assert independent_contract(value) is None


def test_identical_accounts_are_not_a_two_account_observation():
    value = synthetic_observation()
    value["measurement"]["destination_account_digest"] = value["measurement"][
        "source_account_digest"
    ]
    assert inspect_contract(value).status == "conflicting"
    assert independent_contract(value) is None


@pytest.mark.parametrize(
    "field",
    [
        "amount_minor",
        *MEASUREMENTS,
        "concurrent_writers",
        "response_status",
        "rejection_status",
    ],
)
@pytest.mark.parametrize("bad", [True, "7", 7.0, 2**54])
def test_strict_numeric_types_and_bounds_are_independently_enforced(field, bad):
    value = synthetic_observation()
    value["measurement"][field] = bad
    assert inspect_contract(value).status == "invalid"
    assert independent_contract(value) is None


@pytest.mark.parametrize(
    "field", ["expected_category", "oracle", "fault_enabled", "root_cause"]
)
def test_no_producer_answer_field_is_accepted(field):
    value = synthetic_observation()
    value["measurement"][field] = "product_defect"
    with pytest.raises(ValueError):
        parse_contract_observation(json.dumps(value).encode())
    assert independent_contract(value) is None


@pytest.mark.parametrize(
    "field",
    [
        "new_transfer_count",
        "new_journal_entry_count",
        "new_debit_minor",
        "new_credit_minor",
    ],
)
def test_negative_effect_counts_are_invalid(field):
    value = synthetic_observation()
    value["measurement"][field] = -1
    assert inspect_contract(value).status == "invalid"
    assert independent_contract(value) is None


@pytest.mark.parametrize("field", MEASUREMENTS[2:])
def test_each_observable_effect_can_reveal_rejection_contract_violation(field):
    value = synthetic_observation(effects=False)
    value["measurement"][field] += 1
    assert inspect_contract(value).status == "violated"
    assert independent_contract(value) == KIND


def test_independent_scorer_does_not_reuse_runtime_predicate(monkeypatch):
    import failurelens.contract_evidence as runtime

    def forbidden(*args, **kwargs):
        raise AssertionError("Scorer imported production answer")

    monkeypatch.setattr(runtime, "inspect_contract", forbidden)
    assert independent_contract(synthetic_observation()) == KIND


def test_contradiction_cannot_be_cherry_picked_and_nonproduct_cannot_override():
    assert (
        decide(synthetic_observation(), synthetic_observation(effects=False)).category
        == Category.insufficient_evidence
    )
    assert (
        decide(synthetic_observation(), diagnostic("status_expectation")).category
        == Category.insufficient_evidence
    )
    assert (
        decide(synthetic_observation(), diagnostic("runner_memory_limit")).category
        == Category.insufficient_evidence
    )


def test_permutations_and_nuisance_ids_do_not_change_substantive_diagnosis():
    value = synthetic_observation()
    changed = deepcopy(value)
    changed["measurement"]["request_digest"] = changed["measurement"][
        "receipt_request_digest"
    ] = "e" * 64
    changed["measurement"] = dict(reversed(list(changed["measurement"].items())))
    assert decide(value).category == decide(changed).category == Category.product_defect
    assert decide(value).claims[0]["text"] == decide(changed).claims[0]["text"]


def test_api_worker_scopes_finality_to_exact_execution(client, session):
    state = ingest(client, session, bundle(synthetic_observation(), extra=True))
    assert state["state"] == "succeeded"
    failures = list(
        session.scalars(select(Failure).where(Failure.run_id == state["run_id"]))
    )
    assert len(failures) == 2
    for failure in failures:
        result = analyze_and_persist(session, failure)
        if failure.execution.test_identity == "measurement::result":
            assert result.category == Category.product_defect
            assert result.claims[0]["validation_status"] == "verified"
            assert result.validation_results["diagnostic_gap"] is None
            assert (
                result.validation_results["diagnostic_findings"][0]["contract"] == KIND
            )
        else:
            assert result.category == Category.insufficient_evidence
            assert not result.validation_results["diagnostic_findings"]


@pytest.mark.parametrize("change", ["category", "text", "predicate", "reference"])
def test_publication_recomputes_finality_claim(client, session, change):
    state = ingest(client, session, bundle(synthetic_observation()))
    failure = session.scalar(select(Failure).where(Failure.run_id == state["run_id"]))
    rows = select_failure_evidence(session, failure)
    checks = validate_evidence_records(failure, rows)
    result = analyze_failure(
        message=failure.message,
        exception_type=None,
        details={},
        evidence=validated_evidence_views(rows, checks),
    )
    claim = deepcopy(result.claims[0])
    if change == "category":
        result = replace(result, category=Category.known_flake)
    if change == "text":
        claim["text"] += " PostgreSQL is faulty and all other behavior is harmless."
    if change == "predicate":
        claim["predicate"]["contract"] = "atomic_transfer"
    if change == "reference":
        claim["evidence_ids"] = ["another-project"]
    published = validate_decision(
        failure=failure,
        decision=replace(result, claims=(claim,)),
        evidence_rows=rows,
        evidence_validation=checks,
        historical={},
    )
    assert published.category == Category.insufficient_evidence and not published.claims
    assert published.validation_results["diagnostic_gap"] == "publication_rejection"


@pytest.mark.parametrize(
    "field,value",
    [("attempt", 1), ("browser", "other-browser"), ("test_identity", "other::test")],
)
def test_cross_execution_measurements_are_not_bound(client, session, field, value):
    record = synthetic_observation()
    record[field] = value
    state = ingest(client, session, bundle(record))
    failure = session.scalar(select(Failure).where(Failure.run_id == state["run_id"]))
    result = analyze_and_persist(session, failure)
    assert result.category == Category.insufficient_evidence
    assert not result.validation_results["diagnostic_findings"]


def test_finality_schema_retains_existing_variants():
    root = Path(__file__).resolve().parents[2]
    schema = json.loads(
        (root / "evaluation/schemas/contract-observations.schema.json").read_bytes()
    )
    assert schema == ContractObservation.model_json_schema()
    assert {"AtomicTransfer", "OperationIsolation", "TransactionFinality"} <= set(
        schema["$defs"]
    )
