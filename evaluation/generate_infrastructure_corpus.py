from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "corpus" / "infrastructure-cases.jsonl"
MANIFEST = ROOT / "corpus" / "infrastructure-manifest.json"


def _run(day: int, outcome: str, **overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "day": day,
        "outcomes": [outcome],
        "repository": "owner/repo",
        "environment": "ci-linux",
        "run_scope": "full_suite",
        "worker_count": 4,
        "shard_count": 2,
        "source_metadata": {
            "workflow_name": "ci",
            "runner_identity": "runner-1",
            "runner_group": "hosted",
            "region": "ca-east",
        },
    }
    value.update(overrides)
    return value


def _event(event_id: str, day: int, **overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "event_id": event_id,
        "day": day,
        "project": "selected",
        "repository": "owner/repo",
        "environment": "ci-linux",
        "producer": "status-monitor",
        "event_kind": "service_outage",
        "source_trust": "verified_monitor",
        "workflow_name": "ci",
        "runner_identity": "runner-1",
        "runner_group": "hosted",
        "region": "ca-east",
        "worker_count": 4,
        "start_minute": 2,
        "end_minute": 8,
        "recorded_minute": 9,
    }
    value.update(overrides)
    return value


def _balanced_runs() -> list[dict[str, Any]]:
    return [
        *[_run(day, "failed") for day in range(3)],
        *[_run(day, "passed") for day in range(3, 6)],
    ]


def _balanced_events() -> list[dict[str, Any]]:
    return [_event(f"outage-{day}", day) for day in range(3)]


def _case(
    case_id: str,
    expected_status: str,
    *,
    runs: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    minimum_support: int = 3,
    event_kind: str | None = None,
    expected_accepted_events: int = 0,
    expected_exposed_runs: int = 0,
    tags: list[str] | None = None,
    current_day: int = 10,
    current_message: str = "gateway timed out while waiting for checkout",
    expected_category: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "infrastructure-evaluation-v1",
        "case_id": case_id,
        "expected_status": expected_status,
        "runs": runs or [],
        "events": events or [],
        "minimum_support": minimum_support,
        "event_kind": event_kind,
        "expected_accepted_events": expected_accepted_events,
        "expected_exposed_runs": expected_exposed_runs,
        "tags": tags or [],
        "current_day": current_day,
        "current_message": current_message,
        "expected_category": expected_category,
    }


