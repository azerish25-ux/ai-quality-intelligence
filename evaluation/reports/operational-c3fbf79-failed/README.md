# Third actual operational measurement: still above target

Source `c3fbf797ac2146107864ea8e71ee6ec91a07c7d3`,
[run 36679775614](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36679775614),
job `109772471306`, artifact `11081352381`.
Verified artifact SHA-256:
`d14ef7e6aca418053a9e2b681fa9ae776ce2e821f0bd46f3a86c726526c1d4d4`.
Metrics and request records are retained byte-for-byte.

Unchanged workload and target: 50,000 executions, concurrency 10, 200 warm requests,
zero failures, **p95 566.09 ms**, still **FAIL** against <500 ms. Both preceding
failed measurements remain retained. CI hardware is reported, not normalized.
