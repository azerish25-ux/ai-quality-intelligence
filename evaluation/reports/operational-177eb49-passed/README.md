# Passing read measurement at 177eb49

Source [`177eb49e3b2195c54662c545db3ee375d9814ee5`](https://github.com/azerish25-ux/ai-quality-intelligence/tree/177eb49e3b2195c54662c545db3ee375d9814ee5),
[workflow 36795872586](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36795872586),
attempt 1, job `110159051953`, artifact `11133547489`.
The completed workflow conclusion is `success`; its source and artifact agree.

Original ZIP: 11,856 bytes; SHA-256 matched GitHub's artifact digest:
`6331af2f5d95ce468800907ba8e8fad6f5c3ff9d33c4fe4af979317c7f3d0312`.

Retained byte-for-byte:

- `metrics.json`: 4,479 bytes; SHA-256
  `a893bb29074fe2c11b57facc8b239ee7b0dbac7c99d24bea35fdf6dc6f3cff2e`
- `requests.json`: 18,469 bytes; SHA-256
  `acf4380e139bad09cbf6561df06c70727772bd66f10f5991ccc94be28d5808c1`

The unchanged workload contains 1,000 synthetic runs / 50,000 executions, four
cold reads at concurrency one and 200 warm reads at concurrency ten, with 50 warm
reads per route. All 204 requests succeeded. Independently recomputed nearest-rank
warm p95 is **448.566492 ms**, below the unchanged 500 ms target. Warm p50 is
186.962914 ms. Measurement and cleanup completed without errors.

Actual runner: AMD EPYC 9V74 80-Core Processor, four reported logical CPUs.
The original launch declaration records one API worker, no reload and exclusion
of `WEB_CONCURRENCY`/`UVICORN_*` overrides. This declares configuration rather than
a process census. Runtime, benchmark code and workflow are byte-identical to the
preceding [570.77 ms failure at 891f1e9](../operational-891f1e9-failed/README.md).
Every earlier observation remains retained. This passing observation is not a
code speedup or stable/reference-resource acceptance; the measured runner is not
normalized to the two-vCPU/four-GiB reference, and failure-heavy load remains open.

Only original metrics and request rows are published. The API log is excluded.
ZIP CRC, source/workload identity, complete phase counts and percentile
recomputation were checked before retention.
