# Optional HTTP model boundary

Deterministic analysis remains the only published classification path. No provider is
enabled by application startup. `HTTPModelProvider` implements an explicit opt-in
OpenAI-compatible chat-completion JSON transport with an operator-configured HTTPS
endpoint, model and credential. The endpoint never comes from uploaded evidence.
`propose_for_analysis` rechecks scope, derivative digests, redaction/restriction and
expiry before selecting only the analysis's approved supporting/counterevidence.

Responses are untrusted proposals: schema validation, allowed evidence IDs, sensitive
output rejection and product-risk downgrade prevention apply. Every hypothesis stays
`unverified_hypotheses_only`; no claim of semantic validation is attached. The original
deterministic analysis/reviews are never replaced. Provider code has no shell, file,
GitHub, test deletion, release, merge, or tool-calling interface. A tool response is
rejected. This is a supplementary proposal API, not a paid-provider benchmark.

## Limits and failure behavior

The adapter bounds context, response bytes, output tokens, concurrent requests, retry
attempts, request spacing, per-run request/reserved-token budget and circuit failures.
The legacy library interface shares one in-process `RunBudget` across the entire run;
persisted use must go through the durable boundary below. Cancellation is checked before
requests, during backoff and between streamed chunks; an in-flight socket is bounded
by a total wall-time deadline rather than instantaneously interrupted. An exceeded
deadline disables that provider instance and does not retry the ambiguous request.
Transport slots remain occupied until their task actually exits, preventing one
instance from accumulating stuck requests. Retries for eligible bounded failures are bounded and
may consume provider spend; each attempt consumes the run budget before transport.
Authentication failures, redirects, rate limits, malformed/incomplete outputs and
unknown citations yield explicit deterministic fallbacks, with no response-body or
credential logging. There is no alternate-provider fallback or hidden egress.

Usage is reported only when supplied in the declared numeric format. Cost is unknown
without both configured rates, currency, source and pricing date; configured prices
produce an estimate, never a claim about actual charged cost. `$0` paid-provider spend
in the default mode is not zero infrastructure cost.

## Actual verification and remaining scope

The tests use `httpx.MockTransport` and the model name `test-fixture-not-a-model`.
No real model, API credential, paid invocation, or provider benchmark was used.
Tests exercise transport contracts, failure cases, network-free disabled behavior,
product-risk preservation, secrets/citations, budgets, circuit breakers and actual
DB-backed safe-evidence selection. No model quality claim follows from these tests.

## Durable invocation and attempt ledger

`durable_propose_for_analysis` takes a SQLAlchemy session factory plus an exact
project, run, analysis revision and bounded idempotency key. It owns short
transactions and never commits caller work or holds a DB transaction across HTTP.
New `model_run_budgets`, `model_invocations` and `model_attempts` tables are created
by migration `d3a5f7c9b120`. No provider is activated by this migration or startup.

A committed reservation precedes every attempt. Project/run locking and atomic
budget increments prevent concurrent workers or new provider instances from
resetting request/token ceilings. Later settings can tighten a run's limits;
they cannot raise its original ceiling. Every retry consumes a new reservation.
Prompt bytes plus a framing allowance and output-token limit form a conservative
reservation, not a statement of actual billed tokens or an absolute currency cap.
Reported usage above the reservation is recorded and blocks further work as needed.

Invocations bind immutable analysis/evidence digests, provider configuration and
prompt version. Every attempt revalidates current scope and derivative availability.
Only safe proposals are stored, with an explicitly unverified-hypothesis status;
the original deterministic analysis and its contradictions remain unchanged.
Reading a stored proposal rechecks current evidence. Retention physically clears
proposal text while preserving bounded usage/accounting fields.

Attempts retain allowlisted numeric usage even when proposal validation rejects
the output. Pricing includes both rates, source, date and currency, and remains
an estimate. Unknown or partial usage/cost is never relabeled zero. Credentials,
raw prompts/responses, provider request IDs and private lease-owner values are
excluded from the public projection. Endpoint/model/configuration identity and
idempotency keys are digests; key material is not stored in the ledger.

`recover_model_invocations` fences expired owners without refunding reservations
or replaying an uncertain request. A late owner may reconcile only its own
attempt's numeric usage; it cannot revive the invocation or publish its proposal.
Duplicate submissions return existing state rather than repeat transport.

Local tests use independent SQLite sessions, synthetic fixtures and MockTransport.
Five PostgreSQL concurrency/retention/recovery cases are separately required in
the real CI lane; a local skip is not acceptance. Exact tested revisions/results
are recorded in the delivery ledger.

## Remaining service integration

The adapter and durable bridge are library interfaces, not enabled HTTP endpoints
or dashboard features. Operator configuration, request/status/cancellation UI,
service-wide rate/circuit coordination and authorized real-provider evaluation
remain unfinished. Per-instance rate and circuit controls do not establish a
distributed rate limit. Real-provider invocation requires separate authorization.
