from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from failurelens.performance import evaluate_performance_fixture_case

ROOT = Path(__file__).resolve().parent
DEFAULT_CASES = ROOT / "corpus" / "performance-cases.jsonl"


def load_cases(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate(cases: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    predictions: list[dict[str, Any]] = []
    repeated_predictions: list[dict[str, Any]] = []
    for case in cases:
        prediction = evaluate_performance_fixture_case(case)
        replay = evaluate_performance_fixture_case(case)
        prediction["expected_status"] = case["expected_status"]
        prediction["correct"] = prediction["status"] == case["expected_status"]
        prediction["tags"] = case.get("tags", [])
        predictions.append(prediction)
        repeated_predictions.append(replay)

    case_count = len(predictions)
    correct = sum(1 for item in predictions if item["correct"])
    regressions = [item for item in predictions if item["expected_status"] == "REGRESSION"]
    dangerous_false_negatives = [
        item for item in regressions if item["status"] != "REGRESSION"
    ]
    compatibility_cases = [
        item for item in predictions
        if item["expected_status"] in {"BASELINE_UNAVAILABLE", "INCOMPATIBLE_BASELINE"}
    ]
    compatibility_correct = sum(1 for item in compatibility_cases if item["correct"])
    citation_valid = sum(
        1
        for item in predictions
        if item["current_evidence_id"]
        and all(item["baseline_evidence_ids"])
        and len(item["baseline_evidence_ids"]) == len(item["accepted_run_ids"])
    )
    deterministic = sum(
        1
        for first, second in zip(predictions, repeated_predictions, strict=True)
        if {
            key: first[key]
            for key in (
                "status", "accepted_run_ids", "baseline_value", "canonical_unit",
                "absolute_change", "relative_change", "aggregation", "significance_claimed"
            )
        }
        == {
            key: second[key]
            for key in (
                "status", "accepted_run_ids", "baseline_value", "canonical_unit",
                "absolute_change", "relative_change", "aggregation", "significance_claimed"
            )
        }
    )
    status_counts = Counter(item["status"] for item in predictions)
    metrics = {
        "schema_version": "performance-evaluation-result-v1",
        "case_count": case_count,
        "status_accuracy": correct / case_count if case_count else 0,
        "regression_recall": (
            (len(regressions) - len(dangerous_false_negatives)) / len(regressions)
            if regressions else None
        ),
        "dangerous_false_negative": {
            "numerator": len(dangerous_false_negatives),
            "denominator": len(regressions),
            "case_ids": [item["case_id"] for item in dangerous_false_negatives],
        },
        "compatibility_selection_accuracy": (
            compatibility_correct / len(compatibility_cases)
            if compatibility_cases else None
        ),
        "evidence_citation_validity": citation_valid / case_count if case_count else 0,
        "deterministic_repeat_agreement": deterministic / case_count if case_count else 0,
        "statistical_significance_claims": sum(
            1 for item in predictions if item["significance_claimed"]
        ),
        "non_median_baseline_aggregations": sum(
            1 for item in predictions if item["aggregation"] != "median_of_run_level_observations"
        ),
        "status_counts": dict(sorted(status_counts.items())),
        "limitations": [
            "The fixture is synthetic and agent-authored.",
            "The result measures deterministic safety behavior, not population-level production accuracy.",
            "No exported percentile is averaged or represented as an aggregate percentile.",
        ],
    }
    return predictions, metrics


def render_report(metrics: dict[str, Any]) -> str:
    dangerous = metrics["dangerous_false_negative"]
    return "\n".join(
        [
            "# FailureLens performance evaluation",
            "",
            "Controlled synthetic compatibility and regression fixture.",
            "",
            f"- Cases: **{metrics['case_count']}**",
            f"- Status accuracy: **{metrics['status_accuracy']:.3f}**",
            f"- Regression recall: **{metrics['regression_recall']:.3f}**",
            f"- Dangerous false negatives: **{dangerous['numerator']}/{dangerous['denominator']}**",
            f"- Compatibility-selection accuracy: **{metrics['compatibility_selection_accuracy']:.3f}**",
            f"- Evidence-citation validity: **{metrics['evidence_citation_validity']:.3f}**",
            f"- Deterministic repeat agreement: **{metrics['deterministic_repeat_agreement']:.3f}**",
            f"- Statistical-significance claims: **{metrics['statistical_significance_claims']}**",
            f"- Non-median baseline aggregations: **{metrics['non_median_baseline_aggregations']}**",
            "",
            "## Limitations",
            "",
            *[f"- {item}" for item in metrics["limitations"]],
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = load_cases(args.cases)
    predictions, metrics = evaluate(cases)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "performance-predictions.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in predictions),
        encoding="utf-8",
    )
    (args.output / "performance-metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output / "performance-report.md").write_text(render_report(metrics), encoding="utf-8")
    print(json.dumps(metrics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
