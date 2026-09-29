"""Independent execution oracle for the isolated early-commit experiment.

Evaluation-only: no runtime schemas, classifier, publication predicates or
producer-generated verdicts are imported. A failed command without inspected
SQL effects is not proof of successful fault injection.
"""
from __future__ import annotations

from collections import Counter
from uuid import UUID


def _integer(value: object, *, minimum: int = -(2**53 - 1)) -> int:
    if type(value) is not int or not minimum <= value <= 2**53 - 1:
        raise ValueError("Expected a bounded integer observation")
    return value


def _uuid(value: object) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Expected a canonical UUID observation")
    return value


def _snapshot(value: dict, source: str, destination: str) -> tuple[dict, dict, Counter]:
    if not isinstance(value, dict) or set(value) != {"balances", "effects", "entries"}:
        raise ValueError("Incomplete SQL snapshot")
    for key in value:
        if not isinstance(value[key], list) or len(value[key]) > 1024:
            raise ValueError("SQL snapshot exceeds the bounded experiment")
    balances = {}
    for row in value["balances"]:
        if not isinstance(row, dict) or set(row) != {"account_id", "posted_minor"}:
            raise ValueError("Invalid balance observation")
        key = _uuid(row["account_id"])
        if key in balances:
            raise ValueError("Duplicate balance observation")
        balances[key] = _integer(row["posted_minor"])
    if set(balances) != {source, destination}:
        raise ValueError("Both distinct accounts must be observed")
    effects = {}
    for row in value["effects"]:
        if not isinstance(row, dict) or set(row) != {"id", "source_id", "destination_id", "amount_minor", "currency", "journal_id"}:
            raise ValueError("Invalid transfer observation")
        key = _uuid(row["id"])
        if key in effects:
            raise ValueError("Duplicate transfer observation")
        _uuid(row["journal_id"])
        if row["source_id"] != source or row["destination_id"] != destination:
            raise ValueError("Unrelated transfer in isolated SQL snapshot")
        _integer(row["amount_minor"], minimum=1)
        effects[key] = row
    entries = Counter()
    for row in value["entries"]:
        if not isinstance(row, dict) or set(row) != {"journal_id", "account_id", "side", "amount_minor"}:
            raise ValueError("Invalid journal observation")
        journal = _uuid(row["journal_id"])
        account = _uuid(row["account_id"])
        if account not in balances or row["side"] not in {"DEBIT", "CREDIT"}:
            raise ValueError("Invalid journal role")
        entries[(journal, account, row["side"], _integer(row["amount_minor"], minimum=1))] += 1
    return balances, effects, entries


def verify_observation(before: dict, after: dict, *, command: dict, response: dict,
                       expected_effects: int) -> dict:
    """Require actual terminal HTTP rejection and exactly zero or one SQL effect.

    Zero is the passing rollback control; one is the deliberately faulty early
    commit. Shared nuisance amounts do not constitute independent families.
    """
    if type(expected_effects) is not int or expected_effects not in (0, 1):
        raise ValueError("Unsupported experiment expectation")
    source, destination = _uuid(command["source_id"]), _uuid(command["destination_id"])
    if source == destination:
        raise ValueError("Distinct accounts are required")
    amount = _integer(command["amount_minor"], minimum=1)
    if amount > 10**12 or command["currency"] != "CAD":
        raise ValueError("Unsupported isolated fixture intent")
    if (type(response.get("status")) is not int or response["status"] != 422
            or response.get("code") != "TRANSFER_REJECTED"):
        raise ValueError("The expected real business rejection was not observed")
    old_balances, old_effects, old_entries = _snapshot(before, source, destination)
    new_balances, new_effects, new_entries = _snapshot(after, source, destination)
    if any(new_effects.get(key) != row for key, row in old_effects.items()):
        raise ValueError("A pre-existing transfer changed or disappeared")
    if any(new_entries[key] != count for key, count in old_entries.items()):
        raise ValueError("A pre-existing journal changed or disappeared")
    added = [row for key, row in new_effects.items() if key not in old_effects]
    if len(added) != expected_effects:
        raise ValueError("The expected financial intervention did not execute")
    expected_entries = Counter()
    for row in added:
        if row["amount_minor"] != amount or row["currency"] != command["currency"]:
            raise ValueError("Observed effect has a different monetary intent")
        if row["journal_id"] in {r["journal_id"] for r in old_effects.values()}:
            raise ValueError("New transfer reuses a historical journal")
        expected_entries[(row["journal_id"], source, "DEBIT", amount)] += 1
        expected_entries[(row["journal_id"], destination, "CREDIT", amount)] += 1
    if new_entries - old_entries != expected_entries:
        raise ValueError("Independent double-entry observations disagree")
    debit = old_balances[source] - new_balances[source]
    credit = new_balances[destination] - old_balances[destination]
    if debit != expected_effects * amount or credit != expected_effects * amount:
        raise ValueError("Independent balance deltas disagree with committed transfers")
    return {"expectation_met": True, "committed_transfers": len(added),
            "debit_minor": debit, "credit_minor": credit,
            "no_effects_after_rejection": expected_effects == 0}
