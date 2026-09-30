from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict, deque
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .auth import Principal, record_audit_event
from .models import (
    ImpactMappingEdge,
    ImpactMappingSnapshot,
    ImpactOverride,
    ImpactRecommendation,
    ImpactRecommendationItem,
    ImpactTestDefinition,
    Project,
    Run,
    RunInput,
    utcnow,
)
from .schemas import (
    ImpactMappingSnapshotCreate,
    ImpactMappingSnapshotRead,
    ImpactOverrideCreate,
    ImpactOverrideRead,
    ImpactRecommendationCreate,
    ImpactRecommendationItemRead,
    ImpactRecommendationRead,
)

IMPACT_ENGINE_VERSION = "impact-engine-v1"
IMPACT_POLICY_VERSION = "impact-policy-v1"
MAX_DEPENDENCY_DEPTH = 4
TRUSTED_CHANGE_SOURCES = {"authenticated_lookup", "trusted_workflow"}
MANDATORY_TAGS = {"smoke", "security", "transaction", "critical"}
_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{7,64}$")

_CRITICAL_BASENAMES = {
    "dockerfile",
    "compose.yaml",
    "compose.yml",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "pyproject.toml",
    "uv.lock",
    "poetry.lock",
    "requirements.txt",
    "go.mod",
    "go.sum",
    "cargo.toml",
    "cargo.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
}
_CRITICAL_SEGMENTS = {
    "auth",
    "authentication",
    "authorization",
    "security",
    "ledger",
    "transaction",
    "transactions",
    "migration",
    "migrations",
    "schema",
    "schemas",
    "shared",
    "common",
}
_CRITICAL_PREFIXES = (
    ".github/workflows/",
    "migrations/",
    "db/migrations/",
    "database/migrations/",
    "alembic/",
    "ci/",
    "test-infrastructure/",
    "test_infrastructure/",
)

_KIND_LABELS = {
    "file_to_test": "explicit file-to-test mapping",
    "coverage": "coverage mapping",
    "api_ownership": "API ownership mapping",
    "ownership": "reviewed ownership mapping",
    "historical_failure": "prior failure relationship",
    "dependency": "reverse dependency mapping",
}


class ImpactInputError(ValueError):
    """Repository paths or changed-file artifact metadata failed validation."""


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_repo_path(value: str) -> str:
    """Return one stable repository-relative POSIX path or reject ambiguity."""

    if not isinstance(value, str):
        raise ImpactInputError("repository path must be a string")
    candidate = value.strip()
    if not candidate or len(candidate) > 1024:
        raise ImpactInputError("repository path is empty or too long")
    if "\x00" in candidate or "\\" in candidate:
        raise ImpactInputError(f"unsafe repository path: {value}")
    if candidate.startswith("/") or re.match(r"^[A-Za-z]:", candidate):
        raise ImpactInputError(f"repository path must be relative: {value}")
    path = PurePosixPath(candidate)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ImpactInputError(f"unsafe repository path: {value}")
    normalized = path.as_posix()
    if normalized.startswith("../"):
        raise ImpactInputError(f"unsafe repository path: {value}")
    return normalized


def _critical_path_reason(path: str) -> str | None:
    lowered = path.casefold()
    basename = PurePosixPath(lowered).name
    parts = set(PurePosixPath(lowered).parts)
    if basename in _CRITICAL_BASENAMES:
        return "critical_dependency_or_build_configuration_changed"
    if any(lowered.startswith(prefix) for prefix in _CRITICAL_PREFIXES):
        return "critical_ci_migration_or_test_infrastructure_changed"
    matched = sorted(parts.intersection(_CRITICAL_SEGMENTS))
    if matched:
        return f"critical_shared_domain_changed:{matched[0]}"
    return None


def _is_mandatory_test(test: ImpactTestDefinition) -> bool:
    tags = {str(item).casefold() for item in test.tags}
    return (
        test.mandatory
        or test.criticality == "critical"
        or bool(tags.intersection(MANDATORY_TAGS))
    )


def _snapshot_options():
    return (
        selectinload(ImpactMappingSnapshot.tests),
        selectinload(ImpactMappingSnapshot.edges),
    )


def _recommendation_options():
    return (
        selectinload(ImpactRecommendation.items),
        selectinload(ImpactRecommendation.overrides),
        selectinload(ImpactRecommendation.mapping_snapshot),
    )


