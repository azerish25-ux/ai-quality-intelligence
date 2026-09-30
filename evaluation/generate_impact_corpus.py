from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "corpus" / "impact-cases.jsonl"
MANIFEST = ROOT / "corpus" / "impact-manifest.json"
GENERATOR_VERSION = "impact-generator-v1"


def _case(
    case_id: str,
    *,
    changes: list[dict[str, Any]],
    revealing_tests: list[str],
    expected_status: str = "FOCUSED_SUBSET",
    safety_reasons: list[str] | None = None,
    family: str,
    rationale: str,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "schema_version": "1.0",
        "source_kind": "synthetic",
        "source_revision": GENERATOR_VERSION,
        "split": "test",
        "scenario_family_id": family,
        "label_provenance": "agent-authored controlled mapping oracle",
        "label_review_status": "agent-reviewed",
        "changes": changes,
        "preexisting_safety_reasons": safety_reasons or [],
        "expected_status": expected_status,
        "defect_revealing_tests": revealing_tests,
        "oracle_rationale": rationale,
    }


def build_mapping() -> dict[str, Any]:
    return {
        "tests": [
            {
                "test_key": "smoke",
                "test_identity": "tests/smoke.spec.ts::critical smoke",
                "source_path": "tests/smoke.spec.ts",
                "criticality": "critical",
                "mandatory": True,
                "tags": ["smoke", "security"],
                "estimated_duration_ms": 500,
            },
            {
                "test_key": "ledger",
                "test_identity": "tests/ledger.spec.ts::transaction invariants",
                "source_path": "tests/ledger.spec.ts",
                "criticality": "critical",
                "mandatory": True,
                "tags": ["transaction"],
                "estimated_duration_ms": 2500,
            },
            {
                "test_key": "checkout",
                "test_identity": "tests/checkout.spec.ts::submits payment",
                "source_path": "tests/checkout.spec.ts",
                "criticality": "high",
                "mandatory": False,
                "tags": ["checkout"],
                "estimated_duration_ms": 1200,
            },
            {
                "test_key": "profile",
                "test_identity": "tests/profile.spec.ts::updates avatar",
                "source_path": "tests/profile.spec.ts",
                "criticality": "normal",
                "mandatory": False,
                "tags": ["profile"],
                "estimated_duration_ms": 1800,
            },
            {
                "test_key": "reports",
                "test_identity": "tests/reports.spec.ts::exports statement",
                "source_path": "tests/reports.spec.ts",
                "criticality": "normal",
                "mandatory": False,
                "tags": ["reports"],
                "estimated_duration_ms": 900,
            },
        ],
        "edges": [
            {
                "source_path": "src/checkout.py",
                "target_type": "test",
                "target_value": "checkout",
                "kind": "coverage",
                "confidence": 0.97,
                "mapping_source": "controlled-coverage",
                "mapping_version": "coverage-v1",
            },
            {
                "source_path": "src/profile.py",
                "target_type": "test",
                "target_value": "profile",
                "kind": "coverage",
                "confidence": 0.95,
                "mapping_source": "controlled-coverage",
                "mapping_version": "coverage-v1",
            },
            {
                "source_path": "src/ledger.py",
                "target_type": "test",
                "target_value": "ledger",
                "kind": "file_to_test",
                "confidence": 1.0,
                "mapping_source": "reviewed-policy",
                "mapping_version": "policy-v1",
            },
            {
                "source_path": "src/reporting.py",
                "target_type": "test",
                "target_value": "reports",
                "kind": "coverage",
                "confidence": 0.92,
                "mapping_source": "controlled-coverage",
                "mapping_version": "coverage-v1",
            },
            {
                "source_path": "src/core.py",
                "target_type": "file",
                "target_value": "src/checkout.py",
                "kind": "dependency",
                "confidence": 0.93,
                "mapping_source": "controlled-import-graph",
                "mapping_version": "imports-v1",
            },
            {
                "source_path": "src/old-profile.py",
                "target_type": "test",
                "target_value": "profile",
                "kind": "ownership",
                "confidence": 0.9,
                "mapping_source": "reviewed-ownership",
                "mapping_version": "owners-v1",
            },
            {
                "source_path": "api/payments.openapi.yaml",
                "target_type": "test",
                "target_value": "checkout",
                "kind": "api_ownership",
                "confidence": 0.94,
                "mapping_source": "api-contract-map",
                "mapping_version": "api-v1",
            },
            {
                "source_path": "src/payment_gateway.py",
                "target_type": "test",
                "target_value": "checkout",
                "kind": "historical_failure",
                "confidence": 0.78,
                "mapping_source": "reviewed-prior-failures",
                "mapping_version": "history-v1",
            },
        ],
    }


