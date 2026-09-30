# Passing read measurement at c27e2e5

Source [`c27e2e543b7f9b044b976d90625098b6888a0827`](https://github.com/azerish25-ux/ai-quality-intelligence/tree/c27e2e543b7f9b044b976d90625098b6888a0827),
[workflow 36785637342](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36785637342),
attempt 1, job `110126253277`, artifact `11129288759`.
The completed workflow conclusion is `success`; its source and artifact agree.

Original ZIP: 11,838 bytes; SHA-256 matched GitHub's artifact digest:
`5ab4271c5e8c7a061842f2adef1e683c28a425a3b8fd715c3690ad96af9c0e50`.

Retained byte-for-byte:

- `metrics.json`: 4,462 bytes; SHA-256
  `9f784dc851ea26d5f211b617aa92cf28d5e573441a7286b870a2e49aa35dd42b`
- `requests.json`: 18,447 bytes; SHA-256
  `20bc60ac2f2ca4d4a0d42190845814ed734d5cc7c3db9cf44f17ec5da9b0bbe7`

The unchanged workload contains 1,000 synthetic runs / 50,000 executions, four
cold reads at concurrency one and 200 warm reads at concurrency ten, with 50 warm
reads per route. All 204 requests succeeded. Independently recomputed nearest-rank
warm p95 is **386.738934 ms**, below the unchanged 500 ms target. Warm p50 is
189.964675 ms. Measurement and cleanup completed without errors.

Actual runner: Intel Xeon 6973P-C, four reported logical CPUs, Linux
6.17.0-1022-azure, Python 3.13.15 and PostgreSQL 17.11. The new launch declaration
records one API worker, no reload and exclusion of `WEB_CONCURRENCY`/`UVICORN_*`
overrides from the child environment. This is declared configuration rather than
a measured process census. Earlier measurements retain their original metadata.

These are synthetic API reads on hardware not normalized to the two-vCPU/four-GiB
reference. HTTP timing includes connection overhead; database/whole-stack memory
and failure-heavy load remain unmeasured. Every earlier passing and failing
measurement is preserved. This observation establishes neither a causal speedup
nor stable/reference-resource acceptance.

Only original metrics and request rows are published. The API log is excluded.
ZIP CRC, source/workload identity, complete phase counts, bounded sample timings
and percentile recomputation were checked before retention.
