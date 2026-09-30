from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND_SRC = ROOT.parent / "backend" / "src"
sys.path.insert(0, str(BACKEND_SRC))

from failurelens.analysis import EvidenceView, analyze_failure
from failurelens.redaction import redact_text

CATEGORIES = [
    "product_defect",
    "test_defect",
    "infrastructure_failure",
    "known_flake",
    "insufficient_evidence",
]


def wilson(
    successes: int, total: int, z: float = 1.959963984540054
) -> list[float] | None:
    if total == 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return [max(0.0, centre - margin), min(1.0, centre + margin)]


def evaluate(cases: list[dict], split: str) -> tuple[dict, list[dict]]:
    selected = [case for case in cases if split == "all" or case["split"] == split]
    confusion = {truth: {pred: 0 for pred in CATEGORIES} for truth in CATEGORIES}
    predictions: list[dict] = []
    forbidden = 0
    sensitive_leaks = 0
    for case in selected:
        payload = case["input"]
        redacted_message = redact_text(payload["message"]).text
        evidence = [
            EvidenceView(
                id=f"{case['case_id']}-ev-{index}",
                kind="current_run_observation",
                excerpt=redact_text(text).text,
                observation={},
            )
            for index, text in enumerate(payload["evidence"])
        ]
        decision = analyze_failure(
            message=redacted_message,
            exception_type=payload.get("exception_type"),
            details=payload["details"],
            evidence=evidence,
            historical=payload["historical"],
        )
        predicted = decision.category.value
        truth = case["expected_category"]
        confusion[truth][predicted] += 1
        published = " ".join(
            [decision.summary, decision.explanation]
            + [claim.get("text", "") for claim in decision.claims]
        )
        case_forbidden = [
            phrase
            for phrase in case["forbidden_claims"]
            if phrase.casefold() in published.casefold()
        ]
        forbidden += len(case_forbidden)
        leaked = "synthetic-canary-token-123456" in published
        sensitive_leaks += int(leaked)
        predictions.append(
            {
                "case_id": case["case_id"],
                "split": case["split"],
                "family": case["scenario_family_id"],
                "expected": truth,
                "predicted": predicted,
                "severity": case["severity"],
                "score": decision.score,
                "score_kind": decision.score_kind,
                "policy_flags": list(decision.policy_flags),
                "forbidden_claims": case_forbidden,
                "sensitive_canary_leaked": leaked,
            }
        )

    per_category = {}
    for category in CATEGORIES:
        tp = confusion[category][category]
        fp = sum(
            confusion[other][category] for other in CATEGORIES if other != category
        )
        fn = sum(
            confusion[category][other] for other in CATEGORIES if other != category
        )
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = (
            2 * precision * recall / (precision + recall) if precision + recall else 0.0
        )
        per_category[category] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": tp + fn,
        }

    product_total = sum(confusion["product_defect"].values())
    dangerous = (
        confusion["product_defect"]["known_flake"]
        + confusion["product_defect"]["infrastructure_failure"]
    )
    misrouting = dangerous + confusion["product_defect"]["test_defect"]
    non_abstention_truth_total = sum(sum(confusion[c].values()) for c in CATEGORIES[:4])
    non_abstained = sum(
        sum(confusion[c][p] for p in CATEGORIES[:4]) for c in CATEGORIES[:4]
    )
    metrics = {
        "evaluation_version": "harness-v1",
        "split": split,
        "case_count": len(selected),
        "family_count": len({case["scenario_family_id"] for case in selected}),
        "source_counts": dict(Counter(case["source_kind"] for case in selected)),
        "confusion_matrix": confusion,
        "per_category": per_category,
        "macro_f1": sum(item["f1"] for item in per_category.values()) / len(CATEGORIES),
        "dangerous_dismissal": {
            "numerator": dangerous,
            "denominator": product_total,
            "rate": dangerous / product_total if product_total else None,
            "wilson_95": wilson(dangerous, product_total),
        },
        "product_misrouting": {
            "numerator": misrouting,
            "denominator": product_total,
            "rate": misrouting / product_total if product_total else None,
        },
        "product_defect_recall": per_category["product_defect"]["recall"],
        "product_abstentions": confusion["product_defect"]["insufficient_evidence"],
        "non_abstained_coverage": non_abstained / non_abstention_truth_total
        if non_abstention_truth_total
        else None,
        "forbidden_claim_occurrences": forbidden,
        "sensitive_canary_leaks": sensitive_leaks,
        "acceptance": {
            "zero_critical_high_dangerous_dismissals": dangerous == 0,
            "dangerous_dismissal_rate_lte_0_05": dangerous / product_total <= 0.05
            if product_total
            else False,
            "product_recall_gte_0_90": per_category["product_defect"]["recall"] >= 0.90,
            "macro_f1_gte_0_80": sum(item["f1"] for item in per_category.values())
            / len(CATEGORIES)
            >= 0.80,
            "non_abstained_coverage_gte_0_75": (
                non_abstained / non_abstention_truth_total
            )
            >= 0.75
            if non_abstention_truth_total
            else False,
            "zero_forbidden_claims": forbidden == 0,
            "zero_sensitive_canary_leaks": sensitive_leaks == 0,
        },
        "limitations": [
            "Metrics are from a synthetic, public, agent-authored controlled corpus.",
            "No actual LedgerGuard executions are represented in this revision.",
            "A zero observed dangerous-dismissal count is not proof of zero deployment risk.",
        ],
    }
    return metrics, predictions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=ROOT / "corpus" / "cases.jsonl")
    parser.add_argument(
        "--split", choices=["development", "calibration", "test", "all"], default="test"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "latest")
    args = parser.parse_args()
    cases = [
        json.loads(line)
        for line in args.corpus.read_text().splitlines()
        if line.strip()
    ]
    metrics, predictions = evaluate(cases, args.split)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n"
    )
    (args.output / "predictions.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in predictions)
    )
    report = [
        "# FailureLens deterministic evaluation",
        "",
        f"- Split: `{metrics['split']}`",
        f"- Cases: **{metrics['case_count']}** across **{metrics['family_count']}** families",
        f"- Dangerous dismissal: **{metrics['dangerous_dismissal']['numerator']}/{metrics['dangerous_dismissal']['denominator']}**",
        f"- Product-defect recall: **{metrics['product_defect_recall']:.3f}**",
        f"- Macro F1: **{metrics['macro_f1']:.3f}**",
        f"- Non-abstained coverage: **{metrics['non_abstained_coverage']:.3f}**",
        f"- Forbidden claims: **{metrics['forbidden_claim_occurrences']}**",
        f"- Sensitive canary leaks: **{metrics['sensitive_canary_leaks']}**",
        "",
        "## Acceptance gates",
    ]
    report.extend(
        f"- {'PASS' if value else 'FAIL'} — `{name}`"
        for name, value in metrics["acceptance"].items()
    )
    report.extend(
        ["", "## Limitations"] + [f"- {item}" for item in metrics["limitations"]]
    )
    (args.output / "report.md").write_text("\n".join(report) + "\n")
    print(json.dumps(metrics, indent=2))
    if not all(metrics["acceptance"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
