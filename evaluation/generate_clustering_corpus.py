from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "corpus" / "clustering-cases.jsonl"
MANIFEST = ROOT / "corpus" / "clustering-manifest.json"
GENERATOR_VERSION = "clustering-generator-v1"


def case(
    case_id: str,
    incident_id: str,
    *,
    message: str,
    exception_type: str,
    test_identity: str,
    source_path: str,
    browser: str | None = None,
    details: dict[str, Any] | None = None,
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
        "incident_id": incident_id,
        "label_provenance": "generator-owned incident label kept outside the runtime feature view",
        "label_review_status": "agent-reviewed",
        "oracle_rationale": rationale,
        "input": {
            "repository": "example/quality-target",
            "external_id": f"workflow-{case_id}",
            "run_attempt": 1,
            "message": message,
            "exception_type": exception_type,
            "test_identity": test_identity,
            "source_path": source_path,
            "browser": browser,
            "details": details or {},
        },
    }


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    for index, browser in enumerate(("chromium", "firefox", "webkit"), start=1):
        cases.append(case(
            f"pay-timeout-{index}",
            "incident-pay-timeout",
            message=(
                f"API timeout at src/checkout.ts:{100 + index} for request "
                f"9d8f5d2a-8fa2-4f34-9ba1-9ea6d94f68{index:02d} "
                f"on 2026-09-27T10:1{index}:12Z"
            ),
            exception_type="TimeoutError",
            test_identity="checkout::submits payment",
            source_path="tests/checkout.spec.ts",
            browser=browser,
            details={
                "route": f"/api/payments/{18740 + index}",
                "method": "POST",
                "selector": "[data-testid=submit-payment]",
                "stack_frames": [f"src/checkout.ts:{100 + index}", "src/client.ts:44"],
            },
            family="dynamic-cross-browser",
            rationale="The same selector, canonical API route, exception, and stack signature reproduce across browser dimensions; changing IDs and line numbers are noncausal noise.",
        ))

    for index, browser in enumerate(("chromium", "firefox", "webkit"), start=1):
        cases.append(case(
            f"ledger-duplicate-{index}",
            "incident-ledger-duplicate",
            message=f"ledger balance invariant violated after duplicate committed transfer {9000 + index}",
            exception_type="LedgerInvariantError",
            test_identity="ledger::rejects duplicate transfer",
            source_path="tests/ledger.spec.ts",
            browser=browser,
            details={
                "route": f"/api/transfers/{50000 + index}",
                "method": "POST",
                "assertion": "expected committed effect count == 1",
                "stack_frames": ["src/ledger/posting.py:212", "src/transfers/service.py:71"],
            },
            family="data-integrity",
            rationale="All observations share the ledger invariant, assertion direction, endpoint ownership, and stack frames.",
        ))

    for index in range(1, 3):
        cases.append(case(
            f"server-503-{index}",
            "incident-payment-service-503",
            message="payment service unavailable while creating authorization",
            exception_type="HttpError",
            test_identity="api::authorizes payment",
            source_path="tests/api/payment.spec.ts",
            browser="chromium",
            details={
                "route": "/api/payment-authorizations",
                "method": "POST",
                "http_status": 503,
                "stack_frames": ["src/payment/client.ts:81"],
            },
            family="http-status-boundary",
            rationale="The same 503 service failure and route are one incident.",
        ))
        cases.append(case(
            f"auth-401-{index}",
            "incident-authentication-401",
            message="payment request failed for the authorization endpoint",
            exception_type="HttpError",
            test_identity="api::authorizes payment",
            source_path="tests/api/payment.spec.ts",
            browser="chromium",
            details={
                "route": "/api/payment-authorizations",
                "method": "POST",
                "http_status": 401,
                "stack_frames": ["src/payment/client.ts:81"],
            },
            family="http-status-boundary",
            rationale="The 401 authentication failure is deliberately distinct from the 503 service incident despite a shared route.",
        ))

    for index in range(1, 3):
        cases.append(case(
            f"selector-pay-{index}",
            "incident-pay-selector",
            message="Timeout waiting for selector during checkout",
            exception_type="TimeoutError",
            test_identity="ui::checkout action",
            source_path="tests/ui/checkout.spec.ts",
            browser="chromium" if index == 1 else "firefox",
            details={"selector": "#pay-now", "stack_frames": ["tests/ui/checkout.spec.ts:55"]},
            family="selector-collision",
            rationale="Repeated failures of the same checkout control form one incident.",
        ))
        cases.append(case(
            f"selector-cancel-{index}",
            "incident-cancel-selector",
            message="Timeout waiting for selector during checkout",
            exception_type="TimeoutError",
            test_identity="ui::checkout action",
            source_path="tests/ui/checkout.spec.ts",
            browser="chromium" if index == 1 else "firefox",
            details={"selector": "#cancel-order", "stack_frames": ["tests/ui/checkout.spec.ts:77"]},
            family="selector-collision",
            rationale="The cancel control is a separate incident; generic timeout text must not erase selector identity.",
        ))

    for index in range(1, 3):
        cases.append(case(
            f"assert-equal-{index}",
            "incident-balance-equal",
            message="balance assertion failed after reversal",
            exception_type="AssertionError",
            test_identity="ledger::reversal balance",
            source_path="tests/ledger/reversal.spec.ts",
            browser="chromium",
            details={"assertion": "expected balance == 0", "stack_frames": ["tests/ledger/reversal.spec.ts:43"]},
            family="assertion-direction",
            rationale="The equality assertion failures share one expected invariant.",
        ))
        cases.append(case(
            f"assert-negated-{index}",
            "incident-balance-negated",
            message="balance assertion failed after reversal",
            exception_type="AssertionError",
            test_identity="ledger::reversal balance",
            source_path="tests/ledger/reversal.spec.ts",
            browser="chromium",
            details={"assertion": "expected balance != 0", "stack_frames": ["tests/ledger/reversal.spec.ts:43"]},
            family="assertion-direction",
            rationale="The negated assertion is a deliberately different incident; direction and negation are causally material.",
        ))

    cases.extend([
        case(
            "bridge-a",
            "incident-bridge-upstream",
            message="shared checkout signature while submitting payment",
            exception_type="TimeoutError",
            test_identity="checkout::shared signature",
            source_path="tests/bridge.spec.ts",
            browser="chromium",
            details={"route": "/api/payments", "method": "POST", "stack_frames": ["src/upstream.ts:10"]},
            family="bridge-prevention",
            rationale="A and B share the upstream API and stack signature.",
        ),
        case(
            "bridge-b",
            "incident-bridge-upstream",
            message="shared checkout signature while submitting payment",
            exception_type="TimeoutError",
            test_identity="checkout::shared signature",
            source_path="tests/bridge.spec.ts",
            browser="firefox",
            details={"route": "/api/payments", "method": "POST", "selector": "#pay", "stack_frames": ["src/upstream.ts:10", "src/downstream.ts:20"]},
            family="bridge-prevention",
            rationale="B contains both signals but belongs with A based on the upstream failure evidence.",
        ),
        case(
            "bridge-c",
            "incident-bridge-downstream",
            message="shared checkout signature while submitting payment",
            exception_type="TimeoutError",
            test_identity="checkout::shared signature",
            source_path="tests/bridge.spec.ts",
            browser="webkit",
            details={"selector": "#pay", "stack_frames": ["src/downstream.ts:20"]},
            family="bridge-prevention",
            rationale="C shares only the downstream side of B; complete-link consistency must prevent transitive merging with A.",
        ),
    ])

    outliers = [
        ("outlier-dns", "incident-dns", "DNS failure resolving artifact host", "NetworkError", {"runner_diagnostic": True}),
        ("outlier-disk", "incident-disk", "No space left while unpacking browser", "OSError", {"runner_diagnostic": True}),
        ("outlier-contract", "incident-contract", "mock contract drift for refund response", "ContractError", {"contract_mismatch": "test_expectation_stale"}),
    ]
    for case_id, incident_id, message, exception_type, details in outliers:
        cases.append(case(
            case_id,
            incident_id,
            message=message,
            exception_type=exception_type,
            test_identity=f"ops::{case_id}",
            source_path=f"tests/{case_id}.spec.ts",
            browser=None,
            details=details,
            family="outliers",
            rationale="This observation has no corroborating peer and must remain visible as a singleton outlier.",
        ))

    return cases


def main() -> None:
    cases = build_cases()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in cases)
    OUTPUT.write_text(text, encoding="utf-8")
    manifest = {
        "schema_version": "1.0",
        "generator_version": GENERATOR_VERSION,
        "case_count": len(cases),
        "incident_count": len({item["incident_id"] for item in cases}),
        "family_counts": dict(sorted(Counter(item["scenario_family_id"] for item in cases).items())),
        "source_counts": {"synthetic": len(cases), "executed": 0},
        "corpus_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "label_boundary": "incident_id and oracle fields are evaluation-only and are never passed to feature extraction or clustering",
        "limitations": [
            "All clustering cases are synthetic and agent-authored.",
            "The fixture is a regression benchmark, not an independently blinded generalization study.",
            "Screenshot similarity and causal upstream/downstream edge evaluation are not represented in this slice.",
        ],
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
