from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .analysis import ANALYSIS_VERSION, EvidenceView, analyze_failure, input_digest
from .fingerprint import make_fingerprint
from .models import Analysis, Artifact, Category, Evidence, Failure, Outcome, Project, ReviewEvent, Run, RunStatus, TestExecution
from .redaction import REDACTION_VERSION, redact_text
from .schemas import AnalysisResult, Confidence, IngestionRequest, ReviewCreate


def manifest_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_project(session: Session, slug: str, name: str) -> Project:
    project = Project(slug=slug, name=name)
    session.add(project)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(Project).where(Project.slug == slug))
        if existing:
            return existing
        raise
    session.refresh(project)
    return project


def ingest_normalized(session: Session, project: Project, request: IngestionRequest) -> Run:
    payload = request.model_dump(mode="json")
    digest = manifest_digest(payload)
    existing = session.scalar(select(Run).where(
        Run.project_id == project.id,
        Run.external_id == request.external_id,
        Run.attempt == request.attempt,
        Run.manifest_digest == digest,
    ))
    if existing:
        return existing

    run = Run(
        project_id=project.id,
        external_id=request.external_id,
        attempt=request.attempt,
        repository=request.repository,
        commit_sha=request.commit_sha,
        base_sha=request.base_sha,
        branch=request.branch,
        framework=request.framework,
        status=RunStatus.processing,
        completeness="complete" if request.expected_inputs in (None, len(request.observations)) else "partial",
        expected_inputs=request.expected_inputs,
        received_inputs=len(request.observations),
        manifest_digest=digest,
        started_at=datetime.now(UTC),
        source_metadata=request.source_metadata,
    )
    session.add(run)
    session.flush()

    artifact_payload = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    artifact_digest = hashlib.sha256(artifact_payload).hexdigest()
    artifact = Artifact(
        run_id=run.id,
        kind="normalized-manifest",
        original_name="normalized-ingestion.json",
        digest=artifact_digest,
        safe_storage_path=f"db://runs/{run.id}/normalized-manifest",
        media_type="application/json",
        size_bytes=len(artifact_payload),
        redaction_version=REDACTION_VERSION,
        restricted=False,
        metadata_json={"schema_version": request.schema_version},
    )
    session.add(artifact)
    session.flush()

    for observation_index, observation in enumerate(request.observations):
        details = dict(observation.details)
        details["retry_recovered"] = bool(details.get("retry_recovered"))
        safe_message = redact_text(observation.message or "")
        execution = TestExecution(
            run_id=run.id,
            test_identity=observation.test_identity,
            suite=observation.suite,
            source_path=observation.source_path,
            browser=observation.browser,
            attempt=observation.attempt,
            outcome=observation.outcome,
            duration_ms=observation.duration_ms,
            retry_recovered=bool(details.get("retry_recovered")),
            details=details,
        )
        session.add(execution)
        session.flush()
        excerpt = safe_message.text or f"{observation.test_identity}: {observation.outcome.value}"
        evidence = Evidence(
            project_id=project.id,
            run_id=run.id,
            artifact_id=artifact.id,
            kind="current_run_observation",
            locator={"kind": "json-pointer", "pointer": f"/observations/{observation_index}"},
            excerpt=excerpt[:40_000],
            content_digest=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            parser_version="normalized-v1",
            warnings=[f"redacted:{item}" for item in safe_message.classes],
        )
        session.add(evidence)
        session.flush()
        if observation.outcome is Outcome.failed:
            fp, features = make_fingerprint(safe_message.text, observation.exception_type, details)
            failure = Failure(
                project_id=project.id,
                run_id=run.id,
                execution_id=execution.id,
                message=safe_message.text or "Test failed without a message",
                exception_type=observation.exception_type,
                strict_fingerprint=fp,
                loose_features=features,
            )
            session.add(failure)

    run.status = RunStatus.complete if run.completeness == "complete" else RunStatus.partial
    run.ended_at = datetime.now(UTC)
    session.commit()
    session.refresh(run)
    return run


