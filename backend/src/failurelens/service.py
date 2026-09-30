from __future__ import annotations

import hashlib
import json
from dataclasses import replace
import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .analysis import ANALYSIS_VERSION, RULES_VERSION, analyze_failure, input_digest
from .auth import Principal, record_audit_event
from .clustering import cluster_project_failures
from .config import Settings, get_settings
from .evidence_validation import (
    VALIDATION_VERSION,
    persisted_analysis_is_publication_validated,
    validate_decision,
    validate_evidence_records,
    validated_evidence_views,
)
from .fingerprint import make_fingerprint
from .history import history_context_for_failure
from .ingestion import (
    PARSER_VERSION,
    ParsedArtifact,
    ParsedInput,
    ParsedObservation,
    parse_artifact,
)
from .models import (
    Analysis,
    Artifact,
    ArtifactDerivative,
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
    RunInput,
    RunStatus,
    TestExecution,
)
from .performance import (
    build_observation_dimensions,
    infer_metric_direction,
    register_performance_observation,
)
from .redaction import REDACTION_VERSION, redact_sensitive_field, redact_text
from .telemetry import instrument, trace_context
from .schemas import AnalysisResult, Confidence, IngestionRequest, ReviewCreate, RunMetadata
from .storage import (
    StoredUpload,
    read_stored_bytes,
    store_derivative_bytes,
)

INGEST_JOB_KIND = "ingest_and_analyze_v1"
ARTIFACT_POLICY_VERSION = "artifact-policy-v1"
MAX_PERSISTED_PERFORMANCE_OBSERVATIONS = 20_000
MAX_PERFORMANCE_VALUES_PER_METRIC = 32


def _performance_statistic(value: str) -> str:
    normalized = value.strip().casefold()
    aliases = {"med": "median", "mean": "avg"}
    if normalized in aliases:
        return aliases[normalized]
    percentile = re.fullmatch(r"p\((\d+(?:\.\d+)?)\)", normalized)
    if percentile:
        return "p" + percentile.group(1).replace(".", "_")
    return normalized[:80] or "value"


def _performance_unit(
    *, metric_name: str, metric_type: str | None, contains: str | None, statistic: str
) -> str:
    contains_value = (contains or "").casefold()
    type_value = (metric_type or "").casefold()
    lowered_name = metric_name.casefold()
    if statistic in {"count", "passes", "fails"}:
        return "count"
    if contains_value == "time":
        return "ms"
    if contains_value == "data":
        return "B"
    if statistic == "rate" and type_value == "counter":
        if "req" in lowered_name or "request" in lowered_name:
            return "requests/s"
        if "iteration" in lowered_name:
            return "iterations/s"
        return "events/s"
    if type_value == "rate" or statistic == "rate":
        return "ratio"
    return "unknown"


def _metric_threshold_status(thresholds: dict[str, Any]) -> str:
    values = [value for value in thresholds.values() if isinstance(value, bool)]
    if any(value is False for value in values):
        return "failed"
    if values and all(values):
        return "passed"
    return "unknown"


