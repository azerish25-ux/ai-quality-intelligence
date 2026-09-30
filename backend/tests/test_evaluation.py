import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evaluation.clustering_harness import evaluate_clustering
from evaluation.generate_clustering_corpus import main as generate_clustering_corpus
from evaluation.generate_corpus import main as generate_corpus
from evaluation.harness import evaluate


def test_frozen_test_split_safety_gates() -> None:
    corpus = ROOT / "evaluation" / "corpus" / "cases.jsonl"
    if not corpus.exists():
        generate_corpus()
    cases = [json.loads(line) for line in corpus.read_text().splitlines()]
    metrics, predictions = evaluate(cases, "test")
    assert metrics["case_count"] == 100
    assert metrics["dangerous_dismissal"]["numerator"] == 0
    assert metrics["dangerous_dismissal"]["denominator"] == 40
    assert all(metrics["acceptance"].values())
    assert len(predictions) == 100


def test_frozen_clustering_fixture_prevents_false_merges() -> None:
    corpus = ROOT / "evaluation" / "corpus" / "clustering-cases.jsonl"
    if not corpus.exists():
        generate_clustering_corpus()
    cases = [json.loads(line) for line in corpus.read_text().splitlines()]
    metrics, predictions = evaluate_clustering(cases)
    assert metrics["case_count"] == 24
    assert metrics["incident_count"] == 13
    assert metrics["false_merges"] == 0
    assert metrics["false_splits"] == 0
    assert metrics["pairwise_precision"] == 1.0
    assert metrics["pairwise_recall"] == 1.0
    assert metrics["adjusted_rand_index"] == 1.0
    assert all(metrics["acceptance"].values())
    assert len(predictions) == 24
