import pytest
from failurelens.config import get_settings
from failurelens.demo_history import seed_history
from failurelens.models import Run
from failurelens.models import TestExecution as Execution
from sqlalchemy import func, select


def test_seeded_history_has_real_counts_and_three_honest_walkthrough_categories(
    session,
):
    result = seed_history(session)
    assert result["synthetic"] is True
    assert session.scalar(select(func.count()).select_from(Run)) == 100
    runs = session.scalars(select(Run)).all()
    executions = session.scalars(select(Execution)).all()
    assert len({(e.run_id, e.test_identity, e.browser) for e in executions}) == 1000
    assert len(executions) > 1000
    assert {e.browser for e in executions} == {"chromium", "firefox", "webkit"}
    assert {r.branch for r in runs} == {"main", "feature-demo"}
    assert any(r.completeness != "complete" for r in runs)
    assert all(r.source_metadata["synthetic"] for r in runs)
    final = session.get(Run, result["run_id"])
    categories = [a.category.value for f in final.failures for a in f.analyses]
    assert set(categories) == {"product_defect", "known_flake", "insufficient_evidence"}
    again = seed_history(session)
    assert again == result
    assert session.scalar(select(func.count()).select_from(Run)) == 100
    assert session.scalar(select(func.count()).select_from(Execution)) == len(
        executions
    )


def test_history_seed_refuses_production(session, monkeypatch):
    monkeypatch.setenv("FAILURELENS_DEMO_MODE", "false")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="demo mode"):
        seed_history(session)