def _json_pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _persist_performance_observations(
    session: Session,
    *,
    project: Project,
    run: Run,
    artifact: Artifact,
    input_records: Sequence[ParsedInput],
    run_inputs_by_input_id: dict[str, RunInput],
    settings: Settings,
) -> None:
    """Persist bounded, evidence-linked performance observations for one run."""

    persisted = 0
    truncated = False
    executions = list(
        session.scalars(
            select(TestExecution)
            .where(
                TestExecution.run_id == run.id,
                TestExecution.duration_ms.is_not(None),
            )
            .order_by(
                TestExecution.test_identity,
                TestExecution.browser,
                TestExecution.attempt.desc(),
                TestExecution.id.desc(),
            )
        ).all()
    )
    final_executions: dict[tuple[str, str | None], TestExecution] = {}
    for execution in executions:
        final_executions.setdefault((execution.test_identity, execution.browser), execution)
    evidence_rows = list(
        session.scalars(
            select(Evidence).where(
                Evidence.run_id == run.id,
                Evidence.execution_id.in_([item.id for item in final_executions.values()]),
            )
        ).all()
    ) if final_executions else []
    evidence_by_execution = {
        item.execution_id: item for item in evidence_rows if item.execution_id is not None
    }
    for execution in final_executions.values():
        evidence = evidence_by_execution.get(execution.id)
        if evidence is None or execution.duration_ms is None:
            continue
        input_id = str((execution.details or {}).get("input_id") or "input-1")
        run_input = run_inputs_by_input_id.get(input_id)
        producer = str((execution.details or {}).get("producer") or run.framework)
        producer_version = run_input.parser_version if run_input else None
        workload = execution.test_identity
        dimensions = build_observation_dimensions(
            run,
            workload=workload,
            browser=execution.browser,
            producer=producer,
            producer_version=producer_version,
            extra={
                "suite": execution.suite,
                "source_path": execution.source_path,
                "parameterization": execution.parameterization,
            },
        )
        register_performance_observation(
            session,
            project_id=project.id,
            run=run,
            run_input_id=run_input.id if run_input else None,
            execution_id=execution.id,
            evidence_id=evidence.id,
            metric_name="test.duration",
            metric_scope="test_duration",
            statistic="duration",
            original_value=execution.duration_ms,
            original_unit="ms",
            sample_count=1,
            producer=producer,
            producer_version=producer_version,
            workload=workload,
            dimensions=dimensions,
            threshold_status="unknown",
            threshold_details={},
            source_digest=run_input.digest if run_input and run_input.digest else artifact.digest,
            source_locator=evidence.locator,
            direction="lower_is_better",
            observed_at=run.started_at or run.created_at,
        )
        persisted += 1
        if persisted >= MAX_PERSISTED_PERFORMANCE_OBSERVATIONS:
            truncated = True
            break

    for item in input_records:
        if persisted >= MAX_PERSISTED_PERFORMANCE_OBSERVATIONS:
            truncated = True
            break
        if item.kind != "k6-summary-json" or item.status not in {"accepted", "restricted"}:
            continue
        metrics = item.metadata.get("metrics")
        if not isinstance(metrics, dict):
            continue
        run_input = run_inputs_by_input_id.get(item.input_id)
        if run_input is None:
            continue
        producer = str(item.metadata.get("producer") or "k6-handleSummary")
        producer_version = str(
            item.metadata.get("producer_version")
            or (run.source_metadata or {}).get("k6_version")
            or ""
        ) or None
        workload = str(
            item.metadata.get("workload")
            or item.metadata.get("scenario")
            or (run.source_metadata or {}).get("workload")
            or "default"
        )[:512]
        state = item.metadata.get("state") if isinstance(item.metadata.get("state"), dict) else {}
        for metric_name, metric in sorted(metrics.items()):
            if persisted >= MAX_PERSISTED_PERFORMANCE_OBSERVATIONS:
                truncated = True
                break
            if not isinstance(metric, dict):
                continue
            values = metric.get("values") if isinstance(metric.get("values"), dict) else {}
            thresholds = metric.get("thresholds") if isinstance(metric.get("thresholds"), dict) else {}
            metric_type = str(metric.get("type") or "") or None
            contains = str(metric.get("contains") or "") or None
            numeric_values = [
                (str(key), float(value))
                for key, value in values.items()
                if isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
            ][:MAX_PERFORMANCE_VALUES_PER_METRIC]
            sample_count_value = values.get("count")
            sample_count = (
                int(sample_count_value)
                if isinstance(sample_count_value, (int, float))
                and not isinstance(sample_count_value, bool)
                and sample_count_value >= 0
                else None
            )
            threshold_status = _metric_threshold_status(thresholds)
            for value_name, value in numeric_values:
                if persisted >= MAX_PERSISTED_PERFORMANCE_OBSERVATIONS:
                    truncated = True
                    break
                statistic = _performance_statistic(value_name)
                unit = _performance_unit(
                    metric_name=str(metric_name),
                    metric_type=metric_type,
                    contains=contains,
                    statistic=statistic,
                )
                source_locator = {
                    "kind": "json-pointer",
                    "input_id": item.input_id,
                    "input_path": item.path,
                    "pointer": (
                        f"/metrics/{_json_pointer_escape(str(metric_name))}/values/"
                        f"{_json_pointer_escape(value_name)}"
                    ),
                }
                typed_observation = {
                    "metric_name": str(metric_name)[:240],
                    "metric_scope": "k6_summary",
                    "statistic": statistic,
                    "value": value,
                    "unit": unit,
                    "sample_count": sample_count,
                    "producer": producer,
                    "producer_version": producer_version,
                    "workload": workload,
                    "metric_type": metric_type,
                    "contains": contains,
                    "threshold_status": threshold_status,
                    "thresholds": thresholds,
                    "state": state,
                }
                excerpt = json.dumps(typed_observation, sort_keys=True, separators=(",", ":"))
                derivative = _get_or_create_text_derivative(
                    session,
                    project=project,
                    run=run,
                    artifact=artifact,
                    source_locator=source_locator,
                    excerpt=excerpt[: settings.analysis_text_budget],
                    observation=typed_observation,
                    redaction_classes=set(),
                    settings=settings,
                )
                evidence = Evidence(
                    project_id=project.id,
                    run_id=run.id,
                    artifact_id=artifact.id,
                    run_input_id=run_input.id,
                    execution_id=None,
                    derivative_id=derivative.id,
                    kind="performance_metric_observation",
                    provenance_kind="current_run_metric",
                    locator_version="evidence-locator-v2",
                    locator={
                        "version": "evidence-locator-v2",
                        "source": source_locator,
                        "derivative": {"kind": "json-pointer", "pointer": "/excerpt"},
                    },
                    excerpt=excerpt[: settings.analysis_text_budget],
                    observation=typed_observation,
                    content_digest=derivative.digest,
                    parser_version=item.parser_version or "k6-summary-v1",
                    extractor_version="performance-observation-extractor-v1",
                    redaction_version=REDACTION_VERSION,
                    warnings=list(item.warnings),
                )
                session.add(evidence)
                session.flush()
                dimensions = build_observation_dimensions(
                    run,
                    workload=workload,
                    browser=None,
                    producer=producer,
                    producer_version=producer_version,
                    extra={
                        "metric_type": metric_type,
                        "contains": contains,
                        "load_profile": state.get("testRunDurationMs")
                        or state.get("isStdOutTTY")
                        or (run.source_metadata or {}).get("load_profile"),
                    },
                )
                register_performance_observation(
                    session,
                    project_id=project.id,
                    run=run,
                    run_input_id=run_input.id,
                    execution_id=None,
                    evidence_id=evidence.id,
                    metric_name=str(metric_name)[:240],
                    metric_scope="k6_summary",
                    statistic=statistic,
                    original_value=value,
                    original_unit=unit,
                    sample_count=sample_count,
                    producer=producer,
                    producer_version=producer_version,
                    workload=workload,
                    dimensions=dimensions,
                    threshold_status=threshold_status,
                    threshold_details={"thresholds": thresholds},
                    source_digest=run_input.digest or artifact.digest,
                    source_locator=source_locator,
                    direction=infer_metric_direction(
                        str(metric_name),
                        metric_scope="k6_summary",
                        statistic=statistic,
                        contains=contains,
                    ),
                    observed_at=run.started_at or run.created_at,
                )
                persisted += 1

    run.source_metadata = {
        **(run.source_metadata or {}),
        "performance_observation_count": persisted,
        "performance_observations_truncated": truncated,
        "performance_extractor_version": "performance-observation-extractor-v1",
    }


def manifest_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@instrument("redaction")
def _sanitize_evidence_value(value: Any, *, max_text: int, depth: int = 0,
                             _remaining: list[int] | None = None) -> tuple[Any, set[str]]:
    """Trace one bounded structured-redaction operation, not each recursive field."""
    return _sanitize_evidence_value_inner(value, max_text=max_text, depth=depth, _remaining=_remaining)


