"""Evaluation-only interventions. This module is never imported by FailureLens inference."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta

@dataclass(frozen=True)
class Intervention:
    mechanism: str
    file: str
    before: str
    after: str
    assertion: str
    severity: str = "high"

INTERVENTIONS = (
    Intervention("wallet-credit-off-by-one", "WalletBalance.java", "Math.addExact(posted, amount)", "Math.addExact(posted, amount - 1)", "Balance invariant: credited posted balance must equal previous posted balance plus credit", "critical"),
    Intervention("available-balance-ignores-reservations", "WalletBalance.java", "return Math.subtractExact(posted, reserved);", "return posted;", "Balance invariant: available balance must exclude reserved funds", "critical"),
    Intervention("settlement-does-not-consume-hold", "WalletBalance.java", "new WalletBalance(Math.subtractExact(posted, amount), Math.subtractExact(reserved, amount))", "new WalletBalance(Math.subtractExact(posted, amount), reserved)", "Balance invariant: consuming a hold must reduce posted and reserved balances together", "critical"),
    Intervention("hold-release-increases-reservation", "WalletBalance.java", "new WalletBalance(posted, Math.subtractExact(reserved, amount))", "new WalletBalance(posted, Math.addExact(reserved, amount))", "Balance invariant: releasing a hold must decrease reserved funds", "critical"),
    Intervention("money-addition-subtracts", "Money.java", "Math.addExact(minor, other.minor)", "Math.subtractExact(minor, other.minor)", "Balance invariant: exact same-currency addition must conserve minor units", "critical"),
    Intervention("decimal-conversion-wrong-scale", "Money.java", "BigInteger.TEN.pow(unit.exponent())", "BigInteger.TEN.pow(Math.max(0, unit.exponent() - 1))", "Balance invariant: decimal-to-minor conversion must preserve the declared currency scale", "critical"),
    Intervention("journal-accepts-unbalanced-entries", "Journal.java", 'debits.equals(credits), "UNBALANCED_JOURNAL"', 'true, "UNBALANCED_JOURNAL"', "Ledger unbalanced: unequal debit and credit totals must be rejected", "critical"),
    Intervention("journal-mixes-currency-units", "Journal.java", 'entry.currency() == currency, "CURRENCY_MISMATCH"', 'true, "CURRENCY_MISMATCH"', "Ledger unbalanced by currency: debit CAD and credit USD must not form a valid journal", "critical"),
    Intervention("idempotency-fingerprint-omits-actor", "Idempotency.java", "field(hash, actor.toString());", 'field(hash, "");', "Cross-account idempotency: otherwise identical intents from distinct actors must have distinct fingerprints", "critical"),
    Intervention("idempotency-fingerprint-omits-operation", "Idempotency.java", "field(hash, operation);", 'field(hash, "");', "Idempotency isolation: payment and refund intents must have distinct fingerprints", "critical"),
    Intervention("refund-forgets-prior-adjustments", "PaymentRules.java", "Math.addExact(refunded, value)", "value", "Balance invariant: cumulative refund must include previous adjustments", "critical"),
    Intervention("reversal-allows-refunded-payment", "PaymentRules.java", 'state == State.SETTLED && refunded == 0 && !reversed, "REVERSAL_FORBIDDEN"', 'state == State.SETTLED && !reversed, "REVERSAL_FORBIDDEN"', "Over-credit prevention: a previously refunded payment must reject a full reversal", "critical"),
    Intervention("weekly-schedule-advances-six-days", "SchedulePolicy.java", "intended.plusWeeks(1)", "intended.plusDays(6)", "Schedule contract: weekly recurrence must advance seven local calendar days"),
    Intervention("webhook-verifier-accepts-forged-signature", "WebhookSignature.java", "return MessageDigest.isEqual(expected, signature.getBytes(StandardCharsets.US_ASCII));", "return true;", "Authorization bypass: a forged webhook signature must not authenticate", "critical"),
    Intervention("projection-replaces-newer-state-with-stale-event", "Projection.java", "if (incoming.version <= version) return this;", "if (incoming.version <= version) return incoming;", "Projection contract: applying an older event must retain the newer version"),
)


def expected_measurement(operation: int, variant: int) -> str:
    """Independent oracle: Python arithmetic/calendar rules, not the mutated Java implementation."""
    if not 0 <= operation < len(INTERVENTIONS) or not 0 <= variant < 4:
        raise ValueError("Unknown operation/variant")
    amount = 7 + variant
    if operation in {0, 4}: return str(100 + amount)
    if operation == 1: return str(100 - (20 + variant))
    if operation == 2: return f"{100 - amount},{40 - amount}"
    if operation == 3: return str(40 - amount)
    if operation == 5: return str((12 + variant) * 100 + 34)
    if operation == 6: return "UNBALANCED_JOURNAL"
    if operation == 7: return "CURRENCY_MISMATCH"
    if operation in {8, 9, 13}: return "false"
    if operation == 10: return str(20 + amount)
    if operation == 11: return "REVERSAL_FORBIDDEN"
    if operation == 12: return (datetime(2026, 1, 5 + variant, 10, 30) + timedelta(days=7)).isoformat(timespec="minutes")
    return "20"
