"""Real PostgreSQL numeric persistence/savepoints; never substitute SQLite."""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy

import pytest
from failurelens import models as m
from failurelens.api import app
from failurelens.config import get_settings
from failurelens.db import get_authentication_session_factory, get_session
from failurelens.ingestion import parse_artifact
from failurelens.performance import (
    PERFORMANCE_ENGINE_VERSION,
    create_performance_policy,
    create_run_performance_comparisons,
)
from failurelens.performance_numeric import ARITHMETIC_VERSION, PerformanceNumericError
from failurelens.schemas import PerformancePolicyCreate, RunMetadata
from failurelens.service import create_project, ingest_parsed_report
from sqlalchemy import event, func, select, text
from test_auth_transactions_postgres import request_client
from test_performance_numeric_boundaries import (
    _bytes,
    _columns,
    _input_records,
    _post,
    _seed,
)

pytest_plugins = ("test_operations_postgres",)


@pytest.fixture
def postgres_numeric(pg_factory, monkeypatch):
    factory, settings = pg_factory
    assert factory.kw["bind"].dialect.name == "postgresql"
    monkeypatch.setenv("FAILURELENS_ARTIFACT_ROOT", str(settings.artifact_root))
    get_settings.cache_clear()

    def bounded_transaction(_session, _transaction, connection):
        connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        connection.execute(text("SET LOCAL statement_timeout = '10s'"))

    def handler_sessions():
        with factory() as session:
            yield session

    event.listen(factory, "after_begin", bounded_transaction)
    overrides = {
        get_session: handler_sessions,
        get_authentication_session_factory: lambda: factory,
    }
    try:
        with request_client(app, overrides) as client:
            yield factory, client
    finally:
        event.remove(factory, "after_begin", bounded_transaction)
        get_settings.cache_clear()


def test_postgres_finite_five_run_result_persists_and_replays_versioned_identity(
    postgres_numeric,
):
    factory, client = postgres_numeric
    _project, policy, runs = _seed(factory)
    before, retained = _input_records(factory), _bytes()
    response = _post(client, runs[-1], policy)
    assert response.status_code == 201, response.text
    created = response.json()[0]
    assert created["status"] == "REGRESSION"
    assert created["numeric_state"] == "available"
    assert created["baseline_value"] == 1e308
    assert created["relative_change"] == pytest.approx(0.2)
    assert created["engine_version"] == PERFORMANCE_ENGINE_VERSION
    assert (
        created["baseline"]["compatibility"]["arithmetic_version"] == ARITHMETIC_VERSION
    )
    with factory() as observer:
        row = observer.get(m.PerformanceComparison, created["id"])
        assert row.status == "REGRESSION"
        assert row.baseline_snapshot.baseline_value == 1e308
        assert row.baseline_snapshot.baseline_mad == 0.0
        assert row.baseline_run_count == 4
        assert all(
            math.isfinite(value)
            for value in (
                row.current_value,
                row.baseline_value,
                row.absolute_change,
                row.relative_change,
                row.allowed_absolute_change,
            )
        )
        assert row.uncertainty["baseline_mad"] == 0.0
        assert [
            member.observation.canonical_value
            for member in row.baseline_snapshot.members
        ] == [1e308] * 4
    replay = _post(client, runs[-1], policy)
    assert replay.status_code == 201
    repeated = replay.json()[0]
    for field in ("id", "input_digest", "baseline_snapshot_id", "engine_version"):
        assert repeated[field] == created[field]
    assert repeated["baseline"]["input_digest"] == created["baseline"]["input_digest"]
    for path in (
        f"/api/v1/performance-comparisons/{created['id']}",
        f"/api/v1/runs/{runs[-1]}/performance-comparisons",
        f"/api/v1/runs/{runs[-1]}/github-report-preview",
    ):
        assert client.get(path).status_code == 200
    with factory() as observer:
        assert (
            observer.scalar(select(func.count()).select_from(m.PerformanceComparison))
            == 1
        )
        assert (
            observer.scalar(
                select(func.count()).select_from(m.PerformanceBaselineSnapshot)
            )
            == 1
        )
    assert before == _input_records(factory)
    assert retained == _bytes()