def _sanitize_evidence_value_inner(
    value: Any,
    *,
    max_text: int,
    depth: int = 0,
    _remaining: list[int] | None = None,
) -> tuple[Any, set[str]]:
    """Return a bounded JSON-safe value plus redaction classes encountered.

    The shared character budget prevents a large nested object from multiplying
    the per-string limit into an unbounded derivative.
    """
    remaining = _remaining if _remaining is not None else [max_text]
    if depth > 8:
        return "[TRUNCATED:maximum-depth]", {"maximum_depth"}
    if value is None or isinstance(value, (bool, int, float)):
        return value, set()
    if isinstance(value, str):
        if remaining[0] <= 0:
            return "[TRUNCATED:analysis-text-budget]", {"truncated"}
        retained = value[: min(len(value), remaining[0], max_text)]
        remaining[0] -= len(retained)
        redacted = redact_text(retained)
        classes = set(redacted.classes)
        if len(retained) < len(value):
            classes.add("truncated")
        return redacted.text, classes
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        classes: set[str] = set()
        for index, (key, item) in enumerate(value.items()):
            if index >= 500 or remaining[0] <= 0:
                safe["__truncated__"] = "analysis-text-budget-or-member-limit"
                classes.add("truncated")
                break
            safe_key = redact_text(str(key)[:512]).text
            sensitive = redact_sensitive_field(safe_key, item)
            if sensitive is not None:
                safe[safe_key] = sensitive.text
                classes.update(sensitive.classes)
                continue
            safe_value, child_classes = _sanitize_evidence_value_inner(
                item,
                max_text=max_text,
                depth=depth + 1,
                _remaining=remaining,
            )
            safe[safe_key] = safe_value
            classes.update(child_classes)
        return safe, classes
    if isinstance(value, (list, tuple)):
        safe_items: list[Any] = []
        classes: set[str] = set()
        for index, item in enumerate(value):
            if index >= 1000 or remaining[0] <= 0:
                safe_items.append("[TRUNCATED:analysis-text-budget-or-list-limit]")
                classes.add("truncated")
                break
            safe_item, child_classes = _sanitize_evidence_value_inner(
                item,
                max_text=max_text,
                depth=depth + 1,
                _remaining=remaining,
            )
            safe_items.append(safe_item)
            classes.update(child_classes)
        return safe_items, classes
    return _sanitize_evidence_value_inner(
        str(value),
        max_text=max_text,
        depth=depth,
        _remaining=remaining,
    )


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


def _get_or_create_text_derivative(
    session: Session,
    *,
    project: Project,
    run: Run,
    artifact: Artifact,
    source_locator: dict[str, Any],
    excerpt: str,
    observation: dict[str, Any],
    redaction_classes: set[str],
    settings: Settings,
) -> ArtifactDerivative:
    payload = {
        "schema_version": "failurelens-safe-evidence-1.0",
        "excerpt": excerpt,
        "observation": observation,
        "source_locator": source_locator,
        "redaction": {
            "version": REDACTION_VERSION,
            "classes": sorted(redaction_classes),
        },
    }
    content = _canonical_json_bytes(payload)
    digest = hashlib.sha256(content).hexdigest()
    existing = session.scalar(
        select(ArtifactDerivative).where(
            ArtifactDerivative.artifact_id == artifact.id,
            ArtifactDerivative.kind == "safe-observation-json",
            ArtifactDerivative.digest == digest,
        )
    )
    if existing:
        return existing

    stored = store_derivative_bytes(
        content,
        root=settings.artifact_root,
        project_id=project.id,
        filename=f"evidence-{digest[:16]}.json",
        media_type="application/vnd.failurelens.evidence+json",
        max_bytes=settings.analysis_text_budget * 4,
    )
    derivative = ArtifactDerivative(
        project_id=project.id,
        run_id=run.id,
        artifact_id=artifact.id,
        kind="safe-observation-json",
        digest=stored.digest,
        source_digest=artifact.digest,
        storage_path=stored.relative_path,
        media_type=stored.media_type,
        size_bytes=stored.size_bytes,
        redaction_version=REDACTION_VERSION,
        source_map={
            "version": "source-map-v1",
            "source": source_locator,
            "derivative": {"kind": "json-pointer", "pointer": "/excerpt"},
            "location_preserved": not redaction_classes,
        },
        approved=True,
        restricted=False,
        approval_state="auto_approved_text",
        retention_state="active",
        metadata_json={
            "schema_version": payload["schema_version"],
            "redaction_classes": sorted(redaction_classes),
        },
    )
    session.add(derivative)
    session.flush()
    return derivative


def create_project(
    session: Session, slug: str, name: str, *, commit: bool = True
) -> Project:
    project = Project(slug=slug, name=name)
    session.add(project)
    try:
        if commit:
            session.commit()
        else:
            session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(Project).where(Project.slug == slug))
        if existing:
            return existing
        raise
    if commit:
        session.refresh(project)
    return project


def _resolve_input_scope(
    declared_expected: int | None,
    parsed_expected: int | None,
    parsed_received: int | None,
    parsed_completeness: str | None,
) -> tuple[int | None, int, str]:
    expected_candidates = [
        value for value in (declared_expected, parsed_expected) if value is not None
    ]
    expected = max(expected_candidates) if expected_candidates else None
    received = parsed_received if parsed_received is not None else 1
    complete_by_count = expected is None or expected == received
    complete_by_parser = parsed_completeness in {None, "complete"}
    completeness = "complete" if complete_by_count and complete_by_parser else "partial"
    return expected, received, completeness


def _bind_changed_file_trust(
    input_records: Sequence[ParsedInput],
    *,
    effective_trust: str,
) -> tuple[ParsedInput, ...]:
    """Bind changed-file trust at the authenticated ingestion boundary.

    Artifact bytes may declare provenance for audit, but they cannot elevate
    themselves. Only validated RunMetadata supplied by a trusted transport
    establishes the trust level used by impact selection.
    """
    bound: list[ParsedInput] = []
    for item in input_records:
        if item.kind != "changed-files":
            bound.append(item)
            continue
        item_metadata = dict(item.metadata)
        item_metadata.setdefault(
            "declared_trust", item_metadata.get("trust", "self_reported")
        )
        item_metadata["trust"] = effective_trust
        item_metadata["trust_source"] = "ingestion_metadata"
        bound.append(replace(item, metadata=item_metadata))
    return tuple(bound)


