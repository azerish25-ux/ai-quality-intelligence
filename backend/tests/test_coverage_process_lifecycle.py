"""Owned-process cancellation remains bounded and cannot grant acceptance."""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import backend_coverage as runner

ROOT = Path(__file__).resolve().parents[2]
IDENTITY = {"revision": "synthetic-lifecycle-revision"}
SNAPSHOT = {"synthetic.py": "synthetic-source-digest"}
LINUX_PROCESSES = pytest.mark.skipif(
    not sys.platform.startswith("linux")
    or not hasattr(os, "pidfd_open")
    or not hasattr(signal, "pidfd_send_signal"),
    reason="owned-process lifecycle probes require Linux pidfds",
)

HARNESS = """
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts import backend_coverage as runner
output = Path(sys.argv[2])
runner.TEST_TIMEOUT_SECONDS = float(sys.argv[3])
runner.TERMINATION_GRACE_SECONDS = 0.1
runner.host_oom_kills = lambda: None
try:
    code = runner.run_test_process(
        [sys.executable, '-I', '-S', '-c', sys.argv[4], str(output)],
        output, {}, output,
        {'revision': 'synthetic-lifecycle-revision'},
        {'synthetic.py': 'synthetic-source-digest'},
    )
except runner.CoverageError:
    raise SystemExit(2)
raise SystemExit(code)
"""

CHILD_PREFIX = """
import os, signal, sys, time
from pathlib import Path
output = Path(sys.argv[1])
signal.alarm(12)
(output / 'child.pid').write_text(str(os.getpid()))
"""

HANGING_CHILD = (
    CHILD_PREFIX
    + """
(output / 'ready').write_text('ready')
while True:
    time.sleep(0.05)
"""
)

IGNORING_DESCENDANT = """
import os, signal, sys, time
from pathlib import Path
signal.alarm(12)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
output = Path(sys.argv[1])
(output / 'descendant.pid').write_text(str(os.getpid()))
while True:
    time.sleep(0.05)
"""

LEADER_EXITS_ZERO = (
    CHILD_PREFIX
    + f"""
import subprocess
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
subprocess.Popen([sys.executable, '-I', '-S', '-c', {IGNORING_DESCENDANT!r}, str(output)])
while not (output / 'descendant.pid').is_file():
    time.sleep(0.01)
(output / 'ready').write_text('ready')
while True:
    time.sleep(0.05)
"""
)

LEADER_NORMAL_EXIT = (
    CHILD_PREFIX
    + f"""
import subprocess
subprocess.Popen([sys.executable, '-I', '-S', '-c', {IGNORING_DESCENDANT!r}, str(output)])
while not (output / 'descendant.pid').is_file():
    time.sleep(0.01)
(output / 'ready').write_text('ready')
while not (output / 'release').is_file():
    time.sleep(0.01)
"""
)


def read_execution(output: Path) -> dict:
    return json.loads((output / "test-execution.json").read_text())


def assert_no_acceptance(output: Path) -> None:
    assert not (output / "report.json").exists()
    assert not (output / "coverage-data.sqlite").exists()
    assert read_execution(output)["measurement_complete"] is False


def wait_for_file(path: Path, process: subprocess.Popen, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size:
            return
        if process.poll() is not None:
            pytest.fail(f"synthetic collector exited before {path.name} was ready")
        time.sleep(0.01)
    pytest.fail(f"synthetic collector did not create {path.name} before the guard")


def owned_pidfd(output: Path, marker: str) -> int | None:
    """Pin only a synthetic process carrying this test's unique output path."""
    path = output / marker
    if not path.is_file():
        return None
    pid = int(path.read_text())
    try:
        descriptor = os.pidfd_open(pid)
    except ProcessLookupError:
        return None
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except FileNotFoundError:
        os.close(descriptor)
        return None
    if os.fsencode(output) not in command:
        os.close(descriptor)
        return None
    return descriptor


@contextmanager
def synthetic_collector(tmp_path: Path, child: str, timeout: float = 60):
    output = tmp_path / "measurement"
    output.mkdir()
    process = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-c",
            HARNESS,
            str(ROOT),
            str(output),
            str(timeout),
            child,
        ],
        cwd=output,
        env={},
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    descriptors = []

    def track(marker: str) -> int:
        wait_for_file(output / marker, process)
        descriptor = owned_pidfd(output, marker)
        assert descriptor is not None, "synthetic child must still be alive"
        descriptors.append(descriptor)
        return descriptor

    try:
        yield SimpleNamespace(output=output, process=process, track=track)
    finally:
        # Pin any child created immediately before a failed readiness assertion.
        # Never signal a saved numeric PID or an unverified process group here.
        for marker in ("child.pid", "descendant.pid"):
            descriptor = owned_pidfd(output, marker)
            if descriptor is not None:
                descriptors.append(descriptor)
        for descriptor in descriptors:
            try:
                signal.pidfd_send_signal(descriptor, signal.SIGKILL)
            except ProcessLookupError:
                pass
            finally:
                os.close(descriptor)
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)
        assert process.stderr is not None
        process.stderr.close()


