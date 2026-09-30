# Failed read benchmark at caee9e3

Source [`caee9e300bc8974c750ccaab5e78d94c00dfd337`](https://github.com/azerish25-ux/ai-quality-intelligence/tree/caee9e300bc8974c750ccaab5e78d94c00dfd337),
[workflow 36763069609](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36763069609),
attempt 1, job `110050270203`, artifact `11119049051`
(`operational-read-benchmark-caee9e300bc8974c750ccaab5e78d94c00dfd337`).
The completed workflow conclusion is `failure`; source and artifact metadata agree.
Artifact created `2026-09-30T19:05:11Z`.

Original ZIP: 11,738 bytes; SHA-256 matched GitHub's artifact digest:
`2f5977045d80d119a4a9800520e49f97feb59ea5d905dcb66364366e958d5c54`.

Retained byte-for-byte from the verified ZIP:

- `metrics.json`: 4,275 bytes; SHA-256
  `82ab096504fb4020b1e5431d3416cdac3ae952eb72965239e3560845f69bab66`
- `requests.json`: 18,422 bytes; SHA-256
  `6c30d26a6ffcff9071d8a151f20de98f3a5026cae97b52caa7cef884a91deca3`

The unchanged workload contains 1,000 synthetic runs / 50,000 persisted executions,
four cold requests at concurrency one and 200 warm requests at concurrency ten
(50 warm requests per route). All 204 recorded requests succeeded. Warm p95,
independently recomputed using the benchmark's nearest-rank rule, is
**677.267157 ms**; the unchanged **<500 ms target FAILS**.
Warm p50 is 287.980364 ms; seed creation took 5.153835 seconds.
Measurement and cleanup completed without errors. No unsuccessful run was omitted.

Actual runner: AMD EPYC 7763 64-Core Processor, four reported logical CPUs,
Linux 6.17.0-1022-azure, Python 3.13.15, PostgreSQL 17.11.
Hardware was not normalized to the two-vCPU reference. This synthetic read workload
does not measure classification quality or ingestion throughput. Client timings
include HTTP connection overhead; database and whole-stack memory were not measured.
Shared-runner consistency and failure-heavy workloads remain unproven.

Retention review checked the JSON shape against the preceding retained run,
source identity, fixed strings, deterministic route IDs, bounded timings, all phase
counts and independently recomputed p50/p95. The repository retains only the two
JSON members; `api.log` is excluded. Historical bytes and thresholds are unchanged.
This result belongs to the linked source revision, not subsequent working changes.
