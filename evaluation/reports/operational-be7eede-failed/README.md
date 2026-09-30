# Failed read benchmark at be7eede

Source [`be7eede37b4ac25d9d248d47fc5d7caac4242f3d`](https://github.com/azerish25-ux/ai-quality-intelligence/tree/be7eede37b4ac25d9d248d47fc5d7caac4242f3d),
[workflow 36773371389](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36773371389),
attempt 1, job `110085081146`, artifact `11124174222`
(`operational-read-benchmark-be7eede37b4ac25d9d248d47fc5d7caac4242f3d`).
The completed workflow conclusion is `failure`; its source and artifact agree.
Artifact created `2026-09-30T20:33:31Z`.

Original ZIP: 11,772 bytes; SHA-256 matched GitHub's artifact digest:
`43ae9384956d3b932ee086325126d4fd7db74945befc3e85785a0176d12d26b9`.

Retained byte-for-byte:

- `metrics.json`: 4,278 bytes; SHA-256
  `27c92c9366465d7faa979dbb50a61823ea5110c04bae8a514c2342ca04339dc0`
- `requests.json`: 18,437 bytes; SHA-256
  `495e520e6b887d1711fe6806aa807687238062da3e9c950ceee187050fbbe4bc`

The unchanged workload contains 1,000 synthetic runs / 50,000 persisted executions,
four cold requests at concurrency one and 200 warm requests at concurrency ten
(50 warm requests per route). All 204 requests succeeded. Independently recomputed
nearest-rank warm p95 is **607.658224 ms**; the unchanged **<500 ms target FAILS**.
Warm p50 is 255.301159 ms; seed creation took 5.053159 seconds. Measurement and
cleanup completed without errors.

Actual runner: AMD EPYC 7763 64-Core Processor, four reported logical CPUs,
Linux 6.17.0-1022-azure, Python 3.13.15, PostgreSQL 17.11. The runner is not
normalized to the two-vCPU reference. These are synthetic API reads, not
classification or ingestion-throughput evidence. Client timing includes HTTP
connection overhead; database/whole-stack memory and failure-heavy load remain
unmeasured. The lower result than an earlier run does not establish a causal
improvement or stable compliance. All earlier failures remain retained.

Retention checked exact JSON structure, source identity, declared workload,
fixed limitations, deterministic route IDs, successful phase counts, bounded
timings and recomputed percentiles. Only the two JSON members are published;
`api.log` is excluded. No threshold or historical value was changed.
