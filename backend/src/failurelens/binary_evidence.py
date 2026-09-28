"""Input-scoped reviewed images and immutable, non-executable trace evidence."""
from __future__ import annotations

import hashlib
import json
from typing import Any
from pathlib import PurePosixPath

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal, record_audit_event, require_project_role
from .binary_schemas import (BinaryDecisionCreate, BinaryDecisionRead, BinaryEvidenceRead,
                             ImageComparisonRead, ScreenshotReview)
from .config import Settings, get_settings
from .image_codec import ImageCodecError, decode_image
from . import models as m
from .redaction import REDACTION_VERSION, redact_text
from .retention import lock_project
from .schemas import ArtifactDerivativeSummary
from .storage import StorageError, read_stored_bytes, store_derivative_bytes

BINARY_KINDS = {"screenshot", "playwright-trace"}
BINARY_POLICY = "discard-binary-originals-after-processing-v1"


def _error(code: str, message: str, status: int = 422) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


def _expired(run: m.Run) -> None:
    if run.evidence_expired_at is not None:
        raise _error("evidence_expired", "Evidence expired under project retention policy.", 410)


def _correlate(session: Session, run: m.Run, item: m.RunInput) -> tuple[str | None, str]:
    metadata = item.metadata_json
    declared_path = metadata.get("producer_attachment_path") or item.path
    candidates = []
    for execution in session.scalars(select(m.TestExecution).where(m.TestExecution.run_id == run.id)):
        attachments = execution.details.get("attachments", [])
        path_matches = any(isinstance(a, dict) and a.get("path") == declared_path for a in attachments)
        explicit = (isinstance(metadata.get("test_identity"), str)
                    and type(metadata.get("attempt")) is int and isinstance(metadata.get("browser"), str)
                    and execution.test_identity == metadata["test_identity"]
                    and execution.attempt == metadata["attempt"] and execution.browser == metadata["browser"])
        # Supplied dimensions constrain a path match; contradictory declarations fail closed.
        compatible = all(metadata.get(key) is None or metadata[key] == getattr(execution, key)
                         for key in ("test_identity", "attempt", "browser"))
        if compatible and (path_matches or explicit):
            candidates.append((execution.id, "report_attachment" if path_matches else "explicit_self_reported"))
    return candidates[0] if len(candidates) == 1 else (None, "ambiguous" if candidates else "unassociated")


def _store_derivative(session: Session, state: m.BinaryEvidence, content: bytes, *, kind: str,
                      media_type: str, source_map: dict[str, Any], metadata: dict[str, Any],
                      settings: Settings, approval: str = "reviewed") -> m.ArtifactDerivative:
    artifact = session.get(m.Artifact, state.artifact_id)
    if artifact is None:
        raise _error("source_unavailable", "Source identity is unavailable", 409)
    digest = hashlib.sha256(content).hexdigest()
    filename = f"{digest}.{'png' if media_type == 'image/png' else 'json'}"
    stored = store_derivative_bytes(content, root=settings.artifact_root, project_id=state.project_id,
                                    filename=filename, media_type=media_type, max_bytes=settings.max_file_bytes)
    row = m.ArtifactDerivative(project_id=state.project_id, run_id=state.run_id,
        artifact_id=state.artifact_id, kind=kind, digest=digest, source_digest=artifact.digest,
        storage_path=stored.relative_path, media_type=media_type, size_bytes=stored.size_bytes,
        redaction_version=REDACTION_VERSION, source_map=source_map, approved=True, restricted=False,
        approval_state=approval, retention_state="active", metadata_json=metadata)
    session.add(row)
    session.flush()
    return row


