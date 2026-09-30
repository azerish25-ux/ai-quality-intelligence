# Failed read benchmark at 1f7fe67

Source `1f7fe672ee940a4bf117517e399e134b5d05ed88`, workflow
[36690815339](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36690815339),
job `109807335527`, artifact `11086330034`.

Original ZIP SHA-256 verified before extraction:
`fa7f4835294bb93553e512b6c0b50b8421ea60cfad833eebecb87f4bb13bb2f0`.
Metrics and requests retain their exact bytes.

The unchanged 50,000-execution workload measured **601.29 ms p95** with zero failed
requests on an AMD EPYC 7763 runner. The original 500 ms target **FAILS**. The
overview query consolidation did not establish overall read-target compliance;
earlier analysis identified the history route as the tail driver. No measurements
were discarded, threshold changed or shared-runner result normalized to reference
hardware. The all-passing synthetic fixture does not establish failure-heavy load.
