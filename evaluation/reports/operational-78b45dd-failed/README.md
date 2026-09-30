# Retained failure at 78b45dd

Original metrics and requests from workflow [36681988614](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36681988614), artifact 11081688912.
Downloaded ZIP SHA256: `1bd47183f44bcf836df25b57d79d3423ffc13328e44735749a1d3af8e4161491`.

The unchanged workload measured **572.62 ms p95**, zero failed requests, and
**failed** the unchanged <500 ms target. Source 78b45dd differs from the earlier
312.37 ms pass at 845f53d only in documentation and retained evidence. Both report
the same OS, Python and four logical CPUs. Seeding took 5.10 s versus 2.22 s;
all four cold reads and mean warm-route timings were slower. Host resource
variation is a hypothesis, not an established cause; neither run records CPU
model, quota or load. Historical success does not prove stable current acceptance.

The fixture contains 50,000 passing executions and no failure/analysis rows.
It does not establish failure-heavy read performance or classifier acceptance.
