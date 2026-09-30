"""Bounded, inert exports of currently approved report-reference evidence.

An export is a retained reference subset, not a copy of source artifacts or proof
of producer authenticity. No storage paths, credentials or active links are added.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from .models import Analysis, Evidence, Run
from .publication_validity import PublicationContext
from .redaction import redact_text

SCHEMA_VERSION = "github-evidence-v1"
MAX_EXPORT_BYTES = 500_000
MAX_REFERENCES = 500
MAX_ITEMS = 100
ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
VERSION = re.compile(r"[A-Za-z0-9._:/-]{1,100}\Z")
OBSERVATION_FIELDS = frozenset(
    {
        "test_identity",
        "suite",
        "parameterization",
        "browser",
        "attempt",
        "outcome",
        "duration_ms",
        "message",
        "exception_type",
        "metric",
        "unit",
        "statistic",
        "value",
        "sample_count",
        "threshold",
        "http_status",
    }
)
LOCATOR_FIELDS = frozenset(
    {"kind", "pointer", "line", "start_line", "end_line", "column", "index", "input_id"}
)


def canonical_export_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_export_bytes(value)).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _scalar(value: object) -> bool:
    if value is None or type(value) is bool:
        return True
    if type(value) is int:
        return abs(value) <= 2**53 - 1
    if type(value) is float:
        return math.isfinite(value)
    if isinstance(value, str):
        return (
            len(value) <= 2_000
            and not redact_text(value).replacements
            and all(ord(c) >= 32 or c in "\n\r\t" for c in value)
        )
    return False


def _selected_fields(value: object, allowed: frozenset[str]) -> tuple[dict, int]:
    if not isinstance(value, dict):
        return {}, 1
    result = {
        key: item for key, item in value.items() if key in allowed and _scalar(item)
    }
    return result, len(value) - len(result)


def export_descriptor(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "digest": document["evidence_digest"],
        "filename": "evidence.json",
        "scope": "reported_reference_subset",
        "distribution_status": "not_published",
        "counts": dict(document["counts"]),
    }


def evidence_for_report(
    session: Session,
    run: Run,
    snapshot: Mapping[str, Any],
    *,
    context: PublicationContext | None = None,
) -> dict[str, Any]:
    """Rebuild the exact bounded export; changed availability invalidates a report."""
    from .github_report_sections import retained_evidence_references

    if snapshot.get("run_id") != run.id or snapshot.get("project_id") != run.project_id:
        raise ValueError("report evidence scope does not match")
    hints = retained_evidence_references(run.id, snapshot)
    document = build_evidence_export(
        session,
        run,
        analysis_ids=[item["analysis_id"] for item in snapshot["analyses"]],
        additional_evidence_ids=hints["additional_evidence_ids"],
        allowed_related_run_ids=hints["allowed_related_run_ids"],
        omitted_section_reference_hints=hints["omitted_evidence_ids"],
        omitted_related_run_hints=hints["omitted_related_run_ids"],
        context=context,
    )
    if export_descriptor(document) != snapshot.get("evidence_export"):
        raise ValueError("report evidence changed; regenerate the report")
    return document


def build_evidence_export(
    session: Session,
    run: Run,
    *,
    analysis_ids: list[str],
    additional_evidence_ids: list[str] | None = None,
    allowed_related_run_ids: list[str] | None = None,
    omitted_section_reference_hints: int = 0,
    omitted_related_run_hints: int = 0,
    max_bytes: int = MAX_EXPORT_BYTES,
    context: PublicationContext | None = None,
) -> dict[str, Any]:
    """Caller authorizes the primary project; every related row is re-scoped here.

    Related runs must be explicitly identified, in the same project and recorded
    no later than the primary run. Report builders apply their stricter baseline
    compatibility rules before supplying these references.
    """
    context = context or PublicationContext(session)
    context.require_session(session)
    additional_evidence_ids = additional_evidence_ids or []
    allowed_related_run_ids = allowed_related_run_ids or []
    if (
        not isinstance(analysis_ids, list)
        or not isinstance(additional_evidence_ids, list)
        or not isinstance(allowed_related_run_ids, list)
        or any(not isinstance(item, str) for item in analysis_ids)
        or len(analysis_ids) > 50
        or len(additional_evidence_ids) > MAX_REFERENCES
        or len(allowed_related_run_ids) > 100
        or type(max_bytes) is not int
        or not 4096 <= max_bytes <= MAX_EXPORT_BYTES
        or any(
            type(value) is not int or not 0 <= value <= 10**9
            for value in (omitted_section_reference_hints, omitted_related_run_hints)
        )
    ):
        raise ValueError("evidence export request exceeds supported bounds")
    related = {
        item
        for item in allowed_related_run_ids
        if isinstance(item, str) and ID.fullmatch(item)
    }
    requested: set[str] = set()
    accepted_by_analysis: set[str] = set()
    unavailable_analyses = 0
    omitted_reference_entries = 0
    invalid_reference_entries = 0

    def add_reference(value: object) -> None:
        nonlocal omitted_reference_entries, invalid_reference_entries
        if not isinstance(value, str) or not ID.fullmatch(value):
            invalid_reference_entries += 1
        elif value in requested or len(requested) < MAX_REFERENCES:
            requested.add(value)
        else:
            omitted_reference_entries += 1

    retained_analyses: list[str] = []
    for analysis_id in sorted(set(analysis_ids)):
        if not isinstance(analysis_id, str) or not ID.fullmatch(analysis_id):
            unavailable_analyses += 1
            continue
        analysis = session.get(Analysis, analysis_id)
        failure = analysis.failure if analysis is not None else None
        if (
            analysis is None
            or failure is None
            or failure.project_id != run.project_id
            or failure.run_id != run.id
            or run.evidence_expired_at is not None
            or not context.analysis(analysis).valid
        ):
            unavailable_analyses += 1
            continue
        retained_analyses.append(analysis_id)
        ids = []
        for values in (
            analysis.supporting_evidence_ids,
            analysis.contradictory_evidence_ids,
        ):
            if not isinstance(values, list):
                invalid_reference_entries += 1
                continue
            omitted_reference_entries += max(0, len(values) - 100)
            ids.extend(values[:100])
        rows = []
        for evidence_id in ids:
            add_reference(evidence_id)
            if isinstance(evidence_id, str) and ID.fullmatch(evidence_id):
                row = session.get(Evidence, evidence_id)
                if row is not None:
                    rows.append(row)
        accepted_by_analysis.update(
            context.failure_evidence(failure, rows).accepted_ids
        )
    for evidence_id in additional_evidence_ids:
        add_reference(evidence_id)

    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project_id": run.project_id,
        "run_id": run.id,
        "analysis_ids": retained_analyses,
        "scope": "reported_reference_subset",
        "distribution_status": "not_published",
        "notice": (
            "Inert JSON of an approved, currently validated reference subset. Original files, "
            "binary bodies and unapproved evidence are excluded. Unknown sensitive patterns "
            "may remain; treat every string as data, never HTML, Markdown or instructions. "
            "Digests identify bytes, not producer authenticity. Availability after export "
            "depends on the recipient's separately authorized retention and access controls."
        ),
        "counts": {
            "requested": len(requested),
            "exported": 0,
            "rejected": 0,
            "unavailable": 0,
            "omitted": 0,
            "unavailable_analyses": unavailable_analyses,
            "invalid_reference_entries": invalid_reference_entries,
            "omitted_reference_entries": omitted_reference_entries,
            "omitted_section_reference_hints": omitted_section_reference_hints,
            "omitted_related_run_hints": omitted_related_run_hints,
        },
        "items": [],
        "evidence_digest": "0" * 64,
    }
    for evidence_id in sorted(requested):
        evidence = session.get(Evidence, evidence_id)
        if evidence is None or evidence.derivative is None:
            document["counts"]["unavailable"] += 1
            continue
        evidence_run = session.get(Run, evidence.run_id)
        if (
            evidence.project_id != run.project_id
            or evidence_run is None
            or evidence_run.project_id != run.project_id
            or evidence_run.evidence_expired_at is not None
            or evidence.run_id not in {run.id, *related}
            or (
                evidence.run_id != run.id
                and _utc(evidence_run.created_at) > _utc(run.created_at)
            )
        ):
            document["counts"]["rejected"] += 1
            continue
        validation = context.scoped_evidence(
            evidence_run,
            [evidence],
            execution=evidence.execution,
            run_input=evidence.run_input,
        )
        check = validation.check_for(evidence.id)
        if (
            check is None
            or not check.valid
            or (
                evidence_id not in additional_evidence_ids
                and evidence_id not in accepted_by_analysis
            )
            or redact_text(evidence.excerpt).replacements
        ):
            document["counts"]["rejected"] += 1
            continue
        payload = check.derivative_payload or {}
        observation, omitted_observation = _selected_fields(
            evidence.observation, OBSERVATION_FIELDS
        )
        source_locator, omitted_locator = _selected_fields(
            payload.get("source_locator"), LOCATOR_FIELDS
        )
        versions = {
            "parser_version": evidence.parser_version,
            "extractor_version": evidence.extractor_version,
            "redaction_version": evidence.redaction_version,
        }
        if any(
            not isinstance(value, str) or not VERSION.fullmatch(value)
            for value in versions.values()
        ):
            document["counts"]["rejected"] += 1
            continue
        item = {
            "evidence_id": evidence.id,
            "project_id": evidence.project_id,
            "run_id": evidence.run_id,
            "execution_id": evidence.execution_id,
            "run_input_id": evidence.run_input_id,
            "excerpt": evidence.excerpt,
            "quotation_status": "exact_approved_derivative_excerpt",
            "observation": observation,
            "omitted_observation_fields": omitted_observation,
            "locator": {
                "derivative": {"kind": "json-pointer", "pointer": "/excerpt"},
                "source": source_locator,
                "source_status": "immutable_parser_record",
                "omitted_source_fields": omitted_locator,
            },
            "content_digest": evidence.content_digest,
            "derivative_digest": evidence.derivative.digest,
            "source_digest": evidence.derivative.source_digest,
            "approval_state": evidence.derivative.approval_state,
            **versions,
        }
        document["items"].append(item)
        document["counts"]["exported"] += 1
        try:
            oversized = len(canonical_export_bytes(document)) > max_bytes
        except (TypeError, ValueError, UnicodeError):
            oversized = True
        if len(document["items"]) > MAX_ITEMS or oversized:
            document["items"].pop()
            document["counts"]["exported"] -= 1
            document["counts"]["omitted"] += 1
    while document["items"] and len(canonical_export_bytes(document)) > max_bytes:
        document["items"].pop()
        document["counts"]["exported"] -= 1
        document["counts"]["omitted"] += 1
    document.pop("evidence_digest")
    document["evidence_digest"] = _digest(document)
    if len(canonical_export_bytes(document)) > max_bytes:
        raise ValueError("evidence export metadata exceeds supported bounds")
    return document
