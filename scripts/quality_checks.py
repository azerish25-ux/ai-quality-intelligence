"""Fail-closed, read-only quality gates with source-free, bounded JSON reports.

Tools run in an isolated hash-locked environment. Reports deliberately omit tool
messages, source snippets, fixes, secret values and secret hashes. Candidate
counts are not vulnerability confirmation; findings still fail their gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
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
SECRET_REVIEW_FILE = "tools/quality/reviewed-secrets.json"
REVIEW_PARTS_DIR = "tools/quality/reviewed-secrets"
MAX_REVIEW_PART_BYTES = 79_999
MAX_REVIEW_PARTS = 64
MAX_REVIEW_BYTES = 4 * 1024 * 1024
MAX_REVIEW_ENTRIES = 2000
MAX_REVIEW_TEXT = 2048
MAX_REVIEW_OCCURRENCES = 10000
MAX_REVIEW_DEPTH = 12
SECRET_REVIEW_CLASSES = {
    "integrity_identifier",
    "intentional_fake_credential",
    "intentional_public_demo_credential",
    "nonsecret_configuration_literal",
}


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


def secret_occurrences(
    data: dict[str, Any], files: list[str], root: Path
) -> list[dict[str, Any]]:
    """Reconcile CLI candidates with a complete, non-deduplicated offline pass.

    Matched values and fingerprints stay in memory, never in ordinary reports.
    This uses the pinned scanner's own file transformations and heuristics.
    """
    from detect_secrets.core.scan import scan_file
    from detect_secrets.settings import transient_settings

    candidates = []
    with transient_settings(data):
        for name, rows in data["results"].items():
            if name not in files or relative_name(name) != name:
                raise GateError("secret-result-outside-inventory")
            expected = {}
            for row in rows:
                key = (row["type"], row["hashed_secret"])
                if key in expected or type(row["line_number"]) is not int:
                    raise GateError("invalid-secret-candidate")
                expected[key] = row["line_number"]
            observed: dict[tuple[str, str], dict[str, Any]] = {}
            source = (root / name).read_bytes()
            lines = source.decode("utf-8").splitlines()
            for secret in scan_file(str(root / name)):
                key = (secret.type, secret.secret_hash)
                value_digest = hashlib.sha256(secret.secret_value.encode()).hexdigest()
                if key not in observed:
                    observed[key] = {"value_sha256": value_digest, "lines": set()}
                if observed[key]["value_sha256"] != value_digest:
                    raise GateError("ambiguous-secret-candidate")
                observed[key]["lines"].add(secret.line_number)
            if set(observed) != set(expected):
                raise GateError("inconsistent-secret-occurrence-scan")
            for (detector, token_hash), result in observed.items():
                positions = sorted(result["lines"])
                if expected[(detector, token_hash)] not in positions or any(
                    number < 1 or number > len(lines) for number in positions
                ):
                    raise GateError("inconsistent-secret-occurrence-location")
                candidates.append(
                    {
                        "file": name,
                        "detector": detector,
                        "value_sha256": result["value_sha256"],
                        "file_sha256": hashlib.sha256(source).hexdigest(),
                        "occurrences": [
                            {
                                "line": number,
                                "context_sha256": hashlib.sha256(
                                    "\n".join(
                                        lines[max(0, number - 3) : number + 2]
                                    ).encode()
                                ).hexdigest(),
                            }
                            for number in positions
                        ],
                        "line": expected[(detector, token_hash)],
                    }
                )
    return candidates


def exact_keys(value: Any, keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise GateError("invalid-secret-review-schema")


def unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise GateError("duplicate-secret-review-field")
        result[key] = value
    return result


def check_review_json_depth(raw: str) -> None:
    depth = 0
    quoted = escaped = False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_REVIEW_DEPTH:
                raise GateError("secret-review-nesting-limit")
        elif char in "]}":
            depth -= 1


def review_policy_path(name: str) -> bool:
    return name == SECRET_REVIEW_FILE or name.startswith(REVIEW_PARTS_DIR + "/")


def _review_directory(root: Path, relative: str) -> int:
    """Open each directory by descriptor; a symlink swap cannot redirect reads."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(root, flags)
    try:
        for component in Path(relative).parts:
            following = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _review_document(root: Path, name: str, limit: int) -> tuple[dict[str, Any], str]:
    path = Path(name)
    directory = _review_directory(root, path.parent.as_posix())
    try:
        descriptor = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise GateError("nonregular-secret-review-file")
            contents = stream.read(limit + 1)
    finally:
        os.close(directory)
    if len(contents) > limit:
        raise GateError("secret-review-size-limit")
    raw = contents.decode("utf-8")
    check_review_json_depth(raw)
    try:
        policy = json.loads(raw, object_pairs_hook=unique_json_object)
    except RecursionError:
        raise GateError("secret-review-nesting-limit") from None
    except (ValueError, UnicodeError):
        raise GateError("invalid-secret-review-json") from None
    if raw != json.dumps(policy, indent=2, sort_keys=True) + "\n":
        raise GateError("noncanonical-secret-review-policy")
    if not isinstance(policy, dict):
        raise GateError("invalid-secret-review-schema")
    return policy, raw


