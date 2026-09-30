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
