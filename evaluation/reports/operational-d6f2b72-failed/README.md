# Failed read benchmark at d6f2b72

Source [`d6f2b72a425ed3269026a6129794bf2e6fc90f8d`](https://github.com/azerish25-ux/ai-quality-intelligence/tree/d6f2b72a425ed3269026a6129794bf2e6fc90f8d),
[workflow 36735786619](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36735786619),
attempt 1, artifact `11106892644`
(`operational-read-benchmark-d6f2b72a425ed3269026a6129794bf2e6fc90f8d`).
GitHub records the operational workflow as completed with conclusion `failure`;
its head SHA, the artifact source SHA, and `metrics.json` agree.
Artifact created `2026-09-30T15:20:13Z`.

Original ZIP: 11,705 bytes; SHA-256 matched GitHub's artifact digest before
bounded extraction:
`43f2a454df5207061b19032273191011ec6173aebbeb78f420f7a5af78156267`.

Retained byte-for-byte from the verified ZIP:

- `metrics.json`: 3,794 bytes; SHA-256
  `012e880177e117d13755830d28133238b4aa3abc032ea05f2793ba29804045a2`
- `requests.json`: 18,460 bytes; SHA-256
  `efaf97ad56f9e735c155f9d9a777ce0e7f3a7cb0e05b50ff3641ddf483563327`

The unchanged workload contains 1,000 synthetic runs / 50,000 persisted executions,
four cold requests at concurrency one and 200 warm requests at concurrency ten
(50 warm requests per route). All 204 recorded requests succeeded. Warm p95,
recomputed from the original rows using the benchmark's nearest-rank rule, is
**586.886259 ms**; the unchanged **<500 ms target FAILS**.
Warm p50 is 245.866138 ms; seed creation took 4.247929 seconds.

Actual runner: AMD EPYC 9V74 80-Core Processor, four reported logical CPUs,
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

This historical schema counts `failed_requests` over warm requests only; the four
cold rows were inspected separately and also contain no failures. No new fields
were inserted into the original metrics.
