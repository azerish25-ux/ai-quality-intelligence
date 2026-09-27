from __future__ import annotations

import json
from collections import Counter
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .clustering import review_cluster
from .db import get_session, initialize_database
from .demo import seed_demo
from .evidence_validation import persisted_analysis_is_publication_validated
from .history import build_test_history
from .models import (
    Analysis,
    Category,
    ClusterMembership,
    ClusterMembershipDecision,
    ClusterRevision,
    Evidence,
    Failure,
    FailureCluster,
    Ingestion,
    IngestionState,
    Project,
    Run,
    RunInput,
    TestExecution,
)
from .schemas import (
    AnalysisResult,
    ArtifactDerivativeSummary,
    ClusterDecisionRead,
    ClusterDetail,
    ClusterMemberRead,
    ClusterReviewCreate,
    ClusterRevisionRead,
    ClusterSummary,
    EvidenceRead,
    IngestionRead,
    IngestionRequest,
    ProjectCreate,
    ProjectRead,
    ReviewCreate,
    RunInputRead,
    RunMetadata,
    RunRead,
    TestHistoryRead,
)
from .service import (
    add_review,
    analysis_to_schema,
    analyze_and_persist,
    cancel_ingestion,
    create_project,
    enqueue_artifact_ingestion,
    ingest_normalized,
    retry_ingestion,
)
from .storage import StorageError, store_stream


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="FailureLens API",
    version="0.5.0",
    description="Evidence-grounded automated test failure triage",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8080"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def authorized(x_failurelens_token: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if settings.demo_mode and settings.ingestion_token is None:
        return
    if not settings.ingestion_token or x_failurelens_token != settings.ingestion_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid ingestion token")


def _cluster_summary(cluster: FailureCluster) -> ClusterSummary:
    representative = cluster.representative_failure
    return ClusterSummary(
        id=cluster.id,
        project_id=cluster.project_id,
        cluster_key=cluster.cluster_key,
        algorithm_version=cluster.algorithm_version,
        feature_version=cluster.feature_version,
        current_revision=cluster.current_revision,
        representative_failure_id=cluster.representative_failure_id,
        representative_test_identity=(
            representative.execution.test_identity if representative is not None else None
        ),
        member_count=cluster.member_count,
        uncertainty=cluster.uncertainty,
        status=cluster.status,
        superseded_by_cluster_id=cluster.superseded_by_cluster_id,
        created_at=cluster.created_at,
        updated_at=cluster.updated_at,
    )


def _cluster_revision_read(
    session: Session, revision: ClusterRevision
) -> ClusterRevisionRead:
    memberships = list(
        session.scalars(
            select(ClusterMembership)
            .where(ClusterMembership.revision_id == revision.id)
            .options(
                selectinload(ClusterMembership.failure).selectinload(
                    Failure.execution
                )
            )
            .order_by(
                ClusterMembership.role.desc(),
                ClusterMembership.similarity_score.desc(),
                ClusterMembership.failure_id,
            )
        ).all()
    )
    return ClusterRevisionRead(
        id=revision.id,
        cluster_id=revision.cluster_id,
        revision=revision.revision,
        reason=revision.reason,
        algorithm_version=revision.algorithm_version,
        feature_version=revision.feature_version,
        representative_failure_id=revision.representative_failure_id,
        member_count=revision.member_count,
        score_summary=revision.score_summary,
        uncertainty_flags=revision.uncertainty_flags,
        created_at=revision.created_at,
        memberships=[
            ClusterMemberRead(
                failure_id=item.failure_id,
                run_id=item.failure.run_id,
                test_identity=item.failure.execution.test_identity,
                message=item.failure.message,
                exception_type=item.failure.exception_type,
                role=item.role,
                similarity_score=item.similarity_score,
                score_components={
                    str(key): float(value)
                    for key, value in item.score_components.items()
                    if isinstance(value, (int, float))
                },
                matching_signals=item.matching_signals,
                conflicting_signals=item.conflicting_signals,
                candidate_reasons=item.candidate_reasons,
                assignment_kind=item.assignment_kind,
            )
            for item in memberships
        ],
    )