def finish(probe, expected: int) -> None:
    assert probe.process.wait(timeout=8) == expected


def assert_exited(descriptor: int) -> None:
    readable, _, _ = select.select([descriptor], [], [], 2)
    assert readable, "owned child survived collector cleanup"


@LINUX_PROCESSES
def test_real_timeout_preserves_terminal_evidence_and_reaps_child(tmp_path):
    with synthetic_collector(tmp_path, HANGING_CHILD, timeout=1.5) as probe:
        child = probe.track("child.pid")
        finish(probe, 2)
        assert_exited(child)
        execution = read_execution(probe.output)
        assert execution["status"] == "timed_out"
        assert execution["pytest_exit_code"] == -signal.SIGTERM
        assert execution["termination_signal"] == signal.SIGTERM
        assert execution["collector_signal"] is None
        assert execution["source_revision_at_start"] == IDENTITY["revision"]
        assert execution["elapsed_seconds"] >= execution["deadline_seconds"]
        assert_no_acceptance(probe.output)


@LINUX_PROCESSES
def test_timeout_exit_zero_leader_cannot_hide_term_ignoring_descendant(tmp_path):
    with synthetic_collector(tmp_path, LEADER_EXITS_ZERO, timeout=1.5) as probe:
        child = probe.track("child.pid")
        descendant = probe.track("descendant.pid")
        finish(probe, 2)
        assert_exited(child)
        assert_exited(descendant)
        execution = read_execution(probe.output)
        assert execution["status"] == "timed_out"
        assert execution["pytest_exit_code"] == 0
        assert execution["termination_signal"] is None
        assert_no_acceptance(probe.output)


@LINUX_PROCESSES
@pytest.mark.parametrize("received", [signal.SIGINT, signal.SIGTERM])
def test_real_collector_signals_preserve_interruption_and_kill_children(
    tmp_path, received
):
    with synthetic_collector(tmp_path, LEADER_EXITS_ZERO) as probe:
        child = probe.track("child.pid")
        descendant = probe.track("descendant.pid")
        wait_for_file(probe.output / "ready", probe.process)
        probe.process.send_signal(received)
        finish(probe, 2)
        assert_exited(child)
        assert_exited(descendant)
        execution = read_execution(probe.output)
        assert execution["status"] == "interrupted"
        assert execution["collector_signal"] == received
        assert execution["pytest_exit_code"] == 0
        assert execution["termination_signal"] is None
        assert_no_acceptance(probe.output)


@LINUX_PROCESSES
def test_collector_hard_kill_leaves_valid_initial_incomplete_record(tmp_path):
    with synthetic_collector(tmp_path, HANGING_CHILD) as probe:
        probe.track("child.pid")
        wait_for_file(probe.output / "ready", probe.process)
        initial = read_execution(probe.output)
        probe.process.kill()
        finish(probe, -signal.SIGKILL)
        assert read_execution(probe.output) == initial
        assert initial["status"] == "running"
        assert initial["pytest_exit_code"] is None
        assert initial["termination_signal"] is None
        assert_no_acceptance(probe.output)


@LINUX_PROCESSES
def test_normal_leader_exit_cleans_remaining_owned_descendant(tmp_path):
    with synthetic_collector(tmp_path, LEADER_NORMAL_EXIT) as probe:
        child = probe.track("child.pid")
        descendant = probe.track("descendant.pid")
        wait_for_file(probe.output / "ready", probe.process)
        (probe.output / "release").write_text("release")
        finish(probe, 0)
        assert_exited(child)
        assert_exited(descendant)
        execution = read_execution(probe.output)
        assert execution["status"] == "exited"
        assert execution["pytest_exit_code"] == 0
        assert execution["collector_signal"] is None
        assert_no_acceptance(probe.output)


def test_launch_failure_retains_terminal_evidence_and_restores_handlers(
    tmp_path, monkeypatch
):
    before = {
        value: signal.getsignal(value) for value in (signal.SIGINT, signal.SIGTERM)
    }

    def unavailable(*args, **kwargs):
        raise OSError("synthetic launch failure")

    monkeypatch.setattr(runner.subprocess, "Popen", unavailable)
    monkeypatch.setattr(runner, "host_oom_kills", lambda: None)
    with pytest.raises(OSError, match="synthetic launch failure"):
        runner.run_test_process([], tmp_path, {}, tmp_path, IDENTITY, SNAPSHOT)
    execution = read_execution(tmp_path)
    assert execution["status"] == "collector_error"
    assert execution["pytest_exit_code"] is None
    assert execution["termination_signal"] is None
    assert_no_acceptance(tmp_path)
    assert {value: signal.getsignal(value) for value in before} == before


