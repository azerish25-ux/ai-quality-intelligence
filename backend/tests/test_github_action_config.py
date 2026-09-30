from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_github_action import ACTION, _env, _outputs, bundle, runner


def _config(tmp_path, document):
    env = _env(tmp_path)
    path = tmp_path / "operator-config.json"
    data = document if isinstance(document, bytes) else json.dumps(document).encode()
    path.write_bytes(data)
    env["FAILURELENS_CONFIG_PATH"] = str(path)
    env["FAILURELENS_CONFIG_SHA256"] = hashlib.sha256(data).hexdigest()
    return env


def test_action_config_defaults_preserve_deterministic_summary_without_discovery(
    tmp_path,
):
    (tmp_path / ".failurelens.json").write_text('{"analysis_mode":"paid-provider"}')
    config = runner.configuration(_env(tmp_path))
    assert config == {
        "analysis_mode": "deterministic",
        "publication_mode": "summary",
        "limits": {
            "report_bytes": 100_000,
            "markdown_bytes": 50_000,
            "evidence_bytes": 500_000,
        },
    }


def test_action_config_accepts_exact_operator_selected_bytes_and_lower_bounds(tmp_path):
    env = _config(
        tmp_path,
        {
            "schema_version": "github-action-config-v1",
            "analysis_mode": "deterministic",
            "publication_mode": "artifact-only",
            "limits": {
                "report_bytes": 4096,
                "markdown_bytes": 1024,
                "evidence_bytes": 4096,
            },
        },
    )
    result = runner.configuration(env)
    assert result["publication_mode"] == "artifact-only"
    assert result["limits"]["evidence_bytes"] == 4096


@pytest.mark.parametrize(
    "document",
    [
        {"schema_version": "github-action-config-v1", "command": "touch /tmp/canary"},
        {"schema_version": "github-action-config-v1", "token": "secret-canary"},
        {
            "schema_version": "github-action-config-v1",
            "endpoint": "https://attacker.invalid",
        },
        {"schema_version": "github-action-config-v1", "required_inputs": 0},
        {"schema_version": "github-action-config-v1", "analysis_mode": "provider"},
        {
            "schema_version": "github-action-config-v1",
            "analysis_mode": ["deterministic"],
        },
        {"schema_version": "github-action-config-v1", "publication_mode": "comment"},
        {
            "schema_version": "github-action-config-v1",
            "publication_mode": {"summary": True},
        },
        {
            "schema_version": "github-action-config-v1",
            "limits": {"evidence_bytes": 500_001},
        },
        {"schema_version": "github-action-config-v1", "limits": {"report_bytes": True}},
        {
            "schema_version": "github-action-config-v1",
            "limits": {"markdown_bytes": 1023},
        },
        {"schema_version": "github-action-config-v1", "limits": {"unlimited": True}},
        {"schema_version": "github-action-config-v1", "limits": []},
        {"schema_version": "unexpected"},
        b'{"schema_version":"github-action-config-v1","analysis_mode":"deterministic","analysis_mode":"provider"}',
        b'{"schema_version":"github-action-config-v1","limits":{"report_bytes":NaN}}',
        b"[]",
        '{"schema_version":"github-action-config-v1"}'.encode("utf-16"),
        b"---\ncommands: [touch /tmp/canary]",
        b'{"schema_version":"github-action-config-v1",',
        b'{"schema_version":"github-action-config-v1"}' + b" " * 16_384,
    ],
)
def test_hash_does_not_authorize_unsafe_configuration(tmp_path, document, monkeypatch):
    env = _config(tmp_path, document)
    monkeypatch.setattr(
        runner, "_cli", lambda args: pytest.fail("configuration reached CLI")
    )
    assert runner.run(env) == 2
    outputs = _outputs(env)
    assert outputs["status"] == "failed"
    assert outputs["evidence-path"] == outputs["report-path"] == ""
    status = Path(outputs["status-path"]).read_text()
    summary = Path(env["GITHUB_STEP_SUMMARY"]).read_text()
    assert "secret-canary" not in status + summary
    assert "attacker.invalid" not in status + summary


