"""Read-only, project-authorized-by-caller report projection for CLI and API."""
from __future__ import annotations
from collections import Counter, defaultdict
from hashlib import sha256
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .evidence_validation import persisted_analysis_is_publication_validated
from .github_report import _safe, _publication_category, render_markdown
from .models import Analysis, Failure, Run, TestExecution
from .redaction import redact_text


def latest_analyses(session: Session, run: Run) -> list[Analysis]:
    rows = session.scalars(select(Analysis).join(Failure).where(Failure.run_id == run.id)
                           .order_by(Analysis.failure_id, Analysis.revision.desc(), Analysis.id)).all()
    latest = {}
    for item in rows:
        latest.setdefault(item.failure_id, item)
    return list(latest.values())


def report_snapshot(session: Session, run: Run) -> dict:
    analyses = latest_analyses(session, run)
    executions = session.scalars(select(TestExecution).where(TestExecution.run_id == run.id)
                                 .order_by(TestExecution.test_identity, TestExecution.browser, TestExecution.attempt, TestExecution.id)).all()
    groups = defaultdict(list)
    for execution in executions:
        groups[(execution.test_identity, execution.browser, execution.parameterization)].append(execution)
    counts = Counter(items[-1].outcome.value for items in groups.values())
    outcomes = {key: counts[key] for key in ("passed", "failed", "skipped", "cancelled", "unknown")}
    outcomes.update(logical_tests=len(groups), attempts=len(executions),
                    retried=sum(len(items) > 1 for items in groups.values()),
                    retry_recovered=sum(len(items) > 1 and items[-1].outcome.value == "passed" and
                                        any(item.outcome.value == "failed" for item in items[:-1]) for items in groups.values()))
    expired = run.evidence_expired_at is not None
    details = []
    for analysis in analyses[:50]:
        category = "insufficient_evidence" if expired else _publication_category(analysis)
        validated = persisted_analysis_is_publication_validated(analysis)
        details.append({
            "analysis_id": analysis.id, "failure_id": analysis.failure_id, "revision": analysis.revision,
            "category": category,
            "summary": redact_text(analysis.summary).text[:1500] if validated and not expired else "Evidence unavailable or publication validation incomplete; review required.",
            "supporting_evidence_ids": analysis.supporting_evidence_ids if validated and not expired else [],
            "contradictory_evidence_ids": analysis.contradictory_evidence_ids if validated and not expired else [],
            "missing_evidence": [redact_text(str(x)).text[:400] for x in analysis.missing_evidence[:10]] if not expired else ["Evidence expired"],
            "next_investigation": [{"action": redact_text(str(x.get("action", ""))).text[:400]} for x in analysis.next_investigation[:5]] if validated and not expired else [],
        })
    markdown = render_markdown(run, analyses)
    markdown += "\n### Execution outcomes\n\n"
    markdown += (f"Logical tests: {outcomes['logical_tests']}; attempts: {outcomes['attempts']}; "
                 f"retried logical tests: {outcomes['retried']}; retry-recovered: {outcomes['retry_recovered']}.\n")
    markdown += "; ".join(f"{key}: {outcomes[key]}" for key in ("passed", "failed", "skipped", "cancelled", "unknown")) + ".\n"
    markdown += "Final outcomes collapse attempts by test/browser/parameterization. Missing tests are not counted as passed.\n"
    markdown += f"Run scope: `{_safe(run.run_scope)}`. Baseline: UNKNOWN; no new/existing failure claim is made.\n"
    markdown += "Impact exclusions and performance comparisons must be inspected in the authenticated dashboard; absence here is not a clean result.\n"
    markdown += "\n### Investigations\n\n"
    for item in details:
        markdown += f"- Analysis `{_safe(item['analysis_id'])}` revision {item['revision']}: `{item['category']}`\n"
        markdown += f"  {_safe(item['summary'])}\n"
        for label, key in (("Supporting", "supporting_evidence_ids"), ("Contradictory", "contradictory_evidence_ids")):
            markdown += f"  {label} evidence IDs: " + (", ".join(f"`{_safe(x)}`" for x in item[key][:10]) or "none recorded") + ".\n"
        for missing in item["missing_evidence"]:
            markdown += f"  Missing: {_safe(missing)}\n"
        for action in item["next_investigation"]:
            markdown += f"  Investigate: {_safe(action['action'])}\n"
    if len(analyses) > len(details):
        markdown += f"\n{len(analyses) - len(details)} additional investigations omitted from this bounded preview.\n"
    markdown += "\nEvidence IDs resolve through the authorized API; they are not public artifact URLs.\n"
    # Comments have a byte limit. Never truncate through a claim; bound by complete lines.
    if len(markdown.encode()) > 50_000:
        lines, size = [], 0
        for line in markdown.splitlines(keepends=True):
            size += len(line.encode())
            if size > 49_000:
                break
            lines.append(line)
        markdown = "".join(lines) + "\nAdditional detail omitted by publication byte limit. Review the authenticated full report.\n"
    result = {"schema_version": "github-report-v2", "run_id": run.id, "repository": run.repository,
              "tested_head": run.commit_sha, "base_sha": run.base_sha, "run_scope": run.run_scope,
              "completeness": "evidence_expired" if expired else run.completeness,
              "outcomes": outcomes, "analysis_count": len(analyses), "analyses": details,
              "omitted_analyses": len(analyses) - len(details), "baseline_status": "unknown", "markdown": markdown}
    result["report_digest"] = sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return result
