from __future__ import annotations

from .telemetry import instrument

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .analysis import DeterministicDecision, EvidenceView, rule_signal_counts
from .config import Settings, get_settings
from .models import Category, Evidence, Failure
from .transaction_evidence import inspect_multiplicity
from .contract_evidence import CLAIM_TEXT, CONTRACT_CATEGORY, inspect_contract
from .domain_evidence import inspect_domain
from .storage import StorageError, read_stored_bytes

VALIDATION_VERSION = "evidence-validation-v3"
_ALLOWED_DERIVATIVE_MEDIA_TYPES = {
    "application/json",
    "application/vnd.failurelens.evidence+json",
    "text/plain",
}
_VALIDATED_PUBLICATION_STATES = {"passed", "degraded"}
_FORBIDDEN_CLAIM_PHRASES = (
    "release approved",
    "safe to merge",
    "definitely harmless",
    "delete the test",
    "suppress the failure",
)


def persisted_analysis_is_publication_validated(analysis: Any) -> bool:
    validation = getattr(analysis, "validation_results", None) or {}
    category = getattr(getattr(analysis, "category", None), "value", None)
    return bool(
        getattr(analysis, "validation_version", None)
        and validation.get("status") in _VALIDATED_PUBLICATION_STATES
        and validation.get("published_category") == category
    )