def fake_completed_process(monkeypatch, *, interrupt=None):
    events = []
    process = SimpleNamespace(pid=12345, returncode=None)

    def wait(*, timeout):
        events.append("reap")
        process.returncode = 0
        return 0

    def observe(*args):
        events.append("observe")
        if interrupt is not None:
            signal.getsignal(interrupt)(interrupt, None)
        return SimpleNamespace(si_pid=process.pid, si_code=os.CLD_EXITED, si_status=0)

    process.wait = wait
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(runner.os, "waitid", observe)
    monkeypatch.setattr(
        runner.os, "killpg", lambda pid, signum: events.append((pid, signum))
    )
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    monkeypatch.setattr(runner, "host_oom_kills", lambda: None)
    return events


def test_initial_incomplete_record_is_written_before_process_launch(
    tmp_path, monkeypatch
):
    fake_completed_process(monkeypatch)
    original_launch = runner.subprocess.Popen

    def checked_launch(*args, **kwargs):
        execution = read_execution(tmp_path)
        assert execution["status"] == "running"
        assert execution["measurement_complete"] is False
        assert execution["pytest_exit_code"] is None
        assert execution["termination_signal"] is None
        assert execution["collector_signal"] is None
        return original_launch(*args, **kwargs)

    monkeypatch.setattr(runner.subprocess, "Popen", checked_launch)
    assert runner.run_test_process([], tmp_path, {}, tmp_path, IDENTITY, SNAPSHOT) == 0
    assert read_execution(tmp_path)["status"] == "exited"
    assert_no_acceptance(tmp_path)


def test_terminal_replace_failure_preserves_initial_record_and_handlers(
    tmp_path, monkeypatch
):
    before = {
        value: signal.getsignal(value) for value in (signal.SIGINT, signal.SIGTERM)
    }
    fake_completed_process(monkeypatch)

    def unavailable(self, target):
        raise OSError("synthetic final replacement failure")

    monkeypatch.setattr(runner.Path, "replace", unavailable)
    with pytest.raises(OSError, match="synthetic final replacement failure"):
        runner.run_test_process([], tmp_path, {}, tmp_path, IDENTITY, SNAPSHOT)
    execution = read_execution(tmp_path)
    assert execution["status"] == "running"
    assert execution["pytest_exit_code"] is None
    assert_no_acceptance(tmp_path)
    assert {value: signal.getsignal(value) for value in before} == before


def test_cancellation_racing_exit_zero_cleans_group_before_reaping(
    tmp_path, monkeypatch
):
    before = {
        value: signal.getsignal(value) for value in (signal.SIGINT, signal.SIGTERM)
    }
    events = fake_completed_process(monkeypatch, interrupt=signal.SIGINT)
    with pytest.raises(runner.CoverageError, match="test-process-interrupted"):
        runner.run_test_process([], tmp_path, {}, tmp_path, IDENTITY, SNAPSHOT)
    assert events.index((12345, signal.SIGKILL)) < events.index("reap")
    execution = read_execution(tmp_path)
    assert execution["status"] == "interrupted"
    assert execution["collector_signal"] == signal.SIGINT
    assert execution["pytest_exit_code"] == 0
    assert_no_acceptance(tmp_path)
    assert {value: signal.getsignal(value) for value in before} == before


def test_repeated_cancellation_does_not_interrupt_group_cleanup(tmp_path, monkeypatch):
    events = fake_completed_process(monkeypatch, interrupt=signal.SIGINT)

    def second_signal(_):
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        handler(signal.SIGTERM, None)

    monkeypatch.setattr(runner.time, "sleep", second_signal)
    with pytest.raises(runner.CoverageError, match="test-process-interrupted"):
        runner.run_test_process([], tmp_path, {}, tmp_path, IDENTITY, SNAPSHOT)
    assert (
        events.index((12345, signal.SIGTERM))
        < events.index((12345, signal.SIGKILL))
        < events.index("reap")
    )
    assert read_execution(tmp_path)["status"] == "interrupted"
    assert_no_acceptance(tmp_path)


def test_cancellation_during_final_replace_cannot_return_success(tmp_path, monkeypatch):
    before = {
        value: signal.getsignal(value) for value in (signal.SIGINT, signal.SIGTERM)
    }
    fake_completed_process(monkeypatch)
    original_replace = runner.Path.replace

    def interrupted_replace(self, target):
        handler = signal.getsignal(signal.SIGINT)
        assert callable(handler), "cancellation handling must cover final replacement"
        handler(signal.SIGINT, None)
        return original_replace(self, target)

    monkeypatch.setattr(runner.Path, "replace", interrupted_replace)
    with pytest.raises(runner.CoverageError, match="test-process-"):
        runner.run_test_process([], tmp_path, {}, tmp_path, IDENTITY, SNAPSHOT)
    assert_no_acceptance(tmp_path)
    assert {value: signal.getsignal(value) for value in before} == before