@pytest.mark.parametrize(
    "kind",
    [
        "missing-digest",
        "missing-path",
        "wrong-digest",
        "executable",
        "symlink",
        "parent-symlink",
        "directory",
        "fifo",
        "traversal",
    ],
)
def test_action_config_rejects_unsafe_file_selection(tmp_path, kind):
    env = _config(tmp_path, {"schema_version": "github-action-config-v1"})
    path = Path(env["FAILURELENS_CONFIG_PATH"])
    if kind == "missing-digest":
        env["FAILURELENS_CONFIG_SHA256"] = ""
    elif kind == "missing-path":
        env["FAILURELENS_CONFIG_PATH"] = ""
    elif kind == "wrong-digest":
        env["FAILURELENS_CONFIG_SHA256"] = "0" * 64
    elif kind == "executable":
        path.chmod(0o700)
    elif kind == "symlink":
        link = tmp_path / "link.json"
        link.symlink_to(path)
        env["FAILURELENS_CONFIG_PATH"] = str(link)
    elif kind == "parent-symlink":
        link = tmp_path / "linked-directory"
        link.symlink_to(tmp_path, target_is_directory=True)
        env["FAILURELENS_CONFIG_PATH"] = str(link / path.name)
    elif kind == "directory":
        env["FAILURELENS_CONFIG_PATH"] = str(tmp_path)
    elif kind == "fifo":
        path.unlink()
        os.mkfifo(path)
    elif kind == "traversal":
        env["FAILURELENS_CONFIG_PATH"] = str(
            tmp_path / ".." / tmp_path.name / path.name
        )
    with pytest.raises(runner.ActionError):
        runner.configuration(env)


@pytest.mark.parametrize(
    "key,value",
    [
        ("FAILURELENS_ANALYSIS_MODE", "paid"),
        ("FAILURELENS_ANALYSIS_MODE", "deterministic\ncommand=echo"),
        ("FAILURELENS_PUBLICATION_MODE", "comments"),
        ("FAILURELENS_PUBLICATION_MODE", "summary\noutput=forged"),
    ],
)
def test_unsupported_explicit_modes_fail_closed(tmp_path, key, value, monkeypatch):
    env = _env(tmp_path)
    env[key] = value
    monkeypatch.setattr(
        runner, "_cli", lambda args: pytest.fail("unsupported mode reached CLI")
    )
    assert runner.run(env) == 2


def test_conflicting_mode_input_does_not_silently_replace_config(tmp_path):
    env = _config(
        tmp_path,
        {
            "schema_version": "github-action-config-v1",
            "publication_mode": "artifact-only",
        },
    )
    env["FAILURELENS_PUBLICATION_MODE"] = "summary"
    with pytest.raises(runner.ActionError, match="conflicting_mode_input"):
        runner.configuration(env)


