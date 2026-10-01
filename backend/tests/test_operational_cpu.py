"""Warm CPU metadata is bounded, non-identifying and separate from latency gates."""

import json
import os
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
import test_operational_benchmark as benchmark_tests

from evaluation import operational_cpu as cpu

benchmark_main = benchmark_tests.benchmark_main


def _stat(pid=123, *, user=100, system=50, threads=2, start=900):
    fields = [b"R"] + [b"0"] * 19
    for field, value in {14: user, 15: system, 20: threads, 22: start}.items():
        fields[field - 3] = str(value).encode()
    return str(pid).encode() + b" (do-not-retain ) process-label) " + b" ".join(fields)


def _sample(**changes):
    return replace(cpu.ProcessCPU(123, 900, 100, 100, 50, 2, 10.0), **changes)


def _snapshots():
    before = {"client": _sample(), "api": _sample(pid=124)}
    after = {
        "client": _sample(user_ticks=250, system_ticks=100, threads=4, sampled_at=12.0),
        "api": _sample(pid=124, user_ticks=300, system_ticks=100, sampled_at=12.0),
    }
    return before, after


def test_counter_units_and_independent_processes_have_exact_expected_deltas():
    before, after = _snapshots()
    result = cpu.warm_cpu_metrics(before, after)
    assert result["status"] == "available"
    assert result["client"] == {
        "status": "available",
        "reason": None,
        "user_seconds": 1.5,
        "system_seconds": 0.5,
        "total_seconds": 2.0,
        "wall_seconds": 2.0,
        "cpu_seconds_per_wall_second": 1.0,
        "clock_tick_seconds": 0.01,
        "threads_before": 2,
        "threads_after": 4,
    }
    assert result["api"]["user_seconds"] == 2.0
    assert result["api"]["system_seconds"] == 0.5
    assert result["api"]["cpu_seconds_per_wall_second"] == 1.25
    assert not {"pid", "start_ticks", "sampled_at", "raw", "comm"} & set(result["api"])
    encoded = json.dumps(result, allow_nan=False)
    assert "do-not-retain" not in encoded


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"pid": 321}, "process_changed"),
        ({"start_ticks": 901}, "process_changed"),
        ({"clock_ticks": 1000}, "clock_changed"),
        ({"user_ticks": 99}, "counter_decreased"),
        ({"system_ticks": 49}, "counter_decreased"),
        ({"sampled_at": 10.0}, "invalid_interval"),
        ({"sampled_at": 9.0}, "invalid_interval"),
        ({"sampled_at": float("nan")}, "sample_unavailable"),
        ({"sampled_at": float("inf")}, "sample_unavailable"),
        ({"sampled_at": 10**400}, "sample_unavailable"),
        ({"user_ticks": -1}, "sample_unavailable"),
        ({"user_ticks": cpu.MAX_COUNTER + 1}, "sample_unavailable"),
        ({"clock_ticks": 0}, "sample_unavailable"),
        ({"threads": 0}, "sample_unavailable"),
    ],
)
def test_invalid_or_replaced_process_is_unavailable_without_losing_the_other_role(
    changes, reason
):
    before, after = _snapshots()
    after["api"] = replace(after["api"], **changes)
    result = cpu.warm_cpu_metrics(before, after)
    assert result["status"] == "partial"
    assert result["client"]["total_seconds"] == 2.0
    assert result["api"]["reason"] == reason
    assert result["api"]["status"] == "unavailable"
    assert all(
        value is None
        for key, value in result["api"].items()
        if key not in {"reason", "status"}
    )
    json.dumps(result, allow_nan=False)


def test_unrepresentable_rate_is_unavailable_instead_of_infinite_or_clipped():
    before = {"client": _sample(sampled_at=0.0), "api": None}
    after = {
        "client": _sample(sampled_at=5e-324, user_ticks=cpu.MAX_COUNTER),
        "api": None,
    }
    result = cpu.warm_cpu_metrics(before, after)
    assert result["status"] == "unavailable"
    assert result["client"]["reason"] == "nonfinite_derived"
    assert result["client"]["total_seconds"] is None
    json.dumps(result, allow_nan=False)


def test_real_owned_process_can_be_observed_without_retaining_identity():
    first = cpu.process_cpu_snapshot(os.getpid())
    assert first is not None
    second = cpu.process_cpu_snapshot(os.getpid())
    assert second is not None
    assert first.pid == second.pid == os.getpid()
    assert first.start_ticks == second.start_ticks
    assert second.user_ticks >= first.user_ticks
    assert second.system_ticks >= first.system_ticks
    assert second.sampled_at > first.sampled_at
    result = cpu.warm_cpu_metrics({"client": first}, {"client": second})
    assert result["client"]["status"] == "available"
    assert result["client"]["total_seconds"] >= 0
    json.dumps(result, allow_nan=False)


def test_bounded_proc_read_handles_parentheses_and_closes_its_file(monkeypatch):
    opened = []

    class Record(BytesIO):
        def read(self, count=-1):
            assert count == cpu.MAX_STAT_BYTES + 1
            return super().read(count)

    def open_record(path, mode):
        assert str(path) == "/proc/123/stat" and mode == "rb"
        handle = Record(_stat())
        opened.append(handle)
        return handle

    monkeypatch.setattr(Path, "open", open_record)
    monkeypatch.setattr(
        cpu.os, "sysconf", lambda name: 100 if name == "SC_CLK_TCK" else None
    )
    monkeypatch.setattr(cpu.time, "monotonic", lambda: 10.0)
    assert cpu.process_cpu_snapshot(123) == _sample()
    assert len(opened) == 1 and opened[0].closed