def create_mapping_snapshot(
    session: Session,
    project: Project,
    request: ImpactMappingSnapshotCreate,
) -> ImpactMappingSnapshot:
    test_keys: set[str] = set()
    normalized_tests: list[dict[str, Any]] = []
    for item in request.tests:
        if item.test_key in test_keys:
            raise ValueError(f"duplicate impact test key: {item.test_key}")
        test_keys.add(item.test_key)
        source_path = (
            normalize_repo_path(item.source_path) if item.source_path else None
        )
        normalized_tests.append(
            {
                **item.model_dump(mode="json"),
                "source_path": source_path,
                "tags": sorted(
                    {tag.strip().casefold() for tag in item.tags if tag.strip()}
                ),
            }
        )

    normalized_edges: list[dict[str, Any]] = []
    edge_identities: set[tuple[str, str, str, str, str, str]] = set()
    for edge in request.edges:
        source_path = normalize_repo_path(edge.source_path)
        target_value = (
            edge.target_value
            if edge.target_type == "test"
            else normalize_repo_path(edge.target_value)
        )
        if edge.target_type == "test" and target_value not in test_keys:
            raise ValueError(f"impact edge references unknown test key: {target_value}")
        if edge.kind == "dependency" and edge.target_type != "file":
            raise ValueError("dependency edges must target another repository file")
        if edge.target_type == "file" and edge.kind != "dependency":
            raise ValueError("file targets are only valid for dependency edges")
        identity = (
            source_path,
            edge.target_type,
            target_value,
            edge.kind,
            edge.mapping_source,
            edge.mapping_version,
        )
        if identity in edge_identities:
            raise ValueError(
                "duplicate impact mapping edge: "
                f"{source_path} -> {edge.target_type}:{target_value}"
            )
        edge_identities.add(identity)
        normalized_edges.append(
            {
                **edge.model_dump(mode="json"),
                "source_path": source_path,
                "target_value": target_value,
            }
        )

    payload = {
        "schema_version": "impact-mapping-snapshot-v1",
        "version": request.version,
        "policy_version": request.policy_version,
        "trusted": request.trusted,
        "coverage_complete": request.coverage_complete,
        "source_metadata": request.source_metadata,
        "tests": sorted(normalized_tests, key=lambda item: item["test_key"]),
        "edges": sorted(
            normalized_edges,
            key=lambda item: (
                item["source_path"],
                item["target_type"],
                item["target_value"],
                item["kind"],
            ),
        ),
    }
    source_digest = _canonical_digest(payload)
    existing = session.scalar(
        select(ImpactMappingSnapshot)
        .where(
            ImpactMappingSnapshot.project_id == project.id,
            ImpactMappingSnapshot.version == request.version,
        )
        .options(*_snapshot_options())
    )
    if existing is not None:
        if existing.source_digest != source_digest:
            raise ValueError(
                "impact mapping version already exists with different immutable content"
            )
        return existing

    snapshot = ImpactMappingSnapshot(
        project_id=project.id,
        version=request.version,
        policy_version=request.policy_version,
        source_digest=source_digest,
        trusted=request.trusted,
        coverage_complete=request.coverage_complete,
        source_metadata=request.source_metadata,
    )
    session.add(snapshot)
    session.flush()
    for normalized_test in normalized_tests:
        session.add(
            ImpactTestDefinition(
                snapshot_id=snapshot.id,
                test_key=normalized_test["test_key"],
                test_identity=normalized_test["test_identity"],
                source_path=normalized_test["source_path"],
                criticality=normalized_test["criticality"],
                mandatory=normalized_test["mandatory"],
                tags=normalized_test["tags"],
                estimated_duration_ms=normalized_test["estimated_duration_ms"],
                metadata_json=normalized_test["metadata"],
            )
        )
    for normalized_edge in normalized_edges:
        session.add(
            ImpactMappingEdge(
                snapshot_id=snapshot.id,
                source_path=normalized_edge["source_path"],
                target_type=normalized_edge["target_type"],
                target_value=normalized_edge["target_value"],
                kind=normalized_edge["kind"],
                confidence=normalized_edge["confidence"],
                mapping_source=normalized_edge["mapping_source"],
                mapping_version=normalized_edge["mapping_version"],
                metadata_json=normalized_edge["metadata"],
            )
        )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(ImpactMappingSnapshot)
            .where(
                ImpactMappingSnapshot.project_id == project.id,
                ImpactMappingSnapshot.version == request.version,
            )
            .options(*_snapshot_options())
        )
        if existing is not None and existing.source_digest == source_digest:
            return existing
        raise
    return (
        session.scalar(
            select(ImpactMappingSnapshot)
            .where(ImpactMappingSnapshot.id == snapshot.id)
            .options(*_snapshot_options())
        )
        or snapshot
    )


