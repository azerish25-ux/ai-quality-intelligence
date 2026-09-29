# M6.3 frozen five-category benchmark

Tested source: `f1269c3ce52d4bf64f8614aacd34d99903a99b5f`; database: `sqlite`.
Corpus: 260 cases, 83 authored mechanism groups. Headline test split: 108 cases.
Product recall: 0.0; macro F1: 0.3048218029350105; product abstentions: 44.
Dangerous dismissals: 0/44.

## Quality targets
- FAIL — product_recall_at_least_90_percent
- FAIL — macro_f1_at_least_0_80
- FAIL — decision_coverage_at_least_75_percent
- PASS — dangerous_dismissal_at_most_5_percent
- PASS — zero_critical_high_dangerous_dismissals
- PASS — zero_unsupported_critical_reassurance

## Baselines and ablations
| Mode | Product recall | Macro F1 | Product abstentions |
|---|---:|---:|---:|
| constant_product_baseline | 1.0 | 0.11578947368421053 | 0 |
| rules_only | 0.0 | 0.09690346083788706 | 44 |
| rules_with_history | 0.0 | 0.3048218029350105 | 44 |
| full_deterministic | 0.0 | 0.3048218029350105 | 44 |

## Execution/integrity checks
- PASS — minimum_cases
- PASS — minimum_families
- PASS — minimum_category_counts
- PASS — minimum_test_cases
- PASS — minimum_test_products
- PASS — minimum_test_product_families
- PASS — minimum_retained_executed_cases
- PASS — minimum_retained_executed_families
- PASS — family_incident_artifact_split_isolation
- PASS — minimum_tagged_adversarial_cases
- PASS — five_substantive_repetitions
- PASS — all_citations_resolvable
- PASS — later_history_excluded
- PASS — no_sensitive_canary_disclosure
- PASS — no_forbidden_published_claim

