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
    monkeypatch.setattr(quality, "secret_occurrences", lambda *args: [])
    monkeypatch.setattr(quality, "signed_url_findings", lambda *args: [])
    assert (
        quality.run_check("secrets", ["requirements.lock", "test.py"], None)["findings"]
        == []
    )
    command = calls[0]
    # Bound worker count on shared hosts without changing scan scope/settings.
    assert command[1:4] == ["--cores", "1", "scan"]
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


@pytest.fixture
def reviewed_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """An explicit synthetic review; production has no baseline-creation command."""
    import hashlib

    source = 'value = "synthetic-review-canary"\n'
    (tmp_path / "fixture.py").write_text(source)
    candidate = {
        "file": "fixture.py",
        "detector": "Secret Keyword",
        "value_sha256": hashlib.sha256(b"synthetic-review-canary").hexdigest(),
        "file_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "line": 1,
        "occurrences": [
            {
                "line": 1,
                "context_sha256": hashlib.sha256(source.strip().encode()).hexdigest(),
            }
        ],
    }
    scanner = {
        "version": "1.5.0",
        "plugins_used": [{"name": "KeywordDetector"}],
        "filters_used": [],
    }
    entry = {
        **{key: value for key, value in candidate.items() if key != "line"},
        "review_id": "synthetic-test-review",
        "classification": "intentional_fake_credential",
        "reason": "Purpose-built scanner regression canary with no external account.",
        "evidence": "fixture.py:1",
        "reviewed_by": "test fixture",
        "reviewed_on": "2026-09-30",
        "review_reference": "synthetic-review-test",
    }
    policy = {"schema_version": 1, "scanner": scanner, "entries": [entry]}
    policy_path = tmp_path / quality.SECRET_REVIEW_FILE
    policy_path.parent.mkdir(parents=True)
    policy_path.write_text(json.dumps(policy, indent=2, sort_keys=True) + "\n")
    candidates = [candidate]
    monkeypatch.setattr(quality, "secret_occurrences", lambda *args: candidates)
    monkeypatch.setattr(quality, "signed_url_findings", lambda *args: [])
    return {
        "root": tmp_path,
        "policy": policy,
        "path": policy_path,
        "candidates": candidates,
        "raw": json.dumps({**scanner, "results": {}}),
    }


def scan_review(fixture: dict[str, Any]) -> dict[str, Any]:
    return quality.reviewed_secret_findings(
        fixture["raw"], ["fixture.py", quality.SECRET_REVIEW_FILE], fixture["root"]
    )


def save_test_policy(fixture: dict[str, Any]) -> None:
    fixture["path"].write_text(
        json.dumps(fixture["policy"], indent=2, sort_keys=True) + "\n"
    )


