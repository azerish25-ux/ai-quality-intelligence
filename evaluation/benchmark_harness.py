"""Independently score published benchmark decisions after answer-free replay.

Generic classifications use the declared controlled-scenario rubric, not a claim
of universal semantic verification. Numeric domain claims are checked against
producer observations without importing the runtime analyzer or its predicates.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import re
import statistics
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from evaluation.benchmark_audit import audit
from evaluation.benchmark_contract import digest, load_inputs, read_input, safe_read, unique_json, validate_bundle
from evaluation.executed_harness import classification_metrics, fraction, family_recall_interval

MODES=("constant_product_baseline","rules_only","rules_with_history","full_deterministic")
SUBSTANTIVE=("category","severity","confidence","summary","claims","policy_flags","abstention_reason","supporting_evidence_ids","contradictory_evidence_ids")
CATEGORY_TEXT={"product_defect":"probable product defect","test_defect":"probable test defect",
               "infrastructure_failure":"probable infrastructure or environment failure","known_flake":"known flaky behavior"}
CANARY="failurelens-canary-do-not-disclose-abcdef0123456789"


def stored_utc(value: str) -> datetime:
    """SQLAlchemy's SQLite adapter returns stored UTC timestamps without offsets."""
    stamp = datetime.fromisoformat(value)
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)


def reported_domain_shape(value: dict) -> bool:
    """Check producer types independently; booleans and omitted fields are not measurements."""
    common = {"schema_version", "kind", "contract", "test_identity", "attempt", "browser"}
    fields = {
        "operation_identity": {"scope_digest", "payload_digest", "first_operation", "second_operation", "first_fingerprint", "second_fingerprint"},
        "projection_order": {"entity_digest", "before_version", "event_version", "after_version", "before_state_digest", "event_state_digest", "after_state_digest"},
        "weekly_recurrence": {"timezone", "previous_occurrence", "next_occurrence"},
    }
    kind = value.get("kind")
    if (not isinstance(kind, str) or kind not in fields or set(value) != common | fields[kind]
            or value.get("schema_version") != "domain-observations-v1"
            or not isinstance(value.get("test_identity"), str) or not 1 <= len(value["test_identity"]) <= 240
            or type(value.get("attempt")) is not int or not 0 <= value["attempt"] <= 20
            or not (value.get("browser") is None or isinstance(value["browser"], str) and len(value["browser"]) <= 80)):
        return False
    def is_digest(item):
        return isinstance(item, str) and re.fullmatch(r"[0-9a-f]{64}", item) is not None
    if kind == "operation_identity":
        return (all(is_digest(value[k]) for k in ("scope_digest", "payload_digest", "first_fingerprint", "second_fingerprint"))
                and all(isinstance(value[k], str) and 1 <= len(value[k]) <= 120
                        and re.fullmatch(r"[A-Za-z0-9_.:/-]+", value[k]) is not None
                        for k in ("first_operation", "second_operation")))
    if kind == "projection_order":
        return (all(type(value[k]) is int and 0 <= value[k] <= 2**53-1 for k in ("before_version", "event_version", "after_version"))
                and all(is_digest(value[k]) for k in ("entity_digest", "before_state_digest", "event_state_digest", "after_state_digest")))
    return all(isinstance(value[k], str) and 1 <= len(value[k]) <= 80 for k in ("timezone", "previous_occurrence", "next_occurrence"))


