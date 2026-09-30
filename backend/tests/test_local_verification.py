"""Local verifier boundaries exercised without audits or a recursive full suite."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "local_verify", REPO / "scripts/local_verify.py"
)
assert SPEC is not None and SPEC.loader is not None
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


def executable(path: Path, code: str) -> Path:
    path.write_text(f"#!{sys.executable}\n" + code)
    path.chmod(0o700)
    return path


@pytest.fixture
def runner(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    monkeypatch.setattr(verify, "ROOT", root)
    output = verify.fresh_output(tmp_path / "output")
    work = tmp_path / "work"
    work.mkdir()
    env = verify.child_environment(work, sys.executable)
    return verify.Verification(output, work, env)


@pytest.mark.parametrize("kind", ["existing", "inside", "symlink"])
def test_output_refuses_overwrite_and_checkout_aliases(tmp_path, monkeypatch, kind):
    root = tmp_path / "source"
    root.mkdir()
    monkeypatch.setattr(verify, "ROOT", root)
    preserved = root / "historical.json"
    preserved.write_bytes(b"historical bytes")
    if kind == "existing":
        target = tmp_path / "existing"
        target.mkdir()
    elif kind == "inside":
        target = root / "fresh"
    else:
        alias = tmp_path / "alias"
        alias.symlink_to(root, target_is_directory=True)
        target = alias / "fresh"
    with pytest.raises((ValueError, FileExistsError)):
        verify.fresh_output(target)
    assert preserved.read_bytes() == b"historical bytes"
    assert not (root / "fresh").exists()


def test_real_child_cannot_inherit_production_settings_or_startup_hooks(
    tmp_path, monkeypatch
):
    work = tmp_path / "owned work"
    work.mkdir()
    forbidden = (
        "FAILURELENS_PROVIDER_TOKEN",
        "FAILURELENS_TELEMETRY_ENDPOINT",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "PYTHONSTARTUP",
        "NODE_OPTIONS",
        "GITHUB_TOKEN",
        "AWS_PROFILE",
        "PGHOST",
        "PYTEST_PLUGINS",
        "OTEL_SDK_DISABLED",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_HEADERS",
        "OTEL_TRACES_EXPORTER",
    )
    for name in forbidden:
        monkeypatch.setenv(name, "parent-only-canary")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    monkeypatch.setenv("FAILURELENS_DATABASE_URL", "parent-only-canary")
    monkeypatch.setenv("FAILURELENS_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("FAILURELENS_TELEMETRY_EXPORT_ENABLED", "true")
    env = verify.child_environment(work, sys.executable)
    probe = """import json, os
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
with provider.get_tracer('local-verifier-probe').start_as_current_span('local-only'):
    pass
spans = [span.name for span in exporter.get_finished_spans()]
provider.shutdown()
print(json.dumps({'env': dict(os.environ), 'cwd': os.getcwd(), 'spans': spans}))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=work,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    actual = json.loads(result.stdout)
    assert all(name not in actual["env"] for name in forbidden)
    assert "parent-only-canary" not in result.stdout
    assert actual["env"]["FAILURELENS_DATABASE_URL"] == "sqlite+pysqlite:///:memory:"
    assert actual["env"]["FAILURELENS_PROVIDER_ENABLED"] == "false"
    assert actual["env"]["FAILURELENS_TELEMETRY_EXPORT_ENABLED"] == "false"
    assert actual["env"]["NPM_CONFIG_OFFLINE"] == "true"
    assert actual["cwd"] == str(work)
    assert actual["spans"] == ["local-only"]


@pytest.mark.parametrize("fail_downgrade", [False, True])
def test_migration_owns_its_database_and_stops_on_failure(
    runner, tmp_path, fail_downgrade
):
    backend = verify.ROOT / "backend"
    backend.mkdir()
    shutil.copyfile(REPO / "backend/alembic.ini", backend / "alembic.ini")
    sentinel = backend / "verify-migration.db"
    sentinel.write_bytes(b"existing database must survive")
    fake_python = executable(
        tmp_path / "migration-python",
        f"""
import json, os, pathlib, sys
assert sys.argv[1:3] == ['-m', 'alembic']
database = pathlib.Path(os.environ['FAILURELENS_DATABASE_URL'].removeprefix('sqlite+pysqlite:///'))
assert database.parent == pathlib.Path.cwd()
assert not pathlib.Path('.env').exists()
database.write_bytes(b'owned migration fixture')
with pathlib.Path('calls.jsonl').open('a') as stream:
    stream.write(json.dumps(sys.argv[-2:]) + '\\n')
raise SystemExit(17 if {fail_downgrade!r} and sys.argv[-2] == 'downgrade' else 0)
""",
    )
    runner.migration(str(fake_python))
    calls = [
        json.loads(line)
        for line in (runner.work / "calls.jsonl").read_text().splitlines()
    ]
    assert calls == [["upgrade", "head"], ["downgrade", "c7a9e2f4b610"]] + (
        [] if fail_downgrade else [["upgrade", "head"]]
    )
    assert sentinel.read_bytes() == b"existing database must survive"
    assert runner.results[-1]["status"] == ("FAILED" if fail_downgrade else "PASSED")
    assert runner.results[-1]["exit_codes"] == (
        [0, 17] if fail_downgrade else [0, 0, 0]
    )


