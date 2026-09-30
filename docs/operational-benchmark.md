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

The [third retained run](../evaluation/reports/operational-c3fbf79-failed/README.md)
measured 566.09 ms p95 and still failed. PostgreSQL pools are explicitly bounded and
operator-configurable: `FAILURELENS_DATABASE_POOL_SIZE=10` and
`FAILURELENS_DATABASE_MAX_OVERFLOW=10` per process. Account for all API/worker
processes when sizing PostgreSQL connections. SQLite retains its existing pool mode.
The report records configured pool bounds so later comparisons expose that change.

The [fourth executed result](../evaluation/reports/operational-845f53d-passed/README.md)
passes the declared read target at 312.37 ms p95 with zero failures. This fixture is
explicitly all-passing history with no failure/analysis rows; it does not establish
mixed failure-heavy read performance. All three original failures remain retained.

A later docs-only source `78b45dd` **failed** at 572.62 ms with the exact same
runtime/workload, so the earlier pass is not stable acceptance. Its original
[failed evidence](../evaluation/reports/operational-78b45dd-failed/README.md) is
retained. Subsequent measurements additionally capture bounded CPU model/quota/load
metadata and process-local stage metrics, without changing samples or thresholds.

The telemetry implementation `8dbce9b` then
[passed at 359.78 ms](../evaluation/reports/operational-8dbce9b-passed/README.md),
while the runtime-identical viewer-test/docs repair `8daa5c7`
[failed at 571.92 ms](../evaluation/reports/operational-8daa5c7-failed/README.md).
The new diagnostics reveal different CPU models (Intel Xeon 6973P-C versus AMD
EPYC 7763) and higher server-stage durations on the latter. This is an observed
environment difference, not a hardware-normalized result or proof of sole cause.
Both results have zero request failures; stable target compliance is still open.
