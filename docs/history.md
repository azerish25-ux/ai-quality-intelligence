# Historical test intelligence

FailureLens computes historical statistics from persisted test executions. The implementation is deterministic, project-scoped, cutoff-bound, and traceable to exact run and execution IDs. History is supporting evidence only: it cannot erase contradictory current-run product-risk evidence or approve a release.

## Identity and cutoff

A historical query starts from one selected execution and matches the exact logical identity formed from:

- project;
- repository;
- report framework;
- test identity;
- suite;
- relative source path; and
- parameterization.

The selected execution's run timestamp is the default analysis cutoff. Runs at or after that timestamp are excluded, as are reviews created at or after the cutoff. The current run is explicitly excluded. An API caller may request an earlier cutoff but cannot move it later than the selected execution. Cross-project, cross-repository, and cross-framework records never enter the calculation.

## Independent observations

Attempts are ordered inside each run and browser cohort. One run/browser cohort contributes one traceable observation with:

- first-attempt outcome;
- final outcome;
- attempt numbers and execution IDs;
- retry-recovered state;
- duration;
- branch, environment, run scope, worker count and shard count; and
- a timezone-aware local time bucket.

Retries are not independent runs. Overall rates collapse browser cohorts into one conservative outcome per run: any browser failure makes the run-level outcome failed, while unavailable outcomes remain outside the pass/fail denominator. Browser-specific breakdowns retain one observation per run/browser cohort. A run where the test is absent is reported as a comparable run without an observation; it is never converted into a pass. Skipped, cancelled and unknown outcomes remain visible but are excluded from pass/fail denominators.

## Rates and denominators

The API returns each rate as a structured object containing the numerator, denominator, value, 95% Wilson interval, minimum-support rule, status and definition.

- **Observed pass rate:** independent runs whose conservative final outcome passed divided by independent runs whose final outcome was pass or fail.
- **First-attempt failure rate:** independent runs whose conservative first-attempt outcome failed divided by independent runs whose first-attempt outcome was pass or fail.
- **Final failure rate:** independent runs whose conservative final outcome failed divided by independent runs whose final outcome was pass or fail.
- **Retry-recovery rate:** independent runs whose conservative first-attempt outcome failed and final outcome passed divided by all independent runs whose first-attempt outcome failed.

Rates with fewer than three denominator runs are marked `insufficient_data`; they are still shown with their exact counts. The history report also exposes outcome counts, sample sizes, consecutive sequences, transition counts, failure-recurrence intervals and breakdowns by browser, branch, environment, run scope, worker count, shard count and local time bucket.

## Selection bias and known-flake safety

Runs carry an explicit `run_scope`:

- `full_suite`;
- `impact_selected`; or
- `unknown`.

The general history API may compare scopes, but selected-subset and unknown-scope observations produce visible safety warnings. The deterministic analyzer uses only the same browser, branch, environment, worker count, shard count and `full_suite` history.

A history snapshot is eligible to support `known_flake` only when all of these are true:

1. At least five prior independent runs and five prior pass/fail observations exist in the compatible full-suite cohort.
2. At least one prior pass and one prior failure exist.
3. No included run is partial, selected-subset, unknown-scope, duplicate-attempt or truncated by the execution, run or review safety limits.
4. A qualifying prior reviewer decision recording `known_flake` for the same logical test and strict failure fingerprint occurred before the cutoff in the same cohort, and no later pre-cutoff review revision superseded it.
5. Current-run deterministic policy does not find contradictory product-risk evidence.

A review annotates the history but never changes observed outcomes. Repeated failures without a pass cannot become a reassuring known-flake classification merely because someone added a label.

## Reproducibility

Every report includes:

- `history-v1` policy version;
- logical-test key;
- exact cutoff and filters;
- contributing run/execution references;
- qualifying review-event IDs;
- a canonical `history_input_digest`; and
- explicit reasons the history is not reassurance-safe.

The history digest is included in the deterministic analysis input and provenance. When eligible prior data or review state changes, FailureLens creates a new analysis revision rather than silently changing an earlier result.

## API

```http
GET /api/v1/tests/{execution_id}/history
```

Optional query parameters are `after`, `before`, `browser`, `branch`, `environment`, `run_scope`, `worker_count`, `shard_count`, `timezone`, `limit` and `offset`. `before` is clamped to the selected execution's run time. Invalid timezones or a window whose `after` is not earlier than the effective cutoff return `422`.

The dashboard uses this endpoint for a prior-only history workspace with exact counts, cohort filters, observation navigation and safety explanations.

## Current limitation

This checkpoint does not yet correlate history with a separately modeled infrastructure-event stream. Reviewer writes still use the repository's existing token boundary rather than project-scoped verified reviewer identities; role enforcement remains M5 work. Change-impact selection and performance-baseline comparison are also separate remaining M4 work.