def _gauge_batch(factory):
    with factory() as session:
        project = create_project(session, "numeric-gauge-batch", "Ordered gauge batch")
        policy = create_performance_policy(
            session, project, PerformancePolicyCreate(version="ordered-gauge-v1")
        )
        for index, value in enumerate((1e-100,) * 4 + (1e308,)):
            content = json.dumps(
                {
                    "metrics": {
                        "a_control": {
                            "type": "gauge",
                            "contains": "default",
                            "values": {"value": 10.0},
                            "thresholds": {},
                        },
                        "z_overflow": {
                            "type": "gauge",
                            "contains": "default",
                            "values": {"value": value},
                            "thresholds": {},
                        },
                    }
                }
            ).encode()
            parsed = parse_artifact(
                content,
                "summary.json",
                get_settings(),
                source_format="k6-summary-json",
                media_type="application/json",
            )
            digest = hashlib.sha256(content).hexdigest()
            run = ingest_parsed_report(
                session,
                project,
                RunMetadata(
                    external_id=f"ordered-{index}",
                    repository="owner/repo",
                    commit_sha="a" * 40,
                    run_scope="full_suite",
                    comparison_trust="trusted_workflow",
                    environment="synthetic",
                ),
                parsed.observations,
                source_name="summary.json",
                source_digest=digest,
                source_size_bytes=len(content),
                storage_path=f"test://{digest}",
                media_type="application/json",
                source_format=parsed.source_format,
                parser_version=parsed.parser_version,
                parser_warnings=parsed.warnings,
                input_records=parsed.inputs,
                parsed_expected_inputs=parsed.expected_inputs,
                parsed_received_inputs=parsed.received_inputs,
                parsed_completeness=parsed.completeness,
                manifest_version=parsed.manifest_version,
                restricted=False,
            )
        control_id = session.scalar(
            select(m.PerformanceObservation.id).where(
                m.PerformanceObservation.run_id == run.id,
                m.PerformanceObservation.metric_name == "a_control",
            )
        )
        return policy.id, run.id, control_id


def test_postgres_failed_later_observation_rolls_back_all_new_numeric_records(
    postgres_numeric,
):
    factory, client = postgres_numeric
    # Distinct real metric names guarantee the finite control sorts first. Both
    # magnitudes fit PostgreSQL float8; only the derived relative change overflows.
    policy_id, run_id, control_id = _gauge_batch(factory)
    before, retained = _input_records(factory), _bytes()
    earlier_rows = []

    def control_was_inserted(session, _flush_context):
        for row in session.new:
            if isinstance(row, m.PerformanceComparison):
                assert row.current_observation_id == control_id
                connection = session.connection()
                earlier_rows.append(
                    (
                        connection.scalar(
                            select(func.count()).select_from(m.PerformanceComparison)
                        ),
                        connection.scalar(
                            select(func.count()).select_from(
                                m.PerformanceBaselineSnapshot
                            )
                        ),
                    )
                )

    event.listen(factory, "after_flush", control_was_inserted)
    try:
        response = _post(client, run_id, policy_id)
        assert response.status_code == 422, response.text
        assert earlier_rows == [(1, 1)]
        with factory() as observer:
            assert (
                observer.scalar(
                    select(func.count()).select_from(m.PerformanceComparison)
                )
                == 0
            )
            assert (
                observer.scalar(
                    select(func.count()).select_from(m.PerformanceBaselineSnapshot)
                )
                == 0
            )
        with factory() as caller:
            pending = m.Project(slug="caller-owned-pending", name="Pending caller work")
            caller.add(pending)
            run = caller.get(m.Run, run_id)
            policy = caller.get(m.PerformancePolicy, policy_id)
            with pytest.raises(PerformanceNumericError):
                create_run_performance_comparisons(caller, run, policy)
            assert earlier_rows == [(1, 1), (1, 1)]
            assert caller.is_active
            with factory() as observer:
                assert (
                    observer.scalar(
                        select(m.Project.id).where(m.Project.slug == pending.slug)
                    )
                    is None
                )
            caller.commit()
        with factory() as observer:
            assert (
                observer.scalar(
                    select(m.Project.id).where(m.Project.slug == "caller-owned-pending")
                )
                is not None
            )
            assert (
                observer.scalar(
                    select(func.count()).select_from(m.PerformanceComparison)
                )
                == 0
            )
            assert (
                observer.scalar(
                    select(func.count()).select_from(m.PerformanceBaselineSnapshot)
                )
                == 0
            )
            assert (
                observer.scalar(
                    select(func.count()).select_from(m.PerformanceBaselineMember)
                )
                == 0
            )
        assert before == _input_records(factory)
        assert retained == _bytes()
    finally:
        event.remove(factory, "after_flush", control_was_inserted)


