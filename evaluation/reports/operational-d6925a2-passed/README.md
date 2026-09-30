# Passing read measurement at d6925a2

Source [`d6925a2be12750d384c80065e8f22179987ead7d`](https://github.com/azerish25-ux/ai-quality-intelligence/tree/d6925a2be12750d384c80065e8f22179987ead7d),
[workflow 36781849688](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36781849688),
attempt 1, job `110113764591`, artifact `11128132206`.
The completed workflow conclusion is `success`; its source and artifact agree.

Original ZIP: 11,621 bytes; SHA-256 matched GitHub's artifact digest:
`0f88c9e4ec284bf11f73daa76477194c29b41540dae836e1a16216f7b2161515`.

Retained byte-for-byte:

- `metrics.json`: 4,274 bytes; SHA-256
  `b623acd419bae7252287042556274296d76e0ddb5a35836ee9742063e1875154`
- `requests.json`: 18,448 bytes; SHA-256
  `de487615fd448dc486e237ce7dfefee1af2866299401e23142eece62860a9b8a`

The unchanged workload contains 1,000 synthetic runs / 50,000 executions, four
cold reads at concurrency one and 200 warm reads at concurrency ten, with 50 warm
reads per route. All 204 requests succeeded. Independently recomputed nearest-rank
warm p95 is **352.658658 ms**, below the unchanged 500 ms target. Warm p50 is
153.351123 ms. Measurement and cleanup completed without errors.

Actual runner: AMD EPYC 9V45 96-Core Processor, four reported logical CPUs,
Linux 6.17.0-1022-azure, Python 3.13.15 and PostgreSQL 17.11. This AMD model differs
from the prior failed 7763 and 9V74 measurements. CPU brand alone does not explain
the observed variance. Every prior passing and failing measurement remains
preserved; this result establishes neither a causal speedup nor stable acceptance.

These are synthetic API reads. Hardware is not normalized to the two-vCPU/four-GiB
reference. HTTP timing includes connection overhead; database/whole-stack memory
and failure-heavy load remain unmeasured. This historical report also predates
explicit single-worker launch metadata; its original values are unchanged.

Only original metrics and request rows are published. The API log is excluded.
ZIP CRC, source/workload identity, complete phase counts, bounded sample timings
and percentile recomputation were checked before retention.
