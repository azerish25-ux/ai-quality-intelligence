# Failed read measurement at ef9f366

Source [`ef9f3667bacd1cfd6947062065ef0bc88b4cf52a`](https://github.com/azerish25-ux/ai-quality-intelligence/tree/ef9f3667bacd1cfd6947062065ef0bc88b4cf52a),
[workflow 36803188837](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36803188837),
attempt 1, job `110181835596`, artifact `11136730743`.
The completed workflow conclusion is `failure`; its source and artifact agree.

Original ZIP: 11,898 bytes; SHA-256 matched GitHub's artifact digest:
`e092a847e99f6308b590d2c28aaa9119e7a5e2c276e75c56e8d59e79c6b7d1e3`.

Retained byte-for-byte:

- `metrics.json`: 4,482 bytes; SHA-256
  `4d4b9952b12acad73b6d5f5d492beb253b9c3f36ba8a3b09f8dccbff9a601e0f`
- `requests.json`: 18,453 bytes; SHA-256
  `21560807560634c4110e2a1cd878980284b5639c72d4bcc6ee9a3b4e6faf9a99`

The unchanged workload contains 1,000 synthetic runs / 50,000 executions, four
cold reads at concurrency one and 200 warm reads at concurrency ten, with 50 warm
reads per route. All 204 requests succeeded. Independently recomputed nearest-rank
warm p95 is **536.395402 ms**, failing the unchanged 500 ms target. Warm p50 is
226.864734 ms. Measurement and cleanup completed without errors.

Actual runner: AMD EPYC 7763 64-Core Processor, four reported logical CPUs.
The original launch declaration records one API worker, no reload and exclusion
of `WEB_CONCURRENCY`/`UVICORN_*` overrides. This declares configuration rather than
a process census. Runtime, benchmark and workflow are unchanged from the previous
observation. Every earlier passing and failing result remains retained. No code
speedup or sole cause of variation is established; stable/reference-resource
acceptance remains open.

Only original metrics and request rows are published. The API log is excluded.
ZIP CRC, source/workload identity, complete phase counts and percentile
recomputation were checked before retention.
