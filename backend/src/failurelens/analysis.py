from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

from .models import Category
from .transaction_evidence import transaction_findings
from .contract_evidence import CLAIM_TEXT, contract_findings

ANALYSIS_VERSION = "deterministic-v4"
RULES_VERSION = "rules-v4"


@dataclass(frozen=True)
class EvidenceView:
    id: str
    kind: str
    excerpt: str
    observation: dict[str, Any]


@dataclass(frozen=True)
class DeterministicDecision:
    category: Category
    severity: str
    score: float | None
    score_kind: str
    explanation: str
    summary: str
    supporting_ids: tuple[str, ...]
    contradictory_ids: tuple[str, ...]
    missing: tuple[str, ...]
    claims: tuple[dict[str, Any], ...]
    hypotheses: tuple[dict[str, Any], ...]
    next_steps: tuple[dict[str, Any], ...]
    abstention_reason: str | None
    policy_flags: tuple[str, ...]
    signal_counts: dict[str, int]


def _has(text: str, terms: Iterable[str]) -> bool:
    folded = text.casefold()
    return any(term.casefold() in folded for term in terms)


def _history_supports_known_flake(historical: dict[str, Any]) -> bool:
    return bool(
        historical.get("history_eligible_for_reassurance") is True
        and historical.get("reviewed_known_flake") is True
        and historical.get("independent_runs", 0) >= 5
        and historical.get("observed_passes", 0) > 0
        and historical.get("observed_failures", 0) > 0
    )


def rule_signal_counts(
    *,
    message: str,
    exception_type: str | None,
    details: dict[str, Any],
    evidence: list[EvidenceView],
    historical: dict[str, Any] | None = None,
) -> dict[Category, int]:
    """Return the deterministic rule scores used by analysis and validation.

    Keeping this as a pure function lets the publication validator recompute the
    typed predicate instead of trusting a status written by the analyzer.
    """
    historical = historical or {}
    all_text = "\n".join(
        [message, exception_type or "", json.dumps(details, sort_keys=True)]
        + [
            "\n".join(
                [
                    item.excerpt,
                    json.dumps(item.observation, sort_keys=True, ensure_ascii=False),
                ]
            )
            for item in evidence
        ]
    )

    product_signals = 8 if any(f.status == "duplicate" for _, f in transaction_findings(evidence)) else 0
    if any(f.status == "violated" for _, f in contract_findings(evidence)):
        product_signals += 8
    test_signals = 0
    infrastructure_signals = 0
    flake_signals = 0

    if _has(
        all_text,
        [
            "duplicate committed",
            "double charge",
            "ledger unbalanced",
            "balance invariant",
            "over-credit",
            "authorization bypass",
            "cross-account",
        ],
    ):
        product_signals += 4
    if details.get("data_integrity_violation") is True:
        product_signals += 5
    if (
        details.get("http_status") in {500, 502, 503}
        and details.get("service_error_corroborated") is True
    ):
        product_signals += 2

    if _has(
        all_text,
        [
            "expected contract",
            "stale selector",
            "fixture invalid",
            "teardown leaked",
            "mock contract drift",
        ],
    ):
        test_signals += 3
    if details.get("contract_mismatch") == "test_expectation_stale":
        test_signals += 5

    if _has(
        all_text,
        [
            "runner exited",
            "connection refused",
            "dns failure",
            "no space left",
            "database unavailable",
            "browser process crashed",
        ],
    ):
        infrastructure_signals += 3
    if details.get("runner_diagnostic") is True:
        infrastructure_signals += 3

    if _history_supports_known_flake(historical):
        flake_signals += 5
    if historical.get("retry_recovery_rate", 0) > 0.2:
        flake_signals += 1

    return {
        Category.product_defect: product_signals,
        Category.test_defect: test_signals,
        Category.infrastructure_failure: infrastructure_signals,
        Category.known_flake: flake_signals,
    }


def _serialized_scores(scores: dict[Category, int]) -> dict[str, int]:
    return {category.value: score for category, score in scores.items()}


def _evidence_ids_supporting_category(
    *,
    evidence: list[EvidenceView],
    category: Category,
    historical: dict[str, Any],
) -> tuple[str, ...]:
    supporting: list[str] = []
    for item in evidence:
        observation = item.observation if isinstance(item.observation, dict) else {}
        details = observation.get("details")
        if not isinstance(details, dict):
            details = {}
        scores = rule_signal_counts(
            message=str(observation.get("message") or item.excerpt),
            exception_type=(
                str(observation["exception_type"])
                if observation.get("exception_type") is not None
                else None
            ),
            details=details,
            evidence=[item],
            historical=historical,
        )
        if scores.get(category, 0) > 0:
            supporting.append(item.id)
    return tuple(supporting)


