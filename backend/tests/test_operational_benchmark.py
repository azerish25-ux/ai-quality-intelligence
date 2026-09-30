import pytest
from failurelens.models import Run
from failurelens.models import TestExecution as Execution
from sqlalchemy import func, select

from evaluation.operational_benchmark import (
    hardware_details,
    percentile,
    read_stage_metrics,
    seed_workload,
)


def test_latency_percentile_uses_declared_nearest_rank():
    assert percentile(list(range(1, 101)), 0.95) == 95
    assert percentile([4], 0.95) == 4
    with pytest.raises(ValueError):
        percentile([], 0.95)


def test_workload_has_real_persisted_counts_and_refuses_existing_data(session):
    _project, run, execution = seed_workload(session, runs=4, tests_per_run=5)
    assert session.scalar(select(func.count()).select_from(Run)) == 4
    assert session.scalar(select(func.count()).select_from(Execution)) == 20
    assert session.get(Run, run).source_metadata["benchmark_only"]
    assert session.get(Execution, execution).run_id == run
    with pytest.raises(ValueError, match="empty disposable"):
        seed_workload(session, runs=1, tests_per_run=1)


def test_stage_diagnostic_failure_does_not_discard_load_evidence(monkeypatch):
    import httpx

    def unavailable(*args, **kwargs):
        raise httpx.ReadTimeout("collector-canary-must-not-be-recorded")

    monkeypatch.setattr(httpx, "get", unavailable)
    assert read_stage_metrics("http://127.0.0.1:8000") == {
        "status": "unavailable",
        "metrics": None,
    }


def test_stage_diagnostics_require_expected_schema(monkeypatch):
    import httpx

    def result(payload):
        return httpx.Response(
            200, json=payload, request=httpx.Request("GET", "http://127.0.0.1")
        )

    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: result({"schema_version": "wrong"})
    )
    assert read_stage_metrics("http://127.0.0.1")["status"] == "unavailable"
    payload = {"schema_version": "bounded-telemetry-v1", "stage_counts": {}}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: result(payload))
    assert read_stage_metrics("http://127.0.0.1") == {
        "status": "available",
        "metrics": payload,
    }


def test_hardware_diagnostics_are_bounded_and_do_not_contain_machine_identity():
    result = hardware_details()
    assert set(result) == {"cpu_quota", "memory_limit", "cpu_model", "load_average"}
    assert result["cpu_model"] is None or len(result["cpu_model"]) <= 160
    assert result["cpu_quota"] is None or len(result["cpu_quota"]) <= 100


