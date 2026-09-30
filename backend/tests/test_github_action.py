from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from failurelens.config import get_settings
from failurelens.ingestion import parse_artifact

ROOT = Path(__file__).resolve().parents[2]
ACTION = ROOT / "integrations" / "github-action"


def _module(name):
    spec = importlib.util.spec_from_file_location(
        "github_action_" + name, ACTION / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bundle = _module("bundle")
runner = _module("run")


def _env(tmp_path):
    return {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend" / "src"),
        "FAILURELENS_DATABASE_URL": f"sqlite+pysqlite:///{tmp_path / 'action.db'}",
        "FAILURELENS_ARTIFACT_ROOT": str(tmp_path / "private"),
        "FAILURELENS_DEMO_MODE": "true",
        "FAILURELENS_REPORT": str(tmp_path / "bundle.zip"),
        "FAILURELENS_PROJECT": "action-contract",
        "FAILURELENS_EXTERNAL_ID": "gha-contract",
        "FAILURELENS_REPOSITORY": "owner/repo",
        "FAILURELENS_HEAD_SHA": "a" * 40,
        "FAILURELENS_BASE_SHA": "b" * 40,
        "FAILURELENS_RUN_SCOPE": "unknown",
        "FAILURELENS_EXPECTED_INPUTS": "2",
        "FAILURELENS_SHARD_COUNT": "2",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(tmp_path / "outputs"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
    }


def _outputs(env):
    return dict(
        line.split("=", 1)
        for line in Path(env["GITHUB_OUTPUT"]).read_text().splitlines()
    )


def test_bundle_preserves_declared_missing_shard_and_ignores_unlisted_data(tmp_path):
    (tmp_path / "one.xml").write_text(
        '<testsuite><testcase name="passed"/></testsuite>'
    )
    (tmp_path / "labels.json").write_text('{"do_not_read": "evaluation labels"}')
    (tmp_path / "commands.sh").write_text("exit 1")
    result = bundle.build_bundle(
        tmp_path, tmp_path / "bundle.zip", ["one=one.xml", "two=two.xml"]
    )
    assert result == {"expected_shards": 2, "present_shards": 1}
    with zipfile.ZipFile(tmp_path / "bundle.zip") as archive:
        assert archive.namelist() == ["manifest.json", "shards/one.xml"]
    parsed = parse_artifact(
        (tmp_path / "bundle.zip").read_bytes(), "bundle.zip", get_settings()
    )
    assert parsed.expected_inputs == 2
    assert parsed.received_inputs == 1
    assert parsed.completeness == "partial"
    assert [(item.input_id, item.status) for item in parsed.inputs] == [
        ("one", "accepted"),
        ("two", "missing"),
    ]


def test_bundle_bytes_are_reproducible_and_refuse_overwrite(tmp_path):
    (tmp_path / "one.xml").write_text(
        '<testsuite><testcase name="passed"/></testsuite>'
    )
    for filename in ("first.zip", "second.zip"):
        bundle.build_bundle(tmp_path, tmp_path / filename, ["one=one.xml"])
    assert (tmp_path / "first.zip").read_bytes() == (
        tmp_path / "second.zip"
    ).read_bytes()
    with pytest.raises(ValueError, match="must not exist"):
        bundle.build_bundle(tmp_path, tmp_path / "first.zip", ["one=one.xml"])


@pytest.mark.parametrize(
    "declarations",
    [
        [],
        ["one=../private.xml"],
        ["one=/tmp/private.xml"],
        ["one=one.xml", "ONE=two.xml"],
        ["bad name=one.xml"],
        ["one=labels.json"],
        ["one=./one.xml"],
    ],
)
def test_bundle_rejects_unsafe_declarations(tmp_path, declarations):
    with pytest.raises(ValueError):
        bundle.build_bundle(tmp_path, tmp_path / "bundle.zip", declarations)


def test_bundle_rejects_symlink_and_size_limit(tmp_path, monkeypatch):
    (tmp_path / "one.xml").write_text("oversized")
    (tmp_path / "link.xml").symlink_to(tmp_path / "one.xml")
    with pytest.raises(ValueError, match="symlink"):
        bundle.build_bundle(tmp_path, tmp_path / "bundle.zip", ["one=link.xml"])
    monkeypatch.setattr(bundle, "MAX_FILE_BYTES", 4)
    with pytest.raises(ValueError, match="bounded"):
        bundle.build_bundle(tmp_path, tmp_path / "bundle.zip", ["one=one.xml"])


@pytest.mark.parametrize("present", [0, 1, 2])
def test_real_action_cli_emits_safe_digest_bound_reports_and_missing_shards(
    tmp_path, present
):
    env = _env(tmp_path)
    env["FAILURELENS_EXTERNAL_ID"] = (
        "untrusted\noutput=forged @everyone token=action-canary-123456"
    )
    for index in range(present):
        (tmp_path / f"{index}.xml").write_text(
            '<testsuite><testcase name="passed"/>'
            '<testcase name="failed"><failure message="timeout token=action-canary-123456">'
            "TimeoutError</failure></testcase></testsuite>"
        )
    bundle.build_bundle(tmp_path, tmp_path / "bundle.zip", ["one=0.xml", "two=1.xml"])
    result = subprocess.run(
        [sys.executable, str(ACTION / "run.py")],
        env=env,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
    outputs = _outputs(env)
    assert outputs["status"] == "reported"
    assert "output" not in outputs
    assert outputs["completeness"] == ("complete" if present == 2 else "partial")
    assert outputs["advisory-status"] == "HOLD_FOR_REVIEW"
    snapshot = json.loads(Path(outputs["report-json-path"]).read_text())
    runner.validate_snapshot(snapshot, outputs["run-id"])
    assert snapshot["inputs"]["expected"] == 2
    assert snapshot["inputs"]["declared_shards"] == 2
    assert snapshot["inputs"]["states"]["missing"] == 2 - present
    assert snapshot["outcomes"]["attempts"] == present * 2
    assert snapshot["markdown"] == Path(outputs["report-path"]).read_text()
    assert snapshot["markdown"] == Path(env["GITHUB_STEP_SUMMARY"]).read_text()
    assert snapshot["report_digest"] == outputs["report-digest"]
    status = json.loads(Path(outputs["status-path"]).read_text())
    assert status["report_digest"] == outputs["report-digest"]
    assert status["ingestion_state"] == outputs["ingestion-state"]
    for content in [
        result.stdout.decode(),
        result.stderr.decode(),
        json.dumps(snapshot),
        json.dumps(status),
    ]:
        assert "action-canary-123456" not in content
        assert "@everyone" not in content
    assert set(Path(outputs["status-path"]).parent.iterdir()) == {
        Path(outputs["status-path"]),
        Path(outputs["report-path"]),
        Path(outputs["report-json-path"]),
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("FAILURELENS_EXPECTED_INPUTS", "-1"),
        ("FAILURELENS_SHARD_COUNT", "1\nx=y"),
        ("FAILURELENS_ATTEMPT", "0"),
        ("FAILURELENS_COMPARISON_TRUST", "artifact_says_trusted"),
        ("FAILURELENS_RUN_SCOPE", "all"),
        ("FAILURELENS_HEAD_SHA", "abcdef0"),
        ("FAILURELENS_REPOSITORY", "../private"),
        ("FAILURELENS_PROJECT", ""),
    ],
)
def test_action_validates_inputs_before_invoking_cli(tmp_path, key, value, monkeypatch):
    env = _env(tmp_path)
    env[key] = value
    monkeypatch.setattr(
        runner, "_cli", lambda args: pytest.fail("invalid input reached CLI")
    )
    assert runner.run(env) == 2
    outputs = _outputs(env)
    status = json.loads(Path(outputs["status-path"]).read_text())
    assert status["status"] == "failed"
    assert status["advisory_status"] == "HOLD_FOR_REVIEW"
    assert not outputs["report-path"]


def test_action_does_not_emit_injected_cli_identity(tmp_path, monkeypatch):
    env = _env(tmp_path)
    monkeypatch.setattr(
        runner,
        "_cli",
        lambda args: {"run_id": "bad\nreport-path=/private", "state": "succeeded"},
    )
    assert runner.run(env) == 2
    outputs = _outputs(env)
    assert not outputs["run-id"]
    assert not outputs["report-path"]
    assert "invalid_cli_identity" in Path(outputs["status-path"]).read_text()


def test_action_discards_untrusted_cli_error_text(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 2, b"token=private-canary", b"token=private-canary"
        ),
    )
    with pytest.raises(runner.ActionError, match="^cli_processing_failed$"):
        runner._cli(["ingest", "report.xml"])


def test_workflow_has_only_read_permissions_and_declares_both_missing_shards():
    # Dedicated workflow linter runs in quality CI; these are trust invariants.
    text = (ROOT / ".github/workflows/github-report.yml").read_text()
    assert "permissions:\n  contents: read\n" in text
    assert ": write" not in text
    assert "pull_request_target" not in text and "workflow_run:" not in text
    assert "secrets." not in text and "publish-github" not in text
    assert "persist-credentials: false" in text
    assert "image: postgres:17-alpine" in text
    assert "alembic upgrade head" in text
    assert "uses: $/integrations/github-action" in text
    assert (
        "--shard analysis=analysis/results.xml --shard ingestion=ingestion/results.xml"
        in text
    )
    assert 'expected-inputs: "2"' in text and 'shard-count: "2"' in text
    assert 'test "$COMPLETENESS" = complete' in text
    assert "run-scope: unknown" in text


def test_action_install_is_locked_and_does_not_modify_checkout():
    text = (ACTION / "action.yml").read_text()
    assert "--require-hashes" in text
    assert "--no-deps --no-build-isolation" in text
    assert 'cp -R "${GITHUB_ACTION_PATH}/../../backend" "$build_root/backend"' in text


@pytest.mark.parametrize("field", ["advisory_status", "completeness", "run_status"])
def test_invalid_snapshot_types_fail_closed(field):
    snapshot = {
        "schema_version": "github-report-v2",
        "run_id": "expected",
        "advisory_status": "HOLD_FOR_REVIEW",
        "completeness": "partial",
        "run_status": "partial",
    }
    snapshot[field] = []
    with pytest.raises(runner.ActionError):
        runner.validate_snapshot(snapshot, "expected")


def test_action_rejects_wrong_digest_before_retaining_report(tmp_path, monkeypatch):
    env = _env(tmp_path)
    identity = "01234567-89ab-cdef-0123-456789abcdef"
    responses = iter(
        [
            {"run_id": identity, "ingestion_id": identity, "state": "succeeded"},
            {
                "schema_version": "github-report-v2",
                "run_id": identity,
                "advisory_status": "HOLD_FOR_REVIEW",
                "completeness": "complete",
                "run_status": "complete",
                "markdown": "untrusted data",
                "report_digest": "f" * 64,
            },
        ]
    )
    monkeypatch.setattr(runner, "_cli", lambda args: next(responses))
    assert runner.run(env) == 2
    outputs = _outputs(env)
    assert outputs["report-path"] == ""
    assert outputs["report-json-path"] == ""
    assert "untrusted data" not in Path(env["GITHUB_STEP_SUMMARY"]).read_text()
    assert "report_digest_mismatch" in Path(outputs["status-path"]).read_text()
