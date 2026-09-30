"""Read-only Action entry point; CLI output and report text are data, never commands."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import UUID


class ActionError(Exception):
    """A fixed safe code which may be exposed in workflow logs."""


LIMITS = {
    "report_bytes": (4096, 100_000),
    "markdown_bytes": (1024, 50_000),
    "evidence_bytes": (4096, 500_000),
}
CONFIG_BYTES = 16_384


def _json_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _json_load(data: bytes) -> dict:
    def invalid_constant(value: str) -> None:
        raise ValueError("invalid constant")

    value = json.loads(
        data.decode("utf-8"),
        object_pairs_hook=_json_object,
        parse_constant=invalid_constant,
    )
    if not isinstance(value, dict):
        raise TypeError("expected object")
    return value


def _canonical(value: dict) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _read_regular(path: Path, limit: int, *, nonexecutable: bool = False) -> bytes:
    """Read a bounded regular file without following any symlink component."""
    directory = None
    try:
        if any(part == ".." for part in path.parts):
            raise ValueError
        parts = path.parts[1:] if path.is_absolute() else path.parts
        if not parts:
            raise ValueError
        directory = os.open(
            "/" if path.is_absolute() else ".", os.O_RDONLY | os.O_DIRECTORY
        )
        for part in parts[:-1]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            os.close(directory)
            directory = child
        descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or not 0 < info.st_size <= limit
                or (nonexecutable and info.st_mode & 0o111)
            ):
                raise ValueError
            data = handle.read(limit + 1)
            if not 0 < len(data) <= limit:
                raise ValueError
            return data
    except (OSError, ValueError):
        raise ActionError("invalid_bounded_regular_file") from None
    finally:
        if directory is not None:
            os.close(directory)


def configuration(env: dict[str, str]) -> dict:
    """Only operator-selected inert JSON; a matching hash proves no provenance."""
    result: dict = {
        "analysis_mode": "deterministic",
        "publication_mode": "summary",
        "limits": {name: upper for name, (_, upper) in LIMITS.items()},
    }
    path = env.get("FAILURELENS_CONFIG_PATH", "")
    expected = env.get("FAILURELENS_CONFIG_SHA256", "")
    if bool(path) != bool(expected):
        raise ActionError("config_path_and_digest_required")
    if path:
        if (
            len(path) > 4096
            or any(ord(character) < 32 for character in path)
            or not re.fullmatch(r"[0-9a-f]{64}", expected)
        ):
            raise ActionError("invalid_config_input")
        try:
            data = _read_regular(Path(path), CONFIG_BYTES, nonexecutable=True)
        except ActionError:
            raise ActionError("invalid_config_file") from None
        if hashlib.sha256(data).hexdigest() != expected:
            raise ActionError("config_digest_mismatch")
        try:
            document = _json_load(data)
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise ActionError("invalid_config_json") from None
        if document.get("schema_version") != "github-action-config-v1" or set(
            document
        ) - {"schema_version", "analysis_mode", "publication_mode", "limits"}:
            raise ActionError("unsupported_config_fields")
        for name in ("analysis_mode", "publication_mode"):
            if name in document:
                result[name] = document[name]
        limits = document.get("limits", {})
        if not isinstance(limits, dict) or set(limits) - set(LIMITS):
            raise ActionError("unsupported_config_limits")
        for name, value in limits.items():
            lower, upper = LIMITS[name]
            if type(value) is not int or not lower <= value <= upper:
                raise ActionError("invalid_config_limit")
            result["limits"][name] = value
    # Explicit workflow mode inputs may narrow behavior, never grant capabilities.
    for name in ("analysis_mode", "publication_mode"):
        value = env.get("FAILURELENS_" + name.upper(), "")
        if value:
            if path and name in document and value != document[name]:
                raise ActionError("conflicting_mode_input")
            result[name] = value
    if result["analysis_mode"] != "deterministic":
        raise ActionError("unsupported_analysis_mode")
    if not isinstance(result["publication_mode"], str) or result[
        "publication_mode"
    ] not in {"summary", "artifact-only"}:
        raise ActionError("unsupported_publication_mode")
    return result


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
        child_env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("FAILURELENS_PROVIDER_")
            and key not in {"FAILURELENS_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"}
        }
        child_env["FAILURELENS_PROVIDER_ENABLED"] = "false"
        child_env["FAILURELENS_TELEMETRY_EXPORT_ENABLED"] = "false"
        completed = subprocess.run(
            [sys.executable, "-m", "failurelens.cli", *args],
            env=child_env,
            capture_output=True,
            timeout=600,
            check=False,
        )
        if completed.returncode:
            raise ActionError("cli_processing_failed")
        if len(completed.stdout) > 250_000:
            raise ActionError("cli_output_limit")
        return _json_load(completed.stdout)
    except (OSError, subprocess.TimeoutExpired):
        raise ActionError("cli_unavailable_or_timed_out") from None
    except (TypeError, ValueError, UnicodeError, RecursionError):
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
    try:
        actual = hashlib.sha256(_canonical(unsigned)).hexdigest()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ActionError("invalid_report_json") from None
    if digest != actual:
        raise ActionError("report_digest_mismatch")
    _uuid(value.get("project_id"))


def validate_evidence(path: Path, receipt: dict, snapshot: dict, limit: int) -> dict:
    """Corruption/scope checks complement the CLI's fresh DB validation."""
    try:
        data = _read_regular(path, limit)
        evidence = _json_load(data)
        if _canonical(evidence) != data:
            raise ActionError("noncanonical_evidence_export")
        digest = hashlib.sha256(
            _canonical(
                {
                    key: value
                    for key, value in evidence.items()
                    if key != "evidence_digest"
                }
            )
        ).hexdigest()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ActionError("invalid_evidence_json") from None
    if evidence.get("evidence_digest") != digest:
        raise ActionError("evidence_digest_mismatch")
    if set(evidence) != {
        "schema_version",
        "project_id",
        "run_id",
        "analysis_ids",
        "scope",
        "distribution_status",
        "notice",
        "counts",
        "items",
        "evidence_digest",
    }:
        raise ActionError("invalid_evidence_schema")
    if (
        evidence.get("schema_version") != "github-evidence-v1"
        or evidence.get("project_id") != snapshot["project_id"]
        or evidence.get("run_id") != snapshot["run_id"]
        or evidence.get("scope") != "reported_reference_subset"
        or evidence.get("distribution_status") != "not_published"
    ):
        raise ActionError("evidence_scope_mismatch")
    counts = evidence.get("counts")
    if (
        not isinstance(counts, dict)
        or set(counts)
        != {
            "requested",
            "exported",
            "rejected",
            "unavailable",
            "omitted",
            "unavailable_analyses",
            "invalid_reference_entries",
            "omitted_reference_entries",
            "omitted_section_reference_hints",
            "omitted_related_run_hints",
        }
        or any(
            type(value) is not int or not 0 <= value <= 100_000
            for value in counts.values()
        )
        or counts["requested"]
        != sum(
            counts[name] for name in ("exported", "rejected", "unavailable", "omitted")
        )
        or counts["requested"] > 500
    ):
        raise ActionError("invalid_evidence_counts")
    descriptor = {
        "schema_version": "github-evidence-v1",
        "digest": digest,
        "filename": "evidence.json",
        "scope": "reported_reference_subset",
        "distribution_status": "not_published",
        "counts": counts,
    }
    if snapshot.get("evidence_export") != descriptor:
        raise ActionError("evidence_descriptor_mismatch")
    expected_receipt = {
        "schema_version": "github-evidence-export-receipt-v1",
        "run_id": snapshot["run_id"],
        "report_digest": snapshot["report_digest"],
        "evidence_digest": digest,
        "bytes": len(data),
    }
    if receipt != expected_receipt or type(receipt.get("bytes")) is not int:
        raise ActionError("evidence_receipt_mismatch")
    # Reuse the pinned report's explicit bounded reference selection, never scan
    # arbitrary fields for run IDs or infer scope from an evidence item's claim.
    from failurelens.github_report_sections import retained_evidence_references

    try:
        references = retained_evidence_references(snapshot["run_id"], snapshot)
        allowed_runs = {snapshot["run_id"], *references["allowed_related_run_ids"]}
        analysis_ids = evidence["analysis_ids"]
        items = evidence["items"]
        if (
            not isinstance(analysis_ids, list)
            or len(analysis_ids) > 50
            or len(set(analysis_ids)) != len(analysis_ids)
            or any(_uuid(value) != value for value in analysis_ids)
            or not set(analysis_ids)
            <= {item["analysis_id"] for item in snapshot["analyses"]}
            or not isinstance(items, list)
            or len(items) != counts["exported"]
            or len(items) > 100
        ):
            raise ActionError("invalid_evidence_items")
        seen: set[str] = set()
        for item in items:
            if (
                not isinstance(item, dict)
                or item.get("project_id") != snapshot["project_id"]
                or item.get("run_id") not in allowed_runs
                or _uuid(item.get("evidence_id")) in seen
            ):
                raise ActionError("evidence_item_scope_mismatch")
            seen.add(item["evidence_id"])
    except (KeyError, TypeError, ValueError):
        raise ActionError("invalid_evidence_items") from None
    return evidence


