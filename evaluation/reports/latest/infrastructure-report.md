# FailureLens infrastructure-event correlation evaluation

Controlled synthetic evaluation of prior-only event compatibility, outcome accounting, leakage boundaries, and dangerous-downgrade safety.

- Cases: **18**
- Status accuracy: **1.000**
- Compatibility-selection accuracy: **1.000**
- Event-provenance validity: **1.000**
- Deterministic repeat agreement: **1.000**
- Future-event leakage: **0**
- Cross-project leakage: **0**
- Dangerous product-defect downgrades: **0/1**
- Unsupported causality claims: **0**

## Acceptance gates

- PASS — `status_accuracy_eq_1`
- PASS — `compatibility_selection_accuracy_eq_1`
- PASS — `deterministic_repeat_agreement_eq_1`
- PASS — `event_provenance_validity_eq_1`
- PASS — `zero_future_event_leakage`
- PASS — `zero_cross_project_leakage`
- PASS — `zero_dangerous_product_defect_downgrades`
- PASS — `zero_unsupported_causality_claims`
- PASS — `all_snapshots_persisted`
- PASS — `all_snapshot_digests_reused`

## Limitations

- Cases are controlled, synthetic, and agent-authored; they do not estimate production prevalence.
- The fixture evaluates deterministic compatibility, leakage, accounting, and dangerous-downgrade boundaries rather than causal attribution.
- A temporal association is never treated as proof that infrastructure caused a test outcome.
- The harness uses the real SQLAlchemy models, ingestion service, deterministic analyzer, and infrastructure-correlation engine against isolated SQLite databases.
- The fixture does not establish causality or independently blinded production generalization.