def _cluster_detail(session: Session, cluster: FailureCluster) -> ClusterDetail:
    revision = session.scalar(
        select(ClusterRevision).where(
            ClusterRevision.cluster_id == cluster.id,
            ClusterRevision.revision == cluster.current_revision,
        )
    )
    decisions = list(
        session.scalars(
            select(ClusterMembershipDecision)
            .where(
                or_(
                    ClusterMembershipDecision.cluster_id == cluster.id,
                    ClusterMembershipDecision.target_cluster_id == cluster.id,
                )
            )
            .order_by(ClusterMembershipDecision.created_at.desc())
        ).all()
    )
    summary = _cluster_summary(cluster)
    return ClusterDetail(
        **summary.model_dump(),
        current=(
            _cluster_revision_read(session, revision) if revision is not None else None
        ),
        decisions=[
            ClusterDecisionRead(
                id=item.id,
                cluster_id=item.cluster_id,
                actor=item.actor,
                decision=item.decision,
                reason=item.reason,
                failure_ids=item.failure_ids,
                target_cluster_id=item.target_cluster_id,
                revision_before=item.revision_before,
                revision_after=item.revision_after,
                created_at=item.created_at,
            )
            for item in decisions
        ],
    )


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "live"}


@app.get("/health/ready")
def ready(session: Session = Depends(get_session)) -> dict[str, str]:
    session.execute(select(1))
    return {"status": "ready"}


@app.get("/api/v1/overview")
def overview(session: Session = Depends(get_session)) -> dict:
    analyses = list(session.scalars(select(Analysis)).all())
    publication_categories = Counter(
        (
            item.category.value
            if persisted_analysis_is_publication_validated(item)
            else Category.insufficient_evidence.value
        )
        for item in analyses
    )
    return {
        "projects": session.scalar(select(func.count(Project.id))) or 0,
        "runs": session.scalar(select(func.count(Run.id))) or 0,
        "ingestions": session.scalar(select(func.count(Ingestion.id))) or 0,
        "active_ingestions": session.scalar(
            select(func.count(Ingestion.id)).where(
                Ingestion.state.in_([IngestionState.queued, IngestionState.running])
            )
        )
        or 0,
        "failures": session.scalar(select(func.count(Failure.id))) or 0,
        "clusters": session.scalar(
            select(func.count(FailureCluster.id)).where(
                FailureCluster.status == "active"
            )
        )
        or 0,
        "analyses": len(analyses),
        "categories": {
            category.value: publication_categories.get(category.value, 0)
            for category in Category
        },
    }


@app.post("/api/v1/demo/seed", dependencies=[Depends(authorized)])
def demo_seed(session: Session = Depends(get_session)) -> dict:
    settings = get_settings()
    if not settings.demo_mode:
        raise HTTPException(403, "demo mode is disabled")
    return seed_demo(session)


