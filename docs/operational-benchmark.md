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

The launcher explicitly selects one Uvicorn worker and excludes inherited
`WEB_CONCURRENCY` and `UVICORN_*` options from its copied child environment.
Application/database settings and unrelated environment values are preserved.
This prevents ambient reload, worker, env-file and logging options from silently
changing the measured server. The report retains declared launch configuration
even when startup fails; it does not claim an observed process census. Earlier
reports lack that metadata and remain unchanged. The fixed read workload, timing
boundaries, failure handling and 500 ms target are unchanged.

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

The overview-query consolidation source `1f7fe67`
[failed at 601.29 ms](../evaluation/reports/operational-1f7fe67-failed/README.md)
on AMD EPYC 7763. The gateway-only correction `9414d91`
[passed at 389.46 ms](../evaluation/reports/operational-9414d91-passed/README.md)
on Intel Xeon 6973P-C. Both have zero request failures and preserve the exact
workload/target. Every measurement remains; no single passing run establishes
stable target compliance or fixes the previously identified history-route tail.

The later published checkpoints preserve additional failures:
[`efa9a13`](../evaluation/reports/operational-efa9a13-failed/README.md) measured
710.69 ms, [`d6f2b72`](../evaluation/reports/operational-d6f2b72-failed/README.md)
measured 586.89 ms, and the strengthened measurement at
[`44988f5`](../evaluation/reports/operational-44988f5-failed/README.md) measured
**664.57 ms** on AMD EPYC 7763 in
[run 36748154891](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36748154891).
The latest run completed all four cold and 200 warm samples with zero failures in
either set. Stage/failure diagnostics now also record unsuccessful initialization,
seeding, startup, readiness and measurement, with bounded process cleanup. The
successful-warm timing denominator, workload and 500 ms target are unchanged;
none of these results establishes stable or reference-hardware acceptance.

The next exact published source `48e6336`
[fails at 634.50 ms](../evaluation/reports/operational-48e6336-failed/README.md)
on AMD EPYC 9V74 in
[run 36756008925](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36756008925).
All four cold and 200 warm requests succeeded, and measurement completed. Its
original bytes, source/run/job binding and independently recomputed percentiles
are retained. This additional failure does not replace any earlier result.

At `caee9e3`, the same workload
[fails at 677.27 ms](../evaluation/reports/operational-caee9e3-failed/README.md)
on AMD EPYC 7763 in
[run 36763069609](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36763069609).
All four cold and 200 warm requests succeeded. The original metrics and request
rows are retained with verified digests and recomputed percentiles. The history
route's 50 warm samples have p50 590.41 ms and p95 768.75 ms; this identifies a
slower route in this measurement, not the cause or a hardware-normalized result.
The overall target remains failed and every preceding measurement is preserved.

The subsequent published `be7eede` measurement
[fails at 607.66 ms](../evaluation/reports/operational-be7eede-failed/README.md)
on AMD EPYC 7763, with all 204 requests successful and complete cleanup. Original
bytes and recomputed percentiles are retained. This additional result leaves the
unchanged target failed and does not establish stable or causal improvement.

The runtime-identical `8eb264d` source then
[passed at 457.72 ms](../evaluation/reports/operational-8eb264d-passed/README.md)
on Intel Xeon Platinum 8573C, with all 204 requests successful. Its runtime,
benchmark code and workflow are byte-identical to `be7eede`. The original bytes
and recomputed percentiles are retained alongside that AMD failure. The passing
observation is not evidence of a code speedup or stable/reference-resource
acceptance; the 500 ms target and fixed workload remain unchanged.

The following `d6925a2` observation
[passed at 352.66 ms](../evaluation/reports/operational-d6925a2-passed/README.md)
on AMD EPYC 9V45 with all 204 requests successful. That model differs from prior
failed AMD 7763/9V74 runs, so CPU brand is not an acceptance discriminator. Original
metrics and requests are retained. This measurement also predates explicit launch
metadata; no historical worker/reload configuration is invented retroactively.
Stable and reference-resource acceptance remain open.

The explicit-launch source `c27e2e5`
[passed at 386.74 ms](../evaluation/reports/operational-c27e2e5-passed/README.md)
on Intel Xeon 6973P-C with all 204 requests successful. Its original metadata
declares one API worker and no reload after excluding ambient Uvicorn settings;
it does not claim a process census. Original metrics and request bytes are
retained. The same workload and 500 ms threshold apply; this passing observation
does not establish a speedup or stable/reference-resource acceptance.
