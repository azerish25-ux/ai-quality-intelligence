"""Contract and adversarial tests for M6 execution/replay. Fixtures here are synthetic test data."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evaluation.artifact_contract import load_manifest, read_artifact, ArtifactRef
from evaluation.corpus_audit import audit_legacy
from evaluation.executed_harness import classification_metrics, family_recall_interval, fraction
from evaluation.generate_corpus import CATEGORY_COUNTS, build_case

spec = importlib.util.spec_from_file_location("ledgerguard_catalog", ROOT / "integrations/ledgerguard/catalog.py")
catalog = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = catalog
spec.loader.exec_module(catalog)


def make_public_fixture(tmp_path):
    root = tmp_path / "corpus/inputs"; root.mkdir(parents=True)
    case_id = "c-" + "a" * 20
    data = b'<testsuite tests="1"><testcase name="synthetic-fixture"/></testsuite>'
    refs = []
    for role in ("control", "observation"):
        path = root / case_id / (role + ".xml"); path.parent.mkdir(exist_ok=True); path.write_bytes(data)
        refs.append({"role": role, "path": str(path.relative_to(root)), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    manifest = {"schema_version": "artifact-replay-v1", "cases": [{"case_id": case_id, "repository": "example/fixture", "source_revision": "0" * 40, "inputs": refs}]}
    (root / "manifest.json").write_text(json.dumps(manifest))
    return root, manifest


def test_public_replay_schema_accepts_observations_without_ground_truth(tmp_path):
    root, _ = make_public_fixture(tmp_path)
    result = load_manifest(root)
    assert len(result.cases) == 1
    assert b"synthetic-fixture" in read_artifact(root, result.cases[0].inputs[0])


@pytest.mark.parametrize("field", ["expected_category", "root_cause", "scenario_family_id", "fault_enabled", "oracle", "historical"])
def test_runtime_contract_rejects_answer_bearing_metadata(tmp_path, field):
    root, manifest = make_public_fixture(tmp_path)
    manifest["cases"][0][field] = "do not load answers"
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValidationError): load_manifest(root)


@pytest.mark.parametrize("path", ["../outside.xml", "/tmp/outside.xml", "a/../../outside.xml", "a\\outside.xml", "a//b.xml", "a/./b.xml", "a/b/c.xml"])
def test_runtime_paths_cannot_escape_or_collide(tmp_path, path):
    root, manifest = make_public_fixture(tmp_path)
    manifest["cases"][0]["inputs"][0]["path"] = path
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises((ValidationError, ValueError)): load_manifest(root)


def test_runtime_rechecks_digest_after_manifest_validation(tmp_path):
    root, _ = make_public_fixture(tmp_path)
    manifest = load_manifest(root)
    ref = manifest.cases[0].inputs[0]
    (root / ref.path).write_bytes(b"modified")
    with pytest.raises(ValueError, match="digest"): read_artifact(root, ref)


def test_runtime_rejects_symlink_and_duplicate_cases(tmp_path):
    root, data = make_public_fixture(tmp_path)
    data["cases"].append(deepcopy(data["cases"][0]))
    (root / "manifest.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="duplicate"): load_manifest(root)
    data["cases"].pop()
    target = root / data["cases"][0]["inputs"][0]["path"]
    target.unlink(); target.symlink_to(root / data["cases"][0]["inputs"][1]["path"])
    (root / "manifest.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="escapes"): load_manifest(root)


def test_runtime_requires_control_observation_pair(tmp_path):
    root, data = make_public_fixture(tmp_path)
    data["cases"][0]["inputs"][0]["role"] = "observation"
    (root / "manifest.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="pair"): load_manifest(root)


def test_inference_label_read_tripwire_is_exercised_in_separate_process(tmp_path):
    root, _ = make_public_fixture(tmp_path)
    labels = root.parent / "ground-truth.json"; labels.write_text('{"expected_category":"product_defect"}')
    code = "from pathlib import Path; from evaluation.replay import install_label_read_guard; install_label_read_guard(Path(__import__('sys').argv[1])); Path(__import__('sys').argv[2]).read_text()"
    denied = subprocess.run([sys.executable, "-c", code, str(root), str(labels)], cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert denied.returncode != 0 and "PermissionError" in denied.stderr
    allowed = subprocess.run([sys.executable, "-c", code, str(root), str(root / "manifest.json")], cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert allowed.returncode == 0


def test_real_catalog_has_distinct_mechanisms_not_numbered_template_families():
    assert len(catalog.INTERVENTIONS) == 15
    assert len({r.mechanism for r in catalog.INTERVENTIONS}) == 15
    assert len({(r.file, r.before) for r in catalog.INTERVENTIONS}) == 15
    pin = json.loads((ROOT / "integrations/ledgerguard/source.json").read_text())
    assert pin["revision"] == "13bdd62c924a3230825b6d9304f449f887c8e7fe"
    assert len(pin["files"]) == 14
    assert all(len(d) == 64 for d in pin["files"].values())


@pytest.mark.parametrize("variant", range(4))
def test_oracles_use_independent_return_value_contracts(variant):
    n = 7 + variant
    expected = [str(100+n), str(80-variant), f"{100-n},{40-n}", str(40-n), str(100+n), str((12+variant)*100+34),
                "UNBALANCED_JOURNAL", "CURRENCY_MISMATCH", "false", "false", str(20+n), "REVERSAL_FORBIDDEN", f"2026-01-{12+variant:02d}T10:30", "false", "20"]
    assert [catalog.expected_measurement(i, variant) for i in range(15)] == expected


def test_oracle_rejects_unknown_operations():
    with pytest.raises(ValueError): catalog.expected_measurement(15, 0)
    with pytest.raises(ValueError): catalog.expected_measurement(0, 4)


def row(category, predicted, severity="critical", family="a"):
    return {"expected_category": category, "modes": {"full_deterministic": predicted}, "severity": severity, "scenario_family_id": family}


def test_abstention_is_not_dangerous_dismissal_but_reduces_recall():
    m = classification_metrics([row("product_defect", "product_defect"), row("product_defect", "insufficient_evidence")], "full_deterministic")
    assert m["dangerous_dismissal"]["numerator"] == 0
    assert m["product_defect_recall"] == 0.5 and m["product_abstentions"] == 1
    assert m["non_abstained_coverage"] == 0.5
    assert m["macro_f1"] is None


def test_high_critical_gate_is_actually_severity_scoped():
    m = classification_metrics([row("product_defect", "known_flake", "low"), row("product_defect", "product_defect", "high")], "full_deterministic")
    assert m["dangerous_dismissal"]["numerator"] == 1
    assert m["critical_high_dangerous_dismissal"]["numerator"] == 0
    assert m["critical_high_dangerous_dismissal"]["denominator"] == 1


def test_broad_product_misrouting_is_separate():
    m = classification_metrics([row("product_defect", "test_defect"), row("product_defect", "infrastructure_failure")], "full_deterministic")
    assert m["product_misrouting"]["numerator"] == 2
    assert m["dangerous_dismissal"]["numerator"] == 1


def test_empty_denominators_are_unknown_not_perfect():
    assert fraction(0, 0)["rate"] is None
    assert fraction(0, 0)["wilson_95"] is None
    m = classification_metrics([], "full_deterministic")
    assert m["product_defect_recall"] is None and m["macro_f1"] is None


def test_family_resampling_does_not_count_variants_as_independent_families():
    rows = [row("product_defect", "product_defect", family="a") for _ in range(4)] + [row("product_defect", "insufficient_evidence", family="b") for _ in range(4)]
    result = family_recall_interval(rows)
    assert result["families"] == 2 and result["mean"] == 0.5
    assert result == family_recall_interval(rows)


def test_legacy_audit_exposes_template_split_leakage_without_relabeling():
    cases = []; offset = 0
    for category, count in CATEGORY_COUNTS.items():
        for i in range(count): cases.append(build_case(category, i, i//2, offset+i//2))
        offset += count//2
    before = json.dumps(cases, sort_keys=True)
    audit = audit_legacy(cases)
    assert audit["case_count"] == 200 and audit["declared_family_ids"] == 100
    assert audit["conservative_mechanism_count"] == 5
    assert len(audit["cross_split_mechanisms"]) == 5
    assert audit["generalization_claim_allowed"] is False
    assert audit["source_counts"]["ledgerguard_executed"] == 0
    assert json.dumps(cases, sort_keys=True) == before
