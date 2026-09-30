from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
BACKEND_SRC = ROOT.parent / "backend" / "src"
sys.path.insert(0, str(BACKEND_SRC))

from failurelens.impact import (
    IMPACT_ENGINE_VERSION,
    IMPACT_POLICY_VERSION,
    select_impacted_tests,
)
from failurelens.models import ImpactMappingEdge, ImpactTestDefinition


def _models(
    manifest: dict[str, Any],
) -> tuple[list[ImpactTestDefinition], list[ImpactMappingEdge]]:
    tests = [
        ImpactTestDefinition(
            id=f"test-{item['test_key']}",
            snapshot_id="evaluation-snapshot",
            test_key=item["test_key"],
            test_identity=item["test_identity"],
            source_path=item.get("source_path"),
            criticality=item.get("criticality", "normal"),
            mandatory=bool(item.get("mandatory", False)),
            tags=item.get("tags", []),
            estimated_duration_ms=item.get("estimated_duration_ms"),
            metadata_json={},
        )
        for item in manifest["mapping"]["tests"]
    ]
    edges = [
        ImpactMappingEdge(
            id=f"edge-{index:03d}",
            snapshot_id="evaluation-snapshot",
            source_path=item["source_path"],
            target_type=item["target_type"],
            target_value=item["target_value"],
            kind=item["kind"],
            confidence=float(item["confidence"]),
            mapping_source=item["mapping_source"],
            mapping_version=item["mapping_version"],
            metadata_json={},
        )
        for index, item in enumerate(manifest["mapping"]["edges"], start=1)
    ]
    return tests, edges


def evaluate_impact(
    cases: list[dict[str, Any]], manifest: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tests, edges = _models(manifest)
    mandatory_keys = {
        test.test_key
        for test in tests
        if test.mandatory
        or test.criticality == "critical"
        or {str(tag).casefold() for tag in test.tags}.intersection(
            {"smoke", "security", "transaction", "critical"}
        )
    }
    all_test_keys = {test.test_key for test in tests}
    predictions: list[dict[str, Any]] = []
    revealing_total = 0
    revealing_selected = 0
    critical_total = 0
    critical_selected = 0
    expected_status_matches = 0
    focused_cases = 0
    focused_selected_total = 0
    deterministic_matches = 0
    missed_examples: list[dict[str, Any]] = []

    for item in cases:
        kwargs = {
            "tests": tests,
            "edges": edges,
            "changes": item["changes"],
            "preexisting_safety_reasons": item.get("preexisting_safety_reasons", []),
        }
        result = select_impacted_tests(**kwargs)
        repeated = select_impacted_tests(**kwargs)
        selected = {
            decision["test"].test_key
            for decision in result["decisions"]
            if decision["base_selected"]
        }
        repeated_selected = {
            decision["test"].test_key
            for decision in repeated["decisions"]
            if decision["base_selected"]
        }
        if result["status"] == repeated["status"] and selected == repeated_selected:
            deterministic_matches += 1

        revealing = set(item["defect_revealing_tests"])
        revealing_total += len(revealing)
        revealing_selected += len(revealing.intersection(selected))
        critical_total += len(mandatory_keys)
        critical_selected += len(mandatory_keys.intersection(selected))
        if result["status"] == item["expected_status"]:
            expected_status_matches += 1
        if result["status"] == "FOCUSED_SUBSET":
            focused_cases += 1
            focused_selected_total += len(selected)
        missing = sorted(revealing - selected)
        if missing:
            missed_examples.append(
                {"case_id": item["case_id"], "missing_tests": missing}
            )

        predictions.append(
            {
                "case_id": item["case_id"],
                "scenario_family_id": item["scenario_family_id"],
                "expected_status": item["expected_status"],
                "predicted_status": result["status"],
                "selected_tests": sorted(selected),
                "excluded_tests": sorted(all_test_keys - selected),
                "defect_revealing_tests": sorted(revealing),
                "safety_reasons": result["safety_reasons"],
                "metrics": result["metrics"],
            }
        )

    case_count = len(cases)
    revealing_recall = revealing_selected / revealing_total if revealing_total else 1.0
    critical_recall = critical_selected / critical_total if critical_total else 1.0
    status_accuracy = expected_status_matches / case_count if case_count else 1.0
    deterministic_rate = deterministic_matches / case_count if case_count else 1.0
    average_focused_fraction = (
        focused_selected_total / (focused_cases * len(tests))
        if focused_cases and tests
        else None
    )
    fallback_count = sum(
        prediction["predicted_status"] == "FULL_SUITE_REQUIRED"
        for prediction in predictions
    )
    metrics = {
        "evaluation_version": "impact-harness-v1",
        "engine_version": IMPACT_ENGINE_VERSION,
        "policy_version": IMPACT_POLICY_VERSION,
        "case_count": case_count,
        "scenario_family_count": len({item["scenario_family_id"] for item in cases}),
        "test_catalog_count": len(tests),
        "defect_revealing_test_recall": round(revealing_recall, 6),
        "critical_test_recall": round(critical_recall, 6),
        "expected_status_accuracy": round(status_accuracy, 6),
        "deterministic_repeat_rate": round(deterministic_rate, 6),
        "focused_case_count": focused_cases,
        "fallback_case_count": fallback_count,
        "average_focused_selected_fraction": (
            round(average_focused_fraction, 6)
            if average_focused_fraction is not None
            else None
        ),
        "missed_defect_examples": missed_examples,
        "acceptance": {
            "critical_test_recall_eq_1": critical_recall == 1.0,
            "defect_revealing_test_recall_eq_1": revealing_recall == 1.0,
            "expected_status_accuracy_eq_1": status_accuracy == 1.0,
            "deterministic_repeat_rate_eq_1": deterministic_rate == 1.0,
            "zero_missed_defect_examples": not missed_examples,
        },
        "limitations": [
            *manifest.get("limitations", []),
            "Selection recall here is controlled-fixture recall, not population performance.",
            "No counterfactual production runtime savings are claimed.",
        ],
    }
    return metrics, sorted(predictions, key=lambda item: item["case_id"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus", type=Path, default=ROOT / "corpus" / "impact-cases.jsonl"
    )
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "corpus" / "impact-manifest.json"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "latest")
    args = parser.parse_args()
    cases = [
        json.loads(line)
        for line in args.corpus.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    metrics, predictions = evaluate_impact(cases, manifest)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "impact-metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output / "impact-predictions.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in predictions),
        encoding="utf-8",
    )
    report = [
        "# FailureLens deterministic change-impact evaluation",
        "",
        f"- Cases: **{metrics['case_count']}**",
        f"- Scenario families: **{metrics['scenario_family_count']}**",
        f"- Defect-revealing-test recall: **{metrics['defect_revealing_test_recall']:.3f}**",
        f"- Mandatory critical-test recall: **{metrics['critical_test_recall']:.3f}**",
        f"- Expected fallback/focused status accuracy: **{metrics['expected_status_accuracy']:.3f}**",
        f"- Focused cases: **{metrics['focused_case_count']}**",
        f"- Full-suite fallbacks: **{metrics['fallback_case_count']}**",
        "",
        "## Acceptance gates",
    ]
    report.extend(
        f"- {'PASS' if passed else 'FAIL'} — `{name}`"
        for name, passed in metrics["acceptance"].items()
    )
    report.extend(
        ["", "## Limitations"] + [f"- {item}" for item in metrics["limitations"]]
    )
    (args.output / "impact-report.md").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )
    print(json.dumps(metrics, indent=2))
    if not all(metrics["acceptance"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
