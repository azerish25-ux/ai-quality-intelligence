# M6.3: frozen five-category evaluation and domain evidence

## Delivered scope

The general benchmark evaluates the ordinary ingestion API, durable worker, stored
analysis, evidence validator, authorized derivative endpoint and advisory renderer.
It does not substitute direct calls to the analyzer for the published decision.
The comparison modes additionally call the same rules with and without the
prior-only history used by the actual application.

The corpus contains **260 cases in 83 explicitly authored mechanism groups**:
200 controlled synthetic cases and 60 byte-preserved, previously executed
LedgerGuard component cases. Category totals are 140 product defects and 30 each
of test defects, infrastructure failures, known flakes and insufficient evidence.
The 136 development, 16 calibration and 108 test cases are family-separated.
The test partition contains 44 product cases across 20 product mechanisms and
16 cases in each remaining category. Its 108 cases are synthetic. The 60 retained
executions stay in development; this campaign does not execute fresh LedgerGuard
faults, create additional independent variants, or allege new companion defects.

The 83 group definitions are readable in `families.json`. These are authored
mechanism judgments rather than independent expert causal adjudication. Related
variants share a family, and previously inspected component mechanisms cannot
enter the test partition. A public, agent-authored test is not independently blind.

The original acceptance policy is unchanged: product recall >=90%, macro F1
>=0.80, non-abstained coverage >=75%, dangerous dismissal <=5%, and zero observed
critical/high dangerous dismissals. Corpus integrity and quality are distinct.
The new CI workflow enforces both; unmet quality targets fail its final scoring
step. A passing unit test suite never overrides a failed quality target.

## New runtime observations

`domain-observations-json` is a manifest 2.0 diagnostic input. Its
`domain-observations-v1` strict schema has three variants:

| Kind | Declared contract | Recomputed relationship |
|---|---|---|
| `operation_identity` | Operation is part of request identity | Distinct operations with a shared reported scope/payload must not have the same fingerprint. |
| `projection_order` | Older entity events must not replace newer state | Before/event/after versions and state digests jointly establish an older-event replacement. |
| `weekly_recurrence` | Weekly recurrence preserves local wall time | Calendar spacing is seven local days, not always 168 UTC hours. An ambiguous/nonexistent DST target requires an additional policy and abstains. |

Each diagnostic must declare `test_identity`, `attempt`, `browser`, and a
`correlates_to` input ID matching exactly one execution. Measurements and claims
are bound to the authorized immutable derivative and original producer digest.
Unknown schemas, conflicting measurements, missing fields and unsupported causal
wording do not justify product blame. The publication validator recomputes the
predicate. The evaluation scorer has its own numeric/calendar implementation;
it does not import the runtime domain predicates.

These are **reported observations under a declared contract**, not a certificate
that an arbitrary producer is truthful. They do not identify which component is
responsible. The old component XML reports do not acquire measurements they
never contained; their twelve historical abstentions are preserved as historical
results, not retroactively relabeled as fixed.

## Reproduce against the frozen corpus

Install the existing pinned project dependencies, then use an empty disposable
Loose Thread database and an artifact directory outside the corpus. PostgreSQL
must first be migrated with `cd backend && alembic upgrade head`. The following
SQLite example exercises the same API/worker path but does **not** establish
PostgreSQL acceptance:

```sh
python -m pip install './backend[dev]'
export FAILURELENS_DEMO_MODE=true
export FAILURELENS_DATABASE_URL=sqlite+pysqlite:////tmp/failurelens-benchmark.sqlite
export FAILURELENS_ARTIFACT_ROOT=/tmp/failurelens-benchmark-private-artifacts
python evaluation/benchmark_replay.py \
  --inputs evaluation/corpus/benchmark-v1/inputs \
  --output /tmp/failurelens-benchmark-replay \
  --confirm-disposable-database
python evaluation/benchmark_harness.py \
  --corpus evaluation/corpus/benchmark-v1 \
  --replay /tmp/failurelens-benchmark-replay \
  --output /tmp/failurelens-benchmark-report --enforce-quality
```

Both output paths must be new; existing projects and old reports are never
silently overwritten. The scorer returns exit 1 for integrity failures and exit 2
for unmet quality targets when `--enforce-quality` is requested. Without that
flag the report still includes every failed quality target. The permanent
`benchmark-evaluation.yml` workflow runs on PostgreSQL, adds API-backed desktop
and narrow browser checks, retains evidence, and enforces quality explicitly.
Its presence is not evidence that it executed in a disconnected local session.

To reproduce dataset construction, use the generator revision recorded in
`freeze.json` in a separate checkout. The generator CLI verifies that its source
files match that commit. Generation performs no inference or LedgerGuard faults.
A modified dataset must use a new destination/version, not overwrite `benchmark-v1`.

```sh
python evaluation/generate_benchmark.py --output /tmp/new-frozen-corpus
python evaluation/verify_benchmark_snapshot.py
```

The second command verifies committed snapshot digests and independently rescores
retained derivatives and decisions. It does not perform fresh API, worker,
PostgreSQL, browser or LedgerGuard execution.

## Evidence and measurement boundaries

Ground truth, family assignments, oracles, policy and freeze metadata are outside
`inputs/`. The replay imports only the public input contract and installs a
file-open tripwire denying other corpus files. SQLite replay additionally denies
socket connects and records attempts. These are process-local safeguards, **not
an OS sandbox**. The API has no GitHub/release mutation capability in this path.

Known-flake scenarios ingest five independent synthetic prior runs with explicit
synthetic prior reviews through the real API. Later observations are added after
the current analysis, and the history digest and substantive decision must remain
unchanged. This tests ingestion/review ordering, not a dated production backtest.
Prior runs, controls, retries and later probes do not inflate the 260-case count.

The held-out partition is also the declared unknown-family slice; it is not an
additional independent sample. Five substantive analyses are checked per case.
Case-level intervals and the family bootstrap describe this authored sample,
not an estimate of deployment accuracy.

Forty tagged inputs cover five text/canary classes. This is **not** the complete
master adversarial program: broader binary, malicious-archive, cross-project,
resource exhaustion, provider-output, filesystem/network isolation and nuanced
semantic attack evaluation still need their complete campaign. Existing security
regressions are retained separately. No prompt-injection immunity is claimed.

Generic claim support uses explicit controlled-scenario rubrics, not substring
presence or a model judging itself. Numeric claims are producer-bound and scored
independently. Quotation accuracy is undefined when no quoted claims are emitted,
not automatically 100%. Failed targets, abstentions, wrong classifications and
unknown compute cost remain visible. Zero external model requests does not imply
zero compute cost. Case/ingestion timing and peak process RSS are local
measurements, not load or production performance claims.

## Reviewer worksheet

Copy this worksheet outside the frozen corpus for each sampled case. Do not
silently edit labels, move a difficult family between splits, or overwrite a
previous report. Commit dated adjudication separately and create a new corpus
version when a label actually changes.

| Field | Reviewer entry |
|---|---|
| Opaque case ID and dataset version | |
| Original category, severity and family | |
| Artifact digests and exact cited observations inspected | |
| Missing evidence or contradictory interpretation | |
| Proposed category/family correction and rationale | |
| Reviewer identity, expertise and review date | |
| Agreement/disagreement with the agent-authored label | |
| New adjudication record/version | |

No human expert review or inter-rater agreement is claimed by the initial corpus.
Once a test error is used to tune the system, record that reuse: it becomes a
regression case and is not fresh generalization evidence.
