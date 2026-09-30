"""Independent scoring and actual API replay for explicitly developmental data."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evaluation.campaign_contract import audit
from evaluation.campaign_harness import evaluate, independent_contract, render
from integrations.ledgerguard.diagnostics import KINDS, build, synthetic_observation


@pytest.mark.parametrize("kind", KINDS)
def test_independent_numeric_scorer_does_not_use_production_inspector(
    kind, monkeypatch
):
    import failurelens.contract_evidence as runtime

    monkeypatch.setattr(
        runtime,
        "inspect_contract",
        lambda *_: (_ for _ in ()).throw(AssertionError("production inspector called")),
    )
    assert independent_contract(synthetic_observation(kind, 0)) == kind


@pytest.mark.parametrize(
    "kind,changes",
    [
        ("atomic_transfer", {"receipt_request_digest": "f" * 64}),
        ("atomic_transfer", {"after_destination_minor": 75}),
        ("atomic_transfer", {"amount_minor": True}),
        ("atomic_transfer", {"before_source_minor": None}),
        ("atomic_transfer", {"concurrent_writers": 1}),
        (
            "tenant_isolation",
            {"actor_tenant_digest": "b" * 64, "resource_tenant_digest": "b" * 64},
        ),
        ("tenant_isolation", {"returned_resource_digest": None}),
        ("tenant_isolation", {"principal_scope": "administrator"}),
        ("status_expectation", {"served_contract_digest": "f" * 64}),
        ("status_expectation", {"observed_status": 500}),
        ("status_expectation", {"allowed_statuses": [200, 201]}),
        ("status_expectation", {"allowed_statuses": [200, 200]}),
        ("runner_memory_limit", {"process_role": "system_under_test"}),
        ("runner_memory_limit", {"counter_scope": "host"}),
        ("runner_memory_limit", {"oom_kills_after": 0}),
        ("runner_memory_limit", {"termination_signal": 15}),
        ("runner_memory_limit", {"peak_memory_bytes": 1}),
    ],
)
def test_independent_scorer_rejects_incomplete_conflicting_or_conforming_relations(
    kind, changes
):
    record = synthetic_observation(kind, 0)
    record["measurement"].update(changes)
    assert independent_contract(record) is None


def test_development_corpus_never_claims_held_out_minimums(tmp_path):
    root = tmp_path / "development"
    inventory = build(root)
    assert inventory["case_count"] == 20
    assert inventory["family_count"] == 4
    assert inventory["source_counts"] == {"synthetic": 20}
    assert inventory["split_counts"] == {"development": 20}
    assert not any(inventory["minimums"].values())
    with pytest.raises(ValueError):
        audit(root)
    with pytest.raises(ValueError):
        build(root)
    _, labels, public = audit(root, enforce_minimums=False)
    assert all(l.reused_development for l in labels)
    assert all("expected_category" not in c.model_dump() for c in public.cases)


@pytest.fixture(scope="module")
def development(tmp_path_factory):
    root = tmp_path_factory.mktemp("diagnostic-replay")
    corpus = root / "corpus"
    build(corpus)
    env = {
        **os.environ,
        "FAILURELENS_DATABASE_URL": f"sqlite+pysqlite:///{root}/db.sqlite",
        "FAILURELENS_ARTIFACT_ROOT": str(root / "private"),
        "FAILURELENS_DEMO_MODE": "true",
    }
    p = subprocess.run(
        [
            sys.executable,
            str(ROOT / "evaluation/replay_campaign.py"),
            "--inputs",
            str(corpus / "inputs"),
            "--output",
            str(root / "replay"),
            "--confirm-disposable-database",
        ],
        check=False,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert p.returncode == 0, p.stdout + p.stderr
    return corpus, root / "replay"


def test_real_api_worker_replay_and_independent_claims(development):
    corpus, replay = development
    m, rows = evaluate(
        corpus, replay, enforce_minimums=False, score_split="development"
    )
    assert len(rows) == 20 and not m["errors"]
    assert m["claim_checks"]["published"] == m["claim_checks"]["supported"] == 16
    assert m["integrity_acceptance"]["all_published_claims_supported"]
    assert m["citation_checks"]["resolved"]["rate"] == 1
    assert m["repeated_analysis_count"] == 5
    assert m["source_counts"] == {
        "ledgerguard_executed": 0,
        "synthetic": 20,
        "other_executed": 0,
    }
    assert m["evaluation_scope"] == "development_contract_measurement"
    assert (
        m["unknown_family_test_cases"] == 0
        and not m["held_out_acceptance"]
        and not m["full_m6_complete"]
    )
    assert m["corpus_audit"]["minimums"]["test_cases_at_least_100"] is False
    assert "Development/regression only" in render(m)
    assert "Test: 16" not in render(m)
    assert m["per_category"]["known_flake"]["support"] == 0
    assert m["corpus_audit"]["minimums"]["category_minimums"] is False


def test_evaluation_cannot_score_an_empty_test_partition(development):
    with pytest.raises(ValueError, match="empty"):
        evaluate(*development, enforce_minimums=False, score_split="test")


def test_inference_hides_no_capability_failure_as_success(client, session):
    from test_contract_evidence import bundle, ingest

    record = synthetic_observation("atomic_transfer", 0)
    record["measurement"]["after_destination_minor"] = None
    status = ingest(client, session, bundle(record))
    assert status["state"] == "succeeded"
    from failurelens.models import Failure
    from failurelens.service import analyze_and_persist
    from sqlalchemy import select

    analysis = analyze_and_persist(session, session.scalar(select(Failure)))
    assert analysis.category.value == "insufficient_evidence"
    assert (
        analysis.validation_results["diagnostic_gap"]
        == "missing_or_invalid_observations"
    )


def test_requirement_ids_are_unique_and_historical_archives_are_not_rewritten():
    import re

    ids = re.findall(
        r"^\| (R-[A-Z0-9-]+) \|",
        (ROOT / "docs/requirements-matrix.md").read_text(),
        re.MULTILINE,
    )
    assert len(ids) == len(set(ids))
    assert "R-M63-CAMPAIGN-CORPUS" in ids and "R-M63-BENCHMARK-CORPUS" in ids
    assert "R-M64-HELDOUT" in ids
