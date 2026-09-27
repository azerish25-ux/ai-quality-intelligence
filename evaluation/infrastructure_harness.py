from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parent
BACKEND_SRC = ROOT.parent / "backend" / "src"
sys.path.insert(0, str(BACKEND_SRC))

from failurelens.db import Base, create_database_engine  # noqa: E402
from failurelens.infrastructure import (  # noqa: E402
    INFRASTRUCTURE_ENGINE_VERSION,
    INFRASTRUCTURE_POLICY_VERSION,
    build_infrastructure_correlation,
    create_infrastructure_event,
)
from failurelens.models import Failure, Outcome, TestExecution  # noqa: E402
from failurelens.schemas import (  # noqa: E402
    InfrastructureEventCreate,
    IngestionRequest,
    TestObservation,
)
from failurelens.service import (  # noqa: E402
    analyze_and_persist,
    create_project,
    ingest_normalized,
)

BASE = datetime(2026, 2, 1, tzinfo=UTC)
TEST_IDENTITY = "checkout::infrastructure-sensitive"


def _outcome(value: str) -> Outcome:
    return Outcome(value)


def _ingest_run(
    session: Session,
    project: Any,
    *,
    case_id: str,
    index: int,
    definition: dict[str, Any],
) -> Any:
    observations = []
    values = definition.get("outcomes", [definition.get("outcome", "unknown")])
    for attempt, value in enumerate(values):
        outcome = _outcome(value)
        observations.append(
            TestObservation(
                test_identity=TEST_IDENTITY,
                suite="checkout",
                source_path="tests/checkout.spec.ts",
                browser="chromium",
                attempt=attempt,
                outcome=outcome,
                message=(
                    definition.get("message", "gateway timed out while waiting for checkout")
                    if outcome is Outcome.failed
                    else None
                ),
                exception_type="GatewayTimeout" if outcome is Outcome.failed else None,
            )
        )
    run = ingest_normalized(
        session,
        project,
        IngestionRequest(
            external_id=f"{case_id}-history-{index}",
            repository=definition.get("repository", "owner/repo"),
            commit_sha=f"{index + 1:07x}",
            branch=definition.get("branch", "main"),
            run_scope=definition.get("run_scope", "full_suite"),
            environment=definition.get("environment", "ci-linux"),
            timezone="UTC",
            worker_count=definition.get("worker_count", 4),
            shard_count=definition.get("shard_count", 2),
            source_metadata=definition.get(
                "source_metadata",
                {
                    "workflow_name": "ci",
                    "runner_identity": "runner-1",
                    "runner_group": "hosted",
                    "region": "ca-east",
                },
            ),
            observations=observations,
        ),
    )
    observed_at = BASE + timedelta(days=int(definition["day"]))
    run.started_at = observed_at
    run.ended_at = observed_at + timedelta(minutes=10)
    run.created_at = observed_at
    session.commit()
    return run


