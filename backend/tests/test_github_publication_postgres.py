"""Real PostgreSQL reservation races; never substitute SQLite for this lane."""

from test_github_publication_service import (
    scenario_fenced_late_write,
    scenario_serialized,
)

pytest_plugins = ("test_operations_postgres",)


def test_postgres_publisher_reservation_serializes_http(pg_factory):
    factory, _ = pg_factory
    scenario_serialized(factory)


def test_postgres_reconciliation_fences_delayed_http(pg_factory):
    factory, _ = pg_factory
    scenario_fenced_late_write(factory)


def test_postgres_simultaneous_admission_cannot_duplicate_target(pg_factory):
    from test_github_publication_service import scenario_simultaneous_admission

    factory, _ = pg_factory
    scenario_simultaneous_admission(factory)