def test_postgres_finite_legacy_version_coexists_with_new_immutable_computation(
    postgres_numeric,
):
    factory, client = postgres_numeric
    # This finite ordinary synthetic historical record is intentionally separate
    # from the huge even-median case: PostgreSQL could not retain v1's invalid JSON.
    _project, policy_id, runs = _seed(factory, values=(90.0, 100.0, 110.0, 130.0))
    initial = _post(client, runs[-1], policy_id)
    assert initial.status_code == 201
    old_id = initial.json()[0]["id"]
    with factory.begin() as session:
        row = session.get(m.PerformanceComparison, old_id)
        baseline = row.baseline_snapshot
        compatibility = deepcopy(baseline.compatibility)
        compatibility.pop("arithmetic_version")
        baseline.compatibility = compatibility
        observations = sorted(
            (member.observation for member in baseline.members),
            key=lambda item: (item.observed_at, item.id),
            reverse=True,
        )
        payload = {
            "schema_version": "performance-baseline-v1",
            "current_observation_id": row.current_observation_id,
            "current_metric_key": row.current_observation.metric_key,
            "policy_id": policy_id,
            "policy_version": row.policy.version,
            "cutoff": compatibility["prior_only_cutoff"],
            "accepted_observation_ids": [item.id for item in observations],
            "status": "AVAILABLE",
            "compatibility": compatibility,
        }
        digest = lambda value: hashlib.sha256(
            json.dumps(
                value, sort_keys=True, separators=(",", ":"), default=str
            ).encode()
        ).hexdigest()
        baseline.input_digest = digest(payload)
        row.engine_version = "performance-engine-v1"
        row.input_digest = digest(
            {
                "schema_version": "performance-comparison-v1",
                "engine_version": row.engine_version,
                "current_observation_id": row.current_observation_id,
                "current_metric_key": row.current_observation.metric_key,
                "current_value": row.current_value,
                "baseline_input_digest": baseline.input_digest,
                "policy_id": policy_id,
                "policy_version": row.policy.version,
                "direction": row.current_observation.direction,
            }
        )
        row.compatibility = compatibility
        uncertainty = deepcopy(row.uncertainty)
        uncertainty.pop("arithmetic_version")
        row.uncertainty = uncertainty
        baseline_id = baseline.id
    with factory() as observer:
        old_record = _columns(observer.get(m.PerformanceComparison, old_id))
        old_baseline = _columns(
            observer.get(m.PerformanceBaselineSnapshot, baseline_id)
        )
    before, retained = _input_records(factory), _bytes()
    response = _post(client, runs[-1], policy_id)
    assert response.status_code == 201, response.text
    current = response.json()[0]
    assert current["id"] != old_id and current["baseline_snapshot_id"] != baseline_id
    assert current["engine_version"] == PERFORMANCE_ENGINE_VERSION
    assert (
        current["baseline"]["compatibility"]["arithmetic_version"] == ARITHMETIC_VERSION
    )
    assert _post(client, runs[-1], policy_id).json()[0]["id"] == current["id"]
    listed = client.get(f"/api/v1/runs/{runs[-1]}/performance-comparisons").json()
    assert {row["id"] for row in listed} == {old_id, current["id"]}
    assert all(
        row["numeric_state"] == "available" and row["status"] == "REGRESSION"
        for row in listed
    )
    report = client.get(f"/api/v1/runs/{runs[-1]}/github-report-preview")
    assert report.status_code == 200
    assert report.json()["performance"]["count"] == 2
    assert report.json()["performance"]["stored_status_counts"] == {"REGRESSION": 2}
    with factory() as observer:
        assert _columns(observer.get(m.PerformanceComparison, old_id)) == old_record
        assert (
            _columns(observer.get(m.PerformanceBaselineSnapshot, baseline_id))
            == old_baseline
        )
        assert (
            observer.scalar(select(func.count()).select_from(m.PerformanceComparison))
            == 2
        )
        assert (
            observer.scalar(
                select(func.count()).select_from(m.PerformanceBaselineSnapshot)
            )
            == 2
        )
    assert before == _input_records(factory)
    assert retained == _bytes()
