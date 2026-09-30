"""The sensitivity runner must not confuse broken infrastructure with a kill."""

import subprocess
from dataclasses import replace

import pytest

from evaluation import mutation_runner as runner
from evaluation.mutation_cases import BY_ID, CASES

CASE = BY_ID["redaction"]


def receipt(mode="mutant", outcome="failed"):
    call = {"test_id": CASE.test_id, "when": "call", "outcome": outcome}
    if outcome == "failed":
        call.update(
            exception_type="AssertionError",
            assertion_in_test=True,
            failure_source=CASE.test_id.split("::")[0],
            failure_line=7,
        )
    return {
        "case_id": CASE.id,
        "mode": mode,
        "nonce": "synthetic-nonce",
        "exit_code": 1 if outcome == "failed" else 0,
        "collected": [CASE.test_id],
        "collection_errors": 0,
        "runtime_source": "backend/src/failurelens/redaction.py",
        "mutation_applied": mode == "mutant",
        "mutation_calls": int(mode == "mutant"),
        "effect_calls": int(mode == "mutant"),
        "phases": [
            {"test_id": CASE.test_id, "when": "setup", "outcome": "passed"},
            call,
            {"test_id": CASE.test_id, "when": "teardown", "outcome": "passed"},
        ],
    }


def assess(payload, **kwargs):
    return runner.assess_phase(
        payload,
        case=CASE,
        mode=payload.get("mode", "mutant"),
        nonce="synthetic-nonce",
        returncode=payload.get("exit_code", 1),
        provenance_ok=kwargs.get("provenance_ok", True),
    )


def test_classifier_distinguishes_a_real_kill_survivor_and_passing_baseline():
    assert assess(receipt())[0] == "killed"
    assert assess(receipt(outcome="passed"))[0] == "survived"
    assert assess(receipt(mode="baseline", outcome="passed"))[0] == "passed"
    assert assess(receipt(mode="baseline"))[0] == "error"


@pytest.mark.parametrize(
    "alteration",
    [
        {"collection_errors": 1},
        {"collected": []},
        {"collected": ["wrong::test"]},
        {"nonce": "old-replayed-report"},
        {"case_id": "wrong"},
        {"runtime_source": "/installed/old/failurelens/redaction.py"},
        {"mutation_applied": False},
        {"mutation_calls": 0},
        {"effect_calls": 0},
        {"phases": []},
        {"phases": [None, None, None]},
        {"exit_code": 2},
    ],
)
def test_infrastructure_identity_and_ineffective_mutations_are_errors(alteration):
    payload = receipt() | alteration
    assert assess(payload)[0] == "error"


@pytest.mark.parametrize("phase", [0, 2])
@pytest.mark.parametrize("outcome", ["failed", "skipped"])
def test_setup_teardown_and_skips_are_not_kills(phase, outcome):
    payload = receipt()
    payload["phases"][phase]["outcome"] = outcome
    assert assess(payload)[0] == "error"


@pytest.mark.parametrize(
    "exception", ["ModuleNotFoundError", "ImportError", "TypeError", "RuntimeError"]
)
def test_missing_dependencies_and_runtime_errors_are_not_kills(exception):
    payload = receipt()
    payload["phases"][1]["exception_type"] = exception
    assert assess(payload)[0] == "error"


def test_an_assertion_inside_runtime_code_is_not_a_test_body_kill():
    payload = receipt()
    payload["phases"][1].update(
        assertion_in_test=False, failure_source="backend/src/failurelens/redaction.py"
    )
    assert assess(payload)[0] == "error"


def test_source_drift_invalidates_even_an_otherwise_real_kill():
    assert assess(receipt(), provenance_ok=False) == (
        "error",
        "source_provenance_changed",
    )


def test_missing_child_receipt_is_an_error():
    assert (
        runner.assess_phase(
            None, case=CASE, mode="mutant", nonce="n", returncode=1, provenance_ok=True
        )[0]
        == "error"
    )


def test_runner_requires_explicit_opt_in_before_any_test(monkeypatch, tmp_path):
    monkeypatch.setattr(
        runner, "run_suite", lambda *a, **k: pytest.fail("must not execute")
    )
    with pytest.raises(SystemExit) as error:
        runner.main(["--output", str(tmp_path / "fresh.json")])
    assert error.value.code == 2
    assert not (tmp_path / "fresh.json").exists()


def test_runner_refuses_existing_or_in_checkout_reports(monkeypatch, tmp_path):
    existing = tmp_path / "existing.json"
    existing.write_text("preserve me")
    monkeypatch.setattr(
        runner, "run_suite", lambda *a, **k: pytest.fail("must not execute")
    )
    for destination in (
        existing,
        runner.ROOT / "evaluation/reports/new-mutations.json",
    ):
        with pytest.raises(SystemExit) as error:
            runner.main(["--confirm-synthetic-mutations", "--output", str(destination)])
        assert error.value.code == 2
    assert existing.read_text() == "preserve me"


def test_dirty_source_is_not_accepted_as_committed_evidence(monkeypatch):
    monkeypatch.setattr(runner, "source_snapshot", lambda *a: {"source_dirty": True})
    monkeypatch.setattr(
        runner, "run_phase", lambda *a, **k: pytest.fail("must not execute")
    )
    report = runner.run_suite()
    assert report["status"] == "error" and report["development_only"] is True
    assert report["results"] == []