def mapping_snapshot_to_schema(
    snapshot: ImpactMappingSnapshot,
) -> ImpactMappingSnapshotRead:
    return ImpactMappingSnapshotRead(
        id=snapshot.id,
        project_id=snapshot.project_id,
        version=snapshot.version,
        policy_version=snapshot.policy_version,
        source_digest=snapshot.source_digest,
        trusted=snapshot.trusted,
        coverage_complete=snapshot.coverage_complete,
        source_metadata=snapshot.source_metadata,
        test_count=len(snapshot.tests),
        edge_count=len(snapshot.edges),
        created_at=snapshot.created_at,
    )


def _normalized_changed_files(changed_input: RunInput) -> list[dict[str, Any]]:
    raw_files = changed_input.metadata_json.get("files")
    if not isinstance(raw_files, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_files):
        if not isinstance(raw, dict):
            raise ImpactInputError(
                f"changed-file metadata entry {index} is not an object"
            )
        status = str(raw.get("status") or "modified").casefold()
        if status not in {"added", "modified", "deleted", "renamed", "copied"}:
            raise ImpactInputError(f"unsupported changed-file status: {status}")
        path_value = raw.get("path") or raw.get("new_path")
        if not isinstance(path_value, str):
            raise ImpactInputError(f"changed-file metadata entry {index} has no path")
        old_value = raw.get("old_path")
        normalized.append(
            {
                "status": status,
                "path": normalize_repo_path(path_value),
                "old_path": (
                    normalize_repo_path(old_value)
                    if isinstance(old_value, str) and old_value.strip()
                    else None
                ),
                "coverage_reference": raw.get("coverage_reference"),
                "diff_reference": raw.get("diff_reference"),
            }
        )
    return normalized


def _comparison_safety_reasons(
    run: Run,
    changed_input: RunInput,
    *,
    base_sha: str | None,
    head_sha: str | None,
) -> list[str]:
    metadata = changed_input.metadata_json
    reasons: list[str] = []
    if changed_input.status != "accepted":
        reasons.append("changed_file_input_not_accepted")
    if metadata.get("complete") is not True:
        reasons.append("changed_file_list_incomplete")
    if "changed_file_list_incomplete" in changed_input.warnings:
        reasons.append("changed_file_list_incomplete")
    if "file_limit_reached" in changed_input.warnings:
        reasons.append("changed_file_list_truncated")
    if str(metadata.get("trust") or "self_reported") not in TRUSTED_CHANGE_SOURCES:
        reasons.append("changed_file_list_untrusted")
    if not base_sha or not _SHA_PATTERN.fullmatch(base_sha):
        reasons.append("invalid_or_missing_base_sha")
    if not head_sha or not _SHA_PATTERN.fullmatch(head_sha):
        reasons.append("invalid_or_missing_head_sha")
    if base_sha and head_sha and base_sha.casefold() == head_sha.casefold():
        reasons.append("base_head_are_identical")
    if run.base_sha and base_sha and run.base_sha.casefold() != base_sha.casefold():
        reasons.append("run_base_sha_mismatch")
    if run.commit_sha and head_sha and run.commit_sha.casefold() != head_sha.casefold():
        reasons.append("run_head_sha_mismatch")
    return sorted(set(reasons))


def _change_paths(change: dict[str, Any]) -> list[str]:
    values = [str(change["path"])]
    old_path = change.get("old_path")
    if isinstance(old_path, str) and old_path not in values:
        values.append(old_path)
    return values


def _confidence_label(value: float, *, mandatory: bool) -> str:
    if mandatory or value >= 0.85:
        return "high"
    if value >= 0.6:
        return "medium"
    if value > 0:
        return "low"
    return "none"


