from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from .analysis import DeterministicDecision, EvidenceView, rule_signal_counts
from .config import Settings, get_settings
from .contract_evidence import CLAIM_TEXT, CONTRACT_CATEGORY, inspect_contract
from .domain_evidence import inspect_domain
from .models import (
    ArtifactDerivative,
    Category,
    Evidence,
    Failure,
    Run,
    RunInput,
    TestExecution,
)
from .redaction import REDACTION_VERSION, valid_project_provenance
from .storage import StorageError, read_stored_bytes
from .telemetry import instrument
from .transaction_evidence import inspect_multiplicity

VALIDATION_VERSION = "evidence-validation-v4"
MAX_EVIDENCE_CACHE_ENTRIES = 128
MAX_EVIDENCE_CACHE_BYTES = 4 * 1024 * 1024
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
    """Check the recorded validation envelope, not current evidence availability."""
    validation = getattr(analysis, "validation_results", None) or {}
    category = getattr(getattr(analysis, "category", None), "value", None)
    return bool(
        getattr(analysis, "validation_version", None)
        and validation.get("status") in _VALIDATED_PUBLICATION_STATES
        and validation.get("published_category") == category
    )


class EvidenceReadContext:
    """Reuse immutable-byte reads within one request, never authorization results.

    Callers create a fresh context for each request/transaction. Scope, approval,
    retention, quotation and observation checks still run for every use.
    Successful bytes have independent entry/byte budgets; eviction only causes
    another checked read. Failures and their traceback frames are never retained.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._bytes: OrderedDict[tuple[Any, ...], bytes] = OrderedDict()
        self._cached_bytes = 0

    def read(self, derivative: ArtifactDerivative, settings: Settings) -> bytes:
        key = (
            str(settings.artifact_root),
            settings.analysis_text_budget,
            derivative.project_id,
            derivative.run_id,
            derivative.id,
            derivative.storage_path,
            derivative.digest,
            derivative.size_bytes,
        )
        if key in self._bytes:
            self._bytes.move_to_end(key)
            return self._bytes[key]
        content = read_stored_bytes(
            root=settings.artifact_root,
            relative_path=derivative.storage_path,
            expected_digest=derivative.digest,
            expected_size=derivative.size_bytes,
            max_bytes=settings.analysis_text_budget * 4,
        )
        if len(content) > MAX_EVIDENCE_CACHE_BYTES:
            return content
        while self._bytes and (
            len(self._bytes) >= MAX_EVIDENCE_CACHE_ENTRIES
            or self._cached_bytes + len(content) > MAX_EVIDENCE_CACHE_BYTES
        ):
            _, evicted = self._bytes.popitem(last=False)
            self._cached_bytes -= len(evicted)
        self._bytes[key] = content
        self._cached_bytes += len(content)
        return content


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
    if (
        failure.run.project_id != failure.project_id
        or failure.run.id != failure.run_id
        or failure.execution.id != failure.execution_id
    ):
        return False
    return _scoped_evidence_is_authorized(
        failure.run, evidence, failure.execution, None
    )


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
    read_context: EvidenceReadContext | None = None,
) -> EvidenceValidationSet:
    return _validate_evidence_records(
        evidence_rows,
        authorize=lambda evidence: _scope_is_authorized(failure, evidence),
        scope_error="evidence_outside_failure_scope",
        settings=settings,
        read_context=read_context,
    )


def _execution_input_matches(
    evidence: Evidence, execution: TestExecution, execution_input: str | None
) -> bool:
    if not execution_input:
        return True
    linked_input = evidence.run_input
    if linked_input is None:
        return False
    if linked_input.input_id == execution_input:
        return True
    # Registered numeric diagnostics are distinct manifest inputs explicitly
    # correlated to the report input and one exact execution, not its siblings.
    input_kinds = {
        "contract_observation": "contract-observations-json",
        "domain_observation": "domain-observations-json",
        "transaction_observation": "transaction-observations-json",
    }
    recorded = evidence.observation.get(evidence.kind)
    return bool(
        evidence.kind in input_kinds
        and linked_input.kind == input_kinds[evidence.kind]
        and linked_input.metadata_json.get("correlates_to") == [execution_input]
        and isinstance(recorded, dict)
        and recorded.get("test_identity") == execution.test_identity
        and recorded.get("attempt") == execution.attempt
        and recorded.get("browser") == execution.browser
    )


def _scoped_evidence_is_authorized(
    run: Run,
    evidence: Evidence,
    execution: TestExecution | None,
    run_input: RunInput | None,
) -> bool:
    if (
        run.evidence_expired_at is not None
        or evidence.project_id != run.project_id
        or evidence.run_id != run.id
    ):
        return False
    if execution is not None and (
        execution.run_id != run.id
        or execution.run is None
        or execution.run.project_id != run.project_id
    ):
        return False
    if run_input is not None and (
        run_input.project_id != run.project_id or run_input.run_id != run.id
    ):
        return False
    linked_input = evidence.run_input
    if evidence.run_input_id is not None and (
        linked_input is None
        or linked_input.project_id != run.project_id
        or linked_input.run_id != run.id
    ):
        return False
    execution_input = (
        execution.details.get("input_id")
        if execution is not None and isinstance(execution.details, dict)
        else None
    )
    if (
        run_input is not None
        and execution_input
        and execution_input != run_input.input_id
        and (
            linked_input is None
            or linked_input.id != run_input.id
            or execution is None
            or not _execution_input_matches(evidence, execution, execution_input)
        )
    ):
        return False
    if evidence.execution_id is not None:
        if (
            execution is None
            or evidence.execution_id != execution.id
            or evidence.provenance_kind != "current_execution"
        ):
            return False
        # Legacy executions can lack a manifest input binding. When present,
        # it must match the actual evidence input rather than only its test ID.
        return _execution_input_matches(evidence, execution, execution_input)
    if evidence.provenance_kind == "shared_run_diagnostic":
        return True
    if evidence.provenance_kind == "input_diagnostic":
        expected_input = (
            run_input.input_id if run_input is not None else execution_input
        )
        return bool(
            expected_input
            and linked_input is not None
            and linked_input.input_id == expected_input
            and (run_input is None or linked_input.id == run_input.id)
        )
    return False


def validate_scoped_evidence_records(
    run: Run,
    evidence_rows: list[Evidence],
    *,
    execution: TestExecution | None = None,
    run_input: RunInput | None = None,
    settings: Settings | None = None,
    read_context: EvidenceReadContext | None = None,
) -> EvidenceValidationSet:
    """Validate real execution/run scope without fabricating a failure record.

    The caller must authorize the project. Immutable-byte, locator, quotation,
    observation and approval checks are shared with failure publication.
    """
    return _validate_evidence_records(
        evidence_rows,
        authorize=lambda evidence: _scoped_evidence_is_authorized(
            run, evidence, execution, run_input
        ),
        scope_error="evidence_outside_requested_scope",
        settings=settings,
        read_context=read_context,
    )


def validate_inspectable_evidence_records(
    run: Run,
    evidence_rows: list[Evidence],
    *,
    read_context: EvidenceReadContext | None = None,
) -> EvidenceValidationSet:
    """Verify copied evidence for same-project inspection and human citations.

    Supplemental traces and run metrics remain inspectable without becoming
    execution-scoped classification evidence. Their real relationships must agree.
    """

    def authorize(evidence: Evidence) -> bool:
        if (
            run.evidence_expired_at is not None
            or evidence.project_id != run.project_id
            or evidence.run_id != run.id
            or (
                evidence.execution_id is not None
                and (evidence.execution is None or evidence.execution.run_id != run.id)
            )
            or (
                evidence.run_input_id is not None
                and (
                    evidence.run_input is None
                    or evidence.run_input.project_id != run.project_id
                    or evidence.run_input.run_id != run.id
                )
            )
        ):
            return False
        if evidence.provenance_kind in {"supplemental_trace", "current_run_metric"}:
            return True
        return _scoped_evidence_is_authorized(
            run, evidence, evidence.execution, evidence.run_input
        )

    return _validate_evidence_records(
        evidence_rows,
        authorize=authorize,
        scope_error="evidence_outside_requested_scope",
        settings=None,
        read_context=read_context,
    )


def _validate_evidence_records(
    evidence_rows: list[Evidence],
    *,
    authorize: Callable[[Evidence], bool],
    scope_error: str,
    settings: Settings | None,
    read_context: EvidenceReadContext | None = None,
) -> EvidenceValidationSet:
    settings = settings or (read_context.settings if read_context else get_settings())
    read_context = read_context or EvidenceReadContext(settings)
    checks: list[EvidenceIntegrity] = []

    for evidence in evidence_rows:
        reasons: list[str] = []
        derivative = evidence.derivative
        reference_valid = bool(
            derivative is not None
            and evidence.artifact is not None
            and derivative.project_id == evidence.project_id
            and derivative.run_id == evidence.run_id
            and derivative.artifact_id == evidence.artifact_id
            and evidence.artifact.run_id == evidence.run_id
        )
        if not reference_valid:
            reasons.append("invalid_derivative_reference")

        authorized = authorize(evidence)
        if not authorized:
            reasons.append(scope_error)

        actual_digest: str | None = None
        derivative_payload: dict[str, Any] | None = None
        digest_valid = False
        locator_valid = False
        quotation_valid = False
        observation_valid = False
        policy_safe = False

        if reference_valid and derivative is not None:
            try:
                content = read_context.read(derivative, settings)
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
                if locator_valid and derivative_payload is not None:
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
            if derivative.redaction_version == REDACTION_VERSION:
                # Verification needs immutable bytes and public provenance only.
                # Key retirement must not revoke a valid historical citation.
                recorded = (
                    derivative_payload.get("redaction") if derivative_payload else None
                )
                provenance_valid = valid_project_provenance(
                    recorded, evidence.project_id
                ) and recorded == derivative.metadata_json.get("redaction")
                if not provenance_valid:
                    policy_safe = False
                    reasons.append("redaction_provenance_mismatch")
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


def _validated_reference_ids(values: object, accepted_ids: set[str]) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    return tuple(
        value for value in values if isinstance(value, str) and value in accepted_ids
    )


class ClassificationSignalPredicate(TypedDict):
    kind: Literal["classification_signal"]
    category: Category
    minimum_score: int


def _classification_signal_predicate(
    value: object,
) -> ClassificationSignalPredicate | None:
    if not isinstance(value, dict) or value.get("kind") != "classification_signal":
        return None
    category: object = value.get("category")
    minimum_score: object = value.get("minimum_score")
    if not isinstance(category, str) or type(minimum_score) is not int:
        return None
    if minimum_score < 0:
        return None
    try:
        validated_category = Category(category)
    except ValueError:
        return None
    return {
        "kind": "classification_signal",
        "category": validated_category,
        "minimum_score": minimum_score,
    }


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
    classification_predicate = _classification_signal_predicate(predicate)
    typed_predicate_valid = classification_predicate is not None

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
    if classification_predicate is not None:
        category = classification_predicate["category"]
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
            and aggregate_score >= classification_predicate["minimum_score"]
            and not irrelevant_reference_ids
        )

    if (
        isinstance(predicate, dict)
        and predicate.get("kind") == "committed_effect_multiplicity"
    ):
        typed_predicate_valid = (
            set(predicate) == {"kind", "count"}
            and type(predicate.get("count")) is int
            and 2 <= predicate["count"] <= 8
        )
        multiplicity_findings = {
            item.id: inspect_multiplicity(
                item.observation.get("transaction_observation")
            )
            for item in valid_rows
            if item.kind == "transaction_observation"
        }
        irrelevant_reference_ids = [
            identifier
            for identifier in validated_ids
            if identifier not in multiplicity_findings
            or multiplicity_findings[identifier].status != "duplicate"
            or multiplicity_findings[identifier].count != predicate.get("count")
        ]
        semantic_support = bool(
            typed_predicate_valid
            and decision.category == Category.product_defect
            and validated_ids
            and not irrelevant_reference_ids
            and claim.get("text")
            == (
                f"Reported request and database measurements reconcile {predicate.get('count')} committed effects "
                "for one retried logical request; this supports a product-defect investigation "
                "without establishing the responsible component."
            )
        )

    if isinstance(predicate, dict) and predicate.get("kind") == "contract_violation":
        kind = predicate.get("contract")
        typed_predicate_valid = (
            set(predicate) == {"kind", "contract"}
            and isinstance(kind, str)
            and kind in CLAIM_TEXT
        )
        contract_findings = {
            item.id: inspect_contract(item.observation.get("contract_observation"))
            for item in valid_rows
            if item.kind == "contract_observation"
        }
        irrelevant_reference_ids = [
            identifier
            for identifier in validated_ids
            if identifier not in contract_findings
            or contract_findings[identifier].status != "violated"
            or contract_findings[identifier].contract != kind
        ]
        semantic_support = bool(
            typed_predicate_valid
            and isinstance(kind, str)
            and decision.category.value == CONTRACT_CATEGORY.get(kind)
            and validated_ids
            and not irrelevant_reference_ids
            and claim.get("kind") == "inference"
            and claim.get("text") == CLAIM_TEXT.get(kind)
        )

    if (
        isinstance(predicate, dict)
        and predicate.get("kind") == "reported_domain_invariant"
    ):
        domain_findings = {
            item.id: inspect_domain(item.observation.get("domain_observation"))
            for item in valid_rows
            if item.kind == "domain_observation"
        }
        typed_predicate_valid = bool(
            domain_findings
            and all(
                f.status == "violation"
                and f.predicate is not None
                and f.predicate == predicate
                and all(
                    type(predicate.get(key)) is type(value)
                    for key, value in f.predicate.items()
                )
                for f in domain_findings.values()
            )
        )
        irrelevant_reference_ids = [
            identifier
            for identifier in validated_ids
            if identifier not in domain_findings
        ]
        semantic_support = bool(
            typed_predicate_valid
            and validated_ids
            and not irrelevant_reference_ids
            and decision.category == Category.product_defect
            and claim.get("kind") == "inference"
            and all(claim.get("text") == f.claim for f in domain_findings.values())
        )

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

    abstention_reason: str | None
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
        "degraded" if must_degrade or evidence_failed or claim_failed else "passed"
    )
    diagnostic_findings = []
    for row in evidence_rows:
        if row.id in accepted_ids and row.kind == "contract_observation":
            finding = inspect_contract(row.observation.get("contract_observation"))
            diagnostic_findings.append(
                {
                    "evidence_id": row.id,
                    "contract": finding.contract,
                    "status": finding.status,
                    "reason": finding.reason,
                }
            )
    gap = None
    if category is Category.insufficient_evidence:
        statuses = {f["status"] for f in diagnostic_findings}
        if must_degrade or claim_failed:
            gap = "publication_rejection"
        elif no_valid_evidence or "incomplete" in statuses or "invalid" in statuses:
            gap = "missing_or_invalid_observations"
        elif "conflicting" in statuses or set(flags) & {
            "multiple_supported_diagnostic_categories",
            "dangerous_downgrade_blocked",
            "contract_measurements_incomplete_or_conflicting",
        }:
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