def _create_event(
    session: Session,
    selected_project: Any,
    other_project: Any,
    definition: dict[str, Any],
) -> Any:
    project = other_project if definition.get("project") == "other" else selected_project
    day = int(definition["day"])
    recorded_day = int(definition.get("recorded_day", day))
    return create_infrastructure_event(
        session,
        project,
        InfrastructureEventCreate(
            repository=definition.get("repository", "owner/repo"),
            environment=definition.get("environment", "ci-linux"),
            producer=definition.get("producer", "status-monitor"),
            producer_event_id=definition["event_id"],
            event_kind=definition.get("event_kind", "service_outage"),
            severity="error",
            status="resolved",
            started_at=BASE
            + timedelta(days=day, minutes=int(definition.get("start_minute", 2))),
            ended_at=BASE
            + timedelta(days=day, minutes=int(definition.get("end_minute", 8))),
            recorded_at=BASE
            + timedelta(
                days=recorded_day,
                minutes=int(definition.get("recorded_minute", 9)),
            ),
            workflow_name=definition.get("workflow_name", "ci"),
            runner_identity=definition.get("runner_identity", "runner-1"),
            runner_group=definition.get("runner_group", "hosted"),
            region=definition.get("region", "ca-east"),
            worker_count=definition.get("worker_count", 4),
            source_trust=definition.get("source_trust", "verified_monitor"),
            metadata={"evaluation_case": definition["event_id"]},
        ),
    )


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with factory() as session:
            project = create_project(
                session, f"selected-{case['case_id']}", f"Selected {case['case_id']}"
            )
            other_project = create_project(
                session, f"other-{case['case_id']}", f"Other {case['case_id']}"
            )
            for index, definition in enumerate(case.get("runs", [])):
                _ingest_run(
                    session,
                    project,
                    case_id=case["case_id"],
                    index=index,
                    definition=definition,
                )
            for definition in case.get("events", []):
                _create_event(session, project, other_project, definition)

            current_day = int(case.get("current_day", 10))
            current = _ingest_run(
                session,
                project,
                case_id=case["case_id"],
                index=999,
                definition={
                    "day": current_day,
                    "outcomes": ["failed"],
                    "message": case.get(
                        "current_message",
                        "gateway timed out while waiting for checkout",
                    ),
                },
            )
            execution = session.scalar(
                select(TestExecution).where(TestExecution.run_id == current.id)
            )
            failure = session.scalar(select(Failure).where(Failure.run_id == current.id))
            assert execution is not None and failure is not None

            category_before = analyze_and_persist(session, failure).category.value
            kwargs = {
                "selected_execution": execution,
                "selected_run": current,
                "cutoff": current.started_at,
                "browser": "chromium",
                "match_browser": True,
                "environment": "ci-linux",
                "match_environment": True,
                "run_scope": "full_suite",
                "worker_count": 4,
                "match_worker_count": True,
                "shard_count": 2,
                "match_shard_count": True,
                "timezone_name": "UTC",
                "exclude_run_id": current.id,
                "strict_fingerprint": failure.strict_fingerprint,
                "event_kind": case.get("event_kind"),
                "minimum_support": int(case.get("minimum_support", 3)),
                "persist": False,
            }
            first = build_infrastructure_correlation(session, **kwargs)
            second = build_infrastructure_correlation(session, **kwargs)
            persisted = build_infrastructure_correlation(session, **{**kwargs, "persist": True})
            category_after = analyze_and_persist(session, failure).category.value

            stable_fields = (
                "status",
                "input_digest",
                "accepted_event_ids",
                "rejected_events",
                "sample_sizes",
                "exposed_outcomes",
                "unexposed_outcomes",
                "rates",
                "associations",
                "confounders",
                "safety",
                "members",
            )
            deterministic = all(first[field] == second[field] for field in stable_fields)
            accepted_events = first["accepted_events"]
            trusted_accepted = all(
                event["trusted_for_correlation"] for event in accepted_events
            )
            provenance_valid = all(
                len(event["source_digest"]) == 64
                and event["source_trust"]
                in {"authenticated_lookup", "trusted_workflow", "verified_monitor"}
                for event in accepted_events
            )
            return {
                "case_id": case["case_id"],
                "expected_status": case["expected_status"],
                "predicted_status": first["status"],
                "status_correct": first["status"] == case["expected_status"],
                "expected_accepted_events": case.get("expected_accepted_events", 0),
                "accepted_event_count": len(first["accepted_event_ids"]),
                "accepted_event_count_correct": len(first["accepted_event_ids"])
                == int(case.get("expected_accepted_events", 0)),
                "expected_exposed_runs": case.get("expected_exposed_runs", 0),
                "exposed_run_count": first["sample_sizes"]["exposed_runs"],
                "exposed_run_count_correct": first["sample_sizes"]["exposed_runs"]
                == int(case.get("expected_exposed_runs", 0)),
                "deterministic": deterministic,
                "trusted_accepted_events_only": trusted_accepted,
                "accepted_event_provenance_valid": provenance_valid,
                "causality_claimed": first["safety"]["causality_claimed"],
                "independent_classification_authority": first["safety"][
                    "can_independently_authorize_infrastructure_classification"
                ],
                "category_before": category_before,
                "category_after": category_after,
                "expected_category": case.get("expected_category"),
                "dangerous_downgrade": (
                    case.get("expected_category") is not None
                    and category_after != case.get("expected_category")
                ),
                "snapshot_persisted": bool(persisted["snapshot_id"]),
                "snapshot_reused": persisted["input_digest"] == first["input_digest"],
                "tags": case.get("tags", []),
                "sample_sizes": first["sample_sizes"],
                "rejected_events": first["rejected_events"],
            }
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def evaluate(cases: list[dict[str, Any]], manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    predictions = [_evaluate_case(case) for case in cases]
    case_count = len(predictions)
    future_cases = [item for item in predictions if "future-event" in item["tags"]]
    cross_project_cases = [item for item in predictions if "cross-project" in item["tags"]]
    product_cases = [item for item in predictions if "dangerous-downgrade" in item["tags"]]
    status_correct = sum(item["status_correct"] for item in predictions)
    compatibility_correct = sum(
        item["accepted_event_count_correct"] and item["exposed_run_count_correct"]
        for item in predictions
    )
    deterministic = sum(item["deterministic"] for item in predictions)
    provenance_valid = sum(item["accepted_event_provenance_valid"] for item in predictions)
    future_leakage = sum(item["accepted_event_count"] > 0 for item in future_cases)
    cross_project_leakage = sum(
        item["accepted_event_count"] > 0 for item in cross_project_cases
    )
    dangerous_downgrades = [
        item["case_id"] for item in product_cases if item["dangerous_downgrade"]
    ]
    unsupported_causality = [
        item["case_id"]
        for item in predictions
        if item["causality_claimed"] or item["independent_classification_authority"]
    ]
    acceptance = {
        "status_accuracy_eq_1": status_correct == case_count,
        "compatibility_selection_accuracy_eq_1": compatibility_correct == case_count,
        "deterministic_repeat_agreement_eq_1": deterministic == case_count,
        "event_provenance_validity_eq_1": provenance_valid == case_count,
        "zero_future_event_leakage": future_leakage == 0,
        "zero_cross_project_leakage": cross_project_leakage == 0,
        "zero_dangerous_product_defect_downgrades": not dangerous_downgrades,
        "zero_unsupported_causality_claims": not unsupported_causality,
        "all_snapshots_persisted": all(item["snapshot_persisted"] for item in predictions),
        "all_snapshot_digests_reused": all(item["snapshot_reused"] for item in predictions),
    }
    metrics = {
        "schema_version": "infrastructure-evaluation-result-v1",
        "engine_version": INFRASTRUCTURE_ENGINE_VERSION,
        "policy_version": INFRASTRUCTURE_POLICY_VERSION,
        "case_count": case_count,
        "status_accuracy": status_correct / case_count if case_count else 1.0,
        "compatibility_selection_accuracy": compatibility_correct / case_count
        if case_count
        else 1.0,
        "deterministic_repeat_agreement": deterministic / case_count
        if case_count
        else 1.0,
        "event_provenance_validity": provenance_valid / case_count
        if case_count
        else 1.0,
        "future_event_leakage": future_leakage,
        "cross_project_leakage": cross_project_leakage,
        "dangerous_product_defect_downgrades": {
            "numerator": len(dangerous_downgrades),
            "denominator": len(product_cases),
            "case_ids": dangerous_downgrades,
        },
        "unsupported_causality_claims": {
            "count": len(unsupported_causality),
            "case_ids": unsupported_causality,
        },
        "status_counts": {
            status: sum(item["predicted_status"] == status for item in predictions)
            for status in sorted({item["predicted_status"] for item in predictions})
        },
        "acceptance": acceptance,
        "limitations": [
            *manifest.get("limitations", []),
            "The harness uses the real SQLAlchemy models, ingestion service, deterministic analyzer, and infrastructure-correlation engine against isolated SQLite databases.",
            "The fixture does not establish causality or independently blinded production generalization.",
        ],
    }
    return predictions, metrics


def render_report(metrics: dict[str, Any]) -> str:
    dangerous = metrics["dangerous_product_defect_downgrades"]
    lines = [
        "# FailureLens infrastructure-event correlation evaluation",
        "",
        "Controlled synthetic evaluation of prior-only event compatibility, outcome accounting, leakage boundaries, and dangerous-downgrade safety.",
        "",
        f"- Cases: **{metrics['case_count']}**",
        f"- Status accuracy: **{metrics['status_accuracy']:.3f}**",
        f"- Compatibility-selection accuracy: **{metrics['compatibility_selection_accuracy']:.3f}**",
        f"- Event-provenance validity: **{metrics['event_provenance_validity']:.3f}**",
        f"- Deterministic repeat agreement: **{metrics['deterministic_repeat_agreement']:.3f}**",
        f"- Future-event leakage: **{metrics['future_event_leakage']}**",
        f"- Cross-project leakage: **{metrics['cross_project_leakage']}**",
        f"- Dangerous product-defect downgrades: **{dangerous['numerator']}/{dangerous['denominator']}**",
        f"- Unsupported causality claims: **{metrics['unsupported_causality_claims']['count']}**",
        "",
        "## Acceptance gates",
        "",
    ]
    lines.extend(
        f"- {'PASS' if passed else 'FAIL'} — `{name}`"
        for name, passed in metrics["acceptance"].items()
    )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in metrics["limitations"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus", type=Path, default=ROOT / "corpus" / "infrastructure-cases.jsonl"
    )
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "corpus" / "infrastructure-manifest.json"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = [
        json.loads(line)
        for line in args.corpus.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    predictions, metrics = evaluate(cases, manifest)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "infrastructure-predictions.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in predictions),
        encoding="utf-8",
    )
    (args.output / "infrastructure-metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output / "infrastructure-report.md").write_text(
        render_report(metrics), encoding="utf-8"
    )
    print(json.dumps(metrics, indent=2, sort_keys=True))
    if not all(metrics["acceptance"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
