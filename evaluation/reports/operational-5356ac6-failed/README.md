# Failed read measurement at 5356ac6

Source [`5356ac642781cd2ef7c0b97589bf735d5be22e10`](https://github.com/azerish25-ux/ai-quality-intelligence/tree/5356ac642781cd2ef7c0b97589bf735d5be22e10),
[workflow 36812879201](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36812879201),
attempt 1, job `110211572821`, artifact `11139911794`.
The operational workflow conclusion is `failure`; its source and artifact agree.

Original ZIP: 12,213 bytes; verified SHA-256:
`f9b321e06ca7117f2128ca659d9ef05a4b062249aba8b452eaf6285ad24abad3`.

Retained byte-for-byte:

- `metrics.json`: 5,612 bytes; SHA-256
  `47c0dadcd80fc490d645d54653a549aea517f791fc77ff22430354d2add402c7`
- `requests.json`: 18,440 bytes; SHA-256
  `e9c334c5b17dcd96ffd1389ce5e2ec0e266aa6ff3785cb2fb685ca439a8ee514`

All four cold and 200 warm requests succeeded against the unchanged 1,000-run /
50,000-execution workload. Concurrency remains ten, with 50 warm reads per route.
Independently recomputed warm p95 is **589.155964 ms**, failing the unchanged
500 ms target; warm p50 is 239.053453 ms. Measurement and cleanup completed.

Actual runner: AMD EPYC 7763 64-Core Processor, four reported logical CPUs.
The declared launch remains one API worker without reload. Warm CPU observations
report 7.28 client CPU seconds and 5.86 API CPU seconds over approximately 6.15
wall seconds, ratios 1.184 and 0.953. Published arithmetic is consistent; absolute
samples are intentionally unavailable for reconstruction. PostgreSQL, descendants
and other processes are excluded. These figures do not establish whole-stack
resource use or a sole latency cause. Runtime, workload and benchmark instrumentation
are identical to the preceding 317.68 ms observation on AMD EPYC 9V45. Both remain
retained. No code speedup or stable/reference-resource acceptance is claimed.

Only original metrics and request rows are published; the API log is excluded.
ZIP CRC, source/workload identity, complete sample counts and percentile arithmetic
were independently verified. No failed sample, threshold or earlier result is
removed or normalized away.
