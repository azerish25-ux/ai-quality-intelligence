from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Failure, Project
from .schemas import IngestionRequest, TestObservation
from .service import analyze_and_persist, create_project, ingest_normalized


def seed_demo(session: Session) -> dict[str, str]:
    project = create_project(session, "ledgerguard-demo", "LedgerGuard synthetic demonstration")
    request = IngestionRequest(
        external_id="demo-run-001",
        repository="azerish25-ux/transaction-reliability-lab",
        commit_sha="0000000",
        branch="demo",
        framework="normalized",
        expected_inputs=3,
        source_metadata={"synthetic": True, "notice": "No claim of actual LedgerGuard execution"},
        observations=[
            TestObservation(test_identity="payments::duplicate-idempotency", outcome="failed", message="balance invariant violated: duplicate committed transfer produced double charge", exception_type="LedgerInvariantError", details={"data_integrity_violation": True}),
            TestObservation(test_identity="ui::checkout-selector", outcome="failed", message="Timeout waiting for selector [data-testid=pay-now]", exception_type="TimeoutError", details={"trace_missing": True}),
            TestObservation(test_identity="api::health", outcome="passed", duration_ms=42),
        ],
    )
    run = ingest_normalized(session, project, request)
    failures = session.scalars(select(Failure).where(Failure.run_id == run.id)).all()
    for failure in failures:
        if not failure.analyses:
            analyze_and_persist(session, failure)
    return {"project_id": project.id, "run_id": run.id}