@dataclass(frozen=True)
class EvidenceIntegrity:
    evidence_id: str
    reference_valid: bool
    authorized: bool
    digest_valid: bool
    locator_valid: bool
    quotation_valid: bool
    observation_valid: bool
    policy_safe: bool
    actual_digest: str | None
    reasons: tuple[str, ...]
    derivative_payload: dict[str, Any] | None

    @property
    def valid(self) -> bool:
        return all(
            (
                self.reference_valid,
                self.authorized,
                self.digest_valid,
                self.locator_valid,
                self.quotation_valid,
                self.observation_valid,
                self.policy_safe,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "reference_valid": self.reference_valid,
            "authorized": self.authorized,
            "digest_valid": self.digest_valid,
            "locator_valid": self.locator_valid,
            "quotation_valid": self.quotation_valid,
            "observation_valid": self.observation_valid,
            "policy_safe": self.policy_safe,
            "actual_digest": self.actual_digest,
            "status": "verified" if self.valid else "rejected",
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class EvidenceValidationSet:
    checks: tuple[EvidenceIntegrity, ...]

    @property
    def accepted_ids(self) -> tuple[str, ...]:
        return tuple(item.evidence_id for item in self.checks if item.valid)

    @property
    def rejected_ids(self) -> tuple[str, ...]:
        return tuple(item.evidence_id for item in self.checks if not item.valid)

    def check_for(self, evidence_id: str) -> EvidenceIntegrity | None:
        return next(
            (item for item in self.checks if item.evidence_id == evidence_id),
            None,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted_evidence_ids": list(self.accepted_ids),
            "rejected_evidence_ids": list(self.rejected_ids),
            "evidence": [item.as_dict() for item in self.checks],
        }


@dataclass(frozen=True)
class ValidatedDecision:
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
    validation_results: dict[str, Any]


def _scope_is_authorized(failure: Failure, evidence: Evidence) -> bool:
    if evidence.project_id != failure.project_id or evidence.run_id != failure.run_id:
        return False
    if evidence.execution_id == failure.execution_id:
        return evidence.provenance_kind == "current_execution"
    if evidence.execution_id is not None:
        return False
    if evidence.provenance_kind == "shared_run_diagnostic":
        return True
    if evidence.provenance_kind == "input_diagnostic":
        input_id = failure.execution.details.get("input_id")
        return bool(
            input_id
            and evidence.run_input is not None
            and evidence.run_input.input_id == input_id
        )
    return False


def _json_pointer(payload: dict[str, Any], pointer: str) -> Any:
    if pointer == "":
        return payload
    if not pointer.startswith("/"):
        raise ValueError("invalid JSON Pointer")
    value: Any = payload
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise KeyError(pointer)
    return value


@instrument("evidence")
def validate_evidence_records(
    failure: Failure,
    evidence_rows: list[Evidence],
    *,
    settings: Settings | None = None,
) -> EvidenceValidationSet:
    settings = settings or get_settings()
    checks: list[EvidenceIntegrity] = []

    for evidence in evidence_rows:
        reasons: list[str] = []
        derivative = evidence.derivative
        reference_valid = bool(
            derivative is not None
            and derivative.project_id == evidence.project_id
            and derivative.run_id == evidence.run_id
            and derivative.artifact_id == evidence.artifact_id
            and evidence.artifact.run_id == evidence.run_id
        )
        if not reference_valid:
            reasons.append("invalid_derivative_reference")

        authorized = _scope_is_authorized(failure, evidence)
        if not authorized:
            reasons.append("evidence_outside_failure_scope")

        actual_digest: str | None = None
        derivative_payload: dict[str, Any] | None = None
        digest_valid = False
        locator_valid = False
        quotation_valid = False
        observation_valid = False
        policy_safe = False

        if reference_valid and derivative is not None:
            try:
                content = read_stored_bytes(
                    root=settings.artifact_root,
                    relative_path=derivative.storage_path,
                    expected_digest=derivative.digest,
                    expected_size=derivative.size_bytes,
                    max_bytes=settings.analysis_text_budget * 4,
                )
                actual_digest = hashlib.sha256(content).hexdigest()
                digest_valid = (
                    actual_digest == derivative.digest == evidence.content_digest
                    and derivative.source_digest == evidence.artifact.digest
                    and derivative.redaction_version == evidence.redaction_version
                )
                if not digest_valid:
                    reasons.append("derivative_digest_or_provenance_mismatch")
            except StorageError as exc:
                reasons.append(exc.code)
                content = b""
            except OSError:
                reasons.append("derivative_read_failed")
                content = b""

            if content and derivative.media_type in _ALLOWED_DERIVATIVE_MEDIA_TYPES:
                try:
                    decoded = content.decode("utf-8")
                    if derivative.media_type == "text/plain":
                        derivative_payload = {
                            "excerpt": decoded,
                            "observation": {},
                        }
                    else:
                        parsed = json.loads(decoded)
                        if isinstance(parsed, dict):
                            derivative_payload = parsed
                        else:
                            reasons.append("derivative_payload_not_object")
                except (UnicodeDecodeError, json.JSONDecodeError):
                    reasons.append("derivative_payload_invalid")
            elif content:
                reasons.append("derivative_media_type_not_publication_safe")

            locator = evidence.locator
            try:
                locator_valid = bool(
                    evidence.locator_version == "evidence-locator-v2"
                    and locator.get("version") == "evidence-locator-v2"
                    and isinstance(locator.get("source"), dict)
                    and isinstance(locator.get("derivative"), dict)
                    and locator["derivative"].get("kind") == "json-pointer"
                    and derivative_payload is not None
                )
                if locator_valid:
                    pointed = _json_pointer(
                        derivative_payload,
                        str(locator["derivative"].get("pointer", "")),
                    )
                    locator_valid = isinstance(pointed, str)
                if not locator_valid:
                    reasons.append("invalid_or_out_of_bounds_locator")
            except (KeyError, TypeError, ValueError):
                locator_valid = False
                reasons.append("invalid_or_out_of_bounds_locator")

            if locator_valid and derivative_payload is not None:
                pointed = _json_pointer(
                    derivative_payload,
                    str(evidence.locator["derivative"]["pointer"]),
                )
                quotation_valid = pointed == evidence.excerpt
                if not quotation_valid:
                    reasons.append("excerpt_does_not_match_safe_derivative")
                observation_valid = (
                    derivative_payload.get("observation") == evidence.observation
                )
                if not observation_valid:
                    reasons.append("typed_observation_does_not_match_derivative")

            policy_safe = bool(
                derivative.approved
                and not derivative.restricted
                and derivative.approval_state in {"auto_approved_text", "reviewed"}
                and derivative.retention_state == "active"
                and derivative.media_type in _ALLOWED_DERIVATIVE_MEDIA_TYPES
            )
            if not policy_safe:
                reasons.append("derivative_not_approved_for_analysis")

        checks.append(
            EvidenceIntegrity(
                evidence_id=evidence.id,
                reference_valid=reference_valid,
                authorized=authorized,
                digest_valid=digest_valid,
                locator_valid=locator_valid,
                quotation_valid=quotation_valid,
                observation_valid=observation_valid,
                policy_safe=policy_safe,
                actual_digest=actual_digest,
                reasons=tuple(dict.fromkeys(reasons)),
                derivative_payload=derivative_payload,
            )
        )

    return EvidenceValidationSet(checks=tuple(checks))


def validated_evidence_views(
    evidence_rows: list[Evidence], validation: EvidenceValidationSet
) -> list[EvidenceView]:
    accepted = set(validation.accepted_ids)
    return [
        EvidenceView(
            id=evidence.id,
            kind=evidence.kind,
            excerpt=evidence.excerpt,
            observation=evidence.observation,
        )
        for evidence in evidence_rows
        if evidence.id in accepted
    ]


def _validated_reference_ids(
    values: Any, accepted_ids: set[str]
) -> tuple[str, ...]:
    if not isinstance(values, list):
        return tuple()
    return tuple(
        value
        for value in values
        if isinstance(value, str) and value in accepted_ids
    )


def _claim_validation(
    *,
    claim: dict[str, Any],
    decision: DeterministicDecision,
    failure: Failure,
    evidence_rows: list[Evidence],
    evidence_validation: EvidenceValidationSet,
    historical: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    accepted_ids = set(evidence_validation.accepted_ids)
    requested_ids = claim.get("evidence_ids")
    validated_ids = _validated_reference_ids(requested_ids, accepted_ids)
    reference_valid = bool(
        isinstance(requested_ids, list)
        and requested_ids
        and len(validated_ids) == len(requested_ids)
    )

    quotation_valid = True
    quote = claim.get("quote")
    if quote is not None:
        quotation_valid = bool(
            isinstance(quote, str)
            and quote
            and any(
                check.valid
                and check.evidence_id in validated_ids
                and check.derivative_payload is not None
                and quote in str(check.derivative_payload.get("excerpt", ""))
                for check in evidence_validation.checks
            )
        )

    predicate = claim.get("predicate")
    typed_predicate_valid = bool(
        isinstance(predicate, dict)
        and predicate.get("kind") == "classification_signal"
        and predicate.get("category") in {item.value for item in Category}
        and isinstance(predicate.get("minimum_score"), int)
        and predicate["minimum_score"] >= 0
    )

    valid_rows = [
        item
        for item in evidence_rows
        if item.id in accepted_ids and item.id in validated_ids
    ]
    per_reference_scores: dict[str, dict[Category, int]] = {}
    for item in valid_rows:
        observation = item.observation if isinstance(item.observation, dict) else {}
        details = observation.get("details")
        if not isinstance(details, dict):
            details = {}
        view = EvidenceView(
            id=item.id,
            kind=item.kind,
            excerpt=item.excerpt,
            observation=observation,
        )
        per_reference_scores[item.id] = rule_signal_counts(
            message=str(observation.get("message") or item.excerpt),
            exception_type=(
                str(observation["exception_type"])
                if observation.get("exception_type") is not None
                else None
            ),
            details=details,
            evidence=[view],
            historical=historical,
        )

    semantic_support = False
    irrelevant_reference_ids: list[str] = []
    aggregate_score = 0
    if typed_predicate_valid:
        category = Category(str(predicate["category"]))
        reference_scores = {
            evidence_id: scores.get(category, 0)
            for evidence_id, scores in per_reference_scores.items()
        }
        irrelevant_reference_ids = sorted(
            evidence_id
            for evidence_id in validated_ids
            if reference_scores.get(evidence_id, 0) <= 0
        )
        aggregate_score = max(reference_scores.values(), default=0)
        semantic_support = bool(
            category == decision.category
            and aggregate_score >= int(predicate["minimum_score"])
            and not irrelevant_reference_ids
        )

    if isinstance(predicate, dict) and predicate.get("kind") == "committed_effect_multiplicity":
        typed_predicate_valid = (set(predicate) == {"kind", "count"}
                                 and type(predicate.get("count")) is int and 2 <= predicate["count"] <= 8)
        findings = {item.id: inspect_multiplicity(item.observation.get("transaction_observation"))
                    for item in valid_rows if item.kind == "transaction_observation"}
        irrelevant_reference_ids = [identifier for identifier in validated_ids
                                    if identifier not in findings or findings[identifier].status != "duplicate"
                                    or findings[identifier].count != predicate.get("count")]
        semantic_support = bool(typed_predicate_valid and decision.category == Category.product_defect
                                and validated_ids and not irrelevant_reference_ids
                                and claim.get("text") == (
                                    f"Reported request and database measurements reconcile {predicate.get('count')} committed effects "
                                    "for one retried logical request; this supports a product-defect investigation "
                                    "without establishing the responsible component."
                                ))

    if isinstance(predicate, dict) and predicate.get("kind") == "contract_violation":
        kind = predicate.get("contract")
        typed_predicate_valid = set(predicate) == {"kind", "contract"} and isinstance(kind, str) and kind in CLAIM_TEXT
        findings = {item.id: inspect_contract(item.observation.get("contract_observation"))
                    for item in valid_rows if item.kind == "contract_observation"}
        irrelevant_reference_ids = [identifier for identifier in validated_ids
                                    if identifier not in findings or findings[identifier].status != "violated"
                                    or findings[identifier].contract != kind]
        semantic_support = bool(typed_predicate_valid and decision.category.value == CONTRACT_CATEGORY.get(kind)
                                and validated_ids and not irrelevant_reference_ids
                                and claim.get("kind") == "inference"
                                and claim.get("text") == CLAIM_TEXT.get(kind))

    if isinstance(predicate, dict) and predicate.get("kind") == "reported_domain_invariant":
        findings = {item.id: inspect_domain(item.observation.get("domain_observation"))
                    for item in valid_rows if item.kind == "domain_observation"}
        typed_predicate_valid = bool(findings and all(
            f.status == "violation" and f.predicate == predicate
            and all(type(predicate[key]) is type(value) for key, value in f.predicate.items())
            for f in findings.values()))
        irrelevant_reference_ids = [identifier for identifier in validated_ids if identifier not in findings]
        semantic_support = bool(typed_predicate_valid and validated_ids and not irrelevant_reference_ids
                                and decision.category == Category.product_defect and claim.get("kind") == "inference"
                                and all(claim.get("text") == f.claim for f in findings.values()))

    text = str(claim.get("text", ""))
    policy_safe = bool(
        text
        and not any(phrase in text.casefold() for phrase in _FORBIDDEN_CLAIM_PHRASES)
    )
    verified = all(
        (
            reference_valid,
            quotation_valid,
            typed_predicate_valid,
            semantic_support,
            policy_safe,
        )
    )
    reasons: list[str] = []
    if not reference_valid:
        reasons.append("unresolved_or_unauthorized_evidence_reference")
    if not quotation_valid:
        reasons.append("quotation_not_found_in_safe_derivative")
    if not typed_predicate_valid:
        reasons.append("unsupported_typed_predicate")
    if not semantic_support:
        reasons.append("citation_does_not_semantically_support_claim")
    if not policy_safe:
        reasons.append("claim_violates_publication_policy")

    validated_claim = {
        **claim,
        "evidence_ids": list(validated_ids),
        "validation_status": "verified" if verified else "rejected",
        "validation": {
            "reference_valid": reference_valid,
            "quotation_valid": quotation_valid,
            "typed_predicate_valid": typed_predicate_valid,
            "semantic_support": semantic_support,
            "semantic_score": aggregate_score,
            "irrelevant_evidence_ids": irrelevant_reference_ids,
            "policy_safe": policy_safe,
            "reasons": reasons,
        },
    }
    return validated_claim, verified


@instrument("validation")
def validate_decision(
    *,
    failure: Failure,
    decision: DeterministicDecision,
    evidence_rows: list[Evidence],
    evidence_validation: EvidenceValidationSet,
    historical: dict[str, Any],
) -> ValidatedDecision:
    accepted_ids = set(evidence_validation.accepted_ids)
    verified_claims: list[dict[str, Any]] = []
    rejected_claims: list[dict[str, Any]] = []
    claim_checks: list[dict[str, Any]] = []

    for claim in decision.claims:
        validated_claim, verified = _claim_validation(
            claim=dict(claim),
            decision=decision,
            failure=failure,
            evidence_rows=evidence_rows,
            evidence_validation=evidence_validation,
            historical=historical,
        )
        claim_checks.append(
            {
                "claim_id": validated_claim.get("id"),
                "status": validated_claim["validation_status"],
                **validated_claim["validation"],
            }
        )
        if verified:
            verified_claims.append(validated_claim)
        else:
            rejected_claims.append(validated_claim)

    supporting = tuple(
        evidence_id
        for evidence_id in decision.supporting_ids
        if evidence_id in accepted_ids
    )
    contradictory = tuple(
        evidence_id
        for evidence_id in decision.contradictory_ids
        if evidence_id in accepted_ids
    )

    hypotheses = [dict(item) for item in decision.hypotheses]
    for item in hypotheses:
        item["evidence_ids"] = list(
            _validated_reference_ids(item.get("evidence_ids"), accepted_ids)
        )
        item["counterevidence_ids"] = list(
            _validated_reference_ids(item.get("counterevidence_ids"), accepted_ids)
        )
    hypotheses.extend(
        {
            "description": claim.get("text", "Rejected unsupported claim"),
            "evidence_ids": claim.get("evidence_ids", []),
            "counterevidence_ids": [],
            "status": "unverified",
            "validation_reasons": claim["validation"]["reasons"],
        }
        for claim in rejected_claims
    )

    next_steps = [dict(item) for item in decision.next_steps]
    for item in next_steps:
        item["evidence_ids"] = list(
            _validated_reference_ids(item.get("evidence_ids"), accepted_ids)
        )

    missing = set(decision.missing)
    flags = set(decision.policy_flags)
    evidence_failed = bool(evidence_rows) and bool(evidence_validation.rejected_ids)
    no_valid_evidence = not evidence_validation.accepted_ids
    claim_failed = bool(rejected_claims)
    must_degrade = bool(
        decision.category is not Category.insufficient_evidence
        and (no_valid_evidence or not verified_claims)
    )

    if no_valid_evidence:
        missing.add("validated execution-scoped evidence")
        if evidence_rows:
            flags.add("evidence_validation_failed")
    if evidence_failed:
        flags.add("evidence_integrity_warning")
    if claim_failed:
        flags.add("unsupported_claim_withheld")
    if must_degrade:
        flags.update({"evidence_validation_failed", "safe_abstention"})

    if must_degrade:
        category = Category.insufficient_evidence
        score = None
        score_kind = "unavailable"
        explanation = (
            "The deterministic result was withheld because its evidence or typed "
            "claim did not pass the publication validation boundary."
        )
        summary = (
            "Failure requires human investigation because publication-grade "
            "evidence validation did not support the proposed classification."
        )
        abstention_reason = explanation
        verified_claims = []
    else:
        category = decision.category
        score = decision.score
        score_kind = decision.score_kind
        explanation = decision.explanation
        summary = decision.summary
        abstention_reason = decision.abstention_reason

    validation_status = (
        "degraded"
        if must_degrade or evidence_failed or claim_failed
        else "passed"
    )
    diagnostic_findings = []
    for row in evidence_rows:
        if row.id in accepted_ids and row.kind == "contract_observation":
            finding = inspect_contract(row.observation.get("contract_observation"))
            diagnostic_findings.append({"evidence_id": row.id, "contract": finding.contract,
                                        "status": finding.status, "reason": finding.reason})
    gap = None
    if category is Category.insufficient_evidence:
        statuses = {f["status"] for f in diagnostic_findings}
        if must_degrade or claim_failed:
            gap = "publication_rejection"
        elif no_valid_evidence or "incomplete" in statuses or "invalid" in statuses:
            gap = "missing_or_invalid_observations"
        elif "conflicting" in statuses or set(flags) & {"multiple_supported_diagnostic_categories", "dangerous_downgrade_blocked", "contract_measurements_incomplete_or_conflicting"}:
            gap = "contradictory_observations"
        else:
            gap = "unresolved_evidence_or_capability"
    validation_results = {
        "version": VALIDATION_VERSION,
        "status": validation_status,
        **evidence_validation.as_dict(),
        "claims": claim_checks,
        "original_category": decision.category.value,
        "published_category": category.value,
        "diagnostic_gap": gap,
        "diagnostic_findings": diagnostic_findings,
    }

    return ValidatedDecision(
        category=category,
        severity=decision.severity,
        score=score,
        score_kind=score_kind,
        explanation=explanation,
        summary=summary,
        supporting_ids=supporting,
        contradictory_ids=contradictory,
        missing=tuple(sorted(missing)),
        claims=tuple(verified_claims),
        hypotheses=tuple(hypotheses),
        next_steps=tuple(next_steps),
        abstention_reason=abstention_reason,
        policy_flags=tuple(sorted(flags)),
        validation_results=validation_results,
    )