@pytest.fixture(scope="module")
def exported_report(tmp_path_factory):
    root = tmp_path_factory.mktemp("actual-action-export")
    env = _config(
        root,
        {
            "schema_version": "github-action-config-v1",
            "publication_mode": "artifact-only",
        },
    )
    env["GITHUB_EVENT_NAME"] = "pull_request"
    env["FAILURELENS_PROVIDER_ENABLED"] = "true"
    env["FAILURELENS_PROVIDER_ENDPOINT"] = "https://must-not-contact.invalid"
    env["FAILURELENS_PROVIDER_TOKEN"] = "provider-canary"
    for index in range(2):
        (root / f"{index}.xml").write_text(
            '<testsuite><testcase name="failed"><failure message="TimeoutError token=export-canary">'
            "TimeoutError</failure></testcase></testsuite>"
        )
    bundle.build_bundle(root, root / "bundle.zip", ["one=0.xml", "two=1.xml"])
    result = subprocess.run(
        [sys.executable, str(ACTION / "run.py")],
        env=env,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
    outputs = _outputs(env)
    assert not Path(env["GITHUB_STEP_SUMMARY"]).exists()
    snapshot = json.loads(Path(outputs["report-json-path"]).read_bytes())
    evidence = json.loads(Path(outputs["evidence-path"]).read_bytes())
    assert "export-canary" not in json.dumps(evidence)
    assert "provider-canary" not in result.stdout.decode() + result.stderr.decode()
    assert evidence["items"]
    assert Path(outputs["evidence-path"]).stat().st_mode & 0o777 == 0o600
    assert Path(outputs["evidence-path"]).parent.stat().st_mode & 0o777 == 0o700
    return snapshot, evidence, outputs


def _rebind(snapshot, evidence):
    evidence["evidence_digest"] = hashlib.sha256(
        runner._canonical(
            {key: value for key, value in evidence.items() if key != "evidence_digest"}
        )
    ).hexdigest()
    snapshot["evidence_export"]["digest"] = evidence["evidence_digest"]
    snapshot["evidence_export"]["counts"] = copy.deepcopy(evidence["counts"])
    snapshot["report_digest"] = hashlib.sha256(
        runner._canonical(
            {key: value for key, value in snapshot.items() if key != "report_digest"}
        )
    ).hexdigest()


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "malformed",
        "oversized",
        "symlink",
        "directory",
        "noncanonical",
        "duplicate-key",
        "tampered",
        "wrong-run",
        "wrong-project",
        "item-project",
        "item-run",
        "counts",
        "descriptor",
        "receipt",
    ],
)
def test_action_fails_closed_on_damaged_actual_export(
    tmp_path, monkeypatch, exported_report, fault
):
    snapshot, evidence, original_outputs = copy.deepcopy(exported_report)
    env = _env(tmp_path)
    if fault == "wrong-run":
        evidence["run_id"] = "11111111-1111-1111-1111-111111111111"
    elif fault == "wrong-project":
        evidence["project_id"] = "11111111-1111-1111-1111-111111111111"
    elif fault == "item-project":
        evidence["items"][0]["project_id"] = "11111111-1111-1111-1111-111111111111"
    elif fault == "item-run":
        evidence["items"][0]["run_id"] = "11111111-1111-1111-1111-111111111111"
    elif fault == "counts":
        evidence["counts"]["exported"] = True
    _rebind(snapshot, evidence)
    if fault == "descriptor":
        snapshot["evidence_export"]["filename"] = "../private.json"
        snapshot["report_digest"] = hashlib.sha256(
            runner._canonical(
                {
                    key: value
                    for key, value in snapshot.items()
                    if key != "report_digest"
                }
            )
        ).hexdigest()
    data = runner._canonical(evidence)

    def cli(args):
        if args[0] == "ingest":
            return {
                "run_id": original_outputs["run-id"],
                "ingestion_id": original_outputs["ingestion-id"],
                "state": "succeeded",
            }
        if args[0] == "report":
            return snapshot
        assert args[:5] == [
            "export-evidence",
            "--run",
            snapshot["run_id"],
            "--report-digest",
            snapshot["report_digest"],
        ]
        assert args[5] == "--output"
        path = Path(args[6])
        if fault == "symlink":
            outside = tmp_path / "outside.json"
            outside.write_bytes(data)
            path.symlink_to(outside)
        elif fault == "directory":
            path.mkdir()
        elif fault != "missing":
            payload = data
            if fault == "malformed":
                payload = b'{"secret": "malformed-canary"'
            elif fault == "oversized":
                payload = b" " * 500_001
            elif fault == "noncanonical":
                payload = json.dumps(evidence, indent=2).encode()
            elif fault == "duplicate-key":
                payload = data[:-1] + b',"run_id":"duplicate"}'
            elif fault == "tampered":
                payload = data.replace(b'"notice":', b'"unexpected":')
            path.write_bytes(payload)
        return {
            "schema_version": "github-evidence-export-receipt-v1",
            "run_id": snapshot["run_id"],
            "report_digest": "0" * 64
            if fault == "receipt"
            else snapshot["report_digest"],
            "evidence_digest": evidence["evidence_digest"],
            "bytes": len(data),
        }

    monkeypatch.setattr(runner, "_cli", cli)
    assert runner.run(env) == 2
    outputs = _outputs(env)
    assert outputs["status"] == "failed"
    assert (
        outputs["evidence-path"]
        == outputs["report-path"]
        == outputs["report-json-path"]
        == ""
    )
    assert "malformed-canary" not in Path(outputs["status-path"]).read_text()
    assert "malformed-canary" not in Path(env["GITHUB_STEP_SUMMARY"]).read_text()


