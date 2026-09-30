"""Bounded reported domain observations; never benchmark labels or causal proof.

These checks establish narrowly worded relationships under an explicitly declared
contract. They do not certify that a producer is truthful or identify a responsible
service. Missing, inconsistent and ambiguous observations must remain unresolved.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, NotRequired, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Version = Annotated[int, Field(ge=0, le=2**53 - 1)]
Name = Annotated[
    str, Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:/-]+$")
]


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["domain-observations-v1"]
    test_identity: Annotated[str, Field(min_length=1, max_length=240)]
    attempt: Annotated[int, Field(ge=0, le=20)]
    browser: Annotated[str, Field(max_length=80)] | None


class OperationIdentity(Observation):
    kind: Literal["operation_identity"]
    contract: Literal["operation-is-part-of-request-identity-v1"]
    scope_digest: Digest
    payload_digest: Digest
    first_operation: Name
    second_operation: Name
    first_fingerprint: Digest | None
    second_fingerprint: Digest | None


class ProjectionOrder(Observation):
    kind: Literal["projection_order"]
    contract: Literal["ignore-older-entity-events-v1"]
    entity_digest: Digest
    before_version: Version | None
    event_version: Version | None
    after_version: Version | None
    before_state_digest: Digest | None
    event_state_digest: Digest | None
    after_state_digest: Digest | None


class WeeklyRecurrence(Observation):
    kind: Literal["weekly_recurrence"]
    contract: Literal["weekly-same-local-wall-time-v1"]
    timezone: Annotated[str, Field(min_length=1, max_length=80)]
    previous_occurrence: Annotated[str, Field(max_length=80)] | None
    next_occurrence: Annotated[str, Field(max_length=80)] | None


DomainObservation = Annotated[
    OperationIdentity | ProjectionOrder | WeeklyRecurrence, Field(discriminator="kind")
]
ADAPTER: TypeAdapter[OperationIdentity | ProjectionOrder | WeeklyRecurrence] = (
    TypeAdapter(DomainObservation)
)

DomainStatus = Literal[
    "violation", "consistent", "incomplete", "conflicting", "invalid"
]


class DomainPredicate(TypedDict):
    kind: Literal["reported_domain_invariant"]
    invariant: str
    before_version: NotRequired[int]
    event_version: NotRequired[int]
    local_days: NotRequired[int]


@dataclass(frozen=True)
class DomainFinding:
    status: DomainStatus
    kind: str
    predicate: DomainPredicate | None
    claim: str | None
    reason: str


def _finding(
    status: DomainStatus,
    kind: str,
    reason: str,
    *,
    before_version: int | None = None,
    event_version: int | None = None,
    local_days: int | None = None,
) -> DomainFinding:
    if status != "violation":
        return DomainFinding(status, kind, None, None, reason)
    predicate: DomainPredicate = {
        "kind": "reported_domain_invariant",
        "invariant": kind,
    }
    if before_version is not None:
        predicate["before_version"] = before_version
    if event_version is not None:
        predicate["event_version"] = event_version
    if local_days is not None:
        predicate["local_days"] = local_days
    claims = {
        "operation_identity": (
            "Reported fingerprints coincide for distinct operations with the same declared scope and payload, "
            "contrary to the declared operation-identity contract. This supports product investigation, "
            "not attribution to a responsible component."
        ),
        "projection_order": (
            "Reported projection version and state were replaced by an older event, contrary to the declared "
            "ordering contract. This supports product investigation, not attribution to a responsible component."
        ),
        "weekly_recurrence": (
            f"Reported weekly occurrences are {local_days} local calendar days apart instead of "
            "seven under the declared same-wall-time contract. This supports product investigation, "
            "not attribution to a responsible component."
        ),
    }
    return DomainFinding("violation", kind, predicate, claims[kind], reason)


def _local(value: str, zone: ZoneInfo) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Occurrence must carry an explicit UTC offset")
    local = parsed.astimezone(zone)
    if (
        local.replace(tzinfo=None) != parsed.replace(tzinfo=None)
        or local.utcoffset() != parsed.utcoffset()
    ):
        raise ValueError(
            "Occurrence wall time/offset disagrees with its declared timezone"
        )
    return local


def inspect_domain(value: object) -> DomainFinding:
    try:
        observation = ADAPTER.validate_python(value)
    except (ValidationError, ValueError):
        return _finding("invalid", "unknown", "Domain observation schema is invalid.")
    kind = observation.kind
    if isinstance(observation, OperationIdentity):
        if (
            observation.first_fingerprint is None
            or observation.second_fingerprint is None
        ):
            return _finding(
                "incomplete", kind, "Both reported fingerprints are required."
            )
        distinct = observation.first_operation != observation.second_operation
        identical = observation.first_fingerprint == observation.second_fingerprint
        if distinct and identical:
            return _finding(
                "violation",
                kind,
                "Distinct operation identities collide under the declared contract.",
            )
        if not distinct and not identical:
            return _finding(
                "conflicting",
                kind,
                "Identical declared operations and payloads have different fingerprints.",
            )
        return _finding(
            "consistent", kind, "No operation-identity violation is established."
        )
    if isinstance(observation, ProjectionOrder):
        if (
            observation.before_version is None
            or observation.event_version is None
            or observation.after_version is None
            or observation.before_state_digest is None
            or observation.event_state_digest is None
            or observation.after_state_digest is None
        ):
            return _finding(
                "incomplete",
                kind,
                "Before/event/after versions and state digests are required.",
            )
        older = observation.event_version < observation.before_version
        unchanged = (
            observation.after_version == observation.before_version
            and observation.after_state_digest == observation.before_state_digest
        )
        applied = (
            observation.after_version == observation.event_version
            and observation.after_state_digest == observation.event_state_digest
        )
        if older and applied and not unchanged:
            return _finding(
                "violation",
                kind,
                "An older event replaces the recorded newer projection.",
                before_version=observation.before_version,
                event_version=observation.event_version,
            )
        if older and unchanged:
            return _finding(
                "consistent",
                kind,
                "The older event left the newer projection unchanged.",
            )
        if not older and (unchanged or applied):
            return _finding(
                "consistent", kind, "No older-event replacement is established."
            )
        return _finding(
            "conflicting",
            kind,
            "Recorded versions and state digests do not describe one coherent update.",
        )
    if observation.previous_occurrence is None or observation.next_occurrence is None:
        return _finding("incomplete", kind, "Both occurrences are required.")
    try:
        zone = ZoneInfo(observation.timezone)
        previous = _local(observation.previous_occurrence, zone)
        following = _local(observation.next_occurrence, zone)
        expected_wall = previous.replace(tzinfo=None) + timedelta(days=7)
        # An undefined/ambiguous local target needs a DST resolution contract.
        choices = [expected_wall.replace(tzinfo=zone, fold=f) for f in (0, 1)]
        if (
            choices[0].utcoffset() != choices[1].utcoffset()
            or choices[0].astimezone(UTC).astimezone(zone).replace(tzinfo=None)
            != expected_wall
        ):
            return _finding(
                "incomplete",
                kind,
                "The weekly target requires an explicit DST ambiguity/gap policy.",
            )
    except (ValueError, OverflowError, ZoneInfoNotFoundError):
        return _finding(
            "invalid", kind, "Timezone or occurrence is invalid or incompatible."
        )
    if following <= previous:
        return _finding(
            "conflicting",
            kind,
            "The next occurrence does not follow the previous occurrence.",
        )
    if previous.replace(tzinfo=None).time() != following.replace(tzinfo=None).time():
        return _finding(
            "conflicting",
            kind,
            "The observations change wall time; calendar spacing alone is insufficient.",
        )
    days = (following.date() - previous.date()).days
    if days != 7:
        return _finding(
            "violation",
            kind,
            "The declared weekly local-calendar interval is violated.",
            local_days=days,
        )
    return _finding(
        "consistent",
        kind,
        "The occurrences satisfy the declared weekly local-calendar interval.",
    )


def domain_findings(evidence) -> list[tuple[str, DomainFinding]]:
    return [
        (item.id, inspect_domain(item.observation.get("domain_observation")))
        for item in evidence
        if item.kind == "domain_observation"
    ]


def parse_domain_observation(content: bytes) -> dict:
    if len(content) > 16 * 1024:
        raise ValueError("Domain observation exceeds 16 KiB")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON member")
            result[key] = value
        return result

    value = json.loads(content, object_pairs_hook=unique)
    return ADAPTER.validate_python(value).model_dump()


def register_domain_inputs(session, project, run, source_artifact, settings) -> None:
    """Bind each diagnostic to one exact test/input; remove ungoverned metadata copies."""
    from sqlalchemy import select

    from . import models as m
    from .redaction import REDACTION_VERSION
    from .service import _get_or_create_text_derivative, _sanitize_evidence_value

    items = list(
        session.scalars(
            select(m.RunInput).where(
                m.RunInput.run_id == run.id,
                m.RunInput.kind == "domain-observations-json",
            )
        )
    )
    executions = list(
        session.scalars(select(m.TestExecution).where(m.TestExecution.run_id == run.id))
    )
    for item in items:
        if item.status != "accepted" or item.parser_version != "domain-observations-v1":
            continue
        value = item.metadata_json.get("domain_observation")
        observation = ADAPTER.validate_python(value)
        candidates = [
            execution
            for execution in executions
            if execution.test_identity == observation.test_identity
            and execution.attempt == observation.attempt
            and execution.browser == observation.browser
            and item.metadata_json.get("correlates_to", [])
            == [execution.details.get("input_id")]
        ]
        item.metadata_json = {
            k: v for k, v in item.metadata_json.items() if k != "domain_observation"
        }
        if len(candidates) != 1:
            item.warnings = [*item.warnings, "domain_correlation_ambiguous_or_missing"]
            continue
        safe, classes = _sanitize_evidence_value(
            value, max_text=settings.analysis_text_budget
        )
        excerpt = json.dumps(safe, sort_keys=True, separators=(",", ":"))
        if len(excerpt) > settings.analysis_text_budget:
            item.warnings = [*item.warnings, "domain_evidence_exceeds_budget"]
            continue
        source = {
            "kind": "json-pointer",
            "pointer": "",
            "input_id": item.input_id,
            "path": item.path,
            "sha256": item.digest,
        }
        typed = {"domain_observation": safe}
        derivative = _get_or_create_text_derivative(
            session,
            project=project,
            run=run,
            artifact=source_artifact,
            source_locator=source,
            excerpt=excerpt,
            observation=typed,
            redaction_classes=classes,
            settings=settings,
        )
        session.add(
            m.Evidence(
                project_id=project.id,
                run_id=run.id,
                artifact_id=source_artifact.id,
                run_input_id=item.id,
                execution_id=candidates[0].id,
                derivative_id=derivative.id,
                kind="domain_observation",
                provenance_kind="current_execution",
                locator_version="evidence-locator-v2",
                locator={
                    "version": "evidence-locator-v2",
                    "source": source,
                    "derivative": {"kind": "json-pointer", "pointer": "/excerpt"},
                },
                excerpt=excerpt,
                observation=typed,
                content_digest=derivative.digest,
                parser_version=item.parser_version,
                extractor_version="domain-binding-v1",
                redaction_version=REDACTION_VERSION,
                warnings=["producer_reported_contract_not_causal_proof"],
            )
        )
    session.flush()
