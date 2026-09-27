# Infrastructure-event correlation

FailureLens correlates prior test outcomes with independently recorded infrastructure events without treating temporal proximity as proof of cause. The implementation is deterministic, project-scoped, prior-only, and built on the same run-level history aggregation used by the test-history API.

## Event identity and provenance

Infrastructure events are first-class records, not labels copied from a failing test. A producer supplies a stable `producer_event_id`; the project, producer, and producer event ID form the idempotency identity. Reusing that identity with different content is rejected.

Each event records:

- project, repository, and environment scope;
- producer and producer event ID;
- event kind, severity, lifecycle status, start/end time, and independent record time;
- optional workflow, runner, runner group, region, worker, and shard context;
- source trust, canonical source digest, metadata, and optional approved evidence ID.

Eligible trusted sources are `authenticated_lookup`, `trusted_workflow`, and `verified_monitor`. `self_reported`, `artifact_derived`, and `unknown` events remain auditable but cannot enter an exposed cohort. An uploaded report therefore cannot claim that its own failure was infrastructural and then use that claim as independent corroboration.

The initial event taxonomy is:

- `runner_terminated`;
- `runner_unavailable`;
- `service_outage`;
- `database_connection_exhaustion`;
- `dns_failure`;
- `tls_failure`;
- `network_degradation`;
- `storage_exhaustion`;
- `resource_contention`;
- `deployment_event`;
- `dependency_outage`;
- `rate_limit_event`; and
- `unknown_infrastructure_event`.

Resolved events cannot claim an end state before that end was independently recorded. Events starting or recorded at or after the selected analysis cutoff are excluded.

## Cohort compatibility

A correlation starts from one selected execution and reuses the exact prior-only logical-test history calculation. Attempts and browser observations collapse to one conservative final outcome per independent run. Missing tests are not passes, while skipped, cancelled, and unknown outcomes remain visible outside pass/fail denominators.

An event may expose a historical run only when:

- it belongs to the same project;
- repository and environment match exactly;
- optional worker, workflow, runner, runner-group, and region context is compatible;
- its interval overlaps the run interval within the versioned bounded window; and
- both its start and independent record time precede the cutoff.

Rejected events retain explicit reasons such as `untrusted_event_source`, `repository_mismatch`, `environment_mismatch`, `worker_count_mismatch`, `region_mismatch`, `workflow_mismatch`, `runner_mismatch`, `runner_group_mismatch`, `outside_run_window`, or `no_compatible_history_run`.

## Rates and interpretation

For the exposed and unexposed cohorts FailureLens returns:

- run and pass/fail denominator counts;
- passed, failed, skipped, cancelled, and unknown outcomes;
- failure rate with a 95% Wilson interval and minimum-support status;
- absolute failure-rate difference; and
- relative risk when the unexposed rate is nonzero.

The same calculation is repeated per accepted event kind. Runs overlapping multiple kinds are counted once in the overall exposed cohort, identified as confounded, and produce `CONFOUNDED` unless the caller filters to one event kind.

Possible result states are:

- `AVAILABLE`;
- `INSUFFICIENT_DATA`;
- `NO_MATCHING_EVENTS`;
- `INCOMPATIBLE_CONTEXT`;
- `UNTRUSTED_EVENT_SOURCE`;
- `CONFOUNDED`; and
- `TRUNCATED`.

`AVAILABLE` means only that the exposed and unexposed cohorts satisfy the deterministic support and compatibility policy. It does not mean the event caused the failures. FailureLens sets `causality_claimed: false` and `can_independently_authorize_infrastructure_classification: false` for every result. Correlation never removes product-risk evidence, changes a classification on its own, or supplies release authorization.

## Immutable snapshots

A persisted snapshot stores:

- policy and engine versions;
- selected run/execution and prior-only cutoff;
- the underlying history digest;
- event filters, window, and minimum support;
- accepted event IDs and rejected events with reasons;
- exact run/execution members and exposure state;
- rates, event-kind associations, confounders, and safety flags; and
- a canonical input digest.

Replaying identical inputs reuses the same project-scoped snapshot. New history, event state, cutoff, filter, or policy inputs produce a different digest rather than silently mutating an earlier result.

## API and CLI

```http
POST /api/v1/projects/{project_id}/infrastructure-events
GET  /api/v1/projects/{project_id}/infrastructure-events
GET  /api/v1/infrastructure-events/{event_id}
POST /api/v1/tests/{execution_id}/infrastructure-correlations
GET  /api/v1/infrastructure-correlations/{snapshot_id}
GET  /api/v1/tests/{execution_id}/history
```

The history response contains a live, non-persisted `infrastructure_correlations` section for the selected cohort. The correlation POST persists an immutable snapshot.

```bash
failurelens infrastructure-event event.json --project my-project
failurelens infrastructure-correlate --execution <execution-id> --event-kind service_outage --window-seconds 900 --minimum-support 3
```

The dashboard shows trusted event evidence, exact exposed/unexposed denominators, rates, event-kind associations, confounders, rejected context, provenance, and a control to persist the displayed calculation.

## Evaluation boundary

The committed 18-case controlled fixture exercises trusted and untrusted sources, repository/environment/worker isolation, future-event exclusion, bounded windows, event-kind confounding, retry collapse, skipped/cancelled/unknown accounting, cross-project isolation, immutable replay, and product-defect preservation. It reports perfect deterministic fixture accuracy with zero future/cross-project leakage, zero unsupported causality claims, and zero product-defect downgrades. The fixture is synthetic and does not establish causal validity or production prevalence.