def test_baseline_failure_prevents_its_mutant_execution(monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "source_snapshot", lambda *a: {"source_dirty": False})

    def phase(case, mode, *args, **kwargs):
        calls.append(mode)
        return {"status": "error", "reason": "dependency_unavailable"}

    monkeypatch.setattr(runner, "run_phase", phase)
    report = runner.run_suite((CASE,))
    assert calls == ["baseline"]
    assert report["summary"] == {
        "baseline_passed": 0,
        "killed": 0,
        "survived": 0,
        "error": 1,
    }


def test_all_baselines_precede_mutants_and_source_drift_revokes_kills(monkeypatch):
    snapshots = iter(
        [
            {"source_dirty": False, "source_sha": "first"},
            {"source_dirty": False, "source_sha": "changed"},
        ]
    )
    monkeypatch.setattr(runner, "source_snapshot", lambda *a: next(snapshots))
    calls = []

    def phase(case, mode, *args, **kwargs):
        calls.append(mode)
        return {"status": "passed" if mode == "baseline" else "killed"}

    monkeypatch.setattr(runner, "run_phase", phase)
    report = runner.run_suite(CASES[:2])
    assert calls == ["baseline", "baseline", "mutant", "mutant"]
    assert report["provenance_unchanged"] is False
    assert report["summary"]["killed"] == 0 and report["summary"]["error"] == 2
    assert all(
        entry["mutant"]["observed_status"] == "killed" for entry in report["results"]
    )


def test_environment_does_not_inherit_credentials_services_or_python_hooks(
    monkeypatch, tmp_path
):
    secrets = {
        "GITHUB_TOKEN": "synthetic-token",
        "OPENAI_API_KEY": "synthetic-key",
        "FAILURELENS_DATABASE_URL": "postgresql://remote",
        "PYTHONSTARTUP": "unsafe.py",
        "PYTEST_ADDOPTS": "--ignore=tests",
        "PYTEST_PLUGINS": "unsafe_plugin",
        "FAILURELENS_TELEMETRY_ENDPOINT": "https://collector.example.invalid",
    }
    for key, value in secrets.items():
        monkeypatch.setenv(key, value)
    env = runner.child_environment(runner.ROOT, tmp_path)
    assert not (set(secrets) - {"FAILURELENS_DATABASE_URL"}) & env.keys()
    assert env["FAILURELENS_DATABASE_URL"] == "sqlite+pysqlite:///:memory:"
    assert env["FAILURELENS_TELEMETRY_EXPORT_ENABLED"] == "false"
    assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"


def test_timeout_is_an_error_not_a_kill(monkeypatch):
    source = {"source_dirty": False}
    monkeypatch.setattr(runner, "source_snapshot", lambda *a: source)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("pytest", 0.1)

    monkeypatch.setattr(runner.subprocess, "run", timeout)
    result = runner.run_phase(CASE, "mutant", source)
    assert (result["status"], result["reason"]) == ("error", "subprocess_timeout")


def test_real_missing_test_collection_is_an_error():
    case = replace(
        CASE,
        test_id="backend/tests/test_redaction.py::test_does_not_exist_synthetic_probe",
    )
    result = runner.run_phase(case, "mutant", runner.source_snapshot())
    assert result["status"] == "error"
    assert result["reason"] in {
        "child_identity_collection_or_exit_mismatch",
        "missing_or_invalid_child_report",
    }


def test_real_seven_mutants_are_killed_without_changing_parent_or_source():
    from failurelens.auth import require_project_role
    from failurelens.redaction import redact_text

    original_role_check = require_project_role
    before = runner.source_snapshot()
    report = runner.run_suite(allow_dirty_source=True)
    assert report["summary"] == {
        "baseline_passed": 7,
        "killed": 7,
        "survived": 0,
        "error": 0,
    }, report
    assert report["provenance_unchanged"] is True
    assert runner.source_snapshot() == before
    from failurelens.auth import require_project_role as unchanged

    assert unchanged is original_role_check
    assert (
        "synthetic-bearer-canary"
        not in redact_text("Authorization: Bearer synthetic-bearer-canary").text
    )
    assert all(entry["mutant"]["effect_calls"] > 0 for entry in report["results"])
    assert all(len(entry["test_sha256"]) == 64 for entry in report["results"])


@pytest.mark.parametrize("change", ["modify", "stage", "delete", "untracked"])
def test_snapshot_records_actual_changed_source_bytes(tmp_path, change):
    # A minimal Git fixture, not another application checkout/worktree.
    root = tmp_path / "source"
    source = root / "backend/src/probe.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n")

    def git(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.name", "Synthetic provenance regression")
    git("config", "user.email", "provenance@example.invalid")
    git("add", "backend")
    git("commit", "-m", "Synthetic source")
    before = runner.source_snapshot(root)
    assert before["source_dirty"] is False
    if change == "delete":
        source.unlink()
    elif change == "untracked":
        source.with_name("extra.py").write_text("VALUE = 2\n")
    else:
        source.write_text("VALUE = 2\n")
        if change == "stage":
            git("add", "backend")
    after = runner.source_snapshot(root)
    assert after["source_sha"] == before["source_sha"]
    assert after["source_dirty"] is True
    assert after["code_and_tests_sha256"] != before["code_and_tests_sha256"]


def test_empty_mutation_selection_cannot_vacuously_pass():
    with pytest.raises(ValueError, match="at least one"):
        runner.run_suite(())
