# Failed read measurement at fa8cb02

Source [`fa8cb02ff6cbe468c64b93d812f86f75cb95549e`](https://github.com/azerish25-ux/ai-quality-intelligence/tree/fa8cb02ff6cbe468c64b93d812f86f75cb95549e),
[workflow 36800144090](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36800144090),
attempt 1, job `110172412877`, artifact `11135830037`.
The completed workflow conclusion is `failure`; its source and artifact agree.

Original ZIP: 11,893 bytes; SHA-256 matched GitHub's artifact digest:
`954768307419f2639784ada91546b90a804b7c9db8f373beeddfb5d00ed5549e`.

Retained byte-for-byte:

- `metrics.json`: 4,482 bytes; SHA-256
  `17e96d20fe67e1231fe113005896d4d63a583759c8f4e7945eb8de15714ea880`
- `requests.json`: 18,445 bytes; SHA-256
  `8e7feeaa92a2109e4f02cbd0c0b29a8c295d9b9175449a841934b8ce6775c2b5`

The unchanged workload contains 1,000 synthetic runs / 50,000 executions, four
cold reads at concurrency one and 200 warm reads at concurrency ten, with 50 warm
reads per route. All 204 requests succeeded. Independently recomputed nearest-rank
warm p95 is **647.510596 ms**, failing the unchanged 500 ms target. Warm p50 is
256.564744 ms. Measurement and cleanup completed without errors.

Actual runner: AMD EPYC 9V74 80-Core Processor, four reported logical CPUs.
The original launch declaration records one API worker, no reload and exclusion
of `WEB_CONCURRENCY`/`UVICORN_*` overrides. This declares configuration rather than
a process census. Runtime, benchmark and workflow are byte-identical to the
[448.57 ms pass at 177eb49](../operational-177eb49-passed/README.md), which reports
the same CPU model. CPU model alone therefore does not separate passing and
failing observations. Neither a code speedup nor the sole cause of variation is
established. Every earlier result remains retained, and stable/reference-resource
acceptance remains open.

Only original metrics and request rows are published. The API log is excluded.
ZIP CRC, source/workload identity, complete phase counts and percentile
recomputation were checked before retention.
