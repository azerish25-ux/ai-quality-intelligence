"""Optional bounded CPU observations for the two owned benchmark processes."""

from __future__ import annotations

import math
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

MAX_STAT_BYTES = 4096
MAX_COUNTER = 2**64 - 1


@dataclass(frozen=True, slots=True)
class ProcessCPU:
    pid: int
    start_ticks: int
    clock_ticks: int
    user_ticks: int
    system_ticks: int
    threads: int
    sampled_at: float


def _valid_sample(value):
    return (
        isinstance(value, ProcessCPU)
        and type(value.pid) is int
        and 0 < value.pid < 2**31
        and type(value.clock_ticks) is int
        and 0 < value.clock_ticks <= 10**9
        and all(
            type(counter) is int and 0 <= counter <= MAX_COUNTER
            for counter in (value.start_ticks, value.user_ticks, value.system_ticks)
        )
        and type(value.threads) is int
        and 1 <= value.threads <= 10**6
        and type(value.sampled_at) is float
        and math.isfinite(value.sampled_at)
    )


def _parse_stat(pid, raw, clock_ticks, sampled_at):
    # Linux proc_pid_stat(5): fields 14/15 are process CPU ticks, 20 threads,
    # and 22 start time. Fields 16/17 (waited-for child CPU) are not included.
    # https://man7.org/linux/man-pages/man5/proc_pid_stat.5.html
    if len(raw) > MAX_STAT_BYTES or not raw.startswith(str(pid).encode() + b" ("):
        raise ValueError("invalid process counter record")
    _label, separator, tail = raw.rpartition(b")")
    fields = tail.split()
    if not separator or len(fields) < 20 or len(fields[0]) != 1:
        raise ValueError("invalid process counter record")
    sample = ProcessCPU(
        pid=pid,
        start_ticks=int(fields[19]),
        clock_ticks=clock_ticks,
        user_ticks=int(fields[11]),
        system_ticks=int(fields[12]),
        threads=int(fields[17]),
        sampled_at=sampled_at,
    )
    if not _valid_sample(sample):
        raise ValueError("invalid process counter record")
    return sample


def process_cpu_snapshot(pid):
    """Read bounded numeric fields only; never return process names or raw data."""
    if type(pid) is not int or not 0 < pid < 2**31:
        return None
    try:
        with Path(f"/proc/{pid}/stat").open("rb") as handle:
            raw = handle.read(MAX_STAT_BYTES + 1)
        return _parse_stat(pid, raw, os.sysconf("SC_CLK_TCK"), time.monotonic())
    except (OSError, ValueError, TypeError, OverflowError, AttributeError):
        return None


def warm_cpu_snapshot(api_process):
    """Observe the client and its still-owned, unreaped API subprocess."""
    client = process_cpu_snapshot(os.getpid())
    api = None
    try:
        # An exited child is reaped by poll; do not read a subsequently reused PID.
        if api_process.poll() is None:
            api = process_cpu_snapshot(getattr(api_process, "pid", None))
            if api_process.poll() is not None:
                api = None
    except (OSError, subprocess.SubprocessError, AttributeError):
        api = None
    return {"client": client, "api": api}


def _cpu_delta(before, after):
    empty = {
        "status": "unavailable",
        "reason": "sample_unavailable",
        "user_seconds": None,
        "system_seconds": None,
        "total_seconds": None,
        "wall_seconds": None,
        "cpu_seconds_per_wall_second": None,
        "clock_tick_seconds": None,
        "threads_before": None,
        "threads_after": None,
    }
    if not _valid_sample(before) or not _valid_sample(after):
        return empty
    if (before.pid, before.start_ticks) != (after.pid, after.start_ticks):
        return {**empty, "reason": "process_changed"}
    if before.clock_ticks != after.clock_ticks:
        return {**empty, "reason": "clock_changed"}
    if after.user_ticks < before.user_ticks or after.system_ticks < before.system_ticks:
        return {**empty, "reason": "counter_decreased"}
    wall = after.sampled_at - before.sampled_at
    if not math.isfinite(wall) or wall <= 0:
        return {**empty, "reason": "invalid_interval"}
    user = (after.user_ticks - before.user_ticks) / before.clock_ticks
    system = (after.system_ticks - before.system_ticks) / before.clock_ticks
    total = user + system
    per_wall = total / wall
    if not all(math.isfinite(value) for value in (user, system, total, per_wall)):
        return {**empty, "reason": "nonfinite_derived"}
    return {
        "status": "available",
        "reason": None,
        "user_seconds": user,
        "system_seconds": system,
        "total_seconds": total,
        "wall_seconds": wall,
        "cpu_seconds_per_wall_second": per_wall,
        "clock_tick_seconds": 1 / before.clock_ticks,
        "threads_before": before.threads,
        "threads_after": after.threads,
    }


def warm_cpu_metrics(before, after):
    rows = {
        role: _cpu_delta(before.get(role), after.get(role))
        for role in ("client", "api")
    }
    available = sum(row["status"] == "available" for row in rows.values())
    return {
        "status": "available"
        if available == 2
        else "partial"
        if available
        else "unavailable",
        "scope": "owned_client_and_launched_api_process_warm_interval",
        **rows,
        "limitations": [
            "Excludes PostgreSQL, descendants and other processes; not whole-stack CPU",
            "Sampling includes observation overhead and does not measure per-route CPU or latency",
            "Counter resolution is reported; CPU consumption alone does not establish a latency cause",
        ],
    }