@pytest.mark.parametrize("pid", [None, True, "123", -1, 0, 2**31])
def test_invalid_process_identity_never_selects_a_file(monkeypatch, pid):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid identity must not open a path")

    monkeypatch.setattr(Path, "open", forbidden)
    assert cpu.process_cpu_snapshot(pid) is None


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"123 no-parentheses",
        b"123 (unterminated",
        b"123 (short) R 0",
        b"456 (other) R",
        _stat() + b"x" * cpu.MAX_STAT_BYTES,
        _stat(user=-1),
        _stat(threads=0),
        _stat(system="unavailable"),
    ],
)
def test_bad_proc_payload_is_unavailable_and_never_echoed(monkeypatch, raw):
    opened = []

    def open_record(*args, **kwargs):
        handle = BytesIO(raw)
        opened.append(handle)
        return handle

    monkeypatch.setattr(Path, "open", open_record)
    assert cpu.process_cpu_snapshot(123) is None
    assert len(opened) == 1 and opened[0].closed


def test_proc_access_failure_is_optional_and_message_free(monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("process-diagnostic-canary")

    monkeypatch.setattr(Path, "open", denied)
    assert cpu.process_cpu_snapshot(123) is None
    assert "process-diagnostic-canary" not in json.dumps(cpu.warm_cpu_metrics({}, {}))


@pytest.mark.parametrize("ticks", [None, 0, -1, True, 100.0, 2**64])
def test_unsupported_clock_units_are_not_guessed(monkeypatch, ticks):
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: BytesIO(_stat()))
    monkeypatch.setattr(cpu.os, "sysconf", lambda name: ticks)
    assert cpu.process_cpu_snapshot(123) is None


@pytest.mark.parametrize("exit_at", ["before", "during", "error-after", "never"])
def test_exited_child_is_not_read_as_a_reused_process(monkeypatch, exit_at):
    calls = []
    polls = []

    class Process:
        pid = 124

        def poll(self):
            polls.append(True)
            if exit_at == "error-after" and len(polls) == 2:
                raise OSError("unavailable-process-canary")
            return (
                0
                if exit_at == "before" or (exit_at == "during" and len(polls) == 2)
                else None
            )

    def read(pid):
        calls.append(pid)
        return _sample(pid=pid)

    monkeypatch.setattr(cpu.os, "getpid", lambda: 123)
    monkeypatch.setattr(cpu, "process_cpu_snapshot", read)
    result = cpu.warm_cpu_snapshot(Process())
    assert result["client"] == _sample()
    assert calls == ([123] if exit_at == "before" else [123, 124])
    assert result["api"] == (_sample(pid=124) if exit_at == "never" else None)


@pytest.mark.parametrize("available", [False, True])
def test_cpu_metadata_never_changes_request_counts_latency_or_acceptance(
    benchmark_main, monkeypatch, available
):
    benchmark, state, output = benchmark_main
    original_measure = benchmark.measure
    measured = []
    sequence = []

    def measure(base, routes, *, concurrency, samples):
        measured.append((concurrency, samples))
        sequence.append("cold" if concurrency == 1 else "warm")
        return original_measure(base, routes, concurrency=concurrency, samples=samples)

    monkeypatch.setattr(benchmark, "measure", measure)
    before, after = _snapshots() if available else ({}, {})
    observations = iter([before, after])

    def observe(process):
        sequence.append("cpu")
        return next(observations)

    monkeypatch.setattr(benchmark, "warm_cpu_snapshot", observe)
    with pytest.raises(SystemExit) as stopped:
        benchmark.main()
    assert stopped.value.code == 0
    metrics = json.loads((output / "metrics.json").read_text())
    assert metrics["warm_process_cpu"]["status"] == (
        "available" if available else "unavailable"
    )
    assert metrics["recorded_requests"] == {"cold": 4, "warm": 200}
    assert metrics["targets"] == {
        "zero_failed_requests": True,
        "complete_read_samples": True,
        "api_read_p95_under_500ms": True,
        "measurement_completed": True,
    }
    assert metrics["api_process"]["workers"] == 1
    assert measured == [(1, 4), (10, 200)]
    assert sequence == ["cold", "cpu", "warm", "cpu"]
    assert metrics["warm_p95_ms"] == metrics["warm_p50_ms"] == 10
    assert state["terminated"] is True


@pytest.mark.parametrize(
    ("stage", "cpu_status"),
    [("api_readiness", "not_run"), ("warm_reads", "incomplete")],
)
def test_incomplete_load_keeps_its_failure_and_does_not_claim_complete_cpu_data(
    benchmark_main, stage, cpu_status
):
    benchmark, state, output = benchmark_main
    state["failure_stage"] = stage
    with pytest.raises(SystemExit) as stopped:
        benchmark.main()
    assert stopped.value.code == 2
    metrics = json.loads((output / "metrics.json").read_text())
    assert metrics["execution"]["failure"] == {
        "stage": stage,
        "error_type": "RuntimeError",
    }
    assert metrics["warm_process_cpu"]["status"] == cpu_status
    assert metrics["targets"]["measurement_completed"] is False
    assert metrics["targets"]["complete_read_samples"] is False
    assert state["terminated"] is True
