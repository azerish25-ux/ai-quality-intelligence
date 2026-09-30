# Limitations and known failures

This catalog is part of acceptance, not a generic AI disclaimer. The full master
project is **PARTIAL**. The [requirements matrix](requirements-matrix.md) and
[delivery ledger](PROGRESS.md) identify exact tested source and remaining scope.

| ID | Known failure or boundary | Consequence / next verification |
|---|---|---|
| KQ-01 | Frozen `benchmark-v1`: product recall 0/44, macro F1 0.3048, coverage 19.57% | Quality targets fail. All 44 product cases abstain; zero dangerous dismissals does not make coverage acceptable. Develop only on allowed data, then freeze genuinely new held-out families. |
| KQ-02 | Executed component challenge: 48/60 product recognition | 80% recall misses the unchanged 90% target. Twelve abstentions remain visible. Fifteen mechanisms with dependent variants are not 60 independent mechanisms. |
| KD-01 | Corpus labels and family boundaries are agent-authored/reviewed | No blinded expert adjudication or population-risk guarantee is established. Synthetic history is not additional evaluation ground truth. |
| KP-01 | Optional HTTP model proposals have only fixture transport evaluation | No real model quality, paid usage or actual cost was measured. Persistent invocation/budget/operator/UI integration remains incomplete. In-process limits are not restart-safe spend enforcement. |
| KG-01 | Comment API lacks atomic head/comment updates | Caller serialization and pre/post head checks are required. Later PR changes need reconciliation; this is not a continuously monitored release check. No suitable open PR existed for live verification. |
| KG-02 | Rich report scope is partial | Outcome counts and verified investigations are present; complete baseline/history/impact/performance publication remains separate from the full dashboard. No fabricated public evidence URLs are supplied. |
| KS-01 | Declared text redaction and reviewed image masks are bounded | Free-text names, unknown identifiers and arbitrary pixels are not universally detected. Original traces/images can remain restricted. Existing plain-hash pseudonyms are not a guarantee against low-entropy guessing. |
| KS-02 | Capability-spy tests cover normalized input combinations | They do not establish OS sandbox security or complete binary/provider attack coverage. All required attack classes still need consolidated acceptance. |
| KO-01 | Newly added Docker recovery and narrow UI gates exposed regressions | Their repairs require passing actual exact-source CI. Local syntax/build/unit tests cannot substitute for Docker/browser execution. |
| KO-02 | Performance and telemetry acceptance remains incomplete | The latest retained 50,000-execution/concurrency-10 read measurement is 566.09 ms p95 and still fails 500 ms. Complete distributed telemetry and reference-hardware/whole-stack budgets remain unverified. |

Historical passing slices certify their named behavior only. A corrected bug, a new
unit-test count or a screenshot does not waive failed evaluation targets or finish
unimplemented master-prompt requirements.
