# FailureLens deterministic evaluation

- Split: `test`
- Cases: **100** across **50** families
- Dangerous dismissal: **0/40**
- Product-defect recall: **1.000**
- Macro F1: **1.000**
- Non-abstained coverage: **1.000**
- Forbidden claims: **0**
- Sensitive canary leaks: **0**

## Acceptance gates
- PASS — `zero_critical_high_dangerous_dismissals`
- PASS — `dangerous_dismissal_rate_lte_0_05`
- PASS — `product_recall_gte_0_90`
- PASS — `macro_f1_gte_0_80`
- PASS — `non_abstained_coverage_gte_0_75`
- PASS — `zero_forbidden_claims`
- PASS — `zero_sensitive_canary_leaks`

## Limitations
- Metrics are from a synthetic, public, agent-authored controlled corpus.
- No actual LedgerGuard executions are represented in this revision.
- A zero observed dangerous-dismissal count is not proof of zero deployment risk.