def domain_claim_supported(claim: dict, value: dict) -> bool:
    """Evaluation-only arithmetic/calendar rubric, independent of runtime checks."""
    if not isinstance(claim, dict) or not isinstance(value, dict) or not reported_domain_shape(value):
        return False
    predicate=claim.get("predicate",{})
    kind=value.get("kind")
    if not isinstance(predicate, dict) or predicate.get("kind")!="reported_domain_invariant" or predicate.get("invariant")!=kind:
        return False
    try:
        if kind=="operation_identity":
            expected={"kind":"reported_domain_invariant","invariant":kind}
            valid=(value["contract"]=="operation-is-part-of-request-identity-v1"
                   and value["first_operation"]!=value["second_operation"] and value["first_fingerprint"] is not None
                   and value["first_fingerprint"]==value["second_fingerprint"])
            text=("Reported fingerprints coincide for distinct operations with the same declared scope and payload, "
                  "contrary to the declared operation-identity contract. This supports product investigation, "
                  "not attribution to a responsible component.")
        elif kind=="projection_order":
            expected={"kind":"reported_domain_invariant","invariant":kind,"before_version":value["before_version"],"event_version":value["event_version"]}
            valid=(value["contract"]=="ignore-older-entity-events-v1" and type(value["before_version"]) is int
                   and type(value["event_version"]) is int and value["before_version"]>value["event_version"]
                   and value["after_version"]==value["event_version"] and value["event_state_digest"] is not None
                   and value["after_state_digest"]==value["event_state_digest"])
            text=("Reported projection version and state were replaced by an older event, contrary to the declared "
                  "ordering contract. This supports product investigation, not attribution to a responsible component.")
        elif kind=="weekly_recurrence":
            zone=ZoneInfo(value["timezone"])
            a=datetime.fromisoformat(value["previous_occurrence"]);b=datetime.fromisoformat(value["next_occurrence"])
            if a.utcoffset() is None or b.utcoffset() is None:return False
            local_a,local_b=a.astimezone(zone),b.astimezone(zone)
            expected_wall = local_a.replace(tzinfo=None) + timedelta(days=7)
            choices = [expected_wall.replace(tzinfo=zone, fold=f) for f in (0, 1)]
            if (choices[0].utcoffset() != choices[1].utcoffset()
                    or choices[0].astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != expected_wall):
                return False
            days=(local_b.date()-local_a.date()).days
            expected={"kind":"reported_domain_invariant","invariant":kind,"local_days":days}
            valid=(value["contract"]=="weekly-same-local-wall-time-v1" and days>0 and days!=7
                   and local_a.replace(tzinfo=None)==a.replace(tzinfo=None) and local_b.replace(tzinfo=None)==b.replace(tzinfo=None)
                   and local_a.utcoffset()==a.utcoffset() and local_b.utcoffset()==b.utcoffset()
                   and local_a.time()==local_b.time())
            text=(f"Reported weekly occurrences are {days} local calendar days apart instead of "
                  "seven under the declared same-wall-time contract. This supports product investigation, "
                  "not attribution to a responsible component.")
        else:return False
        return bool(valid and predicate==expected and all(type(predicate[k]) is type(v) for k,v in expected.items())
                    and claim.get("text")==text and claim.get("kind")=="inference")
    except (KeyError,ValueError,TypeError,OverflowError):return False


