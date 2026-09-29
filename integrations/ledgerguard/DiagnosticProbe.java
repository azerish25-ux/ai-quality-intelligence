import lab.ledgerguard.core.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.HexFormat;
import java.util.Map;
import java.util.UUID;

/** Measurement-only companion probe. No fault switch, oracle or category is read. */
public final class DiagnosticProbe {
    private static final UUID ACTOR = UUID.fromString("00000000-0000-0000-0000-000000000001");
    private static String digest(String value) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
    }
    private static String snapshot(Projection value) throws Exception {
        return "{\"entity_digest\":\"" + digest(value.aggregate().toString()) + "\",\"version\":" + value.version()
            + ",\"state_digest\":\"" + digest(value.state().name()) + "\"}";
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("operation and variant required");
        int operation = Integer.parseInt(args[0]), variant = Integer.parseInt(args[1]);
        if (variant < 0 || variant > 3) throw new IllegalArgumentException("variant");
        long amount = 7 + variant;
        String measurement;
        switch (operation) {
            case 9 -> {
                var intent = Map.of("amount", Long.toString(amount));
                String actor = digest(ACTOR.toString()), payload = digest("amount=" + amount);
                String first = Idempotency.fingerprint(ACTOR, "payment", "", intent);
                String second = Idempotency.fingerprint(ACTOR, "refund", "", intent);
                measurement = "{\"kind\":\"operation_isolation\",\"fingerprint_scope\":\"operation_actor_payload\","
                    + "\"first\":{\"operation\":\"payment\",\"actor_digest\":\"" + actor + "\",\"payload_digest\":\"" + payload
                    + "\",\"fingerprint\":\"" + first + "\"},\"second\":{\"operation\":\"refund\",\"actor_digest\":\"" + actor
                    + "\",\"payload_digest\":\"" + payload + "\",\"fingerprint\":\"" + second + "\"}}";
            }
            case 12 -> {
                var previous = LocalDateTime.of(2026, 1, 5 + variant, 10, 30);
                var next = SchedulePolicy.next(previous, SchedulePolicy.Recurrence.WEEKLY);
                measurement = "{\"kind\":\"weekly_recurrence\",\"timezone\":\"America/Halifax\",\"wall_time_policy\":\"preserve\","
                    + "\"previous_local\":\"" + previous + "\",\"next_local\":\"" + next + "\"}";
            }
            case 14 -> {
                var previous = new Projection(ACTOR, 20, PaymentRules.State.PENDING);
                var incoming = new Projection(ACTOR, 10 + variant, PaymentRules.State.PENDING);
                var after = previous.apply(incoming);
                measurement = "{\"kind\":\"projection_ordering\",\"stale_event_policy\":\"ignore\",\"before\":" + snapshot(previous)
                    + ",\"incoming\":" + snapshot(incoming) + ",\"after\":" + snapshot(after) + "}";
            }
            default -> throw new IllegalArgumentException("unsupported measurement operation");
        }
        System.out.println("{\"schema_version\":\"contract-observations-v1\",\"test_identity\":\"measurement::result\","
            + "\"attempt\":0,\"browser\":null,\"measurement\":" + measurement + "}");
    }
}
