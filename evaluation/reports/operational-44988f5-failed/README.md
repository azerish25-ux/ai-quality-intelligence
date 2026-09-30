# Failed read benchmark at 44988f5

Source [`44988f581f9330502c030651c2c24e8978a67687`](https://github.com/azerish25-ux/ai-quality-intelligence/tree/44988f581f9330502c030651c2c24e8978a67687),
[workflow 36748154891](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36748154891),
attempt 1, artifact `11112769402`
(`operational-read-benchmark-44988f581f9330502c030651c2c24e8978a67687`).
GitHub records the operational workflow as completed with conclusion `failure`;
its head SHA, the artifact source SHA, and `metrics.json` agree.
Artifact created `2026-09-30T16:59:56Z`.

Original ZIP: 11,773 bytes; SHA-256 matched GitHub's artifact digest before
bounded extraction:
`71de15d743305dc580627978dc24184c203d3f6243cfe2e301fc1d81efa87b42`.

Retained byte-for-byte from the verified ZIP:

- `metrics.json`: 4,263 bytes; SHA-256
  `3c31b33df214735623406d526688202510dc6756f206ac3ddf63482445d26d22`
- `requests.json`: 18,438 bytes; SHA-256
  `55a48aa77195d7c2377ae9a958aa3acf7d8334460ba32a343df3a9204734994c`

The unchanged workload contains 1,000 synthetic runs / 50,000 persisted executions,
four cold requests at concurrency one and 200 warm requests at concurrency ten
(50 warm requests per route). All 204 recorded requests succeeded. Warm p95,
recomputed from the original rows using the benchmark's nearest-rank rule, is
**664.567469 ms**; the unchanged **<500 ms target FAILS**.
Warm p50 is 239.051660 ms; seed creation took 5.227386 seconds.

Actual runner: AMD EPYC 7763 64-Core Processor, four reported logical CPUs,
Linux 6.17.0-1022-azure, Python 3.13.15, PostgreSQL 17.11.
Hardware was not normalized to the two-vCPU reference. This is synthetic read-load
evidence, not classification quality, ingestion throughput, or a population latency
guarantee. Client timings include HTTP connection overhead; database and whole-stack
memory were not measured. Shared-runner consistency and failure-heavy workloads
remain unproven. Earlier and later measurements retain their own source and runner.

Retention review checked the exact expected JSON keys, types, fixed strings and
bounded numeric values, the deterministic synthetic route IDs, both phase counts,
zero failures, and p50/p95 against the original rows. Only the two JSON members were
extracted; `api.log` was excluded. No raw response bodies, prompts, credentials,
user identifiers or unknown fields were retained. Historical values and thresholds
were not changed.
