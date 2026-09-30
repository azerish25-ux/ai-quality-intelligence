"""Execute richer observations for three KNOWN component mechanisms, then freeze development data.

This supplements, never rewrites, the old scalar execution artifacts. The four
additional diagnostic families are explicitly synthetic. No held-out claim.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from catalog import INTERVENTIONS, expected_measurement

from evaluation.campaign_contract import audit, canonical, digest
from integrations.ledgerguard.run import CORE, verify_source

KINDS = (
    "atomic_transfer",
    "tenant_isolation",
    "status_expectation",
    "runner_memory_limit",
)
CATEGORIES = (
    "product_defect",
    "product_defect",
    "test_defect",
    "infrastructure_failure",
)
POLICY = {
    "product_recall_minimum": 0.90,
    "macro_f1_minimum": 0.80,
    "coverage_minimum": 0.75,
    "dangerous_dismissal_maximum": 0.05,
    "high_critical_dismissals_maximum": 0,
    "published_citation_validity_minimum": 1.0,
    "critical_unsupported_reassurance_maximum": 0,
    "sensitive_canary_leaks_maximum": 0,
    "repetitions": 5,
}


def synthetic_observation(kind: str, variant: int) -> dict:
    """Controlled measurements, NOT executed kernel, HTTP or financial scenarios."""
    n = 25 + variant
    measurements = {
        "atomic_transfer": {
            "kind": kind,
            "atomicity_policy": "both_effects_or_neither",
            "observation_scope": "isolated_logical_request",
            "request_digest": "a" * 64,
            "receipt_request_digest": "a" * 64,
            "source_account_digest": "b" * 64,
            "destination_account_digest": "c" * 64,
            "currency": "CAD",
            "amount_minor": n,
            "receipt_outcome": "committed",
            "concurrent_writers": 0,
            "before_source_minor": 100,
            "before_destination_minor": 50,
            "after_source_minor": 100 - n,
            "after_destination_minor": 50,
        },
        "tenant_isolation": {
            "kind": kind,
            "access_policy": "same_tenant_resource_access",
            "principal_scope": "tenant_member",
            "actor_tenant_digest": digest(f"actor-{variant}".encode()),
            "resource_tenant_digest": digest(f"resource-tenant-{variant}".encode()),
            "requested_resource_digest": "c" * 64,
            "returned_resource_digest": "c" * 64,
            "response_status": 200,
        },
        "status_expectation": {
            "kind": kind,
            "assertion_scope": "response_status_equality",
            "contract_source": "versioned_api_contract",
            "contract_digest": digest(f"contract-{variant}".encode()),
            "served_contract_digest": digest(f"contract-{variant}".encode()),
            "allowed_statuses": [200],
            "observed_status": 200,
            "asserted_status": 201,
        },
        "runner_memory_limit": {
            "kind": kind,
            "process_role": "test_runner",
            "counter_scope": "isolated_runner_cgroup",
            "runner_process_digest": "a" * 64,
            "killed_process_digest": "a" * 64,
            "memory_limit_bytes": 1048576 * (variant + 1),
            "peak_memory_bytes": 1048576 * (variant + 1),
            "oom_kills_before": variant,
            "oom_kills_after": variant + 1,
            "termination_signal": 9,
        },
    }
    return {
        "schema_version": "contract-observations-v1",
        "test_identity": "measurement::result",
        "attempt": 0,
        "browser": None,
        "measurement": measurements[kind],
    }


def bundle(record: dict, *, failed: bool) -> bytes:
    # Opaque case identity and generic failure avoid leaking labels or fault flags.
    failure = (
        '<failure type="AssertionError" message="Observed relationship mismatch"/>'
        if failed
        else ""
    )
    xml = (
        f'<testsuite tests="1" failures="{int(failed)}"><testcase classname="measurement" name="result">'
        f"{failure}</testcase></testsuite>"
    ).encode()
    data = {"report.xml": xml, "measurement.json": canonical(record)}
    entries = [
        {
            "id": "report",
            "path": "report.xml",
            "kind": "junit-xml",
            "required": True,
            "role": "primary",
        },
        {
            "id": "measurement",
            "path": "measurement.json",
            "kind": "contract-observations-json",
            "required": True,
            "correlates_to": ["report"],
        },
    ]
    for item in entries:
        item["sha256"] = digest(data[item["path"]])
    data["manifest.json"] = canonical({"schema_version": "2.0", "inputs": entries})
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in sorted(data.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    return result.getvalue()


def add_case(
    root: Path,
    public: list,
    labels: list,
    families: dict,
    *,
    record: dict,
    control: dict | None,
    family: str,
    variant: int,
    source_kind: str,
    revision: str,
    category: str,
    oracle: str,
    severity: str | None = None,
) -> None:
    case_id = (
        "c-" + digest(f"diagnostic-development-v1/{family}/{variant}".encode())[:20]
    )

    def save(value: dict, role: str, failed: bool):
        content = bundle(value, failed=failed)
        path = f"{case_id}/{role}.zip"
        target = root / "inputs" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return {
            "path": path,
            "sha256": digest(content),
            "bytes": len(content),
            "source_format": "failurelens-bundle-v2",
            "expected_inputs": 2,
        }

    current = save(record, "observation", True)
    case = {
        "case_id": case_id,
        "repository": "azerish25-ux/transaction-reliability-lab"
        if source_kind == "ledgerguard_executed"
        else "example/diagnostic-development",
        "source_revision": revision,
        "observed_at": "2026-01-20T12:00:00+00:00",
        "observation": current,
        "control": save(control, "control", False) if control else None,
        "history": [],
    }
    public.append(case)
    label = {
        "schema_version": "campaign-case-v1",
        "case_id": case_id,
        "source_kind": source_kind,
        "source_revision": revision,
        "scenario_family_id": family,
        "incident_id": case_id,
        "artifacts": [current["path"]],
        "history_manifest": None,
        "expected_category": category,
        "root_cause": family,
        "required_evidence": ["execution-bound measured contract relation"],
        "forbidden_claims": ["release approved", "definitely harmless"],
        "severity": severity
        or ("critical" if category == "product_defect" else "medium"),
        "observability_rationale": "The bundled measurements expose the scoped relation; the fault oracle is not an inference input.",
        "oracle": oracle,
        "adversarial_tags": [],
        "label_provenance": "Agent-authored controlled regression with explicit provenance; no expert adjudication",
        "label_review_status": "agent-reviewed",
        "split": "development",
        "variant": variant,
        "family_group": family,
        "reused_development": True,
        "claim_rubric": "bounded-classification-v1"
        if category == "insufficient_evidence"
        else "bounded-contract-v1",
    }
    labels.append(label)
    group = families.setdefault(
        family,
        {
            "family_group": family,
            "split": "development",
            "cases": [],
            "review_status": "agent-reviewed",
            "independent_expert_adjudication": False,
        },
    )
    group["cases"].append(case_id)


def freeze(
    root: Path, public: list, labels: list, families: dict, provenance: dict
) -> dict:
    (root / "inputs").mkdir(parents=True, exist_ok=True)
    (root / "inputs/manifest.json").write_bytes(
        canonical({"schema_version": "campaign-input-v1", "cases": public})
    )
    (root / "labels.json").write_bytes(canonical(labels))
    (root / "families.json").write_bytes(canonical(list(families.values())))
    (root / "policy.json").write_bytes(canonical(POLICY))
    (root / "execution-provenance.json").write_bytes(canonical(provenance))
    (root / "freeze.json").write_bytes(
        canonical(
            {
                "version": "campaign-freeze-v1",
                "scope": "development_only",
                "files": {
                    name: digest((root / name).read_bytes())
                    for name in [
                        "inputs/manifest.json",
                        "labels.json",
                        "families.json",
                        "policy.json",
                        "execution-provenance.json",
                    ]
                },
                "harness_files": {
                    str(p.relative_to(ROOT)): digest(p.read_bytes())
                    for p in [
                        HERE / "diagnostics.py",
                        HERE / "DiagnosticProbe.java",
                        HERE / "Probe.java",
                        HERE / "catalog.py",
                        HERE / "source.json",
                    ]
                },
                "limitations": [
                    "Not a held-out or independently blinded benchmark.",
                    "Known component mechanisms are development only.",
                ],
            }
        )
    )
    inventory, _, _ = audit(root, enforce_minimums=False)
    return inventory


def build(output: Path, source: Path | None = None) -> dict:
    output = output.resolve()
    if output.exists():
        raise ValueError(
            "A new output directory is required; retained data is never overwritten"
        )
    output.mkdir(parents=True)
    public = []
    labels = []
    families = {}
    revision = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    provenance = {
        "scope": "component_development_and_explicit_synthetic",
        "failurelens_revision": revision,
        "source_worktree_dirty": bool(
            subprocess.check_output(
                ["git", "-C", str(ROOT), "status", "--porcelain"], text=True
            ).strip()
        ),
        "commands": [],
        "executed_pairs": 0,
        "executed_families": 0,
        "synthetic_cases": 20,
        "oracle_receipts": [],
        "generated_at": datetime.now(UTC).isoformat(),
        "replay_time_is_synthetic": True,
    }
    if source is not None:
        source = source.resolve()
        pin = json.loads((HERE / "source.json").read_bytes())
        verify_source(source, pin)
        javac, java = shutil.which("javac"), shutil.which("java")
        if not javac or not java:
            raise RuntimeError("JDK 21 is required")
        version = subprocess.run(
            [java, "-version"], text=True, capture_output=True, check=True
        ).stderr
        import re

        if not re.search(r'version "21[.\"]', version):
            raise RuntimeError("JDK major version must be 21")
        provenance.update(
            ledgerguard_revision=pin["revision"],
            source_files=pin["files"],
            java_version=version,
        )
        with tempfile.TemporaryDirectory(
            prefix="failurelens-diagnostic-components-"
        ) as temporary:
            work = Path(temporary)
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(work),
                "TMPDIR": str(work),
                "LANG": "C.UTF-8",
            }

            def execute(argv):
                start = time.perf_counter()
                p = subprocess.run(
                    argv,
                    check=False,
                    cwd=work,
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=60,
                )
                provenance["commands"].append(
                    {
                        "argv": [
                            s.replace(str(work), "<temporary>")
                            .replace(str(source), "<pinned-source>")
                            .replace(str(HERE), "<harness>")
                            for s in argv
                        ],
                        "exit_code": p.returncode,
                        "seconds": time.perf_counter() - start,
                        "stdout_sha256": digest(p.stdout.encode()),
                        "stderr_sha256": digest(p.stderr.encode()),
                    }
                )
                if p.returncode != 0 or len(p.stdout) > 16384:
                    raise RuntimeError(
                        "Bounded producer command failed: " + p.stderr[:1000]
                    )
                return p.stdout.strip()

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
                    *[str(source / p) for p in sorted(pin["files"])],
                    str(HERE / "Probe.java"),
                    str(HERE / "DiagnosticProbe.java"),
                ]
            )
            for index in (9, 12, 14):
                intervention = INTERVENTIONS[index]
                original = (source / CORE / intervention.file).read_text()
                if original.count(intervention.before) != 1:
                    raise ValueError("Pinned mutation boundary differs")
                changed = original.replace(intervention.before, intervention.after)
                mutant = work / f"mutant-{index}"
                mutant.mkdir()
                (mutant / intervention.file).write_text(changed)
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
                        str(mutant / intervention.file),
                    ]
                )
                for variant in range(4):
                    values = {}
                    scalars = {}
                    for role, classpath in [
                        ("control", str(classes)),
                        ("observation", os.pathsep.join([str(mutant), str(classes)])),
                    ]:
                        args = [str(index), str(variant)]
                        values[role] = json.loads(
                            execute(
                                [
                                    java,
                                    "-Xmx64m",
                                    "-cp",
                                    classpath,
                                    "DiagnosticProbe",
                                    *args,
                                ]
                            )
                        )
                        scalars[role] = execute(
                            [java, "-Xmx64m", "-cp", classpath, "Probe", *args]
                        )
                        m = values[role]["measurement"]
                        derived = (
                            str(
                                m["first"]["fingerprint"] == m["second"]["fingerprint"]
                            ).lower()
                            if index == 9
                            else m["next_local"]
                            if index == 12
                            else str(m["after"]["version"])
                        )
                        if derived != scalars[role]:
                            raise ValueError(
                                "New observations disagree with independently executed scalar probe"
                            )
                    expected = expected_measurement(index, variant)
                    if (
                        scalars["control"] != expected
                        or scalars["observation"] == expected
                    ):
                        raise ValueError("Control/intervention oracle failed")
                    add_case(
                        output,
                        public,
                        labels,
                        families,
                        record=values["observation"],
                        control=values["control"],
                        family=intervention.mechanism,
                        variant=variant,
                        source_kind="ledgerguard_executed",
                        revision=pin["revision"],
                        category="product_defect",
                        severity=intervention.severity,
                        oracle="Original scalar probe independently executed in each role and checked against the existing arithmetic/calendar/identity oracle; richer observations must agree.",
                    )
                    provenance["oracle_receipts"].append(
                        {
                            "family": intervention.mechanism,
                            "variant": variant,
                            "expected": expected,
                            "control": scalars["control"],
                            "observation": scalars["observation"],
                            "mutation_sha256": digest(changed.encode()),
                            "control_passed": True,
                            "intervention_failed": True,
                        }
                    )
            verify_source(source, pin)
        provenance.update(executed_pairs=12, executed_families=3)
    for kind, category in zip(KINDS, CATEGORIES):
        for variant in range(4):
            add_case(
                output,
                public,
                labels,
                families,
                record=synthetic_observation(kind, variant),
                control=None,
                family="diagnostic-" + kind,
                variant=variant,
                source_kind="synthetic",
                revision=revision,
                category=category,
                oracle="Explicit synthetic relational fixture, independently recomputed by the campaign scorer; not actual HTTP, database, or kernel execution.",
            )
    missing_fields = {
        "atomic_transfer": "after_destination_minor",
        "tenant_isolation": "response_status",
        "status_expectation": "observed_status",
        "runner_memory_limit": "peak_memory_bytes",
    }
    for kind in KINDS:
        record = synthetic_observation(kind, 0)
        record["measurement"][missing_fields[kind]] = None
        add_case(
            output,
            public,
            labels,
            families,
            record=record,
            control=None,
            family="diagnostic-" + kind,
            variant=4,
            source_kind="synthetic",
            revision=revision,
            category="insufficient_evidence",
            oracle="Required observed measurement is deliberately absent; neither a product nor non-product diagnosis is supported.",
        )
    return freeze(output, public, labels, families, provenance)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ledgerguard-source", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(build(args.output, args.ledgerguard_source), indent=2))


if __name__ == "__main__":
    main()
