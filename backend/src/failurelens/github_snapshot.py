"""Read-only, project-authorized-by-caller report projection for CLI and API."""

from __future__ import annotations

import json
from collections import Counter
from hashlib import sha256
from typing import Any, NotRequired, TypedDict, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from .evidence_validation import (
    persisted_analysis_is_publication_validated,
    validate_evidence_records,
)
from .github_evidence import build_evidence_export, export_descriptor
from .github_report import (
    UnvalidatedAnalysis,
    _publication_category,
    _safe,
    advisory_status,
    render_markdown,
)
from .github_report_sections import (
    advisory_reasons,
    logical_groups,
    render_sections,
    report_sections,
    retained_evidence_references,
)
from .models import Analysis, Failure, Run, RunInput, TestExecution
from .redaction import redact_text
from .service import select_failure_evidence


def latest_analyses(session: Session, run: Run) -> list[Analysis]:
    rows = session.scalars(
        select(Analysis)
        .join(Failure)
        .where(Failure.run_id == run.id)
        .order_by(Analysis.failure_id, Analysis.revision.desc(), Analysis.id)
    ).all()
    latest: dict[str, Analysis] = {}
    for item in rows:
        latest.setdefault(item.failure_id, item)
    return list(latest.values())


INPUT_STATES = ("accepted", "restricted", "missing", "rejected", "unsupported")
MAX_SNAPSHOT_BYTES = 100_000


def _text(value: object, limit: int = 240) -> str | None:
    if value is None:
        return None
    # JSON consumers must treat strings as data, never shell/Markdown instructions.
    return " ".join(redact_text(str(value)).text.split()).replace("@", "@\u200b")[
        :limit
    ]


class _InputDetail(TypedDict):
    input_id: str | None
    kind: str | None
    required: bool
    status: str


class _InputSummary(TypedDict):
    expected: int | None
    received: int
    declared_shards: int | None
    required: int
    accepted_required: int
    states: dict[str, int]
    items: list[_InputDetail]
    omitted_inputs: int


class _NextInvestigation(TypedDict):
    action: str


class _AnalysisDetail(TypedDict):
    analysis_id: str
    failure_id: str
    revision: int
    category: str
    summary: str
    supporting_evidence_ids: list[str]
    contradictory_evidence_ids: list[str]
    missing_evidence: list[str]
    next_investigation: list[_NextInvestigation]
    stored_supporting_evidence_count: int
    stored_contradictory_evidence_count: int
    omitted_supporting_evidence_ids: int
    omitted_contradictory_evidence_ids: int
    omitted_missing_evidence: int
    omitted_next_investigation: int


class ReportSnapshot(TypedDict):
    schema_version: str
    project_id: str
    run_id: str
    external_id: str | None
    attempt: int
    framework: str | None
    environment: str | None
    repository: str | None
    tested_head: str | None
    base_sha: str | None
    run_scope: str | None
    run_status: str
    advisory_status: str
    advisory_reasons: list[str]
    inputs: _InputSummary
    completeness: str
    outcomes: dict[str, int]
    analysis_count: int
    analysis_manifest: dict[str, Any]
    analyses: list[_AnalysisDetail]
    omitted_analyses: int
    baseline_status: str
    skipped_tests: dict[str, Any]
    impact: dict[str, Any]
    clusters: dict[str, Any]
    performance: dict[str, Any]
    baseline: dict[str, Any]
    evidence_export: dict[str, Any]
    markdown: str
    report_digest: NotRequired[str]


def _input_summary(session: Session, run: Run) -> _InputSummary:
    inputs = session.scalars(
        select(RunInput)
        .where(RunInput.run_id == run.id)
        .order_by(RunInput.input_id, RunInput.id)
    ).all()
    states = Counter(
        item.status if item.status in INPUT_STATES else "unknown" for item in inputs
    )
    return {
        "expected": run.expected_inputs,
        "received": run.received_inputs,
        "declared_shards": run.shard_count,
        "required": sum(item.required for item in inputs),
        "accepted_required": sum(
            item.required and item.status == "accepted" for item in inputs
        ),
        "states": {state: states[state] for state in (*INPUT_STATES, "unknown")},
        "items": [
            {
                "input_id": _text(item.input_id, 120),
                "kind": _text(item.kind, 80),
                "required": item.required,
                "status": item.status if item.status in INPUT_STATES else "unknown",
            }
            for item in inputs[:50]
        ],
        "omitted_inputs": max(0, len(inputs) - 50),
    }


