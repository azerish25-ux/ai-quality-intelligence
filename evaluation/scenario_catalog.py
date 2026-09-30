"""Evaluation-only synthetic incident descriptions, never imported by inference.

Each row describes a distinct mechanism/observability scenario and its evidence,
not a new family created by renaming a test. Labels are agent-reviewed, not expert
adjudicated. The catalogue is public and therefore not an independently blinded
benchmark. Nuisance variants of a row remain in the same split.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    family: str
    category: str
    mechanism: str
    observations: str
    rationale: str


# Deliberately do not insert analyzer keywords uniformly or rewrite difficult
# observations to improve a score. Many unsupported contracts should expose
# diagnostic abstentions in the existing deterministic system.
PRODUCT = [
    (
        "rollback-invoice-write-outside-transaction",
        "Invoice insert commits outside the rejected debit transaction",
        "Atomic operation contract requires no durable changes after a rejected debit. Invoice rows before=0, after=1; debit rows before=0, after=0; debit returned rejected.",
        "The rejected business operation left a durable invoice despite the explicit atomicity contract.",
    ),
    (
        "concurrent-debit-read-modify-write",
        "Two successful debits overwrite each other's balance update",
        "Two distinct debit receipts each record 20 minor units. Initial posted balance=100; final posted balance=80; no other operations occurred. Required result=60.",
        "Two accepted operations and the isolated balance delta establish a lost update.",
    ),
    (
        "round-half-even-implemented-half-up",
        "Tie rounding uses half-up instead of contracted half-even",
        "Published rounding contract is HALF_EVEN at two decimal places. Conversion input=1.005; returned minor units=101; exact decimal reference=100.",
        "The documented decimal rule and exact tie result distinguish arithmetic failure from a stale test expectation.",
    ),
    (
        "refund-destination-overwritten-with-merchant",
        "Refund routes to the merchant instead of the original payer",
        "Refund contract names original payer account P. Receipt refund target=M; journal credit account=M; original payment payer=P; payer and merchant are distinct.",
        "Receipt and posting independently agree on a destination forbidden by the refund contract.",
    ),
    (
        "role-bitmask-write-check-inverted",
        "Read-only role bitmask passes the write authorization check",
        "Actor has read-only role; policy revision permits reads only. Write endpoint returned 201 and created a row. Authorization bypass reproduced with the same policy and no elevated session.",
        "The current role, policy, response and durable write corroborate an authorization violation.",
    ),
    (
        "revoked-session-cache-not-invalidated",
        "Revoked sessions remain accepted by an authorization cache",
        "Revocation receipt timestamp precedes request by 30 seconds. The configured revocation grace is zero. The same session created an accepted transfer after revocation; fresh session checks reject it.",
        "A recorded revocation and subsequent protected operation violate the documented immediate-revocation contract.",
    ),
    (
        "amount-integer-overflow-wraps",
        "Unchecked addition wraps a maximum signed monetary integer",
        "The amount API contract requires overflow rejection. Inputs=9223372036854775807 and 1; returned amount=-9223372036854775808; status=200.",
        "The exact operands and returned signed result demonstrate overflow instead of the contracted rejection.",
    ),
    (
        "outbox-published-before-commit",
        "An outbox event becomes visible before its enclosing transaction commits",
        "Consumer received an order-created event with receipt E. The corresponding producer transaction rolled back and order lookup returned not found. Contract forbids event visibility before commit.",
        "Consumer receipt and producer rollback establish the forbidden partial visibility.",
    ),
    (
        "webhook-nonce-store-omitted",
        "A valid signed webhook nonce is not recorded for replay rejection",
        "The same valid signature and nonce were submitted twice within the validity window. Two independent fulfillment receipts were created. Contract allows only one fulfillment for a nonce.",
        "A valid signature does not justify processing the same nonce twice; independent receipts establish the replay effect.",
    ),
    (
        "tenant-filter-missing-on-export",
        "Export query omits the tenant restriction",
        "Authenticated tenant A requested its export. Returned record owner tenant=B; database owner=B; policy denies cross-account exports. Request scope contains only tenant A.",
        "Current request scope and stored owner establish cross-account access rather than an ambiguous HTTP error.",
    ),
    (
        "fee-posted-on-wrong-journal-side",
        "Fee posting debits both legs instead of debiting and crediting",
        "Fee journal has debit=5 to the payer and debit=5 to revenue, credit=0. Ledger unbalanced: the committed journal violates per-currency debit-credit equality.",
        "The two persisted legs prove the accounting imbalance independently of the exception message.",
    ),
    (
        "deleted-profile-cache-survives-invalidation",
        "Profile deletion does not invalidate cached personal data",
        "Deletion receipt confirms profile removal; direct persistent lookup returns absent. Subsequent authenticated cache lookup returns the deleted profile. Policy requires immediate read invalidation.",
        "The contrasted storage/cache results and deletion receipt demonstrate a cache invalidation defect.",
    ),
    (
        "fx-rate-direction-inverted",
        "Currency conversion divides by a rate quoted for multiplication",
        "Rate contract: 1 CAD = 0.75 USD. Input=100 CAD; observed settlement=133.33 USD; exact contracted result=75 USD. Both receipts reference the same fixed quote.",
        "The quote direction and settled units establish an incorrect conversion, not a changed market quote.",
    ),
    (
        "pagination-cursor-uses-nonunique-timestamp",
        "Timestamp-only pagination skips records with equal timestamps",
        "Stable dataset has records A,B,C at the same timestamp. Page one returns A,B; next cursor advances strictly past the timestamp; page two is empty. Contract requires all three records exactly once.",
        "A fixed complete dataset and cursor sequence prove omission without concurrent-write ambiguity.",
    ),
    (
        "soft-delete-uniqueness-index-wrong-scope",
        "A deleted identifier blocks permitted identifier reuse",
        "Current contract permits reuse after deletion. Old record has deleted=true; new insert returns uniqueness violation from the all-records index. No active record has the identifier.",
        "The authoritative contract and index scope distinguish an implementation defect from a stale test.",
    ),
    (
        "ttl-seconds-treated-as-milliseconds",
        "Session expiry interprets configured seconds as milliseconds",
        "Configured session lifetime=3600 seconds. Issued at t=0; expiry recorded at t=3.6 seconds. Stored configuration and response use the same policy revision.",
        "A thousand-fold unit mismatch is observable without guessing about network delay.",
    ),
    (
        "utf8-byte-limit-counts-codepoints",
        "Payload size guard counts Unicode code points instead of UTF-8 bytes",
        "Contract caps UTF-8 payload at 8 bytes. Three three-byte code points produce 9 bytes; request accepted with status=201; stored payload contains all 9 bytes.",
        "Measured byte length and accepted storage violate the declared byte budget.",
    ),
    (
        "negative-stock-check-after-commit",
        "Stock underflow check runs after committing the stock decrement",
        "Initial stock=1; purchase quantity=2. API returned insufficient stock but persistent stock=-1. Contract requires rejected purchases to preserve inventory.",
        "The rejection and changed negative stock establish a product invariant failure.",
    ),
    (
        "csv-export-spreadsheet-formula-unescaped",
        "CSV export fails to neutralize formula-prefixed user content",
        "Export safety contract requires formula-neutral text cells. Uploaded name begins with =SUM(1,2); exported cell begins with the same equals sign without an escape prefix.",
        "Raw exported bytes violate the configured CSV safety contract; no spreadsheet is executed.",
    ),
    (
        "content-length-compressed-size-mismatch",
        "Response length header reports pre-compression bytes",
        "Server emitted gzip body of 120 bytes with Content-Length=500 and closed the stream. Uncompressed content is 500 bytes; no proxy modified the response.",
        "The captured response header and encoded-body size isolate the server's response framing defect.",
    ),
    (
        "sort-decimals-lexicographically",
        "Numeric amount endpoint applies lexicographic ordering",
        "Contract specifies ascending numeric order. Returned amounts=[1,10,2]; all are validated decimal values in one currency. Exact numeric order=[1,2,10].",
        "The documented ordering and returned values establish an implementation mismatch.",
    ),
    (
        "etag-not-varied-by-authorization",
        "Shared response cache reuses an ETag across authorization scopes",
        "Two authorized users have disjoint visible records. Response cache key and ETag are identical; the second user receives the first user's record. cross-account response reuse is visible in captured bodies.",
        "Request identities, visibility rules and response contents establish cross-account leakage.",
    ),
    (
        "unique-insert-check-then-act",
        "Concurrent unique creation checks precede both unguarded inserts",
        "Two requests for the same business identifier both observe absence and both commit distinct row IDs. Contract permits one active row; the final query returns two.",
        "Two commits and the final isolated query establish a uniqueness race.",
    ),
    (
        "backup-restore-omits-tombstones",
        "Restore omits deletion tombstones and resurrects deleted records",
        "Backup contains record R and its later deletion tombstone. Restore import reports success but R is visible. Restore contract requires applying tombstones after records.",
        "The retained backup entries and restored visibility prove the deletion was not honored.",
    ),
]
TEST = [
    (
        "selector-id-obsolete-after-approved-markup-change",
        "Test uses a removed element ID instead of the current accessibility contract",
        "Approved UI contract uses accessible name Submit order. DOM includes that button; test selector #old-submit matches nothing. Test code still asserts the removed ID.",
        "Current UI contract and DOM satisfy the product requirement; the locator contradicts it.",
    ),
    (
        "http-expectation-stale-after-contract-version",
        "Test still expects 200 for a newly documented 201 response",
        "Signed-off API contract revision 2 specifies 201 for creation. Response is 201 with the required body. Test source expects 200. expected contract and test assertion disagree.",
        "The current contract, response and assertion isolate the obsolete expectation.",
    ),
    (
        "fixture-foreign-key-does-not-exist",
        "Test fixture references an account never inserted",
        "fixture invalid: request references account F; seed manifest contains only account A. API returns documented 404; database query confirms F absent.",
        "The fixture inventory and correct missing-account response establish a test setup defect.",
    ),
    (
        "test-clock-hardcoded-local-zone",
        "Test computes a local date using the runner timezone instead of configured project timezone",
        "Product configured zone is America/Halifax. At 02:00 UTC its prior local date is correct; test computes UTC calendar date. Test source ignores the configured timezone.",
        "The instant, configured zone and calculation source distinguish the test assumption from a scheduling defect.",
    ),
    (
        "mock-response-schema-outdated",
        "Mock returns a removed response field",
        "mock contract drift: current schema requires receipt_id; mock fixture supplies transaction_id only. Real contract fixture validates, mocked client fixture does not.",
        "Versioned schema and mock bytes isolate stale mock data.",
    ),
    (
        "teardown-shared-transaction-not-closed",
        "Deterministic teardown leaves a test transaction open",
        "teardown leaked transaction T from test A. Test B waits on T; application request never begins. Test runner source omits rollback in a finally block.",
        "Lock ownership and the absent application request tie the failure to test cleanup.",
    ),
    (
        "assertion-unit-dollars-versus-cents",
        "Test compares integer minor units to decimal major units",
        "API contract returns amount_minor=1234 for 12.34 CAD. Response matches contract; assertion compares amount_minor to 12.34 without conversion.",
        "The contract and assertion operands demonstrate the test's unit error.",
    ),
    (
        "test-secret-not-updated-after-fixture-rotation",
        "Test signs fixtures with an obsolete synthetic key",
        "Fixture keyset revision 2 is active. Test signer selects revision 1, verifier rejects signature as documented. Test setup has not loaded the new synthetic keyset.",
        "Pinned fixture key versions establish a test credential mismatch, not a verifier regression.",
    ),
    (
        "assertion-uses-reference-equality",
        "Test compares object identity where the contract promises value equality",
        "Two returned immutable objects have identical specified fields and different memory identities. Test uses an identity assertion; product contract specifies equal values only.",
        "Recorded fields and assertion operator distinguish a test assertion defect.",
    ),
    (
        "test-query-omits-required-filter",
        "Test helper silently drops the required query parameter",
        "Request contract requires filter=active. Helper emitted URL without filter; API returned documented 400. Test expected a filtered 200 response.",
        "Captured request and helper code show that the product never received a valid request.",
    ),
    (
        "test-awaits-wrong-promise",
        "Test awaits setup completion rather than the operation's promise",
        "Runner trace shows assertion executed before operation promise resolved. Test awaited the setup promise; the operation later returned the correct contracted result.",
        "Promise identities and trace ordering isolate incorrect test synchronization.",
    ),
    (
        "fixture-encoding-decodes-twice",
        "Fixture loader applies URL decoding twice",
        "Stored fixture is literal percent-encoded text. Loader performs two decodes before request; captured request bytes differ from the intended fixture. Product returns the documented result for the actual bytes.",
        "The stored fixture, loader steps and captured request explain a test-only input mutation.",
    ),
]
INFRA = [
    (
        "resolver-servfail-before-connection",
        "Runner DNS resolver returns SERVFAIL",
        "dns failure: resolver response SERVFAIL for the configured service; no TCP connection or application request occurred. Independent resolver diagnostic records the same failure.",
        "Resolver evidence establishes failure before the product boundary.",
    ),
    (
        "runner-ca-bundle-missing-root",
        "Runner lacks the configured service certificate root",
        "TLS handshake failed before any HTTP request. Certificate chain validates against the deployment trust bundle; runner trust bundle lacks its root certificate.",
        "Compared trust bundles isolate the environment rather than an application response.",
    ),
    (
        "artifact-volume-inodes-exhausted",
        "Runner artifact volume exhausts inodes",
        "no space left: inode usage=100%, byte usage=40%. Test process cannot create its initial temporary file; no application request occurred.",
        "Filesystem counters and the failed setup syscall establish runner storage exhaustion.",
    ),
    (
        "container-oom-killed-runner",
        "Container memory limit kills the test runner",
        "runner exited with signal 9. Container event=OOMKilled; memory limit=256 MiB; peak=256 MiB. Supervisor records kill before the test request.",
        "Supervisor and memory evidence corroborate the environment failure.",
    ),
    (
        "cpu-quota-starves-test-worker",
        "Host CPU quota prevents the worker from receiving scheduled CPU",
        "Test worker waits 30 seconds before its first instruction. Cgroup throttled time=29.9 seconds; service responds normally to an independent probe during that interval.",
        "Scheduler and independent service observations isolate runner resource contention.",
    ),
    (
        "database-pool-exhausted-by-admin-session",
        "External maintenance sessions consume all database connection slots",
        "Connection acquisition rejected before application transaction. Database reports all 20 slots owned by maintenance sessions; runner diagnostic records the slot limit and owners.",
        "Independent connection inventory identifies a shared environment limit.",
    ),
    (
        "database-service-stopped-by-maintenance",
        "Database service is intentionally stopped during the run",
        "database unavailable: supervisor records database stopped at 10:00 before the test begins. TCP probe receives connection refused; no server process exists.",
        "Supervisor state and connection probe corroborate the unavailable dependency.",
    ),
    (
        "egress-route-removed-on-runner",
        "Runner routing table loses the service-network route",
        "Kernel reports network unreachable before connection. Runner route table lacks the destination subnet; a separate host reaches the healthy service.",
        "Routing and independent-host evidence distinguish runner networking from a product response.",
    ),
    (
        "package-mirror-unavailable-during-setup",
        "Configured package mirror is unavailable before tests start",
        "Dependency installation failed during setup; test process not launched. Mirror health endpoint returned 503 and runner installation log recorded the same outage.",
        "The execution phase and independent mirror status locate the failure outside the product.",
    ),
    (
        "fixed-port-held-by-unrelated-service",
        "An unrelated daemon owns the runner's configured fixed port",
        "Bind failed before application launch. Socket inventory identifies the port owner as an unrelated pre-existing daemon; runner configuration requires that fixed port.",
        "Port ownership and startup phase establish an environment collision.",
    ),
    (
        "browser-shared-library-absent",
        "Runner image lacks a required browser shared library",
        "Browser process loader reports missing libX11 before any page opens. Runner image inventory confirms the library absent; application health probe passes.",
        "Loader and image inventory identify an incomplete runner image.",
    ),
    (
        "runner-wall-clock-unsynchronized",
        "Runner clock is far outside the test environment's allowed skew",
        "Independent time probe reports runner clock 600 seconds fast; allowed skew=30 seconds. Product timestamps match the reference clock; runner time service is stopped.",
        "Independent clock measurements isolate the environment's time source.",
    ),
]
FLAKE = [
    (
        "harness-fixed-sleep-before-animation-end",
        "Test's fixed sleep races the browser animation completion",
        "Harness assertion occurred at 100 ms; animation completed at 140 ms; final DOM satisfies the UI contract. Controlled harness review isolated premature assertion timing.",
        "Prior reviewed reproductions and matching current trace support the known nonproduct timing issue.",
    ),
    (
        "unordered-fixture-discovery-order",
        "Harness discovers otherwise independent fixture files in unstable filesystem order",
        "Fixture loader order changed between runs while fixture bytes and product build stayed fixed. The assertion assumes the first listed fixture. Controlled review isolates directory enumeration order.",
        "Reviewed history and order traces support the known fixture discovery instability.",
    ),
    (
        "unseeded-random-test-data-boundary",
        "Unseeded test data occasionally violates a documented test precondition",
        "Runner-generated input selected an excluded boundary value. Product rejects it as documented; generator seed was not fixed. Prior review reproduced the invalid random input branch.",
        "Matching reviewed prior failures distinguish this known random-fixture issue from a product race.",
    ),
    (
        "test-midnight-wall-clock-read-twice",
        "Test reads its wall clock twice across a date boundary",
        "Assertion operands were sampled on opposite sides of midnight. Product used one documented request timestamp. Prior harness review reproduced the two-clock-read assumption.",
        "Recorded sampling instants and qualifying reviewed history isolate the recurring test-clock race.",
    ),
    (
        "screenshot-capture-before-font-ready",
        "Screenshot fixture captures before its test-managed font finishes loading",
        "Capture occurred before the font-ready promise; later capture matches approved pixels. Network/font trace and prior review identify missing font synchronization in the screenshot harness.",
        "Current font readiness and matching historical adjudication support this known capture issue.",
    ),
    (
        "parallel-log-capture-interleaving",
        "Harness joins parallel subprocess output without preserving per-process ordering",
        "Two subprocesses emitted correct ordered records; combined harness stream interleaves them. Assertion incorrectly requires total ordering. Prior review reproduces the capture merge behavior.",
        "Per-process logs and reviewed recurrence isolate harness aggregation instability.",
    ),
    (
        "test-port-reservation-released-before-bind",
        "Harness releases its ephemeral port reservation before its own child binds",
        "Parent reserved then released a port; another test child bound it before the intended child. Product was not launched. Prior review isolates the harness allocation race.",
        "Traced ownership transitions and reviewed prior cases establish the known harness race.",
    ),
    (
        "randomized-test-hash-seed-affects-snapshot",
        "Snapshot helper serializes a set in process-randomized hash order",
        "Set values are identical across failures and passes; serialization order changes with runner hash seed. Product contract treats the set as unordered. Prior review confirms snapshot helper ordering.",
        "Recorded identical sets and reviewed seed dependence support the known nonproduct snapshot issue.",
    ),
    (
        "test-double-delayed-callback-delivery",
        "A test double nondeterministically delays its own callback past the assertion",
        "Mock queue trace shows callback scheduled by the test double after its assertion deadline. Real service is not invoked. Prior review reproduces double-specific queue scheduling.",
        "Mock ownership and historical reproduction tie the intermittent failure to the test double.",
    ),
    (
        "test-cleanup-finalizer-deferred",
        "Harness relies on garbage collection to release a temporary test file",
        "Open-handle owner is the prior fixture object; cleanup occurs only when GC runs. Explicit cleanup resolves the reproduction. Reviewed history matches the same fixture finalizer behavior.",
        "Handle ownership and reviewed GC dependence support known test cleanup instability.",
    ),
    (
        "test-network-interceptor-registered-late",
        "Browser harness registers its interceptor after triggering the request",
        "Browser trace records request before interceptor registration. Product returns correct data; test waits for a mock-only response that was never installed. Prior review reproduces this harness ordering race.",
        "Trace order and reviewed repeated behavior identify the known late-interceptor issue.",
    ),
    (
        "snapshot-temp-root-random-suffix",
        "Snapshot helper leaks a random temporary-root suffix into expected output",
        "All semantic output fields match; only the test-created temporary root suffix differs. Prior review confirms the snapshot helper failed to normalize this nondeterministic test path.",
        "Reviewed history and semantic equivalence isolate a known fixture presentation instability.",
    ),
]
UNKNOWN = [
    (
        "missing-image-only-assertion-context",
        "Screenshot assertion lacks its required expected and actual images",
        "Screenshot comparison failed; expected and actual image attachments are absent. No DOM, pixel difference or comparison threshold is retained.",
        "The missing comparison inputs prevent distinguishing product appearance from capture or expectation errors.",
    ),
    (
        "trace-unavailable-after-generic-timeout",
        "A generic wait timeout has no trace or phase information",
        "Wait deadline exceeded. Trace attachment was not uploaded. No request, selector, worker or service diagnostic identifies what was being awaited.",
        "The generic symptom and missing trace do not identify a cause.",
    ),
    (
        "exception-stack-truncated-before-origin",
        "Only a truncated exception suffix survives",
        "Captured error ends with 'at handler'; exception type, origin, message and preceding stack frames are missing.",
        "The retained fragment does not distinguish categories or establish the root cause.",
    ),
    (
        "unrecognized-response-without-contract",
        "An unfamiliar response cannot be compared to an available contract",
        "Observed response status=418 with an empty body. The endpoint contract and deployment revision are unavailable.",
        "Without a contract or revision, the unusual status alone is not a diagnosis.",
    ),
    (
        "independent-causes-with-conflicting-observations",
        "Two uncorrelated services report incompatible explanations",
        "One log says a request completed; another says its connection never opened. Correlation IDs are missing and timestamps overlap only approximately.",
        "The observations cannot be attributed to the same request or a single cause.",
    ),
    (
        "configuration-version-not-retained",
        "Behavior changed but the active configuration revision is unknown",
        "Response differs between runs. Build identifiers match, but feature flag values and configuration revision were not recorded.",
        "Missing configuration prevents deciding whether the result violates the active contract.",
    ),
    (
        "required-shard-result-not-received",
        "One required shard report is missing",
        "Coordinator expected two shards and received one. The surviving shard records an unexplained assertion mismatch; the missing shard may contain setup diagnostics.",
        "Incomplete required context cannot support a confident cause for the unexplained failure.",
    ),
    (
        "retry-pass-without-reviewed-history",
        "A retry succeeds without qualifying historical review",
        "Attempt one failed with an unexplained wait deadline; attempt two passed. There is no prior matching review or controlled reproduction.",
        "Retry recovery alone does not prove a harmless or known flaky cause.",
    ),
    (
        "silent-process-termination-no-supervisor-events",
        "A process stops without exit or supervisor diagnostics",
        "The runner stream ended. Exit status, resource counters and supervisor events were not retained; application logs are also absent.",
        "Silent termination does not establish whether the runner, product or capture system failed.",
    ),
    (
        "transport-reset-no-side-specific-evidence",
        "A transport reset has no endpoint or network diagnostics",
        "Client observed stream reset after sending bytes. Server receipt, proxy events, request identity and durable effect measurements are unavailable.",
        "A reset alone cannot distinguish infrastructure interruption from a product-side failure.",
    ),
    (
        "redacted-identifiers-destroy-correlation",
        "Sensitive identifiers were removed without preserving correlation",
        "Two sanitized records contain different outcomes but all request identifiers are blank. It is unknown whether the records describe the same operation.",
        "Loss of correlation prevents treating apparently conflicting records as evidence for one cause.",
    ),
    (
        "latency-comparison-missing-workload-units",
        "A latency comparison omits workload and units",
        "Current reported value=200; previous=100. Units, sample count, statistic and workload concurrency are absent.",
        "An unqualified numeric increase cannot establish a performance regression or its cause.",
    ),
]


def scenarios() -> list[Scenario]:
    result = []
    for category, rows in [
        ("product_defect", PRODUCT),
        ("test_defect", TEST),
        ("infrastructure_failure", INFRA),
        ("known_flake", FLAKE),
        ("insufficient_evidence", UNKNOWN),
    ]:
        result.extend(
            Scenario(family, category, mechanism, observed, rationale)
            for family, mechanism, observed, rationale in rows
        )
    return result
