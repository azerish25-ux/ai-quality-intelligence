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
prompt version. Preview, approval, each attempt, settlement and stored-proposal
reads revalidate current scope, original accepted analysis inputs and derivative
availability. Known-flake proposals also require the original prior-only history
and its explicit human citations to remain valid. Uncited accepted inputs affect
eligibility without becoming additional transmitted evidence. Missing support
withholds the proposal while preserving the recorded invocation and accounting.
Only safe proposals are stored, with an explicitly unverified-hypothesis status;
the original deterministic analysis and its contradictions remain unchanged.
Reading a stored proposal rechecks current evidence. Retention physically clears
proposal text while preserving bounded usage/accounting fields.

The in-process compatibility helper uses the same current-support checks before
each request and before returning a successful proposal. It forwards reservations
and completions to the caller's original shared `RunBudget`; losing support does
not refund reservations or discard returned numeric usage/pricing. This helper
requires normal Session autoflush and returns an explicit fallback under
`no_autoflush`, preserving pending caller changes. It refreshes only the relevant
analysis/failure/run/execution graph and never commits or rolls back caller work.
Visibility of another transaction's changes remains subject to the caller's
database isolation. Persisted application work uses fresh factory-owned
transactions and PostgreSQL READ COMMITTED, rather than this compatibility helper.

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

## Optional service deployment

The default `compose.yaml` is unchanged: its API and ordinary ingestion worker
remain on the original internal network, have no model credentials, and never
start a provider transport. The optional HTTP routes project disabled status until
an operator explicitly configures the feature. Deterministic analysis remains the
published result, including after provider success or failure.

`compose.provider.yaml` is an explicit, separate overlay and `provider` profile.
It disables demo mode for the API and both workers and requires production
authentication with secure session cookies. Provider submission and execution are
denied in demo mode even for an authenticated administrator: demo setup can mint
privileged accounts, so authentication alone does not make that deployment trusted.
It adds `python -m failurelens.provider_jobs`, which claims only
`model_provider_proposal_v1` jobs, and a dedicated egress proxy. The ordinary worker
excludes provider jobs from both claiming and recovery. The provider worker reads
the same PostgreSQL database and approved evidence volume; its artifact mount is
read-only. Both application workers retain no direct Internet route.

The network membership is deliberately asymmetric:

| Service | Networks | Model credential |
|---|---|---|
| API, ordinary ingestion worker, PostgreSQL | Existing internal `failurelens` | None |
| Provider worker | Internal `failurelens` and internal `provider-egress` | Worker only |
| Provider proxy | Internal `provider-egress` and `provider-outbound` | None |
| Existing dashboard gateway | Existing `failurelens` and `edge` | None |

The proxy has no published host port and never joins `failurelens`. Enabling the
optional overlay therefore does not make the proxy reachable to ordinary workers
through the shared database network. Both optional services run without root,
with read-only roots, dropped capabilities and bounded memory/CPU. This topology
is an intended deployment boundary; an actual Docker verification result is
required before claiming it has passed for a delivered revision.

### Operator configuration and readiness

Supply these operator-owned environment values when using the overlay:

- `FAILURELENS_PROVIDER_DATABASE_PASSWORD`: private operator-selected PostgreSQL
  password; required with no default
- `FAILURELENS_PROVIDER_DATABASE_URL`: matching private SQLAlchemy connection URL
  for the API and both workers; required with no default
- `FAILURELENS_PROVIDER_ID`: stable provider identity for shared admission controls
- `FAILURELENS_PROVIDER_ALLOWED_PROJECT_IDS`: explicit comma-separated project IDs
- `FAILURELENS_PROVIDER_ENDPOINT`: approved HTTPS completion URL on port 443
- `FAILURELENS_PROVIDER_PROXY_HOST`: the exact lowercase ASCII DNS hostname in that URL
- `FAILURELENS_PROVIDER_MODEL`: approved model name
- `FAILURELENS_PROVIDER_WORKER_ENV_FILE`: path to a private, operator-managed file
  containing only the `FAILURELENS_PROVIDER_TOKEN` assignment
- `FAILURELENS_PROVIDER_API_ENV_FILE`: separate private API-only file containing
  `FAILURELENS_BOOTSTRAP_ADMIN_USERNAME` and a strong
  `FAILURELENS_BOOTSTRAP_ADMIN_PASSWORD` for the trusted initial administrator

The API receives endpoint/model/limits and the explicit proxy address as nonsecret
provider metadata, plus its own bootstrap authentication configuration. It never
loads the worker credential file. The ordinary ingestion worker and proxy receive
no model token; neither worker nor the proxy receives the bootstrap password.
The database settings override the base demo password and connection URL for
PostgreSQL, API, ordinary worker and provider worker. The bundled database retains
its nonsecret database/user name `failurelens` at `db:5432`; supply the matching
`postgresql+psycopg` URL with a properly percent-encoded password in its userinfo,
and supply the original unencoded password to PostgreSQL. Missing or empty values
fail Compose interpolation. There is no published password or fallback in this
overlay. The proxy receives neither database URL nor database password.

Keep these interpolation values and the paths to the two service-specific private
files in a protected operator Compose environment file, outside the repository.
Do not commit any private file or collect expanded Compose configuration/container
environments as ordinary diagnostics. Protect all files with restrictive
permissions; host Docker administrators can inspect container environments and
are inside the deployment trust boundary.

After separate authorization for the destination, evidence and any real-provider
spend, an operator can start the optional deployment with:

```sh
docker compose --env-file /secure/provider-compose.env -p loose-thread-secured -f compose.yaml -f compose.provider.yaml --profile provider up --build
```

