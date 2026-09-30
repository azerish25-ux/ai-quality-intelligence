"""Fail-closed, read-only quality gates with source-free, bounded JSON reports.

Tools run in an isolated hash-locked environment. Reports deliberately omit tool
messages, source snippets, fixes, secret values and secret hashes. Candidate
counts are not vulnerability confirmation; findings still fail their gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[1]
TOOL_PROJECT = ROOT / "tools/quality/pyproject.toml"
MAX_CAPTURE_BYTES = 16 * 1024 * 1024
MAX_REPORT_BYTES = 1024 * 1024
MAX_FINDINGS = 2000
CHECKS = (
    "locks",
    "lint",
    "format",
    "types",
    "python-audit",
    "npm-audit",
    "secrets",
    "workflows",
)
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")
SIGNED_QUERY_KEYS = {"sig", "signature", "x-amz-signature", "x-goog-signature"}
SECRET_DISABLED_FILTERS = (
    "detect_secrets.filters.allowlist.is_line_allowlisted",
    "detect_secrets.filters.common.is_ignored_due_to_verification_policies",
    "detect_secrets.filters.heuristic.is_lock_file",
    "detect_secrets.filters.heuristic.is_swagger_file",
)


class GateError(Exception):
    """An incomplete check must never become a clean result."""


def execute(command: list[str], *, cwd: Path = ROOT) -> tuple[int, str]:
    # Never stream scanner output to CI: it can contain source or secret values.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            process = subprocess.run(
                command, cwd=cwd, stdout=stdout, stderr=stderr, timeout=600, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GateError(type(exc).__name__) from None
        if stdout.tell() > MAX_CAPTURE_BYTES or stderr.tell() > MAX_CAPTURE_BYTES:
            raise GateError("tool-output-limit")
        stdout.seek(0)
        try:
            return process.returncode, stdout.read().decode("utf-8")
        except UnicodeDecodeError:
            raise GateError("non-utf8-tool-output") from None


def tool(name: str) -> str:
    return str(Path(sys.executable).parent / name)


def files_in_scope(root: Path = ROOT) -> list[str]:
    code, raw = execute(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
    )
    if code:
        raise GateError("git-inventory-failed")
    files = sorted(set(filter(None, raw.split("\0"))))
    if not files:
        raise GateError("empty-source-inventory")
    for name in files:
        path = root / name
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(root.resolve())
        ):
            raise GateError("missing-or-nonregular-source-file")
    return files


def source_digest(files: list[str], root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    for name in files:
        digest.update(name.encode() + b"\0")
        digest.update(hashlib.sha256((root / name).read_bytes()).digest())
    return digest.hexdigest()


def relative_name(name: str) -> str:
    path = Path(name)
    if path.is_absolute():
        try:
            path = path.relative_to(ROOT)
        except ValueError:
            raise GateError("tool-reported-out-of-scope-file") from None
    if ".." in path.parts:
        raise GateError("tool-reported-out-of-scope-file")
    return path.as_posix()


def checked_versions() -> dict[str, str]:
    project = tomllib.loads(TOOL_PROJECT.read_text())
    expected = dict(item.split("==") for item in project["project"]["dependencies"])
    try:
        actual = {name: version(name) for name in expected}
    except PackageNotFoundError:
        raise GateError("quality-environment-not-installed") from None
    if actual != expected:
        raise GateError("quality-tool-version-mismatch")
    return actual


def json_data(raw: str, expected: type) -> Any:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise GateError("invalid-tool-json") from None
    if not isinstance(data, expected):
        raise GateError("unexpected-tool-json-shape")
    return data


def ruff_findings(raw: str) -> list[dict[str, Any]]:
    return [
        {
            "file": relative_name(row["filename"]),
            "line": row["location"]["row"],
            "code": row["code"] or "format",
        }
        for row in json_data(raw, list)
    ]


def secret_findings(raw: str) -> list[dict[str, Any]]:
    data = json_data(raw, dict)
    if not data.get("plugins_used") or "results" not in data:
        raise GateError("incomplete-secret-scan")
    return [
        {"file": relative_name(name), "line": row["line_number"], "code": row["type"]}
        for name, rows in data["results"].items()
        for row in rows
    ]


def signed_url_findings(files: list[str], root: Path = ROOT) -> list[dict[str, Any]]:
    findings = []
    for name in files:
        # Text embedded in non-UTF8 files is included; archives are not unpacked.
        for number, line in enumerate(
            (root / name).read_bytes().decode("utf-8", errors="replace").splitlines(), 1
        ):
            for match in URL_PATTERN.finditer(line):
                try:
                    keys = {
                        key.lower()
                        for key, value in parse_qsl(urlsplit(match.group()).query)
                        if value
                    }
                except ValueError:
                    continue
                if keys & SIGNED_QUERY_KEYS:
                    findings.append(
                        {"file": name, "line": number, "code": "signed-url-query"}
                    )
    return findings


def workflow_findings(raw: str) -> list[dict[str, Any]]:
    findings = []
    for row in json_data(raw, list):
        locations = row["locations"]
        if not locations:
            raise GateError("workflow-finding-without-location")
        primary = next(
            (loc for loc in locations if loc["symbolic"]["kind"] == "Primary"),
            locations[0],
        )
        findings.append(
            {
                "file": relative_name(
                    primary["symbolic"]["key"]["Local"]["verbatim_path"]
                ),
                "line": primary["concrete"]["location"]["start_point"]["row"] + 1,
                "code": row["ident"],
                "severity": row["determinations"]["severity"],
                "confidence": row["determinations"]["confidence"],
            }
        )
    return findings


def python_audit_findings(raw: str, graph: str) -> tuple[list[dict[str, Any]], int]:
    data = json_data(raw, dict)
    deps = data["dependencies"]
    if not deps or any("skip_reason" in row for row in deps):
        raise GateError("incomplete-python-dependency-audit")
    return [
        {
            "graph": graph,
            "package": row["name"],
            "code": vuln["id"],
            "fixed_versions": vuln["fix_versions"],
        }
        for row in deps
        for vuln in row["vulns"]
    ], len(deps)


def npm_audit_findings(raw: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = json_data(raw, dict)
    if "error" in data or data.get("auditReportVersion") != 2:
        raise GateError("incomplete-npm-dependency-audit")
    findings = []
    for name, row in data["vulnerabilities"].items():
        advisories = []
        for entry in row["via"]:
            if isinstance(entry, dict):
                # Keep only advisory identifiers, never arbitrary remote prose or URLs.
                advisories.extend(re.findall(r"GHSA-[a-z0-9-]+", entry.get("url", "")))
        findings.append(
            {
                "package": name,
                "code": "npm-vulnerable-package",
                "severity": row["severity"],
                "advisories": sorted(set(advisories)),
            }
        )
    metadata = data["metadata"]
    if len(findings) != metadata["vulnerabilities"]["total"]:
        raise GateError("inconsistent-npm-dependency-audit")
    return findings, metadata


def check_locks() -> tuple[list[dict[str, Any]], list[int]]:
    findings = []
    codes = []
    graphs: tuple[tuple[str, str, list[str]], ...] = (
        ("backend", "backend/requirements.lock", ["--extra", "dev"]),
        ("backend", "backend/requirements-runtime.lock", []),
        ("tools/quality", "tools/quality/requirements.lock", []),
    )
    for project in ("backend", "tools/quality"):
        code, _ = execute(
            [tool("uv"), "lock", "--project", project, "--check", "--offline"]
        )
        codes.append(code)
        if code:
            raise GateError("lock-not-current-or-offline-validation-failed")
    for project, target, extra in graphs:
        code, raw = execute(
            [
                tool("uv"),
                "export",
                "--project",
                project,
                "--frozen",
                "--offline",
                "--no-emit-project",
                "--no-header",
                "--format",
                "requirements-txt",
                *extra,
            ]
        )
        codes.append(code)
        if code:
            raise GateError("lock-export-failed")
        if raw.encode() != (ROOT / target).read_bytes():
            findings.append({"file": target, "code": "lock-export-mismatch"})
    manifest = json.loads((ROOT / "frontend/package.json").read_text())
    npm_lock = json.loads((ROOT / "frontend/package-lock.json").read_text())
    locked_root = npm_lock["packages"][""]
    for section in (
        "dependencies",
        "devDependencies",
        "optionalDependencies",
        "peerDependencies",
    ):
        if manifest.get(section, {}) != locked_root.get(section, {}):
            findings.append(
                {
                    "file": "frontend/package-lock.json",
                    "code": "npm-manifest-lock-mismatch",
                    "section": section,
                }
            )
    return findings, codes


def run_check(
    check: str,
    files: list[str],
    app_python: str | None,
    allow_npm_registry_audit: bool = False,
) -> dict[str, Any]:
    python_files = [name for name in files if name.endswith((".py", ".pyi"))]
    details: dict[str, Any] = {}
    if check == "locks":
        findings, codes = check_locks()
        return {"findings": findings, "tool_exit_codes": codes}
    if check in {"lint", "format"}:
        if not python_files:
            raise GateError("empty-python-scope")
        command = [
            tool("ruff"),
            "check" if check == "lint" else "format",
            "--isolated",
            "--target-version",
            "py312",
            "--no-cache",
            "--no-force-exclude",
            "--no-respect-gitignore",
            "--output-format",
            "json",
        ]
        command += ["--ignore-noqa"] if check == "lint" else ["--check"]
        code, raw = execute([*command, *python_files])
        findings = ruff_findings(raw)
        details["files_checked"] = len(python_files)
    elif check == "types":
        if not app_python:
            raise GateError("app-python-required")
        with tempfile.TemporaryDirectory(prefix="loose-mypy-") as cache:
            code, raw = execute(
                [
                    tool("mypy"),
                    "--config-file",
                    str(TOOL_PROJECT),
                    "--python-executable",
                    app_python,
                    "--cache-dir",
                    cache,
                    "--output",
                    "json",
                    "backend/src",
                ]
            )
        rows = [json_data(line, dict) for line in raw.splitlines() if line]
        findings = [
            {
                "file": relative_name(row["file"]),
                "line": row["line"],
                "code": row["code"] or "type-check",
                "severity": row["severity"],
            }
            for row in rows
            if row["severity"] == "error"
        ]
        details["files_in_scope"] = len(
            [name for name in python_files if name.startswith("backend/src/")]
        )
        details["mode"] = (
            "gradual typing with untyped-body and unused-ignore checks; not strict annotation coverage"
        )
    elif check == "secrets":
        command = [tool("detect-secrets"), "scan", "--no-verify", "--all-files"]
        for disabled in SECRET_DISABLED_FILTERS:
            command.extend(["--disable-filter", disabled])
        code, raw = execute([*command, *files])
        findings = secret_findings(raw) + signed_url_findings(files)
        details["files_supplied"] = len(files)
        non_utf8 = []
        for name in files:
            try:
                (ROOT / name).read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                non_utf8.append(name)
        details["non_utf8_files"] = non_utf8
        details["mode"] = (
            "current text files, offline, no baseline; binary/archived content and Git history are not certified"
        )
    elif check == "workflows":
        paths = [
            name
            for name in files
            if (
                name.startswith(".github/workflows/")
                and name.endswith((".yml", ".yaml"))
            )
            or Path(name).name in {"action.yml", "action.yaml"}
        ]
        if not paths:
            raise GateError("empty-workflow-scope")
        code, raw = execute(
            [
                tool("zizmor"),
                "--offline",
                "--strict-collection",
                "--no-ignores",
                "--persona",
                "auditor",
                "--format",
                "json",
                *paths,
            ]
        )
        findings = workflow_findings(raw)
        details["files_checked"] = len(paths)
        details["mode"] = "offline auditor; online-only audits are not executed"
    elif check == "python-audit":
        findings = []
        codes = []
        counts = {}
        for graph in ("backend/requirements.lock", "tools/quality/requirements.lock"):
            code, raw = execute(
                [
                    tool("pip-audit"),
                    "--strict",
                    "--disable-pip",
                    "--require-hashes",
                    "--format",
                    "json",
                    "--desc",
                    "off",
                    "--progress-spinner",
                    "off",
                    "-r",
                    graph,
                ]
            )
            rows, count = python_audit_findings(raw, graph)
            if code not in (0, 1):
                raise GateError("python-audit-tool-error")
            if code and not rows:
                raise GateError("python-audit-nonzero-without-findings")
            findings.extend(rows)
            codes.append(code)
            counts[graph] = count
        return {
            "findings": findings,
            "tool_exit_codes": codes,
            "dependencies_by_graph": counts,
            "mode": "current-platform markers; public PyPI advisory service",
        }
    elif check == "npm-audit":
        if not allow_npm_registry_audit:
            raise GateError("npm-registry-approval-required")
        code, npm_version = execute(["npm", "--version"])
        if code or npm_version.strip() != "11.17.0":
            raise GateError("npm-version-mismatch-expected-11.17.0")
        code, raw = execute(
            [
                "npm",
                "audit",
                "--package-lock-only",
                "--ignore-scripts",
                "--audit-level=low",
                "--include=dev",
                "--include=optional",
                "--include=peer",
                "--json",
                "--registry=https://registry.npmjs.org",
            ],
            cwd=ROOT / "frontend",
        )
        findings, metadata = npm_audit_findings(raw)
        details.update({"npm_version": npm_version.strip(), "audit_metadata": metadata})
    else:
        raise GateError("unknown-check")
    allowed_codes = {"secrets": {0}, "workflows": {0, 11, 12, 13, 14}}.get(
        check, {0, 1}
    )
    if code not in allowed_codes:
        raise GateError("tool-execution-error")
    if code and not findings:
        raise GateError("tool-nonzero-without-findings")
    return {"findings": findings, "tool_exit_codes": [code], **details}


def write_report(report: dict[str, Any], output: Path) -> None:
    findings = report.pop("findings", [])
    report["finding_count"] = len(findings)
    report["categories"] = dict(
        sorted(Counter(row["code"] for row in findings).items())
    )
    report["findings"] = findings[:MAX_FINDINGS]
    report["omitted_finding_count"] = len(findings) - len(report["findings"])
    payload = json.dumps(report, indent=2, sort_keys=True).encode() + b"\n"
    if len(payload) > MAX_REPORT_BYTES:
        report["findings"] = []
        report["omitted_finding_count"] = len(findings)
        payload = json.dumps(report, indent=2, sort_keys=True).encode() + b"\n"
    if len(payload) > MAX_REPORT_BYTES:
        raise GateError("report-size-limit")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=CHECKS)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--app-python",
        help="Python from the separately installed backend lock environment",
    )
    parser.add_argument(
        "--allow-npm-registry-audit",
        action="store_true",
        help="Approve sending dependency names/versions and possible full lock-tree/runtime metadata to registry.npmjs.org for this audit",
    )
    args = parser.parse_args(argv)
    if args.output.resolve().is_relative_to(ROOT):
        parser.error("reports must be outside the source tree")
    report: dict[str, Any] = {
        "schema_version": 1,
        "check": args.check,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "error",
        "findings": [],
    }
    if args.check == "npm-audit" and not args.allow_npm_registry_audit:
        report.update(
            {
                "status": "not_run",
                "reason": "npm-registry-approval-required",
                "finished_at": datetime.now(UTC).isoformat(),
            }
        )
        write_report(report, args.output)
        print(
            "npm-audit: NOT RUN; registry metadata transmission requires approval (not a pass)"
        )
        return 3
    exit_code = 2
    try:
        report["tool_versions"] = checked_versions()
        files = files_in_scope()
        before = source_digest(files)
        code, revision = execute(["git", "rev-parse", "HEAD"])
        if code:
            raise GateError("git-revision-failed")
        report.update(
            {
                "revision": revision.strip(),
                "source_digest": before,
                "source_file_count": len(files),
            }
        )
        status_code, dirty = execute(
            ["git", "status", "--porcelain", "--untracked-files=normal"]
        )
        if status_code:
            raise GateError("git-status-failed")
        report["worktree_clean"] = not dirty.strip()
        report.update(
            run_check(args.check, files, args.app_python, args.allow_npm_registry_audit)
        )
        if files != files_in_scope() or before != source_digest(files):
            raise GateError("source-changed-during-check")
        final_code, final_revision = execute(["git", "rev-parse", "HEAD"])
        if final_code or final_revision.strip() != revision.strip():
            raise GateError("revision-changed-during-check")
        exit_code = 1 if report["findings"] else 0
        report["status"] = "fail" if exit_code else "pass"
    except (GateError, OSError, KeyError, TypeError, ValueError) as exc:
        report["error"] = str(exc) if isinstance(exc, GateError) else type(exc).__name__
    report["finished_at"] = datetime.now(UTC).isoformat()
    # The report contains only structured metadata; exceptions never print tool output.
    write_report(report, args.output)
    print(f"{args.check}: {report['status']}; {report['finding_count']} findings")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
