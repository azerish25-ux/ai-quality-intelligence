from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .db import get_session, initialize_database
from .models import Analysis, Category, Evidence, Failure, Project, ReviewEvent, Run
from .schemas import AnalysisResult, IngestionRequest, ProjectCreate, ProjectRead, ReviewCreate, RunRead
from .demo import seed_demo
from .service import add_review, analysis_to_schema, analyze_and_persist, create_project, ingest_normalized

@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="FailureLens API", version="0.1.0", description="Evidence-grounded automated test failure triage", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:8080"], allow_methods=["*"], allow_headers=["*"])


def authorized(x_failurelens_token: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if settings.demo_mode and settings.ingestion_token is None:
        return
    if not settings.ingestion_token or x_failurelens_token != settings.ingestion_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid ingestion token")


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "live"}


@app.get("/health/ready")
def ready(session: Session = Depends(get_session)) -> dict[str, str]:
    session.execute(select(1))
    return {"status": "ready"}


@app.get("/api/v1/overview")
def overview(session: Session = Depends(get_session)) -> dict:
    return {
        "projects": session.scalar(select(func.count(Project.id))) or 0,
        "runs": session.scalar(select(func.count(Run.id))) or 0,
        "failures": session.scalar(select(func.count(Failure.id))) or 0,
        "analyses": session.scalar(select(func.count(Analysis.id))) or 0,
        "categories": {
            category.value: session.scalar(select(func.count(Analysis.id)).where(Analysis.category == category)) or 0
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
        return {"status": "not_loaded", "message": "No executed evaluation metrics are available in this runtime."}
    try:
        return {"status": "available", "metrics": json.loads(path.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(503, f"evaluation metrics unavailable: {exc}") from exc


@app.post("/api/v1/projects", response_model=ProjectRead, status_code=201, dependencies=[Depends(authorized)])
def projects_create(request: ProjectCreate, session: Session = Depends(get_session)) -> Project:
    return create_project(session, request.slug, request.name)


@app.get("/api/v1/projects", response_model=list[ProjectRead])
def projects_list(session: Session = Depends(get_session)) -> list[Project]:
    return list(session.scalars(select(Project).order_by(Project.created_at)).all())


@app.post("/api/v1/projects/{project_id}/ingestions", response_model=RunRead, status_code=202, dependencies=[Depends(authorized)])
def ingestions_create(project_id: str, request: IngestionRequest, session: Session = Depends(get_session)) -> Run:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    return ingest_normalized(session, project, request)


@app.get("/api/v1/projects/{project_id}/runs", response_model=list[RunRead])
def runs_list(project_id: str, limit: int = Query(default=50, ge=1, le=200), session: Session = Depends(get_session)) -> list[Run]:
    return list(session.scalars(select(Run).where(Run.project_id == project_id).order_by(Run.created_at.desc()).limit(limit)).all())


@app.get("/api/v1/runs/{run_id}")
def runs_get(run_id: str, session: Session = Depends(get_session)) -> dict:
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    counts = dict(session.execute(select(Failure.exception_type, func.count(Failure.id)).where(Failure.run_id == run_id).group_by(Failure.exception_type)).all())
    return {"run": RunRead.model_validate(run), "failure_types": counts, "failure_count": sum(counts.values())}


@app.get("/api/v1/runs/{run_id}/failures")
def failures_list(run_id: str, session: Session = Depends(get_session)) -> list[dict]:
    failures = session.scalars(select(Failure).where(Failure.run_id == run_id).options(selectinload(Failure.analyses))).all()
    return [{"id": f.id, "test_identity": f.execution.test_identity, "message": f.message, "fingerprint": f.strict_fingerprint, "latest_analysis": analysis_to_schema(f.analyses[-1]).model_dump(mode="json") if f.analyses else None} for f in failures]


@app.post("/api/v1/failures/{failure_id}/analyses", response_model=AnalysisResult, status_code=201, dependencies=[Depends(authorized)])
def analyses_create(failure_id: str, session: Session = Depends(get_session)) -> AnalysisResult:
    failure = session.scalar(select(Failure).where(Failure.id == failure_id).options(selectinload(Failure.execution), selectinload(Failure.run)))
    if not failure:
        raise HTTPException(404, "failure not found")
    return analysis_to_schema(analyze_and_persist(session, failure))


@app.get("/api/v1/analyses/{analysis_id}", response_model=AnalysisResult)
def analyses_get(analysis_id: str, session: Session = Depends(get_session)) -> AnalysisResult:
    row = session.scalar(select(Analysis).where(Analysis.id == analysis_id).options(selectinload(Analysis.failure)))
    if not row:
        raise HTTPException(404, "analysis not found")
    return analysis_to_schema(row)


@app.post("/api/v1/analyses/{analysis_id}/reviews", status_code=201, dependencies=[Depends(authorized)])
def reviews_create(analysis_id: str, request: ReviewCreate, session: Session = Depends(get_session)) -> dict:
    row = session.get(Analysis, analysis_id)
    if not row:
        raise HTTPException(404, "analysis not found")
    try:
        event = add_review(session, row, request)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"id": event.id, "version": event.version, "decision": event.decision, "created_at": event.created_at}


@app.get("/api/v1/evidence/{evidence_id}")
def evidence_get(evidence_id: str, session: Session = Depends(get_session)) -> dict:
    evidence = session.get(Evidence, evidence_id)
    if not evidence:
        raise HTTPException(404, "evidence not found")
    return {"id": evidence.id, "kind": evidence.kind, "locator": evidence.locator, "excerpt": evidence.excerpt, "digest": evidence.content_digest, "warnings": evidence.warnings}