def test_failed_command_and_missing_executable_are_not_passes(runner):
    marker = runner.work / "must-not-run"
    result = runner.run(
        "fails",
        "regression",
        [
            [sys.executable, "-c", "raise SystemExit(23)"],
            [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"],
        ],
    )
    assert result["status"] == "FAILED" and result["exit_codes"] == [23]
    assert not marker.exists()
    result = runner.run(
        "missing", "regression", [[str(runner.work / "absent-executable")]]
    )
    assert result["status"] == "NOT RUN"
    assert verify.group_status(runner.results, "regression") == "FAILED"


def test_missing_frozen_inputs_prevents_test_regeneration(runner, tmp_path):
    producers = tmp_path / "producers"
    producers.mkdir()
    (producers / "provenance.json").write_text("{}")
    runner.backend(str(tmp_path / "must-not-execute"), producers)
    assert runner.results[0]["status"] == "NOT RUN"
    assert "cases.jsonl" in runner.results[0]["missing_frozen_inputs"]
    assert not (verify.ROOT / "evaluation/corpus").exists()


def test_provenance_digest_includes_ignored_frozen_inputs_and_reports(
    runner, monkeypatch
):
    ordinary = verify.ROOT / "tracked.py"
    ordinary.write_text("VERSION = 1\n")
    frozen = verify.ROOT / "evaluation/corpus/cases.jsonl"
    frozen.parent.mkdir(parents=True)
    frozen.write_bytes(b"frozen input")
    retained = verify.ROOT / "evaluation/reports/latest/report.json"
    retained.parent.mkdir(parents=True)
    retained.write_bytes(b"retained output")

    def git(command, **kwargs):
        args = command[3:]
        if args[0] == "ls-files":
            value = b"tracked.py\0"
        elif args[0] == "rev-parse":
            value = b"source-revision\n"
        else:
            assert args[0] == "status"
            value = b""
        return subprocess.CompletedProcess(command, 0, stdout=value)

    monkeypatch.setattr(verify.subprocess, "run", git)
    first = verify.source_state(runner.env)
    assert first["worktree_clean"] is True and first["source_file_count"] == 3
    frozen.write_bytes(b"changed input")
    second = verify.source_state(runner.env)
    retained.write_bytes(b"changed retained report")
    third = verify.source_state(runner.env)
    assert len({state["source_digest"] for state in (first, second, third)}) == 3


def test_evaluation_reads_frozen_inputs_and_writes_only_fresh_outputs(runner):
    corpus = verify.ROOT / "evaluation/corpus"
    corpus.mkdir(parents=True)
    retained = verify.ROOT / "evaluation/reports/latest"
    retained.mkdir(parents=True)
    (retained / "report.json").write_bytes(b"historical bytes")
    for _, script, inputs, _ in verify.LEGACY:
        for name in inputs:
            (corpus / name).write_bytes(b"frozen bytes")
        (verify.ROOT / "evaluation" / f"{script}.py").write_text(
            "import pathlib, sys\np = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])\np.mkdir(parents=True)\n(p / 'report.json').write_text('new result')\n"
        )
    before = {path: path.read_bytes() for path in corpus.iterdir()}
    runner.evaluations(sys.executable)
    assert all(result["status"] == "PASSED" for result in runner.results)
    assert {path: path.read_bytes() for path in corpus.iterdir()} == before
    assert (retained / "report.json").read_bytes() == b"historical bytes"
    assert len(list((runner.output / "legacy").rglob("report.json"))) == 5


def test_offline_quality_runs_current_gates_but_never_an_audit(runner):
    scripts = verify.ROOT / "scripts"
    scripts.mkdir()
    (scripts / "quality_checks.py").write_text("""import json, pathlib, sys
check = sys.argv[1]
assert 'audit' not in check
p = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])
p.parent.mkdir(exist_ok=True)
p.write_text(json.dumps({'check': check, 'status': 'pass'}))
""")
    runner.quality(sys.executable, sys.executable)
    assert {path.stem for path in (runner.output / "quality").glob("*.json")} == {
        "locks",
        "lint",
        "format",
        "types",
        "secrets",
        "workflows",
    }
    audits = [result for result in runner.results if "audit" in result["name"]]
    assert len(audits) == 2 and all(result["status"] == "NOT RUN" for result in audits)
    assert verify.group_status(runner.results, "quality-security") == "NOT RUN"


def test_frontend_uses_local_dependencies_without_mutating_the_checkout(
    runner, tmp_path
):
    source = verify.ROOT / "frontend"
    for relative in (
        "typescript/bin/tsc",
        "vite/bin/vite.js",
        "vitest/vitest.mjs",
        "vite/dist/node/cli.js",
    ):
        path = source / "node_modules" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("installed dependency fixture")
    (source / "node_modules/.bin").mkdir()
    (source / "node_modules/.bin/vite").symlink_to(
        source / "node_modules/vite/bin/vite.js"
    )
    (source / ".env.local").write_text("parent-only-canary")
    (source / ".npmrc").write_text("parent-only-canary")
    (source / "dist").mkdir()
    (source / "dist/existing").write_text("preserved build")
    tools = tmp_path / "tools"
    tools.mkdir()
    executable(
        tools / "npm",
        """import os, pathlib, sys
assert sys.argv[1:] in (['run', 'build'], ['test'])
assert os.environ['NPM_CONFIG_OFFLINE'] == 'true'
assert os.environ['NPM_CONFIG_AUDIT'] == 'false'
assert not pathlib.Path('.env.local').exists()
assert not pathlib.Path('.npmrc').exists()
assert pathlib.Path('node_modules/vite/dist/node/cli.js').is_file()
assert pathlib.Path('node_modules/.bin/vite').resolve().is_relative_to(pathlib.Path.cwd())
pathlib.Path('dist').mkdir(exist_ok=True)
pathlib.Path('dist/new').write_text('new build')
pathlib.Path('node_modules/.cache').mkdir(exist_ok=True)
""",
    )
    runner.env["PATH"] = str(tools) + os.pathsep + runner.env["PATH"]
    runner.frontend()
    assert all(result["status"] == "PASSED" for result in runner.results)
    assert not (source / "dist/new").exists()
    assert not (source / "node_modules/.cache").exists()
    assert (source / "dist/existing").read_text() == "preserved build"
    assert (source / ".env.local").read_text() == "parent-only-canary"


def test_unavailable_frontend_is_explicitly_not_run(runner):
    runner.frontend()
    assert {result["name"] for result in runner.results} == {
        "frontend-build",
        "frontend-unit",
    }
    assert all(result["status"] == "NOT RUN" for result in runner.results)


def test_real_installed_npm_runs_a_disposable_offline_package_script(runner):
    npm = shutil.which("npm", path=runner.env["PATH"])
    if npm is None:
        pytest.skip(
            "real installed npm is required for this offline configuration regression"
        )
    package = runner.work / "disposable-package"
    package.mkdir()
    (package / "package.json").write_text(
        json.dumps(
            {
                "name": "local-verification-probe",
                "private": True,
                "scripts": {"verify-local": "node probe.cjs"},
            }
        )
    )
    (package / "probe.cjs").write_text("""const fs = require('node:fs');
if (process.env.NPM_CONFIG_OFFLINE !== 'true') throw new Error('offline required');
if (process.env.NPM_CONFIG_AUDIT !== 'false') throw new Error('audit must be disabled');
fs.writeFileSync('verified.txt', 'local script executed');
""")
    result = runner.run(
        "real-npm-script", "regression", [[npm, "run", "verify-local"]], cwd=package
    )
    assert result["status"] == "PASSED", (runner.output / result["log"]).read_text()
    assert (package / "verified.txt").read_text() == "local script executed"
    assert not (package / "node_modules").exists()
    assert not (package / "package-lock.json").exists()
    user_config = Path(runner.env["NPM_CONFIG_USERCONFIG"])
    global_config = Path(runner.env["NPM_CONFIG_GLOBALCONFIG"])
    assert user_config != global_config
    assert user_config.parent == global_config.parent == runner.work
    assert user_config.read_bytes() == global_config.read_bytes() == b""


@pytest.mark.parametrize("option", ["--app-python", "--quality-python"])
@pytest.mark.parametrize("style", ["relative", "bare"])
def test_relative_interpreter_options_execute_from_original_directory(
    tmp_path, monkeypatch, option, style
):
    invocation = tmp_path / "invocation"
    tools = invocation / "tools"
    tools.mkdir(parents=True)
    source = tmp_path / "source"
    source.mkdir()
    observed = tmp_path / "observed.json"
    executable_path = executable(
        tmp_path / "real-python-probe",
        f"""import json, os, pathlib, sys
pathlib.Path({str(observed)!r}).write_text(json.dumps({{'program': sys.argv[0], 'cwd': str(pathlib.Path.cwd()), 'path': os.environ['PATH']}}))
""",
    )
    # Keep the environment's chosen interpreter path, including a venv-style
    # symlink, rather than resolving it to another interpreter location.
    selected = tools / "python-probe"
    selected.symlink_to(executable_path)
    monkeypatch.chdir(invocation)
    monkeypatch.setenv(
        "PATH", str(tools) + os.pathsep + os.environ.get("PATH", os.defpath)
    )
    monkeypatch.setattr(verify, "ROOT", source)
    monkeypatch.setattr(
        verify,
        "source_state",
        lambda env: {"worktree_clean": True, "source_digest": "unchanged"},
    )
    for name in ("backend", "migration", "evaluations", "frontend", "quality"):
        monkeypatch.setattr(verify.Verification, name, lambda self, *args: None)

    def probe(self, python, *args):
        self.run("interpreter-probe", "regression", [[python, "probe"]])

    monkeypatch.setattr(
        verify.Verification,
        "migration" if option == "--app-python" else "quality",
        probe,
    )
    output = tmp_path / "output"
    command = "tools/python-probe" if style == "relative" else "python-probe"
    assert verify.main(["verify", option, command, "--output", str(output)]) == 1
    report = json.loads((output / "summary.json").read_text())
    assert report["local_regressions"] == "PASSED"
    actual = json.loads(observed.read_text())
    assert actual["program"] == str(selected)
    assert Path(actual["cwd"]).is_relative_to(output)
    assert actual["path"] == os.environ["PATH"]


def test_successful_local_checks_do_not_satisfy_skipped_security_acceptance(
    tmp_path, monkeypatch
):
    root = tmp_path / "source"
    root.mkdir()
    monkeypatch.setattr(verify, "ROOT", root)
    monkeypatch.setattr(
        verify,
        "source_state",
        lambda env: {
            "revision": "test-fixture",
            "worktree_clean": True,
            "source_digest": "unchanged",
        },
    )
    for method in ("backend", "migration", "evaluations", "frontend"):
        monkeypatch.setattr(
            verify.Verification,
            method,
            lambda self, *args: self.record(
                "synthetic-regression", "regression", "PASSED"
            ),
        )

    def quality(self, *args):
        self.record("offline-quality", "quality-security", "PASSED")
        self.record(
            "quality-npm-audit",
            "quality-security",
            "NOT RUN",
            reason="approval-required",
        )

    monkeypatch.setattr(verify.Verification, "quality", quality)
    output = tmp_path / "output"
    assert verify.main(["verify", "--output", str(output)]) == 1
    summary = json.loads((output / "summary.json").read_text())
    assert summary["local_regressions"] == "PASSED"
    assert summary["quality_security_acceptance"] == "FAILED"
    assert summary["full_project_acceptance"] == "NOT RUN"
    assert not list(output.glob("work-*"))


def test_make_security_target_includes_delivered_boundaries_and_propagates_failure(
    tmp_path,
):
    shutil.copyfile(REPO / "Makefile", tmp_path / "Makefile")
    fake_python = executable(
        tmp_path / "python-probe",
        "import json, pathlib, sys\npathlib.Path('arguments.json').write_text(json.dumps(sys.argv[1:]))\nraise SystemExit(29)\n",
    )
    result = subprocess.run(
        ["make", "security-test", f"PYTHON={fake_python}"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0 and "29" in result.stderr
    args = json.loads((tmp_path / "arguments.json").read_text())
    tests = set(args[args.index("--tests") + 1 :])
    required = {
        "project_redaction",
        "image_process_boundary",
        "provider_config",
        "provider_credential_echo",
        "provider_output_bounds",
        "provider_workflow",
        "provider_proxy",
        "github_action",
        "github_evidence",
        "github_publication_revisions",
        "github_publication_service",
        "workflow_contexts",
    }
    assert {f"backend/tests/test_{name}.py" for name in required} <= tests
    assert all((REPO / name).is_file() for name in tests)


def test_shell_entrypoint_preserves_arguments_and_child_failure(tmp_path):
    executable_path = executable(
        tmp_path / "python-probe",
        "import json, pathlib, sys\npathlib.Path('arguments.json').write_text(json.dumps(sys.argv[1:]))\nraise SystemExit(31)\n",
    )
    result = subprocess.run(
        [
            "bash",
            str(REPO / "scripts/verify.sh"),
            "--output",
            str(tmp_path / "fresh output"),
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHON": str(executable_path)},
        capture_output=True,
        check=False,
    )
    assert result.returncode == 31
    args = json.loads((tmp_path / "arguments.json").read_text())
    assert args == [
        str(REPO / "scripts/local_verify.py"),
        "verify",
        "--output",
        str(tmp_path / "fresh output"),
    ]
