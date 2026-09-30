# Actual operational measurement: declared read target passed

Source `845f53dc92ad121257d9b47adc1e4d89ccc1394e`,
[run 36681098079](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36681098079),
job `109776505720`, artifact `11081444531`.
Verified original artifact SHA-256:
`e4f65a7a888190fa3f89aacbdd8855c9c1f34c174e0fdb63ac175a3abd82d654`.
Metrics and request records are retained byte-for-byte.

- 1,000 synthetic runs / 50,000 persisted passing executions
- 200 warm requests, concurrency 10, zero failed requests
- **p95 312.37 ms**, passing the unchanged <500 ms target
- The same four read routes and fresh-client HTTP measurement as the failed runs
- PostgreSQL pool: 10 retained connections plus up to 10 overflow per process

This workload contains no failure/analysis rows. It measures passing-history read
load, not a mixed failure-heavy workload, ingestion throughput or classifier quality.
The four-logical-CPU hosted runner is not normalized to the original reference
hardware. It is one controlled measurement, not a latency SLA or population guarantee.
Database/whole-stack memory remain unmeasured. All three earlier failed results are
retained; none were overwritten or relabeled. Frozen classifier quality still fails.
