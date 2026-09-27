from sqlalchemy import func, select

from failurelens.models import Analysis, Failure, Outcome
from failurelens.schemas import IngestionRequest, TestObservation as Observation
from failurelens.service import analyze_and_persist, create_project, ingest_normalized


def request() -> IngestionRequest:
    return IngestionRequest(
        external_id="run-1",
        repository="owner/repo",
        commit_sha="abcdef0",
        expected_inputs=1,
        observations=[
            Observation(test_identity="ledger::balanced", parameterization="CAD", outcome=Outcome.failed, message="ledger unbalanced after duplicate committed", details={"data_integrity_violation": True}),
            Observation(test_identity="health::ok", outcome=Outcome.passed, duration_ms=12),
        ],
    )


def test_ingestion_is_idempotent_and_analysis_is_persisted(session) -> None:
    project = create_project(session, "demo-project", "Demo")
    first = ingest_normalized(session, project, request())
    second = ingest_normalized(session, project, request())
    assert first.id == second.id
    failures = list(session.scalars(select(Failure).where(Failure.run_id == first.id)).all())
    assert len(failures) == 1
    assert failures[0].execution.parameterization == "CAD"
    analysis = analyze_and_persist(session, failures[0])
    duplicate = analyze_and_persist(session, failures[0])
    assert analysis.id == duplicate.id
    assert analysis.category.value == "product_defect"
    assert session.scalar(select(func.count(Analysis.id))) == 1


def test_incomplete_run_is_explicit(session) -> None:
    project = create_project(session, "partial-project", "Partial")
    payload = request().model_copy(update={"external_id": "run-2", "expected_inputs": 2})
    run = ingest_normalized(session, project, payload)
    assert run.completeness == "partial"
    assert run.status.value == "partial"


def test_failure_evidence_is_execution_scoped_and_claims_are_validated(session) -> None:
    from failurelens.models import Evidence
    from failurelens.service import select_failure_evidence

    project = create_project(session, "scope-project", "Scope")
    payload = IngestionRequest(
        external_id="scope-run",
        expected_inputs=1,
        observations=[
            Observation(
                test_identity="ledger::duplicate",
                outcome=Outcome.failed,
                message="duplicate committed transfer left the ledger unbalanced",
                details={"data_integrity_violation": True},
            ),
            Observation(
                test_identity="browser::startup",
                outcome=Outcome.failed,
                message="browser process crashed after runner exited",
                details={"runner_diagnostic": True},
            ),
        ],
    )
    run = ingest_normalized(session, project, payload)
    failures = list(
        session.scalars(
            select(Failure)
            .where(Failure.run_id == run.id)
            .order_by(Failure.message)
        ).all()
    )
    assert len(failures) == 2

    by_test = {failure.execution.test_identity: failure for failure in failures}
    product_failure = by_test["ledger::duplicate"]
    infra_failure = by_test["browser::startup"]

    product_evidence = select_failure_evidence(session, product_failure)
    infra_evidence = select_failure_evidence(session, infra_failure)
    assert {item.execution_id for item in product_evidence} == {
        product_failure.execution_id
    }
    assert {item.execution_id for item in infra_evidence} == {
        infra_failure.execution_id
    }
    assert {item.id for item in product_evidence}.isdisjoint(
        {item.id for item in infra_evidence}
    )

    product_analysis = analyze_and_persist(session, product_failure)
    infra_analysis = analyze_and_persist(session, infra_failure)
    assert product_analysis.category.value == "product_defect"
    assert infra_analysis.category.value == "infrastructure_failure"
    assert product_analysis.validation_results["status"] == "passed"
    assert infra_analysis.validation_results["status"] == "passed"
    assert product_analysis.claims[0]["validation_status"] == "verified"
    assert infra_analysis.claims[0]["validation_status"] == "verified"
    assert set(product_analysis.supporting_evidence_ids) == {
        item.id for item in product_evidence
    }
    assert set(infra_analysis.supporting_evidence_ids) == {
        item.id for item in infra_evidence
    }

    all_evidence = list(
        session.scalars(select(Evidence).where(Evidence.run_id == run.id)).all()
    )
    assert len(all_evidence) == 2