def _selection_engine(
    *,
    tests: list[ImpactTestDefinition],
    edges: list[ImpactMappingEdge],
    changes: list[dict[str, Any]],
    preexisting_safety_reasons: Iterable[str],
) -> dict[str, Any]:
    tests_by_key = {test.test_key: test for test in tests}
    edges_by_source: dict[str, list[ImpactMappingEdge]] = defaultdict(list)
    for edge in edges:
        edges_by_source[edge.source_path].append(edge)
    for values in edges_by_source.values():
        values.sort(
            key=lambda edge: (
                edge.target_type,
                edge.target_value,
                edge.kind,
                edge.mapping_source,
                edge.id,
            )
        )

    contributions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    mapped_change_indexes: set[int] = set()
    critical_reasons: set[str] = set()

    for change_index, change in enumerate(changes):
        for changed_path in _change_paths(change):
            critical_reason = _critical_path_reason(changed_path)
            if critical_reason:
                critical_reasons.add(critical_reason)

            queue: deque[tuple[str, int, list[str]]] = deque(
                [(changed_path, 0, [changed_path])]
            )
            visited_depth: dict[str, int] = {}
            while queue:
                current_path, depth, chain = queue.popleft()
                previous_depth = visited_depth.get(current_path)
                if previous_depth is not None and previous_depth <= depth:
                    continue
                visited_depth[current_path] = depth
                for edge in edges_by_source.get(current_path, []):
                    if edge.target_type == "test":
                        target = tests_by_key.get(edge.target_value)
                        if target is None:
                            continue
                        effective_confidence = round(edge.confidence * (0.85**depth), 6)
                        contributions[target.test_key].append(
                            {
                                "code": f"mapping:{edge.kind}",
                                "message": (
                                    f"Selected by {_KIND_LABELS.get(edge.kind, edge.kind)} "
                                    f"from {changed_path}."
                                ),
                                "changed_path": changed_path,
                                "matched_path": current_path,
                                "dependency_chain": chain,
                                "mapping_source": edge.mapping_source,
                                "mapping_version": edge.mapping_version,
                                "edge_id": edge.id,
                                "confidence": effective_confidence,
                            }
                        )
                        mapped_change_indexes.add(change_index)
                    elif edge.target_type == "file" and depth < MAX_DEPENDENCY_DEPTH:
                        target_path = edge.target_value
                        queue.append((target_path, depth + 1, [*chain, target_path]))

    safety_reasons = set(preexisting_safety_reasons)
    safety_reasons.update(critical_reasons)
    if not changes:
        safety_reasons.add("no_changed_files")
    unmapped_indexes = set(range(len(changes))) - mapped_change_indexes
    if unmapped_indexes:
        safety_reasons.add("unmapped_changed_files")

    full_suite_required = bool(safety_reasons)
    status = "FULL_SUITE_REQUIRED" if full_suite_required else "FOCUSED_SUBSET"

    decisions: list[dict[str, Any]] = []
    for test in sorted(tests, key=lambda item: (item.test_identity, item.test_key)):
        mandatory = _is_mandatory_test(test)
        reasons = list(contributions.get(test.test_key, []))
        if mandatory:
            reasons.append(
                {
                    "code": "mandatory_policy",
                    "message": "Included by the reviewed mandatory critical-test policy.",
                    "mapping_source": "trusted_policy",
                    "mapping_version": IMPACT_POLICY_VERSION,
                    "confidence": 1.0,
                }
            )
        unique_reasons: dict[tuple[Any, ...], dict[str, Any]] = {}
        for reason in reasons:
            identity = (
                reason.get("code"),
                reason.get("changed_path"),
                reason.get("matched_path"),
                reason.get("edge_id"),
            )
            unique_reasons[identity] = reason
        reasons = sorted(
            unique_reasons.values(),
            key=lambda reason: (
                -float(reason.get("confidence") or 0),
                str(reason.get("code")),
                str(reason.get("changed_path") or ""),
            ),
        )
        confidences = [float(reason.get("confidence") or 0) for reason in reasons]
        combined = 1.0 - math.prod(
            1.0 - min(max(value, 0.0), 1.0) for value in confidences
        )
        combined = round(combined, 6)
        base_selected = full_suite_required or mandatory or bool(reasons)
        if full_suite_required and not reasons:
            reasons.append(
                {
                    "code": "full_suite_safety_fallback",
                    "message": "Included because trusted evidence was insufficient for a narrow subset.",
                    "mapping_source": "safety_policy",
                    "mapping_version": IMPACT_POLICY_VERSION,
                    "confidence": 1.0,
                }
            )
        score = round((100.0 * combined) + (50.0 if mandatory else 0.0), 6)
        decisions.append(
            {
                "test": test,
                "mandatory": mandatory,
                "base_selected": base_selected,
                "score": score,
                "confidence": _confidence_label(combined, mandatory=mandatory),
                "reason_codes": sorted({str(reason["code"]) for reason in reasons}),
                "reasons": reasons,
                "mapping_edge_ids": sorted(
                    {
                        str(reason["edge_id"])
                        for reason in reasons
                        if reason.get("edge_id")
                    }
                ),
                "exclusion_reason": (
                    None
                    if base_selected
                    else "No trusted mapping connects this test to the validated change set."
                ),
            }
        )

    selected = [item for item in decisions if item["base_selected"]]
    selected.sort(
        key=lambda item: (
            not item["mandatory"],
            -float(item["score"]),
            item["test"].test_identity,
            item["test"].test_key,
        )
    )
    ranks = {item["test"].test_key: index for index, item in enumerate(selected, 1)}
    for item in decisions:
        item["rank"] = ranks.get(item["test"].test_key)

    full_duration = sum(test.estimated_duration_ms or 0.0 for test in tests)
    selected_duration = sum(
        item["test"].estimated_duration_ms or 0.0
        for item in decisions
        if item["base_selected"]
    )
    metrics = {
        "changed_file_count": len(changes),
        "mapped_changed_file_count": len(mapped_change_indexes),
        "unmapped_changed_file_count": len(unmapped_indexes),
        "test_catalog_count": len(tests),
        "mandatory_test_count": sum(1 for test in tests if _is_mandatory_test(test)),
        "base_selected_test_count": len(selected),
        "base_excluded_test_count": len(tests) - len(selected),
        "base_selected_fraction": round(len(selected) / len(tests), 6)
        if tests
        else None,
        "estimated_full_duration_ms": round(full_duration, 3),
        "estimated_selected_duration_ms": round(selected_duration, 3),
        "estimated_duration_reduction_ms": round(
            max(full_duration - selected_duration, 0.0), 3
        ),
        "dependency_depth_limit": MAX_DEPENDENCY_DEPTH,
    }
    if full_suite_required:
        summary = (
            "Full-suite execution is required because the validated change/mapping evidence "
            "does not safely support narrowing test scope."
        )
    else:
        summary = (
            f"Selected {len(selected)} of {len(tests)} tests from explicit, versioned "
            "mappings; this is advisory and does not skip tests automatically."
        )
    return {
        "status": status,
        "full_suite_required": full_suite_required,
        "summary": summary,
        "safety_reasons": sorted(safety_reasons),
        "metrics": metrics,
        "decisions": decisions,
    }


