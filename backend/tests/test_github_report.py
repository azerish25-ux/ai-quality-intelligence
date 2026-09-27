from types import SimpleNamespace

from failurelens.github_report import render_markdown
from failurelens.models import Category


def _run():
    return SimpleNamespace(
        commit_sha="abcdef0",
        base_sha="1234567",
        external_id="gha-1",
        attempt=1,
        completeness="complete",
        received_inputs=1,
        expected_inputs=1,
    )


def test_report_publishes_only_validated_categories() -> None:
    validated = SimpleNamespace(
        category=Category.product_defect,
        validation_version="evidence-validation-v1",
        validation_results={
            "status": "passed",
            "published_category": "product_defect",
        },
    )
    legacy = SimpleNamespace(
        category=Category.infrastructure_failure,
        validation_version=None,
        validation_results=None,
    )

    report = render_markdown(_run(), [validated, legacy])

    assert "`product_defect`: 1" in report
    assert "`insufficient_evidence`: 1" in report
    assert "`infrastructure_failure`" not in report
    assert "not_validated=1" in report
    assert "HOLD_FOR_REVIEW" in report
    assert "stored category is not published" in report