def build_cases() -> list[dict[str, Any]]:
    return [
        _case(
            "impact-direct-checkout",
            changes=[{"status": "modified", "path": "src/checkout.py"}],
            revealing_tests=["checkout"],
            family="direct-coverage",
            rationale="The reviewed coverage edge directly maps checkout code to its defect-revealing test.",
        ),
        _case(
            "impact-direct-profile",
            changes=[{"status": "modified", "path": "src/profile.py"}],
            revealing_tests=["profile"],
            family="direct-coverage",
            rationale="The reviewed coverage edge directly maps profile code to the profile test.",
        ),
        _case(
            "impact-reverse-dependency",
            changes=[{"status": "modified", "path": "src/core.py"}],
            revealing_tests=["checkout"],
            family="reverse-dependency",
            rationale="The bounded reverse dependency chain reaches checkout coverage.",
        ),
        _case(
            "impact-renamed-old-path",
            changes=[
                {
                    "status": "renamed",
                    "path": "src/profile_new.py",
                    "old_path": "src/old-profile.py",
                }
            ],
            revealing_tests=["profile"],
            family="rename-delete",
            rationale="Rename handling must preserve the reviewed old-path ownership mapping.",
        ),
        _case(
            "impact-api-ownership",
            changes=[{"status": "modified", "path": "api/payments.openapi.yaml"}],
            revealing_tests=["checkout"],
            family="api-ownership",
            rationale="The versioned API ownership edge selects the consumer test.",
        ),
        _case(
            "impact-prior-failure-link",
            changes=[{"status": "modified", "path": "src/payment_gateway.py"}],
            revealing_tests=["checkout"],
            family="historical-link",
            rationale="A reviewed prior-failure relationship adds the relevant checkout test without implying causality.",
        ),
        _case(
            "impact-multiple-mapped-files",
            changes=[
                {"status": "modified", "path": "src/checkout.py"},
                {"status": "modified", "path": "src/reporting.py"},
            ],
            revealing_tests=["checkout", "reports"],
            family="multi-change",
            rationale="Both independently mapped defect-revealing tests must be selected.",
        ),
        _case(
            "impact-unmapped-fallback",
            changes=[{"status": "modified", "path": "src/unknown_module.py"}],
            revealing_tests=["profile"],
            expected_status="FULL_SUITE_REQUIRED",
            family="safety-fallback",
            rationale="An unmapped path cannot justify narrowing, so all tests must remain selected.",
        ),
        _case(
            "impact-critical-ci-fallback",
            changes=[{"status": "modified", "path": ".github/workflows/ci.yml"}],
            revealing_tests=["checkout"],
            expected_status="FULL_SUITE_REQUIRED",
            family="critical-policy",
            rationale="CI configuration changes require broad execution regardless of mapping sparsity.",
        ),
        _case(
            "impact-untrusted-comparison",
            changes=[{"status": "modified", "path": "src/checkout.py"}],
            revealing_tests=["checkout"],
            expected_status="FULL_SUITE_REQUIRED",
            safety_reasons=["changed_file_list_untrusted"],
            family="provenance-boundary",
            rationale="Self-reported comparison data cannot reduce the trusted test scope.",
        ),
        _case(
            "impact-incomplete-mapping",
            changes=[{"status": "modified", "path": "src/profile.py"}],
            revealing_tests=["profile"],
            expected_status="FULL_SUITE_REQUIRED",
            safety_reasons=["mapping_coverage_incomplete"],
            family="mapping-completeness",
            rationale="Incomplete mapping coverage forces a full-suite recommendation.",
        ),
        _case(
            "impact-empty-change-set",
            changes=[],
            revealing_tests=["ledger"],
            expected_status="FULL_SUITE_REQUIRED",
            family="missing-input",
            rationale="An empty comparison cannot be interpreted as proof that no tests are required.",
        ),
    ]


def main() -> None:
    mapping = build_mapping()
    cases = build_cases()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in cases),
        encoding="utf-8",
    )
    payload = OUTPUT.read_bytes()
    families = Counter(item["scenario_family_id"] for item in cases)
    manifest = {
        "schema_version": "1.0",
        "generator_version": GENERATOR_VERSION,
        "case_count": len(cases),
        "scenario_family_count": len(families),
        "scenario_families": dict(sorted(families.items())),
        "source_kind": "synthetic",
        "mapping": mapping,
        "cases_sha256": hashlib.sha256(payload).hexdigest(),
        "limitations": [
            "All cases and mapping oracles are synthetic and agent-authored.",
            "Durations are declared fixture estimates, not observed runtime measurements.",
            "The fixture does not satisfy the required actual LedgerGuard execution count.",
        ],
    }
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"cases": len(cases), "manifest": str(MANIFEST)}, indent=2))


if __name__ == "__main__":
    main()
