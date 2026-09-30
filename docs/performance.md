# Compatible performance baselines and regression findings

Loose Thread treats performance as an evidence and cohort-compatibility problem, not as a comparison between any two numbers that happen to share a label. The deterministic performance engine is CPU-only and uses the same persisted runs, inputs, artifacts, evidence and project boundaries as failure triage.

## Normalized observations

Ingestion persists two performance sources as first-class `performance_observations`:

- the final attempt duration for each logical test/browser execution; and
- every bounded numeric value exported by a k6 `handleSummary` metric, including the exported statistic, metric type, unit, threshold state and sample count where available.

Each observation records the project, run, manifest input, execution where applicable, safe evidence ID, source digest and locator, producer/version, workload, statistic, metric direction, original value/unit, explicitly converted canonical value/unit and a canonical compatibility-dimension signature. Raw source bytes remain governed by the normal artifact restrictions; performance findings cite approved safe evidence derivatives.

Only explicit conversions are supported. Time units normalize to milliseconds, byte units to bytes, and percentages to ratios. Unsupported conversions are rejected rather than guessed.

## Immutable policy

A project may register immutable, versioned performance policies. A policy defines:

- relative and absolute tolerances;
- the minimum number of independent prior runs;
- maximum baseline age;
- whether trusted comparison provenance is required;
- compatibility dimensions; and
- optional metric-name direction overrides.

Reusing a policy version with different content is rejected. The default strict policy requires three compatible prior runs no older than 30 days, trusted comparison metadata, and matching repository, workload, environment, browser, run scope, producer/version, load profile, region and executor.

## Prior-only baseline selection

For a current observation, the engine establishes an immutable cutoff from the current run and searches only earlier observations in the same project. It then rejects candidates when any required condition differs or is unsafe, including:

- repository, metric scope, statistic, unit or direction;
- workload or any policy compatibility dimension;
- incomplete runs;
- untrusted comparison provenance when required;
- observations at or after the current cutoff;
- stale observations;
- missing evidence; or
- duplicate observations from the same run.

One independent run contributes at most one observation. Every accepted member and bounded rejected-candidate reason is persisted in an immutable `performance_baseline_snapshots` row. The baseline value is the median of compatible **run-level observations**. For exported p95/p99 values, this is explicitly a median of run-level percentile observations; it is never represented as an aggregate percentile.

Persisted baseline states are:

- `AVAILABLE` — the compatibility policy and minimum support are satisfied;
- `BASELINE_UNAVAILABLE` — no usable baseline or insufficient compatible support exists; or
- `INCOMPATIBLE_BASELINE` — candidate/current provenance or dimensions violate the policy.

Missing or incompatible history is never converted to “no regression.”

## Deterministic findings

With an available baseline, the engine reports:

- `REGRESSION`;
- `IMPROVEMENT`;
- `WITHIN_TOLERANCE`; or
- `INCONCLUSIVE` when metric direction is not known.

Every comparison persists the current and baseline values, absolute/relative change, run and sample counts, configured tolerances, producer threshold state, robust median absolute deviation when available, compatibility details, confounders, exact current/baseline evidence IDs and a next-measurement recommendation.

The engine never infers statistical significance from one current summary and one baseline summary. It exposes robust standardized change only when a repeated compatible baseline permits that context, and still records `significance_claimed: false`. Producer thresholds remain separate evidence: a passed producer threshold can coexist with a baseline regression, and a failed threshold without a compatible baseline does not prove attribution.

## Finite arithmetic and historical results

Engine `performance-engine-v2` binds `performance-arithmetic-v2` into baseline and
comparison provenance. Even-sized medians use an overflow-safe exact-ratio mean;
MAD and complete change/tolerance/effect expressions use ratios of the accepted
finite floats before their final floating-point conversion. This avoids both
overflowing an intermediate sum/product and discarding a representable result.
It does not add precision to the original producer measurements.

Nonfinite policy values and unit conversions are rejected. Required calculations
that would produce a nonfinite result fail explicitly; they are not clipped or
replaced with favorable zeros. Failed run comparison batches leave no partial
baseline/comparison rows. Relative change is still undefined for a zero baseline,
and a zero MAD does not support a standardized-effect claim.

