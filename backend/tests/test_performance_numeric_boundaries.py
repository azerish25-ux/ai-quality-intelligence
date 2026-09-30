"""Real synthetic measurements retain their provenance across arithmetic failures."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import sys
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import httpx
import pytest
from failurelens import models as m
from failurelens.config import get_settings
from failurelens.github_evidence import canonical_export_bytes
from failurelens.github_publication_service import durable_publish
from failurelens.performance import (
    PERFORMANCE_ENGINE_VERSION,
    canonicalize_value,
    classify_performance_change,
    create_performance_comparison,
    create_performance_policy,
    create_run_performance_comparisons,
)
from failurelens.performance_numeric import (
    ARITHMETIC_VERSION,
    PerformanceNumericError,
    finite_mad,
    finite_median,
    finite_result,
    ratio,
)
from failurelens.schemas import IngestionRequest, PerformancePolicyCreate
from failurelens.service import create_project, ingest_normalized
from sqlalchemy import func, inspect, select
from test_github_publication import GitHub


def _seed(factory, *, values=(1e308, 1e308, 1e308, 1e308, 1.2e308), extra=False):
    with factory() as session:
        project = create_project(
            session, "numeric-boundaries", "Synthetic numeric boundaries"
        )
        policy = create_performance_policy(
            session, project, PerformancePolicyCreate(version="numeric-v1")
        )
        run_ids = []
        for index, value in enumerate(values):
            observations = [
                {
                    "test_identity": "numeric::latency",
                    "outcome": "passed",
                    "duration_ms": value,
                }
            ]
            if extra:
                observations.insert(
                    0,
                    {
                        "test_identity": "numeric::control",
                        "outcome": "passed",
                        "duration_ms": 10.0,
                    },
                )
            run = ingest_normalized(
                session,
                project,
                IngestionRequest.model_validate(
                    {
                        "external_id": f"numeric-{index}",
                        "repository": "owner/repo",
                        "commit_sha": "a" * 40,
                        "run_scope": "full_suite",
                        "comparison_trust": "trusted_workflow",
                        "environment": "synthetic",
                        "observations": observations,
                    }
                ),
            )
            run_ids.append(run.id)
        return project.id, policy.id, run_ids


def _bytes():
    root = Path(get_settings().artifact_root)
    return {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def _columns(row):
    return json.dumps(
        {
            column.key: getattr(row, column.key)
            for column in inspect(type(row)).column_attrs
        },
        sort_keys=True,
        default=str,
    )


def _input_records(factory):
    with factory() as session:
        return {
            type(row).__name__ + row.id: _columns(row)
            for model in (
                m.PerformanceObservation,
                m.TestExecution,
                m.Evidence,
                m.PerformancePolicy,
            )
            for row in session.scalars(select(model))
        }


def _post(client, run_id, policy_id):
    return client.post(
        f"/api/v1/runs/{run_id}/performance-comparisons", json={"policy_id": policy_id}
    )


def _legacy_history(factory, policy_id, run_id):
    """Import the numeric state captured by the pre-repair five-run SQLite proof.

    Real ingestion and normal cohort construction supply every relationship and
    citation. Only the derived historical fields/version use the observed v1
    record; no evidence/validation flags or original measurements are fabricated.
    """
    with factory() as session:
        row = create_run_performance_comparisons(
            session,
            session.get(m.Run, run_id),
            session.get(m.PerformancePolicy, policy_id),
        )[0]
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
        baseline.baseline_value = math.inf
        baseline.baseline_mad = math.inf
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
        row.status = "WITHIN_TOLERANCE"
        row.baseline_value = math.inf
        row.absolute_change = -math.inf
        row.relative_change = None
        row.allowed_absolute_change = math.inf
        row.effect_size = None
        row.compatibility = compatibility
        row.uncertainty = {
            **row.uncertainty,
            "baseline_mad": math.inf,
            "robust_standardized_change": math.nan,
        }
        row.uncertainty.pop("arithmetic_version", None)
        row.summary = "Recorded v1 WITHIN_TOLERANCE with baseline inf"
        session.commit()
        session.expire_all()
        return row.id, baseline.id, _columns(row), _columns(baseline)


def test_five_finite_runs_publish_a_real_regression(session_factory, request_client):
    project_id, policy_id, runs = _seed(session_factory)
    before, retained = _input_records(session_factory), _bytes()
    response = _post(request_client, runs[-1], policy_id)
    assert response.status_code == 201, response.text
    comparison = response.json()[0]
    assert comparison["status"] == "REGRESSION"
    assert comparison["baseline_value"] == 1e308
    assert comparison["baseline"]["baseline_mad"] == 0
    assert comparison["relative_change"] == pytest.approx(0.2)
    assert comparison["engine_version"] == PERFORMANCE_ENGINE_VERSION
    assert (
        comparison["baseline"]["compatibility"]["arithmetic_version"]
        == ARITHMETIC_VERSION
    )
    assert comparison["baseline_run_count"] == 4
    assert comparison["numeric_state"] == "available"
    for url in (
        f"/api/v1/performance-comparisons/{comparison['id']}",
        f"/api/v1/performance-baselines/{comparison['baseline_snapshot_id']}",
        f"/api/v1/runs/{runs[-1]}/performance-comparisons",
        f"/api/v1/runs/{runs[-1]}/performance-observations",
    ):
        assert request_client.get(url).status_code == 200
    replay = _post(request_client, runs[-1], policy_id).json()[0]
    assert (
        replay["id"] == comparison["id"]
        and replay["input_digest"] == comparison["input_digest"]
    )
    snapshot = request_client.get(f"/api/v1/runs/{runs[-1]}/github-report-preview")
    assert snapshot.status_code == 200
    report = snapshot.json()
    assert "stored_performance_regression" in report["advisory_reasons"]
    assert report["performance"]["items"][0]["status"] == "REGRESSION"
    assert "baseline: inf" not in report["markdown"]
    canonical_export_bytes(report)
    assert before == _input_records(session_factory)
    assert retained == _bytes()
    assert project_id == comparison["project_id"]


def test_invalid_history_remains_readable_beside_versioned_recomputation(
    session_factory, request_client
):
    _project, policy, runs = _seed(session_factory)
    before, retained = _input_records(session_factory), _bytes()
    old_id, baseline_id, old_record, old_baseline = _legacy_history(
        session_factory, policy, runs[-1]
    )
    old = request_client.get(f"/api/v1/performance-comparisons/{old_id}").json()
    assert old["status"] == "NUMERIC_UNAVAILABLE"
    assert old["recorded_status"] == "WITHIN_TOLERANCE"
    assert old["numeric_reasons"] == ["performance_numeric_unavailable"]
    assert old["allowed_absolute_change"] is None
    assert old["baseline"]["status"] == "NUMERIC_UNAVAILABLE"
    assert (
        request_client.get(f"/api/v1/performance-baselines/{baseline_id}").json()[
            "numeric_state"
        ]
        == "unavailable"
    )
    new_response = _post(request_client, runs[-1], policy)
    assert new_response.status_code == 201, new_response.text
    new = new_response.json()[0]
    assert new["id"] != old_id and new["baseline_snapshot_id"] != baseline_id
    assert new["status"] == "REGRESSION"
    assert _post(request_client, runs[-1], policy).json()[0]["id"] == new["id"]
    listed = request_client.get(
        f"/api/v1/runs/{runs[-1]}/performance-comparisons"
    ).json()
    assert {item["id"] for item in listed} == {old_id, new["id"]}
    response = request_client.get(f"/api/v1/runs/{runs[-1]}/github-report-preview")
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["performance"]["count"] == 2
    assert report["performance"]["stored_status_counts"] == {
        "REGRESSION": 1,
        "WITHIN_TOLERANCE": 1,
    }
    assert {item["status"] for item in report["performance"]["items"]} == {
        "REGRESSION",
        "NUMERIC_UNAVAILABLE",
    }
    assert "stored_performance_numeric_unavailable" in report["advisory_reasons"]
    assert "stored_performance_regression" in report["advisory_reasons"]
    assert "baseline: inf" not in report["markdown"]
    assert "Recorded v1 WITHIN_TOLERANCE with baseline inf" not in report["markdown"]
    assert "Numeric result unavailable" in report["markdown"]
    canonical_export_bytes(report)
    server = GitHub()
    published = durable_publish(
        session_factory,
        run_id=runs[-1],
        repository="owner/repo",
        pull_number=7,
        token="fake-test-token",
        transport=httpx.MockTransport(server.handle),
    )
    assert published["status"] == "created"
    assert len(server.writes) == 1
    body = server.writes[0][2]["body"]
    assert "NUMERIC_UNAVAILABLE" in body and "REGRESSION" in body
    assert "baseline: inf" not in body
    with session_factory() as session:
        assert _columns(session.get(m.PerformanceComparison, old_id)) == old_record
        assert (
            _columns(session.get(m.PerformanceBaselineSnapshot, baseline_id))
            == old_baseline
        )
    assert before == _input_records(session_factory)
    assert retained == _bytes()


@pytest.mark.parametrize("target", ["baseline", "comparison"])
def test_invalid_current_version_cache_fails_closed(
    session_factory, request_client, target
):
    _project, policy, runs = _seed(session_factory)
    created = _post(request_client, runs[-1], policy).json()[0]
    with session_factory.begin() as session:
        row = session.get(m.PerformanceComparison, created["id"])
        if target == "baseline":
            row.baseline_snapshot.baseline_mad = math.inf
        else:
            row.allowed_absolute_change = math.inf
    with session_factory() as session:
        row = session.get(m.PerformanceComparison, created["id"])
        before = _columns(row), _columns(row.baseline_snapshot)
    response = _post(request_client, runs[-1], policy)
    assert response.status_code == 422, response.text
    with session_factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(m.PerformanceComparison))
            == 1
        )
        assert (
            session.scalar(
                select(func.count()).select_from(m.PerformanceBaselineSnapshot)
            )
            == 1
        )
        row = session.get(m.PerformanceComparison, created["id"])
        assert (_columns(row), _columns(row.baseline_snapshot)) == before
    assert (
        request_client.get(f"/api/v1/performance-comparisons/{created['id']}").json()[
            "status"
        ]
        == "NUMERIC_UNAVAILABLE"
    )


def test_unrepresentable_new_batch_keeps_original_inputs_without_partial_records(
    session_factory, request_client
):
    _project, policy, runs = _seed(
        session_factory, values=(math.ulp(0.0),) * 4 + (1.0,), extra=True
    )
    before, retained = _input_records(session_factory), _bytes()
    response = _post(request_client, runs[-1], policy)
    assert response.status_code == 422, response.text
    with session_factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(m.PerformanceComparison))
            == 0
        )
        assert (
            session.scalar(
                select(func.count()).select_from(m.PerformanceBaselineSnapshot)
            )
            == 0
        )
        current = session.scalar(
            select(m.PerformanceObservation).where(
                m.PerformanceObservation.run_id == runs[-1],
                m.PerformanceObservation.workload == "numeric::latency",
            )
        )
        with pytest.raises(PerformanceNumericError):
            create_performance_comparison(
                session, current, session.get(m.PerformancePolicy, policy)
            )
        session.commit()
        assert (
            session.scalar(
                select(func.count()).select_from(m.PerformanceBaselineSnapshot)
            )
            == 0
        )
    assert before == _input_records(session_factory)
    assert retained == _bytes()


def test_observation_only_reads_label_invalid_historical_conversion(
    session_factory, request_client
):
    project, policy, runs = _seed(session_factory)
    with session_factory.begin() as session:
        row = session.scalar(
            select(m.PerformanceObservation).where(
                m.PerformanceObservation.run_id == runs[-1]
            )
        )
        row.canonical_value = math.inf
        oid = row.id
    before = _input_records(session_factory)
    response = request_client.get(f"/api/v1/runs/{runs[-1]}/performance-observations")
    assert response.status_code == 200
    item = response.json()[0]
    assert item["numeric_state"] == "unavailable" and item["canonical_value"] is None
    assert item["original_value"] == 1.2e308
    assert item["threshold_status"] == "NUMERIC_UNAVAILABLE"
    assert _post(request_client, runs[-1], policy).status_code == 422
    assert (
        request_client.post(
            f"/api/v1/projects/{project}/performance-baselines",
            json={"current_observation_id": oid, "policy_id": policy},
        ).status_code
        == 422
    )
    assert before == _input_records(session_factory)


def test_even_median_matches_exact_midpoint_for_extremes_and_subnormals():
    tiny, large = math.ulp(0.0), sys.float_info.max
    values = [
        -large,
        math.nextafter(-large, 0.0),
        -1e308,
        -1.0,
        -3 * tiny,
        -2 * tiny,
        -tiny,
        -0.0,
        0.0,
        tiny,
        2 * tiny,
        3 * tiny,
        1.0,
        1e308,
        math.nextafter(large, 0.0),
        large,
    ]
    for left, right in itertools.product(values, repeat=2):
        expected = float((Fraction(left) + Fraction(right)) / 2)
        assert finite_median([left, right]).hex() == expected.hex()
    assert finite_median([-large, 3.0, large]) == 3.0
    assert finite_mad([-large, -large, -large, large], -large) == 0.0
    assert finite_mad([1e308] * 4, 1e308) == 0.0


@pytest.mark.parametrize("delta,mad", [(1e308, 1.5e308), (1.7e308, 0.8)])
def test_representable_effect_survives_intermediate_overflow(delta, mad):
    expected = float(Fraction(delta) / (Fraction(1.4826) * Fraction(mad)))
    assert finite_result(ratio(delta) / (ratio(1.4826) * ratio(mad))) == expected


@pytest.mark.parametrize("value,unit", [(1e308, "s"), (sys.float_info.max, "GiB")])
def test_conversion_overflow_is_rejected_without_clipping(value, unit):
    with pytest.raises(PerformanceNumericError):
        canonicalize_value(value, unit)
    assert canonicalize_value(1e305, "s") == (1e308, "ms")


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_nonfinite_arithmetic_cannot_classify_as_reassuring(value):
    with pytest.raises(PerformanceNumericError):
        classify_performance_change(
            current_value=value,
            baseline_value=1.0,
            direction="lower_is_better",
            absolute_tolerance=0.0,
            relative_tolerance=0.1,
        )


@pytest.mark.parametrize("target", ["baseline", "comparison"])
@pytest.mark.parametrize(
    "invalid", [False, True], ids=["valid-winner", "invalid-winner"]
)
def test_real_unique_recovery_validates_the_cached_winner(
    session_factory, monkeypatch, target, invalid
):
    from failurelens.performance import build_performance_baseline

    _project, policy_id, runs = _seed(session_factory)
    with session_factory() as session:
        run = session.get(m.Run, runs[-1])
        policy = session.get(m.PerformancePolicy, policy_id)
        winner = create_run_performance_comparisons(session, run, policy)[0]
        winner_id = winner.id
        baseline_id = winner.baseline_snapshot_id
        if invalid:
            if target == "baseline":
                winner.baseline_snapshot.baseline_mad = math.inf
            else:
                winner.allowed_absolute_change = math.inf
            session.commit()
        session.expire_all()
        winner = session.get(m.PerformanceComparison, winner_id)
        before = _columns(winner), _columns(winner.baseline_snapshot)
        current = winner.current_observation
        policy = winner.policy
        model = (
            m.PerformanceBaselineSnapshot
            if target == "baseline"
            else m.PerformanceComparison
        )
        original_scalar = session.scalar
        lookups = []

        def stale_first_lookup(statement, *args, **kwargs):
            if statement.column_descriptions[0].get("entity") is model:
                lookups.append(statement)
                if len(lookups) == 1:
                    return None
            return original_scalar(statement, *args, **kwargs)

        monkeypatch.setattr(session, "scalar", stale_first_lookup)
        operation = (
            build_performance_baseline
            if target == "baseline"
            else create_performance_comparison
        )
        if invalid:
            with pytest.raises(PerformanceNumericError):
                operation(session, current, policy)
        else:
            result = operation(session, current, policy)
            assert result.id == (baseline_id if target == "baseline" else winner_id)
        assert len(lookups) >= 2
        assert session.is_active
        session.expire_all()
        winner = session.get(m.PerformanceComparison, winner_id)
        assert (_columns(winner), _columns(winner.baseline_snapshot)) == before
        assert (
            session.scalar(select(func.count()).select_from(m.PerformanceComparison))
            == 1
        )
        assert (
            session.scalar(
                select(func.count()).select_from(m.PerformanceBaselineSnapshot)
            )
            == 1
        )


def test_cli_and_action_accept_neutral_historical_numeric_projection(
    session_factory, monkeypatch, capsys
):
    from failurelens import cli
    from failurelens.db import Base
    from test_github_action import runner

    _project, policy, runs = _seed(session_factory)
    _legacy_history(session_factory, policy, runs[-1])
    monkeypatch.setattr(cli, "SessionLocal", session_factory)
    monkeypatch.setattr(
        cli,
        "initialize_database",
        lambda: Base.metadata.create_all(session_factory.kw["bind"]),
    )
    monkeypatch.setattr(
        sys, "argv", ["failurelens", "report", "--run", runs[-1], "--format", "json"]
    )
    cli.main()
    raw = capsys.readouterr().out.strip()
    report = runner._json_load(raw.encode())
    runner.validate_snapshot(report, runs[-1])
    assert runner._canonical(report).decode() == raw
    assert report["performance"]["items"][0]["status"] == "NUMERIC_UNAVAILABLE"
    monkeypatch.setattr(
        sys,
        "argv",
        ["failurelens", "report", "--run", runs[-1], "--format", "markdown"],
    )
    cli.main()
    assert capsys.readouterr().out == report["markdown"]


def test_all_version_counts_survive_the_report_detail_limit(
    session_factory, request_client
):
    from datetime import timedelta

    _project, policy, runs = _seed(session_factory)
    old_id, _bid, old_record, _old_baseline = _legacy_history(
        session_factory, policy, runs[-1]
    )
    current = _post(request_client, runs[-1], policy).json()[0]
    with session_factory.begin() as session:
        source = session.get(m.PerformanceComparison, current["id"])
        baseline = source.baseline_snapshot
        for index in range(49):
            baseline_values = {
                column.key: deepcopy(getattr(baseline, column.key))
                for column in inspect(m.PerformanceBaselineSnapshot).column_attrs
                if column.key not in {"id", "created_at", "input_digest"}
            }
            archived = m.PerformanceBaselineSnapshot(
                **baseline_values,
                input_digest=f"archive-baseline-{index}",
                created_at=source.created_at - timedelta(days=index + 1),
            )
            session.add(archived)
            session.flush()
            for member in baseline.members:
                session.add(
                    m.PerformanceBaselineMember(
                        snapshot_id=archived.id,
                        observation_id=member.observation_id,
                        run_id=member.run_id,
                        position=member.position,
                    )
                )
            comparison_values = {
                column.key: deepcopy(getattr(source, column.key))
                for column in inspect(m.PerformanceComparison).column_attrs
                if column.key
                not in {
                    "id",
                    "created_at",
                    "input_digest",
                    "baseline_snapshot_id",
                    "engine_version",
                }
            }
            session.add(
                m.PerformanceComparison(
                    **comparison_values,
                    baseline_snapshot_id=archived.id,
                    engine_version=f"archived-arithmetic-{index}",
                    input_digest=f"archive-comparison-{index}",
                    created_at=archived.created_at,
                )
            )
    response = request_client.get(f"/api/v1/runs/{runs[-1]}/github-report-preview")
    assert response.status_code == 200
    report = response.json()
    assert report["performance"]["count"] == 51
    assert report["performance"]["stored_status_counts"] == {
        "REGRESSION": 50,
        "WITHIN_TOLERANCE": 1,
    }
    assert report["performance"]["omitted_items"] == 51 - len(
        report["performance"]["items"]
    )
    assert report["performance"]["omitted_items"] >= 1
    assert "stored_performance_validation_limited" in report["advisory_reasons"]
    assert "stored_performance_numeric_unavailable" in report["advisory_reasons"]
    assert any(
        item["comparison_id"] == old_id and item["status"] == "NUMERIC_UNAVAILABLE"
        for item in report["performance"]["items"]
    )
    canonical_export_bytes(report)
    with session_factory() as session:
        assert _columns(session.get(m.PerformanceComparison, old_id)) == old_record


def test_nonfinite_policy_is_rejected_and_legacy_policy_is_projected_neutrally(
    session_factory, request_client
):
    project, policy, _runs = _seed(session_factory)
    response = request_client.post(
        f"/api/v1/projects/{project}/performance-policies",
        content='{"version":"nonfinite","absolute_tolerance":1e309}',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    with session_factory.begin() as session:
        session.get(m.PerformancePolicy, policy).absolute_tolerance = math.inf
    response = request_client.get(f"/api/v1/projects/{project}/performance-policies")
    assert response.status_code == 200
    assert response.json()[0]["absolute_tolerance"] is None
    assert response.json()[0]["numeric_state"] == "unavailable"


@pytest.mark.parametrize(
    "spread,current_value,unavailable",
    [(1.3e308, 1e308, True), (130.0, 100.0, False)],
    ids=["overflowed-legacy-effect", "ordinary-legacy-rounding"],
)
def test_legacy_effect_integrity_preserves_ordinary_rounding(
    session_factory, request_client, spread, current_value, unavailable
):
    from failurelens.ingestion import parse_artifact
    from failurelens.schemas import RunMetadata
    from failurelens.service import ingest_parsed_report

    with session_factory() as session:
        project = create_project(session, "signed-gauge", "Synthetic signed gauge")
        policy = create_performance_policy(
            session, project, PerformancePolicyCreate(version="signed-gauge-v1")
        )
        for index, value in enumerate((-spread, 0.0, spread, current_value)):
            content = json.dumps(
                {
                    "metrics": {
                        "signed_offset": {
                            "type": "gauge",
                            "contains": "default",
                            "values": {"value": value},
                            "thresholds": {},
                        }
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
                    external_id=f"signed-{index}",
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
        current = session.scalar(
            select(m.PerformanceObservation).where(
                m.PerformanceObservation.run_id == run.id
            )
        )
        row = create_performance_comparison(session, current, policy)
        expected = float(
            Fraction(current_value) / (Fraction(1.4826) * Fraction(spread))
        )
        assert row.effect_size == expected
        # Recorded v1 computation, independently reproduced against c27e2e5:
        # overflowed denominator produced a finite zero, while normal rounding
        # remains a supported historical result.
        legacy_effect = current_value / (1.4826 * spread)
        row.engine_version = "performance-engine-v1"
        row.effect_size = legacy_effect
        row.uncertainty = {
            **row.uncertainty,
            "robust_standardized_change": legacy_effect,
        }
        session.commit()
        row_id, run_id = row.id, run.id
        session.expire_all()
        recorded = _columns(row)
    inputs, retained = _input_records(session_factory), _bytes()
    for item in (
        request_client.get(f"/api/v1/performance-comparisons/{row_id}").json(),
        request_client.get(f"/api/v1/runs/{run_id}/performance-comparisons").json()[0],
    ):
        assert item["numeric_state"] == ("unavailable" if unavailable else "available")
        assert (
            item["effect_size"] is None
            if unavailable
            else item["effect_size"] == legacy_effect
        )
        if unavailable:
            assert expected > 0.5 and legacy_effect == 0.0
            assert item["status"] == "NUMERIC_UNAVAILABLE"
            assert item["recorded_status"] == "INCONCLUSIVE"
            assert "robust_standardized_change" not in item["uncertainty"]
            assert item["uncertainty"]["numeric_state"] == "unavailable"
    report = request_client.get(f"/api/v1/runs/{run_id}/github-report-preview")
    assert report.status_code == 200
    projected = report.json()["performance"]["items"][0]
    # Numeric repair must not widen the existing current_run_metric scope.
    assert projected["evidence_state"] == "unavailable"
    assert projected["status"] == "EVIDENCE_UNAVAILABLE"
    assert projected["uncertainty"] == {}
    with session_factory() as session:
        assert _columns(session.get(m.PerformanceComparison, row_id)) == recorded
    assert inputs == _input_records(session_factory)
    assert retained == _bytes()


def test_new_arithmetic_version_fences_an_already_prepared_publication(
    session_factory, request_client
):
    _project, policy, runs = _seed(session_factory)
    old_id, _baseline_id, recorded, _baseline = _legacy_history(
        session_factory, policy, runs[-1]
    )
    old_digest = request_client.get(
        f"/api/v1/runs/{runs[-1]}/github-report-preview"
    ).json()["report_digest"]
    server = GitHub()
    changed = []

    def recompute_before_transport(request):
        if not changed:
            response = _post(request_client, runs[-1], policy)
            assert response.status_code == 201
            changed.append(response.json()[0]["id"])
        return server.handle(request)

    result = durable_publish(
        session_factory,
        run_id=runs[-1],
        repository="owner/repo",
        pull_number=7,
        token="fake-test-token",
        transport=httpx.MockTransport(recompute_before_transport),
    )
    assert result["status"] == "failed"
    assert result["error_code"] == "report_changed"
    assert changed and changed[0] != old_id
    assert server.writes == []
    current = request_client.get(
        f"/api/v1/runs/{runs[-1]}/github-report-preview"
    ).json()
    assert current["report_digest"] != old_digest
    assert current["performance"]["count"] == 2
    with session_factory() as session:
        assert _columns(session.get(m.PerformanceComparison, old_id)) == recorded
