"""Run real, pinned report producers against disposable loopback-only scenarios.

Non-zero fixture exits are accepted ONLY when independently checked expected
outcomes and artifacts exist. This does not generate any LedgerGuard cases.
"""

from __future__ import annotations

import argparse
import hashlib
import http.server
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=ROOT / "backend/tests/fixtures/producers"
    )
    parser.add_argument(
        "--skip-java-k6",
        action="store_true",
        help="Explicitly partial local generation; full CI never uses this flag",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise SystemExit(
            "Output must be empty; use a fresh directory or deliberately remove previous fixtures"
        )
    os.environ["PRODUCER_OUTPUT"] = str(output)
    records = []

    def execute(argv, expected, cwd=ROOT):
        completed = subprocess.run(
            argv,
            check=False,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=300,
        )
        records.append(
            {
                "argv": argv,
                "exit_code": completed.returncode,
                "expected_exit_codes": expected,
            }
        )
        if completed.returncode not in expected:
            print(completed.stdout[-12000:])
            raise RuntimeError(
                f"Unexpected producer exit: {argv[0]} ({completed.returncode})"
            )
        return completed.stdout

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            status = 503 if self.path.startswith("/down") else 200
            body = b'<!doctype html><html><body><h1>Controlled fixture</h1><p id="private">fixture-person@example.com</p><p>Balance <span id="balance">100</span></p></body></html>'
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 8779), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        version = json.loads(
            (ROOT / "frontend/node_modules/@playwright/test/package.json").read_text()
        )["version"]
        assert version == "1.63.0", version
        assert importlib.metadata.version("pytest-json-report") == "1.5.0"
        assert importlib.metadata.version("pytest") == "9.0.2"
        execute(
            [
                "node",
                str(ROOT / "frontend/node_modules/@playwright/test/cli.js"),
                "test",
                "--config",
                str(HERE / "playwright.config.mjs"),
            ],
            [1],
        )
        report = json.loads((output / "playwright.json").read_text())
        assert report["stats"]["unexpected"] == 1 and report["stats"]["flaky"] == 1
        assert report["stats"]["expected"] == 1 and report["stats"]["skipped"] == 1
        execute(
            [
                sys.executable,
                "-m",
                "pytest",
                str(HERE / "pytest_cases.py"),
                "--json-report",
                f"--json-report-file={output / 'pytest.json'}",
                f"--junitxml={output / 'pytest.junit.xml'}",
                "-q",
            ],
            [1],
        )
        pytest_report = json.loads((output / "pytest.json").read_text())
        assert (
            pytest_report["summary"]["failed"] == 1
            and pytest_report["summary"]["passed"] == 3
        )
        assert (
            pytest_report["summary"]["skipped"] == 1
            and pytest_report["summary"]["xfailed"] == 1
        )
        versions = {
            "playwright": version,
            "pytest": importlib.metadata.version("pytest"),
            "pytest-json-report": "1.5.0",
            "python": sys.version,
            "node": execute(["node", "--version"], [0]).strip(),
        }
        if not args.skip_java_k6:
            execute(["mvn", "-B", "-ntp", "test"], [1], HERE / "java")
            junit = HERE / "java/target/surefire-reports/TEST-HttpEvidenceTest.xml"
            suite = ET.parse(junit).getroot()
            assert (
                suite.get("tests") == "2"
                and suite.get("failures") == "1"
                and suite.get("errors") == "0"
            )
            shutil.copy2(junit, output / "rest-assured.junit.xml")
            exchanges = [
                json.loads(path.read_text())
                for path in sorted(output.glob("java-*.json"))
            ]
            assert sorted(item["response"]["status"] for item in exchanges) == [
                200,
                503,
            ]
            (output / "rest-assured.json").write_text(
                json.dumps({"exchanges": exchanges}, indent=2)
            )
            versions.update(
                {
                    "rest-assured": "6.0.0",
                    "junit": "4.13.2",
                    "surefire": "3.5.4",
                    "maven": execute(["mvn", "--version"], [0]).strip(),
                }
            )
            execute(["docker", "pull", "grafana/k6:1.3.0"], [0])
            versions["k6_image"] = json.loads(
                execute(["docker", "image", "inspect", "grafana/k6:1.3.0"], [0])
            )[0]["RepoDigests"]
            execute(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network=host",
                    "--user",
                    f"{os.getuid()}:{os.getgid()}",
                    "-v",
                    f"{ROOT}:{ROOT}",
                    "-v",
                    f"{output}:{output}",
                    "-w",
                    str(ROOT),
                    "-e",
                    f"PRODUCER_OUTPUT={output}",
                    "grafana/k6:1.3.0",
                    "run",
                    str(HERE / "k6.js"),
                ],
                [99],
            )
            k6 = json.loads((output / "k6.json").read_text())
            assert k6["metrics"]["http_reqs"]["values"]["count"] == 6
            assert k6["metrics"]["checks"]["values"]["rate"] == 1
            assert (
                k6["metrics"]["http_req_failed"]["thresholds"]["rate==0"]["ok"] is False
            )
        build_bundle(output, report)
        # Network JSONL is a documented derivative of actual HAR events, not a hand-authored execution.
        har = json.loads((output / "network.har").read_text())
        network = [
            {
                "method": entry["request"]["method"],
                "url": entry["request"]["url"],
                "status": entry["response"]["status"],
                "duration_ms": entry["time"],
                "timestamp": entry["startedDateTime"],
            }
            for entry in har["log"]["entries"]
        ]
        assert network
        (output / "network.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in network)
        )
        console = [
            json.loads(line)
            for line in (output / "console.jsonl").read_text().splitlines()
        ]
        (output / "console.txt").write_text(
            "\n".join(row["message"] for row in console) + "\n"
        )
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        parent = subprocess.check_output(
            ["git", "rev-parse", "HEAD^"], cwd=ROOT, text=True
        ).strip()
        (output / "github.json").write_text(
            json.dumps(
                {
                    "repository": os.environ.get(
                        "GITHUB_REPOSITORY", "azerish25-ux/ai-quality-intelligence"
                    ),
                    "commit_sha": revision,
                    "base_sha": parent,
                    "workflow": os.environ.get("GITHUB_WORKFLOW"),
                    "run_id": os.environ.get("GITHUB_RUN_ID"),
                    "source": "workflow_environment_self_reported",
                },
                indent=2,
            )
        )
        changes = subprocess.check_output(
            ["git", "diff", "--name-status", parent, revision], cwd=ROOT, text=True
        )
        paths = [
            {
                "path": line.split("\t")[-1],
                "status": {"A": "added", "D": "deleted"}.get(line[0], "modified"),
            }
            for line in changes.splitlines()
        ]
        (output / "changes.json").write_text(
            json.dumps(
                {
                    "base_sha": parent,
                    "head_sha": revision,
                    "complete": True,
                    "files": paths,
                },
                indent=2,
            )
        )
        manifest = {
            "schema_version": "producer-fixtures-1.0",
            "source_kind": "other_executed",
            "ledgerguard_executions": 0,
            "source_revision": revision,
            "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
            "versions": versions,
            "commands": records,
            "scope": "partial-browser-python"
            if args.skip_java_k6
            else "browser-python-java-k6",
            "oracles": {
                "playwright": report["stats"],
                "pytest": pytest_report["summary"],
                "java": "one HTTP 200 control and one observed HTTP 503 intervention"
                if not args.skip_java_k6
                else "NOT RUN",
                "k6": "6 requests, all control/intervention checks pass, expected failed availability threshold"
                if not args.skip_java_k6
                else "NOT RUN",
            },
            "files": {
                p.relative_to(output).as_posix(): {
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                    "bytes": p.stat().st_size,
                }
                for p in sorted(output.rglob("*"))
                if p.is_file()
            },
            "privacy": "All contacts and token values are deliberate synthetic fixture data. No paid services or LedgerGuard code is involved.",
        }
        (output / "provenance.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        print(
            json.dumps(
                {
                    "scope": manifest["scope"],
                    "files": len(manifest["files"]),
                    "source_revision": revision,
                }
            )
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def build_bundle(output: Path, report: dict):
    inputs = [
        {
            "id": "playwright-report",
            "path": "playwright.json",
            "kind": "playwright-json",
            "required": True,
        }
    ]
    files = {"playwright.json": (output / "playwright.json").read_bytes()}

    def visit(suite):
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                for result in test.get("results", []):
                    for attachment in result.get("attachments", []):
                        source = Path(attachment.get("path", ""))
                        if not source.is_file() or source.suffix not in {
                            ".png",
                            ".jpg",
                            ".zip",
                        }:
                            continue
                        index = len(inputs)
                        dest = f"attachments/{index}-{source.name}"
                        kind = (
                            "playwright-trace"
                            if source.suffix == ".zip"
                            else "screenshot"
                        )
                        metadata = {
                            "producer_attachment_path": str(source),
                            "test_identity": test.get("testId") or spec.get("id"),
                            "browser": test["projectName"],
                            "attempt": result.get("retry", 0),
                            "producer_version": "1.63.0",
                        }
                        if kind == "screenshot":
                            metadata.update(
                                {
                                    "relationship": attachment["name"],
                                    "comparison_context": {
                                        "browser": "chromium",
                                        "os": "linux",
                                        "viewport_width": 640,
                                        "viewport_height": 480,
                                        "device_scale_factor": 1,
                                        "comparison_group": f"{spec.get('id')}:{result.get('retry', 0)}",
                                    },
                                }
                            )
                        files[dest] = source.read_bytes()
                        inputs.append(
                            {
                                "id": f"pw-{index}-{attachment['name']}",
                                "kind": kind,
                                "path": dest,
                                "required": True,
                                "sha256": hashlib.sha256(files[dest]).hexdigest(),
                                "metadata": metadata,
                            }
                        )
        for child in suite.get("suites", []):
            visit(child)

    for suite in report["suites"]:
        visit(suite)
    assert any(item["kind"] == "screenshot" for item in inputs) and any(
        item["kind"] == "playwright-trace" for item in inputs
    )
    with zipfile.ZipFile(
        output / "failurelens-bundle.zip", "w", compression=zipfile.ZIP_STORED
    ) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({"schema_version": "2.0", "inputs": inputs}, indent=2),
        )
        for name, content in files.items():
            archive.writestr(name, content)


if __name__ == "__main__":
    main()