def build_cases() -> list[dict[str, Any]]:
    balanced = _balanced_runs()
    events = _balanced_events()
    return [
        _case(
            "infra-001-available-clear-association",
            "AVAILABLE",
            runs=balanced,
            events=events,
            expected_accepted_events=3,
            expected_exposed_runs=3,
            tags=["available", "trusted", "association"],
        ),
        _case(
            "infra-002-insufficient-exposed-support",
            "INSUFFICIENT_DATA",
            runs=[_run(0, "failed"), *[_run(day, "passed") for day in range(1, 4)]],
            events=[_event("single-outage", 0)],
            expected_accepted_events=1,
            expected_exposed_runs=1,
            tags=["minimum-support"],
        ),
        _case(
            "infra-003-no-events",
            "NO_MATCHING_EVENTS",
            runs=balanced,
            events=[],
            tags=["missing-events"],
        ),
        _case(
            "infra-004-untrusted-artifact-claim",
            "UNTRUSTED_EVENT_SOURCE",
            runs=balanced,
            events=[
                _event(
                    f"artifact-{day}",
                    day,
                    source_trust="artifact_derived",
                    producer="uploaded-report",
                )
                for day in range(3)
            ],
            tags=["trust", "self-authorization"],
        ),
        _case(
            "infra-005-cross-repository",
            "INCOMPATIBLE_CONTEXT",
            runs=balanced,
            events=[_event("wrong-repository", 0, repository="other/repo")],
            tags=["repository-isolation"],
        ),
        _case(
            "infra-006-environment-mismatch",
            "INCOMPATIBLE_CONTEXT",
            runs=balanced,
            events=[_event("wrong-environment", 0, environment="staging")],
            tags=["environment-isolation"],
        ),
        _case(
            "infra-007-future-record-excluded",
            "NO_MATCHING_EVENTS",
            runs=balanced,
            events=[_event("future-record", 0, recorded_day=11)],
            tags=["future-event", "leakage"],
        ),
        _case(
            "infra-008-event-outside-window",
            "NO_MATCHING_EVENTS",
            runs=balanced,
            events=[_event("late-event", 7)],
            tags=["time-window"],
        ),
        _case(
            "infra-009-multiple-event-kinds-confounded",
            "CONFOUNDED",
            runs=balanced,
            events=[
                *events,
                *[
                    _event(
                        f"network-{day}",
                        day,
                        event_kind="network_degradation",
                    )
                    for day in range(3)
                ],
            ],
            expected_accepted_events=6,
            expected_exposed_runs=3,
            tags=["confounding"],
        ),
        _case(
            "infra-010-event-kind-filter-removes-confounding",
            "AVAILABLE",
            runs=balanced,
            events=[
                *events,
                *[
                    _event(
                        f"network-filtered-{day}",
                        day,
                        event_kind="network_degradation",
                    )
                    for day in range(3)
                ],
            ],
            event_kind="service_outage",
            expected_accepted_events=3,
            expected_exposed_runs=3,
            tags=["event-filter", "confounding"],
        ),
        _case(
            "infra-011-retries-not-independent",
            "AVAILABLE",
            runs=[
                *[
                    _run(day, "failed", outcomes=["failed", "passed"])
                    for day in range(3)
                ],
                *[_run(day, "passed") for day in range(3, 6)],
            ],
            events=events,
            expected_accepted_events=3,
            expected_exposed_runs=3,
            tags=["retries", "denominator"],
        ),
        _case(
            "infra-012-skipped-cancelled-visible",
            "AVAILABLE",
            runs=[
                *balanced,
                _run(6, "skipped"),
                _run(7, "cancelled"),
                _run(8, "unknown"),
            ],
            events=events,
            expected_accepted_events=3,
            expected_exposed_runs=3,
            tags=["outcome-accounting"],
            current_day=12,
        ),
        _case(
            "infra-013-cross-project-event-excluded",
            "NO_MATCHING_EVENTS",
            runs=balanced,
            events=[_event("other-project-outage", 0, project="other")],
            tags=["cross-project", "leakage"],
        ),
        _case(
            "infra-014-future-start-excluded",
            "NO_MATCHING_EVENTS",
            runs=balanced,
            events=[_event("future-start", 11)],
            tags=["future-event", "leakage"],
        ),
        _case(
            "infra-015-trusted-event-survives-untrusted-noise",
            "AVAILABLE",
            runs=balanced,
            events=[
                *events,
                *[
                    _event(
                        f"untrusted-{day}",
                        day,
                        source_trust="self_reported",
                        producer="artifact-claim",
                    )
                    for day in range(3)
                ],
            ],
            expected_accepted_events=3,
            expected_exposed_runs=3,
            tags=["mixed-trust"],
        ),
        _case(
            "infra-016-product-defect-preserved",
            "AVAILABLE",
            runs=[
                *[
                    _run(
                        day,
                        "failed",
                        message="duplicate committed transfer left the ledger unbalanced",
                    )
                    for day in range(3)
                ],
                *[_run(day, "passed") for day in range(3, 6)],
            ],
            events=events,
            expected_accepted_events=3,
            expected_exposed_runs=3,
            current_message="duplicate committed transfer left the ledger unbalanced",
            expected_category="product_defect",
            tags=["dangerous-downgrade", "product-risk"],
        ),
        _case(
            "infra-017-no-prior-runs",
            "INSUFFICIENT_DATA",
            runs=[],
            events=[],
            tags=["no-history"],
        ),
        _case(
            "infra-018-worker-context-mismatch",
            "INCOMPATIBLE_CONTEXT",
            runs=balanced,
            events=[_event("wrong-workers", 0, worker_count=16)],
            tags=["worker-context"],
        ),
    ]


def main() -> None:
    cases = build_cases()
    CORPUS.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(case, sort_keys=True) + "\n" for case in cases)
    CORPUS.write_text(payload, encoding="utf-8")
    manifest = {
        "schema_version": "infrastructure-evaluation-v1",
        "case_count": len(cases),
        "scenario_family_count": len({tag for case in cases for tag in case["tags"]}),
        "case_ids": [case["case_id"] for case in cases],
        "corpus_sha256": hashlib.sha256(payload.encode()).hexdigest(),
        "source_kind": "controlled_synthetic",
        "limitations": [
            "Cases are controlled, synthetic, and agent-authored; they do not estimate production prevalence.",
            "The fixture evaluates deterministic compatibility, leakage, accounting, and dangerous-downgrade boundaries rather than causal attribution.",
            "A temporal association is never treated as proof that infrastructure caused a test outcome.",
        ],
    }
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
