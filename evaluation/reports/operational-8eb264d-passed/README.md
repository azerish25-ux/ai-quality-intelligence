# Passing read measurement at 8eb264d

Source [`8eb264d459ee0e16ed27b1c0a6c4cc33a32e5b32`](https://github.com/azerish25-ux/ai-quality-intelligence/tree/8eb264d459ee0e16ed27b1c0a6c4cc33a32e5b32),
[workflow 36775868899](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36775868899),
attempt 1, job `110093489985`, artifact `11125802822`.
The completed workflow conclusion is `success`; its source and artifact agree.

Original ZIP: 11,772 bytes; SHA-256 matched GitHub's artifact digest:
`f05415d6db999107d3a82eb1b2adaafb667e2d439750ef4b78bb3b0c0c2593ab`.

Retained byte-for-byte:

- `metrics.json`: 4,276 bytes; SHA-256
  `d3158a2e38332449d937103bfe0b5c5ee331a60c3a23b112084f05657da82c0e`
- `requests.json`: 18,463 bytes; SHA-256
  `ba45a60fe94f9eecc7dc2a835bce64a8f0ce695fd3f92e190f7c5315ce205fc9`

The unchanged workload contains 1,000 synthetic runs / 50,000 executions, four
cold reads at concurrency one and 200 warm reads at concurrency ten, with 50 warm
reads per route. All 204 requests succeeded. Independently recomputed nearest-rank
warm p95 is **457.72 ms**, below the unchanged 500 ms target. Warm p50 is
220.255593 ms. Measurement and cleanup completed without errors.

Actual runner: Intel Xeon Platinum 8573C, four reported logical CPUs, Linux
6.17.0-1022-azure, Python 3.13.15 and PostgreSQL 17.11. Runtime source, benchmark
code and operational workflow are byte-identical to the preceding
[`be7eede` failure](../operational-be7eede-failed/README.md), which measured
607.658224 ms on AMD EPYC 7763. This passing observation establishes neither a
code speedup nor stable compliance. Both measurements remain preserved.

This is synthetic API read evidence, not classification or ingestion-throughput
acceptance. Hardware is not normalized to the two-vCPU/four-GiB reference. HTTP
timing includes connection overhead; database/whole-stack memory and failure-heavy
load remain unmeasured. Only original metrics and request rows are published;
the API log is excluded. ZIP CRC, source/workload identity, complete phase counts,
bounded sample timings and percentile recomputation were checked before retention.
