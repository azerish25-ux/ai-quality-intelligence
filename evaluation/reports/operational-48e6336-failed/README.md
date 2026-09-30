# Failed read benchmark at 48e6336

Source [`48e63361a742ef32df708fa2709ceb640e035f78`](https://github.com/azerish25-ux/ai-quality-intelligence/tree/48e63361a742ef32df708fa2709ceb640e035f78),
[workflow 36756008925](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36756008925),
attempt 1, job `110026311837`, artifact `11116428727`
(`operational-read-benchmark-48e63361a742ef32df708fa2709ceb640e035f78`).
GitHub records the operational workflow as completed with conclusion `failure`;
its head SHA, the artifact source SHA, and `metrics.json` agree.
Artifact created `2026-09-30T18:05:59Z`.

Original ZIP: 11,795 bytes; SHA-256 matched GitHub's artifact digest before
bounded extraction:
`325a3126b18f9e5256a99bddf178331ea37754b976987b6d219e9a27634ab954`.

Retained byte-for-byte from the verified ZIP:

- `metrics.json`: 4,264 bytes; SHA-256
  `e3e831d506e2072227624ba295a6876073a48f090f2dc7e256b08eeb2880292e`
- `requests.json`: 18,431 bytes; SHA-256
  `da85ad1934f47313136c34d69071b914e2c5457dcb809d56ed58d49ebf264da3`

The unchanged workload contains 1,000 synthetic runs / 50,000 persisted executions,
four cold requests at concurrency one and 200 warm requests at concurrency ten
(50 warm requests per route). All 204 recorded requests succeeded. Warm p95,
recomputed from the original rows using the benchmark's nearest-rank rule, is
**634.498979 ms**; the unchanged **<500 ms target FAILS**.
Warm p50 is 273.317426 ms; seed creation took 3.993471 seconds.
The original `measurement_completed`, `complete_read_samples`, and
`zero_failed_requests` targets are true; execution completed with no cleanup errors.

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
were not changed. This result belongs to the linked source revision, not subsequent
working-tree changes.
