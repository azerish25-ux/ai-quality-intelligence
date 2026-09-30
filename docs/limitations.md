# Limitations and known failures

This catalog is part of acceptance, not a generic AI disclaimer. The full master
project is **PARTIAL**. The [requirements matrix](requirements-matrix.md) and
[delivery ledger](PROGRESS.md) identify exact tested source and remaining scope.

| ID | Known failure or boundary | Consequence / next verification |
|---|---|---|
| KQ-01 | Frozen `benchmark-v1`: product recall 0/44, macro F1 0.3048, coverage 19.57% | Quality targets fail. All 44 product cases abstain; zero dangerous dismissals does not make coverage acceptable. Develop only on allowed data, then freeze genuinely new held-out families. |
| KQ-02 | Executed component challenge: 48/60 product recognition | 80% recall misses the unchanged 90% target. Twelve abstentions remain visible. Fifteen mechanisms with dependent variants are not 60 independent mechanisms. |
| KD-01 | Corpus labels and family boundaries are agent-authored/reviewed | No blinded expert adjudication or population-risk guarantee is established. Synthetic history is not additional evaluation ground truth. |
| KP-01 | Optional HTTP model proposals have only fixture transport evaluation | Durable reservations, attempts, recovery, operator approval, isolated worker/proxy and UI are implemented and verified with synthetic PostgreSQL/browser/Docker fixtures. No real model quality, paid usage or actual provider billing was measured; production activation remains separate. |
| KG-01 | Comment API lacks atomic head/comment updates | Caller serialization and pre/post head checks are required. Later PR changes need reconciliation; this is not a continuously monitored release check. No suitable open PR existed for live verification. |
| KG-02 | Rich reports and exports retain bounded subsets | Persisted history, impact, cluster and performance/baseline sections are included with scoped evidence checks. Exports retain only the approved bounded reference subset and do not recreate original artifacts or provide fabricated public evidence URLs. |
| KS-01 | Declared text redaction and reviewed image masks are bounded | Free-text names, unknown identifiers and arbitrary pixels are not universally detected. Original traces/images can remain restricted. Existing plain-hash pseudonyms are not a guarantee against low-entropy guessing. |
| KS-02 | Capability-spy tests cover normalized input combinations | They do not establish OS sandbox security or complete binary/provider attack coverage. All required attack classes still need consolidated acceptance. |
| KO-01 | Ordinary deployment regressions are scoped to tested source | All twelve ordinary jobs pass at `caee9e3`, including PostgreSQL, browser, producer and Docker checks. This does not certify subsequent changes or replace branch, audit, classifier or performance acceptance. |
| KO-02 | Performance and telemetry acceptance remains incomplete | The 50,000-execution/concurrency-10 workload has both passes and failures; the latest `be7eede` result is 607.66 ms p95 and fails the unchanged 500 ms target despite zero request failures. Mixed failure-heavy load and reference-hardware/whole-stack budgets remain unverified. Telemetry is bounded and disabled for external export by default; process-local counts are not whole-deployment totals. |
| KC-01 | Master branch coverage targets fail | Hosted `caee9e3` measures 3,088/3,856 = 80.0830% branches; five of 34 critical files meet 95%. The unchanged targets are 90% overall and 95% per declared critical file. Ordinary combined coverage is a different gate. |
| KA-01 | Required npm dependency audit is NOT RUN | Seven independent hosted quality/security jobs pass, including Python audit. The required aggregate remains failed until the separately authorized npm metadata audit actually executes and passes. |
| KE-01 | Current-evidence/storage repair verification is scoped | Repairs for missing derivatives, expired cited support, upload cancellation, numeric traces and bounded request caching are published at `be7eede`, with focused regression checks. A full local run completed with one stale artifact-contract assertion; its exact correction still needs fresh hosted acceptance. Historical analyses/reviews and every unsuccessful run remain preserved. |

Historical passing slices certify their named behavior only. A corrected bug, a new
unit-test count or a screenshot does not waive failed evaluation targets or finish
unimplemented master-prompt requirements.