def run(env: dict[str, str]) -> int:
    output_dir = Path(
        tempfile.mkdtemp(prefix="failurelens-report-", dir=env.get("RUNNER_TEMP"))
    )
    status_path = output_dir / "status.json"
    outputs = {
        "status-path": str(status_path),
        "report-path": "",
        "report-json-path": "",
        "evidence-path": "",
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
    publication_mode = env.get("FAILURELENS_PUBLICATION_MODE", "summary")
    try:
        config = configuration(env)
        publication_mode = config["publication_mode"]
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
        if (
            len(_canonical(snapshot)) > config["limits"]["report_bytes"]
            or len(snapshot["markdown"].encode()) > config["limits"]["markdown_bytes"]
        ):
            raise ActionError("report_output_limit")
        evidence_path = output_dir / "evidence.json"
        receipt = _cli(
            [
                "export-evidence",
                "--run",
                run_id,
                "--report-digest",
                snapshot["report_digest"],
                "--output",
                str(evidence_path),
            ]
        )
        evidence = validate_evidence(
            evidence_path, receipt, snapshot, config["limits"]["evidence_bytes"]
        )
        report_path = output_dir / "report.md"
        json_path = output_dir / "report.json"
        report_path.write_text(snapshot["markdown"], encoding="utf-8")
        json_path.write_bytes(_canonical(snapshot))
        outputs.update(
            {
                "report-path": str(report_path),
                "report-json-path": str(json_path),
                "evidence-path": str(evidence_path),
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
                "evidence_digest": evidence["evidence_digest"],
                "analysis_mode": config["analysis_mode"],
                "publication_mode": publication_mode,
            }
        )
        summary = snapshot["markdown"]
        code = 0
    except ActionError as exc:
        status["error_code"] = str(exc)
        print(f"Loose Thread Action failed: {exc}", file=sys.stderr)
    except (OSError, ValueError, TypeError, RecursionError):
        status["error_code"] = "invalid_action_data"
        print("Loose Thread Action failed: invalid_action_data", file=sys.stderr)
    status_path.write_text(json.dumps(status, sort_keys=True) + "\n", encoding="utf-8")
    with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
        for key, value in outputs.items():
            if "\n" in value or "\r" in value:
                raise ActionError("unsafe_output_value")
            handle.write(f"{key}={value}\n")
    if publication_mode != "artifact-only":
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(summary)
    return code


if __name__ == "__main__":
    raise SystemExit(run(dict(os.environ)))
