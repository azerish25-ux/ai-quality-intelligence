from unittest.mock import Mock

import failurelens.db as database
import pytest
from failurelens.config import Settings, get_settings
from failurelens.history import _aggregate_run_outcome
from failurelens.infrastructure import _aggregate_outcome
from pydantic import ValidationError


def test_postgresql_pool_is_bounded_and_configurable(monkeypatch):
    monkeypatch.setenv("FAILURELENS_DATABASE_POOL_SIZE", "12")
    monkeypatch.setenv("FAILURELENS_DATABASE_MAX_OVERFLOW", "4")
    get_settings.cache_clear()
    create = Mock()
    monkeypatch.setattr(database, "create_engine", create)
    database.create_database_engine("postgresql+psycopg://localhost/test")
    assert create.call_args.kwargs["pool_size"] == 12
    assert create.call_args.kwargs["max_overflow"] == 4
    database.create_database_engine("sqlite+pysqlite:///:memory:")
    assert "pool_size" not in create.call_args.kwargs
    get_settings.cache_clear()


def test_pool_configuration_rejects_unbounded_values():
    with pytest.raises(ValidationError):
        Settings(database_pool_size=500)
    with pytest.raises(ValidationError):
        Settings(database_max_overflow=-1)


@pytest.mark.parametrize(
    "outcome", ["passed", "failed", "skipped", "cancelled", "unknown", "invalid"]
)
def test_single_observation_fast_path_preserves_conservative_semantics(outcome):
    expected = outcome if outcome != "invalid" else "unknown"
    assert _aggregate_run_outcome([outcome]) == expected
    assert _aggregate_outcome([outcome]) == expected
    assert _aggregate_run_outcome([outcome, outcome]) == expected
    assert _aggregate_outcome([outcome, outcome]) == expected
