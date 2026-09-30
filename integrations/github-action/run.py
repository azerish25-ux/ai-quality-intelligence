"""Read-only Action entry point; CLI output and report text are data, never commands."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import UUID


class ActionError(Exception):
    """A fixed safe code which may be exposed in workflow logs."""


def _positive(env: dict[str, str], key: str, default: str = "") -> str:
    value = env.get(key, default)
    if value and (not re.fullmatch(r"[1-9][0-9]{0,5}", value) or int(value) > 100_000):
        raise ActionError("invalid_numeric_input")
    return value


def ingestion_args(env: dict[str, str]) -> list[str]:
    for key in ("FAILURELENS_REPORT", "FAILURELENS_PROJECT", "FAILURELENS_EXTERNAL_ID"):
        if not env.get(key):
            raise ActionError("missing_required_input")
    scope = env.get("FAILURELENS_RUN_SCOPE", "unknown")
    trust = env.get("FAILURELENS_COMPARISON_TRUST", "self_reported")
    if scope not in {"full_suite", "impact_selected", "unknown"}:
        raise ActionError("invalid_run_scope")
    if trust not in {"self_reported", "authenticated_lookup", "trusted_workflow"}:
        raise ActionError("invalid_comparison_trust")
    args = [
        "ingest",
        env["FAILURELENS_REPORT"],
        "--project",
        env["FAILURELENS_PROJECT"],
        "--external-id",
        env["FAILURELENS_EXTERNAL_ID"],
        "--run-scope",
        scope,
        "--comparison-trust",
        trust,
        "--process",
    ]
    for key, flag in (
        ("REPOSITORY", "--repository"),
        ("BASE_SHA", "--base-sha"),
        ("HEAD_SHA", "--commit-sha"),
        ("BRANCH", "--branch"),
    ):
        value = env.get("FAILURELENS_" + key)
        if value:
            if key in {"BASE_SHA", "HEAD_SHA"} and not re.fullmatch(
                r"[0-9a-f]{40}", value
            ):
                raise ActionError("invalid_exact_sha")
            if key == "REPOSITORY" and (
                not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value)
                or any(part in {".", ".."} for part in value.split("/"))
            ):
                raise ActionError("invalid_repository")
            args.extend([flag, value])
    for key, flag, default in (
        ("ATTEMPT", "--attempt", "1"),
        ("EXPECTED_INPUTS", "--expected-inputs", ""),
        ("SHARD_COUNT", "--shard-count", ""),
    ):
        value = _positive(env, "FAILURELENS_" + key, default)
        if value:
            args.extend([flag, value])
    return args


def _cli(args: list[str]) -> dict:
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "failurelens.cli", *args],
            capture_output=True,
            timeout=600,
            check=False,
        )
        if completed.returncode:
            raise ActionError("cli_processing_failed")
        if len(completed.stdout) > 250_000:
            raise ActionError("cli_output_limit")
        value = json.loads(completed.stdout)
        if not isinstance(value, dict):
            raise ActionError("invalid_cli_output")
        return value
    except (OSError, subprocess.TimeoutExpired):
        raise ActionError("cli_unavailable_or_timed_out") from None
    except (ValueError, UnicodeError):
        raise ActionError("invalid_cli_output") from None


def _uuid(value: object) -> str:
    if not isinstance(value, str):
        raise ActionError("invalid_cli_identity")
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except ValueError:
        raise ActionError("invalid_cli_identity") from None
    return value


def validate_snapshot(value: dict, run_id: str) -> None:
    if (
        value.get("schema_version") != "github-report-v2"
        or value.get("run_id") != run_id
    ):
        raise ActionError("report_scope_mismatch")
    if not isinstance(value.get("advisory_status"), str) or value[
        "advisory_status"
    ] not in {"HOLD_FOR_REVIEW", "NO_BLOCKER_IDENTIFIED_IN_OBSERVED_SCOPE"}:
        raise ActionError("invalid_report_status")
    if not isinstance(value.get("completeness"), str) or value["completeness"] not in {
        "complete",
        "partial",
        "unknown",
        "evidence_expired",
    }:
        raise ActionError("invalid_report_completeness")
    if not isinstance(value.get("run_status"), str) or value["run_status"] not in {
        "queued",
        "processing",
        "complete",
        "partial",
        "failed",
    }:
        raise ActionError("invalid_report_run_status")
    if (
        not isinstance(value.get("markdown"), str)
        or len(value["markdown"].encode()) > 50_000
    ):
        raise ActionError("invalid_report_markdown")
    digest = value.get("report_digest")
    unsigned = {key: item for key, item in value.items() if key != "report_digest"}
    actual = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if digest != actual:
        raise ActionError("report_digest_mismatch")


def run(env: dict[str, str]) -> int:
    output_dir = Path(
        tempfile.mkdtemp(prefix="failurelens-report-", dir=env.get("RUNNER_TEMP"))
    )
    status_path = output_dir / "status.json"
    outputs = {
        "status-path": str(status_path),
        "report-path": "",
        "report-json-path": "",
        "run-id": "",
        "ingestion-id": "",
        "report-digest": "",
        "status": "failed",
        "ingestion-state": "unknown",
        "run-status": "unknown",
        "completeness": "unknown",
        "advisory-status": "HOLD_FOR_REVIEW",
    }
    status = {
        "schema_version": "github-action-status-v1",
        "status": "failed",
        "error_code": None,
        "advisory_status": "HOLD_FOR_REVIEW",
    }
    summary = "## Loose Thread report unavailable\n\nHOLD_FOR_REVIEW\n\nProcessing did not produce a validated report.\n"
    code = 2
    try:
        ingestion = _cli(ingestion_args(env))
        run_id = _uuid(ingestion.get("run_id"))
        ingestion_id = _uuid(ingestion.get("ingestion_id"))
        if not isinstance(ingestion.get("state"), str) or ingestion["state"] not in {
            "succeeded",
            "partial",
        }:
            raise ActionError("ingestion_not_complete")
        snapshot = _cli(["report", "--run", run_id, "--format", "json"])
        validate_snapshot(snapshot, run_id)
        report_path = output_dir / "report.md"
        json_path = output_dir / "report.json"
        report_path.write_text(snapshot["markdown"], encoding="utf-8")
        json_path.write_text(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        outputs.update(
            {
                "report-path": str(report_path),
                "report-json-path": str(json_path),
                "run-id": run_id,
                "ingestion-id": ingestion_id,
                "status": "reported",
                "ingestion-state": ingestion["state"],
                "run-status": snapshot["run_status"],
                "completeness": snapshot["completeness"],
                "advisory-status": snapshot["advisory_status"],
                "report-digest": snapshot["report_digest"],
            }
        )
        status.update(
            {
                "status": "reported",
                "ingestion_id": ingestion_id,
                "run_id": run_id,
                "ingestion_state": ingestion["state"],
                "run_status": snapshot["run_status"],
                "completeness": snapshot["completeness"],
                "advisory_status": snapshot["advisory_status"],
                "report_digest": snapshot["report_digest"],
            }
        )
        summary = snapshot["markdown"]
        code = 0
    except ActionError as exc:
        status["error_code"] = str(exc)
        print(f"Loose Thread Action failed: {exc}", file=sys.stderr)
    status_path.write_text(json.dumps(status, sort_keys=True) + "\n", encoding="utf-8")
    with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
        for key, value in outputs.items():
            if "\n" in value or "\r" in value:
                raise ActionError("unsafe_output_value")
            handle.write(f"{key}={value}\n")
    with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
        handle.write(summary)
    return code


if __name__ == "__main__":
    raise SystemExit(run(dict(os.environ)))
