from __future__ import annotations

from contextlib import contextmanager

import pytest
from failurelens.api import overview
from failurelens.auth import DEMO_PRINCIPAL, Principal
from failurelens.impact import create_impact_recommendation, create_mapping_snapshot
from failurelens.infrastructure import build_infrastructure_correlation
from failurelens.models import (
    Analysis,
    Category,
    Failure,
    FailureCluster,
    InfrastructureEvent,
    Ingestion,
    IngestionState,
    ProjectMembership,
    ProjectRole,
    RunInput,
    User,
    utcnow,
)
from failurelens.models import (
    TestExecution as Execution,
)
from failurelens.performance import (
    create_run_performance_comparisons,
    ensure_default_performance_policy,
)
from failurelens.schemas import (
    ImpactMappingSnapshotCreate,
    ImpactRecommendationCreate,
    IngestionRequest,
)
from failurelens.service import create_project, ingest_normalized
from fastapi import HTTPException
from sqlalchemy import event, select


@contextmanager
def _selects(session):
    statements = []

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(session.bind, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(session.bind, "before_cursor_execute", record)


def _seed_project(session, slug):
    project = create_project(session, slug, slug)
    run = ingest_normalized(
        session,
        project,
        IngestionRequest.model_validate(
            {
                "external_id": slug,
                "observations": [
                    {
                        "test_identity": "overview::failure",
                        "outcome": "failed",
                        "message": "Expected 1, received 2",
                        "duration_ms": 20,
                    }
                ],
            }
        ),
    )
    failure = session.scalar(select(Failure).where(Failure.run_id == run.id))
    execution = session.get(Execution, failure.execution_id)
    for number, state in enumerate(IngestionState):
        session.add(
            Ingestion(
                project_id=project.id,
                external_id=f"{slug}-{state.value}",
                original_name="fixture.json",
                source_digest=f"{number:064x}",
                source_size_bytes=1,
                storage_path=f"test/{slug}/{state.value}",
                state=state,
            )
        )
    session.add(
        FailureCluster(
            project_id=project.id,
            cluster_key="inactive",
            algorithm_version="test",
            feature_version="test",
            status="superseded",
        )
    )
    session.add(
        InfrastructureEvent(
            project_id=project.id,
            producer="test",
            producer_event_id="fixture",
            event_kind="service_outage",
            started_at=utcnow(),
            recorded_at=utcnow(),
            source_digest="0" * 64,
        )
    )
    session.flush()
    build_infrastructure_correlation(
        session,
        selected_execution=execution,
        selected_run=run,
        cutoff=run.created_at,
        exclude_run_id=run.id,
        persist=True,
    )
    policy = ensure_default_performance_policy(session, project)
    create_run_performance_comparisons(session, run, policy)
    changed_input = RunInput(
        project_id=project.id,
        run_id=run.id,
        input_id="changes",
        kind="changed-files",
        status="accepted",
        metadata_json={"files": [], "complete": False},
    )
    session.add(changed_input)
    session.commit()
    mapping = create_mapping_snapshot(
        session,
        project,
        ImpactMappingSnapshotCreate.model_validate(
            {
                "version": "overview-v1",
                "tests": [
                    {"test_key": "overview", "test_identity": "overview::failure"}
                ],
            }
        ),
    )
    create_impact_recommendation(
        session,
        project,
        ImpactRecommendationCreate(
            run_id=run.id,
            mapping_snapshot_id=mapping.id,
            changed_input_id=changed_input.id,
        ),
    )
    # Include every revision, including a previously valid result: overview has
    # always counted persisted analyses, rather than only the latest per failure.
    validations = [
        (
            Category.product_defect,
            "v1",
            {"status": "passed", "published_category": "product_defect"},
        ),
        (
            Category.known_flake,
            "v1",
            {"status": "degraded", "published_category": "known_flake"},
        ),
        (
            Category.test_defect,
            None,
            {"status": "passed", "published_category": "test_defect"},
        ),
        (
            Category.infrastructure_failure,
            "v1",
            {"status": "passed", "published_category": "product_defect"},
        ),
        (
            Category.known_flake,
            "v1",
            {"status": "failed", "published_category": "known_flake"},
        ),
    ]
    for revision, (category, version, validation) in enumerate(validations, 1):
        session.add(
            Analysis(
                failure_id=failure.id,
                revision=revision,
                category=category,
                confidence_explanation="fixture",
                evidence_completeness="partial",
                summary="fixture",
                validation_version=version,
                validation_results=validation,
            )
        )
    session.commit()
    return project


def _principal(session, projects=()):
    user = User(
        username="overview-reader",
        display_name="Overview reader",
        password_hash="test-only",
    )
    session.add(user)
    session.flush()
    for project in projects:
        session.add(
            ProjectMembership(
                project_id=project.id, user_id=user.id, role=ProjectRole.viewer
            )
        )
    session.commit()
    return Principal(
        kind="user", actor_id=user.id, user_id=user.id, display_name=user.display_name
    )


def _expected(project_count):
    return {
        "projects": project_count,
        "runs": project_count,
        "ingestions": len(IngestionState) * project_count,
        "active_ingestions": 2 * project_count,
        "failures": project_count,
        "clusters": project_count,
        "impact_recommendations": project_count,
        "performance_comparisons": project_count,
        "infrastructure_events": project_count,
        "infrastructure_correlations": project_count,
        "analyses": 5 * project_count,
        "categories": {
            "product_defect": project_count,
            "test_defect": 0,
            "infrastructure_failure": 0,
            "known_flake": project_count,
            "insufficient_evidence": 3 * project_count,
        },
    }


@pytest.mark.parametrize(
    "scope,visible,query_count",
    [
        ("admin", 3, 2),
        ("member", 1, 3),
        ("member", 2, 3),
        ("member", 0, 1),
    ],
)
def test_overview_consolidates_counts_without_changing_scope_or_categories(
    session,
    scope,
    visible,
    query_count,
):
    projects = [_seed_project(session, f"overview-{number}") for number in range(3)]
    principal = (
        DEMO_PRINCIPAL if scope == "admin" else _principal(session, projects[:visible])
    )
    session.expunge_all()
    with _selects(session) as statements:
        result = overview(principal=principal, session=session)
    assert result == _expected(visible)
    assert len(statements) == query_count
    count_statements = [sql for sql in statements if "count(" in sql.lower()]
    assert len(count_statements) == (1 if visible else 0)
    if visible:
        # No multi-table join may inflate counts when one table has many rows.
        assert " JOIN " not in count_statements[0].upper()
        assert count_statements[0].lower().count("count(") == (
            10 if scope == "admin" else 9
        )
        analysis_sql = next(sql for sql in statements if "analyses.category" in sql)
        projected = analysis_sql.split("FROM", 1)[0]
        assert "analyses.validation_version" in projected
        assert "analyses.validation_results" in projected
        assert "analyses.summary" not in projected
        assert "analyses.claims" not in projected
        assert "analyses.provenance" not in projected


def test_empty_administrator_overview_keeps_every_zero_field(session):
    with _selects(session) as statements:
        assert overview(principal=DEMO_PRINCIPAL, session=session) == _expected(0)
    assert len(statements) == 2


def test_overview_rechecks_membership_and_current_rows_on_every_request(session):
    project = _seed_project(session, "overview-current")
    principal = _principal(session, [project])
    assert overview(principal=principal, session=session) == _expected(1)
    active = session.scalar(
        select(Ingestion).where(Ingestion.state == IngestionState.queued)
    )
    active.state = IngestionState.succeeded
    session.commit()
    assert overview(principal=principal, session=session)["active_ingestions"] == 1
    membership = session.scalar(
        select(ProjectMembership).where(ProjectMembership.user_id == principal.user_id)
    )
    session.delete(membership)
    session.commit()
    with _selects(session) as statements:
        assert overview(principal=principal, session=session) == _expected(0)
    assert len(statements) == 1


def test_overview_still_rejects_ingestion_token_principal_before_querying(session):
    principal = Principal(
        kind="ingestion_token", actor_id="token", display_name="Token"
    )
    with _selects(session) as statements, pytest.raises(HTTPException) as error:
        overview(principal=principal, session=session)
    assert error.value.status_code == 403
    assert statements == []
