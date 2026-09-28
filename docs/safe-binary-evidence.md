# M2.1 — Producer-verified safe binary evidence

This is a scoped M2 implementation, not completion of the entire master prompt.
The deterministic analyzer, five-category policy and conservative completeness
rules are unchanged. Real LedgerGuard evaluation remains a separate M6 gap.

## Executed M2.1 acceptance

The scoped requirements mapped below passed at source
`a2e4be3e30bfb49e60f949e9ef2f52b2cdee545f` in
[CI run 36475782858](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36475782858)
on September 28, 2026. All nine jobs passed: 241 PostgreSQL/backend tests,
84.93% branch-aware coverage, 16 actual-producer contracts, 35 browser cases
(11 in each desktop engine and two in narrow Chromium), frontend verification,
five deterministic harnesses and Docker configuration/builds. The 16 producer
contracts are also included in the backend suite; the counts are not additive.
The existing 31 browser cases and all their assertions remain enabled.

Actual approved/masked-evidence screenshots were inspected from both the desktop
and narrow artifacts of that run. See [the delivery ledger](PROGRESS.md) for
separate local checks, superseded failure/fix history and remaining scope. This
records the accepted source, not an unexecuted future documentation commit.

## Screenshot lifecycle

PNG/JPEG uploads are decoded, not merely accepted from their headers. A separate
codec subprocess uses Pillow 12.3.0, an eight-second CPU limit, a 12-second parent
wall-clock deadline, a 768 MiB address-space limit on Linux, and at most two codec
processes per application process. Existing upload and 25-megapixel limits still
apply. Animated/multi-frame inputs are rejected. The subprocess never follows
artifact paths or URLs, loads models, or prints native decoder exceptions.
These are bounded codec controls, not an OS sandbox or a global request-rate limit.

The original stays restricted. A reviewer selects their exact original local file;
the browser checks its SHA-256 and size before displaying a local canvas. The server
independently repeats both checks and validation at submission. Pixel masks use
orientation-normalized, full-resolution integer coordinates. The server burns
opaque rectangles into a newly encoded RGB PNG, flattens alpha, and discards image
metadata. A CSS overlay is not a redaction and is never used as the saved result.
An explicit human safety attestation is required even when no masks are drawn.

Every review creates a new immutable derivative, source digest, mask/source map,
review revision and attributed decision. Reapproval cannot overwrite cited bytes
or reopen a revoked historical URL. Revoke/reject closes every derivative belonging
to the specific validated binary input, including trace-event derivatives. Missing
or rejected inputs cannot revoke a parent bundle's unrelated safe evidence.

Approval does not change a restricted required input to accepted, and does not
silently mark a partial run complete. Source completeness and availability of a
reviewed derivative are deliberately separate facts.

## No retained-original download profile

This implementation chooses **no retained binary originals**, rather than adding
an unconfigured encryption scheme. Successfully processed uploads containing
binary inputs are marked source-expired and scheduled in the existing transactional
deletion outbox. The worker removes bytes after active shared consumers finish;
maintenance sweeps retry pending deletions. Metadata, digests and safe derivatives
remain. Replaying an expired ingestion cannot recreate an untracked raw copy.

Raw uploads still require bounded private staging while queued/processing. A failed
or interrupted ingestion follows the existing restricted-source retention/recovery
policy; this checkpoint does not claim instantaneous crash cleanup or encryption
of every transient staging byte. Encryption/key management for a deliberately
retained-original profile is **not provided**. Do not configure long-lived original
retention on the assumption that such encryption exists. Operators must protect the
artifact volume and its backups and use the documented lifecycle controls.

The review submission is processed in memory and the codec subprocess, not saved
as another raw file. A reviewer without the original must obtain it through their
existing controlled workflow; FailureLens does not return an unsanitized original.
Revocation cannot retract a file an authorized person already downloaded.

## Supported Playwright trace contract

`playwright-safe-index-v2` accepts trace schema **9** from pinned Playwright **1.63.0**.
Every `.trace` stream must declare a supported context header. Missing, malformed,
conflicting and unsupported declarations fail explicitly. Arbitrary producer
versions are not treated as compatible because their first few fields look similar.

The parser validates all event JSON within its stated limits, then retains at most
256 eligible safe events. It allows at most 20 event streams, 50,000 source events,
one megabyte per event, the existing archive/file/ratio bounds and ten seconds of
index processing. Truncation is explicit: total validated events, indexed events,
omitted eligible events, full error counts and stream digests are distinct fields.

Only bounded, sanitized action names/IDs/times, errors, console messages, and
network method/URL/status/timing are extracted. Action parameters, arbitrary object
serialization, scripts, DOM snapshots, request/response headers and bodies, resource
pixels and resource names are not copied into the approved event index. Unsupported
resource content stays absent rather than being relabeled safe.