def select_impacted_tests(
    *,
    tests: list[ImpactTestDefinition],
    edges: list[ImpactMappingEdge],
    changes: list[dict[str, Any]],
    preexisting_safety_reasons: Iterable[str] = (),
) -> dict[str, Any]:
    """Public deterministic core shared by runtime and evaluation.

    The caller is responsible for validating comparison provenance and mapping
    snapshot trust, then passing any resulting safety reasons.
    """
    return _selection_engine(
        tests=tests,
        edges=edges,
        changes=changes,
        preexisting_safety_reasons=preexisting_safety_reasons,
    )


def _resolve_changed_input(
    session: Session,
    run: Run,
    changed_input_id: str | None,
) -> RunInput:
    if changed_input_id:
        changed_input = session.get(RunInput, changed_input_id)
        if (
            changed_input is None
            or changed_input.run_id != run.id
            or changed_input.kind != "changed-files"
        ):
            raise ValueError("changed-file input does not belong to the selected run")
        return changed_input
    candidates = list(
        session.scalars(
            select(RunInput).where(
                RunInput.run_id == run.id,
                RunInput.kind == "changed-files",
            )
        ).all()
    )
    if not candidates:
        raise ValueError("selected run has no changed-files input")
    if len(candidates) > 1:
        raise ValueError(
            "selected run has multiple changed-files inputs; choose one explicitly"
        )
    return candidates[0]


