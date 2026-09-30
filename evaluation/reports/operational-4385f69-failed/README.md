# Failed actual operational measurement

Source: `4385f695ec879c073b5063f9825821e5b7146787`
[Workflow 36677790715](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36677790715),
job `109766451819`, artifact `11080860287`.
Original artifact SHA-256:
`8356eb9653b17362c0bdb16bb6065c4cf61b0c0eb12e206d9a39ad0c72ca20ed`.

The artifact was downloaded and checksum-verified. `metrics.json` and `requests.json`
are retained byte-for-byte. Actual PostgreSQL 17.11, Python 3.13.15, Ubuntu runner with
four reported logical CPUs; not normalized to reference hardware.

- 1,000 synthetic runs / 50,000 persisted executions
- 200 measured warm requests, concurrency 10, zero failed requests
- p95 **2,805.73 ms**; unchanged <500 ms target **FAIL**
- p50 358.30 ms; seed creation 4.96 seconds
- History requests dominate the tail (route p95 about 3,020.77 ms)

This is a controlled synthetic read workload, not a classification corpus or a
population throughput guarantee. Later optimizations do not erase this result.
