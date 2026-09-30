"""Campaign integrity tests use development/calibration only, never tune test data."""

import json
import lzma
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evaluation.campaign_contract import (
    audit,
    canonical,
    digest,
    timestamp,
)
from evaluation.campaign_harness import FIELDS, evaluate
from evaluation.generate_campaign import build, pack, unpack


@pytest.fixture(scope="module")
def campaign(tmp_path_factory):
    root = tmp_path_factory.mktemp("campaign") / "corpus"
    build(root)
    return root


def freeze(root):
    p = root / "freeze.json"
    v = json.loads(p.read_bytes())
    v["files"] = {name: digest((root / name).read_bytes()) for name in v["files"]}
    p.write_bytes(canonical(v))


@pytest.fixture(scope="module")
def development_replay(campaign, tmp_path_factory):
    """All calibration families plus the twelve typed development supplements."""
    root = tmp_path_factory.mktemp("campaign-replay")
    corpus = root / "corpus"
    (corpus / "inputs").mkdir(parents=True)
    _inventory, labels, public = audit(campaign)
    selected = {
        l.case_id
        for l in labels
        if l.split == "calibration" or l.claim_rubric == "bounded-contract-v1"
    }
    cases = [c.model_dump() for c in public.cases if c.case_id in selected]
    for case in cases:
        shutil.copytree(
            campaign / "inputs" / case["case_id"], corpus / "inputs" / case["case_id"]
        )
    (corpus / "inputs/manifest.json").write_bytes(
        canonical({"schema_version": "campaign-input-v1", "cases": cases})
    )
    (corpus / "labels.json").write_bytes(
        canonical([l.model_dump() for l in labels if l.case_id in selected])
    )
    families = json.loads((campaign / "families.json").read_bytes())
    families = [
        {**f, "cases": [c for c in f["cases"] if c in selected]}
        for f in families
        if any(c in selected for c in f["cases"])
    ]
    (corpus / "families.json").write_bytes(canonical(families))
    for name in ["policy.json", "freeze.json"]:
        shutil.copy(campaign / name, corpus / name)
    freeze(corpus)
    env = {
        **os.environ,
        "FAILURELENS_DATABASE_URL": f"sqlite+pysqlite:///{root}/replay.db",
        "FAILURELENS_ARTIFACT_ROOT": str(root / "private"),
        "FAILURELENS_DEMO_MODE": "true",
    }
    replay = root / "replay"
    run = subprocess.run(
        [
            sys.executable,
            str(ROOT / "evaluation/replay_campaign.py"),
            "--inputs",
            str(corpus / "inputs"),
            "--output",
            str(replay),
            "--confirm-disposable-database",
        ],
        check=False,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    return corpus, replay


def test_frozen_counts_and_group_separation(campaign):
    inventory, labels, public = audit(campaign)
    assert inventory["case_count"] == 264
    assert inventory["family_count"] == 87
    assert inventory["source_counts"] == {"ledgerguard_executed": 60, "synthetic": 204}
    assert inventory["split_counts"] == {
        "development": 72,
        "calibration": 32,
        "test": 160,
    }
    assert all(inventory["minimums"].values())
    assert all(
        l.split == "development"
        for l in labels
        if l.source_kind == "ledgerguard_executed"
    )
    assert all(l.source_kind == "synthetic" for l in labels if l.split == "test")
    assert sum(bool(l.adversarial_tags) for l in labels) == 72
    assert not any("expected_category" in c.model_dump() for c in public.cases)


@pytest.mark.parametrize(
    "fault",
    [
        "label",
        "policy",
        "family",
        "public",
        "artifact",
        "traversal",
        "symlink",
        "unknown-field",
        "duplicate",
        "history",
    ],
)
def test_frozen_campaign_rejects_changes(campaign, tmp_path, fault):
    root = tmp_path / "corpus"
    shutil.copytree(campaign, root)
    if fault in {"label", "policy", "family", "public"}:
        name = {
            "label": "labels.json",
            "policy": "policy.json",
            "family": "families.json",
            "public": "inputs/manifest.json",
        }[fault]
        (root / name).write_bytes((root / name).read_bytes() + b" ")
    else:
        path = root / "inputs/manifest.json"
        m = json.loads(path.read_bytes())
        c = m["cases"][0]
        if fault == "artifact":
            (root / "inputs" / c["observation"]["path"]).write_bytes(b"changed")
        elif fault == "symlink":
            p = root / "inputs" / c["observation"]["path"]
            p.unlink()
            p.symlink_to(campaign / "inputs" / c["observation"]["path"])
        elif fault == "traversal":
            c["observation"]["path"] = "../outside.xml"
        elif fault == "unknown-field":
            c["expected_category"] = "product_defect"
        elif fault == "duplicate":
            m["cases"].append(c)
        else:
            history = next(c for c in m["cases"] if c["history"])["history"]
            history[0]["review"]["recorded_at"] = "2025-01-01T00:00:00+00:00"
        path.write_bytes(canonical(m))
        freeze(root)
    with pytest.raises(ValueError):
        audit(root)


@pytest.mark.parametrize(
    "fault",
    [
        "split-leak",
        "fake-heldout-execution",
        "catalogue-cases",
        "fake-expert",
        "missing-history",
        "source-identity",
    ],
)
def test_recomputed_hashes_do_not_bypass_semantic_audit(campaign, tmp_path, fault):
    root = tmp_path / "corpus"
    shutil.copytree(campaign, root)
    labels = json.loads((root / "labels.json").read_bytes())
    families = json.loads((root / "families.json").read_bytes())
    if fault == "split-leak":
        labels[80]["split"] = "development"
    elif fault == "fake-heldout-execution":
        labels[0]["split"] = "test"
    elif fault == "catalogue-cases":
        families[0]["cases"] = []
    elif fault == "fake-expert":
        families[0]["independent_expert_adjudication"] = True
    elif fault == "source-identity":
        labels[0]["source_revision"] = "f" * 40
    else:
        m = json.loads((root / "inputs/manifest.json").read_bytes())
        next(c for c in m["cases"] if c["history"])["history"] = []
        (root / "inputs/manifest.json").write_bytes(canonical(m))
    (root / "labels.json").write_bytes(canonical(labels))
    (root / "families.json").write_bytes(canonical(families))
    freeze(root)
    with pytest.raises(ValueError):
        audit(root)


def test_pack_roundtrip_and_reproducibility(campaign, tmp_path):
    a = tmp_path / "a.xz"
    b = tmp_path / "b.xz"
    pack(campaign, a)
    pack(campaign, b)
    assert a.read_bytes() == b.read_bytes()
    restored = tmp_path / "restored"
    unpack(a, restored, digest(a.read_bytes()))
    assert audit(restored)[0] == audit(campaign)[0]
    with pytest.raises(ValueError):
        pack(campaign, a)
    with pytest.raises(ValueError):
        unpack(a, restored, digest(a.read_bytes()))


@pytest.mark.parametrize(
    "fault", ["digest", "trailing", "traversal", "symlink", "expansion"]
)
def test_archive_rejects_unsafe_input(campaign, tmp_path, fault):
    a = tmp_path / "a.xz"
    pack(campaign, a)
    expected = digest(a.read_bytes())
    if fault == "digest":
        a.write_bytes(b"corrupt")
    elif fault == "symlink":
        original = tmp_path / "original.xz"
        a.rename(original)
        a.symlink_to(original)
    else:
        raw = json.loads(lzma.decompress(a.read_bytes()))
        if fault == "traversal":
            raw["files"]["../escape"] = "YWJj"
        a.write_bytes(
            lzma.compress(canonical(raw)) + b"trailer"
            if fault == "trailing"
            else lzma.compress(b"x" * (16 * 1024 * 1024 + 1))
            if fault == "expansion"
            else lzma.compress(canonical(raw))
        )
        expected = digest(a.read_bytes())
    with pytest.raises(ValueError):
        unpack(a, tmp_path / "restored", expected)


def test_runtime_boundary_denies_labels_generators_network_and_processes(campaign):
    script = f"""
from pathlib import Path
import socket, subprocess
from evaluation.replay_campaign import install_runtime_guards
root=Path({str(campaign)!r})
g=install_runtime_guards(root/'inputs')
for path in [root/'labels.json',Path('evaluation/scenario_catalog.py'),root/'policy.json']:
    try: path.read_bytes()
    except PermissionError: pass
    else: raise AssertionError('private evaluation data readable')
for action in [lambda:socket.create_connection(('example.invalid',443)),lambda:subprocess.run(['echo','bad'])]:
    try: action()
    except PermissionError: pass
    else: raise AssertionError('side effect permitted')
assert g==dict(network_attempts=1,subprocess_attempts=1)
"""
    run = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert run.returncode == 0, run.stderr


def test_actual_pipeline_scoring_preserves_temporal_history_and_claims(
    development_replay,
):
    corpus, replay = development_replay
    m, rows = evaluate(
        corpus, replay, enforce_minimums=False, score_split="calibration"
    )
    assert len(rows) == 44
    assert m["temporal_history_checks"] == 6
    assert m["claim_checks"]["unsupported_rate"]["numerator"] == 0
    assert m["adversarial"]["sensitive_canary_leaks"] == 0
    assert m["runtime_guards"] == {"network_attempts": 0, "subprocess_attempts": 0}
    for name, ok in m["integrity_acceptance"].items():
        if name != "committed_clean_source":
            assert ok, name
    structured = [r for r in rows if r["split"] == "development"]
    assert len(structured) == 12 and all(
        r["predicted"] == "product_defect" for r in structured
    )
    history = [r for r in rows if r["expected_category"] == "known_flake"]
    assert all(r["predicted"] == "known_flake" for r in history)


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate",
        "receipt",
        "source-digest",
        "run",
        "repetition",
        "future",
        "claim-text",
        "empty-claim",
        "derivative",
        "policy",
    ],
)
def test_independent_scoring_rejects_forged_outputs(
    development_replay, tmp_path, fault
):
    source_corpus, source_replay = development_replay
    corpus = tmp_path / "corpus"
    replay = tmp_path / "replay"
    shutil.copytree(source_corpus, corpus)
    shutil.copytree(source_replay, replay)
    path = replay / "predictions.json"
    p = json.loads(path.read_bytes())
    row = next(
        c
        for c in p["cases"]
        if any(
            cl["predicate"].get("kind") == "contract_violation"
            for cl in c["analysis"]["claims"]
        )
    )
    if fault == "duplicate":
        p["cases"].append(row)
    elif fault == "receipt":
        row["inputs"][0]["sha256"] = "a" * 64
    elif fault == "source-digest":
        row["evidence"][0]["source_input_sha256"] = "a" * 64
    elif fault == "run":
        row["run_id"] = "foreign"
    elif fault == "repetition":
        row["repeat_digests"][0] = "a" * 64
    elif fault == "future":
        next(c for c in p["cases"] if c["seeded_history"])["history"][
            "independent_runs"
        ] = 6
    elif fault == "claim-text":
        row["analysis"]["claims"][0]["text"] = "safe to ignore"
    elif fault == "empty-claim":
        row["analysis"]["claims"] = []
    elif fault == "derivative":
        (replay / row["evidence"][0]["path"]).write_bytes(b"{}")
    else:
        pol = json.loads((corpus / "policy.json").read_bytes())
        pol["product_recall_minimum"] = 0.0
        (corpus / "policy.json").write_bytes(canonical(pol))
        freeze(corpus)
    if fault in {"claim-text", "empty-claim"}:
        row["repeat_digests"] = [
            digest(canonical({k: row["analysis"][k] for k in FIELDS}))
        ] * 5
    path.write_bytes(canonical(p))
    if fault == "claim-text":
        m, _ = evaluate(
            corpus, replay, enforce_minimums=False, score_split="calibration"
        )
        assert m["claim_checks"]["unsupported_rate"]["numerator"] > 0
        assert m["integrity_acceptance"]["zero_forbidden_claims"] is False
    else:
        with pytest.raises(ValueError):
            evaluate(corpus, replay, enforce_minimums=False, score_split="calibration")