def analyze_failure(
    *,
    message: str,
    exception_type: str | None,
    details: dict[str, Any],
    evidence: list[EvidenceView],
    historical: dict[str, Any] | None = None,
) -> DeterministicDecision:
    historical = historical or {}
    evidence_ids = tuple(item.id for item in evidence)
    contradictions: list[str] = []
    missing: list[str] = []
    flags: list[str] = []
    scores = rule_signal_counts(
        message=message,
        exception_type=exception_type,
        details=details,
        evidence=evidence,
        historical=historical,
    )
    serialized_scores = _serialized_scores(scores)
    product_signals = scores[Category.product_defect]
    test_signals = scores[Category.test_defect]
    infrastructure_signals = scores[Category.infrastructure_failure]
    flake_signals = scores[Category.known_flake]

    if details.get("retry_recovered") is True and not historical.get(
        "reviewed_known_flake"
    ):
        flags.append("retry_recovered_not_proof_of_flake")
    if details.get("incomplete_run") is True:
        missing.append("complete run/shard evidence")
    if details.get("trace_missing") is True:
        missing.append("trace attachment")
    if details.get("contradictory_product_signal") is True:
        scores[Category.product_defect] += 2
        product_signals += 2
        serialized_scores[Category.product_defect.value] = product_signals
        contradictions.extend(evidence_ids[:1])
        flags.append("mixed_cause_or_contradictory_evidence")

    contracts = contract_findings(evidence)
    contract_conflict = any(f.status in {"invalid", "incomplete", "conflicting"} for _, f in contracts)
    for kind in {f.contract for _, f in contracts}:
        contract_conflict |= len({f.status for _, f in contracts if f.contract == kind}) > 1
    if contract_conflict:
        contradictions.extend(identifier for identifier, _ in contracts)
        flags.append("contract_measurements_incomplete_or_conflicting")
        missing.append("consistent execution-bound contract measurements")

    transactions = transaction_findings(evidence)
    transaction_conflict = bool(transactions and (
        any(f.status in {"invalid", "incomplete", "conflicting"} for _, f in transactions)
        or len({f.count for _, f in transactions}) > 1
    ))
    if transaction_conflict:
        contradictions.extend(identifier for identifier, _ in transactions)
        flags.append("transaction_measurements_incomplete_or_conflicting")
        missing.append("consistent correlated transaction measurements")

    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0].value))
    winner, winner_score = ordered[0]
    runner_up_score = ordered[1][1]

    if contract_conflict or transaction_conflict or winner_score < 3 or winner_score == runner_up_score or not evidence_ids:
        reason = "Available observations do not distinguish the required categories safely."
        if product_signals >= 2 and max(
            test_signals, infrastructure_signals, flake_signals
        ) >= 2:
            flags.append("dangerous_downgrade_blocked")
        if not evidence_ids:
            missing.append("resolvable current-run evidence")
        return DeterministicDecision(
            category=Category.insufficient_evidence,
            severity="high" if product_signals else "medium",
            score=None,
            score_kind="unavailable",
            explanation=reason,
            summary=(
                "Failure requires human investigation because the current evidence "
                "is insufficient for a safe causal classification."
            ),
            supporting_ids=evidence_ids,
            contradictory_ids=tuple(contradictions),
            missing=tuple(sorted(set(missing))),
            claims=tuple(),
            hypotheses=(
                {
                    "description": "Cause remains unresolved",
                    "evidence_ids": list(evidence_ids),
                    "counterevidence_ids": list(contradictions),
                    "status": "unverified",
                },
            ),
            next_steps=(
                {
                    "action": (
                        "Collect missing current-run artifacts and reproduce under "
                        "controlled conditions"
                    ),
                    "rationale": reason,
                    "evidence_ids": list(evidence_ids),
                },
            ),
            abstention_reason=reason,
            policy_flags=tuple(sorted(set(flags + ["safe_abstention"]))),
            signal_counts=serialized_scores,
        )

    margin = winner_score - runner_up_score
    heuristic = min(0.95, 0.52 + winner_score * 0.06 + margin * 0.04)
    category_text = {
        Category.product_defect: "probable product defect",
        Category.test_defect: "probable test defect",
        Category.infrastructure_failure: (
            "probable infrastructure or environment failure"
        ),
        Category.known_flake: "known flaky behavior",
        Category.insufficient_evidence: "insufficient evidence",
    }[winner]

    if winner is Category.known_flake and not _history_supports_known_flake(
        historical
    ):
        flags.append("known_flake_requires_reviewed_history")
        return analyze_failure(
            message=message,
            exception_type=exception_type,
            details={**details, "retry_recovered": details.get("retry_recovered")},
            evidence=evidence,
            historical={},
        )

    if (
        winner
        in {
            Category.infrastructure_failure,
            Category.known_flake,
            Category.test_defect,
        }
        and product_signals >= 2
    ):
        flags.append("product_risk_preserved")
        contradictions.extend(evidence_ids[:1])
        if margin < 3:
            return DeterministicDecision(
                category=Category.insufficient_evidence,
                severity="high",
                score=None,
                score_kind="unavailable",
                explanation=(
                    "A possible product-risk signal conflicts with the leading "
                    "non-product explanation."
                ),
                summary=(
                    "Failure is not safely dismissible; contradictory product-risk "
                    "evidence requires review."
                ),
                supporting_ids=evidence_ids,
                contradictory_ids=tuple(sorted(set(contradictions))),
                missing=tuple(sorted(set(missing))),
                claims=tuple(),
                hypotheses=(
                    {
                        "description": category_text,
                        "evidence_ids": list(evidence_ids),
                        "counterevidence_ids": list(contradictions),
                        "status": "conflicted",
                    },
                ),
                next_steps=(
                    {
                        "action": (
                            "Investigate the product-risk signal before considering "
                            "a non-product disposition"
                        ),
                        "rationale": (
                            "Safety policy prevents unsupported reassurance."
                        ),
                        "evidence_ids": list(evidence_ids),
                    },
                ),
                abstention_reason=(
                    "Contradictory product-risk evidence prevents a safe classification."
                ),
                policy_flags=tuple(
                    sorted(set(flags + ["dangerous_downgrade_blocked"]))
                ),
                signal_counts=serialized_scores,
            )

    severity = (
        "critical"
        if details.get("data_integrity_violation")
        or details.get("authorization_violation")
        else "high"
        if winner is Category.product_defect
        else "medium"
    )
    claim_evidence_ids = _evidence_ids_supporting_category(
        evidence=evidence,
        category=winner,
        historical=historical,
    )
    claim = {
        "id": "claim-1",
        "kind": "inference",
        "text": f"Observed signals support a {category_text} classification.",
        "evidence_ids": list(claim_evidence_ids),
        "predicate": {
            "kind": "classification_signal",
            "category": winner.value,
            "minimum_score": 3,
        },
        "validation_status": "pending",
    }
    violations = [(identifier, finding) for identifier, finding in contracts if finding.status == "violated"]
    if winner is Category.product_defect and violations:
        kind = violations[0][1].contract
        claim_evidence_ids = tuple(identifier for identifier, finding in violations if finding.contract == kind)
        claim = {"id": "claim-1", "kind": "inference", "text": CLAIM_TEXT[kind],
                 "evidence_ids": list(claim_evidence_ids),
                 "predicate": {"kind": "contract_violation", "contract": kind},
                 "validation_status": "pending"}
        severity = "critical" if kind == "operation_isolation" else "high"
        flags.append("structured_contract_violation")
    duplicate_findings = [(identifier, finding) for identifier, finding in transactions if finding.status == "duplicate"]
    if winner is Category.product_defect and duplicate_findings:
        claim_evidence_ids = tuple(identifier for identifier, _ in duplicate_findings)
        observed_count = duplicate_findings[0][1].count
        claim = {
            "id": "claim-1", "kind": "inference",
            "text": f"Reported request and database measurements reconcile {observed_count} committed effects for one retried logical request; this supports a product-defect investigation without establishing the responsible component.",
            "evidence_ids": list(claim_evidence_ids),
            "predicate": {"kind": "committed_effect_multiplicity", "count": observed_count},
            "validation_status": "pending",
        }
        severity = "critical"
        flags.append("transaction_effect_multiplicity")
    return DeterministicDecision(
        category=winner,
        severity=severity,
        score=round(heuristic, 3),
        score_kind="heuristic_score",
        explanation=(
            "Rule signals: "
            f"product={product_signals}, test={test_signals}, "
            f"infrastructure={infrastructure_signals}, "
            f"known-flake={flake_signals}. This is not a calibrated probability."
        ),
        summary=(
            f"Failure is classified as {category_text} based on validated "
            "current-run observations and allowed historical context."
        ),
        supporting_ids=claim_evidence_ids,
        contradictory_ids=tuple(sorted(set(contradictions))),
        missing=tuple(sorted(set(missing))),
        claims=(claim,),
        hypotheses=tuple(),
        next_steps=(
            {
                "action": "Review the cited evidence and reproduce the leading hypothesis",
                "rationale": (
                    "Classification remains an engineering aid rather than release approval."
                ),
                "evidence_ids": list(claim_evidence_ids),
            },
        ),
        abstention_reason=None,
        policy_flags=tuple(sorted(set(flags))),
        signal_counts=serialized_scores,
    )


def input_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
