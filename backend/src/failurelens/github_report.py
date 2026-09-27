from __future__ import annotations

from collections import Counter

from .evidence_validation import persisted_analysis_is_publication_validated
from .models import Analysis, Run

MARKER = "<!-- failurelens-report:v1 -->"
def _publication_category(analysis: Analysis) -> str:
    if persisted_analysis_is_publication_validated(analysis):
        return analysis.category.value
    return "insufficient_evidence"


def render_markdown(run: Run, analyses: list[Analysis]) -> str:
    publication_categories = [_publication_category(item) for item in analyses]
    counts = Counter(publication_categories)
    validation_states = Counter(
        str((item.validation_results or {}).get("status", "not_validated"))
        for item in analyses
    )
    completeness = run.completeness.upper()
    expected = run.expected_inputs if run.expected_inputs is not None else "unspecified"
    lines = [
        MARKER,
        "## FailureLens evidence-grounded triage",
        "",
        f"- Tested head: `{run.commit_sha or 'unknown'}`",
        f"- Base: `{run.base_sha or 'unknown'}`",
        f"- Run: `{run.external_id}` attempt `{run.attempt}`",
        (
            f"- Scope completeness: **{completeness}** "
            f"({run.received_inputs}/{expected} inputs)"
        ),
        "- Evidence publication validation: "
        + (
            ", ".join(
                f"{state}={count}"
                for state, count in sorted(validation_states.items())
            )
            if validation_states
            else "no analyses"
        ),
        "",
        "### Classifications",
    ]
    for category in sorted(counts):
        lines.append(f"- `{category}`: {counts[category]}")
    if not analyses:
        lines.append("- No analyzed failures were available.")
    elif validation_states.get("not_validated", 0):
        lines.append(
            "- Unvalidated legacy analyses are reported as `insufficient_evidence`; "
            "their stored category is not published."
        )

    hold = (
        any(
            category in {"product_defect", "insufficient_evidence"}
            for category in publication_categories
        )
        or run.completeness != "complete"
    )
    lines.extend(
        [
            "",
            "### Advisory status",
            "HOLD_FOR_REVIEW" if hold else "NO_BLOCKER_IDENTIFIED_IN_OBSERVED_SCOPE",
            "",
            (
                "This report is advisory. It does not approve a release, suppress "
                "failures, or replace human review."
            ),
        ]
    )
    return "\n".join(lines) + "\n"
