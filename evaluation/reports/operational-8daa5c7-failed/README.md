# Failed read benchmark at 8daa5c7

Source `8daa5c7e3ebb20e9c7519ae6e5e9e6a4afe79e5f`, workflow
[36687923355](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36687923355),
job `109797961739`, artifact `11084173046`.

Original ZIP SHA-256:
`4d7f26cbb68f55ddaf0119d2c5408c847f735e4030281bcecd50bd8efa7b8b8f`.
Downloaded bytes were verified; original metrics/requests are preserved unchanged.

The fixed PostgreSQL read workload measured **571.92 ms p95**, zero failed requests,
and failed the unchanged 500 ms target. Runtime code matches the preceding 359.78 ms
passing source; this commit changes only the local-viewer probe, its test and docs.
This runner reports **AMD EPYC 7763**, whereas the preceding passing runner reported
Intel Xeon 6973P-C. Both expose four logical CPUs. Hardware differs, but that alone
does not establish the cause or waive the failed target. Server-stage timings also
rose; this was not solely extra time outside the server.

The fixture is all-passing history, not failure-heavy load. No hardware normalization,
stable SLA or complete operational acceptance is claimed. All prior results remain.