def _snapshot_markdown(
    run: Run,
    safe_analyses: list[Analysis | UnvalidatedAnalysis],
    inputs: _InputSummary,
    outcomes: dict[str, int],
    details: list[_AnalysisDetail],
    analysis_count: int,
    sections: dict[str, Any],
    extra_holds: list[str],
    status: str,
) -> str:
    markdown = render_markdown(run, safe_analyses, status_override=status)
    if extra_holds:
        markdown += "\nAdditional advisory holds: " + ", ".join(extra_holds) + ".\n"
    markdown += "\n### Input completeness\n\n"
    markdown += (
        f"Required inputs accepted: {inputs['accepted_required']}/{inputs['required']}; "
        f"declared shards: {inputs['declared_shards'] if inputs['declared_shards'] is not None else 'unspecified'}.\n"
    )
    for input_detail in inputs["items"]:
        markdown += f"- `{_safe(input_detail['input_id'])}`: {input_detail['status']} ({'required' if input_detail['required'] else 'optional'})\n"
    if inputs["omitted_inputs"]:
        markdown += f"{inputs['omitted_inputs']} input details omitted; counters cover all inputs.\n"
    markdown += "\n### Execution outcomes\n\n"
    markdown += (
        f"Logical tests: {outcomes['logical_tests']}; attempts: {outcomes['attempts']}; "
        f"retried logical tests: {outcomes['retried']}; retry-recovered: {outcomes['retry_recovered']}.\n"
    )
    markdown += (
        "; ".join(
            f"{key}: {outcomes[key]}"
            for key in ("passed", "failed", "skipped", "cancelled", "unknown")
        )
        + ".\n"
    )
    markdown += "Final outcomes collapse attempts by project/repository/framework/test/suite/source path/parameterization and browser. Missing tests are not counted as passed.\n"
    markdown += f"Run scope: `{_safe(run.run_scope)}`. Baseline: {_safe(sections['baseline']['status']).upper()}; comparison evidence and limitations follow below.\n"
    markdown += "\n### Investigations\n\n"
    for item in details:
        markdown += f"- Analysis `{_safe(item['analysis_id'])}` revision {item['revision']}: `{item['category']}`\n"
        markdown += f"  {_safe(item['summary'])}\n"
        for label, evidence_ids in (
            ("Supporting", item["supporting_evidence_ids"]),
            ("Contradictory", item["contradictory_evidence_ids"]),
        ):
            markdown += (
                f"  {label} evidence IDs: "
                + (
                    ", ".join(f"`{_safe(x)}`" for x in evidence_ids[:10])
                    or "none recorded"
                )
                + ".\n"
            )
        if (
            item["omitted_supporting_evidence_ids"]
            or item["omitted_contradictory_evidence_ids"]
        ):
            markdown += (
                f"  Evidence references omitted or unavailable: {item['omitted_supporting_evidence_ids']} supporting / "
                f"{item['omitted_contradictory_evidence_ids']} contradictory.\n"
            )
        for missing in item["missing_evidence"]:
            markdown += f"  Missing: {_safe(missing)}\n"
        for action in item["next_investigation"]:
            markdown += f"  Investigate: {_safe(action['action'])}\n"
        if item["omitted_missing_evidence"] or item["omitted_next_investigation"]:
            markdown += (
                f"  Details omitted or unavailable: {item['omitted_missing_evidence']} missing-evidence notices / "
                f"{item['omitted_next_investigation']} investigations.\n"
            )
    if analysis_count > len(details):
        markdown += f"\n{analysis_count - len(details)} additional investigations omitted from this bounded preview.\n"
    markdown += render_sections(sections)
    markdown += "\nEvidence IDs resolve through the authorized API; they are not public artifact URLs. A separately generated evidence.json can retain approved referenced excerpts. This preview does not publish that file; its JSON descriptor records scope and omissions.\n"
    # Comments have a byte limit. Never truncate through a claim; bound by complete lines.
    if len(markdown.encode()) > 50_000:
        lines, size = [], 0
        for line in markdown.splitlines(keepends=True):
            size += len(line.encode())
            if size > 49_000:
                break
            lines.append(line)
        markdown = (
            "".join(lines)
            + "\nAdditional detail omitted by publication byte limit. Review the authenticated full report.\n"
        )
    return markdown


