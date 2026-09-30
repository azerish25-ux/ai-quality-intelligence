from __future__ import annotations

import json
from collections import Counter
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .auth import (
    Principal,
    as_utc,
    create_auth_session,
    create_project_ingestion_token,
    create_user,
    current_principal,
    ensure_bootstrap_administrator,
    normalize_username,
    record_audit_event,
    require_project_role,
    require_system_administrator,
    require_user,
    verify_password,
    visible_project_ids,
)
from .config import get_settings
from .clustering import review_cluster
from .db import get_session, initialize_database
from .demo import seed_demo
from .evidence_validation import persisted_analysis_is_publication_validated
from .history import build_test_history
from .infrastructure import (
    MAX_CORRELATION_RUNS,
    build_infrastructure_correlation,
    create_infrastructure_event,
    get_infrastructure_correlation,
    infrastructure_correlation_to_schema,
    infrastructure_event_to_schema,
    list_infrastructure_events,
)
from .impact import (
    apply_impact_override,
    create_impact_recommendation,
    create_mapping_snapshot,
    get_impact_recommendation,
    impact_recommendation_to_schema,
    list_mapping_snapshots,
    list_project_recommendations,
    mapping_snapshot_to_schema,
)
from .performance import (
    build_performance_baseline,
    create_performance_policy,
    create_run_performance_comparisons,
    ensure_default_performance_policy,
    get_performance_baseline,
    get_performance_comparison,
    list_performance_policies,
    list_run_performance_comparisons,
    list_run_performance_observations,
    performance_baseline_to_schema,
    performance_comparison_to_schema,
    performance_observation_to_schema,
    performance_policy_to_schema,
)
from .models import (
    Analysis,
    AuditEvent,
    AuthSession,
    Category,
    ClusterMembership,
    ClusterMembershipDecision,
    ClusterRevision,
    Evidence,
    Failure,
    FailureCluster,
    Ingestion,
    IngestionState,
    IngestionToken,
    ImpactRecommendation,
    InfrastructureCorrelationSnapshot,
    InfrastructureEvent,
    PerformanceComparison,
    PerformanceObservation,
    PerformancePolicy,
    Project,
    ProjectMembership,
    ProjectRole,
    ReviewEvent,
    Run,
    RunInput,
    TestExecution,
    User,
    utcnow,
)
from .schemas import (
    AnalysisResult,
    ArtifactDerivativeSummary,
    AuditEventRead,
    AuthMembershipRead,
    ClusterDecisionRead,
    ClusterDetail,
    ClusterMemberRead,
    ClusterReviewCreate,
    ClusterRevisionRead,
    ClusterSummary,
    EvidenceRead,
    IngestionRead,
    IngestionRequest,
    IngestionTokenCreate,
    IngestionTokenCreated,
    IngestionTokenRead,
    ImpactMappingSnapshotCreate,
    ImpactMappingSnapshotRead,
    ImpactOverrideCreate,
    ImpactRecommendationCreate,
    ImpactRecommendationRead,
    InfrastructureCorrelationCreate,
    InfrastructureCorrelationRead,
    InfrastructureEventCreate,
    InfrastructureEventRead,
    PerformanceBaselineCreate,
    PerformanceBaselineRead,
    PerformanceComparisonCreate,
    PerformanceComparisonRead,
    PerformanceObservationRead,
    PerformancePolicyCreate,
    PerformancePolicyRead,
    PrincipalRead,
    ProjectCreate,
    ProjectMembershipCreate,
    ProjectMembershipRead,
    ProjectMembershipUpdate,
    ProjectRead,
    LoginRequest,
    LoginResponse,
    ReviewCreate,
    ReviewEventRead,
    ReviewQueueItem,
    RunInputRead,
    RunMetadata,
    RunRead,
    RunDetailRead,
    TestHistoryRead,
    UserCreate,
    UserRead,
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
from .operations_api import router as operations_router
from .retention import lock_project
from .telemetry import configure_telemetry, shutdown_telemetry, metrics_snapshot, observe_http_status, stage, SpanKind
from .governance import review_queue_page


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    settings = get_settings()
    settings.validate_security()
    configure_telemetry()
    try:
        if not settings.demo_mode:
            from .db import SessionLocal

            with SessionLocal() as session:
                ensure_bootstrap_administrator(session, settings)
        yield
    finally:
        shutdown_telemetry()


app = FastAPI(
    title="FailureLens API",
    version="0.9.0",
    description="Evidence-grounded automated test failure triage",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8080"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(operations_router)


@app.exception_handler(RequestValidationError)
async def safe_request_validation(_: Request, exc: RequestValidationError):
    # Pydantic's input field can otherwise echo a password or recovery token.
    return JSONResponse(status_code=422, content={"detail": [
        {"type": error["type"], "loc": list(error["loc"]), "msg": error["msg"]}
        for error in exc.errors()
    ]})


@app.middleware("http")
async def private_api_responses(request: Request, call_next):
    with stage("http", parent=request.headers.get("traceparent"), kind=SpanKind.SERVER) as span:
        method = request.method if request.method in {"GET", "POST", "PATCH", "DELETE", "PUT", "HEAD", "OPTIONS"} else "OTHER"
        span.set_attribute("http.request.method", method)
        status_code = None
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            # Starlette's outer error middleware turns this into a 500 response.
            status_code = 500
            raise
        finally:
            # The registered route template contains no request IDs/query values.
            route = getattr(request.scope.get("route"), "path", "unmatched")
            span.set_attribute("http.route", str(route)[:160])
            if status_code is not None:
                span.set_attribute("http.response.status_code", status_code)
                observe_http_status(status_code)
    if request.url.path.startswith("/api/"):
        # Responses can contain approved evidence and one-time credentials. They
        # must not survive logout or expiry in browser/shared HTTP caches.
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _require_project(
    session: Session,
    principal: Principal,
    project_id: str,
    minimum_role: ProjectRole = ProjectRole.viewer,
    *,
    ingestion_scope: str | None = None,
) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    require_project_role(
        session,
        principal,
        project_id,
        minimum_role,
        allow_ingestion_scope=ingestion_scope,
    )
    return project


def _membership_schema(row: ProjectMembership) -> ProjectMembershipRead:
    return ProjectMembershipRead(
        id=row.id,
        project_id=row.project_id,
        user_id=row.user_id,
        username=row.user.username,
        display_name=row.user.display_name,
        role=row.role,
        granted_by_user_id=row.granted_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _ingestion_token_schema(row: IngestionToken) -> IngestionTokenRead:
    return IngestionTokenRead(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        token_prefix=row.token_prefix,
        scopes=[str(scope) for scope in row.scopes],
        created_by_user_id=row.created_by_user_id,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        last_used_at=row.last_used_at,
        created_at=row.created_at,
    )


def _review_event_schema(row: ReviewEvent) -> ReviewEventRead:
    return ReviewEventRead(
        id=row.id,
        analysis_id=row.analysis_id,
        actor=row.actor,
        actor_kind=row.actor_kind,
        actor_user_id=row.actor_user_id,
        decision=row.decision,
        proposed_category=row.proposed_category,
        reason=row.reason,
        supporting_evidence_ids=row.supporting_evidence_ids,
        contradictory_evidence_ids=row.contradictory_evidence_ids,
        hypothesis_decisions=row.hypothesis_decisions,
        investigation_outcome=row.investigation_outcome,
        release_advice=row.release_advice,
        version=row.version,
        created_at=row.created_at,
    )


def _principal_schema(session: Session, principal: Principal) -> PrincipalRead:
    settings = get_settings()
    if principal.kind == "demo":
        memberships = [
            AuthMembershipRead(
                project_id=project.id,
                project_slug=project.slug,
                project_name=project.name,
                role=ProjectRole.administrator,
            )
            for project in session.scalars(
                select(Project).order_by(Project.created_at)
            ).all()
        ]
        return PrincipalRead(
            kind="demo",
            display_name=principal.display_name,
            system_admin=True,
            demo_mode=True,
            memberships=memberships,
        )
    if principal.kind == "ingestion_token":
        return PrincipalRead(
            kind="ingestion_token",
            display_name=principal.display_name,
            system_admin=False,
            demo_mode=settings.demo_mode,
            memberships=[],
        )
    user = session.get(User, principal.user_id) if principal.user_id else None
    memberships = list(
        session.scalars(
            select(ProjectMembership)
            .where(ProjectMembership.user_id == principal.user_id)
            .options(selectinload(ProjectMembership.project))
            .order_by(ProjectMembership.created_at)
        ).all()
    )
    return PrincipalRead(
        kind="user",
        user_id=principal.user_id,
        username=user.username if user else None,
        display_name=principal.display_name,
        system_admin=principal.system_admin,
        demo_mode=settings.demo_mode,
        memberships=[
            AuthMembershipRead(
                project_id=row.project_id,
                project_slug=row.project.slug,
                project_name=row.project.name,
                role=row.role,
            )
            for row in memberships
        ],
    )


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


@app.post("/api/v1/auth/login", response_model=LoginResponse)
def auth_login(
    request: LoginRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> LoginResponse:
    settings = get_settings()
    try:
        username = normalize_username(request.username)
    except ValueError:
        username = request.username.strip().casefold()
    user = session.scalar(select(User).where(User.username == username).with_for_update()
                          .execution_options(populate_existing=True))
    if user is None or not user.is_active or not verify_password(
        request.password, user.password_hash
    ):
        record_audit_event(
            session,
            Principal(kind="user", actor_id=None, display_name=username or "unknown login"),
            action="auth.login_denied",
            resource_type="authentication",
            outcome="denied",
            reason="invalid credentials",
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid username or password",
        )
    auth_session, raw_token = create_auth_session(session, user, settings=settings)
    user.last_login_at = utcnow()
    principal = Principal(
        kind="user",
        actor_id=user.id,
        display_name=user.display_name,
        user_id=user.id,
        session_id=auth_session.id,
        system_admin=user.is_system_admin,
    )
    record_audit_event(
        session,
        principal,
        action="auth.login_succeeded",
        resource_type="auth_session",
        resource_id=auth_session.id,
    )
    session.commit()
    session.refresh(auth_session)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return LoginResponse(
        principal=_principal_schema(session, principal),
        access_token=raw_token,
        expires_at=auth_session.expires_at,
    )


@app.post("/api/v1/auth/logout", status_code=204)
def auth_logout(
    response: Response,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> Response:
    require_user(principal)
    if principal.session_id:
        row = session.get(AuthSession, principal.session_id)
        if row is not None and row.revoked_at is None:
            row.revoked_at = utcnow()
            record_audit_event(
                session,
                principal,
                action="auth.logout",
                resource_type="auth_session",
                resource_id=row.id,
            )
            session.commit()
    response.delete_cookie(get_settings().session_cookie_name, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@app.get("/api/v1/auth/me", response_model=PrincipalRead)
def auth_me(
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> PrincipalRead:
    require_user(principal)
    return _principal_schema(session, principal)


@app.get("/api/v1/users", response_model=list[UserRead])
def users_list(
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[User]:
    require_system_administrator(principal)
    return list(session.scalars(select(User).order_by(User.username)).all())


@app.post("/api/v1/users", response_model=UserRead, status_code=201)
def users_create(
    request: UserCreate,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> User:
    require_system_administrator(principal)
    try:
        row = create_user(
            session,
            username=request.username,
            display_name=request.display_name,
            password=request.password,
            system_admin=request.system_admin,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    record_audit_event(
        session,
        principal,
        action="user.created",
        resource_type="user",
        resource_id=row.id,
        details={"username": row.username, "system_admin": row.is_system_admin},
    )
    session.commit()
    session.refresh(row)
    return row


@app.get("/api/v1/overview")
def overview(
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> dict:
    project_ids = visible_project_ids(session, principal)

    def scoped_count(model, project_column) -> int:
        query = select(func.count(model.id))
        if project_ids is not None:
            if not project_ids:
                return 0
            query = query.where(project_column.in_(project_ids))
        return int(session.scalar(query) or 0)

    analysis_query = select(Analysis).join(Failure, Failure.id == Analysis.failure_id)
    if project_ids is None:
        analyses = list(session.scalars(analysis_query).all())
    elif project_ids:
        analyses = list(
            session.scalars(
                analysis_query.where(Failure.project_id.in_(project_ids))
            ).all()
        )
    else:
        analyses = []
    publication_categories = Counter(
        (
            item.category.value
            if persisted_analysis_is_publication_validated(item)
            else Category.insufficient_evidence.value
        )
        for item in analyses
    )
    active_query = select(func.count(Ingestion.id)).where(
        Ingestion.state.in_([IngestionState.queued, IngestionState.running])
    )
    cluster_query = select(func.count(FailureCluster.id)).where(
        FailureCluster.status == "active"
    )
    if project_ids is None:
        active_ingestions = int(session.scalar(active_query) or 0)
        cluster_count = int(session.scalar(cluster_query) or 0)
        project_count = int(session.scalar(select(func.count(Project.id))) or 0)
    elif project_ids:
        active_ingestions = int(
            session.scalar(active_query.where(Ingestion.project_id.in_(project_ids))) or 0
        )
        cluster_count = int(
            session.scalar(
                cluster_query.where(FailureCluster.project_id.in_(project_ids))
            )
            or 0
        )
        project_count = len(project_ids)
    else:
        active_ingestions = cluster_count = project_count = 0
    return {
        "projects": project_count,
        "runs": scoped_count(Run, Run.project_id),
        "ingestions": scoped_count(Ingestion, Ingestion.project_id),
        "active_ingestions": active_ingestions,
        "failures": scoped_count(Failure, Failure.project_id),
        "clusters": cluster_count,
        "impact_recommendations": scoped_count(
            ImpactRecommendation, ImpactRecommendation.project_id
        ),
        "performance_comparisons": scoped_count(
            PerformanceComparison, PerformanceComparison.project_id
        ),
        "infrastructure_events": scoped_count(
            InfrastructureEvent, InfrastructureEvent.project_id
        ),
        "infrastructure_correlations": scoped_count(
            InfrastructureCorrelationSnapshot,
            InfrastructureCorrelationSnapshot.project_id,
        ),
        "analyses": len(analyses),
        "categories": {
            category.value: publication_categories.get(category.value, 0)
            for category in Category
        },
    }


@app.post("/api/v1/demo/seed")
def demo_seed(
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> dict:
    settings = get_settings()
    if not settings.demo_mode:
        raise HTTPException(403, "demo mode is disabled")
    require_system_administrator(principal)
    result = seed_demo(session)
    record_audit_event(
        session,
        principal,
        action="demo.seeded",
        resource_type="project",
        resource_id=result.get("project_id"),
        project_id=result.get("project_id"),
    )
    session.commit()
    return result


@app.get("/api/v1/evaluations/latest")
def evaluation_latest(
    principal: Principal = Depends(current_principal),
) -> dict:
    require_user(principal)
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


@app.get("/api/v1/evaluations/fullstack")
def evaluation_fullstack(principal: Principal = Depends(current_principal)) -> dict:
    require_user(principal)
    path = get_settings().fullstack_evaluation_metrics_path
    if not path.exists():
        return {"status": "not_loaded", "message": "Full-stack development evaluation is not mounted."}
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("evaluation report exceeds limit")
        metrics = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(metrics, dict) or metrics.get("evaluation_scope") != "http_postgresql_fault_proxy":
            raise ValueError("evaluation scope differs")
        return {"status": "available", "metrics": metrics}
    except (OSError, ValueError) as exc:
        raise HTTPException(503, "full-stack evaluation metrics unavailable") from exc


@app.get("/api/v1/evaluations/campaign")
def evaluation_campaign(principal: Principal = Depends(current_principal)) -> dict:
    require_user(principal)
    path = get_settings().campaign_evaluation_metrics_path
    if not path.exists():
        return {"status": "not_loaded", "message": "Frozen five-category evaluation is not mounted."}
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("report is not a regular file")
        with path.open("rb") as stream:
            data = stream.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("report exceeds limit")
        metrics = json.loads(data)
        if (not isinstance(metrics, dict)
                or metrics.get("evaluation_scope") != "frozen_mixed_source_campaign"
                or metrics.get("split") != "test"):
            raise ValueError("report scope differs")
        return {"status": "available", "metrics": metrics}
    except (OSError, ValueError) as exc:
        raise HTTPException(503, "campaign evaluation metrics unavailable") from exc


@app.get("/api/v1/evaluations/benchmark")
def evaluation_benchmark(principal: Principal = Depends(current_principal)) -> dict:
    require_user(principal)
    path = get_settings().benchmark_evaluation_metrics_path
    if not path.exists() and not path.is_symlink():
        return {"status": "not_loaded", "message": "The frozen five-category benchmark is not mounted."}
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Invalid evaluation report file")
        with path.open("rb") as stream:
            data = stream.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("Evaluation report exceeds its bound")
        def reject_nonfinite(value: str):
            raise ValueError("Non-finite evaluation measurement")
        metrics = json.loads(data, parse_constant=reject_nonfinite)
        if (not isinstance(metrics, dict)
                or metrics.get("evaluation_scope") != "frozen_five_category_benchmark"
                or metrics.get("split") != "test"):
            raise ValueError("Evaluation scope differs")
        return {"status": "available", "metrics": metrics}
    except (OSError, ValueError) as exc:
        raise HTTPException(503, "benchmark evaluation metrics unavailable") from exc


@app.post("/api/v1/projects", response_model=ProjectRead, status_code=201)
def projects_create(
    request: ProjectCreate,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> Project:
    require_system_administrator(principal)
    try:
        project = create_project(session, request.slug, request.name, commit=False)
    except Exception as exc:
        session.rollback()
        raise HTTPException(409, "project slug already exists") from exc
    if principal.user_id:
        session.add(
            ProjectMembership(
                project_id=project.id,
                user_id=principal.user_id,
                role=ProjectRole.administrator,
                granted_by_user_id=principal.user_id,
            )
        )
    record_audit_event(
        session,
        principal,
        action="project.created",
        resource_type="project",
        resource_id=project.id,
        project_id=project.id,
        details={"slug": project.slug, "name": project.name},
    )
    session.commit()
    session.refresh(project)
    return project


@app.get("/api/v1/projects", response_model=list[ProjectRead])
def projects_list(
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[Project]:
    ids = visible_project_ids(session, principal)
    query = select(Project).order_by(Project.created_at)
    if ids is not None:
        if not ids:
            return []
        query = query.where(Project.id.in_(ids))
    return list(session.scalars(query).all())


@app.get(
    "/api/v1/projects/{project_id}/members",
    response_model=list[ProjectMembershipRead],
)
def project_members_list(
    project_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[ProjectMembershipRead]:
    _require_project(session, principal, project_id, ProjectRole.administrator)
    rows = list(
        session.scalars(
            select(ProjectMembership)
            .where(ProjectMembership.project_id == project_id)
            .options(selectinload(ProjectMembership.user))
            .order_by(ProjectMembership.created_at)
        ).all()
    )
    return [_membership_schema(row) for row in rows]


@app.post(
    "/api/v1/projects/{project_id}/members",
    response_model=ProjectMembershipRead,
    status_code=201,
)
def project_members_create(
    project_id: str,
    request: ProjectMembershipCreate,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> ProjectMembershipRead:
    _require_project(session, principal, project_id, ProjectRole.administrator)
    username = normalize_username(request.username)
    user = session.scalar(select(User).where(User.username == username).with_for_update()
                          .execution_options(populate_existing=True))
    if user is None:
        raise HTTPException(404, "user not found")
    if not user.is_active:
        raise HTTPException(409, "user is disabled")
    existing = session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user.id,
        )
    )
    if existing is not None:
        raise HTTPException(409, "project membership already exists")
    row = ProjectMembership(
        project_id=project_id,
        user_id=user.id,
        role=request.role,
        granted_by_user_id=principal.user_id,
    )
    session.add(row)
    session.flush()
    record_audit_event(
        session,
        principal,
        action="project.membership_created",
        resource_type="project_membership",
        resource_id=row.id,
        project_id=project_id,
        details={"user_id": user.id, "role": request.role.value},
    )
    session.commit()
    row = session.scalar(
        select(ProjectMembership)
        .where(ProjectMembership.id == row.id)
        .options(selectinload(ProjectMembership.user))
    )
    assert row is not None
    return _membership_schema(row)


@app.patch(
    "/api/v1/projects/{project_id}/members/{membership_id}",
    response_model=ProjectMembershipRead,
)
def project_members_update(
    project_id: str,
    membership_id: str,
    request: ProjectMembershipUpdate,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> ProjectMembershipRead:
    _require_project(session, principal, project_id, ProjectRole.administrator)
    row = session.scalar(
        select(ProjectMembership)
        .where(
            ProjectMembership.id == membership_id,
            ProjectMembership.project_id == project_id,
        )
        .options(selectinload(ProjectMembership.user))
    )
    if row is None:
        raise HTTPException(404, "membership not found")
    if row.role == ProjectRole.administrator and request.role != ProjectRole.administrator:
        admin_count = int(
            session.scalar(
                select(func.count(ProjectMembership.id)).where(
                    ProjectMembership.project_id == project_id,
                    ProjectMembership.role == ProjectRole.administrator,
                )
            )
            or 0
        )
        if admin_count <= 1:
            raise HTTPException(409, "the last project administrator cannot be demoted")
    previous = row.role
    row.role = request.role
    record_audit_event(
        session,
        principal,
        action="project.membership_updated",
        resource_type="project_membership",
        resource_id=row.id,
        project_id=project_id,
        details={"from": previous.value, "to": request.role.value, "user_id": row.user_id},
    )
    session.commit()
    session.refresh(row)
    return _membership_schema(row)


@app.delete(
    "/api/v1/projects/{project_id}/members/{membership_id}",
    status_code=204,
)
def project_members_delete(
    project_id: str,
    membership_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> Response:
    _require_project(session, principal, project_id, ProjectRole.administrator)
    row = session.get(ProjectMembership, membership_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, "membership not found")
    if row.role == ProjectRole.administrator:
        admin_count = int(
            session.scalar(
                select(func.count(ProjectMembership.id)).where(
                    ProjectMembership.project_id == project_id,
                    ProjectMembership.role == ProjectRole.administrator,
                )
            )
            or 0
        )
        if admin_count <= 1:
            raise HTTPException(409, "the last project administrator cannot be removed")
    user_id = row.user_id
    session.delete(row)
    record_audit_event(
        session,
        principal,
        action="project.membership_deleted",
        resource_type="project_membership",
        resource_id=membership_id,
        project_id=project_id,
        details={"user_id": user_id},
    )
    session.commit()
    return Response(status_code=204)


@app.get(
    "/api/v1/projects/{project_id}/ingestion-tokens",
    response_model=list[IngestionTokenRead],
)
def ingestion_tokens_list(
    project_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[IngestionTokenRead]:
    _require_project(session, principal, project_id, ProjectRole.administrator)
    rows = list(
        session.scalars(
            select(IngestionToken)
            .where(IngestionToken.project_id == project_id)
            .order_by(IngestionToken.created_at.desc())
        ).all()
    )
    return [_ingestion_token_schema(row) for row in rows]


@app.post(
    "/api/v1/projects/{project_id}/ingestion-tokens",
    response_model=IngestionTokenCreated,
    status_code=201,
)
def ingestion_tokens_create(
    project_id: str,
    request: IngestionTokenCreate,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> IngestionTokenCreated:
    _require_project(session, principal, project_id, ProjectRole.administrator)
    expires_at = as_utc(request.expires_at) if request.expires_at is not None else None
    if expires_at is not None and expires_at <= utcnow():
        raise HTTPException(422, "expires_at must be in the future")
    try:
        row, raw_token = create_project_ingestion_token(
            session,
            project_id=project_id,
            name=request.name,
            created_by_user_id=principal.user_id,
            expires_at=expires_at,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    record_audit_event(
        session,
        principal,
        action="project.ingestion_token_created",
        resource_type="ingestion_token",
        resource_id=row.id,
        project_id=project_id,
        details={
            "name": row.name,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        },
    )
    session.commit()
    session.refresh(row)
    return IngestionTokenCreated(**_ingestion_token_schema(row).model_dump(), token=raw_token)


@app.post(
    "/api/v1/projects/{project_id}/ingestion-tokens/{token_id}/revoke",
    response_model=IngestionTokenRead,
)
def ingestion_tokens_revoke(
    project_id: str,
    token_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> IngestionTokenRead:
    _require_project(session, principal, project_id, ProjectRole.administrator)
    row = session.get(IngestionToken, token_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, "ingestion token not found")
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        record_audit_event(
            session,
            principal,
            action="project.ingestion_token_revoked",
            resource_type="ingestion_token",
            resource_id=row.id,
            project_id=project_id,
            details={"name": row.name},
        )
        session.commit()
        session.refresh(row)
    return _ingestion_token_schema(row)


@app.get(
    "/api/v1/projects/{project_id}/audit-events",
    response_model=list[AuditEventRead],
)
def audit_events_list(
    project_id: str,
    action: str | None = Query(default=None, max_length=120),
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[AuditEvent]:
    _require_project(session, principal, project_id, ProjectRole.reviewer)
    query = select(AuditEvent).where(AuditEvent.project_id == project_id)
    if action:
        query = query.where(AuditEvent.action == action)
    return list(
        session.scalars(
            query.order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit)
        ).all()
    )


@app.post(
    "/api/v1/projects/{project_id}/ingestions",
    status_code=202,
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
    comparison_trust: str = Query(
        default="self_reported",
        pattern=r"^(self_reported|authenticated_lookup|trusted_workflow)$",
    ),
    environment: str | None = Query(default=None, max_length=160),
    timezone: str | None = Query(default=None, max_length=80),
    worker_count: int | None = Query(default=None, ge=1, le=100_000),
    shard_count: int | None = Query(default=None, ge=1, le=100_000),
    expected_inputs: int | None = Query(default=None, ge=0),
    source_format: str = Query(default="auto", min_length=1, max_length=80),
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> RunRead | IngestionRead:
    project = _require_project(
        session,
        principal,
        project_id,
        ProjectRole.administrator,
        ingestion_scope="ingestion:create",
    )

    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type == "application/json" and filename is None:
        try:
            payload = await request.json()
            normalized = IngestionRequest.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        run = ingest_normalized(session, project, normalized)
        record_audit_event(
            session,
            principal,
            action="ingestion.normalized_created",
            resource_type="run",
            resource_id=run.id,
            project_id=project_id,
            details={"external_id": run.external_id},
        )
        session.commit()
        return RunRead.model_validate(run)

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
            comparison_trust=comparison_trust,
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
        # Serialize final source creation/reference registration with project cleanup.
        lock_project(session, project.id)
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
    record_audit_event(
        session,
        principal,
        action="ingestion.queued",
        resource_type="ingestion",
        resource_id=ingestion.id,
        project_id=project_id,
        details={"external_id": ingestion.external_id, "source_format": source_format},
    )
    session.commit()
    return IngestionRead.model_validate(ingestion)


@app.get(
    "/api/v1/projects/{project_id}/ingestions",
    response_model=list[IngestionRead],
)
def ingestions_list(
    project_id: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[Ingestion]:
    _require_project(session, principal, project_id)
    return list(
        session.scalars(
            select(Ingestion)
            .where(Ingestion.project_id == project_id)
            .order_by(Ingestion.created_at.desc())
            .limit(limit)
        ).all()
    )


@app.get("/api/v1/ingestions/{ingestion_id}", response_model=IngestionRead)
def ingestions_get(
    ingestion_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> Ingestion:
    ingestion = session.get(Ingestion, ingestion_id)
    if not ingestion:
        raise HTTPException(404, "ingestion not found")
    require_project_role(session, principal, ingestion.project_id)
    return ingestion


@app.post(
    "/api/v1/ingestions/{ingestion_id}/cancel",
    response_model=IngestionRead,
)
def ingestions_cancel(
    ingestion_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> Ingestion:
    ingestion = session.get(Ingestion, ingestion_id)
    if not ingestion:
        raise HTTPException(404, "ingestion not found")
    require_project_role(
        session, principal, ingestion.project_id, ProjectRole.administrator
    )
    result = cancel_ingestion(session, ingestion)
    record_audit_event(
        session,
        principal,
        action="ingestion.cancelled",
        resource_type="ingestion",
        resource_id=ingestion.id,
        project_id=ingestion.project_id,
    )
    session.commit()
    return result


@app.post(
    "/api/v1/ingestions/{ingestion_id}/retry",
    response_model=IngestionRead,
)
def ingestions_retry(
    ingestion_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> Ingestion:
    ingestion = session.get(Ingestion, ingestion_id)
    if not ingestion:
        raise HTTPException(404, "ingestion not found")
    require_project_role(
        session, principal, ingestion.project_id, ProjectRole.administrator
    )
    try:
        result = retry_ingestion(session, ingestion)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    record_audit_event(
        session,
        principal,
        action="ingestion.retried",
        resource_type="ingestion",
        resource_id=ingestion.id,
        project_id=ingestion.project_id,
    )
    session.commit()
    return result


@app.get("/api/v1/projects/{project_id}/runs", response_model=list[RunRead])
def runs_list(
    project_id: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[Run]:
    _require_project(session, principal, project_id)
    return list(
        session.scalars(
            select(Run)
            .where(Run.project_id == project_id)
            .order_by(Run.created_at.desc())
            .limit(limit)
        ).all()
    )


@app.get("/api/v1/runs/{run_id}", response_model=RunDetailRead)
def runs_get(
    run_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> dict:
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    require_project_role(session, principal, run.project_id)
    counts: dict[str, int] = {}
    for exception_type, count in session.execute(
        select(Failure.exception_type, func.count(Failure.id))
        .where(Failure.run_id == run_id)
        .group_by(Failure.exception_type)
    ).all():
        # A failure need not have an exception type. JSON object keys must be
        # strings; retain these failures in an explicit unknown bucket.
        key = exception_type or "unknown"
        counts[key] = counts.get(key, 0) + count
    return {
        "run": RunRead.model_validate(run),
        "failure_types": counts,
        "failure_count": sum(counts.values()),
    }


@app.get("/api/v1/runs/{run_id}/inputs", response_model=list[RunInputRead])
def run_inputs_list(
    run_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[RunInput]:
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    require_project_role(session, principal, run.project_id)
    return list(
        session.scalars(
            select(RunInput)
            .where(RunInput.run_id == run_id)
            .order_by(RunInput.required.desc(), RunInput.input_id.asc())
        ).all()
    )


@app.post(
    "/api/v1/projects/{project_id}/impact-mappings",
    response_model=ImpactMappingSnapshotRead,
    status_code=201,
)
def impact_mappings_create(
    project_id: str,
    request: ImpactMappingSnapshotCreate,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> ImpactMappingSnapshotRead:
    project = _require_project(
        session, principal, project_id, ProjectRole.administrator
    )
    try:
        snapshot = create_mapping_snapshot(session, project, request)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return mapping_snapshot_to_schema(snapshot)


@app.get(
    "/api/v1/projects/{project_id}/impact-mappings",
    response_model=list[ImpactMappingSnapshotRead],
)
def impact_mappings_list(
    project_id: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[ImpactMappingSnapshotRead]:
    _require_project(session, principal, project_id)
    return [
        mapping_snapshot_to_schema(snapshot)
        for snapshot in list_mapping_snapshots(
            session, project_id, limit=limit, offset=offset
        )
    ]


@app.post(
    "/api/v1/projects/{project_id}/impact-recommendations",
    response_model=ImpactRecommendationRead,
    status_code=201,
)
def impact_recommendations_create(
    project_id: str,
    request: ImpactRecommendationCreate,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> ImpactRecommendationRead:
    project = _require_project(session, principal, project_id, ProjectRole.reviewer)
    try:
        recommendation = create_impact_recommendation(session, project, request)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return impact_recommendation_to_schema(recommendation)


@app.get(
    "/api/v1/projects/{project_id}/impact-recommendations",
    response_model=list[ImpactRecommendationRead],
)
def impact_recommendations_list(
    project_id: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[ImpactRecommendationRead]:
    _require_project(session, principal, project_id)
    return [
        impact_recommendation_to_schema(recommendation)
        for recommendation in list_project_recommendations(
            session, project_id, limit=limit, offset=offset
        )
    ]


@app.get(
    "/api/v1/impact-recommendations/{recommendation_id}",
    response_model=ImpactRecommendationRead,
)
def impact_recommendations_get(
    recommendation_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> ImpactRecommendationRead:
    recommendation = get_impact_recommendation(session, recommendation_id)
    if recommendation is None:
        raise HTTPException(404, "impact recommendation not found")
    require_project_role(session, principal, recommendation.project_id)
    return impact_recommendation_to_schema(recommendation)


@app.post(
    "/api/v1/impact-recommendations/{recommendation_id}/overrides",
    response_model=ImpactRecommendationRead,
    status_code=201,
)
def impact_overrides_create(
    recommendation_id: str,
    request: ImpactOverrideCreate,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> ImpactRecommendationRead:
    recommendation = get_impact_recommendation(session, recommendation_id)
    if recommendation is None:
        raise HTTPException(404, "impact recommendation not found")
    require_project_role(
        session, principal, recommendation.project_id, ProjectRole.reviewer
    )
    try:
        refreshed = apply_impact_override(
            session, recommendation, request, principal=principal
        )
    except ValueError as exc:
        detail = str(exc)
        conflict_markers = (
            "revision conflict",
            "cannot be excluded",
            "cannot be excluded while",
            "would not change",
        )
        status_code = 409 if any(marker in detail for marker in conflict_markers) else 422
        raise HTTPException(status_code, detail) from exc
    return impact_recommendation_to_schema(refreshed)


@app.post(
    "/api/v1/projects/{project_id}/performance-policies",
    response_model=PerformancePolicyRead,
    status_code=201,
)
def performance_policies_create(
    project_id: str,
    request: PerformancePolicyCreate,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> PerformancePolicyRead:
    project = _require_project(
        session, principal, project_id, ProjectRole.administrator
    )
    try:
        policy = create_performance_policy(session, project, request)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return performance_policy_to_schema(policy)


@app.get(
    "/api/v1/projects/{project_id}/performance-policies",
    response_model=list[PerformancePolicyRead],
)
def performance_policies_list(
    project_id: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[PerformancePolicyRead]:
    _require_project(session, principal, project_id)
    return [
        performance_policy_to_schema(item)
        for item in list_performance_policies(
            session, project_id, limit=limit, offset=offset
        )
    ]


@app.get(
    "/api/v1/runs/{run_id}/performance-observations",
    response_model=list[PerformanceObservationRead],
)
def performance_observations_list(
    run_id: str,
    limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
    offset: Annotated[int, Query(ge=0)] = 0,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[PerformanceObservationRead]:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    require_project_role(session, principal, run.project_id)
    return [
        performance_observation_to_schema(item)
        for item in list_run_performance_observations(
            session, run_id, limit=limit, offset=offset
        )
    ]


@app.post(
    "/api/v1/projects/{project_id}/performance-baselines",
    response_model=PerformanceBaselineRead,
    status_code=201,
)
def performance_baselines_create(
    project_id: str,
    request: PerformanceBaselineCreate,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> PerformanceBaselineRead:
    project = _require_project(session, principal, project_id, ProjectRole.reviewer)
    observation = session.get(PerformanceObservation, request.current_observation_id)
    if observation is None or observation.project_id != project_id:
        raise HTTPException(404, "performance observation not found in project")
    if request.policy_id:
        policy = session.get(PerformancePolicy, request.policy_id)
        if policy is None or policy.project_id != project_id:
            raise HTTPException(404, "performance policy not found in project")
    else:
        policy = ensure_default_performance_policy(session, project)
    try:
        baseline = build_performance_baseline(session, observation, policy)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return performance_baseline_to_schema(baseline)


@app.get(
    "/api/v1/performance-baselines/{baseline_id}",
    response_model=PerformanceBaselineRead,
)
def performance_baselines_get(
    baseline_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> PerformanceBaselineRead:
    baseline = get_performance_baseline(session, baseline_id)
    if baseline is None:
        raise HTTPException(404, "performance baseline not found")
    require_project_role(session, principal, baseline.project_id)
    return performance_baseline_to_schema(baseline)


@app.post(
    "/api/v1/runs/{run_id}/performance-comparisons",
    response_model=list[PerformanceComparisonRead],
    status_code=201,
)
def performance_comparisons_create(
    run_id: str,
    request: PerformanceComparisonCreate,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[PerformanceComparisonRead]:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    require_project_role(session, principal, run.project_id, ProjectRole.reviewer)
    project = session.get(Project, run.project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    if request.policy_id:
        policy = session.get(PerformancePolicy, request.policy_id)
        if policy is None or policy.project_id != run.project_id:
            raise HTTPException(404, "performance policy not found in project")
    else:
        policy = ensure_default_performance_policy(session, project)
    try:
        rows = create_run_performance_comparisons(
            session,
            run,
            policy,
            observation_ids=request.observation_ids,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return [performance_comparison_to_schema(item) for item in rows]


@app.get(
    "/api/v1/runs/{run_id}/performance-comparisons",
    response_model=list[PerformanceComparisonRead],
)
def performance_comparisons_list(
    run_id: str,
    limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
    offset: Annotated[int, Query(ge=0)] = 0,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[PerformanceComparisonRead]:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    require_project_role(session, principal, run.project_id)
    return [
        performance_comparison_to_schema(item)
        for item in list_run_performance_comparisons(
            session, run_id, limit=limit, offset=offset
        )
    ]


@app.get(
    "/api/v1/performance-comparisons/{comparison_id}",
    response_model=PerformanceComparisonRead,
)
def performance_comparisons_get(
    comparison_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> PerformanceComparisonRead:
    row = get_performance_comparison(session, comparison_id)
    if row is None:
        raise HTTPException(404, "performance comparison not found")
    require_project_role(session, principal, row.project_id)
    return performance_comparison_to_schema(row)


@app.post(
    "/api/v1/projects/{project_id}/infrastructure-events",
    response_model=InfrastructureEventRead,
    status_code=201,
)
def infrastructure_events_create(
    project_id: str,
    request: InfrastructureEventCreate,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> InfrastructureEventRead:
    project = _require_project(
        session,
        principal,
        project_id,
        ProjectRole.administrator,
    )
    try:
        event = create_infrastructure_event(session, project, request)
    except ValueError as exc:
        detail = str(exc)
        status_code = 409 if "already exists" in detail else 422
        raise HTTPException(status_code, detail) from exc
    return InfrastructureEventRead.model_validate(
        infrastructure_event_to_schema(event)
    )


@app.get(
    "/api/v1/projects/{project_id}/infrastructure-events",
    response_model=list[InfrastructureEventRead],
)
def infrastructure_events_list(
    project_id: str,
    event_kind: str | None = Query(default=None, max_length=80),
    before: datetime | None = None,
    after: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[InfrastructureEventRead]:
    _require_project(session, principal, project_id)
    try:
        events = list_infrastructure_events(
            session,
            project_id,
            event_kind=event_kind,
            before=before,
            after=after,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return [
        InfrastructureEventRead.model_validate(infrastructure_event_to_schema(item))
        for item in events
    ]


@app.get(
    "/api/v1/infrastructure-events/{event_id}",
    response_model=InfrastructureEventRead,
)
def infrastructure_events_get(
    event_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> InfrastructureEventRead:
    event = session.get(InfrastructureEvent, event_id)
    if event is None:
        raise HTTPException(404, "infrastructure event not found")
    require_project_role(session, principal, event.project_id)
    return InfrastructureEventRead.model_validate(infrastructure_event_to_schema(event))


@app.post(
    "/api/v1/tests/{execution_id}/infrastructure-correlations",
    response_model=InfrastructureCorrelationRead,
    status_code=201,
)
def infrastructure_correlations_create(
    execution_id: str,
    request: InfrastructureCorrelationCreate,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> InfrastructureCorrelationRead:
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
    require_project_role(
        session, principal, execution.run.project_id, ProjectRole.reviewer
    )
    reference_cutoff = _utc_datetime(execution.run.started_at or execution.run.created_at)
    requested_cutoff = (
        _utc_datetime(request.before) if request.before is not None else reference_cutoff
    )
    effective_cutoff = min(reference_cutoff, requested_cutoff)
    if request.after is not None and _utc_datetime(request.after) >= effective_cutoff:
        raise HTTPException(422, "after must be earlier than the prior-only cutoff")
    try:
        report = build_infrastructure_correlation(
            session,
            selected_execution=execution,
            selected_run=execution.run,
            cutoff=effective_cutoff,
            after=request.after,
            browser=request.browser,
            match_browser=request.browser is not None,
            branch=request.branch,
            match_branch=request.branch is not None,
            environment=request.environment,
            match_environment=request.environment is not None,
            run_scope=request.run_scope,
            worker_count=request.worker_count,
            match_worker_count=request.worker_count is not None,
            shard_count=request.shard_count,
            match_shard_count=request.shard_count is not None,
            timezone_name=request.timezone or execution.run.timezone or "UTC",
            exclude_run_id=execution.run_id,
            strict_fingerprint=(
                execution.failure.strict_fingerprint
                if execution.failure is not None
                else None
            ),
            event_kind=request.event_kind,
            window_seconds=request.window_seconds,
            minimum_support=request.minimum_support,
            persist=True,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return InfrastructureCorrelationRead.model_validate(report)


@app.get(
    "/api/v1/infrastructure-correlations/{snapshot_id}",
    response_model=InfrastructureCorrelationRead,
)
def infrastructure_correlations_get(
    snapshot_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> InfrastructureCorrelationRead:
    snapshot = get_infrastructure_correlation(session, snapshot_id)
    if snapshot is None:
        raise HTTPException(404, "infrastructure correlation snapshot not found")
    require_project_role(session, principal, snapshot.project_id)
    return InfrastructureCorrelationRead.model_validate(
        infrastructure_correlation_to_schema(session, snapshot)
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
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[ClusterSummary]:
    _require_project(session, principal, project_id)
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
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[ClusterSummary]:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    require_project_role(session, principal, run.project_id)
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
    principal: Principal = Depends(current_principal),
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
    require_project_role(session, principal, cluster.project_id)
    return _cluster_detail(session, cluster)


@app.get(
    "/api/v1/clusters/{cluster_id}/revisions",
    response_model=list[ClusterRevisionRead],
)
def cluster_revisions_list(
    cluster_id: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[ClusterRevisionRead]:
    cluster = session.get(FailureCluster, cluster_id)
    if cluster is None:
        raise HTTPException(404, "cluster not found")
    require_project_role(session, principal, cluster.project_id)
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
)
def cluster_reviews_create(
    cluster_id: str,
    request: ClusterReviewCreate,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> ClusterDetail:
    cluster = session.get(FailureCluster, cluster_id)
    if cluster is None:
        raise HTTPException(404, "cluster not found")
    require_project_role(session, principal, cluster.project_id, ProjectRole.reviewer)
    try:
        review_cluster(
            session,
            cluster,
            actor=principal.display_name,
            decision=request.decision,
            reason=request.reason,
            expected_revision=request.expected_revision,
            failure_ids=request.failure_ids,
            target_cluster_id=request.target_cluster_id,
            principal=principal,
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
    principal: Principal = Depends(current_principal),
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
    require_project_role(session, principal, execution.run.project_id)

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
            observation_limit=MAX_CORRELATION_RUNS,
            observation_offset=0,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        report["infrastructure_correlations"] = build_infrastructure_correlation(
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
            persist=False,
            request_history=report,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    # Pagination changes only the returned rows, never any statistical denominator.
    report["observations"] = report["observations"][offset:offset + limit]
    report["pagination"] = {**report["pagination"], "offset": offset, "limit": limit,
                            "returned": len(report["observations"])}
    return TestHistoryRead.model_validate(report)


@app.get("/api/v1/runs/{run_id}/failures")
def failures_list(
    run_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[dict]:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    require_project_role(session, principal, run.project_id)
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
)
def analyses_create(
    failure_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> AnalysisResult:
    failure = session.scalar(
        select(Failure)
        .where(Failure.id == failure_id)
        .options(selectinload(Failure.execution), selectinload(Failure.run))
    )
    if not failure:
        raise HTTPException(404, "failure not found")
    require_project_role(session, principal, failure.project_id, ProjectRole.reviewer)
    return analysis_to_schema(analyze_and_persist(session, failure))


@app.get("/api/v1/analyses/{analysis_id}", response_model=AnalysisResult)
def analyses_get(
    analysis_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> AnalysisResult:
    row = session.scalar(
        select(Analysis)
        .where(Analysis.id == analysis_id)
        .options(selectinload(Analysis.failure))
    )
    if not row:
        raise HTTPException(404, "analysis not found")
    require_project_role(session, principal, row.failure.project_id)
    return analysis_to_schema(row)


@app.get(
    "/api/v1/projects/{project_id}/review-queue",
    response_model=list[ReviewQueueItem],
)
def review_queue_list(
    project_id: str,
    pending_only: bool = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[ReviewQueueItem]:
    _require_project(session, principal, project_id, ProjectRole.reviewer)
    return review_queue_page(session, project_id, status="pending" if pending_only else "all",
                             limit=limit, offset=offset).items


@app.get(
    "/api/v1/analyses/{analysis_id}/reviews",
    response_model=list[ReviewEventRead],
)
def reviews_list(
    analysis_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[ReviewEventRead]:
    analysis = session.scalar(
        select(Analysis)
        .where(Analysis.id == analysis_id)
        .options(selectinload(Analysis.failure))
    )
    if analysis is None:
        raise HTTPException(404, "analysis not found")
    require_project_role(session, principal, analysis.failure.project_id)
    events = list(
        session.scalars(
            select(ReviewEvent)
            .where(ReviewEvent.analysis_id == analysis_id)
            .order_by(ReviewEvent.version)
        ).all()
    )
    return [_review_event_schema(event) for event in events]


@app.post(
    "/api/v1/analyses/{analysis_id}/reviews",
    response_model=ReviewEventRead,
    status_code=201,
)
def reviews_create(
    analysis_id: str,
    request: ReviewCreate,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> ReviewEventRead:
    row = session.scalar(
        select(Analysis)
        .where(Analysis.id == analysis_id)
        .options(selectinload(Analysis.failure))
    )
    if not row:
        raise HTTPException(404, "analysis not found")
    require_project_role(session, principal, row.failure.project_id, ProjectRole.reviewer)
    try:
        event = add_review(session, row, request, principal=principal)
    except ValueError as exc:
        detail = str(exc)
        code = 409 if "version conflict" in detail else 422
        raise HTTPException(code, detail) from exc
    return _review_event_schema(event)


@app.get("/api/v1/evidence/{evidence_id}", response_model=EvidenceRead)
def evidence_get(
    evidence_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> EvidenceRead:
    evidence = session.scalar(
        select(Evidence)
        .where(Evidence.id == evidence_id)
        .options(selectinload(Evidence.derivative))
    )
    if not evidence:
        raise HTTPException(404, "evidence not found")
    require_project_role(session, principal, evidence.project_id)
    derivative = evidence.derivative
    run = session.get(Run, evidence.run_id)
    if (run and run.evidence_expired_at is not None) or (derivative and derivative.retention_state == "expired"):
        raise HTTPException(410, detail={"code": "evidence_expired", "message": "Evidence expired under project retention policy."})
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


# Keep binary handling separate from test-outcome analysis and never expose source storage.
from .binary_api import router as binary_router
app.include_router(binary_router)


@app.get("/api/v1/runs/{run_id}/github-report-preview")
def github_report_preview(
    run_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> dict:
    from .github_snapshot import report_snapshot
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    require_project_role(session, principal, run.project_id)
    return report_snapshot(session, run)


@app.get("/api/v1/operations/telemetry")
def operational_telemetry(
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> dict:
    require_system_administrator(principal)
    from .models import Job, JobState
    counts = {state.value: 0 for state in JobState}
    counts.update({state.value: int(count) for state, count in session.execute(
        select(Job.state, func.count(Job.id)).group_by(Job.state))})
    oldest = session.scalar(select(func.min(Job.created_at)).where(Job.state == JobState.queued))
    return {**metrics_snapshot(), "queue": {"states": counts,
        "oldest_queued_age_seconds": max(0.0, (datetime.now(UTC) - as_utc(oldest)).total_seconds()) if oldest else None}}