def create_impact_recommendation(
    session: Session,
    project: Project,
    request: ImpactRecommendationCreate,
) -> ImpactRecommendation:
    run = session.scalar(
        select(Run).where(Run.id == request.run_id).options(selectinload(Run.inputs))
    )
    if run is None or run.project_id != project.id:
        raise ValueError("run does not belong to the selected project")
    snapshot = session.scalar(
        select(ImpactMappingSnapshot)
        .where(ImpactMappingSnapshot.id == request.mapping_snapshot_id)
        .options(*_snapshot_options())
    )
    if snapshot is None or snapshot.project_id != project.id:
        raise ValueError("mapping snapshot does not belong to the selected project")
    changed_input = _resolve_changed_input(session, run, request.changed_input_id)
    changes = _normalized_changed_files(changed_input)
    base_sha_value = changed_input.metadata_json.get("base_sha")
    head_sha_value = changed_input.metadata_json.get("head_sha")
    base_sha = str(base_sha_value) if base_sha_value is not None else None
    head_sha = str(head_sha_value) if head_sha_value is not None else None
    if request.base_sha is not None and (
        base_sha is None or request.base_sha.casefold() != base_sha.casefold()
    ):
        raise ValueError("requested base SHA does not match changed-file evidence")
    if request.head_sha is not None and (
        head_sha is None or request.head_sha.casefold() != head_sha.casefold()
    ):
        raise ValueError("requested head SHA does not match changed-file evidence")

    comparison_reasons = _comparison_safety_reasons(
        run,
        changed_input,
        base_sha=base_sha,
        head_sha=head_sha,
    )
    mapping_reasons: list[str] = []
    if not snapshot.trusted:
        mapping_reasons.append("mapping_snapshot_untrusted")
    if not snapshot.coverage_complete:
        mapping_reasons.append("mapping_coverage_incomplete")
    preexisting_reasons = sorted({*comparison_reasons, *mapping_reasons})
    result = select_impacted_tests(
        tests=list(snapshot.tests),
        edges=list(snapshot.edges),
        changes=changes,
        preexisting_safety_reasons=preexisting_reasons,
    )

    changed_files_digest = changed_input.digest or _canonical_digest(changes)
    input_payload = {
        "schema_version": "impact-recommendation-input-v1",
        "project_id": project.id,
        "run_id": run.id,
        "run_manifest_digest": run.manifest_digest,
        "changed_input_id": changed_input.id,
        "changed_files_digest": changed_files_digest,
        "mapping_snapshot_id": snapshot.id,
        "mapping_source_digest": snapshot.source_digest,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "engine_version": IMPACT_ENGINE_VERSION,
        "policy_version": snapshot.policy_version,
        "changes": changes,
    }
    input_digest = _canonical_digest(input_payload)
    existing = session.scalar(
        select(ImpactRecommendation)
        .where(
            ImpactRecommendation.project_id == project.id,
            ImpactRecommendation.input_digest == input_digest,
        )
        .options(*_recommendation_options())
    )
    if existing is not None:
        return existing

    recommendation = ImpactRecommendation(
        project_id=project.id,
        run_id=run.id,
        changed_input_id=changed_input.id,
        mapping_snapshot_id=snapshot.id,
        base_sha=base_sha,
        head_sha=head_sha,
        input_digest=input_digest,
        changed_files_digest=changed_files_digest,
        engine_version=IMPACT_ENGINE_VERSION,
        policy_version=snapshot.policy_version,
        status=result["status"],
        current_revision=0,
        comparison_trusted=not comparison_reasons,
        mapping_complete=(
            snapshot.trusted
            and snapshot.coverage_complete
            and "unmapped_changed_files" not in result["safety_reasons"]
            and "no_changed_files" not in result["safety_reasons"]
        ),
        full_suite_required=result["full_suite_required"],
        summary=result["summary"],
        changed_files=changes,
        safety_reasons=result["safety_reasons"],
        metrics=result["metrics"],
    )
    session.add(recommendation)
    session.flush()
    for decision in result["decisions"]:
        test = decision["test"]
        session.add(
            ImpactRecommendationItem(
                recommendation_id=recommendation.id,
                test_key=test.test_key,
                test_identity=test.test_identity,
                source_path=test.source_path,
                criticality=test.criticality,
                mandatory=decision["mandatory"],
                base_selected=decision["base_selected"],
                rank=decision["rank"],
                score=decision["score"],
                confidence=decision["confidence"],
                reason_codes=decision["reason_codes"],
                reasons=decision["reasons"],
                mapping_edge_ids=decision["mapping_edge_ids"],
                exclusion_reason=decision["exclusion_reason"],
            )
        )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(ImpactRecommendation)
            .where(
                ImpactRecommendation.project_id == project.id,
                ImpactRecommendation.input_digest == input_digest,
            )
            .options(*_recommendation_options())
        )
        if existing is not None:
            return existing
        raise
    return get_impact_recommendation(session, recommendation.id) or recommendation


