"""Coverage acceptance fails closed independently of ordinary regression status."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import coverage
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "backend_coverage", ROOT / "scripts/backend_coverage.py"
)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def sample_counts(covered: int = 19, total: int = 20) -> dict[str, int]:
    return {
        "num_statements": 10,
        "covered_lines": 10,
        "missing_lines": 0,
        "num_branches": total,
        "covered_branches": covered,
        "missing_branches": total - covered,
    }


@pytest.mark.parametrize(
    "covered,total,target,expected",
    [
        (899_999, 1_000_000, 90, False),
        (900_000, 1_000_000, 90, True),
        (949_999, 1_000_000, 95, False),
        (950_000, 1_000_000, 95, True),
        (0, 0, 95, False),
        (1, 1, 95, True),
    ],
)
def test_thresholds_use_exact_integers(covered, total, target, expected):
    assert runner.reaches(covered, total, target) is expected


@pytest.mark.parametrize("value", [True, -1, 1.5, "19", None])
def test_invalid_count_types_fail(value):
    item = sample_counts()
    item["covered_branches"] = value
    with pytest.raises(runner.CoverageError, match="invalid-counts"):
        runner.counts(item)


def test_inconsistent_counts_fail():
    item = sample_counts()
    item["missing_branches"] = 0
    with pytest.raises(runner.CoverageError, match="inconsistent-counts"):
        runner.counts(item)


def test_combined_pass_cannot_replace_overall_or_each_critical_branch_gate(monkeypatch):
    monkeypatch.setattr(runner, "CRITICAL", {"critical.py": "security"})
    files = {"critical.py": sample_counts(18), "other.py": sample_counts(20)}
    result = runner.gates(files)
    assert result["ordinary_combined_gate"]["passed"] is True
    assert result["overall_branch_gate"]["passed"] is True
    assert result["critical_branch_gates"]["critical.py"]["passed"] is False
    assert result["master_branch_acceptance"] is False
    files["other.py"] = sample_counts(10)
    assert runner.gates(files)["overall_branch_gate"]["passed"] is False


def test_missing_or_zero_branch_critical_files_fail(monkeypatch):
    monkeypatch.setattr(runner, "CRITICAL", {"critical.py": "security"})
    with pytest.raises(runner.CoverageError, match="missing-critical"):
        runner.gates({"other.py": sample_counts()})
    with pytest.raises(runner.CoverageError, match="critical-file-has-no-branches"):
        runner.gates({"critical.py": sample_counts(0, 0), "other.py": sample_counts()})


def test_declared_policy_includes_mixed_authorization_and_publication_boundaries():
    for name in (
        "api",
        "operations_api",
        "binary_api",
        "provider_api",
        "github_api",
        "service",
        "provider_service",
        "provider_jobs",
        "github_publication_service",
        "image_worker",
        "performance",
        "performance_numeric",
        "schemas",
    ):
        assert f"{runner.PACKAGE}/{name}.py" in runner.CRITICAL
    assert runner.OVERALL_TARGET == 90
    assert runner.CRITICAL_TARGET == 95
    assert runner.COMBINED_TARGET == 75


def test_paths_require_exact_allowlisted_root_and_matching_bytes(tmp_path):
    original = tmp_path / "original"
    installed = tmp_path / "installed"
    foreign = tmp_path / "foreign"
    for root in (original, installed, foreign):
        root.mkdir()
        (root / "sample.py").write_text("value = 1\n")
    inventory = runner.python_inventory(original)
    roots = [original, installed]
    assert (
        runner.canonical_path(str(installed / "sample.py"), roots, inventory)
        == f"{runner.PACKAGE}/sample.py"
    )
    with pytest.raises(runner.CoverageError, match="foreign-measured-path"):
        runner.canonical_path(str(foreign / "sample.py"), roots, inventory)
    (installed / "sample.py").write_text("value = 2\n")
    with pytest.raises(runner.CoverageError, match="changed-or-foreign"):
        runner.canonical_path(str(installed / "sample.py"), roots, inventory)
    with pytest.raises(runner.CoverageError, match="noncanonical"):
        runner.canonical_path("sample.py", roots, inventory)


def test_symlink_inventory_is_rejected(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    target = tmp_path / "outside.py"
    target.write_text("value = 1\n")
    (root / "sample.py").symlink_to(target)
    with pytest.raises(runner.CoverageError, match="symlink-in-source-inventory"):
        runner.python_inventory(root)


@pytest.mark.parametrize("mode", ["missing", "nonbranch", "foreign"])
def test_missing_nonbranch_or_foreign_shards_fail(tmp_path, mode):
    root = tmp_path / "repo"
    package = root / runner.PACKAGE
    package.mkdir(parents=True)
    sample = package / "sample.py"
    sample.write_text("value = 1\n")
    output = tmp_path / "report"
    output.mkdir()
    if mode != "missing":
        data = coverage.CoverageData(basename=str(output / ".coverage.synthetic"))
        if mode == "nonbranch":
            data.add_lines({str(sample): [1]})
        else:
            foreign = tmp_path / "sample.py"
            foreign.write_bytes(sample.read_bytes())
            data.add_arcs({str(foreign): [(-1, 1), (1, -1)]})
        data.write()
    with pytest.raises(
        runner.CoverageError,
        match={
            "missing": "missing-coverage",
            "nonbranch": "nonbranch",
            "foreign": "foreign-measured",
        }[mode],
    ):
        runner.combine_fresh_shards(
            output, [package], runner.python_inventory(package), root
        )


def raw_measurement(name: str) -> dict:
    summary = {
        "num_statements": 2,
        "covered_lines": 1,
        "missing_lines": 1,
        "num_branches": 2,
        "covered_branches": 1,
        "missing_branches": 1,
    }
    return {
        "meta": {"branch_coverage": True},
        "totals": summary,
        "files": {
            name: {
                "summary": dict(summary),
                "executed_lines": [1],
                "missing_lines": [2],
                "executed_branches": [[1, 2]],
                "missing_branches": [[1, 3]],
            }
        },
    }


@pytest.mark.parametrize(
    "failure",
    [
        "nonbranch",
        "meta_list",
        "missing",
        "foreign",
        "bad_total",
        "bad_details",
        "overlap",
        "bad_arc",
    ],
)
def test_upstream_json_rejects_incomplete_or_malformed_data(tmp_path, failure):
    name = f"{runner.PACKAGE}/sample.py"
    raw = raw_measurement(name)
    if failure == "nonbranch":
        raw["meta"]["branch_coverage"] = False
    elif failure == "meta_list":
        raw["meta"] = []
    elif failure == "missing":
        raw["files"] = {}
    elif failure == "foreign":
        raw["files"]["elsewhere.py"] = raw["files"].pop(name)
    elif failure == "bad_total":
        raw["totals"] = sample_counts()
    elif failure == "bad_details":
        raw["files"][name]["executed_branches"] = []
    elif failure == "overlap":
        raw["files"][name]["missing_branches"] = [[1, 2]]
    elif failure == "bad_arc":
        raw["files"][name]["executed_branches"] = [[True, 2]]
    with pytest.raises(runner.CoverageError):
        runner.validate_raw(raw, {name}, tmp_path)


@pytest.fixture
def miniature(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    package = root / runner.PACKAGE
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "sample.py").write_text(
        "def choose(flag):\n    if flag:\n        return 1\n    return 2\n"
    )
    tests = root / "backend/tests"
    tests.mkdir()
    (tests / "test_probe.py").write_text(
        "import subprocess, sys\nfrom failurelens.sample import choose\n"
        "def test_parent_and_inherited_child():\n"
        "    assert choose(True) == 1\n"
        "    subprocess.run([sys.executable, '-c', 'from failurelens.sample import choose; assert choose(False) == 2'], check=True)\n"
    )
    snapshot = lambda current: {
        f"{runner.PACKAGE}/{name}": value
        for name, value in runner.python_inventory(current / runner.PACKAGE).items()
    }
    monkeypatch.setattr(runner, "source_snapshot", snapshot)
    monkeypatch.setattr(
        runner,
        "git_identity",
        lambda current: {"revision": "synthetic-revision", "working_tree_clean": True},
    )
    monkeypatch.setattr(runner, "verify_committed_source", lambda *args: None)
    monkeypatch.setattr(
        runner, "CRITICAL", {f"{runner.PACKAGE}/sample.py": "synthetic-critical"}
    )
    monkeypatch.setattr(
        runner.importlib.util,
        "find_spec",
        lambda name: SimpleNamespace(origin=str(package / "__init__.py")),
    )
    monkeypatch.setenv("PYTHONPATH", str(package.parent))
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    return root, package, tmp_path / "measurement"


def test_fresh_collector_measures_real_inherited_child_and_preserves_ordinary_gate(
    miniature,
):
    root, _package, output = miniature
    assert runner.collect(output, ["backend/tests"], root) == 0
    report = runner.read_json(output / "report.json")
    assert report["files"][f"{runner.PACKAGE}/sample.py"]["covered_branches"] == 2
    assert report["test_summary"] == {
        "tests": 1,
        "passed": 1,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "postgresql_only_skips": 0,
    }
    assert report["master_branch_acceptance"] is True
    assert runner.check_report(report, output / "coverage-data.sqlite", root) is True
    assert not (output / "test-outcomes.xml").exists()
    with pytest.raises(FileExistsError):
        runner.collect(output, ["backend/tests"], root)


@pytest.mark.parametrize(
    "termination,expected_exit,expected_signal",
    [
        ("os._exit(7)", 7, None),
        ("os.kill(os.getpid(), signal.SIGKILL)", -9, 9),
    ],
)
def test_abrupt_test_child_retains_exit_without_granting_acceptance(
    miniature, termination, expected_exit, expected_signal
):
    root, _package, output = miniature
    (root / "backend/tests/test_probe.py").write_text(
        "import os, signal\ndef test_abrupt_exit():\n    " + termination + "\n"
    )
    with pytest.raises(
        runner.CoverageError, match="missing-or-oversized-test-outcomes"
    ):
        runner.collect(output, ["backend/tests"], root)
    execution = runner.read_json(output / "test-execution.json")
    assert execution["pytest_exit_code"] == expected_exit
    assert execution["termination_signal"] == expected_signal
    assert execution["outcome_file_present"] is False
    assert execution["scope"] == "pytest_process_observation_not_acceptance"
    assert execution["source_revision_at_start"] == "synthetic-revision"
    assert execution["elapsed_seconds"] >= 0
    assert not (output / "report.json").exists()
    assert not (output / "coverage-data.sqlite").exists()


@pytest.mark.parametrize(
    "contents,expected",
    [
        ("oom_kill 8\n", 8),
        ("other 8\n", None),
        ("oom_kill bad\n", None),
        ("oom_kill -1\n", None),
    ],
)
def test_host_oom_diagnostic_accepts_only_a_nonnegative_counter(
    monkeypatch, contents, expected
):
    monkeypatch.setattr(runner.Path, "read_text", lambda _: contents)
    assert runner.host_oom_kills() == expected


def test_unavailable_host_oom_diagnostic_does_not_mask_test_outcome(monkeypatch):
    def unavailable(_):
        raise PermissionError("synthetic unavailable host diagnostic")

    monkeypatch.setattr(runner.Path, "read_text", unavailable)
    assert runner.host_oom_kills() is None


def test_collector_refuses_installed_source_mismatch(miniature, monkeypatch, tmp_path):
    root, _package, output = miniature
    installed = tmp_path / "installed"
    installed.mkdir()
    (installed / "__init__.py").write_text("")
    (installed / "sample.py").write_text("mutated = True\n")
    monkeypatch.setattr(
        runner.importlib.util,
        "find_spec",
        lambda name: SimpleNamespace(origin=str(installed / "__init__.py")),
    )
    with pytest.raises(runner.CoverageError, match="installed-package-source-mismatch"):
        runner.collect(output, ["backend/tests"], root)


def test_collector_rejects_dangling_output_symlink_before_creating_target(
    miniature, tmp_path
):
    root, _package, output = miniature
    alias = tmp_path / "fresh-output-alias"
    alias.symlink_to(output, target_is_directory=True)
    assert alias.is_symlink() and not alias.exists()
    with pytest.raises(runner.CoverageError, match="symlink-output-directory"):
        runner.collect(alias, ["backend/tests"], root)
    assert alias.is_symlink()
    assert not output.exists()


def test_identical_installed_package_is_canonicalized_without_double_counting(
    miniature, monkeypatch, tmp_path
):
    root, package, output = miniature
    installed = tmp_path / "site-packages/failurelens"
    installed.mkdir(parents=True)
    for source in package.glob("*.py"):
        (installed / source.name).write_bytes(source.read_bytes())
    monkeypatch.setattr(
        runner.importlib.util,
        "find_spec",
        lambda name: SimpleNamespace(origin=str(installed / "__init__.py")),
    )
    monkeypatch.setenv("PYTHONPATH", str(installed.parent))
    assert runner.collect(output, ["backend/tests"], root) == 0
    report = runner.read_json(output / "report.json")
    assert (
        report["overall"]["num_branches"] == report["overall"]["covered_branches"] == 2
    )
    data_path = output / "coverage-data.sqlite"
    data = coverage.CoverageData(basename=str(data_path))
    data.read()
    assert set(data.measured_files()) == {
        f"{runner.PACKAGE}/__init__.py",
        f"{runner.PACKAGE}/sample.py",
    }
    assert runner.check_report(report, data_path, root) is True


def test_real_branch_shortfall_does_not_fail_ordinary_combined_gate(miniature):
    root, package, output = miniature
    (package / "sample.py").write_text(
        "def choose(flag):\n    value = 2\n    if flag:\n        value = 1\n    return value\n"
    )
    (root / "backend/tests/test_probe.py").write_text(
        "from failurelens.sample import choose\ndef test_parent_only():\n    assert choose(True) == 1\n"
    )
    assert runner.collect(output, ["backend/tests"], root) == 0
    report = runner.read_json(output / "report.json")
    assert report["ordinary_combined_gate"]["passed"] is True
    assert report["overall_branch_gate"]["passed"] is False
    assert runner.check_report(report, output / "coverage-data.sqlite", root) is False


def test_collector_refuses_source_changes_during_test_execution(miniature):
    root, package, output = miniature
    test = root / "backend/tests/test_probe.py"
    test.write_text(
        test.read_text()
        + f"    from pathlib import Path\n    Path({str(package / 'sample.py')!r}).write_text('changed = True\\n')\n"
    )
    with pytest.raises(runner.CoverageError, match="source-changed-during-measurement"):
        runner.collect(output, ["backend/tests"], root)
    assert not (output / "report.json").exists()


@pytest.fixture
def collected_report(miniature):
    root, package, output = miniature
    assert runner.collect(output, ["backend/tests"], root) == 0
    return (
        root,
        package,
        output / "coverage-data.sqlite",
        runner.read_json(output / "report.json"),
    )


@pytest.mark.parametrize(
    "failure",
    [
        "stale",
        "nonbranch",
        "missing_file",
        "bad_counts",
        "denominator",
        "float_gate",
        "extra_source",
        "failed_pytest",
        "bad_outcomes",
        "covered_counts",
        "dirty_report",
        "data_digest",
    ],
)
def test_report_checker_rejects_stale_or_invalid_reports(collected_report, failure):
    root, package, data_path, original = collected_report
    report = copy.deepcopy(original)
    name = f"{runner.PACKAGE}/sample.py"
    if failure == "stale":
        (package / "sample.py").write_text("changed = True\n")
    elif failure == "nonbranch":
        report["branch_coverage"] = False
    elif failure == "missing_file":
        del report["files"][name]
    elif failure == "bad_counts":
        report["files"][name]["covered_branches"] = True
    elif failure == "denominator":
        report["files"][name]["num_branches"] = 1
        report["files"][name]["covered_branches"] = 1
        report.update(runner.gates(report["files"]))
    elif failure == "float_gate":
        report["overall_branch_gate"]["target_percent"] = 90.0
    elif failure == "extra_source":
        report["source_text"] = "not an allowed report field"
    elif failure == "failed_pytest":
        report["pytest_exit_code"] = 1
    elif failure == "bad_outcomes":
        report["test_summary"]["skipped"] = 2
    elif failure == "covered_counts":
        report["files"][name]["covered_branches"] = 1
        report["files"][name]["missing_branches"] = 1
        report.update(runner.gates(report["files"]))
    elif failure == "dirty_report":
        report["source"]["working_tree_clean"] = False
    elif failure == "data_digest":
        report["coverage_data_sha256"] = "incorrect"
    with pytest.raises(runner.CoverageError):
        runner.check_report(report, data_path, root)


def test_development_collection_never_grants_acceptance(miniature, monkeypatch):
    root, _package, output = miniature
    monkeypatch.setattr(
        runner,
        "git_identity",
        lambda current: {"revision": "synthetic-revision", "working_tree_clean": False},
    )
    assert runner.collect(output, ["backend/tests"], root, development=True) == 0
    report = runner.read_json(output / "report.json")
    assert report["overall_branch_gate"]["passed"] is True
    assert report["master_branch_acceptance"] is False
    with pytest.raises(runner.CoverageError, match="development-report-not-acceptance"):
        runner.check_report(report, output / "coverage-data.sqlite", root)


def test_report_check_never_touches_unrelated_default_coverage(
    collected_report, tmp_path, monkeypatch
):
    root, _package, data_path, report = collected_report
    unrelated = tmp_path / ".coverage"
    unrelated.write_bytes(b"unrelated historical measurement")
    monkeypatch.chdir(tmp_path)
    assert runner.check_report(report, data_path, root) is True
    assert unrelated.read_bytes() == b"unrelated historical measurement"


def test_modified_or_foreign_retained_data_is_rejected(collected_report):
    root, _package, data_path, report = collected_report
    original = data_path.read_bytes()
    data_path.write_bytes(original + b"changed")
    with pytest.raises(runner.CoverageError, match="coverage-data-digest-mismatch"):
        runner.check_report(report, data_path, root)
    data_path.write_bytes(original)
    data = coverage.CoverageData(basename=str(data_path))
    data.read()
    data.add_arcs({"copied-or-mutated/sample.py": [(-1, 1), (1, -1)]})
    data.write()
    report["coverage_data_sha256"] = runner.digest(data_path)
    with pytest.raises(runner.CoverageError, match="foreign-coverage-data-paths"):
        runner.check_report(report, data_path, root)


def test_new_runtime_namespace_cannot_silently_escape_overall_scope(tmp_path):
    extra = tmp_path / "backend/src/another_package/module.py"
    extra.parent.mkdir(parents=True)
    extra.write_text("value = 1\n")
    with pytest.raises(
        runner.CoverageError, match="undeclared-backend-runtime-package"
    ):
        runner.source_snapshot(tmp_path)


@pytest.mark.parametrize("failure", ["dirty", "ignored_extra", "changed_bytes"])
def test_committed_provenance_rejects_untracked_ignored_and_changed_source(
    tmp_path, monkeypatch, failure
):
    name = f"{runner.PACKAGE}/sample.py"
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_text("value = 1\n")
    snapshot = {name: runner.digest(path)}
    listed = name.encode() + b"\0"
    if failure == "ignored_extra":
        snapshot[f"{runner.PACKAGE}/ignored_extra.py"] = "unexpected-source"
    identity = {
        "revision": "synthetic-revision",
        "working_tree_clean": failure != "dirty",
    }
    monkeypatch.setattr(
        runner.subprocess, "check_output", lambda *args, **kwargs: listed
    )
    content = b"value = 2\n"
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=b"synthetic blob "
            + str(len(content)).encode()
            + b"\n"
            + content
            + b"\n"
        ),
    )
    with pytest.raises(
        runner.CoverageError,
        match={
            "dirty": "uncommitted-source-measurement",
            "ignored_extra": "uncommitted-source-inventory",
            "changed_bytes": "committed-source-byte-mismatch",
        }[failure],
    ):
        runner.verify_committed_source(tmp_path, snapshot, identity)


def test_committed_provenance_compares_actual_blob_bytes(tmp_path, monkeypatch):
    name = f"{runner.PACKAGE}/sample.py"
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_text("value = 1\n")
    snapshot = {name: runner.digest(path)}
    monkeypatch.setattr(
        runner.subprocess, "check_output", lambda *args, **kwargs: name.encode() + b"\0"
    )
    content = path.read_bytes()
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=b"synthetic blob "
            + str(len(content)).encode()
            + b"\n"
            + content
            + b"\n"
        ),
    )
    runner.verify_committed_source(
        tmp_path,
        snapshot,
        {"revision": "synthetic-revision", "working_tree_clean": True},
    )


def test_duplicate_json_keys_are_rejected(tmp_path):
    path = tmp_path / "report.json"
    path.write_text('{"branch_coverage": false, "branch_coverage": true}')
    with pytest.raises(runner.CoverageError, match="duplicate-json-key"):
        runner.read_json(path)


def test_test_outcomes_retain_postgresql_skips_without_skip_text(tmp_path):
    path = tmp_path / "outcomes.xml"
    path.write_text(
        '<testsuites><testsuite tests="2" failures="0" errors="0" skipped="1"><testcase/><testcase><skipped message="a real PostgreSQL FAILURELENS_DATABASE_URL is required"/></testcase></testsuite></testsuites>'
    )
    summary = runner.test_summary(path)
    assert (
        summary["passed"] == summary["skipped"] == summary["postgresql_only_skips"] == 1
    )
    assert "FAILURELENS_DATABASE_URL" not in json.dumps(summary)
