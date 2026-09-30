"""Fixed synthetic safeguard probes; deliberately separate from frozen evaluation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MutationCase:
    id: str
    module: str
    target: str
    test_id: str
    description: str


CASES = (
    MutationCase(
        "authorization",
        "failurelens.auth",
        "require_project_role",
        "backend/tests/test_auth.py::test_viewer_is_project_scoped_and_cannot_mutate_reviews",
        "Return administrator access without checking project membership or role.",
    ),
    MutationCase(
        "redaction",
        "failurelens.redaction",
        "redact_text",
        "backend/tests/test_redaction.py::test_redacts_declared_sensitive_classes_and_preserves_evidence",
        "Omit the authorization-header redaction pattern.",
    ),
    MutationCase(
        "missing-citation",
        "failurelens.evidence_validation",
        "_validated_reference_ids",
        "backend/tests/test_evidence_validation.py::test_forged_evidence_reference_is_withheld",
        "Replace an unresolved citation with available evidence instead of rejecting it.",
    ),
    MutationCase(
        "retry-as-run",
        "failurelens.history",
        "build_test_history",
        "backend/tests/test_history.py::test_retries_collapse_and_absent_tests_are_not_counted_as_passes",
        "Count retry attempts as independent runs in the history denominator.",
    ),
    MutationCase(
        "timeout-to-flake",
        "failurelens.analysis",
        "analyze_failure",
        "backend/tests/test_analysis.py::test_timeout_without_corroboration_abstains",
        "Classify an uncorroborated timeout as known flaky behavior.",
    ),
    MutationCase(
        "missing-shard",
        "failurelens.service",
        "_resolve_input_scope",
        "backend/tests/test_service.py::test_incomplete_run_is_explicit",
        "Mark run scope complete despite an expected input/shard being absent.",
    ),
    MutationCase(
        "stale-report",
        "failurelens.github_publication",
        "GitHubPublisher._head",
        "backend/tests/test_github_publication.py::test_stale_before_first_write_does_not_publish",
        "Reuse the tested revision instead of the newly observed PR head.",
    ),
)
BY_ID = {case.id: case for case in CASES}
