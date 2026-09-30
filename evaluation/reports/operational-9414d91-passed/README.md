# Passing read benchmark at 9414d91

Source `9414d91f26fc03ac0baf644bf1cb8602ab526c08`, workflow
[36691731040](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36691731040),
artifact `11085962042`.

Original ZIP SHA-256 verified before extraction:
`696e6286e7aeae32bd3ad9a36edcd88256231ddc5b8d14a6b061885660fe49c4`.
Metrics and requests retain their exact bytes.

The unchanged 50,000-execution, concurrency-ten workload measured **389.46 ms p95**
with zero request failures on an Intel Xeon 6973P-C runner. The original <500 ms
measurement target passes on this source and runner. The prior 601.29 ms AMD
measurement remains failed; no measurement was discarded or normalized. Shared
runner consistency, failure-heavy workloads and whole-stack memory remain unproven.
