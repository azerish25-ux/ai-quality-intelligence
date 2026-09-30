from __future__ import annotations

from collections import Counter
import html
import re

from .evidence_validation import persisted_analysis_is_publication_validated
from .models import Analysis, Run
from .redaction import redact_text

MARKER = "<!-- failurelens-report:v1 -->"
def _publication_category(analysis: Analysis) -> str:
    if persisted_analysis_is_publication_validated(analysis):
        return analysis.category.value
    return "insufficient_evidence"


def _safe(value) -> str:
    # Metadata is attacker-controlled report input, never executable Markdown.
    text = html.escape(redact_text(str(value)).text, quote=True)
    text = re.sub(r"[\r\n\x00-\x1f\x7f]", " ", text)
    for character in "`@[]()!\\":
        text = text.replace(character, f"&#{ord(character)};")
    return text[:512]


def render_markdown(run: Run, analyses: list[Analysis]) -> str:
    publication_categories = [_publication_category(item) for item in analyses]
    counts = Counter(publication_categories)
    validation_states = Counter(
        str((item.validation_results or {}).get("status", "not_validated"))
        for item in analyses
    )
    completeness = "EVIDENCE_EXPIRED" if getattr(run, "evidence_expired_at", None) else run.completeness.upper()
    expected = run.expected_inputs if run.expected_inputs is not None else "unspecified"
    lines = [
        MARKER,
        "## Loose Thread evidence-grounded triage",
        "",
        f"- Tested head: `{_safe(run.commit_sha or 'unknown')}`",
        f"- Base: `{_safe(run.base_sha or 'unknown')}`",
        f"- Run: `{_safe(run.external_id)}` attempt `{_safe(run.attempt)}`",
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
        not analyses
        or
        getattr(run, "evidence_expired_at", None) is not None
        or
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