Use a fresh, separate Compose project/database containing only trusted accounts,
then ingest and approve the evidence intended for provider use. **Never activate a
real provider against a database that was exposed in demo mode.** Setting
`DEMO_MODE=false` does not revoke accounts, memberships or sessions created through
the demo's privileged setup routes. Existing production data requires an operator
review of its account and session provenance before activation. The example uses
a separate Compose project so its database/artifact volumes do not reuse the
ordinary demo stack. PostgreSQL initializes its password only for a fresh data
directory; changing an environment variable does not rotate an existing database
password. Do not reuse a volume initialized with the published demo credential.

The overlay requires authenticated production mode but is not a complete hardened
production deployment. Keep trusted ingress/TLS, database access, bootstrap and
account lifecycle under operator control. The provider worker independently checks
production mode and the active authenticated requester session and project
administrator role before execution. A worker factory or synthetic transport does
not exempt it from that gate. The default stack without this overlay remains the
unchanged, offline demo.

`ready` means validated metadata and a recent worker heartbeat bound to the same
configuration digest. It does **not** mean a DNS query, proxy tunnel, TLS exchange,
model invocation or model-quality evaluation succeeded. A missing/stale worker,
configuration mismatch or invalid settings prevent submission. Credentials stay
out of configuration projections, previews, jobs and ledger records. Endpoint
origin and model are disclosed for review; private endpoint paths stay out of the
public projection. API bodies cannot override endpoint, model, token or proxy.

### Egress gate

`failurelens.provider_proxy` uses only the Python standard library. It accepts
only an exact `CONNECT configured-host:443 HTTP/1.1` authority with a matching Host
header. Unknown hosts, ports, absolute URLs, userinfo, trailing dots, alternate
encodings, duplicate/forwarding/authentication/body headers and extra pipelined
bytes are denied. It is not a general forward proxy.

For every accepted tunnel, the gate resolves only the configured hostname and
rejects the entire answer if any address is nonpublic, private, loopback,
link-local, multicast, reserved, scoped, IPv4-mapped, 6to4, Teredo or a standard
NAT64 translation address. It connects to the validated numeric address without
another hostname lookup, preventing a DNS-rebinding gap. It makes one connection
attempt without destination failover. DNS workers have separate bounded permits;
a timed-out caller closes while a still-running resolver retains its permit, so
repeated timeouts cannot accumulate resolver threads.

The proxy caps active clients and DNS resolutions at two each, headers at 4 KiB,
header time at five seconds, each tunnel direction at 512 KiB, and total tunnel
time at 35 seconds. Application context/response/time/attempt limits remain
independent and usually tighter. Only fixed event names are logged; no authority,
address, headers, credentials, request bytes, response bytes or exception strings
are emitted. The CONNECT tunnel is opaque: the worker verifies TLS using the
normal certificate store, redirects remain disabled in the HTTP adapter, and the
proxy cannot inspect or rewrite HTTPS paths/headers. Both transports ignore
ambient proxy/header configuration; the application explicitly sets its proxy
and `trust_env=False`, retaining certificate verification.

### Credential-free fixture verification

Run the dedicated, disposable gate with:

```sh
bash scripts/compose_provider_smoke.sh --confirm-disposable-stack /tmp/provider-report
```

This script creates a separate disposable Compose project, sets production
authentication with synthetic bootstrap/user and database credentials plus secure
cookies, and overwrites all provider settings with reserved `.invalid` fixture values and a
fake canary token. Its trusted seeder explicitly creates synthetic users; anonymous
privileged account creation must fail. The fixture authenticates with bearer
sessions over its private loopback test connection. It mounts trusted fixture
scripts outside the
application image. Constructor-injected `httpx.MockTransport` supplies bounded
success/outage responses without any real provider request. A separate injected
socket-pair connector proves a real provider-worker-to-proxy Docker connection;
another listener uses real OS resolution of a loopback `/etc/hosts` fixture and
the production address validator to prove private-address denial. Production has
no environment/API option to enable these substitutions.

Before startup, the Docker gate verifies that actual Compose rejects missing and
empty database URL/password settings, using quiet validation that never emits
expanded credentials. It requires actual PostgreSQL, authenticated API submissions,
dedicated worker processing, one persisted attempt on duplicate replay, unchanged
deterministic product-risk decisions, unknown-cost semantics and sensitive-canary
exclusion. It inspects actual container network membership, database overrides and credential
isolation,
then checks Internet denial from API and both workers, direct-IP and hostname
proxy denial from API/ordinary worker, and proxy reachability only from the
provider worker. Ordinary ingestion and core readiness must survive the optional
services being enabled or stopped. The original default recovery/Internet-denial
gate remains unchanged and separately required.

`.github/workflows/provider-boundary.yml` pins actions, uses read-only repository
permissions, retains failure evidence, and runs this synthetic-only Docker gate.
It does not request secrets, dispatch another workflow, invoke npm audit or make
model-quality claims. Unit tests cover authority tricks, mixed private/public DNS,
rebind pinning, IPv6 translation addresses, socket deadlines, held DNS permits,
byte limits, and fixed-log canary exclusion. The fixture's API/worker logic also
runs with independent SQLite sessions locally; that result is not PostgreSQL or
Docker evidence.

No real model, credential, paid request or external provider benchmark was used.
Exact-source Docker/PostgreSQL CI remains required where local capabilities are
absent. Real-provider connectivity, pricing accuracy, quality evaluation and
production deployment acceptance remain unfinished and separately authorized.