## All test errors
- `c-04654ceb0dfe05284d31`: infrastructure_failure → insufficient_evidence (container-image-absent)
- `c-0615080119a85d9424be`: infrastructure_failure → insufficient_evidence (cloud-test-quota)
- `c-093af2eb07636488accd`: test_defect → insufficient_evidence (float-exact-equality)
- `c-0e82c68dc3e05c2d6f3e`: product_defect → insufficient_evidence (lost-update-no-version-check)
- `c-0e887a2d9002635f7c3f`: product_defect → insufficient_evidence (refund-reservation-race)
- `c-13e667b6ec1f5c54940f`: infrastructure_failure → insufficient_evidence (container-image-absent)
- `c-142631a7e74b47cbb40c`: test_defect → insufficient_evidence (assertion-before-await)
- `c-15774c19f7ad239af577`: product_defect → insufficient_evidence (cross-tenant-cache-key)
- `c-183586e1118a8e7137d1`: test_defect → insufficient_evidence (screenshot-fixture-font)
- `c-1b578ac5ca8b463dc415`: product_defect → insufficient_evidence (dirty-read-exposes-uncommitted-balance)
- `c-21d6467ca15fea98ae2a`: product_defect → insufficient_evidence (dropped-cache-invalidation)
- `c-22c36e5aa0a16e8f3553`: product_defect → insufficient_evidence (time-window-inclusive-end)
- `c-2467c30da3b13916216c`: test_defect → insufficient_evidence (float-exact-equality)
- `c-284df7cb8fee71ebf7b1`: test_defect → insufficient_evidence (mock-clock-zone)
- `c-2928fbef7ffb3ff5524c`: infrastructure_failure → insufficient_evidence (file-descriptor-exhaustion)
- `c-2e9d2b7df2b0cd28104a`: product_defect → insufficient_evidence (role-scope-mutation-check)
- `c-2eb8da89c6639dbc72a0`: product_defect → insufficient_evidence (closed-account-transfer)
- `c-33e471393acc87950783`: infrastructure_failure → insufficient_evidence (runner-network-interface-down)
- `c-376777f1005da8852e64`: product_defect → insufficient_evidence (reconciliation-reapplies-adjustment)
- `c-3c4f4781ae661e424a49`: product_defect → insufficient_evidence (reconciliation-reapplies-adjustment)
- `c-46af2e43ec685e24c46f`: infrastructure_failure → insufficient_evidence (runner-clock-unsynchronized)
- `c-4cc1538f20f0c2060d95`: test_defect → insufficient_evidence (mock-clock-zone)
- `c-5840054dfab032376e06`: infrastructure_failure → insufficient_evidence (file-descriptor-exhaustion)
- `c-5e234dba80200f5da1fa`: product_defect → insufficient_evidence (fx-rate-effective-window)
- `c-6363dc63507bb0aa1770`: product_defect → insufficient_evidence (signed-integer-overflow)
- `c-687f37b7d56e075e37bc`: test_defect → insufficient_evidence (float-exact-equality)
- `c-689a770563e9ad33953c`: product_defect → insufficient_evidence (signed-integer-overflow)
- `c-6ec8a9fd0310f4baa244`: product_defect → insufficient_evidence (negative-transfer-accepted)
- `c-6f861c3ddf678450c769`: product_defect → insufficient_evidence (utf8-reference-truncation)
- `c-77015105673334bb35ba`: test_defect → insufficient_evidence (unordered-result-order)
- `c-7b6812757ff13e321765`: product_defect → insufficient_evidence (lost-update-no-version-check)
- `c-7c648f39dc8c92c7b365`: infrastructure_failure → insufficient_evidence (file-descriptor-exhaustion)
- `c-827e94e196bf7d01fed0`: product_defect → insufficient_evidence (webhook-sequence-gap)
- `c-82e97fe45433d702dc0a`: product_defect → insufficient_evidence (pagination-skips-equal-timestamps)
- `c-8332b148166f7e188578`: infrastructure_failure → insufficient_evidence (cloud-test-quota)
- `c-87ecb56a8e6521eee5bc`: test_defect → insufficient_evidence (assertion-before-await)
- `c-8b01bcfe350b13b34f24`: product_defect → insufficient_evidence (rollback-leaves-outbox-event)
- `c-8c2198093d6ad618198f`: product_defect → insufficient_evidence (missing-journal-parent-constraint)
- `c-8c62b0fca8d3bf509eed`: product_defect → insufficient_evidence (cross-tenant-cache-key)
- `c-8d197cd7f60abe21022c`: infrastructure_failure → insufficient_evidence (cloud-test-quota)
- `c-90d2474fae22c7289abe`: test_defect → insufficient_evidence (json-member-order-expectation)
- `c-911460b66d370d9e4dc0`: product_defect → insufficient_evidence (expiry-zone-conversion)
- `c-961edba4ed1679224645`: product_defect → insufficient_evidence (negative-transfer-accepted)
- `c-964ecd1ca9713d14cdc7`: product_defect → insufficient_evidence (partial-commit-two-wallets)
- `c-976ca9fd6a88403ed4d8`: product_defect → insufficient_evidence (rollback-leaves-outbox-event)
- `c-9c41060da0ff1538d0f4`: product_defect → insufficient_evidence (negative-transfer-accepted)
- `c-a6505f213692e6811864`: product_defect → insufficient_evidence (lost-update-no-version-check)
- `c-a9f085bc94688c1b9c27`: product_defect → insufficient_evidence (closed-account-transfer)
- `c-ae3eacbb88a8cca4f217`: test_defect → insufficient_evidence (json-member-order-expectation)
- `c-b25d544553f93ac320a1`: test_defect → insufficient_evidence (screenshot-fixture-font)
- `c-b7ce294e4ae4fc0c076f`: product_defect → insufficient_evidence (auth-token-revocation-cache)
- `c-bc922eab338fef7c3ea0`: product_defect → insufficient_evidence (role-scope-mutation-check)
- `c-bddf4f47721712308110`: product_defect → insufficient_evidence (closed-account-transfer)
- `c-bffddd34c129effeb42f`: product_defect → insufficient_evidence (partial-commit-two-wallets)
- `c-c4e7c5bea28d2e4d7c76`: product_defect → insufficient_evidence (pagination-skips-equal-timestamps)
- `c-cbdffeeb13e3eb1312a2`: product_defect → insufficient_evidence (dropped-cache-invalidation)
- `c-cc18bc5f7bf887deaf03`: product_defect → insufficient_evidence (refund-reservation-race)
- `c-cd21c59338b64a0ee1ef`: product_defect → insufficient_evidence (time-window-inclusive-end)
- `c-cd8eac41979011d5b421`: test_defect → insufficient_evidence (unordered-result-order)
- `c-d063e131ce4a725c49f6`: product_defect → insufficient_evidence (webhook-sequence-gap)
- `c-d298a911c04771749ac3`: test_defect → insufficient_evidence (unordered-result-order)
- `c-d37da6e18252f95cb25c`: product_defect → insufficient_evidence (expiry-zone-conversion)
- `c-d6b7c8fe1e9a63ad0fcb`: product_defect → insufficient_evidence (rollback-leaves-outbox-event)
- `c-d6e35c952c65c7c027ee`: infrastructure_failure → insufficient_evidence (container-image-absent)
- `c-d782432092d1d99965d5`: test_defect → insufficient_evidence (screenshot-fixture-font)
- `c-de92832a22e4082acb2b`: product_defect → insufficient_evidence (dirty-read-exposes-uncommitted-balance)
- `c-e36c9e7e4ed06e87d9bf`: infrastructure_failure → insufficient_evidence (runner-clock-unsynchronized)
- `c-e4ed39934dc4f39ffdf2`: infrastructure_failure → insufficient_evidence (runner-network-interface-down)
- `c-ebb3149c700049830344`: test_defect → insufficient_evidence (json-member-order-expectation)
- `c-ec9daa7c9a0818ed3795`: product_defect → insufficient_evidence (fx-rate-effective-window)
- `c-ec9f57fcf1e938cfe108`: product_defect → insufficient_evidence (missing-journal-parent-constraint)
- `c-ee37e175bedeb080b9aa`: product_defect → insufficient_evidence (auth-token-revocation-cache)
- `c-eef323f41f8cba2b66a3`: product_defect → insufficient_evidence (utf8-reference-truncation)
- `c-f1b108862c433ecbb5a0`: infrastructure_failure → insufficient_evidence (runner-clock-unsynchronized)

## Limitations
Public, agent-authored/agent-reviewed scenarios; not an independently blinded benchmark.
Family groupings are explicitly authored mechanism judgments, not automatically proven causal independence.
200 controlled synthetic cases plus 60 retained real component executions; this command runs no LedgerGuard faults.
All previously inspected component mechanisms and related synthetic variants stay in development.
Forty tagged adversarial inputs cover five text/canary classes, not the entire master adversarial program.
Headline quality metrics refer only to the frozen test split; retained executed cases are development-only.
Temporal checks verify prior-only ingestion/review ordering, not a historical calendar-time production backtest.
The unknown-family slice is the same test partition, not additional independent observations.
Benchmark authors saw the public scenario design; no independent expert label adjudication is claimed.
This source adds typed domain checks; it does not retroactively add missing domain measurements to old component artifacts.
Network/filesystem guards are process-local; broader OS isolation and the full adversarial program remain incomplete.
A frozen authored benchmark is engineering evidence, not a deployment accuracy or population-risk guarantee.