def test_review_preserves_raw_count_and_removes_no_locations(reviewed_scan):
    result = scan_review(reviewed_scan)
    assert result["raw_candidate_count"] == 1
    assert result["raw_occurrence_count"] == 1
    assert result["reviewed_candidate_count"] == 1
    assert result["unresolved_candidate_count"] == 0
    assert result["reviewed_classifications"] == {"intentional_fake_credential": 1}
    assert result["review_policy_errors"] == []
    assert result["findings"][0]["review_status"] == "reviewed"
    assert "sha256" not in json.dumps(result)
    assert "synthetic-review-canary" not in json.dumps(result)


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("value", "stale-secret-review-entry"),
        ("file", "stale-secret-review-entry"),
        ("detector", "stale-secret-review-entry"),
        ("file_digest", "changed-secret-review-source"),
        ("context", "changed-secret-review-source"),
        ("new_occurrence", "changed-secret-review-source"),
        ("deleted", "stale-secret-review-entry"),
    ],
)
def test_changed_and_deleted_review_candidates_fail_closed(
    reviewed_scan, mutation, expected
):
    candidate = reviewed_scan["candidates"][0]
    if mutation in {"value", "file", "detector"}:
        candidate[
            {"value": "value_sha256", "file": "file", "detector": "detector"}[mutation]
        ] = "changed"
    elif mutation == "file_digest":
        candidate["file_sha256"] = "changed"
    elif mutation == "context":
        candidate["occurrences"] = [{"line": 1, "context_sha256": "changed"}]
    elif mutation == "new_occurrence":
        candidate["occurrences"] = [
            *candidate["occurrences"],
            {"line": 2, "context_sha256": "changed"},
        ]
    else:
        reviewed_scan["candidates"].clear()
    result = scan_review(reviewed_scan)
    assert result["review_policy_errors"] == [expected]
    assert result["reviewed_candidate_count"] == 0
    assert result["unresolved_candidate_count"] == len(reviewed_scan["candidates"])


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("duplicate", "duplicate-secret-review-entry"),
        ("unknown", "invalid-secret-review-schema"),
        ("wildcard", "invalid-secret-review-path"),
        ("absolute", "invalid-secret-review-path"),
        ("self", "invalid-secret-review-path"),
        ("empty_reason", "invalid-secret-review-text"),
        ("classification", "invalid-secret-review-classification"),
        ("scanner", "secret-review-scanner-mismatch"),
        ("empty", "empty-secret-review-policy"),
        ("bool_line", "invalid-secret-review-occurrence"),
        ("bad_digest", "invalid-secret-review-digest"),
        ("proposal", "invalid-secret-review-schema"),
    ],
)
def test_review_policy_rejects_invalid_or_unreviewed_entries(
    reviewed_scan, mutation, expected
):
    policy = reviewed_scan["policy"]
    entry = policy["entries"][0]
    if mutation == "duplicate":
        policy["entries"].append(dict(entry))
    elif mutation in {"unknown", "proposal"}:
        entry[mutation] = True
    elif mutation in {"wildcard", "absolute", "self"}:
        entry["file"] = {
            "wildcard": "*.py",
            "absolute": "/fixture.py",
            "self": quality.SECRET_REVIEW_FILE,
        }[mutation]
    elif mutation == "empty_reason":
        entry["reason"] = " "
    elif mutation == "classification":
        entry["classification"] = "real_production_credential"
    elif mutation == "scanner":
        policy["scanner"]["version"] = "changed"
    elif mutation == "empty":
        policy["entries"] = []
    elif mutation == "bool_line":
        entry["occurrences"][0]["line"] = True
    else:
        entry["value_sha256"] = "not-a-digest"
    save_test_policy(reviewed_scan)
    result = scan_review(reviewed_scan)
    assert result["review_policy_errors"] == [expected]
    assert result["reviewed_candidate_count"] == 0
    assert result["raw_candidate_count"] == result["unresolved_candidate_count"] == 1


def test_new_candidate_and_same_value_elsewhere_are_unresolved(reviewed_scan):
    candidate = reviewed_scan["candidates"][0]
    reviewed_scan["candidates"].extend(
        [{**candidate, "file": "new.py"}, {**candidate, "value_sha256": "new-value"}]
    )
    result = scan_review(reviewed_scan)
    assert result["reviewed_candidate_count"] == 1
    assert result["unresolved_candidate_count"] == 2
    assert result["raw_candidate_count"] == 3


def test_missing_policy_never_accepts_candidates(reviewed_scan):
    reviewed_scan["path"].unlink()
    result = scan_review(reviewed_scan)
    assert result["reviewed_candidate_count"] == 0
    assert result["unresolved_candidate_count"] == 1


@pytest.mark.parametrize(
    "content", ['{"schema_version":1,"schema_version":1}', "not json"]
)
def test_invalid_policy_json_fails_without_losing_raw_counts(reviewed_scan, content):
    reviewed_scan["path"].write_text(content)
    result = scan_review(reviewed_scan)
    assert result["review_policy_errors"]
    assert result["unresolved_candidate_count"] == result["raw_candidate_count"] == 1


def test_policy_requires_canonical_structure(reviewed_scan):
    reviewed_scan["path"].write_text(json.dumps(reviewed_scan["policy"]))
    assert scan_review(reviewed_scan)["review_policy_errors"] == [
        "noncanonical-secret-review-policy"
    ]


def add_policy_candidate(fixture: dict[str, Any], line: int, value: str) -> None:
    import hashlib

    fixture["candidates"].append(
        {
            "file": quality.SECRET_REVIEW_FILE,
            "line": line,
            "detector": "Hex High Entropy String",
            "value_sha256": hashlib.sha256(value.encode()).hexdigest(),
            "occurrences": [{"line": line, "context_sha256": "unused-in-policy"}],
        }
    )


