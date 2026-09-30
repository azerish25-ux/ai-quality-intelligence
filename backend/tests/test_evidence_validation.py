from pathlib import Path

from failurelens.analysis import DeterministicDecision
from failurelens.config import get_settings
from failurelens.evidence_validation import (
    validate_decision,
    validate_evidence_records,
)
from failurelens.models import Category, Failure, Outcome
from failurelens.schemas import IngestionRequest
from failurelens.schemas import TestObservation as Observation
from failurelens.service import (
    analyze_and_persist,
    create_project,
    ingest_normalized,
    select_failure_evidence,
)
from sqlalchemy import select


def _failure(
    session,
    *,
    slug: str,
    external_id: str,
    message: str,
    details: dict | None = None,
) -> Failure:
    project = create_project(session, slug, slug.title())
    run = ingest_normalized(
        session,
        project,
        IngestionRequest(
            external_id=external_id,
            observations=[
                Observation(
                    test_identity=f"{slug}::failure",
                    outcome=Outcome.failed,
                    message=message,
                    details=details or {},
                )
            ],
        ),
    )
    failure = session.scalar(select(Failure).where(Failure.run_id == run.id))
    assert failure is not None
    return failure


def test_safe_derivative_redacts_secrets_and_records_source_map(session) -> None:
    secret = "top-secret-bearer-value"
    email = "customer@example.com"
    failure = _failure(
        session,
        slug="redacted-derivative",
        external_id="redacted-derivative-run",
        message=(
            "duplicate committed transfer left ledger unbalanced; "
            f"Authorization: Bearer {secret}; contact {email}"
        ),
        details={
            "data_integrity_violation": True,
            "access_token": secret,
            "customer_email": email,
        },
    )
    evidence = select_failure_evidence(session, failure)[0]
    derivative = evidence.derivative
    assert derivative is not None

    content = (Path(get_settings().artifact_root) / derivative.storage_path).read_text(
        encoding="utf-8"
    )

    assert secret not in content
    assert email not in content
    assert "REDACTED" in content
    assert derivative.source_map["version"] == "source-map-v1"
    assert derivative.source_map["derivative"]["pointer"] == "/excerpt"
    assert derivative.approved is True
    assert derivative.restricted is False


def test_out_of_bounds_locator_forces_safe_abstention(session) -> None:
    failure = _failure(
        session,
        slug="locator-integrity",
        external_id="locator-integrity-run",
        message="duplicate committed transfer left ledger unbalanced",
        details={"data_integrity_violation": True},
    )
    first = analyze_and_persist(session, failure)
    evidence = select_failure_evidence(session, failure)[0]
    evidence.locator = {
        **evidence.locator,
        "derivative": {"kind": "json-pointer", "pointer": "/not-present"},
    }
    session.commit()

    second = analyze_and_persist(session, failure)

    assert second.id != first.id
    assert second.category is Category.insufficient_evidence
    check = second.validation_results["evidence"][0]
    assert check["locator_valid"] is False
    assert "invalid_or_out_of_bounds_locator" in check["reasons"]
    assert "evidence_validation_failed" in second.policy_flags


def test_cross_project_evidence_is_rejected_even_when_derivative_is_valid(
    session,
) -> None:
    first = _failure(
        session,
        slug="scope-a",
        external_id="scope-a-run",
        message="duplicate committed transfer left ledger unbalanced",
        details={"data_integrity_violation": True},
    )
    second = _failure(
        session,
        slug="scope-b",
        external_id="scope-b-run",
        message="browser process crashed after runner exited",
        details={"runner_diagnostic": True},
    )
    foreign_evidence = select_failure_evidence(session, first)

    result = validate_evidence_records(second, foreign_evidence)

    assert result.accepted_ids == ()
    assert result.rejected_ids == (foreign_evidence[0].id,)
    assert result.checks[0].authorized is False
    assert "evidence_outside_failure_scope" in result.checks[0].reasons


def test_forged_evidence_reference_is_withheld(session) -> None:
    failure = _failure(
        session,
        slug="forged-reference",
        external_id="forged-reference-run",
        message="duplicate committed transfer left ledger unbalanced",
        details={"data_integrity_violation": True},
    )
    evidence_rows = select_failure_evidence(session, failure)
    evidence_validation = validate_evidence_records(failure, evidence_rows)
    decision = DeterministicDecision(
        category=Category.product_defect,
        severity="high",
        score=0.9,
        score_kind="heuristic_score",
        explanation="validator regression",
        summary="Product defect",
        supporting_ids=("forged-evidence-id",),
        contradictory_ids=(),
        missing=(),
        claims=(
            {
                "id": "claim-forged",
                "kind": "inference",
                "text": "Observed signals support a probable product defect classification.",
                "evidence_ids": ["forged-evidence-id"],
                "predicate": {
                    "kind": "classification_signal",
                    "category": "product_defect",
                    "minimum_score": 3,
                },
                "validation_status": "pending",
            },
        ),
        hypotheses=(),
        next_steps=(),
        abstention_reason=None,
        policy_flags=(),
        signal_counts={"product_defect": 9},
    )

    validated = validate_decision(
        failure=failure,
        decision=decision,
        evidence_rows=evidence_rows,
        evidence_validation=evidence_validation,
        historical={
            "independent_runs": 1,
            "reviewed_known_flake": False,
            "retry_recovery_rate": 0.0,
        },
    )

    assert validated.category is Category.insufficient_evidence
    assert validated.claims == ()
    claim = validated.validation_results["claims"][0]
    assert claim["reference_valid"] is False
    assert "unresolved_or_unauthorized_evidence_reference" in claim["reasons"]
    assert "unsupported_claim_withheld" in validated.policy_flags