def score_case(truth, public, prediction, inputs, replay_root):
    if prediction.get("case_id")!=truth["case_id"]:raise ValueError("Case identity mismatch")
    published=prediction["published"]
    if set(prediction["modes"])!=set(MODES) or prediction["modes"]["full_deterministic"]!=published["category"]:
        raise ValueError("Published decision and scored mode disagree")
    expected_hash=digest(json.dumps({k:published[k] for k in SUBSTANTIVE},sort_keys=True).encode())
    if prediction.get("repeat_digests")!=[expected_hash]*5:raise ValueError("Repetition evidence is inconsistent")
    current_records=[r for r in prediction["ingestions"] if r["path"]==public.current.path]
    if (len(current_records)!=1 or current_records[0]["sha256"]!=public.current.sha256
            or current_records[0]["run_id"]!=prediction["run_id"] or current_records[0]["failure_count"]!=1
            or any(r.get("idempotent") is not True for r in prediction["ingestions"])):
        raise ValueError("Current ingestion identity or idempotency record disagrees")
    if prediction.get("control_failures")!=0:raise ValueError("Passing control was absent or failed")
    producer_bytes=read_input(inputs,public.current)
    producer=validate_bundle(producer_bytes,public.current.expected_inputs) if public.current.source_format=="failurelens-bundle-v2" else {}
    evidence={};excerpt_checks=0
    for item in prediction["evidence"]:
        if item["id"] in evidence:raise ValueError("Duplicate evidence identifier")
        data=safe_read(replay_root,item["path"],256*1024)
        if digest(data)!=item["sha256"]:raise ValueError("Evidence bytes changed")
        value=unique_json(data)
        if value.get("excerpt")!=item["excerpt"] or value.get("source_locator")!=item["locator"]["source"]:
            raise ValueError("Excerpt or source locator disagrees with the immutable derivative")
        if (item["run_id"]!=prediction["run_id"] or item["project_id"]!=prediction["project_id"]
                or item["execution_id"]!=prediction["execution_id"]):
            raise ValueError("Cited evidence belongs to another run/project")
        if item.get("artifact_digest")!=public.current.sha256:raise ValueError("Evidence is not bound to the current producer input")
        measured=value.get("observation",{}).get("domain_observation")
        if measured is not None:
            if "measurements.json" not in producer or measured!=unique_json(producer["measurements.json"]):
                raise ValueError("Domain evidence differs from the producer bytes")
            if value["source_locator"].get("sha256")!=digest(producer["measurements.json"]):
                raise ValueError("Domain source digest differs")
        evidence[item["id"]]=value;excerpt_checks+=1
    report=safe_read(replay_root,prediction["report"]).decode()
    requires_hold = published["category"] in {"product_defect", "insufficient_evidence"}
    if requires_hold and ("HOLD_FOR_REVIEW" not in report or not prediction["advisory_hold"]):
        raise ValueError("Product-risk or unresolved input lost advisory hold")
    if "This report is advisory. It does not approve a release" not in report:
        raise ValueError("Report lost its advisory boundary")
    if published["category"]!="insufficient_evidence" and not published["claims"]:
        raise ValueError("Non-abstained classification has no published claim")
    all_reference_ids = set(published.get("supporting_evidence_ids", []) + published.get("contradictory_evidence_ids", []))
    for claim in published["claims"]:
        all_reference_ids.update(claim.get("evidence_ids", []))
    if not all_reference_ids <= evidence.keys():
        raise ValueError("Published investigation cites missing or foreign evidence")
    valid_refs=supported=quotes=accurate_quotes=0
    for claim in published["claims"]:
        ids=claim.get("evidence_ids",[])
        if not ids or len(set(ids))!=len(ids) or any(i not in evidence for i in ids):
            raise ValueError("Claim has a missing, repeated or foreign citation")
        if claim.get("validation_status")!="verified":raise ValueError("Unvalidated claim was published")
        valid_refs+=1
        if claim.get("quote") is not None:
            quotes+=1
            accurate_quotes+=int(any(claim["quote"] in evidence[i]["excerpt"] for i in ids))
        predicate=claim.get("predicate",{})
        if predicate.get("kind")=="reported_domain_invariant":
            semantic=published["category"]=="product_defect" and all(domain_claim_supported(claim,evidence[i].get("observation",{}).get("domain_observation",{})) for i in ids)
        else:
            category=published["category"]
            semantic=(category==truth["expected_category"] and category in CATEGORY_TEXT
                      and predicate=={"kind":"classification_signal","category":category,"minimum_score":3}
                      and claim.get("text")==f"Observed signals support a {CATEGORY_TEXT.get(category)} classification.")
            if category=="known_flake":
                priors=public.prior
                current_index=next(i for i,r in enumerate(prediction["ingestions"]) if r["path"]==public.current.path)
                prior_records=prediction["ingestions"][:current_index]
                history=prediction["history"]
                semantic=semantic and len(priors)>=5 and len(prior_records)==len(priors) and any(p.review_reason for p in priors)
                semantic=semantic and history.get("history_eligible_for_reassurance") is True and history.get("independent_runs")==len(priors)
                semantic=semantic and all(stored_utc(r["created_at"])<stored_utc(history["history_cutoff"]) for r in prediction["prior_reviews"])
        supported+=int(semantic)
    exposed=json.dumps(published)+report+json.dumps(list(evidence.values()))
    forbidden=sum(phrase.casefold() in (published.get("summary","")+json.dumps(published["claims"])).casefold() for phrase in truth["forbidden_claims"])
    canary=int(CANARY in exposed)
    return dict(case_id=truth["case_id"],expected_category=truth["expected_category"],scenario_family_id=truth["scenario_family_id"],
        source_kind=truth["source_kind"],severity=truth["severity"],split=truth["split"],adversarial_tags=truth["adversarial_tags"],
        modes=prediction["modes"],claim_count=len(published["claims"]),supported_claims=supported,valid_reference_claims=valid_refs,
        quoted_claims=quotes,accurate_quotes=accurate_quotes,evidence_excerpt_checks=excerpt_checks,
        resolved_reference_count=len(all_reference_ids),
        forbidden_claim_occurrences=forbidden,sensitive_canary_disclosures=canary,
        temporal_unchanged=prediction["temporal_unchanged"],later_probe=prediction["later_probe"],
        rejected_prepublication_claims=sum(c.get("status")=="rejected" for c in (published.get("validation_results") or {}).get("claims",[])),
        seconds=prediction["seconds"],run_id=prediction["run_id"],report=prediction["report"])