def register_binary_inputs(session: Session, project: m.Project, run: m.Run,
                           source_artifact: m.Artifact, settings: Settings) -> None:
    """Called in the ingestion transaction after test executions exist. No raw bytes persist here."""
    from .service import _get_or_create_text_derivative
    inputs = session.scalars(select(m.RunInput).where(m.RunInput.run_id == run.id,
                                                      m.RunInput.kind.in_(BINARY_KINDS)))
    for item in inputs:
        if session.get(m.BinaryEvidence, item.id):
            continue
        artifact = source_artifact
        if item.digest:
            artifact = m.Artifact(run_id=run.id, kind=f"binary-input-{item.id}", original_name=item.path or item.input_id,
                digest=item.digest, safe_storage_path=f"db://binary-source-not-retained/{item.id}",
                size_bytes=item.size_bytes or 0, media_type=item.media_type, redaction_version=REDACTION_VERSION,
                restricted=True, metadata_json={"input_id": item.id, "original_policy": BINARY_POLICY})
            session.add(artifact)
            session.flush()
        execution_id, correlation = _correlate(session, run, item)
        state = m.BinaryEvidence(input_id=item.id, project_id=project.id, run_id=run.id,
            artifact_id=artifact.id, execution_id=execution_id, correlation=correlation,
            version=0, state="restricted" if item.status == "restricted" else item.status)
        session.add(state)
        session.flush()
        if item.kind != "playwright-trace" or item.status != "restricted":
            continue
        # Only a successfully version-validated parser may supply an approved index.
        if item.parser_version != "playwright-safe-index-v2":
            continue
        events = item.metadata_json.get("events", [])
        safe_events = []
        for event in events:
            observation = {"kind": "trace_event", "event": event["event"]}
            derivative = _get_or_create_text_derivative(session, project=project, run=run, artifact=artifact,
                source_locator=event["source_locator"], excerpt=event["text"], observation=observation,
                redaction_classes={"trace_allowlist"}, settings=settings)
            evidence = m.Evidence(project_id=project.id, run_id=run.id, artifact_id=artifact.id,
                run_input_id=item.id, execution_id=execution_id, derivative_id=derivative.id,
                kind="trace_event", provenance_kind="supplemental_trace",
                locator_version="evidence-locator-v2", locator={"version": "evidence-locator-v2",
                    "source": event["source_locator"], "derivative": {"kind": "json-pointer", "pointer": "/excerpt"}},
                excerpt=event["text"], observation=observation, content_digest=derivative.digest,
                parser_version=item.parser_version, extractor_version="trace-allowlist-v2",
                redaction_version=REDACTION_VERSION, warnings=["supplemental_not_root_cause_proof"])
            session.add(evidence)
            session.flush()
            safe_events.append({**event, "evidence_id": evidence.id,
                                "evidence_derivative_id": derivative.id, "evidence_digest": derivative.digest})
        index = {"schema_version": "failurelens-safe-trace-2.0", "input_id": item.id,
                 "source_digest": item.digest, "summary": {k: v for k, v in item.metadata_json.items() if k != "events"},
                 "events": safe_events}
        content = (json.dumps(index, sort_keys=True, ensure_ascii=False) + "\n").encode()
        derivative = _store_derivative(session, state, content, kind="safe-trace-index-v2",
            media_type="application/json", source_map={"version": "trace-source-map-v2", "input_id": item.id,
                "source_digest": item.digest, "events": "each /events/N/source_locator"},
            metadata={"index_version": "playwright-safe-index-v2", "indexed_events": len(safe_events)},
            settings=settings, approval="auto_approved_text")
        state.current_derivative_id, state.state = derivative.id, "safe_index_available"
        # Avoid a second, ungoverned copy of the evidence in the run-input metadata API.
        item.metadata_json = {k: v for k, v in item.metadata_json.items() if k != "events"}


def get_state(session: Session, principal: Principal, input_id: str, *, review: bool = False) -> m.BinaryEvidence:
    state = session.get(m.BinaryEvidence, input_id)
    if state is None:
        raise HTTPException(404, "binary evidence not found")
    role = m.ProjectRole.reviewer if review else m.ProjectRole.viewer
    require_project_role(session, principal, state.project_id, role)
    if review:
        lock_project(session, state.project_id)
        state = session.scalar(select(m.BinaryEvidence).where(m.BinaryEvidence.input_id == input_id)
                               .with_for_update().execution_options(populate_existing=True))
        require_project_role(session, principal, state.project_id, role)
    run = session.get(m.Run, state.run_id, populate_existing=True)
    if run is None or run.project_id != state.project_id:
        raise HTTPException(404, "binary evidence not found")
    _expired(run)
    return state


def derivative_summary(row: m.ArtifactDerivative) -> ArtifactDerivativeSummary:
    return ArtifactDerivativeSummary(**{key: getattr(row, key) for key in ArtifactDerivativeSummary.model_fields})


