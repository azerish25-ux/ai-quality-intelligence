"""Recompute bounded contracts from producer-reported, execution-bound measurements.

These records are observations, not trusted verdicts. A violation supports an
investigation; it neither identifies the faulty implementation nor clears a run.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Version = Annotated[int, Field(ge=0, le=10**15)]
LocalTime = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$", max_length=19)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Fingerprint(Record):
    operation: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.:-]{0,79}$")]
    actor_digest: Digest
    payload_digest: Digest
    fingerprint: Digest | None


class OperationIsolation(Record):
    kind: Literal["operation_isolation"]
    fingerprint_scope: Literal["operation_actor_payload"]
    first: Fingerprint
    second: Fingerprint


class Projection(Record):
    entity_digest: Digest
    version: Version
    state_digest: Digest


class ProjectionOrdering(Record):
    kind: Literal["projection_ordering"]
    stale_event_policy: Literal["ignore"]
    before: Projection | None
    incoming: Projection
    after: Projection | None


class WeeklyRecurrence(Record):
    kind: Literal["weekly_recurrence"]
    timezone: Annotated[str, Field(min_length=1, max_length=80)]
    wall_time_policy: Literal["preserve"]
    previous_local: LocalTime
    next_local: LocalTime | None


MinorUnits = Annotated[int, Field(ge=-(2**53 - 1), le=2**53 - 1)]
StatusCode = Annotated[int, Field(ge=100, le=599)]
ByteCount = Annotated[int, Field(ge=0, le=2**53 - 1)]


class AtomicTransfer(Record):
    kind: Literal["atomic_transfer"]
    atomicity_policy: Literal["both_effects_or_neither"]
    observation_scope: Literal["isolated_logical_request"]
    request_digest: Digest
    receipt_request_digest: Digest
    source_account_digest: Digest
    destination_account_digest: Digest
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    amount_minor: Annotated[int, Field(gt=0, le=10**12)]
    receipt_outcome: Literal["committed", "rolled_back", "unresolved"]
    concurrent_writers: Annotated[int, Field(ge=0, le=1000000)]
    before_source_minor: MinorUnits | None
    before_destination_minor: MinorUnits | None
    after_source_minor: MinorUnits | None
    after_destination_minor: MinorUnits | None


class TenantIsolation(Record):
    kind: Literal["tenant_isolation"]
    access_policy: Literal["same_tenant_resource_access"]
    principal_scope: Literal["tenant_member"]
    actor_tenant_digest: Digest
    resource_tenant_digest: Digest
    requested_resource_digest: Digest
    returned_resource_digest: Digest | None
    response_status: StatusCode | None


class StatusExpectation(Record):
    kind: Literal["status_expectation"]
    assertion_scope: Literal["response_status_equality"]
    contract_source: Literal["versioned_api_contract"]
    contract_digest: Digest
    served_contract_digest: Digest
    allowed_statuses: Annotated[list[StatusCode], Field(min_length=1, max_length=8)]
    observed_status: StatusCode | None
    asserted_status: StatusCode | None


class RunnerMemoryLimit(Record):
    kind: Literal["runner_memory_limit"]
    process_role: Literal["test_runner"]
    counter_scope: Literal["isolated_runner_cgroup"]
    runner_process_digest: Digest
    killed_process_digest: Digest | None
    memory_limit_bytes: Annotated[int, Field(gt=0, le=2**53 - 1)]
    peak_memory_bytes: ByteCount | None
    oom_kills_before: Annotated[int, Field(ge=0, le=1000000)] | None
    oom_kills_after: Annotated[int, Field(ge=0, le=1000000)] | None
    termination_signal: Annotated[int, Field(ge=1, le=64)] | None


class ContractObservation(Record):
    schema_version: Literal["contract-observations-v1"]
    test_identity: Annotated[str, Field(min_length=1, max_length=240)]
    attempt: Annotated[int, Field(ge=0, le=20)]
    browser: Annotated[str, Field(max_length=80)] | None
    measurement: Annotated[OperationIsolation | ProjectionOrdering | WeeklyRecurrence | AtomicTransfer
        | TenantIsolation | StatusExpectation | RunnerMemoryLimit, Field(discriminator="kind")]


@dataclass(frozen=True)
class ContractFinding:
    contract: str | None
    status: str
    reason: str


CLAIM_TEXT = {
    "operation_isolation": "Reported identical actor and payload inputs have different operations but equal fingerprints; this violates the declared operation-isolation contract without establishing the responsible implementation.",
    "projection_ordering": "Reported projection snapshots show a lower-version event replacing newer state despite an ignore-stale policy; this supports a product-defect investigation without establishing the responsible implementation.",
    "weekly_recurrence": "Reported local schedule dates do not preserve a seven-calendar-day weekly recurrence in the declared timezone; this supports a product-defect investigation without establishing the responsible implementation.",
}


# Category and wording are bounded by the observed relation, never supplied as a
# producer verdict. Existing v1 variants remain byte-compatible.
CLAIM_TEXT.update({
    "atomic_transfer": "Reported isolated two-account snapshots do not match the declared all-or-nothing transfer outcome; this supports a product-defect investigation without establishing the responsible component.",
    "tenant_isolation": "Reported resource content belongs to a different tenant from the authenticated member despite a same-tenant access policy; this supports an access-isolation investigation without establishing the responsible component.",
    "status_expectation": "Reported failing status assertion expects a status excluded by the matching versioned API contract, while the observed response status is permitted; this supports a test-expectation investigation and does not establish that other product behavior is correct.",
    "runner_memory_limit": "Reported runner-scoped memory measurements and an increased OOM-kill counter corroborate termination of the same test-runner process; this supports an infrastructure-interruption investigation without establishing the trigger or clearing product behavior.",
})
CONTRACT_CATEGORY = {kind: "product_defect" for kind in CLAIM_TEXT} | {
    "status_expectation": "test_defect", "runner_memory_limit": "infrastructure_failure",
}
CONTRACT_SEVERITY = {kind: "high" for kind in CLAIM_TEXT} | {
    "operation_isolation": "critical", "atomic_transfer": "critical", "tenant_isolation": "critical",
    "status_expectation": "medium", "runner_memory_limit": "medium",
}


def _inspect_diagnostic(item: AtomicTransfer | TenantIsolation | StatusExpectation | RunnerMemoryLimit) -> ContractFinding:
    kind = item.kind
    if isinstance(item, AtomicTransfer):
        if (item.request_digest != item.receipt_request_digest
                or item.source_account_digest == item.destination_account_digest
                or item.concurrent_writers != 0):
            return ContractFinding(kind, "conflicting", "One request, two distinct accounts, and isolated snapshots are required.")
        values = (item.before_source_minor, item.before_destination_minor,
                  item.after_source_minor, item.after_destination_minor)
        if item.receipt_outcome == "unresolved" or any(v is None for v in values):
            return ContractFinding(kind, "incomplete", "A resolved receipt and both before/after account balances are required.")
        expected = (item.before_source_minor, item.before_destination_minor)
        if item.receipt_outcome == "committed":
            expected = (expected[0] - item.amount_minor, expected[1] + item.amount_minor)
        violated = (item.after_source_minor, item.after_destination_minor) != expected
    elif isinstance(item, TenantIsolation):
        if item.response_status is None:
            return ContractFinding(kind, "incomplete", "The observed response status and attributable resource content are required.")
        if item.returned_resource_digest is None:
            if item.response_status not in {403, 404}:
                return ContractFinding(kind, "incomplete", "A successful status alone does not establish cross-tenant content disclosure.")
            violated = False
        elif item.returned_resource_digest != item.requested_resource_digest:
            return ContractFinding(kind, "conflicting", "The response does not bind to the requested resource.")
        else:
            # An error status must not hide a body that nevertheless leaks data.
            violated = item.actor_tenant_digest != item.resource_tenant_digest
    elif isinstance(item, StatusExpectation):
        if (item.contract_digest != item.served_contract_digest
                or len(set(item.allowed_statuses)) != len(item.allowed_statuses)):
            return ContractFinding(kind, "conflicting", "One matching deployed contract and distinct permitted statuses are required.")
        if item.observed_status is None or item.asserted_status is None:
            return ContractFinding(kind, "incomplete", "The actual response and failed assertion status are required.")
        if item.observed_status not in item.allowed_statuses:
            return ContractFinding(kind, "conflicting", "The response itself conflicts with the API contract; test blame is unsupported.")
        if item.asserted_status != item.observed_status and item.asserted_status in item.allowed_statuses:
            return ContractFinding(kind, "incomplete", "Both statuses are permitted; operation-specific evidence is needed.")
        violated = item.asserted_status not in item.allowed_statuses
    else:
        if any(v is None for v in (item.killed_process_digest, item.peak_memory_bytes,
                                   item.oom_kills_before, item.oom_kills_after, item.termination_signal)):
            return ContractFinding(kind, "incomplete", "Runner identity, peak memory, before/after OOM counters and termination signal are required.")
        if item.runner_process_digest != item.killed_process_digest or item.oom_kills_after < item.oom_kills_before:
            return ContractFinding(kind, "conflicting", "Runner identity or monotonic OOM-counter scope is inconsistent.")
        increased = item.oom_kills_after > item.oom_kills_before
        violated = increased and item.termination_signal == 9 and item.peak_memory_bytes >= item.memory_limit_bytes
        if increased and not violated:
            return ContractFinding(kind, "conflicting", "The OOM increment is not corroborated by this process's peak and termination signal.")
        if not increased and item.termination_signal == 9:
            return ContractFinding(kind, "incomplete", "SIGKILL without a scoped OOM increment does not establish memory exhaustion.")
    return ContractFinding(kind, "violated" if violated else "conforms",
                           "Reported measurements establish the bounded diagnostic relationship." if violated else
                           "This narrow relationship conforms; the failure cause remains unresolved.")


def _unambiguous_local(value: datetime, zone: ZoneInfo) -> bool:
    offsets = set()
    for fold in (0, 1):
        aware = value.replace(tzinfo=zone, fold=fold)
        try:
            if datetime.fromtimestamp(aware.timestamp(), zone).replace(tzinfo=None) == value:
                offsets.add(aware.utcoffset())
        except (ValueError, OverflowError, OSError):
            return False
    return len(offsets) == 1


def inspect_contract(value: object) -> ContractFinding:
    try:
        item = ContractObservation.model_validate(value).measurement
    except (ValidationError, ValueError, TypeError):
        return ContractFinding(None, "invalid", "Invalid bounded contract observation.")
    kind = item.kind
    if isinstance(item, (AtomicTransfer, TenantIsolation, StatusExpectation, RunnerMemoryLimit)):
        return _inspect_diagnostic(item)
    if isinstance(item, OperationIsolation):
        a, b = item.first, item.second
        if a.fingerprint is None or b.fingerprint is None:
            return ContractFinding(kind, "incomplete", "Both measured fingerprints are required.")
        if a.operation == b.operation or a.actor_digest != b.actor_digest or a.payload_digest != b.payload_digest:
            return ContractFinding(kind, "conflicting", "The pair does not isolate the operation input.")
        violated = a.fingerprint == b.fingerprint
    elif isinstance(item, ProjectionOrdering):
        a, b, c = item.before, item.incoming, item.after
        if a is None or c is None:
            return ContractFinding(kind, "incomplete", "Before and after projection snapshots are required.")
        if len({a.entity_digest, b.entity_digest, c.entity_digest}) != 1 or b.version >= a.version:
            return ContractFinding(kind, "conflicting", "The snapshots do not isolate a stale event for one entity.")
        if c != a and c != b:
            return ContractFinding(kind, "conflicting", "The resulting state is neither the prior nor incoming snapshot.")
        violated = c == b
    else:
        if item.next_local is None:
            return ContractFinding(kind, "incomplete", "The observed next occurrence is missing.")
        try:
            zone = ZoneInfo(item.timezone)
            previous = datetime.fromisoformat(item.previous_local)
            actual = datetime.fromisoformat(item.next_local)
            expected = previous + timedelta(days=7)
        except (ValueError, OverflowError, ZoneInfoNotFoundError):
            return ContractFinding(kind, "invalid", "Unknown timezone or invalid local calendar date.")
        if not all(_unambiguous_local(v, zone) for v in (previous, actual, expected)):
            return ContractFinding(kind, "incomplete", "Ambiguous or nonexistent local times require an explicit DST policy.")
        violated = actual != expected
    return ContractFinding(kind, "violated" if violated else "conforms",
                           "Reported observations violate the declared contract." if violated else
                           "This narrow contract conforms; it does not establish the cause of the failure.")


def contract_findings(evidence) -> list[tuple[str, ContractFinding]]:
    return [(item.id, inspect_contract(item.observation.get("contract_observation")))
            for item in evidence if item.kind == "contract_observation"]


def parse_contract_observation(content: bytes) -> dict:
    if len(content) > 16 * 1024:
        raise ValueError("Contract observation exceeds 16 KiB")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON member")
            result[key] = value
        return result
    return ContractObservation.model_validate(json.loads(content, object_pairs_hook=unique)).model_dump()


def register_contract_inputs(session, project, run, source_artifact, settings) -> None:
    """Attach a diagnostic to one exact execution, with governed immutable storage."""
    from sqlalchemy import select
    from . import models as m
    from .redaction import REDACTION_VERSION
    from .service import _get_or_create_text_derivative, _sanitize_evidence_value

    inputs = list(session.scalars(select(m.RunInput).where(
        m.RunInput.run_id == run.id, m.RunInput.kind == "contract-observations-json")))
    executions = list(session.scalars(select(m.TestExecution).where(m.TestExecution.run_id == run.id)))
    for item in inputs:
        if item.status != "accepted" or item.parser_version != "contract-observations-v1":
            continue
        value = item.metadata_json.get("contract_observation")
        record = ContractObservation.model_validate(value)
        matches = [e for e in executions if e.test_identity == record.test_identity
                   and e.attempt == record.attempt and e.browser == record.browser
                   and item.metadata_json.get("correlates_to") == [e.details.get("input_id")]]
        # Never retain a second ungoverned copy in public input metadata.
        item.metadata_json = {k: v for k, v in item.metadata_json.items() if k != "contract_observation"}
        if len(matches) != 1:
            item.warnings = [*item.warnings, "contract_correlation_ambiguous_or_missing"]
            continue
        safe, classes = _sanitize_evidence_value(value, max_text=settings.analysis_text_budget)
        excerpt = json.dumps(safe, sort_keys=True, separators=(",", ":"))
        if len(excerpt) > settings.analysis_text_budget:
            item.warnings = [*item.warnings, "contract_evidence_exceeds_budget"]
            continue
        source = {"kind": "json-pointer", "pointer": "", "input_id": item.input_id,
                  "path": item.path, "sha256": item.digest}
        typed = {"contract_observation": safe}
        derivative = _get_or_create_text_derivative(session, project=project, run=run, artifact=source_artifact,
            source_locator=source, excerpt=excerpt, observation=typed, redaction_classes=classes, settings=settings)
        session.add(m.Evidence(project_id=project.id, run_id=run.id, artifact_id=source_artifact.id,
            run_input_id=item.id, execution_id=matches[0].id, derivative_id=derivative.id,
            kind="contract_observation", provenance_kind="current_execution", locator_version="evidence-locator-v2",
            locator={"version": "evidence-locator-v2", "source": source,
                     "derivative": {"kind": "json-pointer", "pointer": "/excerpt"}},
            excerpt=excerpt, observation=typed, content_digest=derivative.digest,
            parser_version=item.parser_version, extractor_version="contract-binding-v1",
            redaction_version=REDACTION_VERSION, warnings=["producer_reported_measurements_not_causal_proof"]))
    session.flush()
