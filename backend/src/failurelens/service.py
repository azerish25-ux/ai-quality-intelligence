from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .analysis import ANALYSIS_VERSION, RULES_VERSION, EvidenceView, analyze_failure, input_digest
from .config import Settings, get_settings
from .fingerprint import make_fingerprint
from .ingestion import PARSER_VERSION, ParsedArtifact, ParsedObservation, parse_artifact
from .models import (
    Analysis,
    Artifact,
    Category,
    Evidence,
    Failure,
    Ingestion,
    IngestionState,
    Job,
    JobState,
    Outcome,
    Project,
    ReviewEvent,
    Run,
    RunStatus,
    TestExecution,
)
from .redaction import REDACTION_VERSION, redact_text
from .schemas import AnalysisResult, Confidence, IngestionRequest, ReviewCreate, RunMetadata
from .storage import StoredUpload, read_stored_bytes

INGEST_JOB_KIND = "ingest_and_analyze_v1"
ARTIFACT_POLICY_VERSION = "artifact-policy-v1"


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


def _completeness(expected: int | None, received: int) -> str:
    if expected is None:
        return "complete"
    if expected == received:
        return "complete"
    return "partial"


def ingest_parsed_report(
    session: Session,
    project: Project,
    metadata: RunMetadata,
    observations: Sequence[ParsedObservation],
    *,
    source_name: str,
    source_digest: str,
    source_size_bytes: int,
    storage_path: str,
    media_type: str,
    source_format: str,
    parser_version: str,
    parser_warnings: Sequence[str] = (),
    restricted: bool = True,
) -> Run:
    identity_payload = {
        "schema_version": "artifact-ingestion-v1",
        "external_id": metadata.external_id,
        "attempt": metadata.attempt,
        "repository": metadata.repository,
        "commit_sha": metadata.commit_sha,
        "base_sha": metadata.base_sha,
        "branch": metadata.branch,
        "source_digest": source_digest,
        "source_format": source_format,
        "parser_version": parser_version,
        "expected_inputs": metadata.expected_inputs,
    }
    digest = manifest_digest(identity_payload)
    existing = session.scalar(
        select(Run).where(
            Run.project_id == project.id,
            Run.external_id == metadata.external_id,
            Run.attempt == metadata.attempt,
            Run.manifest_digest == digest,
        )
    )
    if existing:
        return existing

    completeness = _completeness(metadata.expected_inputs, len(observations))
    run = Run(
        project_id=project.id,
        external_id=metadata.external_id,
        attempt=metadata.attempt,
        repository=metadata.repository,
        commit_sha=metadata.commit_sha,
        base_sha=metadata.base_sha,
        branch=metadata.branch,
        framework=source_format,
        status=RunStatus.processing,
        completeness=completeness,
        expected_inputs=metadata.expected_inputs,
        received_inputs=len(observations),
        manifest_digest=digest,
        started_at=datetime.now(UTC),
        source_metadata={
            **metadata.source_metadata,
            "source_format": source_format,
            "parser_version": parser_version,
            "parser_warnings": list(parser_warnings),
            "source_digest": source_digest,
        },
    )
    session.add(run)
    session.flush()

    artifact = Artifact(
        run_id=run.id,
        kind="source-report",
        original_name=source_name,
        digest=source_digest,
        safe_storage_path=storage_path,
        media_type=media_type,
        size_bytes=source_size_bytes,
        redaction_version=REDACTION_VERSION,
        restricted=restricted,
        metadata_json={
            "source_format": source_format,
            "parser_version": parser_version,
            "warnings": list(parser_warnings),
        },
    )
    session.add(artifact)
    session.flush()

    for observation_index, observation in enumerate(observations):
        try:
            outcome = Outcome(observation.outcome)
        except ValueError:
            outcome = Outcome.unknown
        details = dict(observation.details)
        details["retry_recovered"] = bool(details.get("retry_recovered"))
        raw_message = observation.message or ""
        safe_message = redact_text(raw_message)
        execution = TestExecution(
            run_id=run.id,
            test_identity=observation.test_identity,
            suite=observation.suite,
            source_path=observation.source_path,
            browser=observation.browser,
            attempt=observation.attempt,
            outcome=outcome,
            duration_ms=observation.duration_ms,
            retry_recovered=bool(details.get("retry_recovered")),
            details=details,
        )
        session.add(execution)
        session.flush()

        raw_excerpt = observation.evidence_excerpt or raw_message or f"{observation.test_identity}: {outcome.value}"
        safe_excerpt = redact_text(raw_excerpt)
        evidence = Evidence(
            project_id=project.id,
            run_id=run.id,
            artifact_id=artifact.id,
            kind="current_run_observation",
            locator=observation.evidence_locator or {
                "kind": "derived-observation",
                "index": observation_index,
            },
            excerpt=safe_excerpt.text[:40_000],
            content_digest=hashlib.sha256(safe_excerpt.text.encode("utf-8")).hexdigest(),
            parser_version=parser_version,
            warnings=[
                *[f"redacted:{item}" for item in safe_excerpt.classes],
                *[f"parser:{item}" for item in parser_warnings],
            ],
        )
        session.add(evidence)
        session.flush()
        if outcome is Outcome.failed:
            message = safe_message.text or safe_excerpt.text or "Test failed without a message"
            fingerprint, features = make_fingerprint(message, observation.exception_type, details)
            session.add(
                Failure(
                    project_id=project.id,
                    run_id=run.id,
                    execution_id=execution.id,
                    message=message,
                    exception_type=observation.exception_type,
                    strict_fingerprint=fingerprint,
                    loose_features=features,
                )
            )

    run.status = RunStatus.complete if completeness == "complete" else RunStatus.partial
    run.ended_at = datetime.now(UTC)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(Run).where(
                Run.project_id == project.id,
                Run.external_id == metadata.external_id,
                Run.attempt == metadata.attempt,
                Run.manifest_digest == digest,
            )
        )
        if existing:
            return existing
        raise
    session.refresh(run)
    return run