Each event carries original archive ordinal, entry name, line, entry SHA-256,
source SHA-256, immutable safe-event derivative and evidence ID. JSON pointers
identify exact locations in the aggregate safe index. Trace evidence is labeled
`supplemental_trace` and excluded from the classifier's test-outcome evidence pool:
a trace event is not a fabricated test execution or independent proof of root cause.

Attachment association requires one exact report attachment path, constrained by
any supplied test/browser/attempt dimensions, or a unique explicit identity tuple.
Ambiguous/unassociated inputs stay visibly unassociated. Basenames are not guessed.

### Trace-text policy and upgrade guidance

M2.1.1 records `trace-safe-text-v2.1` in each new trace summary and event source
locator. The index schema remains `playwright-safe-index-v2`; the text policy is
versioned separately so already-cited bytes are not silently reinterpreted.

The complete bounded event field is stripped of terminal controls and redacted
**before** the display limit is applied. Incomplete private-key blocks withhold
the remaining suffix. Safe clipping adds an explicit `[TRUNCATED]` marker. This
prevents removing a key's end marker, or splitting an email, before redaction.
Unknown event types contribute to an `unknown` count and an omission warning,
never artifact-controlled unsanitized keys in approved metadata. HTTP(S) URLs
remove user information, query values and fragments; invalid authorities/ports,
excessive query fields and unsupported schemes produce `[URL OMITTED]`, with no
fallback to raw URL text. Method, route, status and timing remain available where
safe and supported. These are bounded policy controls, not universal PII removal.

**Upgrade:** earlier derivatives without `trace-safe-text-v2.1` are not made safe
retroactively. Before exposing pre-hardening trace evidence, use the existing
reviewer revoke action on the affected trace input (which closes aggregate and
individual event derivatives), then ingest the exact local source in a new run
with a new external ID. Reusing the original ingestion identity deliberately
replays the old immutable result. Do not edit derivative bytes or digests in
place. Revocation closes content URLs, not all previously stored run metadata.
Review pre-hardening run-input metadata too; use the existing run-evidence expiry
workflow where that metadata must be removed. Apply operator review to exports
and backups. This patch cannot recall downloaded copies and does not perform a
bulk data migration.

`backend/tests/test_trace_safety.py` includes 12 regressions for complete and
incomplete key blocks, clipping boundaries, unknown types, malformed/excessive/
active-scheme URLs and the durable worker-to-authorized-content path. Canaries are
synthetic. The original version failed 11 of these cases; all 12 pass after the
fix. Existing binary, producer and browser checks remain enabled. Exact current
execution evidence is recorded in `PROGRESS.md`.

### Local inspection

```bash
failurelens trace-inspect path/to/trace.zip --sha256 <recorded-original-sha256>
```

This command checks bounded local bytes, digest, archive safety and supported
producer format **before any database initialization**. It prints a viewer argument
array and warnings. It never installs software, launches a viewer or fetches URLs.
Use an isolated local workspace with Playwright 1.63.0 already installed and
network disabled. Original DOM/network/image content is unsanitized; never serve
the trace viewer or artifact HTML from the authenticated FailureLens origin.

## API contract

- `GET /api/v1/runs/{run_id}/binary-evidence?offset=0&limit=25` returns scoped input
  states. Expired runs can still list their tombstone/metadata states.
- `GET /api/v1/binary-evidence/{input_id}?decision_offset=0` returns input identity,
  derivative metadata and at most 20 decisions. Expired evidence returns HTTP 410.
- `POST /api/v1/binary-evidence/{input_id}/screenshot-reviews` requires reviewer
  access and `Content-Type: application/vnd.failurelens.image-review`. The body is
  one UTF-8 JSON line (at most 16 KiB), newline, then exact original PNG/JPEG bytes.
  Metadata: `expected_version`, `reason` (10–1000 characters), `confirm_safe: true`,
  and `masks` (at most 64 integer `{x,y,width,height}` rectangles). No reason or
  raw bytes are placed in URLs. The receive deadline is 30 seconds. HTTP 201
  returns the new immutable derivative; a stale revision or wrong digest is 409.
- `POST /api/v1/binary-evidence/{input_id}/decisions` accepts `expected_version`,
  `decision: reject|revoke`, and `reason`. Server-derived actors and optimistic
  revisions are enforced under project/input locks, including PostgreSQL contention.
- `GET /api/v1/binary-evidence/{input_id}/trace-events?offset=0&limit=25` returns a
  page from the digest-verified, approved safe index, with exact source locations.
- `GET /api/v1/artifact-derivatives/{id}/content` serves approved, digest-verified
  content only. `preview=true` produces a bounded image thumbnail;
  `download=true` sets attachment disposition. Single byte ranges are supported;
  multi-range/invalid/unsatisfiable requests return 416. Every read checks ownership,
  source identity, derivative approval, private storage namespace, bytes and expiry.
  Responses use `nosniff`, private/no-store, same-origin resource policy and a
  restrictive sandbox CSP. No public or signed original URL is returned.