def report_snapshot(session: Session, run: Run) -> ReportSnapshot:
    analyses = latest_analyses(session, run)
    executions = session.scalars(
        select(TestExecution)
        .where(TestExecution.run_id == run.id)
        .order_by(
            TestExecution.test_identity,
            TestExecution.browser,
            TestExecution.attempt,
            TestExecution.id,
        )
    ).all()
    groups = logical_groups(run, list(executions))
    counts = Counter(items[-1].outcome.value for items in groups)
    outcomes = {
        key: counts[key]
        for key in ("passed", "failed", "skipped", "cancelled", "unknown")
    }
    outcomes.update(
        logical_tests=len(groups),
        attempts=len(executions),
        retried=sum(len(items) > 1 for items in groups),
        retry_recovered=sum(
            len(items) > 1
            and items[-1].outcome.value == "passed"
            and any(item.outcome.value == "failed" for item in items[:-1])
            for items in groups
        ),
    )
    expired = run.evidence_expired_at is not None
    current_validity: dict[str, bool] = {}
    safe_analyses: list[Analysis | UnvalidatedAnalysis] = []
    for analysis in analyses:
        accepted = set()
        if not expired and persisted_analysis_is_publication_validated(analysis):
            rows = select_failure_evidence(session, analysis.failure)
            accepted = set(
                validate_evidence_records(analysis.failure, rows).accepted_ids
            )
        cited = set(
            analysis.supporting_evidence_ids + analysis.contradictory_evidence_ids
        )
        valid = (
            not expired
            and persisted_analysis_is_publication_validated(analysis)
            and cited.issubset(accepted)
        )
        if (
            analysis.category.value != "insufficient_evidence"
            and not analysis.supporting_evidence_ids
        ):
            valid = False
        current_validity[analysis.id] = valid
        safe_analyses.append(
            analysis
            if valid
            else UnvalidatedAnalysis(
                category=analysis.category,
                validation_version=None,
                validation_results=None,
            )
        )
    details: list[_AnalysisDetail] = []
    for analysis in analyses[:50]:
        validated = current_validity[analysis.id]
        category = (
            _publication_category(analysis) if validated else "insufficient_evidence"
        )
        details.append(
            {
                "analysis_id": analysis.id,
                "failure_id": analysis.failure_id,
                "revision": analysis.revision,
                "category": category,
                "summary": redact_text(analysis.summary).text[:1500]
                if validated and not expired
                else "Evidence unavailable or publication validation incomplete; review required.",
                "supporting_evidence_ids": analysis.supporting_evidence_ids[:10]
                if validated and not expired
                else [],
                "contradictory_evidence_ids": analysis.contradictory_evidence_ids[:10]
                if validated and not expired
                else [],
                "missing_evidence": [
                    redact_text(str(x)).text[:400]
                    for x in analysis.missing_evidence[:10]
                ]
                if not expired
                else ["Evidence expired"],
                "stored_supporting_evidence_count": len(
                    analysis.supporting_evidence_ids
                ),
                "stored_contradictory_evidence_count": len(
                    analysis.contradictory_evidence_ids
                ),
                "omitted_supporting_evidence_ids": max(
                    0, len(analysis.supporting_evidence_ids) - 10
                )
                if validated and not expired
                else len(analysis.supporting_evidence_ids),
                "omitted_contradictory_evidence_ids": max(
                    0, len(analysis.contradictory_evidence_ids) - 10
                )
                if validated and not expired
                else len(analysis.contradictory_evidence_ids),
                "omitted_missing_evidence": max(0, len(analysis.missing_evidence) - 10)
                if not expired
                else len(analysis.missing_evidence),
                "omitted_next_investigation": max(
                    0, len(analysis.next_investigation) - 5
                )
                if validated and not expired
                else len(analysis.next_investigation),
                "next_investigation": [
                    {"action": redact_text(str(x.get("action", ""))).text[:400]}
                    for x in analysis.next_investigation[:5]
                ]
                if validated and not expired
                else [],
            }
        )
    inputs = _input_summary(session, run)
    sections = report_sections(session, run, groups)
    extra_holds = advisory_reasons(run, sections)
    status = "HOLD_FOR_REVIEW" if extra_holds else advisory_status(run, safe_analyses)
    markdown = _snapshot_markdown(
        run,
        safe_analyses,
        inputs,
        outcomes,
        details,
        len(analyses),
        sections,
        extra_holds,
        status,
    )
    result: ReportSnapshot = {
        "schema_version": "github-report-v2",
        "project_id": run.project_id,
        "run_id": run.id,
        "external_id": _text(run.external_id),
        "attempt": run.attempt,
        "framework": _text(run.framework),
        "environment": _text(run.environment),
        "repository": _text(run.repository),
        "tested_head": _text(run.commit_sha, 64),
        "base_sha": _text(run.base_sha, 64),
        "run_scope": _text(run.run_scope, 40),
        "run_status": run.status.value,
        "advisory_status": status,
        "advisory_reasons": extra_holds,
        "inputs": inputs,
        "completeness": "evidence_expired" if expired else run.completeness,
        "outcomes": outcomes,
        "analysis_count": len(analyses),
        "analysis_manifest": {
            "schema_version": "report-analysis-revisions-v1",
            "count": len(analyses),
            "digest": sha256(
                json.dumps(
                    {
                        "schema_version": "report-analysis-revisions-v1",
                        "items": [
                            {
                                "analysis_id": item.id,
                                "failure_id": item.failure_id,
                                "revision": item.revision,
                            }
                            for item in analyses
                        ],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
        },
        "analyses": details,
        "omitted_analyses": len(analyses) - len(details),
        "baseline_status": sections["baseline"]["status"],
        "skipped_tests": sections["skipped_tests"],
        "impact": sections["impact"],
        "clusters": sections["clusters"],
        "performance": sections["performance"],
        "baseline": sections["baseline"],
        # Reserve the descriptor's maximum count widths before trimming details.
        # These temporary values are replaced before this projection is returned.
        "evidence_export": {
            "schema_version": "github-evidence-v1",
            "digest": "0" * 64,
            "filename": "evidence.json",
            "scope": "reported_reference_subset",
            "distribution_status": "not_published",
            "counts": {
                key: 10**18
                for key in (
                    "requested",
                    "exported",
                    "rejected",
                    "unavailable",
                    "omitted",
                    "unavailable_analyses",
                    "invalid_reference_entries",
                    "omitted_reference_entries",
                    "omitted_section_reference_hints",
                    "omitted_related_run_hints",
                )
            },
        },
        "markdown": markdown,
    }
    # Remove whole records, retaining exact aggregate and omission counters.
    detail_lists: list[tuple[list[Any], dict[str, Any], str]] = [
        (result["analyses"], cast(dict[str, Any], result), "omitted_analyses")
    ]
    detail_lists.extend(
        (sections[name]["items"], sections[name], "omitted_items")
        for name in ("skipped_tests", "impact", "clusters", "performance", "baseline")
    )
    while len(json.dumps(result, sort_keys=True).encode()) > MAX_SNAPSHOT_BYTES - 100:
        populated = [(rows, owner, key) for rows, owner, key in detail_lists if rows]
        if not populated:
            break
        rows, owner, key = max(
            populated, key=lambda entry: len(json.dumps(entry[0][-1]).encode())
        )
        rows.pop()
        owner[key] += 1
        result["markdown"] = _snapshot_markdown(
            run,
            safe_analyses,
            inputs,
            outcomes,
            details,
            len(analyses),
            sections,
            extra_holds,
            status,
        )
    # JSON escaping can expand non-ASCII Markdown beyond its UTF-8 byte bound.
    # Keep complete lines and a visible notice; exact numeric counters stay outside
    # the Markdown/detail budget and are never dropped.
    if len(json.dumps(result, sort_keys=True).encode()) > MAX_SNAPSHOT_BYTES - 100:
        lines = result["markdown"].splitlines(keepends=True)
        notice = "\nAdditional detail omitted by JSON byte limit. Review the authenticated full report.\n"
        while lines:
            lines.pop()
            result["markdown"] = "".join(lines) + notice
            if (
                len(json.dumps(result, sort_keys=True).encode())
                <= MAX_SNAPSHOT_BYTES - 100
            ):
                break
    hints = retained_evidence_references(run.id, result)
    document = build_evidence_export(
        session,
        run,
        analysis_ids=[item["analysis_id"] for item in result["analyses"]],
        additional_evidence_ids=hints["additional_evidence_ids"],
        allowed_related_run_ids=hints["allowed_related_run_ids"],
        omitted_section_reference_hints=hints["omitted_evidence_ids"],
        omitted_related_run_hints=hints["omitted_related_run_ids"],
    )
    result["evidence_export"] = export_descriptor(document)
    result["report_digest"] = sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return result