def ingest_normalized(session: Session, project: Project, request: IngestionRequest) -> Run:
    payload = request.model_dump(mode="json")
    artifact_payload = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    artifact_digest = hashlib.sha256(artifact_payload).hexdigest()
    parsed = [
        ParsedObservation(
            test_identity=observation.test_identity,
            suite=observation.suite,
            source_path=observation.source_path,
            browser=observation.browser,
            attempt=observation.attempt,
            outcome=observation.outcome.value,
            duration_ms=observation.duration_ms,
            message=observation.message,
            exception_type=observation.exception_type,
            details=observation.details,
            evidence_excerpt=observation.message,
            evidence_locator={"kind": "json-pointer", "pointer": f"/observations/{index}"},
        )
        for index, observation in enumerate(request.observations)
    ]
    metadata = RunMetadata.model_validate(request.model_dump(exclude={"schema_version", "observations"}))
    return ingest_parsed_report(
        session,
        project,
        metadata,
        parsed,
        source_name="normalized-ingestion.json",
        source_digest=artifact_digest,
        source_size_bytes=len(artifact_payload),
        storage_path=f"db://normalized/{artifact_digest}",
        media_type="application/json",
        source_format="normalized-json",
        parser_version="normalized-v1",
        restricted=False,
    )


def enqueue_artifact_ingestion(
    session: Session,
    project: Project,
    metadata: RunMetadata,
    stored: StoredUpload,
    *,
    source_format: str = "auto",
    settings: Settings | None = None,
) -> Ingestion:
    existing = session.scalar(
        select(Ingestion).where(
            Ingestion.project_id == project.id,
            Ingestion.external_id == metadata.external_id,
            Ingestion.attempt == metadata.attempt,
            Ingestion.source_digest == stored.digest,
        )
    )
    if existing:
        supplied = {
            "repository": metadata.repository,
            "commit_sha": metadata.commit_sha,
            "base_sha": metadata.base_sha,
            "branch": metadata.branch,
            "expected_inputs": metadata.expected_inputs,
            "source_format": source_format,
        }
        conflicts = [
            field
            for field, value in supplied.items()
            if value != getattr(existing, field)
        ]
        if conflicts:
            raise ValueError(
                "idempotency conflict for existing ingestion fields: " + ", ".join(conflicts)
            )
        return existing

    settings = settings or get_settings()
    ingestion = Ingestion(
        project_id=project.id,
        external_id=metadata.external_id,
        attempt=metadata.attempt,
        repository=metadata.repository,
        commit_sha=metadata.commit_sha,
        base_sha=metadata.base_sha,
        branch=metadata.branch,
        source_format=source_format,
        source_metadata=metadata.source_metadata,
        original_name=stored.original_name,
        media_type=stored.media_type,
        source_digest=stored.digest,
        source_size_bytes=stored.size_bytes,
        storage_path=stored.relative_path,
        expected_inputs=metadata.expected_inputs,
        state=IngestionState.queued,
        policy_version=ARTIFACT_POLICY_VERSION,
        diagnostics=[{"phase": "accepted", "status": "complete"}],
    )
    session.add(ingestion)
    session.flush()
    job = Job(
        project_id=project.id,
        kind=INGEST_JOB_KIND,
        payload={"ingestion_id": ingestion.id, "job_schema": "1.0"},
        state=JobState.queued,
        max_attempts=settings.job_max_attempts,
    )
    session.add(job)
    session.flush()
    ingestion.job_id = job.id
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(Ingestion).where(
                Ingestion.project_id == project.id,
                Ingestion.external_id == metadata.external_id,
                Ingestion.attempt == metadata.attempt,
                Ingestion.source_digest == stored.digest,
            )
        )
        if existing:
            return existing
        raise
    session.refresh(ingestion)
    return ingestion