@pytest.fixture
def benchmark_main(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace

    from evaluation import operational_benchmark as benchmark

    state = {
        "failure_stage": None,
        "cold_failures": 0,
        "warm_failures": 0,
        "cold_count": 4,
        "warm_count": 200,
        "terminated": False,
        "terminate_error": False,
        "wait_timeout": False,
        "kill_error": False,
        "killed": False,
        "kill_attempts": 0,
    }

    def maybe_fail(stage):
        if state["failure_stage"] == stage:
            raise RuntimeError("fixture-private-error-detail-must-not-be-retained")

    class Process:
        def __init__(self, *args, **kwargs):
            maybe_fail("api_startup")

        def poll(self):
            return 1 if state["failure_stage"] == "api_readiness" else None

        def terminate(self):
            if state["terminate_error"]:
                raise OSError("fixture-private-cleanup-detail")
            state["terminated"] = True

        def wait(self, **kwargs):
            if state["wait_timeout"] and not state["killed"]:
                raise benchmark.subprocess.TimeoutExpired("fixture", kwargs["timeout"])
            return 0

        def kill(self):
            state["kill_attempts"] += 1
            if state["kill_error"]:
                raise OSError("fixture-private-kill-detail")
            state["killed"] = True
            state["terminated"] = True

    class Socket:
        def bind(self, address):
            pass

        def getsockname(self):
            return ("127.0.0.1", 43210)

        def close(self):
            pass

    def seed(session):
        maybe_fail("seeding")
        return "fixture-project", "fixture-run", "fixture-execution"

    def measure(base, routes, *, concurrency, samples):
        kind = "cold" if concurrency == 1 else "warm"
        assert samples == (4 if kind == "cold" else 200)
        maybe_fail(kind + "_reads")
        return [
            {
                "route": "fixture",
                "elapsed_ms": 9000 if kind == "cold" else 10,
                "ok": i >= state[kind + "_failures"],
            }
            for i in range(state[kind + "_count"])
        ]

    monkeypatch.setattr(
        benchmark,
        "get_settings",
        lambda: SimpleNamespace(
            demo_mode=True,
            database_url="postgresql+psycopg://synthetic",
            database_pool_size=10,
            database_max_overflow=0,
        ),
    )
    monkeypatch.setattr(
        benchmark, "initialize_database", lambda: maybe_fail("database_initialization")
    )
    monkeypatch.setattr(
        benchmark,
        "SessionLocal",
        lambda: nullcontext(
            SimpleNamespace(scalar=lambda statement: "fixture-postgresql")
        ),
    )
    monkeypatch.setattr(benchmark, "seed_workload", seed)
    monkeypatch.setattr(
        benchmark.subprocess,
        "check_output",
        lambda command, **kwargs: "" if command[1] == "status" else "0" * 40,
    )
    monkeypatch.setattr(benchmark.subprocess, "Popen", Process)
    monkeypatch.setattr(benchmark.socket, "socket", Socket)
    monkeypatch.setattr(
        benchmark.httpx, "get", lambda *args, **kwargs: SimpleNamespace(status_code=200)
    )
    monkeypatch.setattr(benchmark, "measure", measure)
    monkeypatch.setattr(
        benchmark, "hardware_details", lambda: {"cpu_model": "fixture-cpu"}
    )
    monkeypatch.setattr(
        benchmark,
        "read_stage_metrics",
        lambda base: {"status": "available", "metrics": {}},
    )
    output = tmp_path / "benchmark-report"
    monkeypatch.setattr(
        benchmark.sys,
        "argv",
        ["benchmark", "--confirm-disposable-database", "--output", str(output)],
    )
    return benchmark, state, output


@pytest.mark.parametrize(
    "cold_failures,warm_failures", [(1, 0), (0, 1), (4, 200), (0, 0)]
)
def test_benchmark_counts_cold_and_warm_failures_in_acceptance(
    benchmark_main, cold_failures, warm_failures
):
    import json

    benchmark, state, output = benchmark_main
    state.update(cold_failures=cold_failures, warm_failures=warm_failures)
    with pytest.raises(SystemExit) as stopped:
        benchmark.main()
    metrics = json.loads((output / "metrics.json").read_text())
    assert stopped.value.code == (2 if cold_failures or warm_failures else 0)
    assert metrics["failed_requests"] == cold_failures + warm_failures
    assert metrics["cold_failed_requests"] == cold_failures
    assert metrics["warm_failed_requests"] == warm_failures
    assert metrics["targets"]["zero_failed_requests"] is not bool(
        cold_failures or warm_failures
    )
    # Cold latencies and failed samples never alter the original warm denominator.
    assert metrics["warm_p95_ms"] == (10 if warm_failures < 200 else None)
    assert len(json.loads((output / "requests.json").read_text())) == 200
    assert state["terminated"] is True


@pytest.mark.parametrize("kind", ["cold", "warm"])
def test_benchmark_rejects_missing_declared_samples(benchmark_main, kind):
    import json

    benchmark, state, output = benchmark_main
    state[kind + "_count"] -= 1
    with pytest.raises(SystemExit) as stopped:
        benchmark.main()
    metrics = json.loads((output / "metrics.json").read_text())
    assert stopped.value.code == 2
    assert metrics["targets"]["complete_read_samples"] is False
    assert metrics["failed_requests"] == 0


@pytest.mark.parametrize(
    "stage",
    [
        "database_initialization",
        "seeding",
        "api_startup",
        "api_readiness",
        "cold_reads",
        "warm_reads",
    ],
)
def test_benchmark_retains_stage_failures_without_exception_text(
    benchmark_main, stage, capsys
):
    import json

    benchmark, state, output = benchmark_main
    state["failure_stage"] = stage
    with pytest.raises(SystemExit) as stopped:
        benchmark.main()
    metrics = json.loads((output / "metrics.json").read_text())
    captured = capsys.readouterr()
    assert stopped.value.code == 2
    assert metrics["execution"]["status"] == "failed"
    assert metrics["execution"]["failure"] == {
        "stage": stage,
        "error_type": "RuntimeError",
    }
    assert metrics["targets"]["measurement_completed"] is False
    assert (
        "fixture-private-error-detail"
        not in json.dumps(metrics) + captured.out + captured.err
    )
    assert (output / "requests.json").exists()
    if stage in {"api_readiness", "cold_reads", "warm_reads"}:
        assert state["terminated"] is True
    if stage == "warm_reads":
        assert len(metrics["cold_reads"]) == 4


def test_benchmark_wait_timeout_uses_one_bounded_force_stop(benchmark_main):
    import json

    benchmark, state, output = benchmark_main
    state["wait_timeout"] = True
    with pytest.raises(SystemExit) as stopped:
        benchmark.main()
    metrics = json.loads((output / "metrics.json").read_text())
    assert stopped.value.code == 0
    assert state["killed"] is True
    assert state["kill_attempts"] == 1
    assert metrics["execution"]["cleanup_forced"] is True
    assert metrics["execution"]["cleanup_error_type"] is None


@pytest.mark.parametrize(
    "measurement_failure,kill_error", [(False, False), (True, False), (False, True)]
)
def test_cleanup_failure_cannot_erase_primary_failure_or_report_acceptance(
    benchmark_main, measurement_failure, kill_error, capsys
):
    import json

    benchmark, state, output = benchmark_main
    state["terminate_error"] = True
    state["kill_error"] = kill_error
    if measurement_failure:
        state["failure_stage"] = "warm_reads"
    with pytest.raises(SystemExit) as stopped:
        benchmark.main()
    metrics = json.loads((output / "metrics.json").read_text())
    captured = capsys.readouterr()
    assert stopped.value.code == 2
    assert state["kill_attempts"] == 1
    assert metrics["targets"]["measurement_completed"] is False
    assert metrics["execution"]["cleanup_error_type"] == "OSError"
    assert metrics["execution"]["cleanup_fallback_error_type"] == (
        "OSError" if kill_error else None
    )
    assert metrics["execution"]["failure"] == {
        "stage": "warm_reads" if measurement_failure else "api_cleanup",
        "error_type": "RuntimeError" if measurement_failure else "OSError",
    }
    assert "fixture-private-" not in json.dumps(metrics) + captured.out + captured.err