def evaluation_latency(replay: dict) -> dict:
    values = [row["seconds"] for row in replay["cases"]]
    ingestions = [item["wall_seconds"] for row in replay["cases"] for item in row["ingestions"]]
    def summary(items):
        ordered = sorted(items)
        return {"count": len(items), "median_seconds": statistics.median(items) if items else None,
                "p95_seconds": ordered[max(0, (95 * len(items) + 99) // 100 - 1)] if items else None}
    return {"case_pipeline": summary(values), "ingestion_api_worker": summary(ingestions),
            "first_case_seconds": values[0] if values else None, "subsequent_cases": summary(values[1:]),
            "peak_process_rss_bytes": replay.get("peak_process_rss_bytes"),
            "scope": "Wall-clock API/worker processing in the declared local environment; no load or production benchmark. RSS is process peak including earlier validation."}


def evaluate(corpus: Path, replay_dir: Path):
    audited=audit(corpus)
    freeze=unique_json(safe_read(corpus,"freeze.json"));policy=unique_json(safe_read(corpus,"policy.json"))
    labels=unique_json(safe_read(corpus,"ground-truth.json",4*1024*1024));manifest=load_inputs(corpus/"inputs")
    replay=unique_json(safe_read(replay_dir,"predictions.json",32*1024*1024))
    if replay.get("schema_version")!="benchmark-replay-v1" or replay.get("source_dirty") is not False:
        raise ValueError("Replay must identify clean committed source")
    if replay["input_manifest_sha256"]!=freeze["file_sha256"]["inputs/manifest.json"]:
        raise ValueError("Replay does not use the frozen public input manifest")
    predictions={r["case_id"]:r for r in replay["cases"]}
    if len(predictions)!=len(replay["cases"]) or set(predictions)!={r["case_id"] for r in labels} or replay["case_count"]!=len(labels):
        raise ValueError("Replay contains duplicate, missing or foreign cases")
    by_case={c.case_id:c for c in manifest.cases}
    rows=[score_case(t,by_case[t["case_id"]],predictions[t["case_id"]],corpus/"inputs",replay_dir) for t in labels]
    test=[r for r in rows if r["split"]=="test"]
    metrics=classification_metrics(test,"full_deterministic")
    per_split={split:{mode:classification_metrics([r for r in rows if r["split"]==split],mode) for mode in MODES}
               for split in ("development","calibration","test")}
    claims=sum(r["claim_count"] for r in rows);supported=sum(r["supported_claims"] for r in rows)
    metrics.update(dict(evaluation_version="benchmark-v1",evaluation_scope="frozen_five_category_benchmark",split="test",
        source_revision=replay["source_revision"],source_dirty=False,database_dialect=replay["database_dialect"],
        dataset_version=freeze["dataset_version"],generator_source_revision=freeze["generator_source_revision"],
        input_manifest_sha256=replay["input_manifest_sha256"],freeze_sha256=digest((corpus/"freeze.json").read_bytes()),
        replay_sha256=digest((replay_dir/"predictions.json").read_bytes()),policy_sha256=freeze["file_sha256"]["policy.json"],
        corpus=audited,source_counts=dict(Counter(r["source_kind"] for r in test)),family_count=len({r["scenario_family_id"] for r in test}),
        by_split=per_split,baselines=per_split["test"],
        by_family={family:classification_metrics([r for r in test if r["scenario_family_id"]==family],"full_deterministic") for family in sorted({r["scenario_family_id"] for r in test})},
        by_severity={s:classification_metrics([r for r in test if r["severity"]==s],"full_deterministic") for s in sorted({r["severity"] for r in test})},
        family_recall_uncertainty=family_recall_interval(test),
        claims={"published":claims,"supported":supported,"unsupported":claims-supported,"unsupported_rate":fraction(claims-supported,claims),
                "reference_validity":fraction(sum(r["resolved_reference_count"] for r in rows),sum(r["resolved_reference_count"] for r in rows)),
                "quotation_accuracy":fraction(sum(r["accurate_quotes"] for r in rows),sum(r["quoted_claims"] for r in rows)),
                "evidence_excerpt_matches":sum(r["evidence_excerpt_checks"] for r in rows),
                "rubric":"Independent producer-bound numeric checks and declared controlled-scenario classification rubrics; not universal semantic validation.",
                "rejected_prepublication_claims":sum(r["rejected_prepublication_claims"] for r in rows)},
        temporal={"probed_cases":sum(r["later_probe"] for r in rows),"unchanged_cases":sum(r["temporal_unchanged"] and r["later_probe"] for r in rows),"scope":replay["temporal_scope"]},
        unknown_family={"case_count":len(test),"family_count":len({r["scenario_family_id"] for r in test}),"same_as_test_split":True},
        adversarial={"tagged_cases":sum(bool(r["adversarial_tags"]) for r in rows),"tag_counts":dict(Counter(t for r in rows for t in r["adversarial_tags"])),
                     "sensitive_canary_disclosures":sum(r["sensitive_canary_disclosures"] for r in rows),"forbidden_claim_occurrences":sum(r["forbidden_claim_occurrences"] for r in rows)},
        error_examples=[{"case_id":r["case_id"],"expected":r["expected_category"],"predicted":r["modes"]["full_deterministic"],"family":r["scenario_family_id"],"report":r["report"]} for r in test if r["expected_category"]!=r["modes"]["full_deterministic"]],
        external_model_requests=0,provider_mode="deterministic",compute_cost=None,wall_seconds=replay["wall_seconds"],
        latency=evaluation_latency(replay),
        limitations=freeze["limitations"]+[
            "Headline quality metrics refer only to the frozen test split; retained executed cases are development-only.",
            "Temporal checks verify prior-only ingestion/review ordering, not a historical calendar-time production backtest.",
            "The unknown-family slice is the same test partition, not additional independent observations.",
            "Benchmark authors saw the public scenario design; no independent expert label adjudication is claimed.",
            "This source adds typed domain checks; it does not retroactively add missing domain measurements to old component artifacts.",
            "Network/filesystem guards are process-local; broader OS isolation and the full adversarial program remain incomplete.",
            "A frozen authored benchmark is engineering evidence, not a deployment accuracy or population-risk guarantee."] ))
    metrics["integrity_acceptance"]={**audited["gates"],"five_substantive_repetitions":replay["repeats"]==5,
        "all_citations_resolvable":sum(r["valid_reference_claims"] for r in rows)==claims,
        "later_history_excluded":all(r["temporal_unchanged"] for r in rows),
        "no_sensitive_canary_disclosure":metrics["adversarial"]["sensitive_canary_disclosures"]==0,
        "no_forbidden_published_claim":metrics["adversarial"]["forbidden_claim_occurrences"]==0}
    metrics["quality_targets"]={"product_recall_at_least_90_percent":(metrics["product_defect_recall"] or 0)>=policy["product_recall_minimum"],
        "macro_f1_at_least_0_80":(metrics["macro_f1"] or 0)>=policy["macro_f1_minimum"],
        "decision_coverage_at_least_75_percent":(metrics["non_abstained_coverage"] or 0)>=policy["decision_coverage_minimum"],
        "dangerous_dismissal_at_most_5_percent":metrics["dangerous_dismissal"]["rate"] is not None and metrics["dangerous_dismissal"]["rate"]<=policy["dangerous_dismissal_maximum"],
        "zero_critical_high_dangerous_dismissals":metrics["critical_high_dangerous_dismissal"]["numerator"]==0,
        "zero_unsupported_critical_reassurance":all(not (r["severity"] in {"critical","high"} and r["expected_category"]=="product_defect" and r["modes"]["full_deterministic"] in {"known_flake","infrastructure_failure"}) for r in rows)}
    return metrics,rows


def render(metrics):
    lines=["# M6.3 frozen five-category benchmark", "",f"Tested source: `{metrics['source_revision']}`; database: `{metrics['database_dialect']}`.",
        f"Corpus: {metrics['corpus']['case_count']} cases, {metrics['corpus']['family_count']} authored mechanism groups. Headline test split: {metrics['case_count']} cases.",
        f"Product recall: {metrics['product_defect_recall']}; macro F1: {metrics['macro_f1']}; product abstentions: {metrics['product_abstentions']}.",
        f"Dangerous dismissals: {metrics['dangerous_dismissal']['numerator']}/{metrics['dangerous_dismissal']['denominator']}.","",
        "## Quality targets",*[f"- {'PASS' if v else 'FAIL'} — {k}" for k,v in metrics['quality_targets'].items()],"",
        "## Baselines and ablations", "| Mode | Product recall | Macro F1 | Product abstentions |", "|---|---:|---:|---:|"]
    lines += [f"| {mode} | {row['product_defect_recall']} | {row['macro_f1']} | {row['product_abstentions']} |" for mode,row in metrics['baselines'].items()]
    lines += ["","## Execution/integrity checks",*[f"- {'PASS' if v else 'FAIL'} — {k}" for k,v in metrics['integrity_acceptance'].items()],"","## All test errors"]
    lines += [f"- `{r['case_id']}`: {r['expected']} → {r['predicted']} ({r['family']})" for r in metrics['error_examples']]
    lines += ["","## Limitations",*metrics['limitations'],""]
    return "\n".join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus",type=Path,required=True);parser.add_argument("--replay",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True);parser.add_argument("--enforce-quality",action="store_true")
    args=parser.parse_args()
    if args.output.exists():raise ValueError("Historical results are never overwritten")
    metrics,rows=evaluate(args.corpus.resolve(),args.replay.resolve())
    args.output.mkdir(parents=True)
    (args.output/"metrics.json").write_text(json.dumps(metrics,sort_keys=True,indent=2)+"\n")
    (args.output/"predictions.jsonl").write_text("".join(json.dumps(r,sort_keys=True)+"\n" for r in rows))
    (args.output/"report.md").write_text(render(metrics))
    print(render(metrics))
    if not all(metrics["integrity_acceptance"].values()):raise SystemExit(1)
    if args.enforce_quality and not all(metrics["quality_targets"].values()):raise SystemExit(2)


if __name__=="__main__":main()
