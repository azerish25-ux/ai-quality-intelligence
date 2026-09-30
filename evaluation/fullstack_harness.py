"""Independently rescore the development-only HTTP/PostgreSQL retry experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "integrations/ledgerguard"))
from fullstack_oracle import verify_pair_observation

from evaluation.artifact_contract import (
    load_manifest,
    read_artifact,
    validate_public_bundle,
)
from evaluation.executed_harness import classification_metrics

SUBSTANTIVE = (
    "category",
    "severity",
    "confidence",
    "summary",
    "claims",
    "policy_flags",
    "abstention_reason",
    "supporting_evidence_ids",
    "contradictory_evidence_ids",
)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def bounded_json(path: Path):
    if path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Unsafe or oversized evaluation JSON")
    return json.loads(path.read_bytes())


def safe_path(root: Path, name: str) -> Path:
    path = root / name
    if (
        path.is_symlink()
        or any(p.is_symlink() for p in path.parents if p.is_relative_to(root))
        or not path.resolve().is_relative_to(root.resolve())
    ):
        raise ValueError("Evidence path escapes retained replay")
    return path


def evaluate(corpus: Path, replay_dir: Path) -> tuple[dict, list[dict]]:
    manifest = load_manifest(corpus / "inputs")
    if manifest.schema_version != "artifact-replay-v2":
        raise ValueError(
            "Full-stack scorer requires the multi-artifact replay contract"
        )
    provenance = bounded_json(corpus / "provenance.json")
    labels = bounded_json(corpus / "ground-truth.json")
    replay = bounded_json(replay_dir / "predictions.json")
    if replay["input_manifest_sha256"] != digest(
        (corpus / "inputs/manifest.json").read_bytes()
    ):
        raise ValueError("Replay is not for this frozen input manifest")
    if provenance.get("source_dirty") is not False:
        raise ValueError("Source provenance is not a clean committed revision")
    if (
        len(manifest.cases) != 4
        or len(labels) != 4
        or replay.get("case_count") != 4
        or len(replay["cases"]) != 4
    ):
        raise ValueError("The declared four control/intervention pairs are incomplete")
    predictions = {row["case_id"]: row for row in replay["cases"]}
    ground_truth = {row["case_id"]: row for row in labels}
    if set(predictions) != set(ground_truth) or set(predictions) != {
        c.case_id for c in manifest.cases
    }:
        raise ValueError("Duplicate or mismatched cases")
    rows = []
    inspection = []
    evidence_count = claim_count = 0
    for case in manifest.cases:
        prediction = predictions[case.case_id]
        truth = ground_truth[case.case_id]
        if (
            case.source_revision != provenance["ledgerguard_revision"]
            or truth.get("split") != "development"
            or truth.get("scenario_family_id") != "lost-response-retry-key-corruption"
            or truth.get("source_kind") != "ledgerguard_executed"
        ):
            raise ValueError("Case source, family or split provenance is inconsistent")
        roles = {r["role"]: r for r in truth["roles"]}
        if len(truth["roles"]) != 2 or set(roles) != {"control", "observation"}:
            raise ValueError("Missing role ground truth")
        if prediction.get("repeat_count") != 5 or replay.get("repeats") != 5:
            raise ValueError("Five deterministic repetitions were not retained")
        if len(set(prediction["run_links"].values())) != 2 or set(
            prediction["run_links"]
        ) != {"control", "observation"}:
            raise ValueError(
                "Control and intervention were not isolated into distinct runs"
            )
        evidence = {item["id"]: item for item in prediction["evidence"]}
        if len(evidence) != len(prediction["evidence"]):
            raise ValueError("Duplicated evidence references")
        if len(prediction["inputs"]) != 2 or any(
            row["state"] != "succeeded"
            or row["failure_count"] != 1
            or row["idempotent_replay"] is not True
            for row in prediction["inputs"]
        ):
            raise ValueError("The API ingestion or duplicate replay did not succeed")
        if {row["role"]: row["sha256"] for row in prediction["inputs"]} != {
            ref.role: ref.sha256 for ref in case.inputs
        }:
            raise ValueError(
                "Ingestion role/digest records disagree with the public bundles"
            )
        for ref in case.inputs:
            truth_role = roles[ref.role]
            files = validate_public_bundle(
                read_artifact(corpus / "inputs", ref), ref.expected_inputs
            )
            value = json.loads(files["measurements.json"])
            oracle = verify_pair_observation(
                value,
                truth_role["wire_requests"],
                expected_effects=1 if ref.role == "control" else 2,
            )
            if (
                oracle != truth_role["oracle"]
                or truth_role["input_digest"] != ref.sha256
                or truth_role["global_reconciliation"] != "PASS"
            ):
                raise ValueError("Independent oracle/provenance mismatch")
            analyses = prediction["role_analyses"][ref.role]
            if len(analyses) != 1:
                raise ValueError("Expected exactly one transport failure per role")
            analysis = analyses[0]
            repeats = prediction["repeat_digests"].get(ref.role)
            expected_hash = digest(
                json.dumps(
                    {key: analysis[key] for key in SUBSTANTIVE}, sort_keys=True
                ).encode()
            )
            if repeats != [[expected_hash] * 5]:
                raise ValueError("Substantive repetition evidence disagrees")
            # Resolve exported derivatives and independently tie measurements to
            # this specific role's producer bytes, not merely to any valid ID.
            corresponding = []
            for item in evidence.values():
                path = safe_path(replay_dir, item["path"])
                data = path.read_bytes()
                if len(data) > 256 * 1024 or digest(data) != item["sha256"]:
                    raise ValueError("Safe derivative digest/size mismatch")
                payload = json.loads(data)
                if payload["excerpt"] != item["excerpt"]:
                    raise ValueError("Quoted excerpt does not match the derivative")
                measured = payload.get("observation", {}).get("transaction_observation")
                if measured == value:
                    if payload["source_locator"].get("sha256") != digest(
                        files["measurements.json"]
                    ):
                        raise ValueError(
                            "Numeric evidence is not tied to actual producer bytes"
                        )
                    corresponding.append(item["id"])
            if len(corresponding) != 1:
                raise ValueError("No unique authorized derivative for this role")
            evidence_count += 1
            if len(analysis["claims"]) != (
                1 if analysis["category"] == "product_defect" else 0
            ):
                raise ValueError(
                    "Published classification lacks the required bounded claim record"
                )
            for claim in analysis["claims"]:
                if (
                    claim.get("predicate")
                    != {
                        "kind": "committed_effect_multiplicity",
                        "count": oracle["committed_effects"],
                    }
                    or claim.get("evidence_ids") != corresponding
                    or claim.get("validation_status") != "verified"
                    or oracle["committed_effects"] <= 1
                    or claim.get("kind") != "inference"
                    or claim.get("text")
                    != (
                        f"Reported request and database measurements reconcile {oracle['committed_effects']} committed effects "
                        "for one retried logical request; this supports a product-defect investigation without establishing the responsible component."
                    )
                ):
                    raise ValueError(
                        "Published claim is unsupported by the independent numeric oracle"
                    )
                claim_count += 1
            report = safe_path(
                replay_dir, "reports/" + case.case_id + "-" + ref.role + ".md"
            )
            if "HOLD_FOR_REVIEW" not in report.read_text():
                raise ValueError("A failed observation lost the advisory review hold")
            expected = (
                "product_defect"
                if ref.role == "observation"
                else "insufficient_evidence"
            )
            if truth_role["expected_category"] != expected:
                raise ValueError("Ground truth was relabeled")
            rows.append(
                {
                    "case_id": case.case_id,
                    "role": ref.role,
                    "expected_category": expected,
                    "severity": "critical" if ref.role == "observation" else "medium",
                    "scenario_family_id": truth["scenario_family_id"],
                    "modes": {"full_deterministic": analysis["category"]},
                }
            )
            inspection.append(
                {
                    "case_id": case.case_id,
                    "role": ref.role,
                    "run_id": prediction["run_links"][ref.role],
                    "analysis_id": analysis["analysis_id"],
                    "category": analysis["category"],
                    "committed_effects": oracle["committed_effects"],
                    "evidence_ids": corresponding,
                    "report": "reports/" + case.case_id + "-" + ref.role + ".md",
                }
            )
    metrics = classification_metrics(rows, "full_deterministic")
    product_rows = [r for r in rows if r["role"] == "observation"]
    controls = [r for r in rows if r["role"] == "control"]
    product_metrics = classification_metrics(product_rows, "full_deterministic")
    metrics.update(
        {
            "evaluation_version": "fullstack-retry-v1",
            "evaluation_scope": "http_postgresql_fault_proxy",
            "source_revision": provenance["source_revision"],
            "ledgerguard_revision": provenance["ledgerguard_revision"],
            "database_dialect": replay["database_dialect"],
            "family_count": 1,
            "paired_scenarios": 4,
            "split": "development",
            "source_counts": {
                "ledgerguard_executed": 8,
                "synthetic": 0,
                "other_executed": 0,
            },
            "by_family": {"lost-response-retry-key-corruption": product_metrics},
            "control_case_count": len(controls),
            "control_abstentions": sum(
                r["modes"]["full_deterministic"] == "insufficient_evidence"
                for r in controls
            ),
            "product_abstentions": product_metrics["product_abstentions"],
            "verified_numeric_evidence": evidence_count,
            "verified_claim_count": claim_count,
            "inspection": inspection,
            "limitations": provenance["limitations"],
            "provider_mode": "deterministic",
            "external_model_requests": 0,
            "compute_cost": None,
            "input_manifest_sha256": replay["input_manifest_sha256"],
            "replay_sha256": digest((replay_dir / "predictions.json").read_bytes()),
            "corpus_provenance_sha256": digest(
                (corpus / "provenance.json").read_bytes()
            ),
            "wall_seconds": replay["wall_seconds"],
        }
    )
    metrics["integrity_acceptance"] = {
        "independent_http_sql_oracles": True,
        "role_isolation_and_bundle_idempotency": True,
        "five_identical_substantive_repetitions": True,
        "producer_bound_authorized_derivatives": evidence_count == 8,
        "all_reports_advisory_hold": True,
        "zero_dangerous_critical_dismissals": product_metrics["dangerous_dismissal"][
            "numerator"
        ]
        == 0,
        "postgresql_pipeline": replay["database_dialect"] == "postgresql",
    }
    metrics["quality_targets"] = {
        "product_recall_at_least_90_percent": product_metrics["product_defect_recall"]
        >= 0.90,
        "dangerous_dismissal_at_most_5_percent": product_metrics["dangerous_dismissal"][
            "rate"
        ]
        <= 0.05,
        "coverage_at_least_75_percent": product_metrics["non_abstained_coverage"]
        >= 0.75,
        "all_transport_only_controls_abstain": metrics["control_abstentions"] == 4,
        "five_category_macro_f1_at_least_0_80": None,
    }
    return metrics, rows


def render(metrics):
    return "\n".join(
        [
            "# M6.2 HTTP/PostgreSQL retry experiment",
            "",
            f"Tested FailureLens: `{metrics['source_revision']}`; LedgerGuard: `{metrics['ledgerguard_revision']}`.",
            "",
            f"Development pairs: {metrics['paired_scenarios']}; distinct mechanisms: 1; total role observations: 8.",
            f"Product recall: {metrics['product_defect_recall']}; product abstentions: {metrics['product_abstentions']}; dangerous dismissals: {metrics['dangerous_dismissal']['numerator']}/4.",
            f"Transport-only controls with cautious abstention: {metrics['control_abstentions']}/4.",
            "",
            "The unmodified companion is not alleged to be defective; the deliberate fault is key corruption in the retry proxy.",
            "These measurements do not replace the older 80% component challenge or establish full M6 acceptance.",
            "",
            "## Execution/integrity gates",
            *[
                f"- {'PASS' if v else 'FAIL'}: {k}"
                for k, v in metrics["integrity_acceptance"].items()
            ],
            "",
            "## Unchanged scoped quality targets",
            *[
                f"- {'NOT ESTABLISHED' if v is None else 'PASS' if v else 'FAIL'}: {k}"
                for k, v in metrics["quality_targets"].items()
            ],
            "",
            "## Limitations",
            *metrics["limitations"],
            "",
            "Saved API UUID links require the originating database. The retained safe derivatives and Markdown reports remain inspectable offline.",
            "",
        ]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Refusing to overwrite historical evaluation results")
    metrics, rows = evaluate(args.corpus.resolve(), args.replay.resolve())
    args.output.mkdir(parents=True)
    (args.output / "metrics.json").write_text(
        json.dumps(metrics, sort_keys=True, indent=2) + "\n"
    )
    (args.output / "predictions.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
    )
    (args.output / "report.md").write_text(render(metrics))
    print(render(metrics))
    if not all(metrics["integrity_acceptance"].values()):
        raise SystemExit(1)
    if any(value is False for value in metrics["quality_targets"].values()):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
