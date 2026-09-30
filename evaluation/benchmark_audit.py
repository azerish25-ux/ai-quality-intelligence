"""Verify frozen bytes, family isolation and retained-execution provenance."""

from __future__ import annotations

import json
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from evaluation.benchmark_contract import digest, load_inputs, safe_read, unique_json
from evaluation.benchmark_labels import BenchmarkCaseLabel
from evaluation.benchmark_policy import POLICY

CATEGORIES = {
    "product_defect",
    "test_defect",
    "infrastructure_failure",
    "known_flake",
    "insufficient_evidence",
}
REQUIRED = {
    "case_id",
    "schema_version",
    "source_kind",
    "source_revision",
    "scenario_family_id",
    "incident_id",
    "artifacts",
    "history_manifest",
    "expected_category",
    "root_cause",
    "required_evidence",
    "forbidden_claims",
    "severity",
    "observability_rationale",
    "oracle",
    "adversarial_tags",
    "label_provenance",
    "label_review_status",
    "split",
}


def audit(corpus: Path, *, verify_retained=True) -> dict:
    freeze = unique_json(safe_read(corpus, "freeze.json"))
    expected_files = {
        "inputs/manifest.json",
        "ground-truth.json",
        "families.json",
        "policy.json",
    }
    if (
        freeze.get("schema_version") != "benchmark-freeze-v1"
        or set(freeze.get("file_sha256", {})) != expected_files
    ):
        raise ValueError("Invalid frozen manifest")
    for name, expected in freeze["file_sha256"].items():
        if digest(safe_read(corpus, name, 4 * 1024 * 1024)) != expected:
            raise ValueError("Frozen corpus bytes changed: " + name)
    public = load_inputs(corpus / "inputs")
    labels = unique_json(safe_read(corpus, "ground-truth.json", 4 * 1024 * 1024))
    families = unique_json(safe_read(corpus, "families.json"))
    policy = unique_json(safe_read(corpus, "policy.json"))
    if policy != POLICY:
        raise ValueError("Versioned benchmark acceptance policy was altered")
    if not isinstance(labels, list) or len({r.get("case_id") for r in labels}) != len(
        labels
    ):
        raise ValueError("Duplicate or malformed ground truth")
    if {r["case_id"] for r in labels} != {c.case_id for c in public.cases}:
        raise ValueError("Public inputs and private cases differ")
    fmap = {r["id"]: r for r in families}
    if len(fmap) != len(families) or len({r["mechanism"] for r in families}) != len(
        families
    ):
        raise ValueError("Duplicated family or mechanism definition")
    grouped = defaultdict(set)
    incidents = defaultdict(set)
    artifacts = defaultdict(set)
    by_case = {c.case_id: c for c in public.cases}
    for row in labels:
        BenchmarkCaseLabel.model_validate(row)
        if not REQUIRED <= row.keys() or row["schema_version"] != "2.0":
            raise ValueError("Missing ground-truth fields")
        if (
            row["expected_category"] not in CATEGORIES
            or row["split"] not in {"development", "calibration", "test"}
            or row["label_review_status"] != "agent-reviewed"
            or row["source_kind"] not in {"synthetic", "ledgerguard_executed"}
            or row["scenario_family_id"] not in fmap
            or not row["observability_rationale"]
            or not row["oracle"]
        ):
            raise ValueError("Invalid category, provenance, split or rubric")
        case = by_case[row["case_id"]]
        if row["source_revision"] != case.source_revision or row["artifacts"] != [
            case.current.path
        ]:
            raise ValueError("Case artifact/source provenance mismatch")
        if (
            row["source_kind"] == "ledgerguard_executed"
            and row["split"] != "development"
        ):
            raise ValueError("Previously inspected execution cannot be held out")
        grouped[row["scenario_family_id"]].add(row["split"])
        incidents[row["incident_id"]].add(row["split"])
        for ref in [
            case.current,
            case.control,
            case.later,
            *(p.artifact for p in case.prior),
        ]:
            if ref is not None:
                artifacts[ref.sha256].add(row["split"])
    if any(
        len(v) > 1
        for mapping in (grouped, incidents, artifacts)
        for v in mapping.values()
    ):
        raise ValueError(
            "Family, incident or identical current artifact crosses split boundaries"
        )
    if set(grouped) != set(fmap) or any(
        fmap[k]["split"] != next(iter(v)) for k, v in grouped.items()
    ):
        raise ValueError("Family register and split assignments differ")
    if verify_retained:
        root = Path(__file__).resolve().parents[1]
        archive = root / "evaluation/corpus/ledgerguard-component-v1/execution.zip"
        data = archive.read_bytes()
        if digest(data) != freeze["retained_execution_archive_sha256"]:
            raise ValueError("Retained execution provenance changed")
        with zipfile.ZipFile(archive) as z:
            original = {
                r["case_id"]: r
                for r in json.loads(z.read("corpus/ground-truth.json"))["cases"]
            }
            refs = {
                r["case_id"]: r
                for r in json.loads(z.read("corpus/inputs/manifest.json"))["cases"]
            }
            imported = [r for r in labels if r["source_kind"] == "ledgerguard_executed"]
            if {r["case_id"] for r in imported} != set(original):
                raise ValueError("Retained executed cases were omitted or forged")
            for row in imported:
                old = original[row["case_id"]]
                if any(
                    row.get(k) != old.get(k)
                    for k in [
                        "expected_category",
                        "scenario_family_id",
                        "source_revision",
                        "observed",
                        "expected",
                        "control_passed",
                        "intervention_failed",
                    ]
                ):
                    raise ValueError(
                        "Retained execution labels or oracle records were changed"
                    )
                current = by_case[row["case_id"]]
                for ref in refs[row["case_id"]]["inputs"]:
                    imported_ref = (
                        current.control if ref["role"] == "control" else current.current
                    )
                    if imported_ref is None or imported_ref.sha256 != ref["sha256"]:
                        raise ValueError(
                            "Retained control/intervention bytes were changed"
                        )
    counts = Counter(r["expected_category"] for r in labels)
    sources = Counter(r["source_kind"] for r in labels)
    splits = Counter(r["split"] for r in labels)
    test = [r for r in labels if r["split"] == "test"]
    products = [r for r in test if r["expected_category"] == "product_defect"]
    executed = [r for r in labels if r["source_kind"] == "ledgerguard_executed"]
    gates = {
        "minimum_cases": len(labels) >= policy["minimum_cases"],
        "minimum_families": len(grouped) >= policy["minimum_families"],
        "minimum_category_counts": all(
            counts[c] >= n for c, n in policy["minimum_category_counts"].items()
        ),
        "minimum_test_cases": len(test) >= policy["minimum_test_cases"],
        "minimum_test_products": len(products) >= policy["minimum_test_products"],
        "minimum_test_product_families": len(
            {r["scenario_family_id"] for r in products}
        )
        >= policy["minimum_test_product_families"],
        "minimum_retained_executed_cases": len(executed)
        >= policy["minimum_executed_cases"],
        "minimum_retained_executed_families": len(
            {r["scenario_family_id"] for r in executed}
        )
        >= policy["minimum_executed_families"],
        "family_incident_artifact_split_isolation": True,
        "minimum_tagged_adversarial_cases": sum(
            bool(r["adversarial_tags"]) for r in labels
        )
        >= policy["minimum_adversarial_cases"],
    }
    if (
        freeze["case_count"] != len(labels)
        or freeze["family_count"] != len(grouped)
        or freeze["category_counts"] != dict(counts)
        or freeze["source_counts"] != dict(sources)
        or freeze["split_counts"] != dict(splits)
    ):
        raise ValueError("Frozen manifest counts disagree with actual records")
    return {
        "case_count": len(labels),
        "family_count": len(grouped),
        "category_counts": dict(counts),
        "source_counts": dict(sources),
        "split_counts": dict(splits),
        "test_product_families": len({r["scenario_family_id"] for r in products}),
        "gates": gates,
        "independence_status": "Agent-authored mechanism grouping; no independent causal adjudication",
        "fresh_ledgerguard_executions": 0,
        "retained_ledgerguard_executions": len(executed),
    }
