"""Bounded transaction observations, not benchmark labels or an oracle verdict.

A producer can report measurements, not grant them trust. This module checks the
relations between those measurements and cites them as reported observations.
It does not infer which service introduced a fault or authorize a release.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

Identifier = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Minor = Annotated[int, Field(ge=0, le=10**15)]


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Command(StrictRecord):
    source_id: Identifier
    destination_id: Identifier
    amount_minor: Annotated[int, Field(gt=0, le=10**12)]
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class RequestObservation(StrictRecord):
    sequence: Annotated[int, Field(ge=1, le=8)]
    logical_key_digest: Digest
    intent_digest: Digest
    response_status: Annotated[int, Field(ge=100, le=599)] | None
    receipt_id: Identifier | None


class Balance(StrictRecord):
    account_id: Identifier
    posted_minor: Minor


class Effect(Command):
    id: Identifier
    journal_id: Identifier


class Entry(StrictRecord):
    journal_id: Identifier
    account_id: Identifier
    side: Literal["DEBIT", "CREDIT"]
    amount_minor: Annotated[int, Field(gt=0, le=10**12)]


class Snapshot(StrictRecord):
    balances: Annotated[list[Balance], Field(min_length=2, max_length=2)]
    effects: Annotated[list[Effect], Field(max_length=64)]
    entries: Annotated[list[Entry], Field(max_length=128)]


class TransactionObservation(StrictRecord):
    schema_version: Literal["transaction-observations-v1"]
    test_identity: Annotated[str, Field(min_length=1, max_length=240)]
    attempt: Annotated[int, Field(ge=0, le=20)]
    browser: Annotated[str, Field(max_length=80)] | None
    command: Command
    requests: Annotated[list[RequestObservation], Field(min_length=2, max_length=8)]
    before: Snapshot | None
    after: Snapshot | None


@dataclass(frozen=True)
class Multiplicity:
    status: str
    count: int | None
    reason: str


def inspect_multiplicity(value: object) -> Multiplicity:
    """Recompute effects from exact rows; never accept a producer's count/label."""
    try:
        observation = TransactionObservation.model_validate(value)
    except (ValidationError, ValueError):
        return Multiplicity(
            "invalid", None, "Transaction observation schema is invalid."
        )
    if observation.before is None or observation.after is None:
        return Multiplicity(
            "incomplete", None, "Both before and after database snapshots are required."
        )
    command, requests = observation.command, observation.requests
    if command.source_id == command.destination_id:
        return Multiplicity(
            "conflicting", None, "Source and destination are not distinct."
        )
    if (
        [r.sequence for r in requests] != list(range(1, len(requests) + 1))
        or len({r.logical_key_digest for r in requests}) != 1
        or len({r.intent_digest for r in requests}) != 1
    ):
        return Multiplicity(
            "conflicting", None, "Attempts do not establish one ordered logical intent."
        )
    if requests[0].response_status is not None or requests[0].receipt_id is not None:
        return Multiplicity(
            "conflicting", None, "The first response was not recorded as unavailable."
        )
    if any(r.response_status != 201 or r.receipt_id is None for r in requests[1:]):
        return Multiplicity(
            "incomplete", None, "A retry lacks an authoritative settled receipt."
        )
    snapshots = (observation.before, observation.after)
    maps = []
    for snapshot in snapshots:
        balances = {b.account_id: b.posted_minor for b in snapshot.balances}
        effects = {e.id: e for e in snapshot.effects}
        journals = {e.journal_id for e in snapshot.effects}
        if (
            set(balances) != {command.source_id, command.destination_id}
            or len(effects) != len(snapshot.effects)
            or len(journals) != len(effects)
            or len(snapshot.entries) != 2 * len(effects)
        ):
            return Multiplicity(
                "conflicting",
                None,
                "Snapshot identities or journal cardinality disagree.",
            )
        for effect in effects.values():
            if (
                effect.source_id != command.source_id
                or effect.destination_id != command.destination_id
                or effect.currency != command.currency
            ):
                return Multiplicity(
                    "conflicting",
                    None,
                    "Snapshot includes effects outside the declared account pair.",
                )
            entries = [e for e in snapshot.entries if e.journal_id == effect.journal_id]
            actual = sorted((e.account_id, e.side, e.amount_minor) for e in entries)
            expected = sorted(
                [
                    (effect.source_id, "DEBIT", effect.amount_minor),
                    (effect.destination_id, "CREDIT", effect.amount_minor),
                ]
            )
            if actual != expected:
                return Multiplicity(
                    "conflicting", None, "Transfer and journal rows do not reconcile."
                )
        maps.append((balances, effects))
    (before_balances, before), (after_balances, after) = maps
    if any(after.get(key) != effect for key, effect in before.items()):
        return Multiplicity(
            "conflicting", None, "Previously committed effects disappeared or changed."
        )
    new = [effect for key, effect in after.items() if key not in before]
    if (
        not new
        or len(new) > len(requests)
        or any(e.amount_minor != command.amount_minor for e in new)
    ):
        return Multiplicity(
            "conflicting",
            None,
            "New effects do not match the observed request amount/count.",
        )
    if any(r.receipt_id not in {e.id for e in new} for r in requests[1:]):
        return Multiplicity(
            "conflicting",
            None,
            "The retry receipt does not resolve to a new committed effect.",
        )
    amount = len(new) * command.amount_minor
    if (
        before_balances[command.source_id] - after_balances[command.source_id] != amount
        or after_balances[command.destination_id]
        - before_balances[command.destination_id]
        != amount
    ):
        return Multiplicity(
            "conflicting",
            None,
            "Balance changes disagree with committed transfer rows.",
        )
    return Multiplicity(
        "duplicate" if len(new) > 1 else "single",
        len(new),
        f"Reported snapshots reconcile {len(new)} committed effect(s) for one retried logical request.",
    )


