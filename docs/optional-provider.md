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
Callers share one `RunBudget` across the entire run. Cancellation is checked before
requests, during backoff and between streamed chunks; an in-flight socket is bounded
by the HTTP timeout rather than instantaneously interrupted. Retries are bounded and
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

The adapter is a library interface, not yet an enabled HTTP endpoint or dashboard
feature. Persistent invocation records, restart-safe shared budgets, integration with
operator configuration/UI and real-provider evaluation remain unfinished. Until those
are delivered, callers must not treat an in-process budget as durable service-wide
spend enforcement. Real-provider invocation requires separate authorization.