def test_modified_safe_derivative_forces_new_abstaining_revision(session) -> None:
    from failurelens.config import get_settings
    from failurelens.models import Evidence

    project = create_project(session, "integrity-project", "Integrity")
    run = ingest_normalized(
        session,
        project,
        request().model_copy(update={"external_id": "integrity-run"}),
    )
    failure = session.scalar(select(Failure).where(Failure.run_id == run.id))
    assert failure is not None
    first = analyze_and_persist(session, failure)
    assert first.category.value == "product_defect"
    assert first.validation_results["status"] == "passed"

    evidence = session.scalar(
        select(Evidence).where(Evidence.execution_id == failure.execution_id)
    )
    assert evidence is not None and evidence.derivative is not None
    derivative_path = get_settings().artifact_root / evidence.derivative.storage_path
    original = derivative_path.read_bytes()
    derivative_path.write_bytes(b"x" * len(original))

    second = analyze_and_persist(session, failure)
    assert second.id != first.id
    assert second.revision == first.revision + 1
    assert second.category.value == "insufficient_evidence"
    assert second.validation_results["status"] == "degraded"
    assert second.validation_results["rejected_evidence_ids"] == [evidence.id]
    assert "evidence_validation_failed" in second.policy_flags
    assert "validated execution-scoped evidence" in second.missing_evidence


def test_valid_but_irrelevant_citation_is_withheld(session) -> None:
    from failurelens.analysis import DeterministicDecision
    from failurelens.evidence_validation import (
        validate_decision,
        validate_evidence_records,
    )
    from failurelens.models import Category
    from failurelens.service import select_failure_evidence

    project = create_project(session, "semantic-project", "Semantic")
    payload = IngestionRequest(
        external_id="semantic-run",
        observations=[
            Observation(
                test_identity="runner::crash",
                outcome=Outcome.failed,
                message="browser process crashed because the runner exited",
                details={"runner_diagnostic": True},
            )
        ],
    )
    run = ingest_normalized(session, project, payload)
    failure = session.scalar(select(Failure).where(Failure.run_id == run.id))
    assert failure is not None
    evidence_rows = select_failure_evidence(session, failure)
    validation = validate_evidence_records(failure, evidence_rows)
    assert validation.accepted_ids

    unsupported = DeterministicDecision(
        category=Category.product_defect,
        severity="high",
        score=0.9,
        score_kind="heuristic_score",
        explanation="synthetic decision for validator regression",
        summary="Unsupported product classification",
        supporting_ids=validation.accepted_ids,
        contradictory_ids=tuple(),
        missing=tuple(),
        claims=(
            {
                "id": "claim-irrelevant",
                "kind": "inference",
                "text": "Observed signals support a probable product defect classification.",
                "evidence_ids": list(validation.accepted_ids),
                "predicate": {
                    "kind": "classification_signal",
                    "category": "product_defect",
                    "minimum_score": 3,
                },
                "validation_status": "pending",
            },
        ),
        hypotheses=tuple(),
        next_steps=tuple(),
        abstention_reason=None,
        policy_flags=tuple(),
        signal_counts={"product_defect": 4},
    )
    result = validate_decision(
        failure=failure,
        decision=unsupported,
        evidence_rows=evidence_rows,
        evidence_validation=validation,
        historical={
            "independent_runs": 1,
            "reviewed_known_flake": False,
            "retry_recovery_rate": 0.0,
        },
    )
    assert result.category is Category.insufficient_evidence
    assert result.claims == tuple()
    assert result.validation_results["claims"][0]["semantic_support"] is False
    assert result.validation_results["claims"][0]["irrelevant_evidence_ids"] == list(
        validation.accepted_ids
    )
    assert "unsupported_claim_withheld" in result.policy_flags


def test_legacy_analysis_schema_withholds_unvalidated_stored_category(session) -> None:
    from failurelens.service import analysis_to_schema

    project = create_project(session, "legacy-analysis-project", "Legacy")
    run = ingest_normalized(
        session,
        project,
        request().model_copy(update={"external_id": "legacy-analysis-run"}),
    )
    failure = session.scalar(select(Failure).where(Failure.run_id == run.id))
    assert failure is not None
    analysis = analyze_and_persist(session, failure)
    analysis.validation_version = None
    analysis.validation_results = None
    session.commit()

    published = analysis_to_schema(analysis)

    assert published.category.value == "insufficient_evidence"
    assert published.claims == []
    assert published.supporting_evidence_ids == []
    assert published.validation_results["status"] == "not_validated"
    assert "legacy_analysis_not_publication_validated" in published.policy_flags
