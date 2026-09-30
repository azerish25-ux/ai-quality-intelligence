"""Evaluation-only independent oracle; never imported by runtime inference.

Checks actual request receipts and independent SQL balance/entry observations.
Does not call FailureLens's classifier, its predicates, or a producer verdict.
"""

from __future__ import annotations


def verify_pair_observation(
    value: dict, wire: list[dict], *, expected_effects: int
) -> dict:
    if expected_effects not in (1, 2) or len(wire) != 2 or len(value["requests"]) != 2:
        raise ValueError("Invalid experiment request cardinality")
    if [r["sequence"] for r in wire] != [1, 2] or any(
        r["upstream_status"] != 201 for r in wire
    ):
        raise ValueError("A real upstream transaction did not settle")
    requests = value["requests"]
    if (
        requests[0]["response_status"] is not None
        or requests[0]["receipt_id"] is not None
        or requests[1]["response_status"] != 201
        or requests[1]["receipt_id"] != wire[1]["upstream_receipt_id"]
    ):
        raise ValueError(
            "Client did not observe the declared lost-response/retry sequence"
        )
    if (
        len({r["logical_key_digest"] for r in requests}) != 1
        or len({r["intent_digest"] for r in requests}) != 1
    ):
        raise ValueError("Client did not preserve its logical request")
    if any(
        w["logical_key_digest"] != r["logical_key_digest"]
        or w["intent_digest"] != r["intent_digest"]
        for w, r in zip(wire, requests)
    ):
        raise ValueError("Client and wire observations disagree")
    if len({r["forwarded_key_digest"] for r in wire}) != expected_effects:
        raise ValueError("The key-corruption intervention/control did not execute")
    if wire[1]["idempotency_replayed"] != (
        "true" if expected_effects == 1 else "false"
    ):
        raise ValueError("The API replay receipt contradicts the experiment")
    before, after = value["before"], value["after"]
    command = value["command"]
    previous = {r["id"]: r for r in before["effects"]}
    current = {r["id"]: r for r in after["effects"]}
    if len(previous) != len(before["effects"]) or len(current) != len(after["effects"]):
        raise ValueError("Duplicate SQL effect identifiers")
    if any(current.get(key) != row for key, row in previous.items()):
        raise ValueError("Pre-existing financial effects changed")
    effects = [row for key, row in current.items() if key not in previous]
    if len(effects) != expected_effects or {row["id"] for row in effects} != {
        row["upstream_receipt_id"] for row in wire
    }:
        raise ValueError(
            "Committed SQL effects disagree with independent HTTP receipts"
        )
    debit = credit = 0
    for effect in effects:
        if any(
            effect[field] != command[field]
            for field in ("source_id", "destination_id", "amount_minor", "currency")
        ):
            raise ValueError("Committed intent changed")
        entries = [
            row for row in after["entries"] if row["journal_id"] == effect["journal_id"]
        ]
        source = [
            r
            for r in entries
            if r["side"] == "DEBIT" and r["account_id"] == command["source_id"]
        ]
        destination = [
            r
            for r in entries
            if r["side"] == "CREDIT" and r["account_id"] == command["destination_id"]
        ]
        if len(entries) != 2 or len(source) != 1 or len(destination) != 1:
            raise ValueError("Independent ledger-entry roles disagree")
        if (
            source[0]["amount_minor"] != command["amount_minor"]
            or destination[0]["amount_minor"] != command["amount_minor"]
        ):
            raise ValueError("Independent debit/credit amounts disagree")
        debit += source[0]["amount_minor"]
        credit += destination[0]["amount_minor"]
    balances_before = {r["account_id"]: r["posted_minor"] for r in before["balances"]}
    balances_after = {r["account_id"]: r["posted_minor"] for r in after["balances"]}
    if (
        balances_before[command["source_id"]] - balances_after[command["source_id"]]
        != debit
        or balances_after[command["destination_id"]]
        - balances_before[command["destination_id"]]
        != credit
        or debit != credit
        or debit != expected_effects * command["amount_minor"]
    ):
        raise ValueError("Committed balances, journals and transfer receipts disagree")
    return {
        "committed_effects": len(effects),
        "debit_minor": debit,
        "credit_minor": credit,
        "single_effect_contract_passed": len(effects) == 1,
        "paired_expectation_met": True,
    }