@instrument("ingestion")
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
    input_records: Sequence[ParsedInput] = (),
    parsed_expected_inputs: int | None = None,
    parsed_received_inputs: int | None = None,
    parsed_completeness: str | None = None,
    manifest_version: str = "standalone",
    restricted: bool = True,
) -> Run:
    from .retention import lock_project
    lock_project(session, project.id)
    input_records = _bind_changed_file_trust(
        input_records, effective_trust=metadata.comparison_trust
    )
    expected_inputs, received_inputs, completeness = _resolve_input_scope(
        metadata.expected_inputs,
        parsed_expected_inputs,
        parsed_received_inputs,
        parsed_completeness,
    )
    input_identity = [
        {
            "id": item.input_id,
            "kind": item.kind,
            "path": item.path,
            "required": item.required,
            "status": item.status,
            "digest": item.digest,
        }
        for item in input_records
    ]
    identity_payload = {
        "schema_version": "artifact-ingestion-v2",
        "external_id": metadata.external_id,
        "attempt": metadata.attempt,
        "repository": metadata.repository,
        "commit_sha": metadata.commit_sha,
        "base_sha": metadata.base_sha,
        "branch": metadata.branch,
        "run_scope": metadata.run_scope,
        "comparison_trust": metadata.comparison_trust,
        "environment": metadata.environment,
        "timezone": metadata.timezone,
        "worker_count": metadata.worker_count,
        "shard_count": metadata.shard_count,
        "source_digest": source_digest,
        "source_format": source_format,
        "parser_version": parser_version,
        "manifest_version": manifest_version,
        "expected_inputs": expected_inputs,
        "received_inputs": received_inputs,
        "inputs": input_identity,
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
        cluster_project_failures(session, project.id)
        return existing

    input_summary = [
        {
            "id": item.input_id,
            "kind": item.kind,
            "path": item.path,
            "required": item.required,
            "status": item.status,
            "digest": item.digest,
            "size_bytes": item.size_bytes,
            "parser_version": item.parser_version,
            "warnings": list(item.warnings),
        }
        for item in input_records
    ]
    run = Run(
        project_id=project.id,
        external_id=metadata.external_id,
        attempt=metadata.attempt,
        repository=metadata.repository,
        commit_sha=metadata.commit_sha,
        base_sha=metadata.base_sha,
        branch=metadata.branch,
        framework=source_format,
        run_scope=metadata.run_scope,
        environment=metadata.environment,
        timezone=metadata.timezone,
        worker_count=metadata.worker_count,
        shard_count=metadata.shard_count,
        status=RunStatus.processing,
        completeness=completeness,
        expected_inputs=expected_inputs,
        received_inputs=received_inputs,
        manifest_digest=digest,
        started_at=datetime.now(UTC),
        source_metadata={
            **metadata.source_metadata,
            "source_format": source_format,
            "parser_version": parser_version,
            "run_scope": metadata.run_scope,
            "comparison_trust": metadata.comparison_trust,
            "environment": metadata.environment,
            "timezone": metadata.timezone,
            "worker_count": metadata.worker_count,
            "shard_count": metadata.shard_count,
            "parser_warnings": list(parser_warnings),
            "source_digest": source_digest,
            "manifest_version": manifest_version,
            "observation_count": len(observations),
            "input_summary": input_summary,
        },
    )
    session.add(run)
    session.flush()

    artifact = Artifact(
        run_id=run.id,
        kind="source-bundle" if len(input_records) > 1 else "source-report",
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
            "manifest_version": manifest_version,
            "warnings": list(parser_warnings),
            "inputs": input_summary,
        },
    )
    session.add(artifact)
    session.flush()

    run_inputs_by_input_id: dict[str, RunInput] = {}
    for item in input_records:
        run_input = RunInput(
            project_id=project.id,
            run_id=run.id,
            input_id=item.input_id,
            kind=item.kind,
            path=item.path,
            required=item.required,
            status=item.status,
            digest=item.digest,
            size_bytes=item.size_bytes,
            media_type=item.media_type,
            parser_version=item.parser_version,
            warnings=list(item.warnings),
            metadata_json=item.metadata,
        )
        session.add(run_input)
        run_inputs_by_input_id[item.input_id] = run_input
    session.flush()

    observation_sources: dict[int, tuple[str, str | None, list[str]]] = {}
    for item in input_records:
        for observation in item.observations:
            observation_sources[id(observation)] = (
                item.input_id,
                item.parser_version,
                list(item.warnings),
            )

    settings = get_settings()
    for observation_index, observation in enumerate(observations):
        try:
            outcome = Outcome(observation.outcome)
        except ValueError:
            outcome = Outcome.unknown
        input_id, evidence_parser_version, input_warnings = observation_sources.get(
            id(observation), ("input-1", parser_version, list(parser_warnings))
        )
        raw_details = dict(observation.details)
        raw_details["retry_recovered"] = bool(raw_details.get("retry_recovered"))
        raw_details["input_id"] = input_id
        details_value, detail_redactions = _sanitize_evidence_value(
            raw_details, max_text=settings.analysis_text_budget
        )
        details = dict(details_value) if isinstance(details_value, dict) else {}
        details["retry_recovered"] = bool(details.get("retry_recovered"))
        details["input_id"] = input_id

        raw_message = observation.message or ""
        safe_message = redact_text(raw_message)
        safe_exception = (
            redact_text(observation.exception_type).text
            if observation.exception_type
            else None
        )
        execution = TestExecution(
            run_id=run.id,
            test_identity=redact_text(observation.test_identity).text,
            suite=redact_text(observation.suite).text if observation.suite else None,
            source_path=(
                redact_text(observation.source_path).text
                if observation.source_path
                else None
            ),
            parameterization=(
                redact_text(observation.parameterization).text
                if observation.parameterization
                else None
            ),
            browser=redact_text(observation.browser).text if observation.browser else None,
            attempt=observation.attempt,
            outcome=outcome,
            duration_ms=observation.duration_ms,
            retry_recovered=bool(details.get("retry_recovered")),
            details=details,
        )
        session.add(execution)
        session.flush()

        raw_excerpt = (
            observation.evidence_excerpt
            or raw_message
            or f"{observation.test_identity}: {outcome.value}"
        )
        safe_excerpt = redact_text(raw_excerpt)
        excerpt = safe_excerpt.text[: settings.analysis_text_budget]
        redaction_classes = (
            set(safe_excerpt.classes)
            | set(safe_message.classes)
            | detail_redactions
        )
        if len(safe_excerpt.text) > settings.analysis_text_budget:
            redaction_classes.add("truncated")

        source_locator = dict(
            observation.evidence_locator
            or {"kind": "derived-observation", "index": observation_index}
        )
        source_locator["input_id"] = input_id
        typed_observation = {
            "test_identity": execution.test_identity,
            "suite": execution.suite,
            "source_path": execution.source_path,
            "parameterization": execution.parameterization,
            "browser": execution.browser,
            "attempt": execution.attempt,
            "outcome": outcome.value,
            "duration_ms": execution.duration_ms,
            "message": safe_message.text[: settings.analysis_text_budget],
            "exception_type": safe_exception,
            "details": details,
        }
        derivative = _get_or_create_text_derivative(
            session,
            project=project,
            run=run,
            artifact=artifact,
            source_locator=source_locator,
            excerpt=excerpt,
            observation=typed_observation,
            redaction_classes=redaction_classes,
            settings=settings,
        )
        locator = {
            "version": "evidence-locator-v2",
            "source": source_locator,
            "derivative": {"kind": "json-pointer", "pointer": "/excerpt"},
        }
        run_input = run_inputs_by_input_id.get(input_id)
        evidence = Evidence(
            project_id=project.id,
            run_id=run.id,
            artifact_id=artifact.id,
            run_input_id=run_input.id if run_input else None,
            execution_id=execution.id,
            derivative_id=derivative.id,
            kind="current_run_observation",
            provenance_kind="current_execution",
            locator_version="evidence-locator-v2",
            locator=locator,
            excerpt=excerpt,
            observation=typed_observation,
            content_digest=derivative.digest,
            parser_version=evidence_parser_version or parser_version,
            extractor_version="observation-extractor-v2",
            redaction_version=REDACTION_VERSION,
            warnings=[
                *[f"redacted:{item}" for item in sorted(redaction_classes)],
                *[f"parser:{item}" for item in input_warnings],
            ],
        )
        session.add(evidence)
        session.flush()
        if outcome is Outcome.failed:
            message = safe_message.text or excerpt or "Test failed without a message"
            fingerprint, features = make_fingerprint(
                message, safe_exception, details
            )
            session.add(
                Failure(
                    project_id=project.id,
                    run_id=run.id,
                    execution_id=execution.id,
                    message=message,
                    exception_type=safe_exception,
                    strict_fingerprint=fingerprint,
                    loose_features=features,
                )
            )

    _persist_performance_observations(
        session,
        project=project,
        run=run,
        artifact=artifact,
        input_records=input_records,
        run_inputs_by_input_id=run_inputs_by_input_id,
        settings=settings,
    )

    from .domain_evidence import register_domain_inputs
    register_domain_inputs(session, project, run, artifact, settings)

    from .transaction_evidence import register_transaction_inputs
    register_transaction_inputs(session, project, run, artifact, settings)
    from .contract_evidence import register_contract_inputs
    register_contract_inputs(session, project, run, artifact, settings)

    from .binary_evidence import register_binary_inputs
    register_binary_inputs(session, project, run, artifact, settings)

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
            cluster_project_failures(session, project.id)
            return existing
        raise
    session.refresh(run)
    cluster_project_failures(session, project.id)
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
            parameterization=observation.parameterization,
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
    normalized_input = ParsedInput(
        input_id="normalized-request",
        kind="normalized-json",
        path="normalized-ingestion.json",
        required=True,
        status="accepted",
        digest=artifact_digest,
        size_bytes=len(artifact_payload),
        media_type="application/json",
        parser_version="normalized-v2",
        observations=tuple(parsed),
        metadata={
            "schema_version": request.schema_version,
            "observation_count": len(parsed),
        },
    )
    metadata = RunMetadata.model_validate(
        request.model_dump(exclude={"schema_version", "observations"})
    )
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
        parser_version="normalized-v2",
        input_records=(normalized_input,),
        parsed_expected_inputs=1,
        parsed_received_inputs=1,
        parsed_completeness="complete",
        manifest_version="normalized-1.0",
        restricted=False,
    )


