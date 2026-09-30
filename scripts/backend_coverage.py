"""Collect fresh, source-bound backend coverage and check separate M9 targets.

Only collect writes measurements. Check consumes the source-free report, verifies
its source inventory and counts, and recomputes fixed thresholds without rounding.
Neither command accepts an omission list, alternate target, or preexisting data.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from coverage.exceptions import CoverageException

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "backend/src/failurelens"
OVERALL_TARGET = 90
CRITICAL_TARGET = 95
COMBINED_TARGET = 75
MAX_REPORT_BYTES = 1024 * 1024
# Declared before measurement. Mixed API/service boundaries belong in this scope,
# even when a module also implements ordinary CRUD or display behavior.
CRITICAL_GROUPS = {
    "evidence_and_storage": (
        "evidence_validation",
        "contract_evidence",
        "transaction_evidence",
        "domain_evidence",
        "binary_evidence",
        "trace_evidence",
        "github_evidence",
        "storage",
        "image_codec",
        "image_worker",
    ),
    "authorization_and_configuration": (
        "auth",
        "accounts",
        "config",
        "db",
        "api",
        "operations_api",
        "binary_api",
        "provider_api",
        "github_api",
    ),
    "redaction": ("redaction", "redaction_keys"),
    "dangerous_dismissal_and_report": (
        "analysis",
        "history",
        "providers",
        "impact",
        "performance",
        "performance_numeric",
        "schemas",
        "github_report",
        "github_report_sections",
        "github_snapshot",
        "publication_validity",
    ),
    "publication_and_provider_execution": (
        "service",
        "provider_service",
        "provider_jobs",
        "provider_proxy",
        "github_publication_service",
        "github_publication",
    ),
}
CRITICAL = {
    f"{PACKAGE}/{name}.py": group
    for group, names in CRITICAL_GROUPS.items()
    for name in names
}
COUNT_KEYS = (
    "num_statements",
    "covered_lines",
    "missing_lines",
    "num_branches",
    "covered_branches",
    "missing_branches",
)


class CoverageError(Exception):
    """Invalid or incomplete evidence must fail closed."""


def digest(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise CoverageError("missing-or-nonregular-source")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def python_inventory(directory: Path) -> dict[str, str]:
    directory = directory.resolve()
    result = {}
    if any(path.is_symlink() for path in directory.rglob("*")):
        raise CoverageError("symlink-in-source-inventory")
    for path in sorted(directory.rglob("*.py")):
        if not path.resolve().is_relative_to(directory):
            raise CoverageError("source-path-escape")
        result[path.relative_to(directory).as_posix()] = digest(path)
    if not result:
        raise CoverageError("empty-source-inventory")
    return result


def source_snapshot(root: Path) -> dict[str, str]:
    """Do not read evaluation labels/corpora to establish code provenance."""
    if any(
        not name.startswith("failurelens/")
        for name in python_inventory(root / "backend/src")
    ):
        raise CoverageError("undeclared-backend-runtime-package")
    result = {}
    for directory in (PACKAGE, "backend/tests"):
        result.update(
            {
                f"{directory}/{name}": value
                for name, value in python_inventory(root / directory).items()
            }
        )
    for name in (
        "backend/pyproject.toml",
        "backend/requirements.lock",
        "backend/uv.lock",
        "scripts/backend_coverage.py",
        "scripts/isolated_worker_coverage.py",
    ):
        result[name] = digest(root / name)
    return dict(sorted(result.items()))


def snapshot_digest(snapshot: dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def read_json(path: Path, limit: int = MAX_REPORT_BYTES) -> Any:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise CoverageError("missing-or-oversized-report")
    try:
        return json.loads(path.read_text(), object_pairs_hook=unique_object)
    except (ValueError, UnicodeError) as exc:
        raise CoverageError("invalid-json") from exc


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise CoverageError("duplicate-json-key")
        result[key] = value
    return result


def write_json(path: Path, value: Any) -> None:
    content = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if len(content.encode()) > MAX_REPORT_BYTES:
        raise CoverageError("oversized-report")
    with path.open("x", encoding="utf-8") as target:
        target.write(content)


def counts(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise CoverageError("invalid-counts")
    result = {}
    for key in COUNT_KEYS:
        number = value.get(key)
        if type(number) is not int or number < 0:
            raise CoverageError("invalid-counts")
        result[key] = number
    if (
        result["covered_lines"] + result["missing_lines"] != result["num_statements"]
        or result["covered_branches"] + result["missing_branches"]
        != result["num_branches"]
    ):
        raise CoverageError("inconsistent-counts")
    return result


def add_counts(files: dict[str, dict[str, int]]) -> dict[str, int]:
    return {key: sum(value[key] for value in files.values()) for key in COUNT_KEYS}


def reaches(covered: int, total: int, target: int) -> bool:
    # Never decide acceptance using rounded percentages or floating point.
    return total > 0 and covered * 100 >= target * total


def gates(files: dict[str, dict[str, int]]) -> dict[str, Any]:
    if not set(CRITICAL).issubset(files):
        raise CoverageError("missing-critical-files")
    total = add_counts(files)
    if not total["num_branches"]:
        raise CoverageError("no-branch-opportunities")
    critical = {}
    for name, group in CRITICAL.items():
        item = files[name]
        if not item["num_branches"]:
            raise CoverageError("critical-file-has-no-branches")
        critical[name] = {
            "group": group,
            "target_percent": CRITICAL_TARGET,
            "passed": reaches(
                item["covered_branches"], item["num_branches"], CRITICAL_TARGET
            ),
        }
    combined = reaches(
        total["covered_lines"] + total["covered_branches"],
        total["num_statements"] + total["num_branches"],
        COMBINED_TARGET,
    )
    overall = reaches(total["covered_branches"], total["num_branches"], OVERALL_TARGET)
    return {
        "overall": total,
        "ordinary_combined_gate": {
            "target_percent": COMBINED_TARGET,
            "passed": combined,
        },
        "overall_branch_gate": {"target_percent": OVERALL_TARGET, "passed": overall},
        "critical_branch_gates": critical,
        "master_branch_acceptance": overall
        and all(item["passed"] for item in critical.values()),
    }


def canonical_path(filename: str, roots: list[Path], inventory: dict[str, str]) -> str:
    path = Path(filename)
    if not path.is_absolute() or path.is_symlink():
        raise CoverageError("noncanonical-measured-path")
    resolved = path.resolve()
    for root in roots:
        if resolved.is_relative_to(root):
            relative = resolved.relative_to(root).as_posix()
            if relative not in inventory or digest(path) != inventory[relative]:
                raise CoverageError("changed-or-foreign-measured-source")
            return f"{PACKAGE}/{relative}"
    raise CoverageError("foreign-measured-path")


def combine_fresh_shards(
    output: Path, roots: list[Path], inventory: dict[str, str], root: Path
) -> None:
    from coverage import CoverageData

    # A new directory prevents stale data. Do not let coverage's fuzzy path aliases
    # merge installed, mutated, copied, or unrelated packages by basename.
    shards = sorted(output.glob(".coverage.*"))
    if not shards:
        raise CoverageError("missing-coverage-shards")
    combined = CoverageData(basename=str(output / "coverage-data.sqlite"))
    for path in shards:
        if path.is_symlink() or not path.is_file():
            raise CoverageError("invalid-coverage-shard")
        data = CoverageData(basename=str(path))
        data.read()
        if not data.has_arcs():
            raise CoverageError("nonbranch-coverage-shard")
        for filename in data.measured_files():
            canonical = canonical_path(filename, roots, inventory)
            combined.add_arcs({canonical: data.arcs(filename) or []})
    if not combined.measured_files():
        raise CoverageError("empty-coverage-measurement")
    combined.touch_files([f"{PACKAGE}/{name}" for name in inventory])
    combined.write()


def measured_counts(
    data_path: Path, expected: set[str], root: Path
) -> dict[str, dict[str, int]]:
    from coverage import Coverage, CoverageData

    if not data_path.is_file() or data_path.is_symlink():
        raise CoverageError("missing-or-nonregular-coverage-data")
    data = CoverageData(basename=str(data_path))
    data.read()
    if not data.has_arcs():
        raise CoverageError("nonbranch-coverage-data")
    if set(data.measured_files()) != expected:
        raise CoverageError("missing-or-foreign-coverage-data-paths")
    measured = Coverage(
        data_file=None, config_file=False, branch=True, source=[str(root / PACKAGE)]
    )
    measured.get_data().add_arcs(
        {str(root / name): data.arcs(name) or [] for name in expected}
    )
    measured.get_data().touch_files([str(root / name) for name in expected])
    with tempfile.TemporaryDirectory(prefix="failurelens-coverage-json-") as temporary:
        raw_path = Path(temporary) / "coverage.json"
        measured.json_report(outfile=str(raw_path))
        raw = read_json(raw_path, limit=32 * MAX_REPORT_BYTES)
    return validate_raw(raw, expected, root)


def validate_raw(raw: Any, expected: set[str], root: Path) -> dict[str, dict[str, int]]:
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("meta"), dict)
        or raw["meta"].get("branch_coverage") is not True
    ):
        raise CoverageError("nonbranch-coverage-json")
    files = raw.get("files")
    if not isinstance(files, dict):
        raise CoverageError("invalid-file-measurements")
    result = {}
    for name, item in files.items():
        path = Path(name)
        if name not in expected:
            path = path.resolve()
            if not path.is_relative_to(root):
                raise CoverageError("foreign-json-path")
            name = path.relative_to(root).as_posix()
        if name not in expected or name in result or not isinstance(item, dict):
            raise CoverageError("foreign-or-duplicate-json-path")
        summary = counts(item.get("summary"))
        for field, count in (
            ("executed_lines", "covered_lines"),
            ("missing_lines", "missing_lines"),
            ("executed_branches", "covered_branches"),
            ("missing_branches", "missing_branches"),
        ):
            values = item.get(field)
            if not isinstance(values, list) or len(values) != summary[count]:
                raise CoverageError("inconsistent-coverage-details")
            if "branches" in field:
                if any(
                    not isinstance(pair, list)
                    or len(pair) != 2
                    or any(type(number) is not int for number in pair)
                    for pair in values
                ):
                    raise CoverageError("invalid-branch-details")
                values = [tuple(pair) for pair in values]
            elif any(type(number) is not int or number < 1 for number in values):
                raise CoverageError("invalid-line-details")
            if len(set(values)) != len(values):
                raise CoverageError("duplicate-coverage-details")
        for kind in ("lines", "branches"):
            executed = item[f"executed_{kind}"]
            missing = item[f"missing_{kind}"]
            if any(value in executed for value in missing):
                raise CoverageError("overlapping-coverage-details")
        result[name] = summary
    if set(result) != expected:
        raise CoverageError("missing-runtime-files")
    if counts(raw.get("totals")) != add_counts(result):
        raise CoverageError("inconsistent-total-counts")
    return dict(sorted(result.items()))


def git_identity(root: Path) -> dict[str, Any]:
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=root,
        text=True,
    )
    return {"revision": revision, "working_tree_clean": not bool(status)}


def verify_committed_source(
    root: Path, snapshot: dict[str, str], identity: dict[str, Any]
) -> None:
    if identity["working_tree_clean"] is not True:
        raise CoverageError("uncommitted-source-measurement")
    revision = identity["revision"]
    explicit = {
        name
        for name in snapshot
        if not name.startswith((PACKAGE + "/", "backend/tests/"))
    }
    listed = (
        subprocess.check_output(
            [
                "git",
                "ls-tree",
                "-r",
                "--name-only",
                "-z",
                revision,
                "--",
                PACKAGE,
                "backend/tests",
                *sorted(explicit),
            ],
            cwd=root,
        )
        .decode()
        .split("\0")
    )
    committed = {
        name for name in listed if name and (name.endswith(".py") or name in explicit)
    }
    if committed != set(snapshot):
        raise CoverageError("uncommitted-source-inventory")
    names = sorted(snapshot)
    if any("\n" in name or "\r" in name for name in names):
        raise CoverageError("invalid-source-path")
    result = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=root,
        input="".join(f"{revision}:{name}\n" for name in names).encode(),
        capture_output=True,
        check=True,
    ).stdout
    cursor = 0
    for name in names:
        end = result.find(b"\n", cursor)
        header = result[cursor:end].split()
        if end < 0 or len(header) != 3 or header[1] != b"blob":
            raise CoverageError("invalid-committed-source")
        size = int(header[2])
        start = end + 1
        content = result[start : start + size]
        if (
            len(content) != size
            or hashlib.sha256(content).hexdigest() != snapshot[name]
        ):
            raise CoverageError("committed-source-byte-mismatch")
        cursor = start + size
        if result[cursor : cursor + 1] != b"\n":
            raise CoverageError("invalid-committed-source")
        cursor += 1
    if cursor != len(result):
        raise CoverageError("invalid-committed-source")


def test_summary(path: Path) -> dict[str, int]:
    if not path.is_file() or path.stat().st_size > 32 * MAX_REPORT_BYTES:
        raise CoverageError("missing-or-oversized-test-outcomes")
    document = ET.fromstring(path.read_bytes())
    suites = list(document.iter("testsuite"))
    if not suites:
        raise CoverageError("missing-test-outcomes")
    result = {
        key: sum(int(suite.attrib[key]) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    result["passed"] = (
        result["tests"] - result["failures"] - result["errors"] - result["skipped"]
    )
    result["postgresql_only_skips"] = sum(
        skip.attrib.get("message")
        == "a real PostgreSQL FAILURELENS_DATABASE_URL is required"
        for skip in document.iter("skipped")
    )
    validate_test_summary(result)
    return result


def validate_test_summary(value: Any) -> None:
    expected = {
        "tests",
        "passed",
        "failures",
        "errors",
        "skipped",
        "postgresql_only_skips",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or any(type(number) is not int or number < 0 for number in value.values())
        or not value["tests"]
        or value["passed"] + value["failures"] + value["errors"] + value["skipped"]
        != value["tests"]
        or value["postgresql_only_skips"] > value["skipped"]
    ):
        raise CoverageError("invalid-test-outcomes")


def host_oom_kills() -> int | None:
    """Optional host-wide diagnostic, never attribution to this test process."""
    try:
        for line in Path("/proc/vmstat").read_text().splitlines():
            if line.startswith("oom_kill "):
                value = int(line.split()[1])
                return value if value >= 0 else None
    except (OSError, ValueError, IndexError):
        pass
    return None


def collect(
    output: Path,
    pytest_args: list[str],
    root: Path = ROOT,
    *,
    development: bool = False,
) -> int:
    import coverage

    if tuple(map(int, coverage.__version__.split(".")[:2])) < (7, 10):
        raise CoverageError("coverage-subprocess-patch-unavailable")
    root = root.resolve()
    if output.is_symlink():
        raise CoverageError("symlink-output-directory")
    output = output.resolve()
    if output.is_relative_to(root):
        raise CoverageError("output-must-be-outside-measured-checkout")
    output.mkdir(parents=True, exist_ok=False)
    snapshot = source_snapshot(root)
    identity = git_identity(root)
    if not development:
        verify_committed_source(root, snapshot, identity)
    inventory = python_inventory(root / PACKAGE)
    spec = importlib.util.find_spec("failurelens")
    if spec is None or spec.origin is None:
        raise CoverageError("backend-package-not-importable")
    installed = Path(spec.origin).resolve().parent
    if python_inventory(installed) != inventory:
        raise CoverageError("installed-package-source-mismatch")
    roots = sorted({installed, (root / PACKAGE).resolve()})
    config = output / "coverage.ini"
    config.write_text(
        "[run]\nbranch = true\nparallel = true\npatch = subprocess\n"
        f"data_file = {output / '.coverage'}\nsource =\n"
        + "".join(f"    {path}\n" for path in roots)
        + "\n[report]\nshow_missing = true\nfail_under = 75\n"
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("COVERAGE_", "COV_CORE_", "COV_CONTEXT"))
    }
    # Keep inherited CLI subprocess coverage, while the production image child's
    # explicit minimal environment continues to omit it.
    environment["COVERAGE_FILE"] = str(output / ".coverage")
    import_paths = [str(root)]
    if "PYTHONPATH" in environment:
        import_paths.extend(
            str(Path(part or os.curdir).resolve())
            for part in environment["PYTHONPATH"].split(os.pathsep)
        )
    environment["PYTHONPATH"] = os.pathsep.join(import_paths)
    test_args = []
    for argument in pytest_args:
        filename, separator, selector = argument.partition("::")
        candidate = root / filename
        test_args.append(
            str(candidate) + separator + selector
            if not argument.startswith("-") and candidate.exists()
            else argument
        )
    working = output / "test-working"
    working.mkdir()
    outcomes = output / "test-outcomes.xml"
    command = [
        sys.executable,
        "-m",
        "coverage",
        "run",
        f"--rcfile={config}",
        "-m",
        "pytest",
        "-p",
        "no:pytest_cov",
        *test_args,
        f"--junitxml={outcomes}",
    ]
    oom_before = host_oom_kills()
    test_started = time.monotonic()
    completed = subprocess.run(command, cwd=working, env=environment, check=False)
    execution = {
        "schema_version": 1,
        "scope": "pytest_process_observation_not_acceptance",
        "source_revision_at_start": identity["revision"],
        "source_digest_at_start": snapshot_digest(snapshot),
        "pytest_exit_code": completed.returncode,
        "termination_signal": -completed.returncode
        if completed.returncode < 0
        else None,
        "elapsed_seconds": time.monotonic() - test_started,
        "outcome_file_present": outcomes.is_file(),
        "host_oom_kills_before": oom_before,
        "host_oom_kills_after": host_oom_kills(),
    }
    # Preserve the child exit even when it could not write JUnit or coverage.
    # A signal or host-wide OOM delta alone cannot identify the cause of death.
    print(json.dumps({"test_process": execution}, sort_keys=True), flush=True)
    write_json(output / "test-execution.json", execution)
    try:
        outcomes_summary = test_summary(outcomes)
    finally:
        outcomes.unlink(missing_ok=True)
    if source_snapshot(root) != snapshot or git_identity(root) != identity:
        raise CoverageError("source-changed-during-measurement")
    if any(python_inventory(path) != inventory for path in roots):
        raise CoverageError("runtime-source-changed-during-measurement")
    combine_fresh_shards(output, roots, inventory, root)
    data_path = output / "coverage-data.sqlite"
    data_digest = digest(data_path)
    files = measured_counts(
        data_path, {f"{PACKAGE}/{name}" for name in inventory}, root
    )
    if source_snapshot(root) != snapshot or git_identity(root) != identity:
        raise CoverageError("source-changed-during-report")
    if not development:
        verify_committed_source(root, snapshot, identity)
    if digest(data_path) != data_digest:
        raise CoverageError("coverage-data-changed-during-report")
    report = {
        "schema_version": 1,
        "branch_coverage": True,
        "measurement_complete": True,
        "coverage_version": coverage.__version__,
        "coverage_data_sha256": data_digest,
        "measurement_kind": "development" if development else "committed",
        "source": {**identity, "files": snapshot, "sha256": snapshot_digest(snapshot)},
        "pytest_exit_code": completed.returncode,
        "test_summary": outcomes_summary,
        "files": files,
        **gates(files),
    }
    if (
        development
        or completed.returncode != 0
        or outcomes_summary["failures"]
        or outcomes_summary["errors"]
    ):
        report["master_branch_acceptance"] = False
    write_json(output / "report.json", report)
    print(
        json.dumps(
            {
                "pytest_exit_code": completed.returncode,
                "test_summary": outcomes_summary,
                "overall": report["overall"],
                "ordinary_combined_gate": report["ordinary_combined_gate"],
                "master_branch_acceptance": report["master_branch_acceptance"],
            },
            sort_keys=True,
        )
    )
    return (
        0
        if completed.returncode == 0 and report["ordinary_combined_gate"]["passed"]
        else 1
    )


def check_report(report: Any, data_path: Path, root: Path = ROOT) -> bool:
    import coverage

    if (
        not isinstance(report, dict)
        or type(report.get("schema_version")) is not int
        or report["schema_version"] != 1
        or report.get("branch_coverage") is not True
        or report.get("measurement_complete") is not True
    ):
        raise CoverageError("incomplete-or-nonbranch-report")
    expected_keys = {
        "schema_version",
        "branch_coverage",
        "measurement_complete",
        "coverage_version",
        "coverage_data_sha256",
        "measurement_kind",
        "source",
        "pytest_exit_code",
        "test_summary",
        "files",
        "overall",
        "ordinary_combined_gate",
        "overall_branch_gate",
        "critical_branch_gates",
        "master_branch_acceptance",
    }
    if (
        set(report) != expected_keys
        or report["coverage_version"] != coverage.__version__
    ):
        raise CoverageError("invalid-report-schema-or-coverage-version")
    if report["measurement_kind"] != "committed":
        raise CoverageError("development-report-not-acceptance")
    snapshot = source_snapshot(root)
    identity = git_identity(root)
    verify_committed_source(root, snapshot, identity)
    source = report.get("source")
    if (
        not isinstance(source, dict)
        or set(source) != {"files", "sha256", "revision", "working_tree_clean"}
        or source.get("files") != snapshot
        or source.get("sha256") != snapshot_digest(snapshot)
        or source.get("revision") != identity["revision"]
        or source.get("working_tree_clean") is not True
    ):
        raise CoverageError("stale-or-invalid-source")
    values = report.get("files")
    if not isinstance(values, dict):
        raise CoverageError("invalid-file-measurements")
    expected = {name for name in snapshot if name.startswith(PACKAGE + "/")}
    if set(values) != expected:
        raise CoverageError("missing-or-foreign-runtime-files")
    if any(
        not isinstance(value, dict) or set(value) != set(COUNT_KEYS)
        for value in values.values()
    ):
        raise CoverageError("invalid-file-count-schema")
    files = {name: counts(value) for name, value in values.items()}
    data_digest = digest(data_path)
    if report["coverage_data_sha256"] != data_digest:
        raise CoverageError("coverage-data-digest-mismatch")
    # Recompute both numerators and denominators from the retained executed arcs
    # and current committed source, never from a self-certified summary alone.
    if files != measured_counts(data_path, expected, root):
        raise CoverageError("coverage-counts-do-not-match-measurement")
    if source_snapshot(root) != snapshot or git_identity(root) != identity:
        raise CoverageError("source-changed-during-check")
    if digest(data_path) != data_digest:
        raise CoverageError("coverage-data-changed-during-check")
    calculated = gates(files)
    if any(
        json.dumps(report.get(key), sort_keys=True) != json.dumps(value, sort_keys=True)
        for key, value in calculated.items()
    ):
        raise CoverageError("inconsistent-derived-gates")
    if (
        type(report.get("pytest_exit_code")) is not int
        or report["pytest_exit_code"] != 0
    ):
        raise CoverageError("regression-run-did-not-pass")
    validate_test_summary(report["test_summary"])
    if report["test_summary"]["errors"] or report["test_summary"]["failures"]:
        raise CoverageError("regression-run-did-not-pass")
    return (
        calculated["master_branch_acceptance"]
        and calculated["ordinary_combined_gate"]["passed"]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    collect_parser = commands.add_parser("collect")
    collect_parser.add_argument("--output", type=Path, required=True)
    collect_parser.add_argument(
        "--development",
        action="store_true",
        help="Allow development diagnostics; never grants master acceptance",
    )
    collect_parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    check_parser = commands.add_parser("check")
    check_parser.add_argument("--report", type=Path, required=True)
    check_parser.add_argument(
        "--data", type=Path, help="Defaults to coverage-data.sqlite beside report.json"
    )
    args = parser.parse_args()
    try:
        if args.command == "collect":
            test_args = args.pytest_args
            if test_args[:1] == ["--"]:
                test_args = test_args[1:]
            return collect(
                args.output,
                test_args or ["backend/tests"],
                development=args.development,
            )
        passed = check_report(
            read_json(args.report),
            args.data or args.report.parent / "coverage-data.sqlite",
        )
        print("M9 branch acceptance: " + ("PASS" if passed else "FAIL"))
        return 0 if passed else 1
    except (
        CoverageError,
        CoverageException,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        ET.ParseError,
        subprocess.SubprocessError,
    ) as exc:
        # Avoid copying source, environment, exceptions from decoders, or local
        # absolute paths to a report/log error message.
        code = str(exc) if isinstance(exc, CoverageError) else type(exc).__name__
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
