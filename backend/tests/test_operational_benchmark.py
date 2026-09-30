import pytest
from sqlalchemy import func, select

from evaluation.operational_benchmark import percentile, seed_workload
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
