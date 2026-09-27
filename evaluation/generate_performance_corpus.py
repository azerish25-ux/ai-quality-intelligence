from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "corpus" / "performance-cases.jsonl"
MANIFEST = ROOT / "corpus" / "performance-manifest.json"


BASE_DIMENSIONS = {
    "environment": "ci-linux",
    "browser": None,
    "run_scope": "full_suite",
    "producer": "k6-handleSummary",
    "producer_version": "0.54.0",
    "load_profile": "steady-10-vus-60s",
    "region": "ca-central-1",
    "executor": "ubuntu-24.04-x64",
}


def _policy(**overrides: Any) -> dict[str, Any]:
    value = {
        "relative_tolerance": 0.10,
        "absolute_tolerance": 5.0,
        "min_baseline_runs": 3,
        "max_baseline_age_days": 30,
        "require_trusted": True,
        "required_dimensions": [
            "repository",
            "workload",
            "environment",
            "browser",
            "run_scope",
            "producer",
            "producer_version",
            "load_profile",
            "region",
            "executor",
        ],
    }
    value.update(overrides)
    return value


def _current(**overrides: Any) -> dict[str, Any]:
    value = {
        "project": "failurelens",
        "repository": "example/ledgerguard",
        "metric_name": "http_req_duration",
        "metric_scope": "k6_summary",
        "statistic": "p95",
        "value": 100.0,
        "unit": "ms",
        "direction": "lower_is_better",
        "workload": "checkout-steady",
        "completeness": "complete",
        "trust": "trusted_workflow",
        "evidence_id": "evidence-current",
        **BASE_DIMENSIONS,
    }
    value.update(overrides)
    return value


def _baseline(index: int, value: float, **overrides: Any) -> dict[str, Any]:
    row = {
        "run_id": f"baseline-{index}",
        "project": "failurelens",
        "repository": "example/ledgerguard",
        "metric_name": "http_req_duration",
        "metric_scope": "k6_summary",
        "statistic": "p95",
        "value": value,
        "unit": "ms",
        "direction": "lower_is_better",
        "workload": "checkout-steady",
        "completeness": "complete",
        "trust": "trusted_workflow",
        "evidence_id": f"evidence-baseline-{index}",
        "prior": True,
        "age_days": index + 1,
        **BASE_DIMENSIONS,
    }
    row.update(overrides)
    return row


def _case(
    case_id: str,
    expected_status: str,
    *,
    current: dict[str, Any] | None = None,
    baselines: list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "schema_version": "performance-evaluation-v1",
        "expected_status": expected_status,
        "current": current or _current(),
        "baselines": baselines if baselines is not None else [
            _baseline(0, 98),
            _baseline(1, 100),
            _baseline(2, 102),
        ],
        "policy": policy or _policy(),
        "tags": tags or [],
    }