def to_schema(session: Session, state: m.BinaryEvidence, *, decision_offset: int = 0) -> BinaryEvidenceRead:
    item = session.get(m.RunInput, state.input_id)
    run = session.get(m.Run, state.run_id)
    expired = run is None or run.evidence_expired_at is not None
    metadata = {} if expired else item.metadata_json
    derivative = session.get(m.ArtifactDerivative, state.current_derivative_id) if state.current_derivative_id else None
    decisions_query = select(m.BinaryEvidenceDecision).where(m.BinaryEvidenceDecision.input_id == state.input_id)
    decisions = list(session.scalars(decisions_query.order_by(m.BinaryEvidenceDecision.version.desc()).limit(20).offset(decision_offset)))
    return BinaryEvidenceRead(input_id=item.id, manifest_input_id=item.input_id, project_id=state.project_id,
        run_id=state.run_id, kind=item.kind, path=item.path, source_digest=item.digest, source_bytes=item.size_bytes,
        source_status=item.status, state="expired" if expired else state.state, version=state.version,
        execution_id=state.execution_id, correlation=state.correlation,
        relationship=metadata.get("relationship") if isinstance(metadata.get("relationship"), str) and metadata.get("relationship") in {"expected", "actual", "diff"} else None,
        width=metadata.get("width") if type(metadata.get("width")) is int else None,
        height=metadata.get("height") if type(metadata.get("height")) is int else None,
        coordinate_system=metadata.get("coordinate_system") if isinstance(metadata.get("coordinate_system"), str) else None,
        comparison_context=metadata.get("comparison_context", {}) if isinstance(metadata.get("comparison_context"), dict) else {},
        derivative=derivative_summary(derivative) if derivative else None,
        warnings=["evidence_expired"] if expired else item.warnings,
        decisions=[BinaryDecisionRead.model_validate(row) for row in decisions],
        decisions_total=session.scalar(select(func.count()).select_from(decisions_query.subquery())) or 0)


def _decision(session: Session, principal: Principal, state: m.BinaryEvidence, *, decision: str,
              reason: str, masks: list[dict[str, int]], derivative_id: str | None) -> None:
    safe_reason = redact_text(reason.strip()).text
    if len(safe_reason) < 10:
        raise _error("reason_required", "Provide a substantive review reason")
    state.version += 1
    session.add(m.BinaryEvidenceDecision(input_id=state.input_id, project_id=state.project_id,
        derivative_id=derivative_id, version=state.version, decision=decision,
        actor_id=principal.actor_id or "unknown", actor_display=principal.display_name,
        reason=safe_reason, masks=masks))
    record_audit_event(session, principal, project_id=state.project_id, action=f"binary_evidence.{decision}",
        resource_type="run", resource_id=state.run_id, reason=safe_reason,
        details={"input_id": state.input_id, "derivative_id": derivative_id, "version": state.version})


def review_screenshot(session: Session, principal: Principal, input_id: str, options: ScreenshotReview,
                      content: bytes, settings: Settings | None = None) -> BinaryEvidenceRead:
    settings = settings or get_settings()
    state = get_state(session, principal, input_id, review=True)
    item = session.get(m.RunInput, input_id)
    if item.kind != "screenshot" or item.status != "restricted":
        raise _error("input_not_reviewable", "Only validated screenshot inputs can be reviewed", 409)
    if state.version != options.expected_version:
        raise _error("version_conflict", "Review changed; reload before submitting", 409)
    if hashlib.sha256(content).hexdigest() != item.digest or len(content) != item.size_bytes:
        raise _error("source_digest_mismatch", "Select the exact original image for this input", 409)
    masks = [mask.model_dump() for mask in options.masks]
    try:
        metadata, png = decode_image(content, settings, masks=masks, encode=True)
    except ImageCodecError as exc:
        raise _error(exc.code, "Image review failed safely") from exc
    if (metadata["width"], metadata["height"]) != (item.metadata_json.get("width"), item.metadata_json.get("height")):
        raise _error("dimension_mismatch", "Image dimensions do not match the validated source", 409)
    derivative = _store_derivative(session, state, png, kind=f"reviewed-screenshot-v{state.version + 1}",
        media_type="image/png", source_map={"version": "image-source-map-v1", "input_id": item.id,
            "source_digest": item.digest, "coordinate_system": metadata["coordinate_system"], "masks": masks,
            "transforms": ["EXIF orientation normalized", "alpha flattened", "metadata stripped", "solid pixel masks"]},
        metadata={**metadata, "masks": masks, "comparison_context": item.metadata_json.get("comparison_context", {}),
                  "input_id": item.id}, settings=settings)
    state.current_derivative_id, state.state = derivative.id, "approved"
    _decision(session, principal, state, decision="approve", reason=options.reason, masks=masks, derivative_id=derivative.id)
    session.commit()
    return to_schema(session, state)


