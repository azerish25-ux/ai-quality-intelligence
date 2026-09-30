"""Policy immutability regressions, including a simulated stale initial lookup.

SQLite exercises real unique-constraint recovery here, not a concurrent database
race. The separate PostgreSQL module covers concurrent creators.
"""

from __future__ import annotations

import pytest
from failurelens.models import PerformancePolicy
from failurelens.performance import create_performance_policy
from failurelens.schemas import PerformancePolicyCreate
from failurelens.service import create_project
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


def policy_request(**changes):
    return PerformancePolicyCreate.model_validate(
        {
            "version": "immutable-v1",
            "relative_tolerance": 0.1,
            "absolute_tolerance": 5.0,
            "min_baseline_runs": 3,
            "max_baseline_age_days": 30,
            "require_trusted": True,
            "required_dimensions": ["repository", "environment"],
            "direction_overrides": {
                "latency": "lower_is_better",
                "requests": "higher_is_better",
            },
            **changes,
        }
    )


POLICY_CHANGES = [
    pytest.param({"relative_tolerance": 0.2}, id="relative-tolerance"),
    pytest.param({"absolute_tolerance": 10.0}, id="absolute-tolerance"),
    pytest.param({"min_baseline_runs": 4}, id="minimum-runs"),
    pytest.param({"max_baseline_age_days": 14}, id="maximum-age"),
    pytest.param({"require_trusted": False}, id="trust"),
    pytest.param({"required_dimensions": ["repository"]}, id="dimensions"),
    pytest.param({"direction_overrides": {"latency": "neutral"}}, id="directions"),
]

CONFLICT_MESSAGE = (
    "performance policy version already exists with different immutable content"
)


def _hide_first_policy_lookup(session, monkeypatch):
    original_scalar = session.scalar
    lookups = []

    def scalar(statement, *args, **kwargs):
        if statement.column_descriptions[0].get("entity") is PerformancePolicy:
            lookups.append(statement)
            if len(lookups) == 1:
                return None
        return original_scalar(statement, *args, **kwargs)

    monkeypatch.setattr(session, "scalar", scalar)
    return lookups


def _persisted_payload(row):
    return {
        field: getattr(row, field) for field in PerformancePolicyCreate.model_fields
    }


@pytest.mark.parametrize("stale_lookup", [False, True], ids=["existing", "recovery"])
@pytest.mark.parametrize("changes", POLICY_CHANGES)
def test_policy_rejects_changed_immutable_content(
    session, monkeypatch, stale_lookup, changes
):
    project = create_project(session, "policy-conflict", "Policy conflict")
    original = policy_request()
    winner = create_performance_policy(session, project, original)
    winner_id = winner.id
    lookups = _hide_first_policy_lookup(session, monkeypatch) if stale_lookup else []

    with pytest.raises(ValueError, match=f"^{CONFLICT_MESSAGE}$"):
        create_performance_policy(session, project, policy_request(**changes))

    if stale_lookup:
        assert len(lookups) == 2
    assert session.is_active
    session.expire_all()
    rows = session.scalars(select(PerformancePolicy)).all()
    assert len(rows) == 1
    assert rows[0].id == winner_id
    assert _persisted_payload(rows[0]) == original.model_dump(mode="json")
    assert create_performance_policy(session, project, original).id == winner_id


@pytest.mark.parametrize("stale_lookup", [False, True], ids=["existing", "recovery"])
def test_policy_equivalent_content_is_idempotent(session, monkeypatch, stale_lookup):
    project = create_project(session, "policy-repeat", "Policy repeat")
    original = policy_request()
    winner = create_performance_policy(session, project, original)
    winner_id = winner.id
    lookups = _hide_first_policy_lookup(session, monkeypatch) if stale_lookup else []
    equivalent = policy_request(
        required_dimensions=[" environment ", "repository", "environment"],
        direction_overrides={
            "requests": "higher_is_better",
            "latency": "lower_is_better",
        },
    )

    repeated = create_performance_policy(session, project, equivalent)

    if stale_lookup:
        assert len(lookups) == 2
    assert repeated.id == winner_id
    assert session.is_active
    session.expire_all()
    rows = session.scalars(select(PerformancePolicy)).all()
    assert len(rows) == 1
    assert _persisted_payload(rows[0]) == original.model_dump(mode="json")


def test_policy_immutability_is_scoped_to_project_and_version(session):
    first = create_project(session, "policy-first", "First project")
    second = create_project(session, "policy-second", "Second project")
    original = create_performance_policy(session, first, policy_request())
    other_project = create_performance_policy(
        session, second, policy_request(relative_tolerance=0.2)
    )
    other_version = create_performance_policy(
        session, first, policy_request(version="immutable-v2", relative_tolerance=0.3)
    )

    assert len({original.id, other_project.id, other_version.id}) == 3
    assert len(session.scalars(select(PerformancePolicy)).all()) == 3


def test_policy_reraises_integrity_error_without_a_winner(session, monkeypatch):
    project = create_project(session, "policy-no-winner", "Policy without winner")
    error = IntegrityError("insert policy", {}, ValueError("unrelated constraint"))

    def fail_commit():
        raise error

    monkeypatch.setattr(session, "commit", fail_commit)
    with pytest.raises(IntegrityError) as caught:
        create_performance_policy(session, project, policy_request())

    assert caught.value is error
    assert session.is_active
    assert session.scalars(select(PerformancePolicy)).all() == []
