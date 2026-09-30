# Synthetic history walkthrough

Run explicitly in a demo stack:

```sh
docker compose exec api failurelens demo-history
```

This creates a separate `synthetic-history-v1` project. It never replaces existing
projects or runs, and rerunning the command is idempotent. Production mode refuses
this command. The seed is fixed to January 1–April 10, 2026 (UTC), with 100 runs,
1,000 logical test/browser observations, and additional retry attempts. It includes
three browsers, two branches, worker/shard dimensions, full/selected scope, missing
required inputs, skipped/cancelled outcomes and a fixed synthetic time span.
Its project explicitly keeps demonstration evidence for 3,650 days; this does not
change other projects' retention policies.

Select the returned project and final run in the dashboard. The final run contains:

- A product-defect observation with a measured data-integrity assertion
- Known flaky behavior backed by matching prior pass/fail history and a clearly
  synthetic reviewed harness explanation, not a retry-pass shortcut
- A selector timeout that correctly remains insufficient evidence

The historical review is synthetic fixture data, not independently adjudicated or
human-reviewed evidence. Cohorts still require matching browser, branch, environment,
worker count and scope. The seed initially failed to qualify its flaky case because
its failing prior runs had a different worker count; the generator now supplies a
legitimate matching prior cohort without changing that safety policy.

These are dashboard/history demonstration records. They are not additional labeled
root causes and never increase the benchmark denominator. Tests verify exact counts,
cohort-sensitive classifications, incomplete/skip/cancel states, idempotence and
production-mode rejection.
