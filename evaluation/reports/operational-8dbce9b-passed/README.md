# Actual read benchmark at 8dbce9b

Source `8dbce9b327d943d85a1fce7d77d190853b8f2951`, workflow
[36687238442](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36687238442),
job `109795791336`, artifact `11085010098`.

Original ZIP SHA-256:
`2cf44571f8d2a62e8a4cf2ac28d9b980dda21e361bd64f6f55ad29726c51b0fd`.
The downloaded ZIP was verified before preserving its metrics/requests unchanged.

The fixed 50,000-execution PostgreSQL workload completed 200 requests at concurrency
ten with **359.78 ms p95 and zero failures**, passing the unchanged 500 ms target.
Four logical CPUs, Intel Xeon 6973P-C and actual load averages are recorded; cgroup
quota/memory limits were unavailable and remain null. The actual stage metrics were
available and show no HTTP/history exceptions. Export was disabled during this run.

This is another measured pass, not proof that shared-runner performance is stable.
All earlier passing and failing results remain. The fixture is all-passing history,
not mixed failure/analysis load, and does not measure whole-stack memory or normalize
to the requested reference machine. Classifier quality remains a separate failed gate.
