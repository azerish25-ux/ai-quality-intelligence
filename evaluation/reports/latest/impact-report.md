# FailureLens deterministic change-impact evaluation

- Cases: **12**
- Scenario families: **11**
- Defect-revealing-test recall: **1.000**
- Mandatory critical-test recall: **1.000**
- Expected fallback/focused status accuracy: **1.000**
- Focused cases: **7**
- Full-suite fallbacks: **5**

## Acceptance gates
- PASS — `critical_test_recall_eq_1`
- PASS — `defect_revealing_test_recall_eq_1`
- PASS — `expected_status_accuracy_eq_1`
- PASS — `deterministic_repeat_rate_eq_1`
- PASS — `zero_missed_defect_examples`

## Limitations
- All cases and mapping oracles are synthetic and agent-authored.
- Durations are declared fixture estimates, not observed runtime measurements.
- The fixture does not satisfy the required actual LedgerGuard execution count.
- Selection recall here is controlled-fixture recall, not population performance.
- No counterfactual production runtime savings are claimed.
