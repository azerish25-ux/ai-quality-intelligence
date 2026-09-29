# M6.3: frozen mixed-source five-category campaign

This is a public, agent-authored engineering benchmark, not an independently
blinded benchmark or a deployment guarantee. The complete M6 milestone remains
PARTIAL. Quality failures remain visible even when integrity verification passes.

## Dataset and split boundaries

The committed compact archive contains 264 cases in 87 explicitly catalogued
family groups. Sixty original LedgerGuard component observations and passing
controls retain their executed provenance and remain in development. Replaying
those artifacts does **not** constitute a new Java or HTTP/database execution.
The original execution archive and reports remain unchanged.

There are 204 synthetic cases: 192 cases in 72 new scenario groups, plus twelve
structured-measurement supplements for three already-inspected component
families. The supplements add neither new families nor real executions.

| Split | Product | Test | Infrastructure | Known flake | Insufficient | Total |
|---|---:|---:|---:|---:|---:|---:|
| Development | 72 | 0 | 0 | 0 | 0 | 72 |
| Calibration | 8 | 6 | 6 | 6 | 6 | 32 |
| Test | 40 | 30 | 30 | 30 | 30 | 160 |

All 160 test cases are synthetic and belong to 60 groups not used in development
or calibration, including twenty product groups. Overall counts are 120 product
cases and 36 cases in each other category. The group catalogue documents the
mechanism/rationale and is agent-reviewed; structural checks cannot prove
conceptual independence or expert adjudication.

`freeze.json` binds the input manifest, label schema instances, group catalogue,
acceptance policy, generator file digests, seed and retained execution provenance.
The public manifest contains no labels, family names, oracle values or split
assignments. Artifacts have opaque IDs and digests. Near-duplicate XML and family
cross-split checks are tripwires, not universal semantic duplicate detection.
The corpus and acceptance policy are committed before the final test replay.
Inspected examples must subsequently be described as regression evidence, not a
fresh generalization result. Never move examples or weaken thresholds to improve
a score.

## Three new structured diagnostic contracts

A manifest `2.0` bundle can add a required `contract-observations-json` input with
`correlates_to` naming exactly one primary report input. Its strict
`contract-observations-v1` record contains `test_identity`, `attempt`, `browser`
and a discriminated measurement:

* `operation_isolation`: same actor and payload, different operations, and the
  measured fingerprints under an explicit `fingerprint_scope: operation_actor_payload`
  contract. A payload-only fingerprint is not diagnosed as faulty merely because
  two operations share it.
* `projection_ordering`: one entity's before/incoming/after versions and state
  digests under an explicit ignore-stale policy.
* `weekly_recurrence`: previous and next local dates, a timezone, and a
  preserve-wall-time weekly contract. Calendar arithmetic is used, not an assumed
  168-hour interval. Ambiguous/nonexistent local times require more policy and
  do not generate confident blame.

An input binds to one matching execution, not every failure in its run. Governed
safe derivatives retain source digests; redundant measurement copies are removed
from public input metadata. The publication validator recomputes the predicate
and requires exact bounded claim wording. Missing, malformed, conflicting or
cross-execution evidence cannot justify the new diagnosis. A conforming contract
is not proof that the whole application or failure is harmless.

These capabilities are tested with synthetic measurements. The older twelve
component abstentions remain in the historical report: this work does not invent
missing measurements in their original artifacts or claim they have all been
resolved by a new real companion execution.

## Reproduction

Install the backend dependencies and use an **empty, disposable** database and
private artifact directory. The replay refuses existing projects, non-demo mode,
existing output directories, and a destination inside the corpus.

```sh
python -m pip install './backend[dev]'
python evaluation/verify_campaign.py --output /tmp/failurelens-m63/corpus
# Set FAILURELENS_DATABASE_URL, FAILURELENS_ARTIFACT_ROOT and FAILURELENS_DEMO_MODE=true.
# For PostgreSQL, migrate it first: (cd backend && alembic upgrade head).
python evaluation/replay_campaign.py --inputs /tmp/failurelens-m63/corpus/inputs \
  --output /tmp/failurelens-m63/replay --confirm-disposable-database
python evaluation/campaign_harness.py --corpus /tmp/failurelens-m63/corpus \
  --replay /tmp/failurelens-m63/replay --output /tmp/failurelens-m63/report
```

The verifier checks frozen bytes; it does not execute inference or the companion.
The generator is a separate engineering tool, not a way to silently replace the
retained benchmark. Reproduction uses the retained archive, not a regenerated
corpus whose source digest may differ.

The runner uses actual API requests, durable worker jobs, idempotent reimports,
normal evidence validation and five recomputed analyses. Each case has its own
project to prevent unrelated split histories from mixing. Synthetic flake
fixtures include five prior runs with a prior attributable review and an explicit
future run/review. An offline fixture clock is applied before initial analysis;
there is no production backdating endpoint. The scorer checks that future context
was excluded and qualifying history actually persisted.

Labels and scoring run separately from inference. File-open tripwires deny
private corpus files and generators; Python network/subprocess guards record
attempts. These are **not** an OS sandbox and do not prove universal native-code
network isolation. No external model is requested. External API spend is zero;
compute cost is not measured.

The independent scorer checks source/input identity, role and history receipts,
five exact repetition hashes, authorized exported derivative records, producer
input digests, bounded wording and independently recomputed contract relations.
Generic classification support uses the explicitly labelled controlled scenario
rubric; it is not a universal semantic judge. Citation resolution, quotation
accuracy and controlled claim support are reported separately.

## Results, CI and reviewer view

`campaign-evaluation.yml` uses PostgreSQL, retains exact-source replay/evidence
and report artifacts, and tests desktop/narrow Chromium against the real API.
Its default scorer enforces integrity and mandatory safety. Use a **new** output
directory with `--enforce-quality` to also fail with exit 2 when a quality target
fails. Green scoped CI is not full M6 acceptance. The unchanged recall, macro F1,
coverage and dangerous-dismissal targets are stored with the corpus.

`GET /api/v1/evaluations/campaign` is an authenticated, bounded, regular-file
report endpoint. Configure `FAILURELENS_CAMPAIGN_EVALUATION_METRICS_PATH` for a
fresh report. The dashboard distinguishes the synthetic test denominator from
retained development executions, displays the tested source and frozen manifest,
and preserves per-category scores, confusion counts, all test errors, failed
targets and limitations. Retained UUIDs refer to the originating database, not
unrelated new runtime data.

## Remaining limits

The textual adversarial slice covers 72 variants across eight classes. It does
not complete every attack class in the master prompt. The family-disjoint slice
and future-history checks are not a production temporal backtest. Independent
human adjudication, broader semantic claim evaluation, full adversarial/resource
coverage, measured deployment behavior and passing all quality targets remain
separate work. Existing M6.1 and M6.2 evidence is preserved independently.
