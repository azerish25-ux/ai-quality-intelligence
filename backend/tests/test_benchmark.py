"""Development-only evaluation-contract tests; never tune on held-out predictions."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evaluation.benchmark_audit import audit
from evaluation.benchmark_contract import InputRef, PublicCase, digest, load_inputs, read_input, safe_read, validate_bundle
from evaluation.benchmark_harness import domain_claim_supported, score_case
from evaluation.benchmark_labels import BenchmarkCaseLabel
from evaluation.generate_benchmark import bundle, domain, freeze
from failurelens.domain_evidence import inspect_domain


@pytest.fixture(scope="module")
def frozen(tmp_path_factory):
    path = tmp_path_factory.mktemp("benchmark-corpus-parent") / "corpus"
    freeze(path, "0ca3003472917af004fe62870221b67527cf4e71")
    return path


def test_counts_provenance_and_split_isolation(frozen):
    result = audit(frozen)
    assert result["case_count"] == 260
    assert result["family_count"] == 83
    assert result["source_counts"] == {"synthetic": 200, "ledgerguard_executed": 60}
    assert result["split_counts"] == {"development": 136, "calibration": 16, "test": 108}
    assert result["test_product_families"] == 20
    assert result["fresh_ledgerguard_executions"] == 0
    assert all(result["gates"].values())


def test_generation_is_deterministic_and_refuses_overwrite(frozen, tmp_path):
    other = tmp_path / "corpus"
    freeze(other, "0ca3003472917af004fe62870221b67527cf4e71")
    for source in frozen.rglob("*"):
        if source.is_file():
            assert source.read_bytes() == (other / source.relative_to(frozen)).read_bytes()
    with pytest.raises(ValueError, match="overwrite"):
        freeze(other, "0ca3003472917af004fe62870221b67527cf4e71")


def test_schema_matches_validated_cases(frozen):
    schema = json.loads((ROOT / "evaluation/schemas/benchmark-case.schema.json").read_text())
    schema.pop("$schema")
    assert schema == BenchmarkCaseLabel.model_json_schema()
    rows = json.loads((frozen / "ground-truth.json").read_text())
    for row in rows:
        BenchmarkCaseLabel.model_validate(row)
    with pytest.raises(ValidationError):
        BenchmarkCaseLabel.model_validate({**rows[0], "severity": True})


@pytest.mark.parametrize("field", ["expected_category", "scenario_family_id", "split", "oracle"])
def test_public_contract_refuses_current_labels(frozen, field):
    case = load_inputs(frozen / "inputs").cases[0].model_dump()
    case[field] = "product_defect"
    with pytest.raises(ValidationError):
        PublicCase.model_validate(case)


@pytest.mark.parametrize("path", ["../case.xml", "/a/c.xml", "a/../c.xml", "a\\c.xml", "a//c.xml"])
def test_public_paths_cannot_escape(path):
    with pytest.raises(ValidationError):
        InputRef(path=path, sha256="a"*64, bytes=10, source_format="junit-xml")


def test_symlink_and_size_boundaries(tmp_path):
    outside = tmp_path / "outside"; outside.write_bytes(b"private")
    inside = tmp_path / "in"; inside.mkdir()
    (inside / "link").symlink_to(outside)
    with pytest.raises(ValueError):
        safe_read(inside, "link")
    (inside / "large").write_bytes(b"x"*20)
    with pytest.raises(ValueError):
        safe_read(inside, "large", 10)


def test_artifact_digest_is_checked_before_inference(frozen):
    ref = load_inputs(frozen / "inputs").cases[0].current.model_copy(update={"sha256": "f"*64})
    with pytest.raises(ValueError, match="digest"):
        read_input(frozen / "inputs", ref)


def test_unmanifested_file_is_rejected():
    import io, zipfile
    data, count = bundle("check::test", "observed", "facts")
    buffer = io.BytesIO(data)
    with zipfile.ZipFile(buffer, "a") as z:
        z.writestr("answers.json", b'{"category":"product_defect"}')
    with pytest.raises(ValueError):
        validate_bundle(buffer.getvalue(), count)


@pytest.mark.parametrize("kind", ["operation_identity", "projection_order", "weekly_recurrence"])
def test_independent_numeric_rubric(kind):
    value = domain(kind, "check::test", 0)
    finding = inspect_domain(value)
    claim = {"kind": "inference", "predicate": finding.predicate, "text": finding.claim}
    assert domain_claim_supported(claim, value)
    assert not domain_claim_supported({**claim, "text": "The service is definitely defective."}, value)
    assert not domain_claim_supported(claim, domain(kind, "check::test", 0, control=True))
    assert not domain_claim_supported({**claim, "predicate": {}}, value)


@pytest.fixture(scope="module")
def development_replay(frozen, tmp_path_factory):
    # Select only declared development cases; test predictions remain uninspected.
    labels = json.loads((frozen / "ground-truth.json").read_text())
    chosen = []
    for category in ("known_flake", "infrastructure_failure", "test_defect", "insufficient_evidence"):
        chosen.append(next(r["case_id"] for r in labels if r["expected_category"] == category and r["split"] == "development"))
    for kind in ("operation_identity", "projection_order", "weekly_recurrence"):
        chosen.append(next(r["case_id"] for r in labels if r.get("domain_kind") == kind and r["split"] == "development"))
    chosen.append(next(r["case_id"] for r in labels if r["source_kind"] == "ledgerguard_executed"))
    root = tmp_path_factory.mktemp("benchmark-development-run")
    output = root / "replay"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend/src"),
           "FAILURELENS_DATABASE_URL": "sqlite+pysqlite:///" + str(root / "db.sqlite"),
           "FAILURELENS_ARTIFACT_ROOT": str(root / "artifacts"), "FAILURELENS_DEMO_MODE": "true"}
    completed = subprocess.run([sys.executable, str(ROOT / "evaluation/benchmark_replay.py"), "--inputs", str(frozen / "inputs"),
        "--output", str(output), "--case-ids", ",".join(chosen), "--confirm-disposable-database"], env=env, cwd=ROOT,
        capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    replay = json.loads((output / "predictions.json").read_text())
    return frozen, output, replay, {r["case_id"]: r for r in labels}


def test_real_development_pipeline_and_prior_only_history(development_replay):
    corpus, output, replay, truth = development_replay
    public = {c.case_id: c for c in load_inputs(corpus / "inputs").cases}
    assert replay["network_connect_denied"] and replay["network_attempt_count"] == 0
    for row in replay["cases"]:
        assert truth[row["case_id"]]["split"] == "development"
        result = score_case(truth[row["case_id"]], public[row["case_id"]], row, corpus / "inputs", output)
        assert result["supported_claims"] == result["claim_count"]
        assert result["temporal_unchanged"]
        if truth[row["case_id"]]["expected_category"] == "known_flake":
            assert result["modes"]["full_deterministic"] == "known_flake"
            assert row["history"]["independent_runs"] == 5
            assert row["prior_reviews"]


@pytest.mark.parametrize("change", ["repetition", "foreign_run", "foreign_execution", "empty_claim", "derivative_digest", "scope_digest"])
def test_independent_scoring_rejects_forged_evidence(development_replay, change):
    corpus, output, replay, truth = development_replay
    row = deepcopy(next(r for r in replay["cases"] if r["published"]["category"] == "product_defect"))
    public = next(c for c in load_inputs(corpus / "inputs").cases if c.case_id == row["case_id"])
    if change == "repetition": row["repeat_digests"][0] = "f"*64
    elif change == "foreign_run": row["evidence"][0]["run_id"] = "foreign"
    elif change == "foreign_execution": row["evidence"][0]["execution_id"] = "foreign"
    elif change == "derivative_digest": row["evidence"][0]["sha256"] = "f"*64
    elif change == "scope_digest": row["evidence"][0]["artifact_digest"] = "f"*64
    elif change == "empty_claim":
        from evaluation.benchmark_replay import substantive_hash
        row["published"]["claims"] = []
        row["repeat_digests"] = [substantive_hash(row["published"])]*5
    with pytest.raises(ValueError):
        score_case(truth[row["case_id"]], public, row, corpus / "inputs", output)


@pytest.mark.parametrize("change", ["policy", "family", "hash", "case_label", "retained_oracle"])
def test_frozen_audit_rejects_tampering(frozen, tmp_path, change):
    import shutil
    corpus = tmp_path / "corpus"; shutil.copytree(frozen, corpus)
    name = "policy.json" if change == "policy" else "ground-truth.json"
    content = json.loads((corpus / name).read_text())
    if change == "policy": content["product_recall_minimum"] = 0
    elif change == "hash": content[0]["root_cause"] = "changed"
    elif change == "case_label": content[0]["expected_category"] = "arbitrary-category"
    elif change == "family":
        family = next(r["scenario_family_id"] for r in content if r["split"] == "test")
        next(r for r in content if r["scenario_family_id"] == family)["split"] = "development"
    elif change == "retained_oracle":
        next(r for r in content if r["source_kind"] == "ledgerguard_executed")["observed"] = "forged"
    (corpus / name).write_text(json.dumps(content))
    if change != "hash":
        freeze_doc = json.loads((corpus / "freeze.json").read_text())
        freeze_doc["file_sha256"][name] = digest((corpus / name).read_bytes())
        (corpus / "freeze.json").write_text(json.dumps(freeze_doc))
    with pytest.raises(ValueError): audit(corpus)


@pytest.mark.parametrize("member", ["../escape", "/absolute", "unexpected.txt", "reports/../escape", "reports\\bad"])
def test_snapshot_extraction_rejects_unsafe_paths(tmp_path, member):
    import zipfile
    from evaluation.verify_benchmark_snapshot import extract_snapshot
    source = tmp_path / "snapshot.zip"
    with zipfile.ZipFile(source, "w") as z: z.writestr(member, "not authorized")
    destination = tmp_path / "extracted"; destination.mkdir()
    with pytest.raises(ValueError): extract_snapshot(source, destination)


def test_label_read_tripwire_is_exercised_out_of_process(frozen):
    script = '''
from pathlib import Path
from evaluation.replay import install_label_read_guard
root=Path(__import__('sys').argv[1])
install_label_read_guard(root/'inputs')
(root/'inputs/manifest.json').read_bytes()
try:
    (root/'ground-truth.json').read_bytes()
except PermissionError:
    print('blocked')
else:
    raise AssertionError('Inference unexpectedly read ground truth')
'''
    completed = subprocess.run([sys.executable, "-c", script, str(frozen)], cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "blocked"
