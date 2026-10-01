# Passing read measurement at d869361

Source [`d86936168bfb96490bfb06c09f7276518f14902c`](https://github.com/azerish25-ux/ai-quality-intelligence/tree/d86936168bfb96490bfb06c09f7276518f14902c),
[workflow 36809227373](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36809227373),
attempt 1, job `110200329682`, artifact `11139146610`.
The completed operational workflow is `success`; its source and artifact agree.

Original ZIP: 12,163 bytes; SHA-256 matched GitHub's artifact digest:
`97c5937207633398717a89c263666e2b8a88eb333d7ecd55bd8240e428b6bef0`.

Retained byte-for-byte:

- `metrics.json`: 5,599 bytes; SHA-256
  `06298d302959a3c00242909274264d9c00dc399b955a1be5ff22573912398bb2`
- `requests.json`: 18,476 bytes; SHA-256
  `d41202e5117121c0783a8557288aebddd2367bf4cbfc5b613efed25580fa1c6f`

The unchanged workload contains 1,000 synthetic runs / 50,000 executions, four
cold reads at concurrency one and 200 warm reads at concurrency ten, 50 per route.
All 204 requests succeeded. Independently recomputed nearest-rank warm p95 is
**317.680817 ms**, below the unchanged 500 ms target; p50 is 135.116744 ms.
Actual runner: AMD EPYC 9V45 96-Core Processor, four reported logical CPUs.
The declared launch remains one API worker without reload. These fields describe
launch configuration, not an observed process census.

New bounded warm CPU observations report 4.50 client CPU seconds and 3.09 API CPU
seconds over approximately 3.38 wall seconds: 1.331 and 0.914 CPU seconds per wall
second, respectively. Numeric field consistency and derived arithmetic were
checked independently; absolute counters are intentionally discarded, so these
checks cannot reconstruct the original samples. PostgreSQL, descendants and other
processes are excluded. This is not whole-stack or per-route CPU, a latency-cause
finding, a code speedup, or stable/reference-resource acceptance. All earlier
passing and failing observations remain retained.

The separate regression workflow was cancelled during backend testing after
20m19s. Its log reached 71% dot progress; no complete backend count or coverage
artifact exists for this source. Eleven other ordinary jobs pass. This operational
result does not replace the missing backend measurement or failed quality gates.

Only original metrics and request rows are published. The API log is excluded.
ZIP CRC, source/workload identity, counts and percentiles were checked before
retention. The workload, failure denominators and original target are unchanged.