def decide(session: Session, principal: Principal, input_id: str, options: BinaryDecisionCreate) -> BinaryEvidenceRead:
    state = get_state(session, principal, input_id, review=True)
    if state.version != options.expected_version:
        raise _error("version_conflict", "Review changed; reload before submitting", 409)
    item = session.get(m.RunInput, input_id)
    artifact = session.get(m.Artifact, state.artifact_id)
    if item.status != "restricted" or artifact is None or artifact.kind != f"binary-input-{input_id}":
        raise _error("input_not_reviewable", "Only validated binary inputs have review decisions", 409)
    derivative_id = state.current_derivative_id
    # Revoke all historical copies for this input, including extracted event JSON.
    # Re-approval creates a new version; it cannot reopen a revoked URL.
    for derivative in session.scalars(select(m.ArtifactDerivative).where(m.ArtifactDerivative.artifact_id == state.artifact_id)):
        derivative.approved, derivative.restricted, derivative.approval_state = False, True, "revoked"
    state.current_derivative_id, state.state = None, "rejected" if options.decision == "reject" else "revoked"
    _decision(session, principal, state, decision=options.decision, reason=options.reason, masks=[], derivative_id=derivative_id)
    session.commit()
    return to_schema(session, state)


def read_derivative(session: Session, principal: Principal, derivative_id: str,
                    settings: Settings | None = None) -> tuple[m.ArtifactDerivative, bytes]:
    settings = settings or get_settings()
    row = session.get(m.ArtifactDerivative, derivative_id)
    if row is None:
        raise HTTPException(404, "artifact derivative not found")
    require_project_role(session, principal, row.project_id)
    run, artifact = session.get(m.Run, row.run_id), session.get(m.Artifact, row.artifact_id)
    if run is None or artifact is None or run.project_id != row.project_id or artifact.run_id != run.id:
        raise HTTPException(404, "artifact derivative not found")
    _expired(run)
    if row.retention_state != "active":
        raise _error("evidence_expired", "Artifact derivative is unavailable", 410)
    if not row.approved or row.restricted or row.approval_state not in {"reviewed", "auto_approved_text"}:
        raise _error("artifact_restricted", "Artifact derivative is not approved", 403)
    if row.source_digest != artifact.digest:
        raise _error("source_digest_mismatch", "Artifact source identity failed validation", 409)
    allowed = row.media_type in {"application/json", "application/vnd.failurelens.evidence+json", "text/plain"}
    allowed = allowed or (row.media_type == "image/png" and row.kind.startswith("reviewed-screenshot-v"))
    if not allowed:
        raise _error("unsupported_derivative", "Artifact type is not approved for serving", 403)
    parts = PurePosixPath(row.storage_path).parts
    if len(parts) < 5 or parts[:2] != ("derivatives", row.project_id) or ".." in parts:
        raise _error("artifact_integrity_failed", "Artifact storage scope failed validation", 409)
    # Re-resolve inside the owning namespace to reject a symlink into another project.
    namespace = (settings.artifact_root / "derivatives" / row.project_id).resolve()
    try:
        (settings.artifact_root / row.storage_path).resolve().relative_to(namespace)
    except ValueError as exc:
        raise _error("artifact_integrity_failed", "Artifact storage scope failed validation", 409) from exc
    try:
        content = read_stored_bytes(root=settings.artifact_root, relative_path=row.storage_path,
            expected_digest=row.digest, expected_size=row.size_bytes, max_bytes=settings.max_file_bytes)
    except (StorageError, OSError) as exc:
        raise _error("artifact_integrity_failed", "Artifact bytes are missing or failed integrity validation", 409) from exc
    return row, content