@app.get("/api/v1/evaluations/latest")
def evaluation_latest() -> dict:
    path = get_settings().evaluation_metrics_path
    if not path.exists():
        return {
            "status": "not_loaded",
            "message": "No executed evaluation metrics are available in this runtime.",
        }
    try:
        return {"status": "available", "metrics": json.loads(path.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(503, f"evaluation metrics unavailable: {exc}") from exc


@app.post(
    "/api/v1/projects",
    response_model=ProjectRead,
    status_code=201,
    dependencies=[Depends(authorized)],
)
def projects_create(request: ProjectCreate, session: Session = Depends(get_session)) -> Project:
    return create_project(session, request.slug, request.name)


@app.get("/api/v1/projects", response_model=list[ProjectRead])
def projects_list(session: Session = Depends(get_session)) -> list[Project]:
    return list(session.scalars(select(Project).order_by(Project.created_at)).all())


@app.post(
    "/api/v1/projects/{project_id}/ingestions",
    status_code=202,
    dependencies=[Depends(authorized)],
)
async def ingestions_create(
    project_id: str,
    request: Request,
    external_id: str | None = Query(default=None, min_length=1, max_length=240),
    attempt: int = Query(default=1, ge=1),
    filename: str | None = Query(default=None, min_length=1, max_length=1024),
    repository: str | None = Query(default=None, max_length=240),
    commit_sha: str | None = Query(default=None, pattern=r"^[0-9a-fA-F]{7,64}$"),
    base_sha: str | None = Query(default=None, pattern=r"^[0-9a-fA-F]{7,64}$"),
    branch: str | None = Query(default=None, max_length=240),
    run_scope: str = Query(
        default="unknown", pattern=r"^(full_suite|impact_selected|unknown)$"
    ),
    environment: str | None = Query(default=None, max_length=160),
    timezone: str | None = Query(default=None, max_length=80),
    worker_count: int | None = Query(default=None, ge=1, le=100_000),
    shard_count: int | None = Query(default=None, ge=1, le=100_000),
    expected_inputs: int | None = Query(default=None, ge=0),
    source_format: str = Query(default="auto", min_length=1, max_length=80),
    session: Session = Depends(get_session),
) -> RunRead | IngestionRead:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")

    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type == "application/json" and filename is None:
        try:
            payload = await request.json()
            normalized = IngestionRequest.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        return RunRead.model_validate(ingest_normalized(session, project, normalized))

    if external_id is None or filename is None:
        raise HTTPException(
            422,
            "raw artifact ingestion requires external_id and filename query parameters",
        )
    try:
        metadata = RunMetadata(
            external_id=external_id,
            attempt=attempt,
            repository=repository,
            commit_sha=commit_sha,
            base_sha=base_sha,
            branch=branch,
            framework=source_format,
            run_scope=run_scope,
            environment=environment,
            timezone=timezone,
            worker_count=worker_count,
            shard_count=shard_count,
            expected_inputs=expected_inputs,
            source_metadata={"transport": "raw-http"},
        )
    except ValidationError as exc:
        raise HTTPException(422, detail=exc.errors()) from exc

    settings = get_settings()
    declared_length = request.headers.get("content-length")
    max_bytes = settings.max_bundle_bytes if filename.lower().endswith(".zip") else settings.max_file_bytes
    if declared_length:
        try:
            if int(declared_length) > max_bytes:
                raise HTTPException(413, "upload exceeds configured size limit")
        except ValueError as exc:
            raise HTTPException(400, "invalid content-length header") from exc
    try:
        stored = await store_stream(
            request.stream(),
            root=settings.artifact_root,
            project_id=project.id,
            filename=filename,
            media_type=content_type or "application/octet-stream",
            max_bytes=max_bytes,
        )
    except StorageError as exc:
        http_status = 413 if exc.code == "limit_exceeded" else 400
        raise HTTPException(http_status, detail={"code": exc.code, "message": str(exc)}) from exc
    try:
        ingestion = enqueue_artifact_ingestion(
            session,
            project,
            metadata,
            stored,
            source_format=source_format,
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return IngestionRead.model_validate(ingestion)


@app.get(
    "/api/v1/projects/{project_id}/ingestions",
    response_model=list[IngestionRead],
)
def ingestions_list(
    project_id: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    session: Session = Depends(get_session),
) -> list[Ingestion]:
    return list(
        session.scalars(
            select(Ingestion)
            .where(Ingestion.project_id == project_id)
            .order_by(Ingestion.created_at.desc())
            .limit(limit)
        ).all()
    )


@app.get("/api/v1/ingestions/{ingestion_id}", response_model=IngestionRead)
def ingestions_get(ingestion_id: str, session: Session = Depends(get_session)) -> Ingestion:
    ingestion = session.get(Ingestion, ingestion_id)
    if not ingestion:
        raise HTTPException(404, "ingestion not found")
    return ingestion


@app.post(
    "/api/v1/ingestions/{ingestion_id}/cancel",
    response_model=IngestionRead,
    dependencies=[Depends(authorized)],
)
def ingestions_cancel(ingestion_id: str, session: Session = Depends(get_session)) -> Ingestion:
    ingestion = session.get(Ingestion, ingestion_id)
    if not ingestion:
        raise HTTPException(404, "ingestion not found")
    return cancel_ingestion(session, ingestion)


@app.post(
    "/api/v1/ingestions/{ingestion_id}/retry",
    response_model=IngestionRead,
    dependencies=[Depends(authorized)],
)
def ingestions_retry(ingestion_id: str, session: Session = Depends(get_session)) -> Ingestion:
    ingestion = session.get(Ingestion, ingestion_id)
    if not ingestion:
        raise HTTPException(404, "ingestion not found")
    try:
        return retry_ingestion(session, ingestion)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/runs", response_model=list[RunRead])
def runs_list(
    project_id: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    session: Session = Depends(get_session),
) -> list[Run]:
    return list(
        session.scalars(
            select(Run)
            .where(Run.project_id == project_id)
            .order_by(Run.created_at.desc())
            .limit(limit)
        ).all()
    )


@app.get("/api/v1/runs/{run_id}")
def runs_get(run_id: str, session: Session = Depends(get_session)) -> dict:
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    counts = dict(
        session.execute(
            select(Failure.exception_type, func.count(Failure.id))
            .where(Failure.run_id == run_id)
            .group_by(Failure.exception_type)
        ).all()
    )
    return {
        "run": RunRead.model_validate(run),
        "failure_types": counts,
        "failure_count": sum(counts.values()),
    }


@app.get("/api/v1/runs/{run_id}/inputs", response_model=list[RunInputRead])
def run_inputs_list(run_id: str, session: Session = Depends(get_session)) -> list[RunInput]:
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return list(
        session.scalars(
            select(RunInput)
            .where(RunInput.run_id == run_id)
            .order_by(RunInput.required.desc(), RunInput.input_id.asc())
        ).all()
    )


@app.get(
    "/api/v1/projects/{project_id}/clusters",
    response_model=list[ClusterSummary],
)
def clusters_list(
    project_id: str,
    include_superseded: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    session: Session = Depends(get_session),
) -> list[ClusterSummary]:
    if session.get(Project, project_id) is None:
        raise HTTPException(404, "project not found")
    query = (
        select(FailureCluster)
        .where(FailureCluster.project_id == project_id)
        .options(
            selectinload(FailureCluster.representative_failure).selectinload(
                Failure.execution
            )
        )
        .order_by(
            FailureCluster.status,
            FailureCluster.member_count.desc(),
            FailureCluster.updated_at.desc(),
            FailureCluster.cluster_key,
        )
        .offset(offset)
        .limit(limit)
    )
    if not include_superseded:
        query = query.where(FailureCluster.status == "active")
    return [_cluster_summary(cluster) for cluster in session.scalars(query).all()]


@app.get(
    "/api/v1/runs/{run_id}/clusters",
    response_model=list[ClusterSummary],
)
def run_clusters_list(
    run_id: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    session: Session = Depends(get_session),
) -> list[ClusterSummary]:
    if session.get(Run, run_id) is None:
        raise HTTPException(404, "run not found")
    clusters = list(
        session.scalars(
            select(FailureCluster)
            .join(
                ClusterRevision,
                ClusterRevision.cluster_id == FailureCluster.id,
            )
            .join(
                ClusterMembership,
                ClusterMembership.revision_id == ClusterRevision.id,
            )
            .join(Failure, Failure.id == ClusterMembership.failure_id)
            .where(
                Failure.run_id == run_id,
                FailureCluster.status == "active",
                ClusterRevision.revision == FailureCluster.current_revision,
            )
            .options(
                selectinload(FailureCluster.representative_failure).selectinload(
                    Failure.execution
                )
            )
            .order_by(
                FailureCluster.member_count.desc(),
                FailureCluster.updated_at.desc(),
                FailureCluster.cluster_key,
            )
            .offset(offset)
            .limit(limit)
            .distinct()
        ).all()
    )
    return [_cluster_summary(cluster) for cluster in clusters]


@app.get("/api/v1/clusters/{cluster_id}", response_model=ClusterDetail)
def clusters_get(
    cluster_id: str,
    session: Session = Depends(get_session),
) -> ClusterDetail:
    cluster = session.scalar(
        select(FailureCluster)
        .where(FailureCluster.id == cluster_id)
        .options(
            selectinload(FailureCluster.representative_failure).selectinload(
                Failure.execution
            )
        )
    )
    if cluster is None:
        raise HTTPException(404, "cluster not found")
    return _cluster_detail(session, cluster)


@app.get(
    "/api/v1/clusters/{cluster_id}/revisions",
    response_model=list[ClusterRevisionRead],
)
def cluster_revisions_list(
    cluster_id: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    session: Session = Depends(get_session),
) -> list[ClusterRevisionRead]:
    if session.get(FailureCluster, cluster_id) is None:
        raise HTTPException(404, "cluster not found")
    revisions = list(
        session.scalars(
            select(ClusterRevision)
            .where(ClusterRevision.cluster_id == cluster_id)
            .order_by(ClusterRevision.revision.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return [_cluster_revision_read(session, revision) for revision in revisions]


@app.post(
    "/api/v1/clusters/{cluster_id}/reviews",
    response_model=ClusterDetail,
    status_code=201,
    dependencies=[Depends(authorized)],
)
def cluster_reviews_create(
    cluster_id: str,
    request: ClusterReviewCreate,
    session: Session = Depends(get_session),
) -> ClusterDetail:
    cluster = session.get(FailureCluster, cluster_id)
    if cluster is None:
        raise HTTPException(404, "cluster not found")
    try:
        review_cluster(
            session,
            cluster,
            actor=request.actor,
            decision=request.decision,
            reason=request.reason,
            expected_revision=request.expected_revision,
            failure_ids=request.failure_ids,
            target_cluster_id=request.target_cluster_id,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    refreshed = session.scalar(
        select(FailureCluster)
        .where(FailureCluster.id == cluster_id)
        .options(
            selectinload(FailureCluster.representative_failure).selectinload(
                Failure.execution
            )
        )
    )
    if refreshed is None:
        raise HTTPException(404, "cluster not found after review")
    return _cluster_detail(session, refreshed)


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@app.get("/api/v1/tests/{execution_id}/history", response_model=TestHistoryRead)
def test_history_get(
    execution_id: str,
    after: datetime | None = None,
    before: datetime | None = None,
    browser: str | None = Query(default=None, max_length=80),
    branch: str | None = Query(default=None, max_length=240),
    environment: str | None = Query(default=None, max_length=160),
    run_scope: str | None = Query(
        default=None, pattern=r"^(full_suite|impact_selected|unknown)$"
    ),
    timezone_name: str | None = Query(default=None, alias="timezone", max_length=80),
    worker_count: int | None = Query(default=None, ge=1, le=100_000),
    shard_count: int | None = Query(default=None, ge=1, le=100_000),
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    session: Session = Depends(get_session),
) -> TestHistoryRead:
    execution = session.scalar(
        select(TestExecution)
        .where(TestExecution.id == execution_id)
        .options(
            selectinload(TestExecution.run),
            selectinload(TestExecution.failure),
        )
    )
    if execution is None:
        raise HTTPException(404, "test execution not found")

    reference_cutoff = _utc_datetime(execution.run.started_at or execution.run.created_at)
    requested_cutoff = _utc_datetime(before) if before is not None else reference_cutoff
    effective_cutoff = min(reference_cutoff, requested_cutoff)
    if after is not None and _utc_datetime(after) >= effective_cutoff:
        raise HTTPException(422, "after must be earlier than the prior-only cutoff")

    try:
        report = build_test_history(
            session,
            selected_execution=execution,
            selected_run=execution.run,
            cutoff=effective_cutoff,
            after=after,
            browser=browser,
            match_browser=browser is not None,
            branch=branch,
            match_branch=branch is not None,
            environment=environment,
            match_environment=environment is not None,
            run_scope=run_scope,
            worker_count=worker_count,
            match_worker_count=worker_count is not None,
            shard_count=shard_count,
            match_shard_count=shard_count is not None,
            timezone_name=timezone_name or execution.run.timezone or "UTC",
            exclude_run_id=execution.run_id,
            strict_fingerprint=(
                execution.failure.strict_fingerprint
                if execution.failure is not None
                else None
            ),
            observation_limit=limit,
            observation_offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return TestHistoryRead.model_validate(report)


@app.get("/api/v1/runs/{run_id}/failures")
def failures_list(run_id: str, session: Session = Depends(get_session)) -> list[dict]:
    failures = session.scalars(
        select(Failure)
        .where(Failure.run_id == run_id)
        .options(selectinload(Failure.analyses), selectinload(Failure.execution))
        .order_by(Failure.created_at)
    ).all()
    result: list[dict] = []
    for failure in failures:
        latest = max(failure.analyses, key=lambda item: item.revision, default=None)
        result.append(
            {
                "id": failure.id,
                "execution_id": failure.execution_id,
                "test_identity": failure.execution.test_identity,
                "message": failure.message,
                "fingerprint": failure.strict_fingerprint,
                "latest_analysis": analysis_to_schema(latest).model_dump(mode="json") if latest else None,
            }
        )
    return result


@app.post(
    "/api/v1/failures/{failure_id}/analyses",
    response_model=AnalysisResult,
    status_code=201,
    dependencies=[Depends(authorized)],
)
def analyses_create(failure_id: str, session: Session = Depends(get_session)) -> AnalysisResult:
    failure = session.scalar(
        select(Failure)
        .where(Failure.id == failure_id)
        .options(selectinload(Failure.execution), selectinload(Failure.run))
    )
    if not failure:
        raise HTTPException(404, "failure not found")
    return analysis_to_schema(analyze_and_persist(session, failure))


@app.get("/api/v1/analyses/{analysis_id}", response_model=AnalysisResult)
def analyses_get(analysis_id: str, session: Session = Depends(get_session)) -> AnalysisResult:
    row = session.scalar(
        select(Analysis)
        .where(Analysis.id == analysis_id)
        .options(selectinload(Analysis.failure))
    )
    if not row:
        raise HTTPException(404, "analysis not found")
    return analysis_to_schema(row)


@app.post(
    "/api/v1/analyses/{analysis_id}/reviews",
    status_code=201,
    dependencies=[Depends(authorized)],
)
def reviews_create(
    analysis_id: str,
    request: ReviewCreate,
    session: Session = Depends(get_session),
) -> dict:
    row = session.get(Analysis, analysis_id)
    if not row:
        raise HTTPException(404, "analysis not found")
    try:
        event = add_review(session, row, request)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "id": event.id,
        "version": event.version,
        "decision": event.decision,
        "created_at": event.created_at,
    }


@app.get("/api/v1/evidence/{evidence_id}", response_model=EvidenceRead)
def evidence_get(
    evidence_id: str,
    session: Session = Depends(get_session),
) -> EvidenceRead:
    evidence = session.scalar(
        select(Evidence)
        .where(Evidence.id == evidence_id)
        .options(selectinload(Evidence.derivative))
    )
    if not evidence:
        raise HTTPException(404, "evidence not found")
    derivative = evidence.derivative
    if (
        derivative is None
        or not derivative.approved
        or derivative.restricted
        or derivative.retention_state != "active"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="evidence derivative is not approved for safe inspection",
        )
    return EvidenceRead(
        id=evidence.id,
        project_id=evidence.project_id,
        run_id=evidence.run_id,
        run_input_id=evidence.run_input_id,
        execution_id=evidence.execution_id,
        derivative_id=evidence.derivative_id,
        kind=evidence.kind,
        provenance_kind=evidence.provenance_kind,
        locator_version=evidence.locator_version,
        locator=evidence.locator,
        excerpt=evidence.excerpt,
        observation=evidence.observation,
        content_digest=evidence.content_digest,
        parser_version=evidence.parser_version,
        extractor_version=evidence.extractor_version,
        redaction_version=evidence.redaction_version,
        warnings=evidence.warnings,
        derivative=ArtifactDerivativeSummary(
            id=derivative.id,
            kind=derivative.kind,
            digest=derivative.digest,
            media_type=derivative.media_type,
            size_bytes=derivative.size_bytes,
            redaction_version=derivative.redaction_version,
            approved=derivative.approved,
            restricted=derivative.restricted,
            approval_state=derivative.approval_state,
            retention_state=derivative.retention_state,
        ),
    )
