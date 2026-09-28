"""Project-scoped retention, privacy tombstones and resumable file deletion.

A run's evidence body is the expiration unit. Outcomes, opaque IDs, recorded
categories and attributed decision/version history remain; potentially quoted
free text is erased. This is retention redaction, not a replacement diagnosis.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import PurePosixPath

from fastapi import HTTPException
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from .auth import Principal, as_utc, record_audit_event
from .config import Settings
from . import models as m
from .schemas import RetentionPreview
from .storage import StorageError, _resolve_under

RETENTION_JOB_KIND = "retention_cleanup_v1"
EXPIRED = "Evidence expired under the project retention policy."
BATCH_SIZE = 20
SYSTEM = Principal(kind="system", actor_id="retention-worker", display_name="Retention worker")


def lock_project(session: Session, project_id: str) -> m.Project:
    project = session.scalar(select(m.Project).where(m.Project.id == project_id)
                             .with_for_update().execution_options(populate_existing=True))
    if project is None:
        raise HTTPException(404, "project not found")
    return project


def policy_for(session: Session, project_id: str) -> m.RetentionPolicy:
    row = session.get(m.RetentionPolicy, project_id)
    if row is None:
        lock_project(session, project_id)
        row = session.get(m.RetentionPolicy, project_id, populate_existing=True)
        if row is None:
            row = m.RetentionPolicy(project_id=project_id)
            session.add(row)
            session.flush()
    return row


def _active_ingestion(session: Session, project_id: str) -> bool:
    return session.scalar(select(m.Job.id).where(m.Job.project_id == project_id,
        m.Job.kind != RETENTION_JOB_KIND, m.Job.state.in_([m.JobState.queued, m.JobState.running])).limit(1)) is not None


def _candidates(project_id: str, policy: m.RetentionPolicy, as_of: datetime):
    sources = select(m.Ingestion).where(m.Ingestion.project_id == project_id,
        m.Ingestion.source_expired_at.is_(None),
        m.Ingestion.created_at <= as_of - timedelta(days=policy.source_days),
        m.Ingestion.state.not_in([m.IngestionState.queued, m.IngestionState.running]))
    source_runs = select(m.Run).where(m.Run.project_id == project_id, m.Run.source_expired_at.is_(None),
        m.Run.created_at <= as_of - timedelta(days=policy.source_days),
        m.Run.status.not_in([m.RunStatus.queued, m.RunStatus.processing]))
    evidence = select(m.Run).where(m.Run.project_id == project_id, m.Run.evidence_expired_at.is_(None),
        m.Run.created_at <= as_of - timedelta(days=policy.evidence_days),
        m.Run.status.not_in([m.RunStatus.queued, m.RunStatus.processing]))
    audits = select(m.AuditEvent).where(m.AuditEvent.project_id == project_id,
        m.AuditEvent.created_at <= as_of - timedelta(days=policy.audit_days))
    return sources, source_runs, evidence, audits


def preview(session: Session, project_id: str, *, as_of: datetime | None = None,
            proposed: m.RetentionPolicy | None = None) -> RetentionPreview:
    policy = proposed or policy_for(session, project_id)
    now = as_utc(as_of) if as_of else m.utcnow()
    if now > m.utcnow() + timedelta(seconds=1):
        raise HTTPException(422, "retention cutoff cannot be in the future")
    queries = _candidates(project_id, policy, now)
    counts = [session.scalar(select(func.count()).select_from(q.subquery())) or 0 for q in queries]
    values = dict(project_id=project_id, policy_version=policy.version, as_of=now,
                  cutoff_source=now - timedelta(days=policy.source_days),
                  cutoff_evidence=now - timedelta(days=policy.evidence_days),
                  cutoff_audit=now - timedelta(days=policy.audit_days),
                  source_ingestions=counts[0], source_runs=counts[1], evidence_runs=counts[2],
                  audit_events=counts[3], blocked_by_ingestion=_active_ingestion(session, project_id),
                  sample_run_ids=list(session.scalars(queries[2].with_only_columns(m.Run.id)
                    .order_by(m.Run.created_at, m.Run.id).limit(BATCH_SIZE)).all()))
    # Preview identity includes actual affected IDs, not only counts. Stream IDs
    # instead of materializing all records; a changed candidate set invalidates it.
    digest = hashlib.sha256(json.dumps(values, default=str, sort_keys=True).encode())
    for query, model in zip(queries, (m.Ingestion, m.Run, m.Run, m.AuditEvent), strict=True):
        for ident in session.scalars(query.with_only_columns(model.id).order_by(model.id)
                                      .execution_options(yield_per=1000)):
            digest.update(f"{model.__tablename__}:{ident}\n".encode())
    return RetentionPreview(**values, confirmation_digest=digest.hexdigest())


def enqueue(session: Session, project_id: str, proof: RetentionPreview, principal: Principal) -> m.Job:
    lock_project(session, project_id)
    active = session.scalar(select(m.Job).where(m.Job.project_id == project_id, m.Job.kind == RETENTION_JOB_KIND,
        m.Job.state.in_([m.JobState.queued, m.JobState.running])).order_by(m.Job.created_at).limit(1))
    if active:
        return active
    job = m.Job(project_id=project_id, kind=RETENTION_JOB_KIND, state=m.JobState.queued,
        max_attempts=5, payload={"policy_version": proof.policy_version, "as_of": proof.as_of.isoformat(),
                               "progress": {}, "requested_by": principal.user_id})
    session.add(job)
    session.flush()
    record_audit_event(session, principal, project_id=project_id, action="retention.cleanup_queued",
        resource_type="job", resource_id=job.id, details={"policy_version": proof.policy_version})
    session.commit()
    return job


def _tombstone(session: Session, project_id: str, kind: str, ident: str, version: int) -> None:
    exists = session.scalar(select(m.RetentionTombstone.id).where(m.RetentionTombstone.project_id == project_id,
        m.RetentionTombstone.resource_type == kind, m.RetentionTombstone.resource_id == ident))
    if exists is None:
        session.add(m.RetentionTombstone(project_id=project_id, resource_type=kind,
                                         resource_id=ident, policy_version=version))


def _delete_later(session: Session, project_id: str, path: str) -> None:
    if path.startswith("db://"):
        return
    row = session.scalar(select(m.StorageDeletion).where(m.StorageDeletion.project_id == project_id,
                                                        m.StorageDeletion.storage_path == path))
    if row is None:
        session.add(m.StorageDeletion(project_id=project_id, storage_path=path))
    else:
        # A path may legitimately have been recreated by a later import.
        row.state, row.error_code, row.deleted_at = "pending", None, None


def _scrub_run(session: Session, run: m.Run, version: int) -> None:
    run.evidence_expired_at = m.utcnow()
    run.retention_policy_version = version
    run.source_metadata = {"retention_state": "expired"}
    failure_ids = select(m.Failure.id).where(m.Failure.run_id == run.id)
    analysis_ids = select(m.Analysis.id).where(m.Analysis.failure_id.in_(failure_ids))
    evidence_ids = select(m.Evidence.id).where(m.Evidence.run_id == run.id)
    # Do not alter recorded categories, outcomes, versions, reviewer identities or digests.
    session.execute(update(m.Evidence).where(m.Evidence.run_id == run.id).values(
        excerpt=EXPIRED, observation={}, locator={}, warnings=["evidence_expired"]))
    session.execute(update(m.TestExecution).where(m.TestExecution.run_id == run.id).values(details={}))
    session.execute(update(m.Failure).where(m.Failure.run_id == run.id).values(message=EXPIRED, loose_features={}))
    session.execute(update(m.RunInput).where(m.RunInput.run_id == run.id).values(metadata_json={}, warnings=["evidence_expired"]))
    session.execute(update(m.Artifact).where(m.Artifact.run_id == run.id).values(metadata_json={}))
    session.execute(update(m.Analysis).where(m.Analysis.failure_id.in_(failure_ids)).values(
        summary=EXPIRED, claims=[], hypotheses=[], confidence_explanation=EXPIRED,
        missing_evidence=["evidence_expired"], next_investigation=[], abstention_reason=EXPIRED,
        provenance={"retention_state": "expired"}, validation_results={"status": "expired"}))
    session.execute(update(m.ReviewEvent).where(m.ReviewEvent.analysis_id.in_(analysis_ids)).values(
        reason=EXPIRED, investigation_outcome=None, hypothesis_decisions=[]))
    session.execute(update(m.Ingestion).where(m.Ingestion.run_id == run.id).values(source_metadata={},
        diagnostics=[{"code": "evidence_expired"}], error_message=None))
    session.execute(update(m.ClusterMembership).where(m.ClusterMembership.failure_id.in_(failure_ids)).values(
        score_components={}, matching_signals=[], conflicting_signals=[], candidate_reasons=["evidence_expired"]))
    revision_ids = select(m.ClusterMembership.revision_id).where(m.ClusterMembership.failure_id.in_(failure_ids))
    cluster_ids = select(m.ClusterMembership.cluster_id).where(m.ClusterMembership.failure_id.in_(failure_ids))
    session.execute(update(m.ClusterRevision).where(m.ClusterRevision.id.in_(revision_ids)).values(score_summary={}, uncertainty_flags=["evidence_expired"]))
    # Other members' comparison explanations can quote the expiring member too.
    session.execute(update(m.ClusterMembership).where(m.ClusterMembership.revision_id.in_(revision_ids)).values(
        score_components={}, matching_signals=[], conflicting_signals=[], candidate_reasons=["evidence_expired"]))
    session.execute(update(m.ClusterMembershipDecision).where(m.ClusterMembershipDecision.cluster_id.in_(cluster_ids)).values(reason=EXPIRED))
    # Metadata derived from this run is also evidence, not an exemption from retention.
    recommendation_ids = select(m.ImpactRecommendation.id).where(m.ImpactRecommendation.run_id == run.id)
    session.execute(update(m.ImpactRecommendation).where(m.ImpactRecommendation.run_id == run.id).values(
        summary=EXPIRED, changed_files=[], safety_reasons=["evidence_expired"], metrics={}))
    session.execute(update(m.ImpactRecommendationItem).where(m.ImpactRecommendationItem.recommendation_id.in_(recommendation_ids)).values(
        reasons=[], reason_codes=["evidence_expired"], exclusion_reason=EXPIRED))
    session.execute(update(m.ImpactOverride).where(m.ImpactOverride.recommendation_id.in_(recommendation_ids)).values(reason=EXPIRED))
    session.execute(update(m.PerformanceObservation).where(m.PerformanceObservation.run_id == run.id).values(
        dimensions={}, threshold_details={}, source_locator={}))
    session.execute(update(m.PerformanceComparison).where(m.PerformanceComparison.current_run_id == run.id).values(
        summary=EXPIRED, uncertainty={}, compatibility={}, confounders=["evidence_expired"], next_measurement=EXPIRED))
    session.execute(update(m.PerformanceBaselineSnapshot).where(m.PerformanceBaselineSnapshot.current_run_id == run.id).values(
        cohort_dimensions={}, compatibility={}, rejected_candidates=[]))
    session.execute(update(m.InfrastructureEvent).where(m.InfrastructureEvent.evidence_id.in_(evidence_ids)).values(metadata_json={}))
    # Review/audit text may quote evidence. Clear only this run's related events,
    # leaving their actor, action, resource, timestamp and structured decision records.
    review_ids = select(m.ReviewEvent.id).where(m.ReviewEvent.analysis_id.in_(analysis_ids))
    session.execute(update(m.AuditEvent).where(m.AuditEvent.project_id == run.project_id,
        or_(m.AuditEvent.resource_id == run.id, m.AuditEvent.resource_id.in_(review_ids),
            m.AuditEvent.resource_id.in_(analysis_ids))).values(reason=EXPIRED, details={"retention_state": "expired"}))
    for derivative in session.scalars(select(m.ArtifactDerivative).where(m.ArtifactDerivative.run_id == run.id)):
        derivative.retention_state = "expired"
        derivative.source_map, derivative.metadata_json = {}, {}
        _delete_later(session, run.project_id, derivative.storage_path)
        _tombstone(session, run.project_id, "derivative", derivative.id, version)
    _tombstone(session, run.project_id, "run_evidence", run.id, version)


def _has_live_reference(session: Session, path: str) -> bool:
    # Check globally too: corrupt cross-project references must protect bytes, not delete them.
    return any(session.scalar(q.limit(1)) is not None for q in (
        select(m.ArtifactDerivative.id).where(m.ArtifactDerivative.storage_path == path,
                                             m.ArtifactDerivative.retention_state == "active"),
        select(m.Ingestion.id).where(m.Ingestion.storage_path == path, m.Ingestion.source_expired_at.is_(None)),
        select(m.Artifact.id).join(m.Run).where(m.Artifact.safe_storage_path == path, m.Run.source_expired_at.is_(None)),
    ))


def flush_deletions(session: Session, project_id: str, settings: Settings, limit: int = 100) -> int:
    lock_project(session, project_id)
    if _active_ingestion(session, project_id):
        session.commit()
        return 0
    removed = 0
    rows = list(session.scalars(select(m.StorageDeletion).where(m.StorageDeletion.project_id == project_id,
        m.StorageDeletion.state == "pending").order_by(m.StorageDeletion.created_at, m.StorageDeletion.id).limit(limit)))
    for row in rows:
        parts = PurePosixPath(row.storage_path).parts
        if (len(parts) != 5 or parts[0] not in {"sources", "derivatives"} or parts[1] != project_id
                or ".." in parts or PurePosixPath(row.storage_path).is_absolute()):
            row.state, row.error_code = "blocked", "unsafe_storage_path"
            continue
        if _has_live_reference(session, row.storage_path):
            row.state, row.error_code = "retained_reference", "active_reference"
            continue
        # Reject symlinks even if they resolve to another valid project path.
        candidate = settings.artifact_root
        if any((settings.artifact_root.joinpath(*parts[:i])).is_symlink() for i in range(1, len(parts)+1)):
            row.state, row.error_code = "blocked", "unsafe_storage_path"
            continue
        candidate = _resolve_under(settings.artifact_root, row.storage_path)
        candidate.unlink(missing_ok=True)
        row.state, row.error_code, row.deleted_at = "deleted", None, m.utcnow()
        removed += 1
    session.commit()
    return removed


def process_cleanup(session: Session, job: m.Job, worker_id: str, settings: Settings) -> None:
    lock_project(session, job.project_id)
    session.refresh(job, with_for_update=True)
    if job.state != m.JobState.running or job.lease_owner != worker_id:
        raise RuntimeError("retention job lease is no longer owned")
    if job.lease_expires_at is None or as_utc(job.lease_expires_at) <= m.utcnow():
        raise RuntimeError("retention lease expired")
    policy = policy_for(session, job.project_id)
    if policy.version != job.payload["policy_version"]:
        job.state, job.last_error = m.JobState.cancelled, "policy_version_changed"
        job.lease_owner = job.lease_expires_at = None
        session.commit()
        return
    if _active_ingestion(session, job.project_id):
        job.state, job.available_at = m.JobState.queued, m.utcnow() + timedelta(seconds=30)
        job.lease_owner = job.lease_expires_at = None
        job.attempts = 0
        session.commit()
        return
    as_of = as_utc(datetime.fromisoformat(job.payload["as_of"]))
    queries = _candidates(job.project_id, policy, as_of)
    progress = dict(job.payload.get("progress", {}))
    for label, query, model in zip(("source_ingestions", "source_runs", "evidence_runs", "audit_events"),
                                   queries, (m.Ingestion, m.Run, m.Run, m.AuditEvent), strict=True):
        rows = list(session.scalars(query.order_by(model.created_at, model.id).limit(BATCH_SIZE)))
        for row in rows:
            if label == "source_ingestions":
                row.source_expired_at = m.utcnow()
                _delete_later(session, job.project_id, row.storage_path)
                _tombstone(session, job.project_id, "ingestion_source", row.id, policy.version)
            elif label == "source_runs":
                row.source_expired_at = m.utcnow()
                for artifact in session.scalars(select(m.Artifact).where(m.Artifact.run_id == row.id)):
                    _delete_later(session, job.project_id, artifact.safe_storage_path)
                _tombstone(session, job.project_id, "run_source", row.id, policy.version)
            elif label == "evidence_runs":
                _scrub_run(session, row, policy.version)
            else:
                _tombstone(session, job.project_id, "audit_event", row.id, policy.version)
                session.delete(row)
        progress[label] = progress.get(label, 0) + len(rows)
    job.payload = {**job.payload, "progress": progress}
    session.flush()
    remaining = any(session.scalar(q.with_only_columns(model.id).limit(1)) is not None
                    for q, model in zip(queries, (m.Ingestion, m.Run, m.Run, m.AuditEvent), strict=True))
    job.lease_expires_at = m.utcnow() + timedelta(seconds=settings.job_lease_seconds)
    # Logical expiry/outbox commits before the first unlink: crash recovery cannot
    # republish a file whose bytes have disappeared.
    session.commit()
    removed = flush_deletions(session, job.project_id, settings)
    session.refresh(job, with_for_update=True)
    if job.state != m.JobState.running or job.lease_owner != worker_id:
        raise RuntimeError("retention job lease is no longer owned")
    progress = {**job.payload.get("progress", {})}
    progress["files_deleted"] = progress.get("files_deleted", 0) + removed
    remaining = remaining or session.scalar(select(m.StorageDeletion.id).where(m.StorageDeletion.project_id == job.project_id,
                                               m.StorageDeletion.state == "pending").limit(1)) is not None
    job.payload = {**job.payload, "progress": progress}
    blocked = session.scalar(select(func.count()).select_from(m.StorageDeletion).where(
        m.StorageDeletion.project_id == job.project_id, m.StorageDeletion.state == "blocked")) or 0
    progress["blocked_deletions"] = blocked
    job.payload = {**job.payload, "progress": progress}
    job.state = m.JobState.queued if remaining else m.JobState.partial if blocked else m.JobState.succeeded
    job.last_error = "unsafe_storage_path" if blocked else None
    job.attempts = 0 if remaining else job.attempts
    job.available_at = m.utcnow()
    job.lease_owner = job.lease_expires_at = None
    if not remaining:
        record_audit_event(session, SYSTEM, project_id=job.project_id, action="retention.cleanup_completed",
            resource_type="job", resource_id=job.id, details=progress, outcome="partial" if blocked else "success")
    session.commit()


def schedule_due(session: Session) -> None:
    """Bounded round-robin sweep; empty projects do not accumulate no-op jobs."""
    due = m.utcnow() - timedelta(minutes=5)
    projects = list(session.scalars(select(m.Project.id).outerjoin(m.RetentionPolicy,
        m.RetentionPolicy.project_id == m.Project.id).where(or_(m.RetentionPolicy.last_scanned_at.is_(None),
        m.RetentionPolicy.last_scanned_at <= due)).order_by(m.RetentionPolicy.last_scanned_at.asc().nullsfirst(),
        m.Project.id).limit(10)))
    for project_id in projects:
        lock_project(session, project_id)
        policy = policy_for(session, project_id)
        session.refresh(policy, with_for_update=True)
        if policy.last_scanned_at and as_utc(policy.last_scanned_at) > due:
            session.commit()
            continue
        proof = preview(session, project_id)
        policy.last_scanned_at = m.utcnow()
        pending = session.scalar(select(m.StorageDeletion.id).where(m.StorageDeletion.project_id == project_id,
            m.StorageDeletion.state == "pending").limit(1)) is not None
        if proof.source_ingestions or proof.source_runs or proof.evidence_runs or proof.audit_events or pending:
            enqueue(session, project_id, proof, SYSTEM)
        session.commit()