def retry_ingestion(
    session: Session,
    ingestion: Ingestion,
    *,
    settings: Settings | None = None,
) -> Ingestion:
    if ingestion.state not in {
        IngestionState.failed,
        IngestionState.dead_lettered,
        IngestionState.cancelled,
    }:
        raise ValueError(f"ingestion in state {ingestion.state.value} cannot be retried")
    settings = settings or get_settings()
    job = Job(
        project_id=ingestion.project_id,
        kind=INGEST_JOB_KIND,
        payload={"ingestion_id": ingestion.id, "job_schema": "1.0"},
        state=JobState.queued,
        max_attempts=settings.job_max_attempts,
    )
    session.add(job)
    session.flush()
    ingestion.job_id = job.id
    ingestion.state = IngestionState.queued
    ingestion.error_code = None
    ingestion.error_message = None
    ingestion.started_at = None
    ingestion.completed_at = None
    ingestion.retry_count += 1
    ingestion.diagnostics = [
        *ingestion.diagnostics,
        {"phase": "retry", "status": "queued", "retry": ingestion.retry_count},
    ]
    session.commit()
    session.refresh(ingestion)
    return ingestion


def cancel_ingestion(session: Session, ingestion: Ingestion) -> Ingestion:
    if ingestion.state in {
        IngestionState.succeeded,
        IngestionState.partial,
        IngestionState.failed,
        IngestionState.dead_lettered,
        IngestionState.cancelled,
    }:
        return ingestion
    ingestion.state = IngestionState.cancelled
    ingestion.completed_at = datetime.now(UTC)
    ingestion.diagnostics = [*ingestion.diagnostics, {"phase": "cancel", "status": "cancelled"}]
    if ingestion.job and ingestion.job.state in {JobState.queued, JobState.running}:
        ingestion.job.state = JobState.cancelled
        ingestion.job.lease_owner = None
        ingestion.job.lease_expires_at = None
    session.commit()
    session.refresh(ingestion)
    return ingestion


