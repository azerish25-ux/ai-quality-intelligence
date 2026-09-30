from failurelens.analysis import EvidenceView, analyze_failure
from failurelens.models import Category


def evidence(text: str = "current observation") -> list[EvidenceView]:
    return [
        EvidenceView(
            id="ev-1", kind="current_run_observation", excerpt=text, observation={}
        )
    ]


def test_data_integrity_failure_is_product_defect() -> None:
    result = analyze_failure(
        message="ledger balance invariant violated after duplicate committed transfer",
        exception_type="LedgerInvariantError",
        details={"data_integrity_violation": True},
        evidence=evidence("duplicate committed transfer produced two ledger entries"),
    )
    assert result.category is Category.product_defect
    assert result.severity == "critical"
    assert result.score_kind == "heuristic_score"


def test_timeout_without_corroboration_abstains() -> None:
    result = analyze_failure(
        message="Timeout waiting for selector",
        exception_type="TimeoutError",
        details={"trace_missing": True},
        evidence=evidence("selector timed out after 30s"),
    )
    assert result.category is Category.insufficient_evidence
    assert result.abstention_reason
    assert "trace attachment" in result.missing


def test_infrastructure_label_cannot_hide_product_signal() -> None:
    result = analyze_failure(
        message="runner exited while ledger balance invariant was violated",
        exception_type="RunnerExit",
        details={"runner_diagnostic": True, "contradictory_product_signal": True},
        evidence=evidence(
            "runner exited; duplicate committed effect remains in database"
        ),
    )
    assert result.category is Category.insufficient_evidence
    assert "dangerous_downgrade_blocked" in result.policy_flags


def test_known_flake_requires_reviewed_history() -> None:
    accepted = analyze_failure(
        message="reviewed harness timing instability",
        exception_type="HarnessTimeout",
        details={},
        evidence=evidence(),
        historical={
            "reviewed_known_flake": True,
            "independent_runs": 8,
            "observed_passes": 5,
            "observed_failures": 3,
            "history_eligible_for_reassurance": True,
            "retry_recovery_rate": 0.5,
        },
    )
    assert accepted.category is Category.known_flake
    rejected = analyze_failure(
        message="retry passed once",
        exception_type="TimeoutError",
        details={"retry_recovered": True},
        evidence=evidence(),
        historical={
            "reviewed_known_flake": False,
            "independent_runs": 2,
            "observed_passes": 1,
            "observed_failures": 1,
            "history_eligible_for_reassurance": False,
            "retry_recovery_rate": 0.5,
        },
    )
    assert rejected.category is Category.insufficient_evidence