def build_cases() -> list[dict[str, Any]]:
    return [
        _case("perf-001-clear-regression", "REGRESSION", current=_current(value=130), tags=["regression"]),
        _case("perf-002-clear-improvement", "IMPROVEMENT", current=_current(value=75), tags=["improvement"]),
        _case("perf-003-within-tolerance", "WITHIN_TOLERANCE", current=_current(value=106), tags=["tolerance"]),
        _case("perf-004-missing-baseline", "BASELINE_UNAVAILABLE", baselines=[], tags=["missing-baseline"]),
        _case(
            "perf-005-stale-baseline",
            "INCOMPATIBLE_BASELINE",
            baselines=[_baseline(index, 100 + index, age_days=90) for index in range(3)],
            tags=["stale"],
        ),
        _case(
            "perf-006-different-workload",
            "INCOMPATIBLE_BASELINE",
            baselines=[_baseline(index, 100 + index, workload="search-steady") for index in range(3)],
            tags=["workload"],
        ),
        _case(
            "perf-007-different-environment",
            "INCOMPATIBLE_BASELINE",
            baselines=[_baseline(index, 100 + index, environment="staging") for index in range(3)],
            tags=["environment"],
        ),
        _case(
            "perf-008-incompatible-unit",
            "INCOMPATIBLE_BASELINE",
            baselines=[_baseline(index, 100 + index, unit="unknown") for index in range(3)],
            tags=["unit"],
        ),
        _case(
            "perf-009-explicit-unit-conversion",
            "REGRESSION",
            current=_current(value=0.13, unit="s"),
            baselines=[_baseline(0, 98), _baseline(1, 100), _baseline(2, 102)],
            tags=["unit-conversion"],
        ),
        _case(
            "perf-010-different-statistic",
            "INCOMPATIBLE_BASELINE",
            baselines=[_baseline(index, 100 + index, statistic="avg") for index in range(3)],
            tags=["statistic"],
        ),
        _case(
            "perf-011-incomplete-current",
            "INCOMPATIBLE_BASELINE",
            current=_current(value=80, completeness="partial"),
            tags=["completeness"],
        ),
        _case(
            "perf-012-incomplete-baselines",
            "INCOMPATIBLE_BASELINE",
            baselines=[_baseline(index, 100 + index, completeness="partial") for index in range(3)],
            tags=["completeness"],
        ),
        _case(
            "perf-013-future-leakage",
            "INCOMPATIBLE_BASELINE",
            baselines=[_baseline(index, 100 + index, prior=False) for index in range(3)],
            tags=["leakage"],
        ),
        _case(
            "perf-014-single-pair-no-significance",
            "WITHIN_TOLERANCE",
            current=_current(value=103),
            baselines=[_baseline(0, 100)],
            policy=_policy(min_baseline_runs=1),
            tags=["single-pair", "uncertainty"],
        ),
        _case(
            "perf-015-repeated-distribution",
            "REGRESSION",
            current=_current(value=140),
            baselines=[_baseline(0, 90), _baseline(1, 100), _baseline(2, 120), _baseline(3, 105)],
            tags=["repeated", "uncertainty"],
        ),
        _case(
            "perf-016-p95-anti-averaging",
            "REGRESSION",
            current=_current(value=135, statistic="p95"),
            baselines=[_baseline(0, 90), _baseline(1, 100), _baseline(2, 120)],
            tags=["percentile", "anti-averaging"],
        ),
        _case(
            "perf-017-threshold-attribution-uncertain",
            "WITHIN_TOLERANCE",
            current=_current(value=105, threshold_status="failed"),
            tags=["threshold", "attribution"],
        ),
        _case(
            "perf-018-project-isolation",
            "INCOMPATIBLE_BASELINE",
            baselines=[_baseline(index, 100 + index, project="other-project") for index in range(3)],
            tags=["isolation"],
        ),
        _case(
            "perf-019-higher-is-better-regression",
            "REGRESSION",
            current=_current(
                metric_name="http_reqs",
                statistic="rate",
                value=75,
                unit="requests/s",
                direction="higher_is_better",
            ),
            baselines=[
                _baseline(index, value, metric_name="http_reqs", statistic="rate", unit="requests/s", direction="higher_is_better")
                for index, value in enumerate((98, 100, 102))
            ],
            tags=["direction"],
        ),
        _case(
            "perf-020-untrusted-current",
            "INCOMPATIBLE_BASELINE",
            current=_current(value=80, trust="self_reported"),
            tags=["trust"],
        ),
    ]


def main() -> None:
    cases = build_cases()
    CORPUS.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(case, sort_keys=True) + "\n" for case in cases)
    CORPUS.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    manifest = {
        "schema_version": "performance-evaluation-v1",
        "case_count": len(cases),
        "case_ids": [case["case_id"] for case in cases],
        "corpus_sha256": digest,
        "source_kind": "controlled_synthetic",
        "limitations": [
            "Cases are agent-authored controlled fixtures, not production workload evidence.",
            "Run-level exported percentiles are compared as run-level observations and never aggregated into a new percentile.",
        ],
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