def get_impact_recommendation(
    session: Session, recommendation_id: str
) -> ImpactRecommendation | None:
    return session.scalar(
        select(ImpactRecommendation)
        .where(ImpactRecommendation.id == recommendation_id)
        .options(*_recommendation_options())
    )


def list_project_recommendations(
    session: Session,
    project_id: str,
    *,
    limit: int,
    offset: int,
) -> list[ImpactRecommendation]:
    return list(
        session.scalars(
            select(ImpactRecommendation)
            .where(ImpactRecommendation.project_id == project_id)
            .options(*_recommendation_options())
            .order_by(ImpactRecommendation.created_at.desc(), ImpactRecommendation.id)
            .limit(limit)
            .offset(offset)
        ).all()
    )


def list_mapping_snapshots(
    session: Session,
    project_id: str,
    *,
    limit: int,
    offset: int,
) -> list[ImpactMappingSnapshot]:
    return list(
        session.scalars(
            select(ImpactMappingSnapshot)
            .where(ImpactMappingSnapshot.project_id == project_id)
            .options(*_snapshot_options())
            .order_by(ImpactMappingSnapshot.created_at.desc(), ImpactMappingSnapshot.id)
            .limit(limit)
            .offset(offset)
        ).all()
    )


def _latest_overrides(
    recommendation: ImpactRecommendation,
) -> dict[str, ImpactOverride]:
    latest: dict[str, ImpactOverride] = {}
    for override in sorted(
        recommendation.overrides,
        key=lambda item: (item.revision_after, item.created_at, item.id),
    ):
        latest[override.test_key] = override
    return latest


def _effective_selected(
    item: ImpactRecommendationItem,
    latest: dict[str, ImpactOverride],
) -> tuple[bool, str]:
    override = latest.get(item.test_key)
    if override is None:
        return item.base_selected, "engine"
    return override.action == "include", f"override:{override.id}"


def apply_impact_override(
    session: Session,
    recommendation: ImpactRecommendation,
    request: ImpactOverrideCreate,
    *,
    principal: Principal | None = None,
    actor: str | None = None,
) -> ImpactRecommendation:
    if recommendation.current_revision != request.expected_revision:
        raise ValueError(
            "impact recommendation revision conflict: expected "
            f"{request.expected_revision}, current {recommendation.current_revision}"
        )
    item = next(
        (
            candidate
            for candidate in recommendation.items
            if candidate.test_key == request.test_key
        ),
        None,
    )
    if item is None:
        raise ValueError("test key is not part of this impact recommendation")
    if request.action == "exclude":
        if recommendation.full_suite_required:
            raise ValueError(
                "tests cannot be excluded while full-suite execution is required"
            )
        if item.mandatory or item.criticality == "critical":
            raise ValueError("mandatory critical tests cannot be excluded")

    latest = _latest_overrides(recommendation)
    current_selected, _ = _effective_selected(item, latest)
    requested_selected = request.action == "include"
    if current_selected == requested_selected:
        raise ValueError("override would not change the effective selection")

    revision_before = recommendation.current_revision
    revision_after = revision_before + 1
    updated_id = session.scalar(
        update(ImpactRecommendation)
        .where(
            ImpactRecommendation.id == recommendation.id,
            ImpactRecommendation.current_revision == revision_before,
        )
        .values(current_revision=revision_after, updated_at=utcnow())
        .returning(ImpactRecommendation.id)
    )
    if updated_id is None:
        session.rollback()
        raise ValueError("impact recommendation revision conflict")
    effective_principal = principal or Principal(
        kind="user",
        actor_id=None,
        display_name=(actor or "legacy reviewer").strip(),
    )
    event = ImpactOverride(
        recommendation_id=recommendation.id,
        actor=effective_principal.display_name,
        actor_kind=effective_principal.audit_kind,
        actor_user_id=effective_principal.user_id,
        action=request.action,
        test_key=request.test_key,
        reason=request.reason,
        revision_before=revision_before,
        revision_after=revision_after,
    )
    session.add(event)
    session.flush()
    record_audit_event(
        session,
        effective_principal,
        action="impact.override_created",
        resource_type="impact_override",
        resource_id=event.id,
        project_id=recommendation.project_id,
        reason=request.reason,
        details={
            "recommendation_id": recommendation.id,
            "test_key": request.test_key,
            "override_action": request.action,
            "revision_before": revision_before,
            "revision_after": revision_after,
        },
    )
    session.commit()
    session.expire_all()
    refreshed = get_impact_recommendation(session, recommendation.id)
    if refreshed is None:
        raise RuntimeError("impact recommendation disappeared after override")
    return refreshed


