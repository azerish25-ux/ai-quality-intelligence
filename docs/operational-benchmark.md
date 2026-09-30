# Operational read benchmark

`evaluation/operational_benchmark.py` measures the actual HTTP API against a real,
empty, disposable PostgreSQL database. Its fixed synthetic workload contains 1,000
runs and 50,000 persisted executions. Four cold reads are recorded separately from
200 reads at concurrency 10 across run listing, run detail, test history and overview.
The process refuses a non-PostgreSQL URL, disabled demo mode, an existing project,
dirty source or an existing output directory.

```sh
python evaluation/operational_benchmark.py --confirm-disposable-database --output /tmp/new-operational-report
```

The dedicated workflow records the actual source SHA, PostgreSQL/Python/platform/CPU
metadata, seeding time, per-request latency/outcome, nearest-rank p50/p95 and explicit
failure counts. It preserves unsuccessful reports and exits nonzero unless every
request succeeds and warm read p95 is under the original 500 ms target.

This is synthetic read-load evidence, not a root-cause corpus, ingestion-throughput
measurement, a deployment guarantee or a 50,000-independent-case quality claim.
HTTP timings include client connection overhead. CI hardware is reported as observed,
not normalized to the original 2-vCPU/4-GiB reference. Python client/API peak RSS is
reported separately; database and whole-stack memory remain unmeasured. API startup
readiness and seed time are outside the warm-read timing denominator and named
separately. Actual acceptance awaits the workflow result; no performance is promised
from the presence of the harness.

The first executed measurement failed: [retained original result](../evaluation/reports/operational-4385f69-failed/README.md).
Subsequent optimization must preserve the workload and original 500 ms target.
