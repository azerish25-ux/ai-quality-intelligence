"""Evaluation-only, agent-authored synthetic scenario catalog.

Each row specifies a distinct causal mechanism and concrete observable facts, not
an expected category embedded in an inference input. Repeated amounts/names are
variants of a row, never new families. The first twelve product mechanisms were
already inspected in M6.1 and remain DEVELOPMENT, including all retained variants.
This is a public authored benchmark, not independently blinded adjudication.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    family: str
    category: str
    observation: str
    reference: str
    mechanism: str
    domain_kind: str | None = None


def rows(category, source):
    return [
        Scenario(family, category, observation, reference, mechanism, domain)
        for family, observation, reference, mechanism, domain in source
    ]


PRODUCT = rows(
    "product_defect",
    [
        (
            "idempotency-fingerprint-omits-operation",
            "The payment and refund requests produced equal identity digests.",
            "Same actor and payload; operation is part of the declared request identity.",
            "Operation discriminator omitted from identity preimage.",
            "operation_identity",
        ),
        (
            "projection-replaces-newer-state-with-stale-event",
            "Projection version 9 became version 8 after delivery of event version 8.",
            "The per-entity contract ignores events older than the stored version; matching state digests are supplied.",
            "Older event replaces newer projection state.",
            "projection_order",
        ),
        (
            "weekly-schedule-advances-six-days",
            "The next occurrence was recorded six local dates after the previous occurrence.",
            "Configured recurrence is seven local calendar days at the same wall time in the declared timezone.",
            "Weekly calendar increment uses six days.",
            "weekly_recurrence",
        ),
        (
            "journal-accepts-unbalanced-entries",
            "Ledger unbalanced: journal J has debit total 900 minor units and credit total 800; commit receipt exists.",
            "Each committed journal must have equal debit and credit totals in one currency.",
            "Journal validation does not enforce equal totals.",
            None,
        ),
        (
            "journal-mixes-currency-units",
            "Journal J committed debit 500 CAD minor units and credit 500 USD minor units.",
            "A journal is single-currency; matching integers across currencies do not balance it.",
            "Journal currency compatibility check omitted.",
            None,
        ),
        (
            "decimal-conversion-wrong-scale",
            "Currency exponent is 2; input decimal 12.34 was stored as 123 minor units.",
            "Decimal coefficient and declared exponent require exactly 1234 minor units.",
            "Decimal conversion uses an exponent one lower than the declared currency scale.",
            None,
        ),
        (
            "refund-forgets-prior-adjustments",
            "Balance invariant: two refunds of 20 and 7 leave the recorded cumulative refund at 7.",
            "The cumulative adjustment must retain both committed refund receipts: total 27.",
            "Refund accumulation replaces rather than adds the previous adjustment.",
            None,
        ),
        (
            "reversal-allows-refunded-payment",
            "Over-credit: a settled payment of 100 was refunded by 20 and then reversed by 100.",
            "The declared state machine prohibits full reversal after a partial refund.",
            "Reversal eligibility ignores prior refunds.",
            None,
        ),
        (
            "wallet-credit-off-by-one",
            "Balance invariant: posted 100 plus credit 7 produced posted 106.",
            "Integer credit arithmetic requires posted 107; reservation remained unchanged.",
            "Credit operation subtracts one minor unit from the increment.",
            None,
        ),
        (
            "available-balance-ignores-reservations",
            "Balance invariant: posted 100 and reserved 20 produced available 100.",
            "Available funds are posted minus active reservations: 80.",
            "Available-balance projection ignores reserved funds.",
            None,
        ),
        (
            "webhook-verifier-accepts-forged-signature",
            "Authorization bypass: a body with an altered byte and the old signature was accepted.",
            "The exact signed body and verification key were unchanged; a modified body must fail authentication.",
            "Webhook signature verification result is ignored.",
            None,
        ),
        (
            "idempotency-fingerprint-omits-actor",
            "Cross-account identity: distinct authenticated actors submitting the same operation/payload received the same fingerprint.",
            "Actor identity is part of the configured request identity contract.",
            "Actor discriminator omitted from identity preimage.",
            None,
        ),
        (
            "lost-update-no-version-check",
            "Two writers read version 4 and balance 100; credits 7 and 9 committed; final balance is 109.",
            "Both receipts are committed and no debit occurred; final balance must conserve both credits: 116.",
            "Read-modify-write update lacks a version predicate.",
            None,
        ),
        (
            "rollback-leaves-outbox-event",
            "Database transaction T aborted; no transfer row exists; its outbox event was delivered and credited a wallet.",
            "The outbox insert must be atomic with its transfer commit; aborted commands have no committed effects.",
            "Outbox write commits on a separate transaction from the business write.",
            None,
        ),
        (
            "closed-account-transfer",
            "Account status CLOSED at version 7 preceded transfer receipt R at version 8.",
            "The product state machine rejects outgoing transfers from a closed account.",
            "Transfer eligibility does not recheck account lifecycle state.",
            None,
        ),
        (
            "negative-transfer-accepted",
            "POST transfer amount_minor=-7 returned a committed receipt; source posted balance increased by 7.",
            "The endpoint contract accepts strictly positive amounts and rejects negative requests without mutation.",
            "Command validation omits the lower amount bound.",
            None,
        ),
        (
            "signed-integer-overflow",
            "Adding 1 to stored integer 9223372036854775807 produced -9223372036854775808 and a success receipt.",
            "Out-of-range arithmetic must reject without changing stored value.",
            "Unchecked signed addition wraps at the storage boundary.",
            None,
        ),
        (
            "auth-token-revocation-cache",
            "Token session S was revoked at 10:00; a request at 10:05 with S returned protected data.",
            "Revocation receipt is authoritative and policy permits no grace period.",
            "Authorization cache retains a revoked session after invalidation.",
            None,
        ),
        (
            "role-scope-mutation-check",
            "A principal with READ_ONLY permission received success for DELETE wallet and the row was removed.",
            "The signed permission snapshot permits reads only; deletion requires administrator permission.",
            "Mutation endpoint checks authentication but omits the action permission.",
            None,
        ),
        (
            "cross-tenant-cache-key",
            "Tenant A cached resource 17; tenant B requested its own resource 17 and received A's body digest.",
            "Both tenant-specific database rows differ; responses must use the authenticated tenant scope.",
            "Shared cache key omits tenant identity.",
            None,
        ),
        (
            "dirty-read-exposes-uncommitted-balance",
            "Reader observed balance 80 written by transaction T; T later rolled back and no committed debit exists.",
            "The endpoint contract exposes committed balances only; the last committed balance was 100.",
            "Read path uses an isolation mode allowing uncommitted state.",
            None,
        ),
        (
            "missing-journal-parent-constraint",
            "Entry E references journal J404; E committed although J404 does not exist.",
            "Every committed entry must resolve to an existing parent journal.",
            "Entry persistence lacks the parent referential constraint.",
            None,
        ),
        (
            "reconciliation-reapplies-adjustment",
            "Reconciliation job K restarted after recording adjustment A; it applied A again and balance moved twice.",
            "The adjustment cursor must advance atomically with its effect; one adjustment ID has one effect.",
            "Reconciliation checkpoint is committed separately after the balance change.",
            None,
        ),
        (
            "time-window-inclusive-end",
            "A benefit was applied at exactly 12:00, the exclusive end of its declared validity window.",
            "The window is [11:00,12:00); timestamp equality at the end must be excluded.",
            "Eligibility uses less-than-or-equal instead of strict less-than at the end boundary.",
            None,
        ),
        (
            "dropped-cache-invalidation",
            "A committed update changed database digest D1 to D2; subsequent uncached read is D2 but cached reads remain D1 beyond TTL.",
            "The invalidation event has a durable receipt and the configured TTL has elapsed.",
            "Cache invalidation consumer acknowledges before deleting its entry.",
            None,
        ),
        (
            "pagination-skips-equal-timestamps",
            "Page one ends at timestamp T with ID 20; page two starts after T and omits IDs 21 and 22 at T.",
            "The contract orders by (timestamp,ID) and all matching records must occur once across pages.",
            "Cursor continuation compares timestamp but omits the tie-breaking identifier.",
            None,
        ),
        (
            "fx-rate-effective-window",
            "A conversion at 10:05 used rate 1.20 whose interval ended at 10:00; active rate was 1.25.",
            "Conversion receipts must use the rate interval containing the command timestamp.",
            "Rate lookup chooses newest inserted record rather than the effective interval.",
            None,
        ),
        (
            "refund-reservation-race",
            "Concurrent refunds of 60 each read remaining refundable 100; both committed, total refunded 120.",
            "The remaining-refundable constraint must be enforced atomically at commit.",
            "Refund limit is checked before competing writes without locking or compare-and-swap.",
            None,
        ),
        (
            "expiry-zone-conversion",
            "Expiry instant 14:00Z was compared as local 14:00-04:00; access succeeded at 16:00Z.",
            "The expiry is an absolute UTC instant, not a wall-clock value in the server zone.",
            "Expiry parsing discards offset information before comparison.",
            None,
        ),
        (
            "partial-commit-two-wallets",
            "Source debit committed and destination credit rolled back; the transfer nevertheless returned success.",
            "Debit and credit are one atomic transaction; a failed side must roll back both.",
            "Wallet legs use separate database transactions.",
            None,
        ),
        (
            "utf8-reference-truncation",
            "A persisted external reference ends in an incomplete UTF-8 byte sequence after a multibyte character was cut.",
            "Accepted references must round-trip as valid UTF-8; length is defined in characters, not partial bytes.",
            "Storage truncates encoded bytes without respecting codepoint boundaries.",
            None,
        ),
        (
            "webhook-sequence-gap",
            "Consumer applied event sequence 13 while the stored sequence was 11; required event 12 is absent.",
            "This stream requires contiguous application and queues events with a sequence gap.",
            "Consumer enforces only increasing rather than contiguous sequence numbers.",
            None,
        ),
    ],
)

TEST = rows(
    "test_defect",
    [
        (
            "selector-renamed-by-contract",
            "Selector #submit-v1 matched zero nodes; captured DOM contains button data-testid=submit-v2.",
            "Approved UI contract renamed the test ID to submit-v2; the test still targets submit-v1.",
            "Test locator retained the superseded UI identifier.",
            None,
        ),
        (
            "locale-decimal-expectation",
            "Rendered locale fr-CA value is 1,25; assertion expected string 1.25.",
            "The selected locale's contract uses a decimal comma; product value is correct.",
            "Test expected string ignores configured locale.",
            None,
        ),
        (
            "fixture-missing-parent",
            "Fixture invalid: test creates a child for parent P404 and receives the documented 404.",
            "Fixture setup never created P404; reference endpoint passes with an existing parent.",
            "Fixture omits the required parent entity.",
            None,
        ),
        (
            "teardown-leaves-unique-row",
            "Teardown leaked row with reference R; next test's insert fails the unique constraint.",
            "Product rejects duplicate references correctly; isolated fresh fixture succeeds.",
            "Previous test teardown does not delete its seeded unique row.",
            None,
        ),
        (
            "mock-response-contract-drift",
            "Mock contract drift: local mock returns {amount:7}; current client expects {amount_minor:7}.",
            "Versioned service schema and real response both use amount_minor.",
            "Test double implements a superseded response schema.",
            None,
        ),
        (
            "created-status-expectation",
            "Assertion expected 200 but POST returned 201 with a valid new resource Location.",
            "Approved endpoint specification requires 201 for resource creation.",
            "Test asserts an obsolete success status.",
            None,
        ),
        (
            "assertion-before-await",
            "Assertion read an empty task result before the test awaited its Promise; awaited result is correct.",
            "The API is asynchronous and the test must await completion before checking it.",
            "Test omits the await at the assertion boundary.",
            None,
        ),
        (
            "mock-clock-zone",
            "Test injected local midnight as UTC midnight and asserted a date one day later than the contract.",
            "The product received the exact injected instant; the test clock setup used the wrong zone.",
            "Fixture clock constructs the intended local instant with a UTC constructor.",
            None,
        ),
        (
            "float-exact-equality",
            "Assertion compared binary floating result 0.30000000000000004 to exact 0.3.",
            "The approximate measurement API specifies tolerance 1e-9; the observed difference is within tolerance.",
            "Test uses exact floating equality instead of the specified tolerance.",
            None,
        ),
        (
            "json-member-order-expectation",
            "Response object contains a=1,b=2; string assertion failed because encoded member order is b,a.",
            "The JSON object contract imposes no member order; decoded values match.",
            "Test compares serialization text instead of object semantics.",
            None,
        ),
        (
            "unordered-result-order",
            "Endpoint returned IDs [3,1,2]; assertion required [1,2,3].",
            "The endpoint explicitly returns an unordered set and all required IDs occur once.",
            "Test imposes an order absent from the API contract.",
            None,
        ),
        (
            "screenshot-fixture-font",
            "Screenshot comparison used fallback font after test fixture omitted its declared font asset.",
            "The same product renders the approved image when the fixture supplies its required font.",
            "Visual test fixture omits a required deterministic font resource.",
            None,
        ),
    ],
)

INFRA = rows(
    "infrastructure_failure",
    [
        (
            "runner-cgroup-oom",
            "Runner exited with signal 9; cgroup memory.events oom_kill increased by 1 at the same instant.",
            "Independent runner diagnostics record enforced memory limit 512 MiB; no application assertion completed.",
            "Runner process is killed by its container memory limit.",
            None,
        ),
        (
            "runner-storage-full",
            "Write failed: no space left on device; filesystem available bytes=0 and inode availability is positive.",
            "Independent runner filesystem measurement and errno ENOSPC agree.",
            "Runner data volume exhausts byte capacity.",
            None,
        ),
        (
            "dns-authoritative-nxdomain",
            "DNS failure NXDOMAIN for dependency.test; resolver trace received an authoritative negative response.",
            "The configured service name was removed from the test environment's DNS zone.",
            "Environment DNS zone lacks the dependency record.",
            None,
        ),
        (
            "dependency-tls-expired",
            "TLS handshake rejected certificate expired at 09:00Z; trusted runner clock reads 10:00Z.",
            "Independent certificate chain inspection confirms its notAfter timestamp; application traffic never started.",
            "Environment dependency certificate expired.",
            None,
        ),
        (
            "service-listener-absent",
            "Connection refused at service port 8081; host inspection shows no listener and supervisor reports stopped.",
            "An independent deployment check confirms the required service process is not running.",
            "Environment supervisor did not start a required dependency.",
            None,
        ),
        (
            "database-connection-pool-limit",
            "Database returned SQLSTATE 53300; server active connection count equals configured max_connections.",
            "Independent server telemetry confirms exhausted connection slots before the test query executes.",
            "Shared database environment exhausts its connection capacity.",
            None,
        ),
        (
            "runner-network-interface-down",
            "Network request returned ENETDOWN; OS link state for the sole route interface is DOWN.",
            "Independent route/link diagnostics show no usable route from this runner.",
            "Runner network interface is disabled.",
            None,
        ),
        (
            "browser-renderer-crash",
            "Browser process crashed with a native signal; minidump timestamp precedes any page assertion.",
            "The runner recorded renderer exit and the test process lost its browser connection.",
            "Browser runtime terminates in native code.",
            None,
        ),
        (
            "cloud-test-quota",
            "Provisioning returned quota_exceeded; control-plane account quota usage equals its limit.",
            "Independent quota API confirms the environment cannot allocate the requested test worker.",
            "Shared cloud account exhausts its worker allocation quota.",
            None,
        ),
        (
            "container-image-absent",
            "Image pull returned MANIFEST_UNKNOWN for the configured immutable digest.",
            "Registry metadata lookup confirms that digest does not exist; test container never starts.",
            "Environment deployment references a removed container image.",
            None,
        ),
        (
            "file-descriptor-exhaustion",
            "Socket open returned EMFILE; process open descriptor count equals RLIMIT_NOFILE.",
            "Independent runner /proc and resource-limit measurements agree.",
            "Runner process exhausts its file descriptor limit.",
            None,
        ),
        (
            "runner-clock-unsynchronized",
            "TLS check reports not-yet-valid; runner clock differs from independent reference by 2 hours.",
            "Certificate is valid at the reference time; NTP status reports unsynchronized runner clock.",
            "Runner wall clock is skewed outside certificate validity tolerance.",
            None,
        ),
    ],
)

FLAKE = rows(
    "known_flake",
    [
        (
            "fixture-dictionary-order",
            "Harness fixture selected a different first element from an unordered dictionary.",
            "Prior controlled harness-only reproduction and reviewed pass/fail runs identify nondeterministic fixture iteration.",
            "Fixture iteration depends on randomized hash order.",
            None,
        ),
        (
            "animation-frame-sampling",
            "Harness sampled the animation midway through a frame; completed frame matches the contract.",
            "Prior review reproduced only the capture timing variation, with stable application end state.",
            "Screenshot fixture capture is scheduled on an uncontrolled animation frame.",
            None,
        ),
        (
            "harness-temp-name-randomness",
            "Test fixture's randomly drawn temporary name collided with its own previously generated name.",
            "Prior reviewed reproduction identifies a small random namespace in the test fixture, not the product.",
            "Harness draws temporary identifiers from an insufficient random namespace.",
            None,
        ),
        (
            "port-allocation-harness-race",
            "Fixture released its reserved loopback port before binding the test double; another fixture claimed it.",
            "Prior controlled reproduction and review isolate the free-port-then-bind fixture race.",
            "Test double port allocation has a time-of-check/time-of-use gap.",
            None,
        ),
        (
            "random-fixture-order",
            "Harness selected a test order that reused a fixture before its own reset step.",
            "Prior reviewed shuffled-order reproductions identify shared fixture ordering instability.",
            "Fixture reset dependency is absent from the test scheduler.",
            None,
        ),
        (
            "clock-tick-harness-boundary",
            "Test fixture captured two wall-clock reads on opposite sides of a tick and compared their text.",
            "Prior review identifies the test's two-read assumption; product receives neither value.",
            "Harness assumes adjacent clock reads share a quantization bucket.",
            None,
        ),
        (
            "seedless-test-data",
            "Unseeded fixture drew a boundary value excluded by its own assertion assumptions.",
            "Prior reviewed seeded replays isolate the fixture generator and show unchanged product responses.",
            "Test data generation is unseeded and contradicts the fixture's own assumptions.",
            None,
        ),
        (
            "harness-callback-registration",
            "Test subscribed after its local mock emitted a completion callback; replay with earlier subscription succeeds.",
            "Prior review reproduces callback ordering solely in the test mock.",
            "Mock emits before the harness installs its listener.",
            None,
        ),
        (
            "fixture-cleanup-watcher",
            "Fixture file watcher delivered its cleanup notification after the harness's polling deadline.",
            "Prior reviewed local fixture reproductions show stable product behavior and variable watcher timing.",
            "Harness cleanup completion depends on an uncontrolled watcher scheduling delay.",
            None,
        ),
        (
            "test-console-interleaving",
            "Two fixture log writers interleaved lines; the test's ordered transcript comparison failed.",
            "Prior review identifies the fixture transcript assertion; application output is not part of this comparison.",
            "Harness expects deterministic ordering from concurrent fixture log producers.",
            None,
        ),
        (
            "fixture-random-salt",
            "Local fixture generated a new salt, but its snapshot expected the previous random salt.",
            "Prior reviewed fixture-only reproductions confirm randomized snapshot input.",
            "Test snapshots an unseeded fixture salt.",
            None,
        ),
        (
            "harness-worker-readiness",
            "Test fixture started its assertion before its local stub worker signaled readiness.",
            "Prior review reproduced the harness startup ordering issue with no production component involved.",
            "Harness waits a fixed delay instead of the stub readiness signal.",
            None,
        ),
    ],
)

INSUFFICIENT = rows(
    "insufficient_evidence",
    [
        (
            "timeout-without-diagnostics",
            "Operation timed out after the configured deadline.",
            "No response, runner diagnostics, or authoritative operation receipt was retained.",
            "Observable timeout does not identify a cause.",
            None,
        ),
        (
            "missing-assertion-body",
            "The test is reported failed, but no assertion body or expected/actual values are present.",
            "Only a failure counter was retained.",
            "The failure body required to distinguish explanations is missing.",
            None,
        ),
        (
            "truncated-stack-before-cause",
            "Stack excerpt ends before the first causal frame; only wrapper invocation is retained.",
            "The source reports truncation and no originating exception details.",
            "Truncation removes the causal portion of the diagnostic.",
            None,
        ),
        (
            "retry-pass-no-history",
            "First attempt timed out and a retry returned successfully.",
            "No prior reviewed history or authoritative first-attempt outcome is available.",
            "Retry recovery alone does not establish harmlessness.",
            None,
        ),
        (
            "conflicting-response-copies",
            "Two purported records for request R disagree: one says success and the other says aborted.",
            "Neither record has an authoritative receipt or ordering metadata.",
            "Unresolved conflicting request evidence.",
            None,
        ),
        (
            "unknown-exception-code",
            "The only retained error is opaque code ZXQ-917 from an undocumented subsystem.",
            "No code dictionary, stack, or reproducible observation is supplied.",
            "Unknown error code lacks interpretable supporting context.",
            None,
        ),
        (
            "screenshot-unavailable",
            "Visual assertion failed, but both the expected and observed images are unavailable.",
            "No safe inspected image derivative or pixel measurements exist.",
            "The only evidence required for the visual comparison is missing.",
            None,
        ),
        (
            "assertion-spec-absent",
            "Assertion says expected 12 and observed 13, without identifying the measured quantity.",
            "No authoritative contract or unit is provided to determine which value is correct.",
            "Numeric mismatch lacks semantic units and contract context.",
            None,
        ),
        (
            "history-unreviewed",
            "An intermittent failure resembles earlier pass/fail observations.",
            "No qualifying prior review attributes the intermittent behavior to a nonproduct cause.",
            "Unreviewed repetition is insufficient to classify a known flake.",
            None,
        ),
        (
            "infrastructure-uncorrelated",
            "A monitoring note records maintenance on a different service in an unspecified time window.",
            "The failing test has no recorded dependency or temporal association with that service.",
            "Uncorrelated environment event does not explain the failure.",
            None,
        ),
        (
            "redacted-only-identifier",
            "The diagnostic identifies a resource only as [REDACTED]; no stable correlation token remains.",
            "The retained evidence cannot connect the failing request to a recorded resource.",
            "Redaction removed a required correlation identity.",
            None,
        ),
        (
            "incomplete-transaction-snapshot",
            "A retried request has a success receipt, but the before/after database snapshots are unavailable.",
            "The number of committed effects cannot be independently reconciled.",
            "Missing transaction observations prevent duplicate-effect diagnosis.",
            None,
        ),
    ],
)

SCENARIOS = PRODUCT + TEST + INFRA + FLAKE + INSUFFICIENT
assert len(SCENARIOS) == 80 and len({s.family for s in SCENARIOS}) == 80


def split_for(scenario: Scenario) -> str:
    group = {
        "product_defect": PRODUCT,
        "test_defect": TEST,
        "infrastructure_failure": INFRA,
        "known_flake": FLAKE,
        "insufficient_evidence": INSUFFICIENT,
    }[scenario.category]
    index = group.index(scenario)
    if scenario.category == "product_defect":
        return "development" if index < 12 else "test"
    return "development" if index < 4 else "calibration" if index < 6 else "test"


def variant_count(scenario: Scenario) -> int:
    group = {
        "product_defect": PRODUCT,
        "test_defect": TEST,
        "infrastructure_failure": INFRA,
        "known_flake": FLAKE,
        "insufficient_evidence": INSUFFICIENT,
    }[scenario.category]
    index = group.index(scenario)
    return (
        3
        if (
            index < 16
            if scenario.category == "product_defect"
            else index in {0, 1, 8, 9, 10, 11}
        )
        else 2
    )
