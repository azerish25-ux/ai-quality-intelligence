"""Score independently executed cases AFTER a separate, label-free application replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from evaluation.artifact_contract import load_manifest, read_artifact

CATEGORIES = (
    "product_defect",
    "test_defect",
    "infrastructure_failure",
    "known_flake",
    "insufficient_evidence",
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def wilson(numerator: int, denominator: int) -> list[float] | None:
    if not denominator:
        return None
    z = 1.959963984540054
    p = numerator / denominator
    d = 1 + z * z / denominator
    center = (p + z * z / (2 * denominator)) / d
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * denominator)) / denominator) / d
    return [max(0, center - margin), min(1, center + margin)]


def fraction(n: int, d: int) -> dict:
    return {
        "numerator": n,
        "denominator": d,
        "rate": n / d if d else None,
        "wilson_95": wilson(n, d),
    }


def classification_metrics(rows: list[dict], mode: str) -> dict:
    confusion = {a: {b: 0 for b in CATEGORIES} for a in CATEGORIES}
    for row in rows:
        confusion[row["expected_category"]][row["modes"][mode]] += 1
    per_class = {}
    for category in CATEGORIES:
        support = sum(confusion[category].values())
        tp = confusion[category][category]
        predicted = sum(confusion[c][category] for c in CATEGORIES)
        precision = tp / predicted if predicted else None
        recall = tp / support if support else None
        f1 = 2 * tp / (support + predicted) if support + predicted else None
        per_class[category] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }
    products = [r for r in rows if r["expected_category"] == "product_defect"]
    dangerous = [
        r
        for r in products
        if r["modes"][mode] in {"known_flake", "infrastructure_failure"}
    ]
    high = [r for r in products if r["severity"] in {"critical", "high"}]
    truth_non_abstention = [
        r for r in rows if r["expected_category"] != "insufficient_evidence"
    ]
    return {
        "case_count": len(rows),
        "confusion_matrix": confusion,
        "per_category": per_class,
        "macro_f1": sum(per_class[c]["f1"] or 0 for c in CATEGORIES) / len(CATEGORIES)
        if all(per_class[c]["support"] for c in CATEGORIES)
        else None,
        "macro_f1_status": "available"
        if all(per_class[c]["support"] for c in CATEGORIES)
        else "not_applicable_missing_true_categories",
        "dangerous_dismissal": fraction(len(dangerous), len(products)),
        "critical_high_dangerous_dismissal": fraction(
            sum(r["severity"] in {"critical", "high"} for r in dangerous), len(high)
        ),
        "product_misrouting": fraction(
            sum(
                r["modes"][mode]
                in {"test_defect", "known_flake", "infrastructure_failure"}
                for r in products
            ),
            len(products),
        ),
        "product_defect_recall": per_class["product_defect"]["recall"],
        "product_abstentions": sum(
            r["modes"][mode] == "insufficient_evidence" for r in products
        ),
        "abstentions": fraction(
            sum(r["modes"][mode] == "insufficient_evidence" for r in rows), len(rows)
        ),
        "non_abstained_coverage": sum(
            r["modes"][mode] != "insufficient_evidence" for r in truth_non_abstention
        )
        / len(truth_non_abstention)
        if truth_non_abstention
        else None,
    }


def family_recall_interval(rows: list[dict]) -> dict:
    groups: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        if row["expected_category"] == "product_defect":
            groups[row["scenario_family_id"]].append(
                int(row["modes"]["full_deterministic"] == "product_defect")
            )
    rates = [sum(v) / len(v) for _, v in sorted(groups.items())]
    if not rates:
        return {"method": "family-bootstrap", "interval": None, "families": 0}
    rng = random.Random(20260928)
    sampled = sorted(
        statistics.mean(rng.choices(rates, k=len(rates))) for _ in range(2000)
    )
    return {
        "method": "equal-family percentile bootstrap; 2000 draws; seed 20260928",
        "families": len(rates),
        "mean": statistics.mean(rates),
        "interval": [sampled[49], sampled[1949]],
        "limitation": "Descriptive resampling of agent-selected mechanisms, not a population guarantee or blinded benchmark.",
    }


def evaluate(corpus: Path, replay_dir: Path, policy: dict) -> tuple[dict, list[dict]]:
    provenance = json.loads((corpus / "provenance.json").read_bytes())
    truth_bytes = (corpus / "ground-truth.json").read_bytes()
    manifest_bytes = (corpus / "inputs/manifest.json").read_bytes()
    replay = json.loads((replay_dir / "predictions.json").read_bytes())
    if (
        sha(truth_bytes) != provenance["ground_truth_sha256"]
        or sha(manifest_bytes) != provenance["input_manifest_sha256"]
    ):
        raise ValueError("frozen corpus provenance mismatch")
    if replay["input_manifest_sha256"] != provenance["input_manifest_sha256"]:
        raise ValueError("predictions were produced from a different input manifest")
    public_manifest = load_manifest(corpus / "inputs")
    for case in public_manifest.cases:
        for artifact in case.inputs:
            read_artifact(corpus / "inputs", artifact)
    labels = json.loads(truth_bytes)["cases"]
    if (
        replay.get("schema_version") != "artifact-replay-result-v1"
        or replay.get("case_count") != len(labels)
        or type(replay.get("repeats")) is not int
        or not 1 <= replay["repeats"] <= 10
    ):
        raise ValueError("invalid replay count or version contract")
    if not labels or len(labels) != provenance["case_count"]:
        raise ValueError("empty corpus or inconsistent provenance count")
    predictions = {r["case_id"]: r for r in replay["cases"]}
    if len(predictions) != len(replay["cases"]) or len(
        {c["case_id"] for c in labels}
    ) != len(labels):
        raise ValueError("duplicate prediction or ground-truth case")
    if set(predictions) != {c["case_id"] for c in labels}:
        raise ValueError("missing or unexpected predictions")
    public_cases = {r["case_id"]: r for r in json.loads(manifest_bytes)["cases"]}
    if set(public_cases) != set(predictions):
        raise ValueError("public manifest and prediction cases differ")
    if (
        provenance.get("family_count") != len({c["scenario_family_id"] for c in labels})
        or provenance.get("control_passes") != len(labels)
        or provenance.get("intervention_failures") != len(labels)
    ):
        raise ValueError("producer family/control/intervention counts differ")
    rows = []
    citations = Counter()
    forbidden = 0
    leaked = 0
    for label in labels:
        if (
            label["expected_category"] not in CATEGORIES
            or label["source_kind"] != "ledgerguard_executed"
            or label["execution_scope"] != "production_component"
        ):
            raise ValueError("invalid executed label/source contract")
        if (
            not label["control_passed"]
            or not label["intervention_failed"]
            or label["control"] != label["expected"]
            or label["observed"] == label["expected"]
        ):
            raise ValueError(
                "independent control/intervention oracle did not establish the fault"
            )
        prediction = predictions[label["case_id"]]
        if prediction.get("repeat_count") != replay["repeats"]:
            raise ValueError("per-case repetition evidence differs from aggregate")
        if {i.get("role") for i in prediction["inputs"]} != {
            "control",
            "observation",
        } or set(prediction["ablation_categories"]) != {
            "rules_only",
            "rules_with_history",
            "full_deterministic",
        }:
            raise ValueError("incomplete control/observation or comparison contract")
        if len(prediction["inputs"]) != 2 or len(prediction["analyses"]) != 1:
            raise ValueError("expected one control and one failed intervention")
        public = public_cases[label["case_id"]]
        for item in prediction["inputs"]:
            reference = next(
                (a for a in public["inputs"] if a["role"] == item["role"]), None
            )
            if (
                not reference
                or reference["sha256"] != item["sha256"]
                or item["state"] != "succeeded"
                or not item["idempotent_replay"]
            ):
                raise ValueError("unverified ingestion/duplicate replay")
            expected_count = 0 if item["role"] == "control" else 1
            if item["failure_count"] != expected_count:
                raise ValueError(
                    "parser outcome does not match independently verified producer outcome"
                )
        analysis = prediction["analyses"][0]
        mode_categories = {
            **prediction["ablation_categories"],
            "constant_product_baseline": "product_defect",
        }
        if mode_categories.get("full_deterministic") != analysis["category"] or any(
            v not in CATEGORIES for v in mode_categories.values()
        ):
            raise ValueError("category/report mismatch")
        checks = {
            r["evidence_id"]: r for r in prediction["integrity_checks"]["evidence"]
        }
        exported = {r["id"]: r for r in prediction["evidence"]}
        ids = set(
            analysis["supporting_evidence_ids"] + analysis["contradictory_evidence_ids"]
        )
        for claim in analysis["claims"]:
            ids.update(claim.get("evidence_ids", []))
        for evidence_id in ids:
            citations["total"] += 1
            check = checks.get(evidence_id, {})
            exported_item = exported.get(evidence_id)
            if not exported_item:
                raise ValueError(
                    "published citation has no exported inspectable evidence"
                )
            path = replay_dir / exported_item["path"]
            if path.is_symlink() or not path.resolve().is_relative_to(
                replay_dir.resolve()
            ):
                raise ValueError("unsafe exported evidence path")
            content = path.read_bytes()
            safe = json.loads(content)
            if (
                sha(content) != exported_item["sha256"]
                or safe["excerpt"] != exported_item["excerpt"]
            ):
                raise ValueError("exported evidence changed after inference")
            for metric, fields in (
                (
                    "reference_valid",
                    (
                        "reference_valid",
                        "authorized",
                        "digest_valid",
                        "locator_valid",
                        "policy_safe",
                    ),
                ),
                ("quotation_accurate", ("quotation_valid",)),
                ("typed_observation_valid", ("observation_valid",)),
            ):
                citations[metric] += int(all(check.get(f) is True for f in fields))
        # Score published output, not generator assertions or hidden labels.
        published = json.dumps(
            {
                k: analysis[k]
                for k in ("summary", "claims", "hypotheses", "next_investigation")
            },
            sort_keys=True,
        )
        hits = [
            p for p in label["forbidden_claims"] if p.casefold() in published.casefold()
        ]
        forbidden += len(hits)
        leaked += int("synthetic-canary-token-123456" in published)
        verified_claims = sum(
            c.get("validation_status") == "verified"
            and c.get("validation", {}).get("semantic_support") is True
            for c in analysis["claims"]
        )
        rows.append(
            {
                k: label[k]
                for k in (
                    "case_id",
                    "expected_category",
                    "scenario_family_id",
                    "severity",
                    "source_kind",
                    "execution_scope",
                )
            }
            | {
                "modes": mode_categories,
                "predicted": analysis["category"],
                "abstention_reason": analysis["abstention_reason"],
                "claim_count": len(analysis["claims"]),
                "verified_claim_count": verified_claims,
                "forbidden_claims": hits,
                "repeat_count": prediction["repeat_count"],
                "advisory_hold": prediction["advisory_hold"],
                "seconds": prediction["seconds"],
                "evidence_count": len(ids),
            }
        )
    modes = {
        mode: classification_metrics(rows, mode)
        for mode in (
            "constant_product_baseline",
            "rules_only",
            "rules_with_history",
            "full_deterministic",
        )
    }
    metrics = modes["full_deterministic"].copy()
    family_count = len({r["scenario_family_id"] for r in rows})
    metrics.update(
        {
            "evaluation_version": "executed-component-v1",
            "evaluation_scope": "production_component_challenge",
            "source_counts": {
                kind: sum(r["source_kind"] == kind for r in rows)
                for kind in ("ledgerguard_executed", "synthetic", "other_executed")
            },
            "family_count": family_count,
            "source_revision": provenance["failurelens_revision"],
            "source_worktree_dirty": provenance["failurelens_worktree_dirty"],
            "ledgerguard_revision": provenance["ledgerguard_revision"],
            "producer_java_version": provenance["java_version"],
            "harness_digests": provenance["harness_files"],
            "manifest_sha256": provenance["input_manifest_sha256"],
            "ground_truth_sha256": provenance["ground_truth_sha256"],
            "policy_sha256": sha(json.dumps(policy, sort_keys=True).encode()),
            "database_dialect": replay["database_dialect"],
            "control_passes": len(rows),
            "intervention_failures": len(rows),
            "source_provenance_verified": True,
            "generalization_claim_allowed": False,
            "full_m6_complete": False,
            "by_severity": {
                s: classification_metrics(
                    [r for r in rows if r["severity"] == s], "full_deterministic"
                )
                for s in sorted({r["severity"] for r in rows})
            },
            "by_family": {
                f: classification_metrics(
                    [r for r in rows if r["scenario_family_id"] == f],
                    "full_deterministic",
                )
                for f in sorted({r["scenario_family_id"] for r in rows})
            },
            "family_recall_uncertainty": family_recall_interval(rows),
            "comparisons": modes,
            "citation_checks": {
                name: fraction(citations[name], citations["total"])
                for name in (
                    "reference_valid",
                    "quotation_accurate",
                    "typed_observation_valid",
                )
            },
            "semantic_support_scope": "Application deterministic typed-predicate validation, not independent universal semantic/hallucination scoring.",
            "forbidden_claim_occurrences": forbidden,
            "sensitive_canary_leaks": leaked,
            "canary_scope": "No canary challenge is included in this production-component slice; zero is not a redaction-recall claim.",
            "repeated_analysis_count": replay["repeats"],
            "substantive_repeat_agreement": True,
            "wall_seconds": replay["wall_seconds"],
            "per_case_p95_seconds": sorted(r["seconds"] for r in rows)[
                math.ceil(0.95 * len(rows)) - 1
            ],
            "cost": {
                "provider_mode": "deterministic",
                "external_api_calls": 0,
                "external_api_spend": 0,
                "currency": "USD",
                "compute_cost": "not_measured",
            },
            "limitations": [
                "Real production-component execution only: no HTTP, PostgreSQL business transactions, rollback, concurrency, or committed-money oracle in LedgerGuard.",
                "All 60 cases are product defects. Five-class macro F1 and nonproduct precision/generalization are not established by this slice.",
                "The constant-product baseline is intentionally trivial on this one-category challenge; a perfect baseline does not validate diagnosis.",
                "This agent-authored public challenge is not a blinded/frozen test split. Inspected failures become regression evidence, never fresh held-out evidence.",
                "Four variants share each of 15 mechanisms. Case-level Wilson intervals assume independence and are only an illustration; family resampling is also limited.",
                "The old 200-case synthetic regression suite is not silently relabeled as real execution or independent scenario families.",
                "The full M6 200-case/80-independent-family, five-category leakage-controlled benchmark remains incomplete.",
                "Repeated API analysis recomputes the deterministic decision, but is not five independent whole-stack performance runs.",
                "Raw controlled producer artifacts and exported safe derivatives have finite CI retention; API UUID links require the originating database.",
            ],
        }
    )
    metrics["claim_checks"] = {
        "typed_supported_published_claims": fraction(
            sum(r["verified_claim_count"] for r in rows),
            sum(r["claim_count"] for r in rows),
        ),
        "rubric": "application typed predicates, not independent causal adjudication",
    }
    metrics["integrity_acceptance"] = {
        "minimum_executed_cases": len(rows) >= policy["minimum_executed_cases"],
        "minimum_executed_families": family_count
        >= policy["minimum_executed_families"],
        "all_controls_pass_and_interventions_fail": True,
        "all_citations_verified": citations["total"] > 0
        and all(
            citations[x] == citations["total"]
            for x in (
                "reference_valid",
                "quotation_accurate",
                "typed_observation_valid",
            )
        ),
        "five_repeated_analyses": replay["repeats"] >= policy["repeats"],
        "no_critical_high_dangerous_dismissal": metrics[
            "critical_high_dangerous_dismissal"
        ]["numerator"]
        == 0,
        "no_forbidden_claims": forbidden == 0,
        "all_published_claims_typed_verified": all(
            r["verified_claim_count"] == r["claim_count"] for r in rows
        ),
        "all_failures_hold_for_review": all(r["advisory_hold"] for r in rows),
    }
    metrics["quality_targets"] = {
        "dangerous_dismissal_lte_5_percent": metrics["dangerous_dismissal"]["rate"]
        <= policy["dangerous_dismissal_maximum"],
        "product_recall_gte_90_percent": metrics["product_defect_recall"]
        >= policy["product_defect_recall_target"],
        "non_abstained_coverage_gte_75_percent": metrics["non_abstained_coverage"]
        >= policy["non_abstained_coverage_target"],
    }
    return metrics, rows


def render_report(metrics: dict, rows: list[dict]) -> str:
    d = metrics["dangerous_dismissal"]
    lines = [
        "# LedgerGuard production-component challenge",
        "",
        "**Scope: executed M6 component slice, not full M6 acceptance.**",
        "",
        f"FailureLens source: `{metrics['source_revision']}`; dirty working tree: `{metrics['source_worktree_dirty']}`.",
        f"LedgerGuard source: `{metrics['ledgerguard_revision']}`.",
        f"Database for the real FailureLens API/worker replay: `{metrics['database_dialect']}`.",
        "",
        f"{metrics['case_count']} executed interventions across {metrics['family_count']} independent mechanisms; {metrics['control_passes']} passing controls.",
        f"Dangerous dismissals: **{d['numerator']}/{d['denominator']}**. Product recall: **{metrics['product_defect_recall']:.3f}**. Product abstentions: **{metrics['product_abstentions']}**.",
        "Five-category macro F1: **not established** (this slice has only product-defect ground truth).",
        "",
        "## Executable integrity gates",
        *[
            f"- {'PASS' if v else 'FAIL'} — {k}"
            for k, v in metrics["integrity_acceptance"].items()
        ],
        "",
        "## Measured quality targets",
        *[
            f"- {'PASS' if v else 'FAIL'} — {k}"
            for k, v in metrics["quality_targets"].items()
        ],
        "",
        "The integrity workflow checks truthful execution, safe publication and recovery. It does not convert a failed quality target into a pass. `--enforce-quality` fails for unmet targets.",
        "",
        "## Baselines and ablations",
        "| Mode | Product recall | Product abstentions | Dangerous dismissals |",
        "|---|---:|---:|---:|",
    ]
    for name, m in metrics["comparisons"].items():
        lines.append(
            f"| {name} | {m['product_defect_recall']:.3f} | {m['product_abstentions']} | {m['dangerous_dismissal']['numerator']}/{m['dangerous_dismissal']['denominator']} |"
        )
    lines += ["", "## Cases requiring review"]
    lines.extend(
        f"- `{r['case_id']}` — {r['scenario_family_id']}: `{r['predicted']}`; {r['abstention_reason'] or 'no abstention'}"
        for r in rows
        if r["predicted"] != r["expected_category"]
    )
    lines += ["", "## Limits", *[f"- {s}" for s in metrics["limitations"]], ""]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", required=True, type=Path)
    p.add_argument("--replay", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument(
        "--policy", type=Path, default=ROOT / "policies/ledgerguard-component-v1.json"
    )
    p.add_argument("--enforce-quality", action="store_true")
    args = p.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit("Refusing to overwrite a previous evaluation report")
    metrics, rows = evaluate(
        args.corpus.resolve(),
        args.replay.resolve(),
        json.loads(args.policy.read_bytes()),
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "metrics.json").write_text(
        json.dumps(metrics, sort_keys=True, indent=2) + "\n"
    )
    (args.output / "predictions.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
    )
    (args.output / "report.md").write_text(render_report(metrics, rows))
    print(
        json.dumps(
            {
                k: metrics[k]
                for k in (
                    "case_count",
                    "family_count",
                    "database_dialect",
                    "dangerous_dismissal",
                    "product_defect_recall",
                    "product_abstentions",
                    "integrity_acceptance",
                    "quality_targets",
                )
            },
            indent=2,
        )
    )
    if not all(metrics["integrity_acceptance"].values()):
        raise SystemExit(1)
    if args.enforce_quality and not all(metrics["quality_targets"].values()):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
