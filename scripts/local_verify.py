"""Offline local checks with fresh outputs and separate acceptance results."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OFFLINE_GATES = ("locks", "lint", "format", "types", "secrets", "workflows")
LEGACY = (
    ("classification", "harness", ("cases.jsonl",), ("--split", "test")),
    ("clustering", "clustering_harness", ("clustering-cases.jsonl",), ()),
    ("impact", "impact_harness", ("impact-cases.jsonl", "impact-manifest.json"), ()),
    ("performance", "performance_harness", ("performance-cases.jsonl",), ()),
    (
        "infrastructure",
        "infrastructure_harness",
        ("infrastructure-cases.jsonl", "infrastructure-manifest.json"),
        (),
    ),
)


def fresh_output(path: Path | None) -> Path:
    if path is None:
        path = Path(tempfile.mkdtemp(prefix="loose-verify-", dir="/tmp"))
    else:
        path = path.absolute()
        if path.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError("output-must-be-outside-checkout")
        path.mkdir(mode=0o700, parents=True, exist_ok=False)
    if path.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("output-must-be-outside-checkout")
    path.chmod(0o700)
    return path.resolve()


def is_path_command(command: str) -> bool:
    return any(separator and separator in command for separator in (os.sep, os.altsep))


def interpreter_command(command: str, invocation_cwd: Path) -> str:
    # abspath normalizes relative components but preserves venv symlinks.
    return (
        os.path.abspath(invocation_cwd / command)
        if is_path_command(command)
        else command
    )


def child_environment(work: Path, app_python: str) -> dict[str, str]:
    # Keep credentials, database URLs, proxies, tracing and startup hooks out.
    env = {
        key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ
    }
    for name in ("home", "tmp", "cache", "artifacts"):
        (work / name).mkdir(mode=0o700)
    # npm rejects loading the same path for both configuration scopes.
    for name in ("npm-user.conf", "npm-global.conf"):
        (work / name).touch(mode=0o600, exist_ok=False)
    env.update(
        {
            "HOME": str(work / "home"),
            "TMPDIR": str(work / "tmp"),
            "XDG_CACHE_HOME": str(work / "cache"),
            "UV_CACHE_DIR": str(work / "cache/uv"),
            "UV_OFFLINE": "1",
            "PIP_NO_INDEX": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_CONFIG_FILE": os.devnull,
            "NPM_CONFIG_USERCONFIG": str(work / "npm-user.conf"),
            "NPM_CONFIG_GLOBALCONFIG": str(work / "npm-global.conf"),
            "NPM_CONFIG_CACHE": str(work / "cache/npm"),
            "NPM_CONFIG_OFFLINE": "true",
            "NPM_CONFIG_AUDIT": "false",
            "NPM_CONFIG_FUND": "false",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": os.pathsep.join((str(ROOT / "backend/src"), str(ROOT))),
            "PYTEST_ADDOPTS": "-p no:cacheprovider",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "FAILURELENS_DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "FAILURELENS_ARTIFACT_ROOT": str(work / "artifacts"),
            "FAILURELENS_DEMO_MODE": "true",
            "FAILURELENS_PROVIDER_ENABLED": "false",
            "FAILURELENS_TELEMETRY_EXPORT_ENABLED": "false",
            "TZ": "UTC",
        }
    )
    return env


def source_state(env: dict[str, str]) -> dict[str, Any]:
    def git(*args: str) -> bytes:
        return subprocess.run(
            ["git", "-C", str(ROOT), *args],
            env=env,
            capture_output=True,
            check=True,
            timeout=60,
        ).stdout

    names = set(
        filter(
            None,
            git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
            .decode()
            .split("\0"),
        )
    )
    # Include ignored legacy inputs and retained reports too.
    for folder in ("evaluation/corpus", "evaluation/reports"):
        names.update(
            str(path.relative_to(ROOT))
            for path in (ROOT / folder).rglob("*")
            if path.is_file()
        )
    digest = hashlib.sha256()
    for name in sorted(names):
        path = ROOT / name
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(ROOT.resolve())
        ):
            raise ValueError("source-inventory-not-regular")
        digest.update(
            name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest()
        )
    return {
        "revision": git("rev-parse", "HEAD").decode().strip(),
        "worktree_clean": not git(
            "status", "--porcelain", "--untracked-files=normal"
        ).strip(),
        "source_digest": digest.hexdigest(),
        "source_file_count": len(names),
    }


class Verification:
    def __init__(self, output: Path, work: Path, env: dict[str, str]) -> None:
        self.output, self.work, self.env = output, work, env
        self.results: list[dict[str, Any]] = []
        (output / "logs").mkdir(mode=0o700)

    def record(
        self, name: str, group: str, status: str, **details: Any
    ) -> dict[str, Any]:
        result = {"name": name, "group": group, "status": status, **details}
        self.results.append(result)
        print(
            f"{name}: {status}"
            + (f" ({details['reason']})" if "reason" in details else ""),
            flush=True,
        )
        return result

    def run(
        self,
        name: str,
        group: str,
        commands: list[list[str]],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        codes: list[int] = []
        reason = None
        status = "PASSED"
        with (self.output / "logs" / f"{name}.log").open("xb") as log:
            for command in commands:
                try:
                    result = subprocess.run(
                        command,
                        cwd=cwd or self.work,
                        env=env or self.env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        timeout=3600,
                        check=False,
                    )
                except FileNotFoundError:
                    status, reason = "NOT RUN", "required-executable-unavailable"
                    break
                except (OSError, subprocess.TimeoutExpired) as exc:
                    status, reason = "FAILED", type(exc).__name__
                    break
                codes.append(result.returncode)
                if result.returncode:
                    status = "FAILED"
                    break
        details: dict[str, Any] = {"exit_codes": codes, "log": f"logs/{name}.log"}
        if reason:
            details["reason"] = reason
        return self.record(name, group, status, **details)

    def backend(self, python: str, producers: Path | None) -> None:
        missing = sorted(
            {
                name
                for _, _, inputs, _ in LEGACY
                for name in inputs
                if not (ROOT / "evaluation/corpus" / name).is_file()
            }
        )
        producer_root = producers or ROOT / "backend/tests/fixtures/producers"
        if missing or not (producer_root / "provenance.json").is_file():
            self.record(
                "backend-regressions",
                "regression",
                "NOT RUN",
                reason="frozen-inputs-or-executed-producer-fixtures-missing",
                missing_frozen_inputs=missing,
            )
            self.record(
                "branch-targets",
                "branch",
                "NOT RUN",
                reason="backend-measurement-unavailable",
            )
            return
        env = {
            **self.env,
            "FAILURELENS_PRODUCER_FIXTURES": str(producer_root.resolve()),
        }
        destination = self.output / "backend-coverage"
        self.run(
            "backend-regressions",
            "regression",
            [
                [
                    python,
                    str(ROOT / "scripts/backend_coverage.py"),
                    "collect",
                    "--output",
                    str(destination),
                ]
            ],
            env=env,
        )
        if (destination / "report.json").is_file():
            self.run(
                "branch-targets",
                "branch",
                [
                    [
                        python,
                        str(ROOT / "scripts/backend_coverage.py"),
                        "check",
                        "--report",
                        str(destination / "report.json"),
                    ]
                ],
                env=env,
            )
        else:
            self.record(
                "branch-targets",
                "branch",
                "NOT RUN",
                reason="coverage-report-unavailable",
            )

    def migration(self, python: str) -> None:
        config = configparser.ConfigParser()
        config.read(ROOT / "backend/alembic.ini")
        for key, relative in (
            ("script_location", "backend/migrations"),
            ("prepend_sys_path", "backend/src"),
        ):
            config["alembic"][key] = str(ROOT / relative).replace("%", "%%")
        target = self.work / "alembic.ini"
        with target.open("x") as stream:
            config.write(stream)
        env = {
            **self.env,
            "FAILURELENS_DATABASE_URL": f"sqlite+pysqlite:///{self.work / 'migration.db'}",
        }
        command = [python, "-m", "alembic", "-c", str(target)]
        self.run(
            "migration-roundtrip",
            "regression",
            [
                [*command, "upgrade", "head"],
                [*command, "downgrade", "c7a9e2f4b610"],
                [*command, "upgrade", "head"],
            ],
            env=env,
        )

    def evaluations(self, python: str) -> None:
        for name, script, inputs, arguments in LEGACY:
            if any(
                not (ROOT / "evaluation/corpus" / item).is_file() for item in inputs
            ):
                self.record(
                    f"legacy-{name}",
                    "regression",
                    "NOT RUN",
                    reason="frozen-input-unavailable",
                )
                continue
            self.run(
                f"legacy-{name}",
                "regression",
                [
                    [
                        python,
                        str(ROOT / "evaluation" / f"{script}.py"),
                        *arguments,
                        "--output",
                        str(self.output / "legacy" / name),
                    ]
                ],
            )

    def frontend(self) -> None:
        source = ROOT / "frontend"
        if not shutil.which("npm", path=self.env.get("PATH")) or not all(
            (source / "node_modules" / item).exists()
            for item in ("typescript/bin/tsc", "vite/bin/vite.js", "vitest/vitest.mjs")
        ):
            for name in ("frontend-build", "frontend-unit"):
                self.record(
                    name,
                    "regression",
                    "NOT RUN",
                    reason="npm-or-installed-frontend-dependencies-unavailable",
                )
            return
        # Copy dependencies too: compiler/test caches must stay outside source.
        target = self.work / "frontend"
        links = [path for path in source.rglob("*") if path.is_symlink()]
        if any(not path.resolve().is_relative_to(source.resolve()) for path in links):
            for name in ("frontend-build", "frontend-unit"):
                self.record(
                    name,
                    "regression",
                    "NOT RUN",
                    reason="frontend-symlink-outside-source",
                )
            return

        def ignored(directory: str, names: list[str]) -> set[str]:
            excluded = {
                name
                for name in names
                if name in {".npmrc", ".cache", ".vite", ".vite-temp"}
                or name == ".env"
                or name.startswith(".env.")
            }
            if Path(directory) == source:
                excluded.update(
                    {"dist", "test-results", "playwright-report"} & set(names)
                )
            return excluded

        shutil.copytree(source, target, symlinks=True, ignore=ignored)
        for link in links:
            copied = target / link.relative_to(source)
            if copied.is_symlink():
                copied.unlink()
                copied.symlink_to(
                    os.path.relpath(
                        target / link.resolve().relative_to(source.resolve()),
                        copied.parent,
                    )
                )
        self.run("frontend-build", "regression", [["npm", "run", "build"]], cwd=target)
        self.run("frontend-unit", "regression", [["npm", "test"]], cwd=target)

    def quality(self, python: str, app_python: str) -> None:
        for gate in OFFLINE_GATES:
            self.run(
                f"quality-{gate}",
                "quality-security",
                [
                    [
                        python,
                        str(ROOT / "scripts/quality_checks.py"),
                        gate,
                        "--app-python",
                        app_python,
                        "--output",
                        str(self.output / "quality" / f"{gate}.json"),
                    ]
                ],
            )
        for gate, reason in (
            (
                "python-audit",
                "online-advisory-audit-excluded-from-offline-verification",
            ),
            ("npm-audit", "registry-transmission-approval-required-audit-paused"),
        ):
            self.record(f"quality-{gate}", "quality-security", "NOT RUN", reason=reason)


def group_status(results: list[dict[str, Any]], group: str) -> str:
    statuses = [item["status"] for item in results if item["group"] == group]
    return (
        "FAILED"
        if "FAILED" in statuses
        else "NOT RUN"
        if not statuses or "NOT RUN" in statuses
        else "PASSED"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("verify", "evaluate", "security"))
    parser.add_argument(
        "--output",
        type=Path,
        help="Fresh directory outside checkout; default: unique /tmp directory",
    )
    parser.add_argument("--app-python", default=sys.executable)
    parser.add_argument("--quality-python", default=sys.executable)
    parser.add_argument(
        "--producer-fixtures",
        type=Path,
        help="Previously executed producer fixtures with provenance",
    )
    parser.add_argument(
        "--tests", nargs="+", help="Explicit test files for security mode"
    )
    args = parser.parse_args(argv)
    invocation_cwd = Path.cwd()
    args.app_python = interpreter_command(args.app_python, invocation_cwd)
    args.quality_python = interpreter_command(args.quality_python, invocation_cwd)
    if args.mode == "security" and not args.tests:
        parser.error("security mode requires --tests")
    try:
        output = fresh_output(args.output)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Verification outputs: {output}", flush=True)
    started = datetime.now(UTC).isoformat()
    with tempfile.TemporaryDirectory(prefix="work-", dir=output) as temporary:
        work = Path(temporary)
        env = child_environment(work, args.app_python)
        runner = Verification(output, work, env)
        before = None
        try:
            before = source_state(env)
            if args.mode == "verify":
                runner.backend(args.app_python, args.producer_fixtures)
                runner.migration(args.app_python)
                runner.evaluations(args.app_python)
                runner.frontend()
                runner.quality(args.quality_python, args.app_python)
                for name in (
                    "postgresql",
                    "browser",
                    "docker",
                    "fresh-producer-execution",
                    "frozen-classifier-quality",
                    "operational-performance",
                ):
                    runner.record(
                        name,
                        "external-acceptance",
                        "NOT RUN",
                        reason="separate-exact-source-acceptance-required",
                    )
            elif args.mode == "evaluate":
                runner.evaluations(args.app_python)
            else:
                tests = [str((ROOT / name).resolve()) for name in args.tests]
                runner.run(
                    "security-regressions",
                    "regression",
                    [
                        [
                            args.app_python,
                            "-m",
                            "pytest",
                            "-q",
                            "--basetemp",
                            str(work / "pytest"),
                            "--junitxml",
                            str(output / "security-junit.xml"),
                            *tests,
                        ]
                    ],
                )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            runner.record(
                "verification-orchestration",
                "regression",
                "FAILED",
                reason=type(exc).__name__,
            )
        try:
            after = source_state(env)
            clean = before == after and before and before["worktree_clean"]
            runner.record(
                "source-provenance",
                "provenance",
                "PASSED" if clean else "FAILED",
                reason="clean-source-unchanged" if clean else "dirty-or-changed-source",
            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            after = None
            runner.record(
                "source-provenance", "provenance", "FAILED", reason=type(exc).__name__
            )
        regression = group_status(runner.results, "regression")
        quality = group_status(runner.results, "quality-security")
        report = {
            "schema_version": 1,
            "mode": args.mode,
            "started_at": started,
            "finished_at": datetime.now(UTC).isoformat(),
            "source_before": before,
            "source_after": after,
            "results": runner.results,
            "local_regressions": regression,
            "branch_target_acceptance": group_status(runner.results, "branch"),
            "quality_security_acceptance": "PASSED"
            if quality == "PASSED"
            else "FAILED"
            if args.mode == "verify"
            else "NOT RUN",
            "full_project_acceptance": "NOT RUN",
        }
        (output / "summary.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n"
        )
        print(f"Local regressions: {regression}", flush=True)
        if args.mode == "verify":
            print(
                f"Required quality/security acceptance: {report['quality_security_acceptance']} (NOT RUN audits cannot satisfy acceptance)",
                flush=True,
            )
        failed = any(item["status"] == "FAILED" for item in runner.results) or (
            args.mode == "verify" and report["quality_security_acceptance"] != "PASSED"
        )
        return 1 if failed else 3 if regression == "NOT RUN" else 0


if __name__ == "__main__":
    raise SystemExit(main())