def _validate_ingestion_idempotency(
    existing: Ingestion,
    metadata: RunMetadata,
    *,
    source_format: str,
) -> None:
    supplied = {
        "repository": metadata.repository,
        "commit_sha": metadata.commit_sha,
        "base_sha": metadata.base_sha,
        "branch": metadata.branch,
        "source_format": source_format,
    }
    conflicts = [
        field
        for field, value in supplied.items()
        if value != getattr(existing, field)
    ]
    # Processing derives the effective count from the manifest; retries must
    # compare the original transport declaration, not that derived count.
    declared_expected = existing.source_metadata.get("declared_expected_inputs", existing.expected_inputs)
    if metadata.expected_inputs != declared_expected:
        conflicts.append("expected_inputs")
    context = {
        "run_scope": metadata.run_scope,
        "comparison_trust": metadata.comparison_trust,
        "environment": metadata.environment,
        "timezone": metadata.timezone,
        "worker_count": metadata.worker_count,
        "shard_count": metadata.shard_count,
    }
    legacy_defaults = {
        "run_scope": "unknown",
        "comparison_trust": "self_reported",
    }
    conflicts.extend(
        field
        for field, value in context.items()
        if existing.source_metadata.get(field, legacy_defaults.get(field)) != value
    )
    if conflicts:
        raise ValueError(
            "idempotency conflict for existing ingestion fields: "
            + ", ".join(sorted(set(conflicts)))
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
    from .retention import lock_project, _delete_later, flush_deletions
    lock_project(session, project.id)
    existing = session.scalar(
        select(Ingestion).where(
            Ingestion.project_id == project.id,
            Ingestion.external_id == metadata.external_id,
            Ingestion.attempt == metadata.attempt,
            Ingestion.source_digest == stored.digest,
        )
    )
    if existing:
        if existing.source_expired_at is not None:
            # A replay might just have recreated the content-addressed source.
            # It cannot revive an expired ingestion or leave an untracked copy.
            _delete_later(session, project.id, stored.relative_path)
            session.commit()
            flush_deletions(session, project.id, settings or get_settings())
            _validate_ingestion_idempotency(existing, metadata, source_format=source_format)
            # Deliberately discarded binary originals are not a failed/expired
            # investigation. A retry acknowledges its durable result without
            # requeueing work or retaining newly submitted source bytes. Actual
            # retention expiry keeps the established conflict behavior.
            from .binary_evidence import BINARY_POLICY
            run = session.get(Run, existing.run_id) if existing.run_id else None
            if (run is not None and run.evidence_expired_at is None
                    and run.source_metadata.get("binary_original_policy") == BINARY_POLICY
                    and existing.state in (IngestionState.succeeded, IngestionState.partial)):
                return existing
            raise ValueError("source expired; submit a new external ID or attempt")
        _validate_ingestion_idempotency(
            existing, metadata, source_format=source_format
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
        source_metadata={
            **metadata.source_metadata,
            "declared_expected_inputs": metadata.expected_inputs,
            "run_scope": metadata.run_scope,
            "comparison_trust": metadata.comparison_trust,
            "environment": metadata.environment,
            "timezone": metadata.timezone,
            "worker_count": metadata.worker_count,
            "shard_count": metadata.shard_count,
        },
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
        payload={"ingestion_id": ingestion.id, "job_schema": "1.0", **trace_context()},
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
            _validate_ingestion_idempotency(
                existing, metadata, source_format=source_format
            )
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
    from .retention import lock_project
    lock_project(session, ingestion.project_id)
    session.refresh(ingestion)
    if ingestion.source_expired_at is not None:
        raise ValueError("source expired; retry cannot resurrect retained evidence")
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
        payload={"ingestion_id": ingestion.id, "job_schema": "1.0", **trace_context()},
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


@instrument("ingestion")
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
    parsed: ParsedArtifact = parse_artifact(
        content,
        ingestion.original_name,
        settings,
        source_format=ingestion.source_format,
        media_type=ingestion.media_type,
    )
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
        run_scope=str(ingestion.source_metadata.get("run_scope") or "unknown"),
        comparison_trust=str(
            ingestion.source_metadata.get("comparison_trust") or "self_reported"
        ),
        environment=(
            str(ingestion.source_metadata["environment"])
            if ingestion.source_metadata.get("environment") is not None
            else None
        ),
        timezone=(
            str(ingestion.source_metadata["timezone"])
            if ingestion.source_metadata.get("timezone") is not None
            else None
        ),
        worker_count=(
            int(ingestion.source_metadata["worker_count"])
            if ingestion.source_metadata.get("worker_count") is not None
            else None
        ),
        shard_count=(
            int(ingestion.source_metadata["shard_count"])
            if ingestion.source_metadata.get("shard_count") is not None
            else None
        ),
        expected_inputs=ingestion.expected_inputs,
        source_metadata={
            **ingestion.source_metadata,
            "ingestion_id": ingestion.id,
            "report_name": parsed.report_name,
            "source_format_requested": ingestion.source_format,
            "manifest_version": parsed.manifest_version,
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
        input_records=parsed.inputs,
        parsed_expected_inputs=parsed.expected_inputs,
        parsed_received_inputs=parsed.received_inputs,
        parsed_completeness=parsed.completeness,
        manifest_version=parsed.manifest_version,
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
    ingestion.expected_inputs = run.expected_inputs
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
            "manifest_version": parsed.manifest_version,
            "expected_inputs": run.expected_inputs,
            "received_inputs": run.received_inputs,
            "completeness": run.completeness,
            "observations": len(parsed.observations),
            "inputs": [
                {
                    "id": item.input_id,
                    "kind": item.kind,
                    "path": item.path,
                    "required": item.required,
                    "status": item.status,
                    "warnings": list(item.warnings),
                }
                for item in parsed.inputs
            ],
            "warnings": list(parsed.warnings),
        },
        {
            "phase": "analysis",
            "status": "complete",
            "failures": len(failures),
        },
    ]
    from .binary_evidence import discard_binary_source
    discard_binary_source(session, ingestion, run)
    session.commit()
    session.refresh(ingestion)
    return run



def select_failure_evidence(session: Session, failure: Failure) -> list[Evidence]:
    """Return only evidence authorized for one failure investigation.

    Execution evidence is isolated by execution ID. Shared run diagnostics and
    input diagnostics are admitted only through explicit provenance labels; old
    unscoped evidence is intentionally excluded rather than guessed into scope.
    """
    conditions = [Evidence.execution_id == failure.execution_id]
    conditions.append(
        and_(
            Evidence.execution_id.is_(None),
            Evidence.provenance_kind == "shared_run_diagnostic",
        )
    )

    input_id = failure.execution.details.get("input_id")
    if isinstance(input_id, str) and input_id:
        run_input = session.scalar(
            select(RunInput).where(
                RunInput.run_id == failure.run_id,
                RunInput.input_id == input_id,
            )
        )
        if run_input is not None:
            conditions.append(
                and_(
                    Evidence.execution_id.is_(None),
                    Evidence.provenance_kind == "input_diagnostic",
                    Evidence.run_input_id == run_input.id,
                )
            )

    return list(
        session.scalars(
            select(Evidence)
            .where(
                Evidence.project_id == failure.project_id,
                Evidence.run_id == failure.run_id,
                Evidence.provenance_kind != "supplemental_trace",
                or_(*conditions),
            )
            .options(
                selectinload(Evidence.artifact),
                selectinload(Evidence.derivative),
                selectinload(Evidence.run_input),
            )
            .order_by(Evidence.id)
        ).all()
    )


@instrument("analysis")
def analyze_and_persist(session: Session, failure: Failure) -> Analysis:
    from fastapi import HTTPException
    from .retention import lock_project
    lock_project(session, failure.project_id)
    session.refresh(failure.run)
    if failure.run.evidence_expired_at is not None:
        raise HTTPException(410, "evidence expired; submit a new run rather than resurrecting old evidence")
    evidence_rows = select_failure_evidence(session, failure)
    historical = history_context_for_failure(session, failure)
    settings = get_settings()

    evidence_validation = validate_evidence_records(
        failure,
        evidence_rows,
        settings=settings,
    )
    views = validated_evidence_views(evidence_rows, evidence_validation)
    execution = failure.execution
    analysis_details = {
        **execution.details,
        "retry_recovered": execution.retry_recovered,
        "incomplete_run": failure.run.completeness != "complete",
    }
    decision = analyze_failure(
        message=failure.message,
        exception_type=failure.exception_type,
        details=analysis_details,
        evidence=views,
        historical=historical,
    )
    validated = validate_decision(
        failure=failure,
        decision=decision,
        evidence_rows=evidence_rows,
        evidence_validation=evidence_validation,
        historical=historical,
    )

    evidence_checks = {item.evidence_id: item for item in evidence_validation.checks}
    payload = {
        "message": failure.message,
        "exception_type": failure.exception_type,
        "details": analysis_details,
        "evidence": [
            {
                "id": evidence.id,
                "execution_id": evidence.execution_id,
                "run_input_id": evidence.run_input_id,
                "provenance_kind": evidence.provenance_kind,
                "content_digest": evidence.content_digest,
                "derivative_digest": (
                    evidence.derivative.digest if evidence.derivative else None
                ),
                "actual_digest": (
                    evidence_checks[evidence.id].actual_digest
                    if evidence.id in evidence_checks
                    else None
                ),
                "validation_status": (
                    "verified"
                    if evidence.id in evidence_validation.accepted_ids
                    else "rejected"
                ),
                "validation_reasons": (
                    list(evidence_checks[evidence.id].reasons)
                    if evidence.id in evidence_checks
                    else ["validation_check_missing"]
                ),
            }
            for evidence in evidence_rows
        ],
        "history": historical,
        "decision_signals": decision.signal_counts,
        "validation": validated.validation_results,
        "analysis_version": ANALYSIS_VERSION,
        "rules_version": RULES_VERSION,
        "validation_version": VALIDATION_VERSION,
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

    revision = (
        session.scalar(
            select(func.max(Analysis.revision)).where(
                Analysis.failure_id == failure.id
            )
        )
        or 0
    ) + 1
    row = Analysis(
        failure_id=failure.id,
        revision=revision,
        analysis_version=ANALYSIS_VERSION,
        input_digest=digest,
        category=validated.category,
        severity=validated.severity,
        confidence_value=validated.score,
        confidence_kind=validated.score_kind,
        confidence_explanation=validated.explanation,
        evidence_completeness=(
            "partial"
            if validated.missing or evidence_validation.rejected_ids
            else "complete"
        ),
        summary=validated.summary,
        claims=list(validated.claims),
        supporting_evidence_ids=list(validated.supporting_ids),
        contradictory_evidence_ids=list(validated.contradictory_ids),
        missing_evidence=list(validated.missing),
        hypotheses=list(validated.hypotheses),
        next_investigation=list(validated.next_steps),
        abstention_reason=validated.abstention_reason,
        policy_flags=list(validated.policy_flags),
        provenance={
            "input_digest": digest,
            "history_cutoff": historical["history_cutoff"],
            "history_policy_version": historical["policy_version"],
            "history_input_digest": historical["history_input_digest"],
            "history_cohort": historical["cohort"],
            "parser_versions": sorted(
                {item.parser_version for item in evidence_rows}
            ),
            "extractor_versions": sorted(
                {item.extractor_version for item in evidence_rows}
            ),
            "redaction_versions": sorted(
                {item.redaction_version for item in evidence_rows}
            ),
            "derivative_digests": sorted(
                {
                    item.derivative.digest
                    for item in evidence_rows
                    if item.derivative is not None
                }
            ),
            "evidence_scope": {
                "project_id": failure.project_id,
                "run_id": failure.run_id,
                "execution_id": failure.execution_id,
                "input_id": execution.details.get("input_id"),
            },
            "rules_version": RULES_VERSION,
            "analysis_version": ANALYSIS_VERSION,
            "validation_version": VALIDATION_VERSION,
        },
        validation_version=VALIDATION_VERSION,
        validation_results=validated.validation_results,
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
    if row.failure.run.evidence_expired_at is not None:
        reason = "Evidence expired under the project retention policy. The recorded category is historical, not a current verified diagnosis."
        return AnalysisResult(analysis_id=row.id, analysis_version=row.analysis_version,
            failure_id=row.failure_id, run_id=row.failure.run_id, evidence_state="expired", recorded_category=row.category,
            category=Category.insufficient_evidence, severity=row.severity,
            confidence=Confidence(value=None, kind="unavailable", explanation=reason), evidence_completeness="expired",
            summary=reason, claims=[], supporting_evidence_ids=[], contradictory_evidence_ids=[],
            missing_evidence=["evidence_expired"], hypotheses=[], next_investigation=[{
                "action": "Collect fresh evidence in a new run", "rationale": reason, "evidence_ids": []}],
            abstention_reason=reason, policy_flags=["evidence_expired"], provenance={"retention_state": "expired"},
            validation_version=row.validation_version, validation_results={"status": "expired"})
    publication_validated = persisted_analysis_is_publication_validated(row)
    if publication_validated:
        category = row.category
        confidence = Confidence(
            value=row.confidence_value,
            kind=row.confidence_kind,
            explanation=row.confidence_explanation,
        )
        evidence_completeness = row.evidence_completeness
        summary = row.summary
        claims = row.claims
        supporting_ids = row.supporting_evidence_ids
        contradictory_ids = row.contradictory_evidence_ids
        missing = row.missing_evidence
        hypotheses = row.hypotheses
        next_investigation = row.next_investigation
        abstention_reason = row.abstention_reason
        policy_flags = row.policy_flags
        validation_results = row.validation_results
    else:
        reason = (
            "This analysis predates or failed the publication validation boundary; "
            "its stored category is withheld."
        )
        category = Category.insufficient_evidence
        confidence = Confidence(
            value=None,
            kind="unavailable",
            explanation=reason,
        )
        evidence_completeness = "unvalidated"
        summary = (
            "Failure requires re-analysis because publication-grade evidence "
            "validation is unavailable."
        )
        claims = []
        supporting_ids = []
        contradictory_ids = []
        missing = sorted(set([*row.missing_evidence, "validated analysis revision"]))
        hypotheses = [
            {
                "description": row.summary,
                "evidence_ids": [],
                "counterevidence_ids": [],
                "status": "legacy_unvalidated",
            }
        ]
        next_investigation = [
            {
                "action": "Re-run analysis against immutable scoped derivatives",
                "rationale": reason,
                "evidence_ids": [],
            }
        ]
        abstention_reason = reason
        policy_flags = sorted(
            set([*row.policy_flags, "legacy_analysis_not_publication_validated"])
        )
        validation_results = row.validation_results or {
            "version": row.validation_version,
            "status": "not_validated",
            "accepted_evidence_ids": [],
            "rejected_evidence_ids": [],
            "claims": [],
            "original_category": row.category.value,
            "published_category": Category.insufficient_evidence.value,
        }

    return AnalysisResult(
        analysis_id=row.id,
        analysis_version=row.analysis_version,
        failure_id=row.failure_id,
        run_id=row.failure.run_id,
        category=category,
        severity=row.severity,
        confidence=confidence,
        evidence_completeness=evidence_completeness,
        summary=summary,
        claims=claims,
        supporting_evidence_ids=supporting_ids,
        contradictory_evidence_ids=contradictory_ids,
        missing_evidence=missing,
        hypotheses=hypotheses,
        next_investigation=next_investigation,
        abstention_reason=abstention_reason,
        policy_flags=policy_flags,
        provenance=row.provenance,
        validation_version=row.validation_version,
        validation_results=validation_results,
    )


def add_review(
    session: Session,
    analysis: Analysis,
    request: ReviewCreate,
    *,
    principal: Principal | None = None,
    actor: str | None = None,
) -> ReviewEvent:
    from .retention import lock_project
    lock_project(session, analysis.failure.project_id)
    session.refresh(analysis)
    session.refresh(analysis.failure.run)
    expired = analysis.failure.run.evidence_expired_at is not None
    current_version = session.scalar(
        select(func.max(ReviewEvent.version)).where(ReviewEvent.analysis_id == analysis.id)
    ) or 0
    if request.expected_version != current_version:
        raise ValueError(
            f"review version conflict: expected {request.expected_version}, current {current_version}"
        )
    if request.decision == "category_correction" and request.proposed_category is None:
        raise ValueError("category_correction requires proposed_category")
    if request.decision != "category_correction" and request.proposed_category is not None:
        raise ValueError("proposed_category is only valid for category_correction")
    if (
        request.release_advice == "NO_BLOCKER_IDENTIFIED_IN_OBSERVED_SCOPE"
        and (
            expired
            or analysis.evidence_completeness != "complete"
            or analysis.category in {Category.product_defect, Category.insufficient_evidence}
            or bool(analysis.policy_flags)
        )
    ):
        raise ValueError(
            "reassuring release advice is blocked by incomplete evidence, unresolved "
            "product risk, or active safety policy flags"
        )

    failure = session.get(Failure, analysis.failure_id)
    if failure is None:
        raise ValueError("analysis failure is unavailable")
    cited_ids = set(request.supporting_evidence_ids) | set(
        request.contradictory_evidence_ids
    )
    if cited_ids:
        rows = list(
            session.scalars(select(Evidence).where(Evidence.id.in_(sorted(cited_ids)))).all()
        )
        found = {row.id for row in rows if row.project_id == failure.project_id
                 and row.derivative is not None and row.derivative.retention_state == "active"}
        missing = sorted(cited_ids - found)
        if missing:
            raise ValueError(
                "review evidence must exist in the same project: " + ", ".join(missing)
            )

    effective_principal = principal or Principal(
        kind="user",
        actor_id=None,
        display_name=(actor or "legacy reviewer").strip(),
    )
    if not effective_principal.display_name:
        raise ValueError("review actor is required")
    event = ReviewEvent(
        analysis_id=analysis.id,
        actor=effective_principal.display_name,
        actor_kind=effective_principal.audit_kind,
        actor_user_id=effective_principal.user_id,
        decision=request.decision,
        proposed_category=request.proposed_category.value if request.proposed_category else None,
        reason=request.reason,
        supporting_evidence_ids=request.supporting_evidence_ids,
        contradictory_evidence_ids=request.contradictory_evidence_ids,
        hypothesis_decisions=request.hypothesis_decisions,
        investigation_outcome=request.investigation_outcome,
        release_advice=request.release_advice,
        version=current_version + 1,
    )
    session.add(event)
    session.flush()
    record_audit_event(
        session,
        effective_principal,
        action="analysis.review_created",
        resource_type="analysis_review",
        resource_id=event.id,
        project_id=failure.project_id,
        reason=request.reason,
        details={
            "analysis_id": analysis.id,
            "decision": request.decision,
            "proposed_category": (
                request.proposed_category.value if request.proposed_category else None
            ),
            "release_advice": request.release_advice,
            "version": event.version,
        },
    )
    session.commit()
    session.refresh(event)
    return event
