"""Fail-closed reporting and scope regressions for the isolated quality runner."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "quality_checks", ROOT / "scripts/quality_checks.py"
)
assert SPEC is not None and SPEC.loader is not None
quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality)


def test_inventory_includes_tracked_ignored_and_new_nonignored_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = ["tracked.lock", "new.py"]
    for name in files:
        (tmp_path / name).write_text("source")
    calls = []

    def execute(command: list[str], **kwargs: Any) -> tuple[int, str]:
        calls.append(command)
        return 0, "\0".join(files) + "\0"

    monkeypatch.setattr(quality, "execute", execute)
    assert quality.files_in_scope(tmp_path) == sorted(files)
    assert calls == [
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    ]


@pytest.mark.parametrize("content", ["missing", "symlink"])
def test_invalid_inventory_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    if content == "symlink":
        (tmp_path / "entry").symlink_to(tmp_path / "outside")
    monkeypatch.setattr(quality, "execute", lambda *a, **k: (0, "entry\0"))
    with pytest.raises(quality.GateError, match="missing-or-nonregular"):
        quality.files_in_scope(tmp_path)


def test_source_digest_changes_on_name_or_bytes(tmp_path: Path) -> None:
    (tmp_path / "a").write_text("one")
    first = quality.source_digest(["a"], tmp_path)
    (tmp_path / "a").write_text("two")
    assert first != quality.source_digest(["a"], tmp_path)
    (tmp_path / "b").write_text("one")
    assert first != quality.source_digest(["b"], tmp_path)


def test_scanner_messages_and_secret_hashes_never_enter_reports(tmp_path: Path) -> None:
    sensitive = "synthetic-value-never-copy-into-a-report"
    raw = json.dumps(
        {
            "plugins_used": [{"name": "SecretKeywordDetector"}],
            "results": {
                "settings.py": [
                    {
                        "type": "Secret Keyword",
                        "line_number": 4,
                        "hashed_secret": sensitive,
                        "secret_value": sensitive,
                    }
                ]
            },
        }
    )
    findings = quality.secret_findings(raw)
    output = tmp_path / "report.json"
    quality.write_report({"status": "fail", "findings": findings}, output)
    assert sensitive not in output.read_text()
    assert json.loads(output.read_text())["findings"] == [
        {"code": "Secret Keyword", "file": "settings.py", "line": 4}
    ]


@pytest.mark.parametrize(
    "key", ["sig", "Signature", "X-Amz-Signature", "X-Goog-Signature"]
)
def test_signed_query_detection_keeps_only_location(tmp_path: Path, key: str) -> None:
    canary = "sensitive-synthetic-signature"
    (tmp_path / "workflow.yml").write_text(
        "source: " + "https://example.invalid/file?" + key + "=" + canary
    )
    findings = quality.signed_url_findings(["workflow.yml"], tmp_path)
    assert findings == [{"file": "workflow.yml", "line": 1, "code": "signed-url-query"}]
    assert canary not in json.dumps(findings)


def test_report_truncation_preserves_total_counts_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(quality, "MAX_FINDINGS", 2)
    report = {
        "status": "fail",
        "findings": [{"code": "finding", "line": i} for i in range(5)],
    }
    output = tmp_path / "report.json"
    quality.write_report(report, output)
    result = json.loads(output.read_text())
    assert result["status"] == "fail"
    assert result["finding_count"] == 5
    assert result["categories"] == {"finding": 5}
    assert result["omitted_finding_count"] == 3
    assert len(result["findings"]) == 2


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "[]",
        "{}",
        '{"dependencies":[]}',
        '{"dependencies":[{"skip_reason":"not available"}]}',
    ],
)
def test_incomplete_dependency_results_cannot_pass(raw: str) -> None:
    with pytest.raises((quality.GateError, KeyError)):
        quality.python_audit_findings(raw, "test.lock")


def test_npm_remote_errors_cannot_pass() -> None:
    with pytest.raises(quality.GateError, match="incomplete"):
        quality.npm_audit_findings('{"error":{"code":"registry unavailable"}}')


def test_secret_candidates_turn_scanner_zero_into_gate_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(quality, "checked_versions", dict)
    monkeypatch.setattr(quality, "files_in_scope", lambda: ["test.py"])
    monkeypatch.setattr(quality, "source_digest", lambda files: "source-digest")
    monkeypatch.setattr(quality, "execute", lambda *a, **k: (0, "revision"))
    monkeypatch.setattr(
        quality,
        "run_check",
        lambda *a: {"findings": [{"code": "candidate"}], "tool_exit_codes": [0]},
    )
    output = tmp_path / "result.json"
    assert quality.main(["secrets", "--output", str(output)]) == 1
    assert json.loads(output.read_text())["status"] == "fail"


def test_tool_error_never_becomes_clean_or_finding_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(quality, "execute", lambda *a, **k: (2, "[]"))
    with pytest.raises(quality.GateError, match="tool-execution-error"):
        quality.run_check("lint", ["test.py"], None)


def test_nonzero_without_findings_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quality, "execute", lambda *a, **k: (1, "[]"))
    with pytest.raises(quality.GateError, match="nonzero-without-findings"):
        quality.run_check("lint", ["test.py"], None)


def test_source_mutation_invalidates_measurement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(quality, "checked_versions", dict)
    monkeypatch.setattr(quality, "files_in_scope", lambda: ["test.py"])
    values = iter(["before", "after"])
    monkeypatch.setattr(quality, "source_digest", lambda files: next(values))
    monkeypatch.setattr(quality, "execute", lambda *a, **k: (0, "revision"))
    monkeypatch.setattr(
        quality, "run_check", lambda *a: {"findings": [], "tool_exit_codes": [0]}
    )
    output = tmp_path / "result.json"
    assert quality.main(["lint", "--output", str(output)]) == 2
    result = json.loads(output.read_text())
    assert (
        result["status"] == "error" and result["error"] == "source-changed-during-check"
    )


def test_secret_scan_is_offline_and_does_not_skip_lock_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(quality, "ROOT", tmp_path)
    (tmp_path / "requirements.lock").write_text("public-package==1.0")
    (tmp_path / "test.py").write_text("pass")
    calls = []

    def execute(command: list[str], **kwargs: Any) -> tuple[int, str]:
        calls.append(command)
        return 0, '{"plugins_used":[{"name":"test"}],"results":{}}'

    monkeypatch.setattr(quality, "execute", execute)
    monkeypatch.setattr(quality, "signed_url_findings", lambda files: [])
    assert (
        quality.run_check("secrets", ["requirements.lock", "test.py"], None)["findings"]
        == []
    )
    command = calls[0]
    assert "--no-verify" in command and "--baseline" not in command
    assert "detect_secrets.filters.heuristic.is_lock_file" in command
    assert command[-2:] == ["requirements.lock", "test.py"]


def test_execute_preserves_exit_code_without_printing_source(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = quality.execute(
        [
            sys.executable,
            "-c",
            "import sys; print('sensitive synthetic output'); sys.exit(1)",
        ]
    )
    assert result == (1, "sensitive synthetic output\n")
    assert capsys.readouterr().out == ""


def test_execute_timeout_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired("scanner", 600)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(quality.GateError, match="TimeoutExpired"):
        quality.execute(["scanner"])


def test_workflow_keeps_failure_and_uses_isolated_lock() -> None:
    source = (quality.ROOT / ".github/workflows/quality-security.yml").read_text()
    assert "continue-on-error" not in source and "|| true" not in source
    assert "fail-fast: false" in source and "if: always()" in source
    assert "--require-hashes -r tools/quality/requirements.lock" in source
    assert "persist-credentials: false" in source
    assert "--output" in source and '"$QUALITY_CHECK"' in source
    assert "--fix" not in source


def test_capture_limit_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quality, "MAX_CAPTURE_BYTES", 3)
    with pytest.raises(quality.GateError, match="tool-output-limit"):
        quality.execute([sys.executable, "-c", "print('four')"])


def test_missing_environment_is_a_reportable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(name: str) -> str:
        raise quality.PackageNotFoundError(name)

    monkeypatch.setattr(quality, "version", missing)
    with pytest.raises(quality.GateError, match="quality-environment-not-installed"):
        quality.checked_versions()


def test_reports_cannot_mutate_measured_source() -> None:
    with pytest.raises(SystemExit) as result:
        quality.main(["lint", "--output", str(quality.ROOT / "not-created.json")])
    assert result.value.code == 2
    assert not (quality.ROOT / "not-created.json").exists()


def test_unapproved_npm_gate_is_not_run_and_calls_no_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no tool may run without transmission approval")

    monkeypatch.setattr(quality, "execute", forbidden)
    monkeypatch.setattr(quality, "checked_versions", forbidden)
    output = tmp_path / "not-run.json"
    assert quality.main(["npm-audit", "--output", str(output)]) == 3
    assert json.loads(output.read_text())["status"] == "not_run"
    with pytest.raises(quality.GateError, match="npm-registry-approval-required"):
        quality.run_check("npm-audit", [], None)


def test_npm_workflow_is_manual_and_default_off() -> None:
    # BaseLoader retains GitHub's YAML-1.2 `on` key as a string.
    import yaml

    workflow = yaml.load(
        (quality.ROOT / ".github/workflows/quality-security.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert (
        workflow["on"]["workflow_dispatch"]["inputs"]["npm_audit"]["default"] == "false"
    )
    assert "npm-audit" not in workflow["jobs"]["checks"]["strategy"]["matrix"]["check"]
    assert (
        workflow["jobs"]["npm-audit"]["if"]
        == "github.event_name == 'workflow_dispatch' && inputs.npm_audit"
    )


def test_workflow_acceptance_rejects_skipped_audit(tmp_path):
    """A default-off transmission must not imply a passed security gate."""
    import itertools
    import subprocess
    import textwrap

    workflow = (quality.ROOT / ".github/workflows/quality-security.yml").read_text()
    acceptance = workflow.split("\n  acceptance:\n", 1)[1]
    assert "needs: [checks, npm-audit]" in acceptance
    assert "if: always()" in acceptance
    script = textwrap.dedent(acceptance.split("        run: |\n", 1)[1])
    for independent, audit in itertools.product(
        ("success", "failure", "skipped", "cancelled"), repeat=2
    ):
        result = subprocess.run(
            ["bash", "-c", script],
            env={
                "INDEPENDENT_CHECKS_RESULT": independent,
                "NPM_AUDIT_RESULT": audit,
                "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
            },
            capture_output=True,
            timeout=5,
            check=False,
        )
        assert (result.returncode == 0) is (independent == audit == "success")
