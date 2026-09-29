# Development diagnostic measurement

Tested source: `b7327b437d8fc4cb009918d1d4d31b6bf36f508a`; database: `postgresql`.
Full dataset: 8 cases / 1 catalogued families. Scored development: 8 cases / 1 families.
Development/regression only; no held-out acceptance or completed M6 is claimed.
Product recall: 1.000; macro F1: undefined; non-abstained coverage: 1.000.
Dangerous dismissals: 0/4; product abstentions: 0.

## Unchanged numerical targets (not full acceptance)
- PASS — product_recall_at_least_90_percent
- FAIL — macro_f1_at_least_0_80
- PASS — non_abstained_coverage_at_least_75_percent
- PASS — dangerous_dismissal_at_most_5_percent
- PASS — identical_nuisance_results

## Original corpus minimums
- FAIL — cases_at_least_200
- FAIL — families_at_least_80
- FAIL — category_minimums
- FAIL — test_cases_at_least_100
- FAIL — test_products_at_least_40
- FAIL — test_product_families_at_least_20
- FAIL — retained_executed_cases_at_least_60
- FAIL — retained_executed_families_at_least_15

## Integrity and safety
- PASS — frozen_corpus_and_group_separation
- PASS — all_input_receipts_idempotent
- PASS — five_exact_repetitions
- PASS — all_published_citations_resolve
- PASS — all_citations_authorized_and_bounded
- PASS — committed_clean_source
- PASS — no_future_history
- PASS — no_external_network_or_subprocess
- PASS — zero_sensitive_canary_leaks
- PASS — zero_forbidden_claims
- PASS — zero_critical_high_dangerous_dismissals
- PASS — all_published_claims_supported
- PASS — no_unsupported_critical_reassurance

## Measured baselines
| Mode | Product recall | Macro F1 | Coverage |
|---|---:|---:|---:|
| constant_product_baseline | 1.000 | undefined | 1.000 |
| rules_only | 1.000 | undefined | 1.000 |
| rules_with_history | 1.000 | undefined | 1.000 |
| full_deterministic | 1.000 | undefined | 1.000 |

## Cases requiring review

## Limitations
- This is development/regression measurement, not a held-out test or full M6 acceptance.
- Case variants share mechanisms and are not independent population observations.
- Source kinds describe the actual producer; replay alone is not a fresh companion execution.
- Labels and scope are agent-reviewed, not independently blinded or expert-adjudicated.
- All original corpus minimums and numerical targets remain unchanged and visible.
- A missing category makes broad five-category acceptance unsupported regardless of displayed macro F1.
- Future independent families, a complete temporal backtest and the full adversarial suite remain required.
