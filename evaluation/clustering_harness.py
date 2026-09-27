from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
BACKEND_SRC = ROOT.parent / "backend" / "src"
sys.path.insert(0, str(BACKEND_SRC))

from failurelens.clustering import (  # noqa: E402
    ALGORITHM_VERSION,
    FEATURE_VERSION,
    feature_from_observation,
    pairwise_cluster_metrics,
    propose_clusters_from_features,
)
from failurelens.fingerprint import make_fingerprint  # noqa: E402


def evaluate_clustering(cases: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    features = []
    truth: dict[str, str] = {}
    case_by_id: dict[str, dict[str, Any]] = {}
    for item in cases:
        payload = item["input"]
        strict_fingerprint, loose_features = make_fingerprint(
            payload["message"], payload.get("exception_type"), payload.get("details")
        )
        feature = feature_from_observation(
            failure_id=item["case_id"],
            project_id="clustering-evaluation",
            run_id=f"run-{item['case_id']}",
            repository=payload.get("repository"),
            external_id=payload["external_id"],
            run_attempt=int(payload.get("run_attempt", 1)),
            strict_fingerprint=strict_fingerprint,
            message=payload["message"],
            exception_type=payload.get("exception_type"),
            details=payload.get("details") or {},
            loose_features=loose_features,
            source_path=payload.get("source_path"),
            browser=payload.get("browser"),
            test_identity=payload["test_identity"],
        )
        features.append(feature)
        truth[item["case_id"]] = item["incident_id"]
        case_by_id[item["case_id"]] = item

    proposals = propose_clusters_from_features(features)
    predicted: dict[str, str] = {}
    predictions: list[dict[str, Any]] = []
    for proposal_index, proposal in enumerate(proposals, start=1):
        predicted_id = f"predicted-{proposal_index:03d}-{proposal.cluster_key[:10]}"
        for member in proposal.members:
            case_id = member.feature.failure_id
            predicted[case_id] = predicted_id
            predictions.append({
                "case_id": case_id,
                "incident_id": truth[case_id],
                "predicted_cluster": predicted_id,
                "role": member.role,
                "similarity_score": member.score.total,
                "matching_signals": list(member.score.matching_signals),
                "conflicting_signals": list(member.score.conflicting_signals),
                "scenario_family_id": case_by_id[case_id]["scenario_family_id"],
            })

    metrics = pairwise_cluster_metrics(predicted, truth)
    metrics.update({
        "evaluation_version": "clustering-harness-v1",
        "algorithm_version": ALGORITHM_VERSION,
        "feature_version": FEATURE_VERSION,
        "incident_count": len(set(truth.values())),
        "predicted_cluster_count": len(proposals),
        "singleton_cluster_count": sum(len(proposal.members) == 1 for proposal in proposals),
        "acceptance": {
            "pairwise_precision_gte_0_95": metrics["pairwise_precision"] >= 0.95,
            "pairwise_recall_gte_0_90": metrics["pairwise_recall"] >= 0.90,
            "zero_false_merges": metrics["false_merges"] == 0,
            "false_splits_lte_1": metrics["false_splits"] <= 1,
            "adjusted_rand_index_gte_0_90": metrics["adjusted_rand_index"] >= 0.90,
            "zero_missing_predictions": metrics["missing_predictions"] == 0,
            "zero_unexpected_predictions": metrics["unexpected_predictions"] == 0,
        },
        "limitations": [
            "All cases are synthetic and agent-authored.",
            "Incident labels are evaluation-only and are excluded from runtime clustering features.",
            "The fixture emphasizes collision boundaries and bridge prevention rather than production prevalence.",
            "Screenshot similarity and causal edge quality are not measured in this milestone.",
        ],
    })
    return metrics, sorted(predictions, key=lambda item: item["case_id"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus",
        type=Path,
        default=ROOT / "corpus" / "clustering-cases.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "latest",
    )
    args = parser.parse_args()
    cases = [json.loads(line) for line in args.corpus.read_text(encoding="utf-8").splitlines() if line.strip()]
    metrics, predictions = evaluate_clustering(cases)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "clustering-metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output / "clustering-predictions.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in predictions),
        encoding="utf-8",
    )
    report = [
        "# FailureLens deterministic clustering evaluation",
        "",
        f"- Cases: **{metrics['case_count']}**",
        f"- Evaluation-only incident labels: **{metrics['incident_count']}**",
        f"- Predicted clusters: **{metrics['predicted_cluster_count']}**",
        f"- Pairwise precision: **{metrics['pairwise_precision']:.3f}**",
        f"- Pairwise recall: **{metrics['pairwise_recall']:.3f}**",
        f"- False merges: **{metrics['false_merges']}**",
        f"- False splits: **{metrics['false_splits']}**",
        f"- Adjusted Rand index: **{metrics['adjusted_rand_index']:.3f}**",
        "",
        "## Acceptance gates",
    ]
    report.extend(
        f"- {'PASS' if passed else 'FAIL'} — `{name}`"
        for name, passed in metrics["acceptance"].items()
    )
    report.extend(["", "## Limitations"] + [f"- {item}" for item in metrics["limitations"]])
    (args.output / "clustering-report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    if not all(metrics["acceptance"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
