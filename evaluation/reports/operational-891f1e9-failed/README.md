# Failed read measurement at 891f1e9

Source [`891f1e9cbe3109e68ecd5ad996f78b57066daafc`](https://github.com/azerish25-ux/ai-quality-intelligence/tree/891f1e9cbe3109e68ecd5ad996f78b57066daafc),
[workflow 36792456210](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36792456210),
attempt 1, job `110148268589`, artifact `11132204171`.
The completed workflow conclusion is `failure`; its source and artifact agree.

Original ZIP: 11,875 bytes; SHA-256 matched GitHub's artifact digest:
`9ba11abfbbdcf92b9c99808e64317a9bccfb123e5b996b4ffc154bb92a9eeb24`.

Retained byte-for-byte:

- `metrics.json`: 4,482 bytes; SHA-256
  `e2821ae411bc0434cc98d2282ee8a60d727e58fbf11c85d6af5c1a7799c4f0e1`
- `requests.json`: 18,468 bytes; SHA-256
  `6e5a40683e9a439f767c182506add3a1e529359859337fe3ba4f2edddd4747cd`

The unchanged workload contains 1,000 synthetic runs / 50,000 executions, four
cold reads at concurrency one and 200 warm reads at concurrency ten, with 50 warm
reads per route. All 204 requests succeeded. Independently recomputed nearest-rank
warm p95 is **570.767209 ms**, failing the unchanged 500 ms target. Warm p50 is
232.223441 ms. Measurement and cleanup completed without errors.

Actual runner: AMD EPYC 7763 64-Core Processor, four reported logical CPUs,
Linux 6.17.0-1022-azure, Python 3.13.15 and PostgreSQL 17.11. The original launch
declaration records one API worker, no reload and exclusion of
`WEB_CONCURRENCY`/`UVICORN_*` overrides. This declares configuration rather than
a process census. Every earlier passing and failing observation remains retained.

All 20 warm requests exceeding 500 ms use the history route. This identifies the
measured tail; it does not isolate database time, Python work, pool/queue waiting,
serialization or client overhead as its cause. No causal speedup is claimed.
These synthetic reads are not normalized to the two-vCPU/four-GiB reference;
failure-heavy load and database/whole-stack memory remain unmeasured. Stable and
reference-resource acceptance remain open.

Only original metrics and request rows are published. The API log is excluded.
ZIP CRC, source/workload identity, complete phase counts, bounded sample timings
and percentile recomputation were checked before retention.
