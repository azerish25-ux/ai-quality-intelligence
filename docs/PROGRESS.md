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