def load_review_policy(
    root: Path, files: list[str]
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    """Load legacy or bounded multipart policy without changing its logical data."""
    index_path = root / SECRET_REVIEW_FILE
    parts_path = root / REVIEW_PARTS_DIR
    if not index_path.exists() and not index_path.is_symlink():
        if parts_path.exists() or parts_path.is_symlink():
            raise GateError("orphan-secret-review-parts")
        return None, {}
    if SECRET_REVIEW_FILE not in files:
        raise GateError("secret-review-outside-inventory")
    policy, raw = _review_document(root, SECRET_REVIEW_FILE, MAX_REVIEW_BYTES)
    documents = {SECRET_REVIEW_FILE: raw}
    schema = policy.get("schema_version")
    if type(schema) is not int or schema not in {1, 2}:
        raise GateError("unsupported-secret-review-schema")
    if schema == 1:
        exact_keys(policy, {"schema_version", "scanner", "entries"})
        if parts_path.exists() or parts_path.is_symlink():
            raise GateError("orphan-secret-review-parts")
        return policy, documents
    exact_keys(
        policy, {"schema_version", "scanner", "entry_count", "logical_sha256", "parts"}
    )
    if len(raw.encode()) > MAX_REVIEW_PART_BYTES:
        raise GateError("secret-review-size-limit")
    if (
        type(policy["entry_count"]) is not int
        or not 1 <= policy["entry_count"] <= MAX_REVIEW_ENTRIES
        or not isinstance(policy["logical_sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", policy["logical_sha256"])
    ):
        raise GateError("invalid-secret-review-manifest")
    parts = policy["parts"]
    if not isinstance(parts, list) or not 1 <= len(parts) <= MAX_REVIEW_PARTS:
        raise GateError("invalid-secret-review-parts")
    expected_names = [f"part-{number:04}.json" for number in range(1, len(parts) + 1)]
    directory = _review_directory(root, REVIEW_PARTS_DIR)
    try:
        if set(os.listdir(directory)) != set(expected_names):
            raise GateError("secret-review-part-inventory-mismatch")
    finally:
        os.close(directory)
    expected_paths = {f"{REVIEW_PARTS_DIR}/{name}" for name in expected_names}
    if {
        name for name in files if name.startswith(REVIEW_PARTS_DIR + "/")
    } != expected_paths:
        raise GateError("secret-review-outside-inventory")
    entries: list[dict[str, Any]] = []
    total_bytes = len(raw.encode())
    for part, filename in zip(parts, expected_names, strict=True):
        exact_keys(part, {"path", "sha256", "entry_count"})
        expected_path = f"{REVIEW_PARTS_DIR}/{filename}"
        if (
            part["path"] != expected_path
            or type(part["entry_count"]) is not int
            or not 1 <= part["entry_count"] <= MAX_REVIEW_ENTRIES
            or not isinstance(part["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", part["sha256"])
        ):
            raise GateError("invalid-secret-review-part")
        content, part_raw = _review_document(root, expected_path, MAX_REVIEW_PART_BYTES)
        total_bytes += len(part_raw.encode())
        if total_bytes > MAX_REVIEW_BYTES:
            raise GateError("secret-review-size-limit")
        if hashlib.sha256(part_raw.encode()).hexdigest() != part["sha256"]:
            raise GateError("secret-review-part-digest-mismatch")
        exact_keys(content, {"schema_version", "entries"})
        if type(content["schema_version"]) is not int or content["schema_version"] != 1:
            raise GateError("unsupported-secret-review-schema")
        if (
            not isinstance(content["entries"], list)
            or len(content["entries"]) != part["entry_count"]
        ):
            raise GateError("secret-review-part-count-mismatch")
        entries.extend(content["entries"])
        if len(entries) > MAX_REVIEW_ENTRIES:
            raise GateError("secret-review-entry-limit")
        documents[expected_path] = part_raw
    logical = {"schema_version": 1, "scanner": policy["scanner"], "entries": entries}
    logical_bytes = (json.dumps(logical, indent=2, sort_keys=True) + "\n").encode()
    if len(logical_bytes) > MAX_REVIEW_BYTES:
        raise GateError("secret-review-size-limit")
    if len(entries) != policy["entry_count"]:
        raise GateError("secret-review-entry-count-mismatch")
    if hashlib.sha256(logical_bytes).hexdigest() != policy["logical_sha256"]:
        raise GateError("secret-review-logical-digest-mismatch")
    return logical, documents


def validated_secret_reviews(
    data: dict[str, Any], candidates: list[dict[str, Any]], root: Path, files: list[str]
) -> tuple[dict[tuple[str, str, str], str], set[tuple[str, int, str]]]:
    """Only fully recomputed review fields can explain exact policy findings."""
    policy, documents = load_review_policy(root, files)
    if policy is None:
        return {}, set()
    scanner = {key: data[key] for key in ("version", "plugins_used", "filters_used")}
    if policy["scanner"] != scanner:
        raise GateError("secret-review-scanner-mismatch")
    if not isinstance(policy["entries"], list) or not policy["entries"]:
        raise GateError("empty-secret-review-policy")
    if len(policy["entries"]) > MAX_REVIEW_ENTRIES:
        raise GateError("secret-review-entry-limit")
    index = {
        (row["file"], row["detector"], row["value_sha256"]): row
        for row in candidates
        if not review_policy_path(row["file"])
    }
    reviews = {}
    review_ids = set()
    for entry in policy["entries"]:
        exact_keys(
            entry,
            {
                "review_id",
                "file",
                "detector",
                "value_sha256",
                "file_sha256",
                "occurrences",
                "classification",
                "reason",
                "evidence",
                "reviewed_by",
                "reviewed_on",
                "review_reference",
            },
        )
        for field in (
            "review_id",
            "file",
            "detector",
            "classification",
            "reason",
            "evidence",
            "reviewed_by",
            "reviewed_on",
            "review_reference",
        ):
            if (
                not isinstance(entry[field], str)
                or not entry[field].strip()
                or len(entry[field]) > MAX_REVIEW_TEXT
            ):
                raise GateError("invalid-secret-review-text")
        name = entry["file"]
        if (
            review_policy_path(name)
            or Path(name).is_absolute()
            or Path(name).as_posix() != name
            or ".." in Path(name).parts
            or any(char in name for char in "*?[]\\")
        ):
            raise GateError("invalid-secret-review-path")
        if entry["classification"] not in SECRET_REVIEW_CLASSES:
            raise GateError("invalid-secret-review-classification")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["reviewed_on"]):
            raise GateError("invalid-secret-review-date")
        for field in ("value_sha256", "file_sha256"):
            if not isinstance(entry[field], str) or not re.fullmatch(
                r"[0-9a-f]{64}", entry[field]
            ):
                raise GateError("invalid-secret-review-digest")
        if not isinstance(entry["occurrences"], list) or not entry["occurrences"]:
            raise GateError("invalid-secret-review-occurrences")
        if len(entry["occurrences"]) > MAX_REVIEW_OCCURRENCES:
            raise GateError("secret-review-occurrence-limit")
        for occurrence in entry["occurrences"]:
            exact_keys(occurrence, {"line", "context_sha256"})
            if (
                type(occurrence["line"]) is not int
                or occurrence["line"] < 1
                or not isinstance(occurrence["context_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", occurrence["context_sha256"])
            ):
                raise GateError("invalid-secret-review-occurrence")
        key = (name, entry["detector"], entry["value_sha256"])
        if key in reviews or entry["review_id"] in review_ids:
            raise GateError("duplicate-secret-review-entry")
        candidate = index.get(key)
        if candidate is None:
            raise GateError("stale-secret-review-entry")
        if any(
            entry[field] != candidate[field] for field in ("file_sha256", "occurrences")
        ):
            raise GateError("changed-secret-review-source")
        reviews[key] = entry["classification"]
        review_ids.add(entry["review_id"])
    metadata = set()
    for name, raw in documents.items():
        fields = "value_sha256|file_sha256|context_sha256"
        if name == SECRET_REVIEW_FILE and len(documents) > 1:
            fields = "sha256|logical_sha256"
        for number, line in enumerate(raw.splitlines(), 1):
            match = re.fullmatch(rf'\s*"(?:{fields})": "([0-9a-f]{{64}})",?', line)
            if match:
                metadata.add(
                    (name, number, hashlib.sha256(match[1].encode()).hexdigest())
                )
    return reviews, metadata


def reviewed_secret_findings(raw: str, files: list[str], root: Path) -> dict[str, Any]:
    data = json_data(raw, dict)
    secret_findings(raw)  # Preserve completeness checks before interpreting policy.
    candidates = secret_occurrences(data, files, root)
    errors = []
    try:
        if (root / SECRET_REVIEW_FILE).exists() and SECRET_REVIEW_FILE not in files:
            raise GateError("secret-review-outside-inventory")
        reviews, metadata = validated_secret_reviews(data, candidates, root, files)
    except GateError as exc:
        reviews, metadata = {}, set()
        errors.append(str(exc))
    except RecursionError:
        reviews, metadata = {}, set()
        errors.append("secret-review-nesting-limit")
    except (OSError, UnicodeError, KeyError, TypeError, ValueError):
        reviews, metadata = {}, set()
        errors.append("unreadable-or-invalid-secret-review-policy")
    findings = []
    classes: Counter[str] = Counter()
    for row in candidates:
        key = (row["file"], row["detector"], row["value_sha256"])
        classification = reviews.get(key)
        if (
            review_policy_path(row["file"])
            and row["detector"] == "Hex High Entropy String"
            and all(
                (row["file"], occurrence["line"], row["value_sha256"]) in metadata
                for occurrence in row["occurrences"]
            )
        ):
            classification = "validated_policy_metadata"
        decision = "reviewed" if classification else "unresolved"
        if classification:
            classes[classification] += 1
        findings.append(
            {
                "file": row["file"],
                "line": row["line"],
                "code": row["detector"],
                "review_status": decision,
                "occurrence_count": len(row["occurrences"]),
            }
        )
    signed = signed_url_findings(files, root)
    findings.extend({**row, "review_status": "unresolved"} for row in signed)
    # A large reviewed policy must not push unresolved locations out of the
    # bounded public report. Raw and classification totals remain untruncated.
    findings.sort(
        key=lambda row: (
            row["review_status"] != "unresolved",
            row["file"],
            row["line"],
            row["code"],
        )
    )
    reviewed = sum(classes.values())
    policy_count = sum(review_policy_path(row["file"]) for row in candidates)
    reviewed_policy = classes["validated_policy_metadata"]
    return {
        "findings": findings,
        "raw_candidate_count": len(findings),
        "raw_source_candidate_count": len(findings) - policy_count,
        "raw_policy_candidate_count": policy_count,
        "raw_occurrence_count": sum(len(row["occurrences"]) for row in candidates)
        + len(signed),
        "reviewed_candidate_count": reviewed,
        "reviewed_source_candidate_count": reviewed - reviewed_policy,
        "reviewed_policy_candidate_count": reviewed_policy,
        "reviewed_classifications": dict(sorted(classes.items())),
        "unresolved_candidate_count": len(findings) - reviewed,
        "review_policy_errors": errors,
    }


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
        if code:
            raise GateError("tool-execution-error")
        review = reviewed_secret_findings(raw, files, ROOT)
        findings = review.pop("findings")
        details.update(review)
        details["files_supplied"] = len(files)
        non_utf8 = []
        for name in files:
            try:
                (ROOT / name).read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                non_utf8.append(name)
        details["non_utf8_files"] = non_utf8
        details["mode"] = (
            "current text files, offline, exact reviewed entries; binary/archived content and Git history are not certified"
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
        unresolved = report.get("unresolved_candidate_count", len(report["findings"]))
        exit_code = 1 if unresolved or report.get("review_policy_errors") else 0
        report["status"] = "fail" if exit_code else "pass"
    except (GateError, OSError, KeyError, TypeError, ValueError) as exc:
        report["error"] = str(exc) if isinstance(exc, GateError) else type(exc).__name__
    report["finished_at"] = datetime.now(UTC).isoformat()
    # The report contains only structured metadata; exceptions never print tool output.
    write_report(report, args.output)
    if args.check == "secrets" and "raw_candidate_count" in report:
        print(
            f"secrets: {report['status']}; {report['raw_candidate_count']} raw, "
            f"{report['reviewed_source_candidate_count']} reviewed source, "
            f"{report['reviewed_policy_candidate_count']} validated policy metadata, "
            f"{report['unresolved_candidate_count']} unresolved"
        )
    else:
        print(f"{args.check}: {report['status']}; {report['finding_count']} findings")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
