# Loose Thread delivery ledger

## M6.4.1 closeout — verified 2026-09-29

Canonical repository: `azerish25-ux/ai-quality-intelligence`; delivery branch: `main`.
Verified implementation source: `1381cfafb0d67f129d2e5ae12f6cd1315a2a8d02`,
tree `a178a04d67bd43da570624ec4c57d0539d1f166b`.

**The clean-source CI repair and scoped transaction-finality delivery are verified.
Full M6 and the complete master project remain PARTIAL.** A later documentation
commit does not change the source named by these measurements and needs its own CI.

The preceding ledger is preserved byte-for-byte in
[PROGRESS-through-M6.4.1.md](https://github.com/azerish25-ux/ai-quality-intelligence/blob/2de918e5709d12afba2e415edd3c020fac83ed7c/docs/PROGRESS-through-M6.4.1.md), original blob
`4921e06d9a3c611b353bb35ee179365d2a499dd7`. Its local-only, blocked and NOT RUN
statements describe their original checkpoints, not the subsequent delivery below.
Earlier archived ledgers, frozen corpora, labels, thresholds and reports are unchanged.

### Implemented and published

- `aca0d1a2cea056ba2b07c7f67c45f4df304ebf27`: ordinary backend CI uses
  `scripts/install_committed_backend.sh`. It installs a Git archive of the exact
  commit outside the measured checkout, refuses uncommitted source and checks
  source cleanliness and unchanged HEAD after installation. No broad ignore rule
  or integrity exemption was added. Campaign provenance now includes changed paths.
- `9b68283d1e5e32115e76ab1a45c3efe5310089d4`: explicitly installs the existing
  setuptools build backend in the development environment for real offline
  package-build regressions. Runtime dependencies and coverage gates are unchanged.
- `1381cfafb0d67f129d2e5ae12f6cd1315a2a8d02`: retains actual PostgreSQL evidence,
  adds bounded independent snapshot verification/export, and names failed integrity
  gates together with source changes in the finality replay regression.

There are **42 new tests**: 25 real-build/source-provenance regressions and 17
retention/oracle/scope regressions. Modified, staged, deleted and untracked measured
source remain detectable. Corrupted artifacts, fabricated PASS flags, false
held-out claims and overwritten export destinations are rejected.

### Exact-source verification

At `1381cfafb0d67f129d2e5ae12f6cd1315a2a8d02`:

| Verification | Actual result and evidence |
|---|---|
| Ordinary CI | All ten jobs passed in [36575299066](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36575299066): backend, producer fixtures, frontend, legacy evaluation, component execution/evidence integrity, Docker validation/builds and four browser lanes. |
| Backend PostgreSQL suite | **881 passed, zero failed or skipped**, one deprecation warning; **86.13% branch-aware coverage**, unchanged 75% gate. [Job 109429887731](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36575299066/job/109429887731). The log confirms installation leaves the measured source clean. |
| Actual finality execution | [36575299122](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36575299122), job `109429246401`, passed actual HTTP/PostgreSQL controls/interventions, API/durable-worker replay, independent scoring and desktop/narrow journeys. |
| Campaign execution | [36575299051](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36575299051) passed its existing integrity/safety and API-backed browser checks. This is not a waiver of quality targets. |
| Frozen benchmark | [36575298977](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36575298977) **FAILED the unchanged quality-target step** after passing replay, integrity scoring and desktop/narrow browser verification. No thresholds or cases were altered to turn it green. |
| Local targeted verification | 90 selected finality/provenance/retention tests passed on the clean exact source. This includes 48 existing tests plus 42 new tests; local SQLite replay is not local PostgreSQL execution. |

The fresh finality report was downloaded and its artifact SHA-256 verified:
`a9fca10b57753681097c8de0cc50761dcd199bdd7752b76259a26585719980e1`
(artifact `11037146300`). It reports eight cases, four executed fault/control pairs,
one mechanism, four synthetic insufficient cases, four supported published claims,
twelve valid citations and five repeated analyses. All integrity gates pass;
five-category macro F1 is undefined and full corpus minimums fail.

Browser artifact `11036906385` was checksum-verified
(`365d80c53832936dfa4f3baf552e3e94c7ffc7f48ce624c3328d240ab3a3e78f`).
Representative desktop/narrow diagnostic captures were visually inspected, including
violated and missing-observation states. Their text retains the investigation and
non-reassurance boundary. These are actual captured diagnostic regions, not a claim
that a new whole-dashboard visual audit was performed.

### Preserved failures and their resolution

At `b7327b4`, backend CI reported 838 passed and one failure because in-place
packaging created untracked `backend/src/failurelens.egg-info/`. The clean-source
integrity gate correctly rejected that measured checkout. The isolated archive
installation fixes the cause rather than bypassing the check.

The first repair run at `aca0d1a`, [36573002193](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36573002193),
passed the original finality regression but exposed two new offline build tests
without setuptools in the clean Python 3.13 test environment (862 passed, two
failed). The explicit development dependency fixed that prerequisite. Backend job
`109425649445` at `9b68283`, run `36574064400`, then passed; all 881 tests passed at
`1381cfa`. No tests were skipped or assertions weakened to resolve these failures.

### Permanent original execution evidence

The first successful actual finality execution belongs to
`b7327b437d8fc4cb009918d1d4d31b6bf36f508a`,
[run 36567980376](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36567980376),
job `109404555847`. It is retained independently of the expiring CI artifact in
[transaction-finality-postgresql-v1](../evaluation/reports/transaction-finality-postgresql-v1/README.md).

All 48 original artifact member bodies are preserved byte-for-byte, including
public inputs, safe derivatives, predictions, exact report/metrics, independent
SQL/receipt oracles and diagnostic-gap audit. Metadata records the original
artifact digest, each retained file digest and the documented lossless repack.
The earlier all-synthetic SQLite snapshot remains separate and unchanged.

```sh
python evaluation/verify_finality_snapshot.py
python evaluation/verify_finality_snapshot.py --extract-to /tmp/finality-retained
```

The export destination must not exist. Both commands verify bounded archive
extraction, exact digests, independent rescoring and recomputed paired oracles.
They do **not** claim fresh Java, Docker, PostgreSQL or browser execution.

### Remaining boundary

The experiment injects a controlled JDBC early commit in disposable copies of a
pinned companion, not a defect in unmodified LedgerGuard or PostgreSQL. Four amount
variants remain one mechanism. Labels are agent-reviewed, not independently blinded
or expert-adjudicated. The companion repository was not modified or published to.

No new held-out acceptance is claimed. Broader diagnostic coverage, genuinely new
held-out families, a complete temporal/adversarial program, remaining M2/M5 scope,
optional-provider boundaries, full GitHub publication, operational hardening and
final audit remain unfinished. Continue from the actual failures using the existing
diagnostic-gap audit; do not reimplement the delivered finality relation or overwrite
historical reports. See [requirements-matrix.md](requirements-matrix.md) and
[transaction-finality.md](transaction-finality.md).

## M8 publication foundation — 2026-09-30

Starting source `af7a041`. Added an opt-in CLI GitHub publisher with exact-SHA,
trusted PR lookup, bot-owned project markers, bounded pagination, idempotent
reconciliation, safe stale-head replacement and sanitized operational failures.
The ingestion path remains secret-free and does not automatically publish.
Empty analysis reports now require review, and untrusted Markdown metadata is escaped.
See [publication contract](github-publication.md) for tests and remaining scope.
Frozen evaluation files, labels and thresholds are unchanged. This is not M8 or
full-project completion; live publication and complete report/workflow scope remain.

### M8 read-only projection

Added project-authorized API preview and a shared versioned JSON/Markdown projection.
Outcome denominators collapse retries; only the latest analysis per failure is
reported. Unvalidated legacy summaries and expired evidence are withheld; links,
images, mentions and declared secrets in metadata are neutralized. Five new API/data
regressions and a Markdown injection regression pass locally. The preceding publisher
batch is remotely delivered as `c3d98983c4e69fe66a3b640c5602bcce7df6489d` (tree
`884308c01c606e78c0d1db6674255c3361d74087`), with all seven workflows actually triggered.
A local complete suite attempt cannot substitute for CI: real producer fixtures were
not generated locally (16 explicit failures), and four PostgreSQL cases skipped.
No gate was removed. Exact-source CI results remain pending at this checkpoint.

## M7 optional-provider boundary foundation — 2026-09-30

Implemented an explicitly disabled-by-default HTTP proposal adapter and a DB-backed
bridge selecting independently revalidated safe evidence. Deterministic analysis is
never replaced. Bounded transport, cancellation, budgets, circuit failure handling,
unknown-cost semantics, proposal schema/citations and product-risk downgrade gates
are covered by transport fixtures. No paid or real-model request was made. Persistent
invocation/budget/UI scope remains open; see [provider contract](optional-provider.md).
Previous report-preview batch delivered to main as `9d8a5b93326fdeb8569554e73ea3b080ac0e7fd8`.
All ten ordinary CI jobs at preceding `c3d9898` passed in run `36652899198`.
This statement does not certify later source, and frozen benchmark failure is retained.

### Executed M7 foundation and M8 dashboard work

At local provider commit `fb4e09d`, the full backend suite using checksum-verified
real producer exports from CI `36653389182` completed: **944 passed, four
PostgreSQL-only skips**, 83.78% branch-aware coverage against the unchanged 75%
existing gate. This was a SQLite run with real exported artifacts, not a local
PostgreSQL or fresh producer execution. Thirty-three provider/bridge tests pass;
no real model ran. Publishing this batch encountered an authorization-evidence
review block after the preceding two accepted publications; no bypass attempted.

The remotely delivered `9d8a5b9` passed all ten ordinary CI jobs in run
[36653389182](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36653389182).
The frozen benchmark workflow still fails its unchanged quality targets. Desktop
browser artifact `11071502407` was downloaded and SHA-256 checked as
`d40eefb8777d382daca0ad4de5f8e3c7f5fefb6b2082d600cc9b39998b10bc1d`;
the actual full-dashboard capture was inspected. These screenshots predate the
new report panel and must not be used to certify it.

The dashboard now exposes the selected run's read-only advisory report with explicit
completeness/digest, inert sanitized text, cancellation when changing runs and a
Markdown download. Visible branding is Loose Thread; package names, MIME types and
compatibility interfaces retain `failurelens`. Local type/build passes and **48
frontend unit tests pass**. A real API/browser report/download regression is added;
its execution is pending publication/CI. The cloud browser rejected local-loopback
navigation (`ERR_BLOCKED_BY_CLIENT`); no browser restriction was bypassed.

### Additional safety regressions

Forty normalized-input injection combinations passed through the real ingestion and
analysis path with network/process/shell/GitHub mutation spies and a protected source
sentinel. They are regression combinations, not newly independent evaluation cases.
Report preview now independently rechecks current derivative scope/digests/restriction
before exposing a previously validated analysis; a new post-analysis restriction test
passes. Full adversarial and production isolation claims remain intentionally absent.

### M9 isolated runtime/recovery gate prepared

Inspection found the dashboard's Compose port exposed on all interfaces despite
its documented loopback demo contract. It is corrected to `127.0.0.1:8080` and the
runtime service network is internal. Added an actual Docker smoke gate for synthetic
startup, denied Internet egress, restart persistence and PostgreSQL/artifact restore
with real evidence validation. Shell syntax checked locally; Docker is unavailable
here, so actual execution is pending authorized publication and the CI Docker job.
No local Docker pass is claimed.

### Synthetic history and complete walkthrough seed

Added explicit demo-only `failurelens demo-history`: a separate idempotent 100-run,
1,000-logical-observation history with retries, browser/branch/worker variation,
incomplete runs and skipped/cancelled outcomes. The final persisted run demonstrates
product defect, qualifying reviewed known flake and honest abstention. Two tests pass,
including rerun idempotence and production rejection. An initial fixture failed its
known-flake expectation because worker cohorts differed; corrected the synthetic
fixture rather than weakening the history gate. This is not new benchmark evidence.

### Reproducible dependency graph

Generated a PyPI-backed uv lock and hash-checked pip export using actual installed
uv 0.12.19; the export installed successfully. Bootstrap and the committed-source
backend installer now consume the locked graph while retaining source-cleanliness
checks. A full test rerun on the resolved graph is pending below; producer-specific
versions and frozen evaluation bytes remain unchanged.

Locked-graph targeted verification: 64 source-provenance, report and provider tests
pass with `PYTHONPATH=backend/src:.`. An initial focused invocation omitted the repo
root from PYTHONPATH and could not import the existing `evaluation` package; fixing
the invocation resolved collection without altering any test assertion.

## Recoverable execution checkpoint — 2026-09-30

Measured local implementation source: `546ecf8b48f57ab4e7adf2943282e1a9760681c4`.
On the hash-locked Python graph, the full local backend run completed with **987
passed, four PostgreSQL-only skips, one deprecation warning and 83.85% branch-aware
coverage**, preserving the 75% existing gate. Command:

```sh
FAILURELENS_PRODUCER_FIXTURES=/tmp/loose-ci-producers PYTHONPATH=backend/src:. \
  python -m pytest backend/tests --cov=failurelens --cov-branch --cov-report=term --cov-fail-under=75
```

Producer bytes came from checksum-verified actual CI exports at `9d8a5b9`; this run
is not fresh local producer/PostgreSQL execution. Local frontend type/build and 48
unit tests passed. New report browser journey and Docker recovery gate remain NOT RUN
until publication/CI. The last remotely verified source is `9d8a5b9`, ordinary CI
`36653389182` with all ten jobs passing; its frozen benchmark remains FAIL.

Source publication of the provider batch was rejected for missing visible
repo-specific user authorization evidence. It was not bypassed or blindly retried.
Subsequent implementation is committed locally, awaiting the exact authorization
transcript needed for a single permitted retry. The working tree is clean at this
checkpoint. No live PR exists in the target repository, so live bot publication was
not attempted and no artificial PR was created.

Full master-prompt acceptance remains incomplete: failed frozen quality targets and
new held-out validation, wider producer/adversarial/temporal breadth, complete rich
GitHub publication/workflow/live target, durable model invocation/budget/UI integration,
full telemetry/load/operational acceptance and final portfolio verification remain.
The new regression counts and synthetic history do not increase evaluation denominators.

### Publisher safety review and blocked delivery recheck

A resumed delivery attempt accepted the previously blocked evidence-bridge blob,
but the following provider-module upload was rejected for missing trusted approval.
Its single authorized retry was also rejected. No branch update or alternative write
route was attempted; remote main remains `9d8a5b9`. Direct authorization is required
before publication can continue.

Independent local review found two publisher boundary gaps: the response-size limit
was applied after response buffering, and the actual receipt author was not checked.
The client now enforces the limit while streaming and validates the returned bot
identity. Two new regressions plus the existing publisher/report-snapshot tests pass
(**36 tests**). A receipt-author mismatch requires inspecting the written comment;
the publisher never blindly retries it.

### Delivered backlog and first real recovery-gate result

All eight pending commits were delivered to main at
`d1226b509c629d35a26c0d498a7e791c8b0b7bad`, exact tree
`c06c2e2833b7c5551603e1777000fdcde41049a7`, following explicit owner approval.
Remote reread and local reconciliation match; none of that implementation remains
local-only. Its seven workflows actually started. Latest prepublication local suite:
989 passed, four PostgreSQL-only skips, 83.88% coverage.

The new Docker recovery job exposed a genuine network-topology defect: the internal
network blocked runtime Internet as intended but also prevented the host from
reaching directly published service ports. The job correctly failed (exit 7); it
was not waived. The repair puts only the fixed-route Nginx gateway on a separate
edge network, publishing both loopback entry points through it. API, worker and DB
remain internal-only, and the original outbound-denial assertion remains mandatory.
Failure cleanup now prints bounded logs for diagnosis. Restore execution remains
pending until this repaired source passes its actual Docker job.

### Narrow report layout regression

The first exact-source diagnostic/campaign/full-stack browser runs caught horizontal
page overflow on narrow screens. The new report's 64-character digest was unbroken
outside its wrapped preview region. Applied scoped wrapping to report metadata and
flexible panel controls, and added a dedicated real narrow-browser regression for
both collapsed and expanded report text. Original viewport assertions remain intact;
no test was skipped or weakened. Fresh browser execution is required for this repair.

The repaired Docker topology at `60020f9` passed actual gateway ingress, blocked
backend Internet, restart persistence and PostgreSQL dump/restore. It then exposed
an import-order error in the artifact restore verifier: application imports created
the destination before its deliberate fresh-directory assertion. Moved application
imports after bounded extraction, preserving refusal to overwrite an existing
destination. Added an ordering regression; the full restore gate must run again.

### Runtime image hardening

The backend image now consumes the hash-locked runtime-only dependency export from
the same uv graph. Switched the gateway to the official unprivileged Nginx variant
and added actual non-root UID assertions for all three application containers in
the Docker smoke gate. Local topology/source regressions pass; runtime image and
UID claims remain subject to actual CI execution.

### Operational acceptance measurement added

Added a strict actual-PostgreSQL HTTP read benchmark for 1,000 synthetic runs /
50,000 persisted executions at concurrency ten, with cold/warm timing, per-request
outcomes, actual hardware/source metadata and retained failure reports. It preserves
the original <500 ms p95 target and requires zero failed requests. Two local harness
regressions pass; actual performance is NOT RUN until the dedicated workflow executes.
This workload does not alter the classification corpus or evaluation denominator.

### First operational measurement and evidence-preserving optimization

The actual PostgreSQL load workflow at `4385f69`, run `36677790715`, completed 200
requests at concurrency ten over 50,000 executions with zero request failures, but
**p95 2,805.73 ms fails the unchanged 500 ms target**. The downloaded artifact's
SHA-256 was verified; original metrics/requests are retained in
`evaluation/reports/operational-4385f69-failed/`. Four logical runner CPUs are reported;
no reference-hardware normalization or whole-stack memory claim is made.

Inspection found the history API recomputed the same full history for infrastructure
correlations in the same request and eagerly reloaded already selected run objects.
It now reuses only a complete same-scope request-local history, checks logical scope,
cutoff/cohorts and completeness, and paginates only the returned observations. There
is no cross-request cache or stale authorization reuse. Thirty-two relevant history,
correlation and reuse tests pass, including unchanged full denominators and rejection
of cross-scope/incomplete inputs. The workload, target and original failed report are
unchanged; actual performance improvement still requires the next measured run.

Real desktop and narrow report-panel screenshots at verified source `3a9a89a` were
checksum-verified and visually inspected, then added to README with exact capture
provenance. They contain only the controlled synthetic demo.

The next actual PostgreSQL run at `e3fbd05` measured p95 **1,022.13 ms**, still failing
500 ms despite zero request failures. Its original metrics/requests are retained,
checksum-verified, beside the first failure. The harness, concurrency, workload and
threshold are unchanged. Profiling identified remaining hydration of unused ORM/JSON
fields. History now uses typed scalar projections; event-free correlation checks only
run existence rather than fetching unused run metadata. Existing cohort/cutoff limits
and all statistical denominators remain unchanged, with a query regression guarding
against reintroducing large unused JSON reads. Actual acceptance requires remeasurement.

The scalar-projection measurement at `c3fbf79` reached **566.09 ms p95**, still above
500 ms, with zero failed requests. Original third-run metrics/requests were downloaded,
checksum-verified and retained; no target was rounded down or waived. Further work
adds a semantics-preserving single-observation aggregation fast path and makes the
PostgreSQL pool explicit/bounded at the declared concurrency (10 retained + 10 overflow
per process). Forty-one focused tests pass, including every valid/unknown outcome,
SQLite compatibility and configuration bounds. The benchmark now records pool
configuration; its workload and threshold are unchanged. Actual remeasurement remains
required before claiming the performance target passed.

The pool-refinement upload encountered a credential-shaped example URL in the
previous `.env.example`. Replaced that line with credential-free environment guidance
before publication; Compose's isolated demo configuration remains unchanged. This
safer payload avoids transmitting a username/password URL in the updated example.

### Operational read target passed on actual PostgreSQL

At `845f53d`, workflow `36681098079`, job `109776505720`, the unchanged 50,000-execution
workload completed 200 warm requests at concurrency ten with **zero failures and
312.37 ms p95**, passing the original <500 ms target. Artifact `11081444531` was
checksum-verified and its original metrics/requests retained byte-for-byte under
`evaluation/reports/operational-845f53d-passed/`. The fixture is all-passing history
with no failure/analysis records, not mixed failure-heavy performance; runner hardware
is reported, not normalized, and this is not an SLA. All three earlier failures remain.
Frozen classifier quality is unaffected and remains a separate failed acceptance gate.

All ten ordinary CI jobs at the same `845f53d` source passed in
[36681098018](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36681098018):
PostgreSQL backend, actual producers, frontend, legacy evaluation, executed component
integrity, all four browser lanes and the Docker non-root/offline/recovery gate.
This scoped verification is not full-project or classifier-quality completion.

### Bounded tracing and current load evidence

The docs-only `78b45dd` source passed all ordinary CI but failed the read target at
572.62 ms in workflow `36681988614`. Its checksum-verified artifact is retained.
Runtime/workload match the earlier 312.37 ms pass; stable acceptance is unproven.
CPU/quota/load and bounded server-stage diagnostics are added without relaxing gates.

Manual OTel spans, durable traceparent propagation, redacted structured logging,
admin-only process metrics and explicitly enabled bounded OTLP transport are
implemented. A real loopback receiver caught environment-header inheritance in
the stock exporter; the explicit transport prevents it. No external collector,
paid model or live GitHub comment was used. See `telemetry.md` for scope and limits.

Resumed review found missing telemetry lifecycle cleanup, missing unhandled-500
accounting and a slow-header response able to exceed the nominal network timeout.
Added shared shutdown/export deadlines, one in-flight transport limit, graceful
worker SIGTERM, explicit span-specific limits and fixed-cardinality result counters.
Focused loopback, durable-context and privacy regressions cover these discoveries.
The earlier dirty-source full suite correctly failed its clean-source integrity
gate (1 failed, 1,024 passed, four PostgreSQL-only skips); it was not waived.

Added an explicit isolated local Jaeger collector/viewer profile and a real Docker
CI check for PostgreSQL-backed ingestion, API/worker trace continuity, sensitive
canary absence, viewer ingress, denied runtime Internet and collector outage.
Local shell/YAML/topology checks pass; actual collector execution is pending CI.
Performance diagnostics preserve completed load evidence even if the separate
metrics endpoint is unavailable. Frozen evaluation labels and thresholds are unchanged.

Telemetry source `8dbce9b327d943d85a1fce7d77d190853b8f2951` is published and its
remote tree matches `6fff5a599213786e64777b58e1bdcc6906f3b6c2`. Clean local
verification passed **1,049 tests, four PostgreSQL-only skips, 84.65% branch-aware
coverage**; the skips are not PostgreSQL acceptance. All nine workflows started.

The first actual local-collector CI run, `36687238268`, successfully executed the
PostgreSQL/API/worker trace and verified canary absence. It then failed the viewer
service-list probe because Jaeger 2.21 removed the internal `/api/services` route.
Updated the probe to the documented stable `/api/v3/services` contract and added a
regression. The failed job remains visible; viewer and collector-outage acceptance
still require a fresh successful exact-source execution.

All ten ordinary CI jobs at `8dbce9b` passed in `36687238184`; the actual PostgreSQL
backend passed **1,053 tests, zero skips, 86.94% branch-aware coverage**. Its unchanged
load run passed at **359.78 ms p95**, zero failures. The viewer repair `8daa5c7`
passed actual local collector/viewer/outage execution in `36687923599`, including
all eleven emitted stage names. Original checksum-verified outcome files and the
preceding failure are retained under `evaluation/reports/telemetry-*`.

The same runtime at `8daa5c7` nevertheless failed load again at **571.92 ms p95**,
zero request failures. This runner reports AMD EPYC 7763 versus the preceding
passing Intel Xeon 6973P-C; both expose four logical CPUs. Hardware differs and
server-stage timings rose, but causality and stable performance remain unproven.
Both exact reports remain preserved. No reference normalization or gate waiver.

The actual tracing logs exposed Uvicorn's default raw URL/query/client-address
access records. Added fixed-field access records and fixed-code lifecycle/error
records, replacing unsafe duplicate handlers. Eighty-one local affected tests,
including a real loopback Uvicorn request/error canary test, pass on the new dirty
working source; exact committed-source verification remains pending for this repair.
The gateway configuration now uses the same method/status-only logging contract.
Added real success and stopped-upstream 502 query-canary checks to the Docker
recovery smoke gate. Proxy error detail is intentionally omitted because the
unstructured Nginx error format cannot redact request targets; actual fresh Docker
verification is required before this additional boundary is certified.

Prepared seven isolated safeguard mutations with baseline-first, assertion-only
kill scoring and explicit collection/setup/provenance error states. The first
development run recorded seven passing baselines and seven kills; 38 new runner
regressions passed. A later concurrent edit correctly invalidated the repeat's
provenance (zero accepted kills, seven errors), and the broader security suite
recorded 649 passes plus one provenance assertion failure. No retries or waivers
were used to relabel that run. Final mutation acceptance requires stable committed
source and is separate from unchanged classifier-quality failures.

Removed the historical CLI/worker coverage omissions so future backend-configured
reports expose those untested branches too. The existing 75% regression gate is
unchanged; the master prompt's 90% overall / 95% critical-module visibility targets
are not claimed achieved. Dependency declarations are unchanged by this reporting
configuration edit; both lock exports are still checked against the resolved graph.

### Durable provider accounting foundation

Added migration `d3a5f7c9b120`, persistent per-run request/token ceilings, scoped
idempotent invocation records, committed-before-transport per-attempt reservations,
immutable input revalidation, recovery fencing and safe late usage reconciliation.
Reported usage survives rejected proposals; unknown/ambiguous spend keeps its
reservation. Retention removes proposal text without erasing accounting. URL,
configuration, response shape, compressed-body and total-deadline boundaries have
targeted regressions; deadline-expired providers cannot create more requests.

The local affected run passed **138 tests with five PostgreSQL-only skips**,
including independent-session SQLite races and Alembic upgrade/downgrade/upgrade.
Real PostgreSQL contention, expiry-during-transport and late-owner cases require
exact-source CI. These are explicitly opt-in internal interfaces; no API/UI/job
activation, real model invocation or paid provider evaluation occurred. Per-instance
rate/circuit limits and text-byte reservations are not distributed rate enforcement
or a guaranteed actual billing ceiling. M7 service integration remains unfinished.

### Read-path diagnosis and bounded query repair

Per-request evidence at `8daa5c7` identifies history as the failing workload's tail:
all 23 requests above 500 ms use the history route. Read-only local SQLite profiling
shows allocation/GC pressure but does not establish the cause on PostgreSQL/CI or
justify disabling GC, changing serialization, caching stale scope or truncating
denominators. None of those changes were made.

Separately consolidated overview counters into one scalar-subquery SELECT instead
of ten round-trips, retaining each table's independent project filter and every
analysis revision's publication validation. Only category/validation fields are
loaded for analysis counts. New multi-project, current-state, membership-revocation,
token and SQL-projection regressions preserve the response contract. This reduces
known query work; improvement of the strict history-dominated target still requires
actual remeasurement on the new source.

The first clean combined source `3876720` passed the strict seven-baseline/seven-kill
mutation run, but its full backend suite exposed logger-disable state left by
in-process Alembic configuration: **1,182 passed, one failed, nine PostgreSQL-only
skips**, 85.34% coverage. Safe handler installation now explicitly re-enables its
owned logger trees, and the regression starts from disabled unsafe loggers. The
failure was preserved; a new clean full run is required before branch publication.

At repaired clean source `1f7fe67`, local verification passed **1,183 tests, nine
PostgreSQL-only skips, 85.34% coverage**. The strict local and actual CI mutation
runs both passed seven baselines/seven kills with zero survivors or errors.
Remote head/tree were reread after publication. Local collector CI also passed.

The new Docker privacy probe then exposed Nginx log inheritance: a second
http-level access-log directive added a safe record while the vendor's raw combined
record still appeared. Moved the override into every server block, with a regression
against the faulty sibling-directive pattern. Stopped Docker endpoints can time
out (504) as well as refuse (502); the probe now verifies those two genuine upstream
errors with bounded connect/request timeouts, never accepting success. Canary
exclusion remains mandatory and the original failed job `109807337030` is retained.
Fresh actual Docker execution is still required for this correction.


### Verified gateway repair and retained performance variance

At source `9414d91`, [all ten ordinary CI jobs passed](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36691730960),
including **1,192 PostgreSQL tests, zero skips**, four browser lanes and the actual
Docker success/upstream-error privacy canaries, non-root/offline and backup restore
checks. The earlier `1f7fe67` Docker inheritance failure remains visible. Dedicated
local-collector and seven-pair strict mutation workflows passed on `9414d91` too.
The original mutation report at `1f7fe67` is retained with its verified artifact hash.

The overview repair's actual `1f7fe67` load measurement **failed at 601.29 ms p95**
on AMD EPYC 7763, zero request failures. The subsequent gateway-only correction
`9414d91` **passed at 389.46 ms p95** on Intel Xeon 6973P-C, also zero failures.
Both checksum-verified original metrics/request files are retained. The unchanged
50,000-execution/concurrency-ten target, all-passing fixture, shared-runner limits
and lack of whole-stack memory measurement remain explicit. This is still not
stable or reference-hardware performance acceptance.

### Project-keyed privacy and read-only Action integration

Implemented project-domain HMAC-SHA256-128 pseudonyms for declared sensitive
correlation fields, a private persistent offline key lifecycle, server-pinned key
references for queued work, rotation/retirement behavior and key-free verification
of immutable older citations. New validation-v4 checks public v3 provenance against
digest-bound bytes. Strict typed UUID/integrity contracts remain untransformed;
this is not universal anonymization or encrypted-original storage. The affected
local run passed **441 tests, zero skips**, with **47 new privacy/lifecycle cases**.
Review found and fixed malformed-token passthrough and an unbounded key lock;
real subprocess regressions exercise lock timeout and fail-closed interrupted
publication. Full combined clean-source and actual PostgreSQL/Docker acceptance
are still pending for these edits. See `project-redaction.md`.

The reusable read-only GitHub Action now emits sanitized JSON/Markdown, digest,
completeness and fixed-field failure status. A real two-shard consuming workflow
preserves explicitly missing required shards and uses disposable PostgreSQL.
Snapshot input/counter projections are bounded without changing outcome denominators.
The publisher rejects repository traversal before transport. **106 affected tests**,
Action shell/YAML, scoped Ruff and offline workflow security checks passed locally;
actual hosted Action execution remains pending. No write token, live comment,
companion-repository modification or trusted-publisher activation was used.

### Honest static/security gates and dependency maintenance

Added a separately resolved and hash-exported quality-tool graph and bounded,
source-free gate reports for full tracked Python lint/format, backend typing, lock
consistency, dependency advisories, secret candidates and workflow security. Initial
dirty-source scans expose hundreds of lint/format/secret candidates and roughly
180 type findings; these are failed gates, not clean baselines or confirmed leaks.
No blanket ignores or threshold waivers were added. Binary/archive/history secret
coverage is explicitly not certified. The npm metadata audit's current invocation
requires authorization and stays not run by default; it is not silently routed
through CI. Details and reproducible opt-in behavior are in `quality-security.md`.

Removed an obsolete one-shot transfer workflow containing an expired signed URL;
its history and the candidate finding remain. Disabled retained checkout credentials,
removed direct matrix interpolation into shell, pinned PostgreSQL/build/collector
images to verified vendor OCI digests, and added missing workflow job names and
source-export concurrency. The strict offline workflow auditor now reports **zero
findings** on the current edited tree, without suppressions; hosted gates await
publication. These checks are not container vulnerability scans.

Upgraded pinned Vitest within major four from 4.0.18 to **4.1.11**, addressing the
published UI/API and mocker path-traversal advisories. Local frontend verification
passed **48 tests**, TypeScript and Vite production build. An earlier independent
npm audit after the upgrade returned zero vulnerabilities; that does not mark the
separately unrun quality-gate invocation as passed. Build metadata now lives under
node_modules/.cache, preserving the source-cleanliness contract instead of adding
an ignore exemption.


### Clean local integration and follow-up boundary repairs

The complete privacy/Action/tooling tree `9d82f40e064f0df2fc2d8863cb72aec7e9030210`
was committed locally as `f7d847fa56f92a3277cc917f6892623780e1d711`. Its clean
backend run passed **1,302 tests, nine PostgreSQL-only skips, 85.81% branch-aware
coverage**. The strict mutation run passed seven baselines/seven kills with zero
survivors/errors and clean provenance. Lock/export parity and the whole-workflow
offline auditor passed. These are local-source results; no PostgreSQL/hosted
acceptance is inferred from skipped cases or from the earlier `9414d91` CI.

The dedicated clean-source scans exposed **758 lint findings, 151 unformatted
files and 892 secret candidates**. The initial type-gate invocation returned a
tool-execution error, correctly not a clean result; diagnostic mypy runs then
reported 161 actual type findings. Original failures were not relabeled as passes.
An offline source-bound review classified all 892 candidates into 844 integrity/
provenance identifiers, 26 synthetic canaries and 22 deliberately published
local/demo database credentials. The latter really authenticate disposable
instances and are not called fictitious. No candidate was automatically exempted;
reviewed exception handling requires exact source/context guards and separate
raw/reviewed/unresolved counts. The dedicated npm metadata audit remains not run.

Follow-up work removes the static debt while preserving semantic boundaries:

- API dependency/parameter declarations use Annotated; generated OpenAPI remains
  exactly identical over 77 paths. All 126 focused API/auth/parameter cases pass.
- Binary input lookup now rejects absent or mismatched project/run links before
  metadata exposure, reviews, revocations or comparisons. Fifty-six affected
  tests pass, including 24 new cases; 13 reproduced defects in the old source.
- Publication predicates reject malformed unhashable categories and boolean
  scores instead of crashing or treating booleans as integers. All 339 affected
  tests pass, including 16 new cases; five fail against the old validator.
- Non-finite/overflow numeric artifact values no longer produce infinite
  durations or HAR/k6 conversion crashes. Failure observations remain present;
  invalid measurements become unavailable. The 127-case affected run and 62-case
  privacy/evidence run pass, including 11 new malformed-number cases.
- Runtime typing and fixed-code exception logging preserve worker/telemetry
  containment without raw traceback, exception text or provider secrets. The
  516-case affected run and final 38-case history/privacy run pass, including four
  new raw-log/transport-slot regressions. Whole-backend gradual mypy reports no
  errors on this edited tree; it is not a strict annotation-completeness claim.

Formatting was checked against executable AST equality before later type repairs:
145 files were identical; one migration module only lost trailing whitespace in
its docstring. Collection-literal rewrites separately verified unshadowed builtins
and normalized AST equivalence. Existing imports required for model registration
and PostgreSQL fixture discovery remain explicit. Subprocess calls state their
existing check=False behavior, and evaluation loop closures bind their case scope.
All 60 component-oracle outputs and 21 weekly fixture outputs compare identically
with the committed pre-cleanup implementation. Frozen artifacts were not regenerated.
The harness/privacy affected run passed 173 tests with five PostgreSQL-only skips.

The combined follow-up source was committed locally as
`9369ee2e1f36943d740d57c2f5d9ab47968abe88` (tree
`224053aafb31ac92f5d88fccb1e575aea7dbe7a6`). Its clean full backend run passed
**1,415 tests, nine PostgreSQL-only skips, 85.90% branch-aware coverage**. Strict
mutations passed seven baselines/seven kills with zero errors. All six independent
offline gates passed: lint, format, gradual backend types, lock/export parity,
workflow audit and source-bound secret review. The latter reconciled 900 reviewed
source candidates and 2,075 recomputed policy-metadata candidates, with no
unresolved cases or policy errors. These are source-specific local results, not
hosted acceptance or a claim that every possible secret is detectable.

The required npm metadata audit remains NOT RUN because its external transmission
has not been authorized. Security acceptance remains blocked. The original
90%/95% coverage visibility goals, stable read performance and frozen classifier
quality are still not claimed achieved. No labels, denominators, targets or
historical measurements were changed to produce a green result.

### M7 application workflow, awaiting committed-source and hosted verification

The next implementation connects the existing optional provider library to an
operator-configured API, dedicated durable worker and administrator approval UI.
It remains disabled by default. Submission and execution require production
authentication, secure cookies, an allowed project, a current administrator
session, a matching worker heartbeat and immutable analysis/evidence/configuration
digests. Demo deployments cannot submit, even as authenticated administrators.
Preview discloses the destination origin, approved excerpts, limits and dated or
unknown pricing before explicit approval. Provider hypotheses remain unverified;
deterministic classifications, reviews and contradictions are never replaced.

Migration `e6c8a2f4b130` adds linked provider jobs, shared admission state and durable
once-per-attempt circuit accounting. Short transactions reserve request/token
budgets before transport. Cancellation, lease loss and recovery never resend or
refund an uncertain request. Late completion may settle numeric usage and release
the transport permit, but cannot revive a terminal proposal or account one circuit
failure twice. The ordinary ingestion worker excludes provider job types from
both execution and recovery.

The separate Compose overlay places the credential only in the provider worker
and permits egress only through an exact-host CONNECT proxy. DNS results must all
be public addresses; numeric connects prevent a second resolution. Resolver slots,
connections, headers, bytes and deadlines are bounded. API and ordinary-worker
network membership remains isolated from the proxy. The overlay requires a fresh
trusted production-auth database; disabling demo mode does not invalidate accounts
previously created in a demo deployment.

Initial focused local verification passed **286 provider/configuration/ledger cases** with
seven new PostgreSQL cases explicitly skipped, **81 proxy/deployment cases**, and
**99 frontend tests**, plus frontend type/build and scoped Python static checks.
Actual local production-auth HTTP/API/worker fixture checks covered proposal
success, HTTP 503 fallback and cancellation; authenticated demo setup returned 403.
Fixtures use synthetic sessions and injected MockTransport, never a real provider.
Separate desktop/narrow provider browser jobs preserve the four existing demo
browser lanes and their 43 tests. Local browser execution is blocked by the
available browser environment; no visual acceptance is inferred from unit tests.

Independent review then reproduced three integration defects: known worker-token
echoes could survive generic response redaction, provider jobs could block the real
retention cleanup queue, and backend/UI string bounds could disagree on a valid
proposal. All three repairs pass their new regressions: ten decoded credential-echo
cases, six actual retention-queue cases and fourteen output/preview contract cases.
The preview is compared to the exact sanitized request payload, including a context
larger than 32 KiB. Backend and frontend limits now agree on Unicode code points;
invalid older cached proposals are withheld without blocking invocation history.
The revised frontend passes **115 tests** and production type/build checks.
The deployment review also rejected reuse of the published demo database password:
the optional overlay now requires operator-owned database URL/password values for
all application services and PostgreSQL, with no fallback. Its synthetic fixture
checks pass **85 local cases**; actual Compose missing/empty-value rejection and
container checks remain pending.

Full clean-source verification, new source-bound candidate review, real PostgreSQL,
Docker topology and hosted browser execution remain required for this new tree.
No real model invocation, paid-provider benchmark or live publication has occurred.

The first clean full M7 source `79c73542bb5328bc7f948ca513b2ba4e4f6f0444`
(tree `28427833516966b929ad2ef90fa667732b77b9f4`) produced **1,704 passes, one
failure and sixteen PostgreSQL-only skips**, with 86.37% branch-aware coverage.
The failure is retained: an older runtime-diagnostic regression called a private
transport helper whose contract now defers exception propagation until durable
accounting settles. That regression now exercises the public provider boundary,
initializes real telemetry before capturing its logger, and retains the exact
exception identity, private fixed-code log and released-slot assertions. It also
checks the consumed reservation and released outer concurrency permit. This is a
test-interface correction, not removal of the safety regression.

At `79c7354`, all six independent offline gates passed on clean source, including
**3,030 raw secret candidates: 915 reviewed source, 2,115 independently validated
policy metadata and zero unresolved**. Frontend verification passed 115 tests and
production type/build. A fresh clean full backend and strict mutation run are
required after the diagnostic-test correction; the failed source is not relabeled
successful. No npm audit or hosted acceptance is inferred.

The correction was committed locally as `132efc083d6ad51dd9c80920ab456465a0622759`
(tree `85cebd7ba70abb25395fdd7e6919e7809bd8a401`). Its clean full backend run passed
**1,705 tests with sixteen PostgreSQL-only skips and 86.37% branch-aware coverage**.
The strict mutation suite passed seven baselines/seven kills with zero survivors
or errors and clean provenance. All six independent offline gates passed, including
the same 3,030-candidate fully reconciled secret scan. The frontend tree is unchanged
from the 115-test/type/build verification at `79c7354`. PostgreSQL, Docker topology,
browser execution, live model evaluation and new hosted CI remain unverified. The
required npm audit remains NOT RUN and aggregate security acceptance is blocked.

### M8 report, retained evidence and durable publication integration

The next local implementation expands the shared report from existing persisted
data: skipped reasons, effective impact decisions, current clusters, performance
comparisons and conservative prior exact-base new/existing/unknown observations.
Logical identity includes suite/source path; whole-record JSON trimming regenerates
Markdown so removed citations cannot linger. Stored regressions, unavailable
comparisons and violated full-suite fallbacks force HOLD. No preview creates
recommendations or invents a favorable baseline. The 112-case focused report,
Action and publication suite passed before final integration.

`github_evidence.py` retains at most 100 approved reference entries/500,000 bytes
as canonical inert JSON. Exact derivative excerpts, narrow scalar observations,
immutable locators and provenance are revalidated at export. Originals, storage
paths, arbitrary nested metadata and binary bodies are excluded. Counts expose
rejected, unavailable and omitted references. The digest-bound CLI/API detects
report/evidence changes; HTTP downloads preserve canonical bytes. Thirty-two
focused export/snapshot/validator tests pass. The Action verifies actual exclusive
output, digest, receipt, byte bounds and scope before exposing `evidence-path`.
Its strict optional config cannot enable code, credentials, provider or comment
execution. All 86 Action cases and the offline workflow auditor pass.

Migration `f8d0c2e4a610` and the dedicated publisher service persist target
reservations, attributable publication attempts and bounded write journals. Bot
identity is verified before any mutation. Write intent commits before HTTP; no
transaction spans transport. Missing acknowledgements preserve a sticky reservation.
Reconciliation fences the original process and never treats absence as permission
to resend. Only explicit neutral repair may replace an exactly observed stale report.
Source workflow metadata remains labeled unverified. History APIs are read-only
and project-authorized; analysis/provider code gains no GitHub capability.

Independent review reproduced two defects and both are fixed: malformed comment
records could be mistaken for absence and create a duplicate; no-op/reconciliation
paths could accept changed evidence without notice. Required shapes now fail before
POST, and every new success/no-op checks current scope/evidence/report digest.
Observed historical writes remain recorded while drift becomes failed/uncertain;
same-SHA neutral repair uses truthful evidence-change wording. The expanded local
publication suite passes **103 tests**, with three real PostgreSQL cases explicitly
skipped. Whole-backend type checking passed before the final UI integration.

The final receipt extension records report schema and exact analysis revision
identity without storing prose. A full-scope manifest covers every latest analysis,
including detail omitted by byte limits; visible ID/revision references are bounded
at 50 and remaining references are counted. A regression proves that revising an
omitted analysis changes report identity even when Markdown is unchanged. The
expanded publication suite now passes **134 tests**, with the same three PostgreSQL
skips. All 28 snapshot/export tests pass after that manifest extension.

The dashboard adds canonical report/evidence JSON downloads beside Markdown.
It preserves original server bytes, verifies hashes without reserializing Python
floats/Unicode escapes, checks scope and limits, and cancels stale work on refresh,
navigation and sign-out. Production type/build and **200 frontend tests** pass.
A real synthetic SQLite ingestion/report/export round trip through the transpiled
frontend preserves the exact bytes. All 43 existing browser tests still collect;
extended desktop/narrow download journeys have not been executed locally.

New source-bound secret review, combined clean-source verification, real PostgreSQL,
hosted Action/browser execution and an authorized live publication target remain
required. No live GitHub comment, provider call, npm audit or external release has
been performed. These implementation results do not complete the failed frozen
classifier-quality requirements or the full master project.

### M8 clean-source checkpoint and first resumed hosted verification

Local `d7dd7ebc4b21da82d86ed2d73d225979e1715d92`, tree
`e5d31d11451148ce4882fb0a869bf474a66cfe9b`, passed **1,907 backend tests** with
**nineteen explicitly PostgreSQL-only skips**, **200 frontend tests**, production
type/build and all six offline quality gates. The source remained clean during the
full run and strict mutation verification: seven baselines, seven kills, zero
survivors or errors. Secret review resolved all 3,052 candidates (921 source plus
2,131 independently validated policy metadata), with zero unresolved or policy
errors. Existing producer inputs were verified prior CI exports.

Coverage terminology matters: the reported **87.4926% is combined statement and
branch coverage**. Actual branch-only coverage is **2,985/3,822 = 78.1005%**. The
master's 90% branch-only target and 95% critical-module targets remain unmet;
earlier combined percentages must not be read as branch-only acceptance.

Owner-authorized delivery resumed with remote
`efa9a13dfbe70a266217acc5b0bcae4b98cd238e`, whose tree exactly matches local
`f7d847f`. All ten jobs in [ordinary CI 36725943839](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36725943839)
and eight other workflows passed. The unchanged [frozen benchmark](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36725943695)
still failed. The [operational read benchmark](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36725945608)
retains another failure: **710.69 ms warm p95**, zero failed requests, 50,000
executions/concurrency ten on the AMD EPYC 7763 runner. Its 500 ms threshold remains
unchanged. These results belong to efa9a13, not the newer M7/M8 source.

The first [quality workflow](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36725942000)
failed before creating jobs. Inspection found `runner.temp` references in job-level
`env`, where the [GitHub context availability rules](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#context-availability)
do not permit `runner`. The correction initializes the same isolated cache paths
in the first shell step after runner allocation. New regressions check every
workflow's job/global environments and execute both initialization scripts with
space-containing runner paths. All 80 focused quality/context tests and the offline
workflow/secret gates pass. The initial focused rerun hit pytest's temporary-root
symlink safety check after relocating inactive scratch; restoring a real root and
preserving individual archived paths resolved that environment failure.

The npm audit remains explicitly NOT RUN pending its separate approval. The
required aggregate still fails when that audit is skipped; fixing workflow syntax
does not waive security acceptance. No live comment, external provider request or
external collector was sent. Fresh hosted acceptance for newer M7/M8 source remains
pending at this record; branch coverage, stable performance and failed frozen
classifier quality still prevent a full-project completion claim.


### Bounded review-policy delivery repair

The large canonical policy exceeded the reliable connected-service transfer path;
ordinary Git transport could read the repository but had no CLI authentication.
No partial source tree was moved onto `main`. The source policy is now packaged as
sixteen canonical parts below 70 KB with an ordered, digest-bound index, preserving
all scan scope and validation rules. Both filesystem and scanner inventories must
match; missing, extra, reordered, duplicate or modified parts fail closed.

Independent reconstruction first reproduced the original 921 ordered review
entries, scanner configuration and all 1,047,671 bytes exactly. Changing the loader
correctly invalidated its own old source guard, and the real scan rejected all
3,101 candidates while that guard was stale. A separate independent review then
authorized only the nonsecret policy-path entry's source/occurrence guard refresh;
all other entry fields and all other 920 entries remain unchanged. The original
policy, migration proof and guard delta are preserved. All 129 focused tests pass,
including 49 new malformed-input, inventory, symlink and metadata-boundary cases.
The first new resource-limit test used a cap larger than its fixture; its retained
failed run is corrected by deriving the cap from the actual fixture size.

This changes tooling and packaging, not application classification or held-out
labels. Required npm audit remains NOT RUN. New hosted acceptance is still required
for the final delivered commit; earlier full M8 verification remains separately
identified above.

Final packaging verification passed all six offline gates. The actual scan reports
**3,101 raw candidates: 921 reviewed source and 2,180 validated policy metadata,
zero unresolved and zero policy errors**. Metadata counts now include separately
scanned part/index digest occurrences; source review count remains 921. Final
focused verification is **129 passed**, with no skips. The application source is
unchanged from the earlier full M8 run; this targeted tooling verification is not
a substitute for the final commit's PostgreSQL/browser/hosted acceptance.

### Published M7/M8 checkpoint — 2026-09-30

Remote `d6f2b72a425ed3269026a6129794bf2e6fc90f8d`, exact tree
`81fb83d26f00040d4ec79e301685d001ee39b041`, contains the complete prepared M7/M8
source, workflow repair and bounded policy packaging. The non-force main update
and exact remote tree were verified. No incomplete source tree was published.

[Ordinary CI 36735786458](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36735786458)
passed all **twelve jobs**: PostgreSQL backend (**1,978 passed, zero skipped**, 87.58%
combined coverage), frontend, actual producer fixtures, existing evaluations,
Docker validation/builds, four general browser lanes and two production-auth
provider browser lanes. The dedicated [provider boundary run](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36735786501)
also passed actual PostgreSQL/API/fixture-worker success and outage cases, ordinary
worker exclusion, readiness and container network/token placement. This uses an
injected synthetic fixture, not real model connectivity or paid inference. Its
retained report marks cost unknown and confirms sensitive canaries are absent.
Representative desktop proposal and narrow outage captures were inspected; the
unverified proposal and deterministic-fallback states remain explicit.

The [read-only Action consumer](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36735786596)
passed with retained report, Markdown, status and canonical evidence outputs.
The [strict mutation workflow](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36735786606)
and the existing telemetry, diagnostic, campaign, transaction-finality, full-stack
and source-export workflows also passed. This hosted verification belongs to d6f2b72.

All seven independent jobs in [quality/security](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36735786565)
passed, including Python dependency audit and the exact 3,101-candidate scan. npm
audit was explicitly skipped, so the required aggregate correctly **FAILED**.
The unchanged [frozen classifier benchmark](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36735786602)
still failed. [Operational reads](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36735786619)
again failed: **586.89 ms warm p95**, zero recorded warm request failures, AMD EPYC
9V74 hardware, the same 50,000-execution/concurrency-ten workload and unchanged
500 ms target. Earlier failed and passed measurements are retained; stability on
the reference resource envelope remains unproven. No live GitHub comment, external
provider request, external collector or npm metadata audit was performed.

### M9 cohort, measurement and child-process hardening

Three reproduced defects now have local repairs and failing-before regressions:

- Requested cohort predicates now run before the bounded comparable-run query, so
  unrelated older runs cannot consume the cap and erase missing-test denominators.
  Branch/environment nulls, time windows, excluded runs, worker/shard counts and
  scope normalization retain their prior-only and truncation rules. Independent
  review found a related preexisting mismatch: legacy unknown scopes counted as
  comparable but lost their actual executions and human reviews. A shared SQL
  predicate now matches the existing normalization across all three queries.
  Unknown-scope observations still explicitly disallow reassurance.
- Operational measurement counts cold and warm failures, requires exactly four
  cold and 200 warm samples, retains the successful-warm latency denominator and
  unchanged 500 ms threshold, and records fixed stage/error types on initialization,
  seeding, startup, readiness or measurement failures. Cleanup is bounded, keeps
  the primary failure and reports forced/failing fallback cleanup. No exception
  message or connection detail is copied into retained metrics.
- The image child starts the sibling worker directly with isolated Python imports,
  a minimal environment and closed inherited descriptors. Actual child-process
  canaries show that parent settings/credentials and inheritable descriptors are
  absent and an untrusted PYTHONPATH startup hook does not run. Existing PNG/JPEG
  processing still passes. This is process/import hygiene, not a filesystem or
  network sandbox; documentation no longer claims that stronger boundary.

Focused local verification passed 61 history/reuse tests after the independent
scope repair, 21 measurement tests and 46 image-related tests. The same review found
no additional blocker in benchmark/image changes and no existing source-bound
review entries for the changed files. Six offline gates pass with the unchanged
3,101-candidate resolved scan. Full clean-source regression and exact-source hosted
verification are required after this new checkpoint. No performance acceptance or
full-master completion is inferred from these local regressions.

### M9 hardening delivered and verified

Published source `44988f581f9330502c030651c2c24e8978a67687` has exactly the tested
local `b863541` tree, `6900fb2849d03512e4c22e7ef1516c8588baf506`. The clean local run
passed **2,012 tests with nineteen PostgreSQL-only skips**, 87.4706% combined
coverage and **2,998/3,840 = 78.0729% branch-only**. Six offline gates and the strict
seven-baseline/seven-kill mutation run pass. PostgreSQL skips are not acceptance.

At the published source, [all twelve ordinary CI jobs](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36748154707)
pass. The actual PostgreSQL backend passed **2,031 tests with zero skips**, eight
warnings and **87.56% combined coverage**. All four general browser lanes, both
provider browser lanes, synthetic provider deployment, producer fixtures, Docker
and evaluation integrations pass. The separate read-only Action, telemetry,
provider boundary, mutation, full-stack, diagnostic, finality, campaign and source
export workflows pass too. These results belong to this exact source.

The strict frozen classifier still fails. The operational run fails at
**664.567469 ms p95** on AMD EPYC 7763, with zero cold or warm failures and the full
4/200 samples. The [original metrics and requests](../evaluation/reports/operational-44988f5-failed/README.md)
are retained byte-for-byte with their verified archive digest, alongside the
`efa9a13` and `d6f2b72` failures. All seven independent quality/security jobs pass, while the npm
audit is **NOT RUN** and the required aggregate correctly fails. No gate is waived
and no real provider, live PR publication or external collector was activated.

### M9 immutable policy and verifiable coverage work

A reproduced concurrency defect allowed an immutable performance-policy version
conflict to return the winning row after an integrity-error rollback without
checking its content. Ordinary duplicate lookup and race recovery now share the
same content validation. Seven different-content recovery cases failed before
the repair; the focused local suite passes 26 cases. Eight real PostgreSQL races
are present but skipped locally, pending exact-source hosted execution.

New coverage tooling keeps the original 75% combined regression gate and declares
separate 90% overall/95% per-critical-file branch targets. It binds committed source
bytes and runtime/test inventories to fresh process data, collects ordinary Python
children, and exercises the unchanged isolated image worker through a trusted
test-only harness. A source-free report and canonical executed-arcs database are
checked together; failed numeric targets remain failures. See
[coverage scope and trust limits](backend-branch-coverage.md). Focused collector
tests do not establish whole-project coverage acceptance.

The local verification wrapper now uses fresh external outputs and owned temporary
storage, preserves existing frozen inputs/reports, and disables inherited provider,
production-database and telemetry activation. Six offline quality gates use the
existing source-bound review policy; both online audits are explicitly NOT RUN
and required acceptance fails. Twenty-one focused wrapper regressions and an actual
temporary SQLite migration roundtrip pass. This new combined source still requires
clean committed collection and hosted verification; full master acceptance remains
open.

### First complete local verifier execution and repair

The clean `1ab3fcb` integration run is retained as a **failed** measurement:
**2,125 backend passes, seven failures and 27 PostgreSQL-only skips**. Six failures
came from the new verifier's blanket `OTEL_SDK_DISABLED=true`, which also disabled
the tests' intentionally local in-memory/loopback spans. The seventh was an old
workflow-contract assertion that still required the replaced pytest-cov command.
No failed test or assertion was suppressed. The delegated coverage contract now
checks the actual collector invocation, real PostgreSQL service, clean archive
installation, subprocess/branch configuration and unchanged 75% combined gate.

That run preserved clean source and frozen inputs/reports. The real SQLite
migration, all five legacy harnesses, frontend build, **200 frontend tests**, and
all six offline gates passed, including **3,120 resolved secret candidates with
zero unresolved**. Both audits remained NOT RUN and required security acceptance
failed. Its branch counts were **3,045/3,840**, but failed regression execution
cannot grant branch acceptance. The original report/data pair and logs remain
separate from the next repaired-source run; no publication was made from this
failed checkpoint.

### Committed measurement and policy-race delivery

The repaired clean local source `03df4f6` passed **2,132 backend tests with 27
PostgreSQL-only skips**, all five legacy harnesses, the SQLite migration roundtrip,
frontend build and **200 frontend tests**. All six offline gates passed, with
3,120 secret candidates resolved and zero unresolved. Source and frozen inputs
were unchanged. Branch-only coverage was **3,047/3,840 = 79.3490%**, combined
coverage 88.5414%; the master branch gate still failed, both audits remained NOT
RUN, and the overall verifier deliberately exited nonzero.

Published `48e63361a742ef32df708fa2709ceb640e035f78` has that exact tested tree,
`1cc91fed722247622454fb10b1486ce6f9df88fc`. In
[CI run 36756008656](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36756008656),
all twelve ordinary jobs pass, including **2,159 actual PostgreSQL tests with zero
skips**, all eight immutable-policy races, all browser lanes and Docker/producer
checks. Hosted branch coverage is **3,055/3,840 = 79.5573%**, combined coverage
88.6295%. The independent branch job downloaded the exact source-free report/data
pair, recomputed the evidence and correctly failed its unchanged 90%/95% targets;
it did not fail because evidence was missing or invalid. The workflow therefore
remains red despite passing ordinary regressions.

The separate Action, provider, telemetry, mutation, full-stack, diagnostic,
finality, campaign and source-export workflows pass. Seven independent security
jobs pass; the required aggregate remains failed because npm audit is NOT RUN.
The frozen classifier gate still fails. The unchanged operational workload also
[fails at 634.498979 ms](../evaluation/reports/operational-48e6336-failed/README.md)
on AMD EPYC 9V74: all four cold and 200 warm requests succeeded. Original metrics
and request bytes are retained with verified artifact and member digests. None of
these results completes the master project or establishes stable performance.

### Authentication transaction and membership boundary repairs

Fresh request sessions reproduced a metadata defect: successful bearer/cookie
`/auth/me` requests flushed `last_used_at` but rolled it back when the handler
session closed. Credential validation now owns an engine-bound transaction that
commits and closes before returning a principal. Business transactions retain
their own commit/rollback behavior. Tests cover invalid credentials, commit
failure, subsequent recovery, and a failed handler whose business insert rolls
back while successful authentication metadata remains. The timestamp records
credential validation, including requests later denied or failed; expiry and
permissions do not depend on it.

Authentication requires independent connections using standard QueuePool/NullPool
PostgreSQL or ordinary file-backed SQLite. Shared pools, existing Connection or
Session bindings, per-model overrides and SQLite URI modes are rejected before
credential access. Independent review reproduced two URI bypasses and confirmed
their repairs open zero connections. Credential-free demo use remains supported
with in-memory SQLite. This adds a security boundary to `db.py`, which is declared
as the 34th critical coverage file before the next measurement; the 95% target is
unchanged. Thirty focused transaction cases pass. Three additional real-PostgreSQL
cases remain locally skipped and verify distinct live backend connections plus
persistence/rollback when executed in CI.

Membership review reproduced schema-valid normalized usernames escaping as HTTP
500 and stale authorization after a concurrent actor/role/session change.
Mutations now return 422 for invalid normalized usernames, reserve the shared
project boundary and refresh actor, credential and membership state before
rechecking permission. PostgreSQL uses its row lock. Independent testing also
reproduced two successful SQLite demotions leaving zero administrators; a narrow
SQLite no-op Project UPDATE now reserves the writer before permission/count reads.
It does not commit or reset the caller transaction. Stale WAL upgrades fail closed,
and existing inactive-administrator counting is unchanged.

All three real-file SQLite race variants failed before repair and pass afterward.
Independent verification observes one success, one 409, one remaining administrator
and one success audit. The focused membership/auth/operations run passed **82
tests with 21 PostgreSQL-only skips**; the separate original auth/provider-focused
run passed 113 cases before the two URI regressions were added. Four new bootstrap
security cases and the corrected existing production-bootstrap scenario pass:
bootstrap never promotes/reactivates an existing ordinary user, replaces its
password or creates a later administrator under a changed configuration. The prior
existing test accidentally used demo mode for that last assertion.

These changes have focused and independent review evidence. Clean full-source
collection, exact-source PostgreSQL execution and hosted regression remain
required before delivery; no new coverage percentage is claimed yet.

### Authentication and membership exact-source execution

The clean local measurement `b3ac25082129f974986d32a4dc673928a23c51ff`
passed **2,214 backend tests with 51 PostgreSQL-only skips**, all five legacy
harnesses, SQLite migrations, frontend build and 200 frontend tests. All six
offline quality gates passed. Source and frozen inputs remained unchanged.
Branch coverage was 3,077/3,856; the 90%/95% targets failed, both online audits
were NOT RUN and full-project acceptance remained NOT RUN.

Published `caee9e300bc8974c750ccaab5e78d94c00dfd337` has the exact measured tree
`f72e75e898a0a15d7a9087150a1640401a2fc0a4`. In
[run 36763069596](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36763069596),
backend job `110050915541` passed **2,265 tests with zero skips**, including all
51 real-PostgreSQL cases. This executes the three independent authentication
transaction cases and 21 membership concurrency/current-authority cases that
could not run locally. Hosted branch coverage is **3,088/3,856 = 80.0830%**;
combined coverage is 88.9683%. Five of 34 critical files meet 95%. The independent
checker verified the report/data pair and correctly failed the numeric targets.
All twelve ordinary CI jobs completed successfully, including all four browser
lanes, provider browser checks, Docker and producer fixtures. Source export,
telemetry, optional-provider boundary, Action consumer, diagnostic, mutation,
campaign, transaction-finality and full-stack workflows also completed successfully.

Seven independent hosted quality/security jobs pass. Python audit succeeded;
npm audit remained skipped and the required aggregate failed. The unchanged
operational workload [failed at 677.267157 ms](../evaluation/reports/operational-caee9e3-failed/README.md),
with all four cold and 200 warm requests successful. Frozen classifier acceptance
still fails. These results do not establish full-project readiness.

### Current-evidence and storage review findings

Ordinary ingestion/API and real retention probes at `caee9e3` reproduced two
current-validity gaps: removing a derivative left API analysis claims and new
reassuring review eligibility live, and expiring prior supporting history left
known-flake reassurance live in the API and GitHub preview. Historical stored
analyses and reviews are immutable records; their original validation must not be
treated as proof of current availability. Shared current projections and new
review eligibility are being repaired, with fresh original-cutoff history checks.

Separately, real coroutine cancellation left an upload staging file, and a bounded
JSON trace containing an oversized integer timestamp raised `OverflowError`
instead of rejecting only that manifest input. Filesystem fault probes also found
unbounded reads after pathname stat and symlink/finalization weaknesses under
artifact-volume modification. Those defenses require distinct threat assumptions;
the probes did not demonstrate a remote cross-project exploit. Repairs and fresh
verification remain pending at this checkpoint.

### Current-validity and bounded storage implementation

One request/transaction context now rechecks current evidence across analysis
projections, human review submission, GitHub preview and canonical export. It
refreshes preloaded policy records and shares immutable-byte reads without caching
authorization decisions. It validates the original accepted analysis inputs,
including uncited inputs, while preserving unrelated sibling-execution isolation
and explicitly correlated diagnostic inputs. Contexts cannot cross sessions or
transactions. Stored analyses and review events remain unchanged by projection.

Known-flake publication rechecks the original prior-only cutoff, cohort, policy
and history digest. Explicit citations on qualifying past human reviews must
remain available; an uncited category correction remains a human judgment rather
than being assigned invented evidence. No recursive reclassification or future
review input is introduced. Missing bytes, digest mismatch, revoked approval and
expired supporting history withhold current claims and block new reassurance.
Old preview/export/publication digests fail after relevant support changes.

The API exposes unavailable current support separately from retention expiry and
the recorded category. The dashboard displays this distinction and labels overview
and review-queue values as recorded history. SQL filters/counts/pagination keep
their historical semantics. Frontend build and **203 tests** pass. The focused
evidence/history/API/publication run passed **456 tests**; the additional real
trace/k6 producer-inspection, binary, performance and redaction run passed **99**.
These overlap and are not an additive full-suite count. Independent two-session
review verified that a previously loaded derivative is refreshed after another
transaction restricts it. A new historical-citation fixture initially reused the
same content-addressed path for prior/current bytes; the corrected fixture asserts
distinct paths before deletion. That was a fixture error, not a runtime defect.

Storage now bounds reads on opened regular-file descriptors, rejects symlinked
namespace components and publishes private staging inodes without overwriting
existing finals. Cancellation and OS cleanup failures preserve the original
exception. Huge trace integers receive scoped `malformed_report` rejection,
including optional/required manifest and durable-worker paths. Sixty new
regressions cover these boundaries: 15 of 16 selected cases fail on the published
old-source archive; the final combined caller run passes **183 tests**, with no
failures or skips. Focused lint, formatting and types pass for both repair groups.

The documented Linux/container storage capability requirements and trusted-volume,
orphan-cleanup and power-loss limitations remain explicit. The new
`publication_validity.py` is the 35th declared critical file before the next
measurement; the 95% target is unchanged. Clean full-source collection, all offline
gates, exact-source CI and publication are still pending for this new batch.

### Clean local checkpoint and cache resource review

Intermediate local source `1fac840e24d07881426b10a4b329ba9164fcfb72` completed
the full clean-source verifier: **2,297 backend tests passed, 51 PostgreSQL-only
cases skipped, zero failures**, in 459.80 seconds. SQLite migrations, all five
legacy harnesses, frontend build/203 tests and all six offline gates passed;
source remained unchanged. Its branch measurement is **3,159/3,922 = 80.5456%**,
with six of 35 critical files meeting 95%. Combined coverage is 89.3193%.
The strict branch gate still fails; both local audits are NOT RUN, required
security acceptance fails and full-project acceptance remains NOT RUN.

This checkpoint was withheld from publication after final review found that its
new request caches could retain every distinct evidence body, history context and
read exception. The measured source/report pair is preserved. A bounded-cache
repair is required before publishing the batch; it must evict or bypass caching
without truncating input, skipping validation or retaining exception tracebacks.

The repair caps successful byte caching at **128 entries / 4 MiB**, using least
recently used eviction. Larger valid bodies are returned uncached and errors are
never retained. History caching holds at most 16 exact-scope contexts; those with
more than 256 qualifying review IDs bypass caching intact. These are cache
retention bounds, not reductions to evidence/history inputs or validation.
Ten tiny real-artifact/history tests produced eight expected failures and two
passing controls before the repair; all ten pass afterward within **157 focused
integration tests**. They verify hit promotion, both budgets, exact boundaries,
reread/corruption detection, recovery after failure, released traceback frames,
original cutoff/digest recomputation and complete uncached review references.
Focused types, lint and formatting pass. Final-source CI remains required.

The bounded local checkpoint `2d64b3c22f586a69fb592cafbbd3fbdbbd1320d0`
passed its 157 focused checks and all six offline gates, but its subsequent full
test process ended before writing JUnit outcomes. The collector correctly rejected
the run with `missing-or-oversized-test-outcomes`; branch measurement is NOT RUN,
and no full backend pass is claimed. Migrations, five legacy harnesses, frontend
build/203 tests, all six offline gates and source-preservation checks completed.
The original logs/shards and failed wrapper summary are retained separately.

Concurrent shared-host memory pressure is a hypothesis, not an established cause:
the original collector did not retain the child return code and no pre-run OOM
counter was captured. The exact source tree was uploaded as immutable Git objects,
but no commit/ref update was made from this incomplete result. The collector now
retains a bounded, source-free process diagnostic before reading outcomes, and
actual self-terminating child tests verify that it still refuses acceptance.
An isolated verification window and new committed-source run remain required.
