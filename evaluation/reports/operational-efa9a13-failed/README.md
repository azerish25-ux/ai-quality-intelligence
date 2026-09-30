# Failed read benchmark at efa9a13

Source [`efa9a13dfbe70a266217acc5b0bcae4b98cd238e`](https://github.com/azerish25-ux/ai-quality-intelligence/tree/efa9a13dfbe70a266217acc5b0bcae4b98cd238e),
[workflow 36725945608](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36725945608),
attempt 1, artifact `11102945631`
(`operational-read-benchmark-efa9a13dfbe70a266217acc5b0bcae4b98cd238e`).
GitHub records the operational workflow as completed with conclusion `failure`;
its head SHA, the artifact source SHA, and `metrics.json` agree.
Artifact created `2026-09-30T14:02:15Z`.

Original ZIP: 11,661 bytes; SHA-256 matched GitHub's artifact digest before
bounded extraction:
`8a1daa85ce4e3640215941c59a50446d2a583869283478930ed449b7e689bee2`.

Retained byte-for-byte from the verified ZIP:

- `metrics.json`: 3,786 bytes; SHA-256
  `5c00202f13d198b65a45960e0e7d2a99327e16c5f3e2f1aa6298864f922eade7`
- `requests.json`: 18,437 bytes; SHA-256
  `ae741fd866476e8c76b2844c912c794eca6c6ae2ea724bdef90e38605c9e3ec6`

The unchanged workload contains 1,000 synthetic runs / 50,000 persisted executions,
four cold requests at concurrency one and 200 warm requests at concurrency ten
(50 warm requests per route). All 204 recorded requests succeeded. Warm p95,
recomputed from the original rows using the benchmark's nearest-rank rule, is
**710.686251 ms**; the unchanged **<500 ms target FAILS**.
Warm p50 is 261.534203 ms; seed creation took 5.206917 seconds.

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

This historical schema counts `failed_requests` over warm requests only; the four
cold rows were inspected separately and also contain no failures. No new fields
were inserted into the original metrics.
