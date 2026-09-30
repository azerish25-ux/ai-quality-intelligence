import pytest
from sqlalchemy import func, select

from evaluation.operational_benchmark import hardware_details, percentile, read_stage_metrics, seed_workload
from failurelens.models import Run, TestExecution as Execution


def test_latency_percentile_uses_declared_nearest_rank():
    assert percentile(list(range(1, 101)), .95) == 95
    assert percentile([4], .95) == 4
    with pytest.raises(ValueError):
        percentile([], .95)


def test_workload_has_real_persisted_counts_and_refuses_existing_data(session):
    project, run, execution = seed_workload(session, runs=4, tests_per_run=5)
    assert session.scalar(select(func.count()).select_from(Run)) == 4
    assert session.scalar(select(func.count()).select_from(Execution)) == 20
    assert session.get(Run, run).source_metadata['benchmark_only']
    assert session.get(Execution, execution).run_id == run
    with pytest.raises(ValueError, match='empty disposable'):
        seed_workload(session, runs=1, tests_per_run=1)


def test_stage_diagnostic_failure_does_not_discard_load_evidence(monkeypatch):
    import httpx
    def unavailable(*args, **kwargs):
        raise httpx.ReadTimeout('collector-canary-must-not-be-recorded')
    monkeypatch.setattr(httpx, 'get', unavailable)
    assert read_stage_metrics('http://127.0.0.1:8000') == {'status': 'unavailable', 'metrics': None}


def test_stage_diagnostics_require_expected_schema(monkeypatch):
    import httpx
    def result(payload):
        return httpx.Response(200, json=payload, request=httpx.Request('GET', 'http://127.0.0.1'))
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: result({'schema_version': 'wrong'}))
    assert read_stage_metrics('http://127.0.0.1')['status'] == 'unavailable'
    payload = {'schema_version': 'bounded-telemetry-v1', 'stage_counts': {}}
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: result(payload))
    assert read_stage_metrics('http://127.0.0.1') == {'status': 'available', 'metrics': payload}


def test_hardware_diagnostics_are_bounded_and_do_not_contain_machine_identity():
    result = hardware_details()
    assert set(result) == {'cpu_quota', 'memory_limit', 'cpu_model', 'load_average'}
    assert result['cpu_model'] is None or len(result['cpu_model']) <= 160
    assert result['cpu_quota'] is None or len(result['cpu_quota']) <= 100
