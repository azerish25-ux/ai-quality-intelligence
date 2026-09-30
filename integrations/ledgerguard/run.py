"""Execute pinned LedgerGuard production components; emit real, independently checked reports.

Only the selected production .class is shadowed in a disposable directory. No source
checkout is edited. This is component execution, not HTTP/PostgreSQL/commit-time proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from catalog import INTERVENTIONS, expected_measurement

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CORE = Path("backend/src/main/java/lab/ledgerguard/core")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def verify_source(source: Path, pin: dict) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", pin["revision"]):
        raise ValueError("invalid pinned revision")
    source = source.resolve()
    expected = set(pin["files"])
    actual = {str(p.relative_to(source)) for p in (source / CORE).glob("*.java")}
    if actual != expected:
        raise ValueError("pinned component source inventory differs")
    for name, expected_digest in pin["files"].items():
        path = source / name
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError("unsafe component source path")
        if digest(path.read_bytes()) != expected_digest:
            raise ValueError(f"pinned source mismatch: {name}")
    # Archives are accepted by their complete pinned component inventory. For a
    # checkout, also require the declared commit and an unchanged tracked tree.
    if (source / ".git").exists():
        sha = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
        ).strip()
        if sha != pin["revision"]:
            raise ValueError("companion checkout is at the wrong revision")
        subprocess.run(
            ["git", "-C", str(source), "diff", "--exit-code", "HEAD", "--"],
            check=True,
            capture_output=True,
        )


def junit(case_id: str, assertion: str, expected: str, actual: str) -> bytes:
    failed = expected != actual
    suite = ET.Element(
        "testsuite",
        name="LedgerGuard contract measurements",
        tests="1",
        failures=str(int(failed)),
        errors="0",
        skipped="0",
    )
    test = ET.SubElement(
        suite,
        "testcase",
        classname="contracts.Measurements",
        name=case_id,
        file="contracts/measurements.java",
    )
    detail = f"{assertion}. Expected={expected}; observed={actual}."
    if failed:
        ET.SubElement(
            test, "failure", type="AssertionError", message=detail
        ).text = detail
    ET.SubElement(test, "system-out").text = f"Expected={expected}; observed={actual}."
    return ET.tostring(suite, encoding="utf-8", xml_declaration=True)


def run(source: Path, output: Path) -> dict:
    pin = json.loads((HERE / "source.json").read_text())
    verify_source(source, pin)
    if output.exists() and any(output.iterdir()):
        raise ValueError(
            "output must be a new or empty directory; historical evidence is never overwritten"
        )
    output.mkdir(parents=True, exist_ok=True)
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        raise RuntimeError("JDK 21 is required")
    version = subprocess.run(
        [java, "-version"], text=True, capture_output=True, check=True
    ).stderr.strip()
    if not re.search(r'version "21[.\"]', version):
        raise RuntimeError("This producer is pinned to JDK major version 21")
    records: list[dict] = []
    public: list[dict] = []
    commands: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="failurelens-ledgerguard-") as temporary:
        work = Path(temporary)
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(work),
            "TMPDIR": str(work),
            "LANG": "C.UTF-8",
        }

        def execute(argv: list[str], expected_exit: int = 0) -> str:
            started = time.perf_counter()
            proc = subprocess.run(
                argv,
                check=False,
                env=env,
                cwd=work,
                text=True,
                capture_output=True,
                timeout=60,
            )
            commands.append(
                {
                    "argv": [
                        s.replace(str(work), "<temporary>")
                        .replace(str(source), "<pinned-source>")
                        .replace(str(HERE), "<harness>")
                        for s in argv
                    ],
                    "exit_code": proc.returncode,
                    "expected_exit": expected_exit,
                    "seconds": time.perf_counter() - started,
                    "stdout_sha256": digest(proc.stdout.encode()),
                    "stderr_sha256": digest(proc.stderr.encode()),
                }
            )
            if proc.returncode != expected_exit:
                raise RuntimeError(
                    f"producer command failed: {Path(argv[0]).name}; exit={proc.returncode}; {proc.stderr[:2000]}"
                )
            if len(proc.stdout) > 4096:
                raise RuntimeError("unexpected measurement output size")
            return proc.stdout.strip()

        classes = work / "control"
        classes.mkdir()
        execute(
            [
                javac,
                "-J-Xmx256m",
                "--release",
                "21",
                "-d",
                str(classes),
                *[str(source / path) for path in sorted(pin["files"])],
                str(HERE / "Probe.java"),
            ]
        )
        for index, intervention in enumerate(INTERVENTIONS):
            original = (source / CORE / intervention.file).read_text()
            if original.count(intervention.before) != 1:
                raise ValueError(
                    f"intervention does not match exactly once: {intervention.mechanism}"
                )
            changed = original.replace(intervention.before, intervention.after)
            mutant = work / f"intervention-{index}"
            mutant.mkdir()
            mutant_file = mutant / intervention.file
            mutant_file.write_text(changed)
            execute(
                [
                    javac,
                    "-J-Xmx256m",
                    "--release",
                    "21",
                    "-cp",
                    str(classes),
                    "-d",
                    str(mutant),
                    str(mutant_file),
                ]
            )
            for variant in range(4):
                case_id = (
                    "c-"
                    + digest(f"ledgerguard-component-v1/{index}/{variant}".encode())[
                        :20
                    ]
                )
                expected = expected_measurement(index, variant)
                control = execute(
                    [
                        java,
                        "-Xmx64m",
                        "-cp",
                        str(classes),
                        "Probe",
                        str(index),
                        str(variant),
                    ]
                )
                observed = execute(
                    [
                        java,
                        "-Xmx64m",
                        "-cp",
                        os.pathsep.join([str(mutant), str(classes)]),
                        "Probe",
                        str(index),
                        str(variant),
                    ]
                )
                if control != expected:
                    raise RuntimeError(
                        f"passing control violated independent oracle: {case_id}"
                    )
                if observed == expected:
                    raise RuntimeError(
                        f"intervention survived the independent oracle: {case_id}"
                    )
                item = {
                    "case_id": case_id,
                    "repository": pin["repository"],
                    "source_revision": pin["revision"],
                    "inputs": [],
                }
                for role, value in (("control", control), ("observation", observed)):
                    name = f"{case_id}/{role}.xml"
                    content = junit(case_id, intervention.assertion, expected, value)
                    path = output / "inputs" / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                    item["inputs"].append(
                        {
                            "role": role,
                            "path": name,
                            "sha256": digest(content),
                            "bytes": len(content),
                        }
                    )
                public.append(item)
                records.append(
                    {
                        "case_id": case_id,
                        "source_kind": "ledgerguard_executed",
                        "execution_scope": "production_component",
                        "source_revision": pin["revision"],
                        "scenario_family_id": intervention.mechanism,
                        "incident_id": case_id,
                        "expected_category": "product_defect",
                        "severity": intervention.severity,
                        "split": "challenge",
                        "root_cause": intervention.mechanism,
                        "control": control,
                        "expected": expected,
                        "observed": observed,
                        "oracle": "Independent Python arithmetic, calendar or documented rejection/identity contract checked against returned Java measurements",
                        "control_passed": True,
                        "intervention_failed": True,
                        "mutation_file": str(CORE / intervention.file),
                        "mutation_source_sha256": digest(changed.encode()),
                        "variant": variant,
                        "label_review_status": "agent-reviewed",
                        "required_evidence": [
                            "expected and observed measurements",
                            "current-run failed contract assertion",
                        ],
                        "forbidden_claims": ["release approved", "definitely harmless"],
                        "adversarial_tags": [],
                    }
                )
        verify_source(source, pin)
    public_manifest = {"schema_version": "artifact-replay-v1", "cases": public}
    (output / "inputs" / "manifest.json").write_bytes(canonical(public_manifest))
    (output / "ground-truth.json").write_bytes(
        canonical({"schema_version": "executed-case-v1", "cases": records})
    )
    git = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    dirty = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
        check=False,
        capture_output=True,
        text=True,
    )
    provenance = {
        "schema_version": "ledgerguard-execution-v1",
        "source_kind": "ledgerguard_executed",
        "execution_scope": "production_component",
        "ledgerguard_revision": pin["revision"],
        "failurelens_revision": git.stdout.strip() if git.returncode == 0 else None,
        "failurelens_worktree_dirty": bool(dirty.stdout.strip()),
        "java_version": version,
        "case_count": len(records),
        "family_count": len(INTERVENTIONS),
        "control_passes": len(records),
        "intervention_failures": len(records),
        "commands": commands,
        "source_files": pin["files"],
        "harness_files": {
            p.name: digest(p.read_bytes())
            for p in (
                HERE / "run.py",
                HERE / "Probe.java",
                HERE / "catalog.py",
                HERE / "source.json",
            )
        },
        "input_manifest_sha256": digest(
            (output / "inputs" / "manifest.json").read_bytes()
        ),
        "ground_truth_sha256": digest((output / "ground-truth.json").read_bytes()),
        "limitations": [
            "Real execution of pinned production components, not HTTP/database/commit-time transaction execution.",
            "Four variants per family are correlated, not 60 independent root causes.",
            "This is an agent-authored challenge/regression slice, not the complete 200-case/80-family M6 benchmark.",
            "No application classification rules are changed or tuned by this generator.",
        ],
    }
    (output / "provenance.json").write_bytes(canonical(provenance))
    return provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledgerguard-source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.ledgerguard_source.resolve(), args.output.resolve())
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "case_count",
                    "family_count",
                    "control_passes",
                    "intervention_failures",
                    "execution_scope",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