def transaction_findings(evidence) -> list[tuple[str, Multiplicity]]:
    return [
        (item.id, inspect_multiplicity(item.observation.get("transaction_observation")))
        for item in evidence
        if item.kind == "transaction_observation"
    ]


def parse_transaction_observation(content: bytes) -> dict:
    if len(content) > 64 * 1024:
        raise ValueError("Transaction observations exceed 64 KiB")

    # Duplicate JSON keys are not an unambiguous measurement record.
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON member")
            result[key] = value
        return result

    value = json.loads(content, object_pairs_hook=unique)
    return TransactionObservation.model_validate(value).model_dump()


def register_transaction_inputs(
    session, project, run, source_artifact, settings
) -> None:
    """Bind a diagnostic to one exact execution, never every failure in a run."""
    from sqlalchemy import select

    from . import models as m
    from .redaction import REDACTION_VERSION
    from .service import _get_or_create_text_derivative, _sanitize_evidence_value

    items = list(
        session.scalars(
            select(m.RunInput).where(
                m.RunInput.run_id == run.id,
                m.RunInput.kind == "transaction-observations-json",
            )
        )
    )
    executions = list(
        session.scalars(select(m.TestExecution).where(m.TestExecution.run_id == run.id))
    )
    for item in items:
        if (
            item.status != "accepted"
            or item.parser_version != "transaction-observations-v1"
        ):
            continue
        value = item.metadata_json.get("transaction_observation")
        observation = TransactionObservation.model_validate(value)
        targets = item.metadata_json.get("correlates_to", [])
        candidates = [
            execution
            for execution in executions
            if execution.test_identity == observation.test_identity
            and execution.attempt == observation.attempt
            and execution.browser == observation.browser
            and targets == [execution.details.get("input_id")]
        ]
        if len(candidates) != 1:
            item.warnings = [
                *item.warnings,
                "transaction_correlation_ambiguous_or_missing",
            ]
            # Do not expose a duplicate, ungoverned copy through input metadata.
            item.metadata_json = {
                k: v
                for k, v in item.metadata_json.items()
                if k != "transaction_observation"
            }
            continue
        safe, classes = _sanitize_evidence_value(
            value, max_text=settings.analysis_text_budget
        )
        excerpt = json.dumps(safe, sort_keys=True, separators=(",", ":"))
        if len(excerpt) > settings.analysis_text_budget:
            item.warnings = [*item.warnings, "transaction_evidence_exceeds_budget"]
            item.metadata_json = {
                k: v
                for k, v in item.metadata_json.items()
                if k != "transaction_observation"
            }
            continue
        source = {
            "kind": "json-pointer",
            "pointer": "",
            "input_id": item.input_id,
            "path": item.path,
            "sha256": item.digest,
        }
        typed = {"transaction_observation": safe}
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
                kind="transaction_observation",
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
                extractor_version="transaction-binding-v1",
                redaction_version=REDACTION_VERSION,
                warnings=["producer_reported_measurements_not_causal_proof"],
            )
        )
        item.metadata_json = {
            k: v
            for k, v in item.metadata_json.items()
            if k != "transaction_observation"
        }
    session.flush()