def compare_images(session: Session, principal: Principal, expected_id: str, actual_id: str) -> ImageComparisonRead:
    first, first_bytes = read_derivative(session, principal, expected_id)
    second, second_bytes = read_derivative(session, principal, actual_id)
    if first.project_id != second.project_id:
        raise HTTPException(404, "image comparison not found")
    states = [session.scalar(select(m.BinaryEvidence).where(m.BinaryEvidence.current_derivative_id == ident))
              for ident in (expected_id, actual_id)]
    reasons = []
    if not all(states) or any(row.media_type != "image/png" for row in (first, second)):
        raise _error("not_current_approved_images", "Comparison requires current approved screenshots", 409)
    items = [session.get(m.RunInput, state.input_id) for state in states]
    if items[0].metadata_json.get("relationship") != "expected" or items[1].metadata_json.get("relationship") != "actual":
        reasons.append("expected_actual_relationship_required")
    contexts = [item.metadata_json.get("comparison_context", {}) for item in items]
    dimensions = ("browser", "os", "viewport_width", "viewport_height", "device_scale_factor", "comparison_group")
    def valid_dimension(context: Any, key: str) -> bool:
        if not isinstance(context, dict):
            return False
        value = context.get(key)
        if key in {"viewport_width", "viewport_height"}:
            return type(value) is int and 0 < value <= 100_000
        if key == "device_scale_factor":
            return type(value) in {int, float} and 0 < value <= 10
        return isinstance(value, str) and 0 < len(value.strip()) <= 200
    missing = [key for key in dimensions if any(not valid_dimension(c, key) for c in contexts)]
    if missing:
        reasons.extend(f"missing_{key}" for key in missing)
    else:
        reasons.extend(f"incompatible_{key}" for key in dimensions if contexts[0][key] != contexts[1][key])
    if (first.metadata_json.get("width"), first.metadata_json.get("height")) != (
            second.metadata_json.get("width"), second.metadata_json.get("height")):
        reasons.append("incompatible_dimensions")
    # Correlation must be explicit and unambiguous, not a shared filename or label.
    if not states[0].execution_id or states[0].execution_id != states[1].execution_id:
        reasons.append("same_execution_required")
    # This version compares an expected/actual pair within a single test attempt.
    if first.run_id != second.run_id:
        reasons.append("different_run")
    similarity = distance = None
    status = "INSUFFICIENT_CONTEXT" if missing else "INCOMPATIBLE" if reasons else "COMPARABLE"
    if status == "COMPARABLE":
        settings = get_settings()
        try:
            a, _ = decode_image(first_bytes, settings)
            b, _ = decode_image(second_bytes, settings)
        except ImageCodecError as exc:
            raise _error(exc.code, "Approved image could not be decoded", 409) from exc
        distance = (int(a["dhash"], 16) ^ int(b["dhash"], 16)).bit_count()
        similarity = 1 - distance / 64
    return ImageComparisonRead(status=status, reasons=reasons, expected_derivative_id=expected_id,
        actual_derivative_id=actual_id, similarity=similarity, hamming_distance=distance)


def discard_binary_source(session: Session, ingestion: m.Ingestion, run: m.Run) -> None:
    """Transactional deletion outbox. Safe derivatives survive deletion of raw bundles."""
    from .retention import _delete_later
    if session.scalar(select(m.RunInput.id).where(m.RunInput.run_id == run.id, m.RunInput.kind.in_(BINARY_KINDS)).limit(1)) is None:
        return
    if ingestion.source_expired_at is not None:
        return
    now = m.utcnow()
    # Bytes may be shared by idempotent or distinct-attempt imports. The outbox checks
    # every live reference before unlinking, and the final consumer reschedules it.
    ingestion.source_expired_at, run.source_expired_at = now, now
    _delete_later(session, run.project_id, ingestion.storage_path)
    run.source_metadata = {**run.source_metadata, "binary_original_policy": BINARY_POLICY}
    record_audit_event(session, Principal(kind="system", actor_id="ingestion-worker", display_name="Ingestion worker"),
        project_id=run.project_id, action="binary_evidence.original_discard_scheduled", resource_type="run",
        resource_id=run.id, details={"policy": BINARY_POLICY, "source_digest": ingestion.source_digest})
