"""Publication boundary regressions for malformed claim predicate field types."""

from copy import deepcopy
from dataclasses import replace

import pytest
from failurelens.analysis import analyze_failure
from failurelens.evidence_validation import (
    validate_decision,
    validate_evidence_records,
    validated_evidence_views,
)
from failurelens.models import Category, Failure, Outcome
from failurelens.schemas import IngestionRequest
from failurelens.schemas import TestObservation as Observation
from failurelens.service import (
    create_project,
    ingest_normalized,
    select_failure_evidence,
)
from sqlalchemy import select


@pytest.fixture
def supported_classification(session):
    project = create_project(session, "predicate-types", "Predicate type validation")
    run = ingest_normalized(
        session,
        project,
        IngestionRequest(
            external_id="predicate-types-run",
            observations=[
                Observation(
                    test_identity="payments::balance",
                    outcome=Outcome.failed,
                    message="duplicate committed transfer left ledger unbalanced",
                    details={"data_integrity_violation": True},
                )
            ],
        ),
    )
    failure = session.scalar(select(Failure).where(Failure.run_id == run.id))
    assert failure is not None
    rows = select_failure_evidence(session, failure)
    checked = validate_evidence_records(failure, rows)
    decision = analyze_failure(
        message=failure.message,
        exception_type=failure.exception_type,
        details=failure.execution.details,
        evidence=validated_evidence_views(rows, checked),
    )
    assert decision.category is Category.product_defect
    assert decision.claims[0]["predicate"]["kind"] == "classification_signal"
    return failure, rows, checked, decision


@pytest.mark.parametrize(
    "field,value",
    [
        pytest.param("category", ["product_defect"], id="list-category"),
        pytest.param("category", {"value": "product_defect"}, id="object-category"),
        pytest.param("category", None, id="null-category"),
        pytest.param("category", "unsupported", id="unknown-category"),
        pytest.param("minimum_score", True, id="boolean-true-score"),
        pytest.param("minimum_score", False, id="boolean-false-score"),
        pytest.param("minimum_score", "3", id="string-score"),
        pytest.param("minimum_score", 3.0, id="float-score"),
        pytest.param("minimum_score", None, id="null-score"),
        pytest.param("minimum_score", [3], id="list-score"),
        pytest.param("minimum_score", {"value": 3}, id="object-score"),
        pytest.param("minimum_score", -1, id="negative-score"),
    ],
)
def test_malformed_classification_fields_are_withheld(
    supported_classification, field, value
):
    failure, rows, checked, decision = supported_classification
    claim = deepcopy(decision.claims[0])
    claim["predicate"][field] = value

    published = validate_decision(
        failure=failure,
        decision=replace(decision, claims=(claim,)),
        evidence_rows=rows,
        evidence_validation=checked,
        historical={},
    )

    assert published.category is Category.insufficient_evidence
    assert not published.claims
    assert "safe_abstention" in published.policy_flags
    assert "unsupported_claim_withheld" in published.policy_flags
    claim_check = published.validation_results["claims"][0]
    assert claim_check["reference_valid"] is True
    assert claim_check["typed_predicate_valid"] is False
    assert "unsupported_typed_predicate" in claim_check["reasons"]


@pytest.mark.parametrize("minimum_score", [0, 1, 3])
def test_supported_integer_scores_preserve_classification(
    supported_classification, minimum_score
):
    failure, rows, checked, decision = supported_classification
    claim = deepcopy(decision.claims[0])
    claim["predicate"]["minimum_score"] = minimum_score

    published = validate_decision(
        failure=failure,
        decision=replace(decision, claims=(claim,)),
        evidence_rows=rows,
        evidence_validation=checked,
        historical={},
    )

    assert published.category is Category.product_defect
    assert len(published.claims) == 1
    assert published.claims[0]["validation_status"] == "verified"
    assert published.abstention_reason is None


def test_malformed_claim_does_not_prevent_independent_valid_claim(
    supported_classification,
):
    failure, rows, checked, decision = supported_classification
    malformed = deepcopy(decision.claims[0])
    malformed["id"] = "malformed-claim"
    malformed["predicate"]["category"] = ["product_defect"]

    published = validate_decision(
        failure=failure,
        decision=replace(decision, claims=(malformed, *decision.claims)),
        evidence_rows=rows,
        evidence_validation=checked,
        historical={},
    )

    assert published.category is Category.product_defect
    assert len(published.claims) == 1
    assert published.claims[0]["id"] == decision.claims[0]["id"]
    assert "unsupported_claim_withheld" in published.policy_flags
    assert published.validation_results["status"] == "degraded"
    assert published.validation_results["claims"][0]["status"] == "rejected"
    assert published.validation_results["claims"][1]["status"] == "verified"