def test_only_recomputed_exact_policy_digest_fields_are_reviewed(reviewed_scan):
    entry = reviewed_scan["policy"]["entries"][0]
    value = entry["file_sha256"]
    line = next(
        i
        for i, text in enumerate(reviewed_scan["path"].read_text().splitlines(), 1)
        if '"file_sha256"' in text
    )
    add_policy_candidate(reviewed_scan, line, value)
    result = scan_review(reviewed_scan)
    assert result["reviewed_classifications"]["validated_policy_metadata"] == 1
    assert result["unresolved_candidate_count"] == 0
    # The same bytes on any other line, or under another detector, are unresolved.
    reviewed_scan["candidates"][-1]["occurrences"].append({"line": line + 1})
    assert scan_review(reviewed_scan)["unresolved_candidate_count"] == 1
    reviewed_scan["candidates"][-1]["occurrences"].pop()
    reviewed_scan["candidates"][-1]["detector"] = "Secret Keyword"
    assert scan_review(reviewed_scan)["unresolved_candidate_count"] == 1


def test_arbitrary_hash_in_policy_text_is_not_accepted(reviewed_scan):
    entry = reviewed_scan["policy"]["entries"][0]
    entry["reason"] = entry["file_sha256"]
    save_test_policy(reviewed_scan)
    line = next(
        i
        for i, text in enumerate(reviewed_scan["path"].read_text().splitlines(), 1)
        if '"reason"' in text
    )
    add_policy_candidate(reviewed_scan, line, entry["reason"])
    assert scan_review(reviewed_scan)["unresolved_candidate_count"] == 1
    entry["file_sha256"] = "0" * 64
    save_test_policy(reviewed_scan)
    result = scan_review(reviewed_scan)
    assert result["reviewed_candidate_count"] == 0
    assert result["review_policy_errors"] == ["changed-secret-review-source"]


def test_signed_urls_remain_unresolved_under_review_policy(reviewed_scan, monkeypatch):
    monkeypatch.setattr(
        quality,
        "signed_url_findings",
        lambda *args: [{"file": "fixture.py", "line": 1, "code": "signed-url-query"}],
    )
    result = scan_review(reviewed_scan)
    assert result["raw_candidate_count"] == 2
    assert result["unresolved_candidate_count"] == 1


@pytest.mark.parametrize(
    "errors,unresolved,expected",
    [([], 0, 0), ([], 1, 1), (["stale-secret-review-entry"], 0, 1)],
)
def test_secret_gate_uses_decisions_and_rejects_stale_entries(
    tmp_path, monkeypatch, errors, unresolved, expected
):
    monkeypatch.setattr(quality, "checked_versions", dict)
    monkeypatch.setattr(quality, "files_in_scope", lambda: ["test.py"])
    monkeypatch.setattr(quality, "source_digest", lambda files: "source-digest")
    monkeypatch.setattr(quality, "execute", lambda *args, **kwargs: (0, "revision"))
    monkeypatch.setattr(
        quality,
        "run_check",
        lambda *args: {
            "findings": [{"code": "candidate", "review_status": "reviewed"}],
            "unresolved_candidate_count": unresolved,
            "review_policy_errors": errors,
        },
    )
    output = tmp_path / "result.json"
    assert quality.main(["secrets", "--output", str(output)]) == expected
    assert json.loads(output.read_text())["finding_count"] == 1


@pytest.mark.parametrize(
    "mutation",
    ["missing", "extra", "line", "out_of_scope", "duplicate", "wrong_line_type"],
)
def test_occurrence_scan_rejects_incomplete_or_inconsistent_cli_result(
    tmp_path, monkeypatch, mutation
):
    import contextlib
    import types

    name = "fixture.py"
    (tmp_path / name).write_text("synthetic source\n")
    row = {
        "type": "Secret Keyword",
        "hashed_secret": "detector-fingerprint",
        "line_number": 1,
    }
    data = {"results": {name: [row]}}
    occurrences = [
        types.SimpleNamespace(
            type=row["type"],
            secret_hash=row["hashed_secret"],
            secret_value="synthetic-canary",
            line_number=1,
        )
    ]
    if mutation == "missing":
        occurrences.clear()
    elif mutation == "extra":
        occurrences.append(
            types.SimpleNamespace(
                type=row["type"],
                secret_hash="extra-fingerprint",
                secret_value="other-canary",
                line_number=1,
            )
        )
    elif mutation == "line":
        occurrences[0].line_number = 2
    elif mutation == "out_of_scope":
        data["results"] = {"other.py": [row]}
    elif mutation == "duplicate":
        data["results"][name].append(dict(row))
    else:
        row["line_number"] = True
    scanner = types.ModuleType("detect_secrets.core.scan")
    scanner.scan_file = lambda path: iter(occurrences)
    settings = types.ModuleType("detect_secrets.settings")
    settings.transient_settings = lambda config: contextlib.nullcontext()
    monkeypatch.setitem(sys.modules, "detect_secrets.core.scan", scanner)
    monkeypatch.setitem(sys.modules, "detect_secrets.settings", settings)
    with pytest.raises(quality.GateError):
        quality.secret_occurrences(data, [name], tmp_path)