def process_artifact_ingestion(
    session: Session,
    ingestion: Ingestion,
    *,
    settings: Settings | None = None,
    heartbeat: Any | None = None,
) -> Run:
    settings = settings or get_settings()
    content = read_stored_bytes(
        root=settings.artifact_root,
        relative_path=ingestion.storage_path,
        expected_digest=ingestion.source_digest,
        expected_size=ingestion.source_size_bytes,
        max_bytes=max(settings.max_file_bytes, settings.max_bundle_bytes),
    )
    if heartbeat:
        heartbeat()
    parsed: ParsedArtifact = parse_artifact(content, ingestion.original_name, settings)
    if heartbeat:
        heartbeat()
    metadata = RunMetadata(
        external_id=ingestion.external_id,
        attempt=ingestion.attempt,
        repository=ingestion.repository,
        commit_sha=ingestion.commit_sha,
        base_sha=ingestion.base_sha,
        branch=ingestion.branch,
        framework=parsed.source_format,
        expected_inputs=ingestion.expected_inputs,
        source_metadata={
            **ingestion.source_metadata,
            "ingestion_id": ingestion.id,
            "report_name": parsed.report_name,
            "source_format_requested": ingestion.source_format,
        },
    )
    run = ingest_parsed_report(
        session,
        ingestion.project,
        metadata,
        parsed.observations,
        source_name=ingestion.original_name,
        source_digest=ingestion.source_digest,
        source_size_bytes=ingestion.source_size_bytes,
        storage_path=ingestion.storage_path,
        media_type=ingestion.media_type,
        source_format=parsed.source_format,
        parser_version=parsed.parser_version,
        parser_warnings=parsed.warnings,
        restricted=True,
    )
    failures = list(session.scalars(select(Failure).where(Failure.run_id == run.id)).all())
    for failure in failures:
        analyze_and_persist(session, failure)
        if heartbeat:
            heartbeat()

    ingestion = session.get(Ingestion, ingestion.id)
    if ingestion is None:
        raise RuntimeError("ingestion disappeared while processing")
    session.refresh(ingestion)
    if ingestion.state is IngestionState.cancelled:
        return run
    ingestion.run_id = run.id
    ingestion.received_inputs = run.received_inputs
    ingestion.parser_version = parsed.parser_version
    ingestion.state = (
        IngestionState.succeeded if run.completeness == "complete" else IngestionState.partial
    )
    ingestion.error_code = None
    ingestion.error_message = None
    ingestion.completed_at = datetime.now(UTC)
    ingestion.diagnostics = [
        *ingestion.diagnostics,
        {
            "phase": "parse",
            "status": "complete",
            "format": parsed.source_format,
            "report": parsed.report_name,
            "observations": len(parsed.observations),
            "warnings": list(parsed.warnings),
        },
        {
            "phase": "analysis",
            "status": "complete",
            "failures": len(failures),
        },
    ]
    session.commit()
    session.refresh(ingestion)
    return run


def _historical_context(session: Session, failure: Failure) -> dict[str, Any]:
    prior_count = session.scalar(
        select(func.count(Failure.id)).where(
            Failure.project_id == failure.project_id,
            Failure.strict_fingerprint == failure.strict_fingerprint,
            Failure.created_at < failure.created_at,
        )
    ) or 0
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
    evidence_rows = list(
        session.scalars(select(Evidence).where(Evidence.run_id == failure.run_id)).all()
    )
    views = [
        EvidenceView(id=evidence.id, kind=evidence.kind, excerpt=evidence.excerpt, observation={})
        for evidence in evidence_rows
    ]
    execution = failure.execution
    historical = _historical_context(session, failure)
    payload = {
        "message": failure.message,
        "exception_type": failure.exception_type,
        "details": execution.details,
        "evidence": [evidence.id for evidence in evidence_rows],
        "history": historical,
        "analysis_version": ANALYSIS_VERSION,
        "rules_version": RULES_VERSION,
    }
    digest = input_digest(payload)
    existing = session.scalar(
        select(Analysis).where(
            Analysis.failure_id == failure.id,
            Analysis.analysis_version == ANALYSIS_VERSION,
            Analysis.input_digest == digest,
        )
    )
    if existing:
        return existing

    decision = analyze_failure(
        message=failure.message,
        exception_type=failure.exception_type,
        details={
            **execution.details,
            "retry_recovered": execution.retry_recovered,
            "incomplete_run": failure.run.completeness != "complete",
        },
        evidence=views,
        historical=historical,
    )
    revision = (
        session.scalar(select(func.max(Analysis.revision)).where(Analysis.failure_id == failure.id))
        or 0
    ) + 1
    row = Analysis(
        failure_id=failure.id,
        revision=revision,
        analysis_version=ANALYSIS_VERSION,
        input_digest=digest,
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
        provenance={
            "input_digest": digest,
            "history_cutoff": datetime.now(UTC).isoformat(),
            "parser_versions": sorted({item.parser_version for item in evidence_rows}),
            "rules_version": RULES_VERSION,
            "analysis_version": ANALYSIS_VERSION,
        },
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(Analysis).where(
                Analysis.failure_id == failure.id,
                Analysis.analysis_version == ANALYSIS_VERSION,
                Analysis.input_digest == digest,
            )
        )
        if existing:
            return existing
        raise
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
        confidence=Confidence(
            value=row.confidence_value,
            kind=row.confidence_kind,
            explanation=row.confidence_explanation,
        ),
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
    current_version = session.scalar(
        select(func.max(ReviewEvent.version)).where(ReviewEvent.analysis_id == analysis.id)
    ) or 0
    if request.expected_version != current_version:
        raise ValueError(
            f"review version conflict: expected {request.expected_version}, current {current_version}"
        )
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
