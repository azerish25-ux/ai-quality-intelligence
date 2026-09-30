"""Baseline-first, opt-in synthetic safeguard mutation checks in fresh processes.

This is regression sensitivity evidence, not a classifier benchmark or sandbox
attestation. Runtime files and frozen evaluation inputs are never rewritten.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time

from evaluation.mutation_cases import BY_ID, CASES, MutationCase

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "safeguard-mutations-v1"


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, timeout=30).stdout


def source_snapshot(root: Path = ROOT) -> dict:
    """Bind code/test bytes, including dirty/untracked code, separately from HEAD."""
    sha = _git(root, "rev-parse", "HEAD").decode().strip()
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    listed = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z",
                  "backend", "evaluation", "scripts", "Makefile",
                  ".github/workflows/safeguard-mutations.yml")
    names = sorted(set(name.decode() for name in listed.split(b"\0") if name))
    digest = hashlib.sha256()
    count = 0
    for name in names:
        path = root / name
        if path.suffix not in {".py", ".toml", ".lock", ".sh", ".yml"} and name != "Makefile":
            continue
        if path.is_symlink():
            raise ValueError("measured code must not be a symlink")
        value = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "deleted"
        digest.update(name.encode() + b"\0" + value.encode() + b"\n")
        count += 1
    return {"source_sha": sha, "source_dirty": bool(status),
            "worktree_status_sha256": hashlib.sha256(status).hexdigest(),
            "code_and_tests_sha256": digest.hexdigest(), "measured_file_count": count}


def assess_phase(payload: dict | None, *, case: MutationCase, mode: str,
                 nonce: str, returncode: int, provenance_ok: bool) -> tuple[str, str]:
    """Only a real assertion in the selected test body can kill a mutant."""
    if not provenance_ok:
        return "error", "source_provenance_changed"
    if not isinstance(payload, dict):
        return "error", "missing_or_invalid_child_report"
    if any(payload.get(key) != value for key, value in {
        "case_id": case.id, "mode": mode, "nonce": nonce, "exit_code": returncode,
        "collected": [case.test_id], "collection_errors": 0,
        "runtime_source": "backend/src/" + case.module.replace(".", "/") + ".py",
    }.items()):
        return "error", "child_identity_collection_or_exit_mismatch"
    phases = payload.get("phases")
    if (not isinstance(phases, list) or len(phases) != 3
            or any(not isinstance(phase, dict) for phase in phases)):
        return "error", "missing_or_extra_test_phases"
    if [phase.get("when") for phase in phases] != ["setup", "call", "teardown"]:
        return "error", "invalid_test_phase_order"
    if any(phase.get("test_id") != case.test_id for phase in phases):
        return "error", "unexpected_test_id"
    setup, call, teardown = phases
    if setup.get("outcome") != "passed" or teardown.get("outcome") != "passed":
        return "error", "test_setup_or_teardown_failed_or_skipped"
    if mode == "baseline":
        if payload.get("mutation_applied") is not False or payload.get("mutation_calls") != 0:
            return "error", "baseline_was_mutated"
        if returncode == 0 and call.get("outcome") == "passed":
            return "passed", "unmodified_focused_test_passed"
        return "error", "baseline_did_not_pass"
    if payload.get("mutation_applied") is not True:
        return "error", "mutation_not_applied"
    if not isinstance(payload.get("mutation_calls"), int) or payload["mutation_calls"] < 1:
        return "error", "mutation_not_exercised"
    if not isinstance(payload.get("effect_calls"), int) or payload["effect_calls"] < 1:
        return "error", "mutation_had_no_effect"
    if returncode == 0 and call.get("outcome") == "passed":
        return "survived", "focused_test_passed_with_mutation"
    if (returncode == 1 and call.get("outcome") == "failed"
            and call.get("exception_type") == "AssertionError"
            and call.get("assertion_in_test") is True
            and call.get("failure_source") == case.test_id.split("::")[0]):
        return "killed", "selected_test_assertion_failed"
    return "error", "non_assertion_failure_or_abnormal_exit"


def child_environment(root: Path, scratch: Path) -> dict[str, str]:
    # Do not inherit database URLs, provider keys, GitHub tokens, Python hooks,
    # pytest options/plugins or telemetry export configuration from the operator.
    env = {key: value for key, value in os.environ.items()
           if key in {"PATH", "SYSTEMROOT", "LANG", "LC_ALL"}}
    env.update(PYTHONPATH=os.pathsep.join((str(root / "backend/src"), str(root))),
               PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               PYTHONHASHSEED="0", HOME=str(scratch), TMPDIR=str(scratch),
               FAILURELENS_DATABASE_URL="sqlite+pysqlite:///:memory:",
               FAILURELENS_ARTIFACT_ROOT=str(scratch / "artifacts"),
               FAILURELENS_DEMO_MODE="true", FAILURELENS_TELEMETRY_EXPORT_ENABLED="false",
               FAILURELENS_SYNTHETIC_MUTATIONS="1")
    return env


def run_phase(case: MutationCase, mode: str, source: dict, *,
              root: Path = ROOT, timeout: float = 90) -> dict:
    started = time.monotonic()
    nonce = secrets.token_hex(16)
    result = {"mode": mode, "status": "error", "reason": "runner_error"}
    with tempfile.TemporaryDirectory(prefix="loose-thread-mutation-") as directory:
        scratch = Path(directory)
        report_path = scratch / "child.json"
        log_path = scratch / "pytest.log"
        args = [sys.executable, "-m", "pytest", "-q", "-o", "addopts=",
                "-p", "no:cacheprovider", "-p", "evaluation.mutation_plugin",
                "--rootdir", str(root), "--basetemp", str(scratch / "tests"),
                "--safeguard-case", case.id, "--safeguard-mode", mode,
                "--safeguard-result", str(report_path), "--safeguard-nonce", nonce,
                str(root / case.test_id)]
        try:
            if source_snapshot(root) != source:
                result["reason"] = "source_provenance_changed"
                return result
            with log_path.open("wb") as log:
                process = subprocess.run(args, cwd=scratch, env=child_environment(root, scratch),
                                         stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
            payload = None
            if report_path.exists() and report_path.stat().st_size <= 100_000:
                try:
                    payload = json.loads(report_path.read_text())
                except (ValueError, UnicodeError):
                    pass
            provenance_ok = source_snapshot(root) == source
            status, reason = assess_phase(payload, case=case, mode=mode, nonce=nonce,
                                          returncode=process.returncode, provenance_ok=provenance_ok)
            result.update(status=status, reason=reason, exit_code=process.returncode)
            if isinstance(payload, dict):
                for key in ("mutation_applied", "mutation_calls", "effect_calls", "phases"):
                    result[key] = payload.get(key)
        except subprocess.TimeoutExpired:
            result["reason"] = "subprocess_timeout"
        except (OSError, ValueError, subprocess.SubprocessError):
            result["reason"] = "runner_or_provenance_error"
        finally:
            result["duration_seconds"] = round(time.monotonic() - started, 3)
            if log_path.exists():
                result["output_sha256"] = hashlib.sha256(log_path.read_bytes()).hexdigest()
    return result


def run_suite(cases=CASES, *, root: Path = ROOT, allow_dirty_source: bool = False,
              timeout: float = 90) -> dict:
    if not cases:
        raise ValueError("at least one registered mutation is required")
    source = source_snapshot(root)
    report = {"schema_version": SCHEMA_VERSION,
              "started_at": datetime.now(timezone.utc).isoformat(),
              "scope": "synthetic targeted regression sensitivity; not held-out quality acceptance",
              "source": source, "development_only": bool(source["source_dirty"]),
              "results": [], "status": "error"}
    if source["source_dirty"] and not allow_dirty_source:
        report["error"] = "dirty_source_requires_explicit_development_opt_in"
        return report
    # Establish every baseline before applying any mutation in another process.
    for case in cases:
        report["results"].append({
            "case_id": case.id, "description": case.description,
            "target": case.module + "." + case.target, "test_ids": [case.test_id],
            "test_sha256": hashlib.sha256((root / case.test_id.split("::")[0]).read_bytes()).hexdigest(),
            "baseline": run_phase(case, "baseline", source, root=root, timeout=timeout),
        })
    for case, entry in zip(cases, report["results"], strict=True):
        if entry["baseline"]["status"] != "passed":
            entry["mutant"] = {"status": "error", "reason": "baseline_not_passing_mutant_not_run"}
        else:
            entry["mutant"] = run_phase(case, "mutant", source, root=root, timeout=timeout)
    report["provenance_unchanged"] = source_snapshot(root) == source
    if not report["provenance_unchanged"]:
        # Never retain kills as accepted evidence if the measured checkout changed.
        for entry in report["results"]:
            entry["mutant"]["observed_status"] = entry["mutant"]["status"]
            entry["mutant"].update(status="error", reason="source_provenance_changed")
    report["summary"] = {
        "baseline_passed": sum(item["baseline"]["status"] == "passed" for item in report["results"]),
        **{status: sum(item["mutant"]["status"] == status for item in report["results"])
           for status in ("killed", "survived", "error")},
    }
    report["status"] = "passed" if report["summary"]["killed"] == len(cases) else "failed"
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-synthetic-mutations", action="store_true",
                        help="explicitly permit deliberate in-process safeguard bypasses in isolated tests")
    parser.add_argument("--allow-dirty-source", action="store_true",
                        help="development only; records code digests and never labels dirty source committed evidence")
    parser.add_argument("--case", action="append", choices=tuple(BY_ID))
    parser.add_argument("--timeout", type=float, default=90, help="seconds per subprocess")
    parser.add_argument("--output", type=Path, required=True, help="fresh JSON file outside the checkout")
    args = parser.parse_args(argv)
    if not args.confirm_synthetic_mutations:
        parser.error("--confirm-synthetic-mutations is required")
    if not 0 < args.timeout <= 600:
        parser.error("--timeout must be greater than zero and at most 600")
    destination = args.output.resolve()
    if destination.is_relative_to(ROOT) or destination.exists():
        parser.error("--output must be fresh and outside the checkout")
    cases = tuple(BY_ID[key] for key in dict.fromkeys(args.case)) if args.case else CASES
    try:
        report = run_suite(cases, allow_dirty_source=args.allow_dirty_source, timeout=args.timeout)
    except (OSError, ValueError, subprocess.SubprocessError):
        report = {"schema_version": SCHEMA_VERSION, "status": "error", "error": "source_provenance_unavailable"}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"status": report["status"], "summary": report.get("summary"),
                      "error": report.get("error"), "output": str(destination)}, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
