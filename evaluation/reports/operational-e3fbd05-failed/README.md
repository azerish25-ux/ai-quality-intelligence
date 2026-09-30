# Second actual operational measurement: target still failed

Source `e3fbd05559155be9305c101250f8fa9b98980a8f`,
[run 36678869236](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36678869236),
job `109769730218`, artifact `11080693836`.
Verified original artifact SHA-256:
`d41b0adc079ece6943568e01d59578d855b077ca8aff3d89e76f0c64dc0e9cec`.
Metrics and request records are retained byte-for-byte.

The same 50,000-execution / concurrency-10 workload recorded zero request failures
and p95 **1,022.13 ms**, still **FAIL** against the unchanged <500 ms target. The
prior 2,805.73 ms failed report remains separately retained. Different hosted runs
are not a controlled reference-hardware causal comparison.