- `POST /api/v1/image-comparisons` accepts `expected_derivative_id` and
  `actual_derivative_id`. Only current approved images from the same explicitly
  associated execution and run are eligible. Browser, OS, viewport width/height,
  device scale and comparison group must be present, typed and compatible.
  `dhash-64-v1` returns advisory similarity/Hamming distance, or explicit
  `INSUFFICIENT_CONTEXT`/`INCOMPATIBLE`, never a root-cause verdict. Masks can increase
  apparent similarity. Caller-supplied comparison metadata remains self-reported.

Viewer roles may inspect approved content; reviewers/administrators may decide.
Ingestion-only credentials cannot read or review evidence. Cross-project guessed
IDs return not-found. Metadata alone never grants access. The dashboard preserves
project/run/input/event links, pagination, role-aware controls, local draft revision,
loading/error/restricted/revoked/expired states and narrow-screen access.

## Actual producer fixtures

`integrations/producer-fixtures/run.py` runs pinned Playwright, pytest-json-report,
JUnit/REST Assured and k6 against a disposable loopback-only test server. Deliberate
nonzero producer exits are accepted only after independent outcome assertions:
Playwright pass/fail/retry/skip, Pytest pass/fail/skip/xfail/parameterization, observed
Java HTTP 200/503, and k6's six actual requests plus failed availability threshold.
The outputs include actual JSON/JUnit, HAR/network derivatives, console output,
paired screenshots, trace archives, a manifest-2.0 bundle, and current Git metadata.
No second banking application, paid provider or companion-repository mutation is used.

```bash
python -m pip install './backend[dev]' pytest==9.0.2 pytest-json-report==1.5.0
(cd frontend && npm ci && npx playwright install --with-deps chromium)
# Java 17, Maven and Docker are also required for the full producer set.
python integrations/producer-fixtures/run.py --output /tmp/failurelens-producer-fixtures
FAILURELENS_PRODUCER_FIXTURES=/tmp/failurelens-producer-fixtures \
  python -m pytest backend/tests/test_producer_contracts.py
```

The output directory must be empty. The provenance manifest records commands,
actual exit codes, source revision, workflow execution, producer versions, resolved
k6 image digest, oracles and SHA-256/size for every retained output. All contacts,
tokens and faults are synthetic fixture data; their **execution is real**. Origin
is `other_executed`, with **zero LedgerGuard executions**, not fabricated M6 provenance.

The CI producer job creates and validates these fixtures, retains the exact-revision
artifact for 30 days, and supplies it to backend and all four browser lanes. Missing
fixtures fail acceptance instead of skipping tests. Browser tests execute the real
upload/worker/review/compare/trace/revoke/retention journey, including narrow layout,
and capture actual approved-evidence screenshots. Artifact expiry at the hosting
service is distinct from the application's retention behavior.

## Requirement-to-evidence map

| ID | Implementation | Regression/acceptance evidence |
|---|---|---|
| M2.1-IMAGE-DECODE | `image_codec.py`, `image_worker.py`, `ingestion.py` | `test_header_only_rasters_are_rejected`, image bounds/orientation/alpha tests |
| M2.1-IMAGE-REVIEW | `binary_evidence.py`, `binary_schemas.py`, new migration | Actual pixel/metadata assertions, source digest mismatch, stale revision, immutable reapproval and revocation tests |
| M2.1-TRACE | `trace_evidence.py`, `register_binary_inputs` | Unsupported declarations, bounded/full counts, actual producer entry digest/line checks |
| M2.1.1-TRACE-TEXT | `trace_evidence.py`, policy `trace-safe-text-v2.1` | `test_trace_safety.py`: redaction-before-clipping, unknown type keys, fail-closed URLs, durable authorized serving |
| M2.1-SCOPE | `binary_api.py`, `read_derivative`, `_correlate` | Guessed IDs, viewer mutation denial, missing-input sibling protection, ambiguous association tests |
| M2.1-RETENTION | Existing deletion outbox and `retention.py` extension | Original discard, idempotent replay, derivative 410, decision/mask erasure, worker browser journey |
| M2.1-CONCURRENCY | Project/input row locks, decision uniqueness | PostgreSQL two-reviewer race: one 201 and one 409; expiry prevents reapproval |
| M2.1-COMPARE | `compare_images` | Same-execution constraint; environment mismatch and insufficient-context tests; no automatic classification |
| M2.1-UI | `BinaryEvidence.tsx`, typed client | Client contract tests and real API-backed desktop/narrow journey with reloadable event link |
| M2.1-PRODUCERS | `integrations/producer-fixtures`, CI producer job | Actual versions/commands/oracles/digests and `test_producer_contracts.py` |

Execution results and exact delivered SHA belong in `PROGRESS.md`; the existence of
these tests or this matrix is not itself proof that a remote checkpoint passed.
Remaining full-M2 work includes broader producer/dialect edge coverage, richer
application-specific sensitive-field policy and any separately authorized encrypted
retained-original profile. Full M5, M6 real LedgerGuard execution, M7–M10 and final
master acceptance remain independently tracked, not silently declared finished.