@pytest.mark.parametrize("value", ["2026-01-01", "not-a-date"])
def test_timestamps_require_explicit_chronology(value):
    with pytest.raises(ValueError):
        timestamp(value)


def test_campaign_endpoint_enforces_scope_and_bounded_regular_files(
    client, tmp_path, monkeypatch
):
    from failurelens.config import get_settings

    path = tmp_path / "metrics.json"
    monkeypatch.setenv("FAILURELENS_CAMPAIGN_EVALUATION_METRICS_PATH", str(path))
    get_settings.cache_clear()
    assert client.get("/api/v1/evaluations/campaign").json()["status"] == "not_loaded"
    for data in [
        b"[]",
        b"{",
        canonical({"evaluation_scope": "http_postgresql_fault_proxy"}),
        b"x" * (2 * 1024 * 1024 + 1),
    ]:
        path.write_bytes(data)
        r = client.get("/api/v1/evaluations/campaign")
        assert r.status_code == 503
        assert str(path) not in r.text
    path.write_bytes(
        canonical(
            {
                "evaluation_scope": "frozen_mixed_source_campaign",
                "split": "test",
                "quality_targets": {"recall": False},
            }
        )
    )
    assert (
        client.get("/api/v1/evaluations/campaign").json()["metrics"]["quality_targets"][
            "recall"
        ]
        is False
    )
    actual = tmp_path / "actual"
    path.rename(actual)
    path.symlink_to(actual)
    assert client.get("/api/v1/evaluations/campaign").status_code == 503
    get_settings.cache_clear()