Existing observations, baselines and comparisons are not rewritten. Recomputing
under v2 creates separate version-bound snapshots and is idempotent for the same
inputs. Historic nonfinite calculations, and the known v1 finite-zero effect
caused by an overflowing denominator, receive an explicit unavailable projection.
Ordinary valid v1 results remain readable. Public reads carry `numeric_state` and
`numeric_reasons`; invalid baselines/comparisons show `NUMERIC_UNAVAILABLE`, retain
their recorded status, ID and provenance, and use null for unavailable derived
values. Original finite measurements and evidence references remain inspectable.
Policy and observation-only reads expose the same numeric-state contract.

API clients must handle nullable numeric fields rather than interpreting null as
zero. Reports preserve all-version stored counts, distinguish recorded and shown
status, and hold for unavailable arithmetic or omitted validation details. New
numeric projections are included in the report digest, so old preview approvals
cannot silently authorize a changed report. Evidence availability is checked
separately; numeric validity does not grant access to an unavailable artifact.

The dashboard labels unavailable values and uses bounded scientific notation for
extreme finite values. Percentage formatting preserves a finite ratio even when
multiplying it by 100 would overflow the display number type. These are display
choices; stored measurements and exported numeric values are unchanged.

The [delivery ledger](PROGRESS.md) records reproduced failures and the exact tested
source. Focused arithmetic and projection tests do not establish full-project
acceptance, stable operational latency or population-level statistical accuracy.

## API

```text
POST /api/v1/projects/{project_id}/performance-policies
GET  /api/v1/projects/{project_id}/performance-policies
GET  /api/v1/runs/{run_id}/performance-observations
POST /api/v1/projects/{project_id}/performance-baselines
GET  /api/v1/performance-baselines/{baseline_id}
POST /api/v1/runs/{run_id}/performance-comparisons
GET  /api/v1/runs/{run_id}/performance-comparisons
GET  /api/v1/performance-comparisons/{comparison_id}
```

The run comparison operation accepts an optional immutable policy ID and optional observation IDs. Omitting observation IDs compares every normalized performance observation in the run. Omitting the policy ID uses or creates the project’s strict default policy.

## CLI

```bash
failurelens performance --run <run-id>
failurelens performance --run <run-id> --policy <policy-id>
failurelens performance --run <run-id> --observation <observation-id>
```

The CLI invokes the same persistence and comparison engine as the API and dashboard.

## Dashboard

The performance workspace shows normalized observations, policy provenance, current and baseline values, absolute and relative deltas, tolerances, current/baseline sample and run counts, rejected-candidate reason counts, confounders, exact evidence links and the recommended next measurement. It does not hide unavailable baselines behind favorable zeros.

## Controlled evaluation

`evaluation/generate_performance_corpus.py` creates 20 synthetic cases spanning regression, improvement, tolerance, missing/stale baselines, workload/environment/unit/statistic incompatibility, supported unit conversion, incomplete and untrusted runs, future-data leakage, single-pair uncertainty, repeated distributions, percentile anti-aggregation, threshold attribution and project isolation.

`evaluation/performance_harness.py` executes the runtime compatibility/classification semantics and emits predictions, machine-readable metrics and a Markdown report. The committed fixture currently reports:

- status accuracy 1.000;
- regression recall 1.000;
- compatibility-selection accuracy 1.000;
- evidence-citation validity 1.000;
- deterministic repeat agreement 1.000;
- zero dangerous false negatives across five regression cases;
- zero statistical-significance claims; and
- zero non-median baseline aggregations.

These are synthetic agent-authored regression-fixture results, not production accuracy, throughput or population-level guarantees.

## Known limits

- k6 summary quantiles do not contain raw samples and cannot be reconstructed into an aggregate quantile.
- Test-duration observations represent the final attempt; retry history remains separately available in execution/history data.
- Compatibility is deterministic and policy-driven; it does not establish causal attribution.
- Infrastructure-event correlation is a separate signal and does not prove causality.
- Project-scoped roles and evidence availability remain separate access boundaries.
