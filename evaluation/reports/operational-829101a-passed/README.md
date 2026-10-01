# Passing read measurement at 829101a

Source [`829101a686acda52b6c498939ef54666bed373d8`](https://github.com/azerish25-ux/ai-quality-intelligence/tree/829101a686acda52b6c498939ef54666bed373d8),
[workflow 36805858144](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36805858144),
attempt 1, job `110189916950`, artifact `11137975374`.
The completed workflow conclusion is `success`; its source and artifact agree.

Original ZIP: 11,828 bytes; SHA-256 matched GitHub's artifact digest:
`1333abdb71c57a676cd1ac9f0ea2c493f0184cee0986d85e987ef86a09503f74`.

Retained byte-for-byte:

- `metrics.json`: 4,483 bytes; SHA-256
  `51fbd3fca9215a08ab1d67ba44d9f3c5382bddfe74d78c35f01b25de49adbefa`
- `requests.json`: 18,474 bytes; SHA-256
  `597ff69eaa91fd8c7e8ad0a4cdfb323f140400ccf443d887280a35b8fa1c737e`

The unchanged workload contains 1,000 synthetic runs / 50,000 executions, four
cold reads at concurrency one and 200 warm reads at concurrency ten, with 50 warm
reads per route. All 204 requests succeeded. Independently recomputed nearest-rank
warm p95 is **371.285115 ms**, below the unchanged 500 ms target. Warm p50 is
157.755033 ms. Measurement and cleanup completed without errors.

Actual runner: AMD EPYC 9V45 96-Core Processor, four reported logical CPUs.
The original launch declaration records one API worker, no reload and exclusion
of `WEB_CONCURRENCY`/`UVICORN_*` overrides. This declares configuration rather than
a process census. Runtime, benchmark and operational workflow are unchanged from
the preceding 536.40 ms failure. Every prior result remains retained. This is
neither a code speedup nor stable/reference-resource acceptance. No CPU counters
were captured in this revision and none are reconstructed retrospectively.

Only original metrics and request rows are published. The API log is excluded.
ZIP CRC, source/workload identity, complete phase counts and percentile
recomputation were checked before retention.