def test_cli_never_forwards_publishing_or_provider_credentials(monkeypatch):
    monkeypatch.setenv("FAILURELENS_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("FAILURELENS_PROVIDER_TOKEN", "provider-canary")
    monkeypatch.setenv("FAILURELENS_GITHUB_TOKEN", "github-canary")
    monkeypatch.setenv("GITHUB_TOKEN", "github-canary")
    monkeypatch.setenv("GH_TOKEN", "github-canary")
    monkeypatch.setenv("FAILURELENS_TELEMETRY_EXPORT_ENABLED", "true")

    def subprocess_run(args, **kwargs):
        child_env = kwargs["env"]
        assert child_env["FAILURELENS_PROVIDER_ENABLED"] == "false"
        assert child_env["FAILURELENS_TELEMETRY_EXPORT_ENABLED"] == "false"
        assert not any(
            key in child_env
            for key in (
                "FAILURELENS_PROVIDER_TOKEN",
                "FAILURELENS_GITHUB_TOKEN",
                "GITHUB_TOKEN",
                "GH_TOKEN",
            )
        )
        assert kwargs.get("shell", False) is False
        return subprocess.CompletedProcess(args, 0, b"{}", b"")

    monkeypatch.setattr(subprocess, "run", subprocess_run)
    assert runner._cli(["report", "--run", "inert; command"]) == {}


@pytest.mark.parametrize(
    "limit_name", ["report_bytes", "markdown_bytes", "evidence_bytes"]
)
def test_reduced_config_limits_are_enforced_on_valid_actual_outputs(
    tmp_path, monkeypatch, exported_report, limit_name
):
    snapshot, evidence, original_outputs = copy.deepcopy(exported_report)
    lower_limit = 1024 if limit_name == "markdown_bytes" else 4096
    env = _config(
        tmp_path,
        {
            "schema_version": "github-action-config-v1",
            "limits": {limit_name: lower_limit},
        },
    )
    if limit_name == "evidence_bytes":
        evidence["notice"] += "x" * 5000
    else:
        snapshot["markdown"] = "x" * 6000
    _rebind(snapshot, evidence)

    def cli(args):
        if args[0] == "ingest":
            return {
                "run_id": original_outputs["run-id"],
                "ingestion_id": original_outputs["ingestion-id"],
                "state": "succeeded",
            }
        if args[0] == "report":
            return snapshot
        assert limit_name == "evidence_bytes"
        data = runner._canonical(evidence)
        Path(args[6]).write_bytes(data)
        return {
            "schema_version": "github-evidence-export-receipt-v1",
            "run_id": snapshot["run_id"],
            "report_digest": snapshot["report_digest"],
            "evidence_digest": evidence["evidence_digest"],
            "bytes": len(data),
        }

    monkeypatch.setattr(runner, "_cli", cli)
    assert runner.run(env) == 2
    outputs = _outputs(env)
    assert outputs["report-json-path"] == outputs["evidence-path"] == ""


def test_invalid_cli_json_is_always_a_fixed_safe_error(monkeypatch):
    for payload in (
        b'{"run_id":"a","run_id":"secret-canary"}',
        b"[]",
        b'{"run_id":NaN}',
    ):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *args, payload=payload, **kwargs: subprocess.CompletedProcess(
                args, 0, payload, b""
            ),
        )
        with pytest.raises(runner.ActionError, match="^invalid_cli_output$"):
            runner._cli(["ingest", "inert.xml"])
