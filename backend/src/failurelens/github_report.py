from __future__ import annotations

from .models import Analysis, Run

MARKER = "<!-- failurelens-report:v1 -->"


def render_markdown(run: Run, analyses: list[Analysis]) -> str:
    counts: dict[str, int] = {}
    for analysis in analyses:
        counts[analysis.category.value] = counts.get(analysis.category.value, 0) + 1
    completeness = run.completeness.upper()
    lines = [
        MARKER,
        "## FailureLens evidence-grounded triage",
        "",
        f"- Tested head: `{run.commit_sha or 'unknown'}`",
        f"- Base: `{run.base_sha or 'unknown'}`",
        f"- Run: `{run.external_id}` attempt `{run.attempt}`",
        f"- Scope completeness: **{completeness}** ({run.received_inputs}/{run.expected_inputs if run.expected_inputs is not None else 'unspecified'} inputs)",
        "",
        "### Classifications",
    ]
    for category in sorted(counts):
        lines.append(f"- `{category}`: {counts[category]}")
    if not analyses:
        lines.append("- No analyzed failures were available.")
    lines.extend([
        "",
        "### Advisory status",
        "HOLD_FOR_REVIEW" if any(a.category.value in {"product_defect", "insufficient_evidence"} for a in analyses) or run.completeness != "complete" else "NO_BLOCKER_IDENTIFIED_IN_OBSERVED_SCOPE",
        "",
        "This report is advisory. It does not approve a release, suppress failures, or replace human review.",
    ])
    return "\n".join(lines) + "\n"