def impact_recommendation_to_schema(
    recommendation: ImpactRecommendation,
) -> ImpactRecommendationRead:
    latest = _latest_overrides(recommendation)
    selected: list[ImpactRecommendationItemRead] = []
    excluded: list[ImpactRecommendationItemRead] = []
    for item in recommendation.items:
        effective, source = _effective_selected(item, latest)
        view = ImpactRecommendationItemRead(
            id=item.id,
            test_key=item.test_key,
            test_identity=item.test_identity,
            source_path=item.source_path,
            criticality=item.criticality,
            mandatory=item.mandatory,
            base_selected=item.base_selected,
            effective_selected=effective,
            selection_source=source,
            rank=item.rank,
            score=item.score,
            confidence=item.confidence,
            reason_codes=item.reason_codes,
            reasons=item.reasons,
            mapping_edge_ids=item.mapping_edge_ids,
            exclusion_reason=item.exclusion_reason,
        )
        (selected if effective else excluded).append(view)

    selected.sort(
        key=lambda item: (
            item.rank is None,
            item.rank if item.rank is not None else 1_000_000,
            item.test_identity,
        )
    )
    excluded.sort(key=lambda item: (item.test_identity, item.test_key))
    metrics = {
        **recommendation.metrics,
        "effective_selected_test_count": len(selected),
        "effective_excluded_test_count": len(excluded),
        "effective_selected_fraction": round(
            len(selected) / (len(selected) + len(excluded)), 6
        )
        if selected or excluded
        else None,
    }
    return ImpactRecommendationRead(
        id=recommendation.id,
        project_id=recommendation.project_id,
        run_id=recommendation.run_id,
        changed_input_id=recommendation.changed_input_id,
        mapping_snapshot_id=recommendation.mapping_snapshot_id,
        base_sha=recommendation.base_sha,
        head_sha=recommendation.head_sha,
        input_digest=recommendation.input_digest,
        changed_files_digest=recommendation.changed_files_digest,
        engine_version=recommendation.engine_version,
        policy_version=recommendation.policy_version,
        status=recommendation.status,
        current_revision=recommendation.current_revision,
        comparison_trusted=recommendation.comparison_trusted,
        mapping_complete=recommendation.mapping_complete,
        full_suite_required=recommendation.full_suite_required,
        summary=recommendation.summary,
        changed_files=recommendation.changed_files,
        safety_reasons=recommendation.safety_reasons,
        metrics=metrics,
        selected_tests=selected,
        excluded_tests=excluded,
        overrides=[
            ImpactOverrideRead(
                id=item.id,
                actor=item.actor,
                action=item.action,
                test_key=item.test_key,
                reason=item.reason,
                revision_before=item.revision_before,
                revision_after=item.revision_after,
                created_at=item.created_at,
            )
            for item in sorted(
                recommendation.overrides,
                key=lambda event: (event.revision_after, event.created_at, event.id),
                reverse=True,
            )
        ],
        created_at=recommendation.created_at,
        updated_at=recommendation.updated_at,
    )
