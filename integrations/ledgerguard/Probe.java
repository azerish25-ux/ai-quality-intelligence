import lab.ledgerguard.core.*;
import java.time.*;
import java.util.*;

/** Measurement only: expected results and fault settings never enter this process. */
public final class Probe {
    private static final UUID A = UUID.fromString("00000000-0000-0000-0000-000000000001");
    private static final UUID B = UUID.fromString("00000000-0000-0000-0000-000000000002");
    public static void main(String[] args) {
        int operation = Integer.parseInt(args[0]);
        int variant = Integer.parseInt(args[1]);
        if (variant < 0 || variant > 3) throw new IllegalArgumentException("variant");
        long amount = 7 + variant;
        String value;
        switch (operation) {
            case 0 -> value = Long.toString(new WalletBalance(100, 20).credit(amount).posted());
            case 1 -> value = Long.toString(new WalletBalance(100, 20 + variant).available());
            case 2 -> {
                var b = new WalletBalance(100, 40).consume(amount);
                value = b.posted() + "," + b.reserved();
            }
            case 3 -> value = Long.toString(new WalletBalance(100, 40).release(amount).reserved());
            case 4 -> value = new Money(100, CurrencyUnit.CAD).plus(new Money(amount, CurrencyUnit.CAD)).minorString();
            case 5 -> value = Money.decimalAmount((12 + variant) + ".34", CurrencyUnit.CAD).minorString();
            case 6 -> {
                try {
                    new Journal(A, CurrencyUnit.CAD, List.of(
                        new Journal.Entry(A, CurrencyUnit.CAD, Journal.Side.DEBIT, 100),
                        new Journal.Entry(B, CurrencyUnit.CAD, Journal.Side.CREDIT, 100 + amount)));
                    value = "accepted";
                } catch (DomainFailure expected) { value = expected.code(); }
            }
            case 7 -> {
                try {
                    new Journal(A, CurrencyUnit.CAD, List.of(
                        new Journal.Entry(A, CurrencyUnit.CAD, Journal.Side.DEBIT, amount),
                        new Journal.Entry(B, CurrencyUnit.USD, Journal.Side.CREDIT, amount)));
                    value = "accepted";
                } catch (DomainFailure expected) { value = expected.code(); }
            }
            case 8 -> {
                var intent = Map.of("amount", Long.toString(amount));
                value = Boolean.toString(Idempotency.fingerprint(A, "transfer", "", intent)
                    .equals(Idempotency.fingerprint(B, "transfer", "", intent)));
            }
            case 9 -> {
                var intent = Map.of("amount", Long.toString(amount));
                value = Boolean.toString(Idempotency.fingerprint(A, "payment", "", intent)
                    .equals(Idempotency.fingerprint(A, "refund", "", intent)));
            }
            case 10 -> value = Long.toString(new PaymentRules.Snapshot(100, PaymentRules.State.SETTLED, 20, false, 1)
                .refund(amount).refunded());
            case 11 -> {
                try {
                    new PaymentRules.Snapshot(100, PaymentRules.State.SETTLED, amount, false, 1).reverse();
                    value = "accepted";
                } catch (DomainFailure expected) { value = expected.code(); }
            }
            case 12 -> value = SchedulePolicy.next(LocalDateTime.of(2026, 1, 5 + variant, 10, 30),
                SchedulePolicy.Recurrence.WEEKLY).toString();
            case 13 -> {
                byte[] secret = new byte[32]; Arrays.fill(secret, (byte) 7);
                byte[] body = ("{\"amount\":" + amount + "}").getBytes(java.nio.charset.StandardCharsets.UTF_8);
                Clock clock = Clock.fixed(Instant.parse("2026-01-01T00:00:00Z"), ZoneOffset.UTC);
                value = Boolean.toString(WebhookSignature.verify(secret, clock.instant().getEpochSecond(), A,
                    body, "v1=" + "0".repeat(64), clock));
            }
            case 14 -> value = Long.toString(new Projection(A, 20, PaymentRules.State.PENDING)
                .apply(new Projection(A, 10 + variant, PaymentRules.State.PENDING)).version());
            default -> throw new IllegalArgumentException("operation");
        }
        // Values above are generated primitives, not artifact-supplied strings.
        System.out.println(value);
    }
}