def _historical_context(session: Session, failure: Failure) -> dict[str, Any]:
    prior_count = session.scalar(select(func.count(Failure.id)).where(
        Failure.project_id == failure.project_id,
        Failure.strict_fingerprint == failure.strict_fingerprint,
        Failure.created_at < failure.created_at,
    )) or 0
    reviewed_known_flake = session.scalar(
        select(func.count(ReviewEvent.id))
        .join(Analysis, ReviewEvent.analysis_id == Analysis.id)
        .join(Failure, Analysis.failure_id == Failure.id)
        .where(
            Failure.project_id == failure.project_id,
            Failure.strict_fingerprint == failure.strict_fingerprint,
            ReviewEvent.proposed_category == Category.known_flake.value,
            ReviewEvent.decision.in_(["accept", "category_correction"]),
        )
    ) or 0
    return {
        "independent_runs": prior_count + 1,
        "reviewed_known_flake": reviewed_known_flake > 0,
        "retry_recovery_rate": 0.0,
    }


def analyze_and_persist(session: Session, failure: Failure) -> Analysis:
    evidence_rows = list(session.scalars(select(Evidence).where(Evidence.run_id == failure.run_id)).all())
    views = [EvidenceView(id=e.id, kind=e.kind, excerpt=e.excerpt, observation={}) for e in evidence_rows]
    execution = failure.execution
    decision = analyze_failure(
        message=failure.message,
        exception_type=failure.exception_type,
        details={**execution.details, "retry_recovered": execution.retry_recovered, "incomplete_run": failure.run.completeness != "complete"},
        evidence=views,
        historical=_historical_context(session, failure),
    )
    revision = (session.scalar(select(func.max(Analysis.revision)).where(Analysis.failure_id == failure.id)) or 0) + 1
    payload = {
        "message": failure.message,
        "exception_type": failure.exception_type,
        "details": execution.details,
        "evidence": [e.id for e in evidence_rows],
    }
    row = Analysis(
        failure_id=failure.id,
        revision=revision,
        analysis_version=ANALYSIS_VERSION,
        category=decision.category,
        severity=decision.severity,
        confidence_value=decision.score,
        confidence_kind=decision.score_kind,
        confidence_explanation=decision.explanation,
        evidence_completeness="partial" if decision.missing else "complete",
        summary=decision.summary,
        claims=list(decision.claims),
        supporting_evidence_ids=list(decision.supporting_ids),
        contradictory_evidence_ids=list(decision.contradictory_ids),
        missing_evidence=list(decision.missing),
        hypotheses=list(decision.hypotheses),
        next_investigation=list(decision.next_steps),
        abstention_reason=decision.abstention_reason,
        policy_flags=list(decision.policy_flags),
        provenance={"input_digest": input_digest(payload), "history_cutoff": datetime.now(UTC).isoformat(), "rules_version": "rules-v1", "analysis_version": ANALYSIS_VERSION},
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def analysis_to_schema(row: Analysis) -> AnalysisResult:
    return AnalysisResult(
        analysis_id=row.id,
        analysis_version=row.analysis_version,
        failure_id=row.failure_id,
        run_id=row.failure.run_id,
        category=row.category,
        severity=row.severity,
        confidence=Confidence(value=row.confidence_value, kind=row.confidence_kind, explanation=row.confidence_explanation),
        evidence_completeness=row.evidence_completeness,
        summary=row.summary,
        claims=row.claims,
        supporting_evidence_ids=row.supporting_evidence_ids,
        contradictory_evidence_ids=row.contradictory_evidence_ids,
        missing_evidence=row.missing_evidence,
        hypotheses=row.hypotheses,
        next_investigation=row.next_investigation,
        abstention_reason=row.abstention_reason,
        policy_flags=row.policy_flags,
        provenance=row.provenance,
    )


def add_review(session: Session, analysis: Analysis, request: ReviewCreate) -> ReviewEvent:
    current_version = session.scalar(select(func.max(ReviewEvent.version)).where(ReviewEvent.analysis_id == analysis.id)) or 0
    if request.expected_version != current_version:
        raise ValueError(f"review version conflict: expected {request.expected_version}, current {current_version}")
    if request.decision == "category_correction" and request.proposed_category is None:
        raise ValueError("category_correction requires proposed_category")
    event = ReviewEvent(
        analysis_id=analysis.id,
        actor=request.actor,
        decision=request.decision,
        proposed_category=request.proposed_category.value if request.proposed_category else None,
        reason=request.reason,
        version=current_version + 1,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event
