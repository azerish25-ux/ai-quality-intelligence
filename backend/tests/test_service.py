from sqlalchemy import select

from failurelens.models import Analysis, Failure, Outcome
from failurelens.schemas import IngestionRequest, TestObservation as Observation
from failurelens.service import analyze_and_persist, create_project, ingest_normalized


def request() -> IngestionRequest:
    return IngestionRequest(
        external_id="run-1",
        repository="owner/repo",
        commit_sha="abcdef0",
        expected_inputs=2,
        observations=[
            Observation(test_identity="ledger::balanced", outcome=Outcome.failed, message="ledger unbalanced after duplicate committed", details={"data_integrity_violation": True}),
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
    analysis = analyze_and_persist(session, failures[0])
    assert analysis.category.value == "product_defect"
    assert session.get(Analysis, analysis.id) is not None


def test_incomplete_run_is_explicit(session) -> None:
    project = create_project(session, "partial-project", "Partial")
    payload = request().model_copy(update={"external_id": "run-2", "expected_inputs": 4})
    run = ingest_normalized(session, project, payload)
    assert run.completeness == "partial"
    assert run.status.value == "partial"