def test_policy_outside_measured_inventory_cannot_activate(reviewed_scan):
    result = quality.reviewed_secret_findings(
        reviewed_scan["raw"], ["fixture.py"], reviewed_scan["root"]
    )
    assert result["review_policy_errors"] == ["secret-review-outside-inventory"]
    assert result["reviewed_candidate_count"] == 0


def test_non_utf8_policy_preserves_unresolved_counts(reviewed_scan):
    reviewed_scan["path"].write_bytes(bytes([255]))
    result = scan_review(reviewed_scan)
    assert result["review_policy_errors"] == [
        "unreadable-or-invalid-secret-review-policy"
    ]
    assert result["raw_candidate_count"] == result["unresolved_candidate_count"] == 1


def test_reviewed_secrets_cannot_pass_after_concurrent_source_change(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(quality, "checked_versions", dict)
    monkeypatch.setattr(quality, "files_in_scope", lambda: ["fixture.py"])
    digests = iter(["reviewed-source", "changed-source"])
    monkeypatch.setattr(quality, "source_digest", lambda files: next(digests))
    monkeypatch.setattr(quality, "execute", lambda *args, **kwargs: (0, "revision"))
    monkeypatch.setattr(
        quality,
        "run_check",
        lambda *args: {
            "findings": [{"code": "candidate", "review_status": "reviewed"}],
            "unresolved_candidate_count": 0,
            "review_policy_errors": [],
        },
    )
    output = tmp_path / "report.json"
    assert quality.main(["secrets", "--output", str(output)]) == 2
    report = json.loads(output.read_text())
    assert report["status"] == "error"
    assert report["error"] == "source-changed-during-check"
    assert report["finding_count"] == 1


@pytest.mark.parametrize(
    "bound,error",
    [
        ("bytes", "secret-review-size-limit"),
        ("entries", "secret-review-entry-limit"),
        ("text", "invalid-secret-review-text"),
        ("occurrences", "secret-review-occurrence-limit"),
        ("nesting", "secret-review-nesting-limit"),
    ],
)
def test_policy_resource_limits_fail_closed_without_source_text(
    reviewed_scan, monkeypatch, bound, error
):
    if bound == "bytes":
        monkeypatch.setattr(quality, "MAX_REVIEW_BYTES", 8)
    elif bound == "entries":
        monkeypatch.setattr(quality, "MAX_REVIEW_ENTRIES", 0)
    elif bound == "text":
        reviewed_scan["policy"]["entries"][0]["reason"] = (
            "synthetic-sensitive-text" * 100
        )
        save_test_policy(reviewed_scan)
    elif bound == "occurrences":
        monkeypatch.setattr(quality, "MAX_REVIEW_OCCURRENCES", 0)
    else:
        reviewed_scan["path"].write_text(
            "[" * 3000 + '"synthetic-sensitive-text"' + "]" * 3000
        )
    result = scan_review(reviewed_scan)
    assert result["review_policy_errors"] == [error]
    assert result["reviewed_candidate_count"] == 0
    assert result["unresolved_candidate_count"] == result["raw_candidate_count"] == 1
    assert "synthetic-sensitive-text" not in json.dumps(result)


def test_policy_depth_check_handles_json_string_escapes(reviewed_scan):
    reviewed_scan["policy"]["entries"][0]["reason"] = (
        "[" * 40 + '"literal quoted braces"' + "\\" + "}" * 40
    )
    save_test_policy(reviewed_scan)
    assert scan_review(reviewed_scan)["review_policy_errors"] == []


def test_unresolved_locations_precede_reviewed_metadata_when_report_is_bounded(
    reviewed_scan, monkeypatch, tmp_path
):
    candidate = reviewed_scan["candidates"][0]
    reviewed_scan["candidates"].append({**candidate, "file": "new.py"})
    result = scan_review(reviewed_scan)
    monkeypatch.setattr(quality, "MAX_FINDINGS", 1)
    output = tmp_path / "bounded.json"
    quality.write_report({"status": "fail", **result}, output)
    report = json.loads(output.read_text())
    assert report["findings"][0]["file"] == "new.py"
    assert report["findings"][0]["review_status"] == "unresolved"
    assert report["raw_candidate_count"] == 2
    assert report["unresolved_candidate_count"] == 1
    assert report["omitted_finding_count"] == 1
