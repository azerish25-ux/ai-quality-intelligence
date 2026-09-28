# LedgerGuard production-component challenge

**Scope: executed M6 component slice, not full M6 acceptance.**

FailureLens source: `7405d923e453a00e3460101bb9800fcfe2a8fb30`; dirty working tree: `False`.
LedgerGuard source: `13bdd62c924a3230825b6d9304f449f887c8e7fe`.
Database for the real FailureLens API/worker replay: `postgresql`.

60 executed interventions across 15 independent mechanisms; 60 passing controls.
Dangerous dismissals: **0/60**. Product recall: **0.800**. Product abstentions: **12**.
Five-category macro F1: **not established** (this slice has only product-defect ground truth).

## Executable integrity gates
- PASS — minimum_executed_cases
- PASS — minimum_executed_families
- PASS — all_controls_pass_and_interventions_fail
- PASS — all_citations_verified
- PASS — five_repeated_analyses
- PASS — no_critical_high_dangerous_dismissal
- PASS — no_forbidden_claims
- PASS — all_published_claims_typed_verified
- PASS — all_failures_hold_for_review

## Measured quality targets
- PASS — dangerous_dismissal_lte_5_percent
- FAIL — product_recall_gte_90_percent
- PASS — non_abstained_coverage_gte_75_percent

The integrity workflow checks truthful execution, safe publication and recovery. It does not convert a failed quality target into a pass. `--enforce-quality` fails for unmet targets.

## Baselines and ablations
| Mode | Product recall | Product abstentions | Dangerous dismissals |
|---|---:|---:|---:|
| constant_product_baseline | 1.000 | 0 | 0/60 |
| rules_only | 0.800 | 12 | 0/60 |
| rules_with_history | 0.800 | 12 | 0/60 |
| full_deterministic | 0.800 | 12 | 0/60 |

## Cases requiring review
- `c-7d8234662c3ddc40ae56` — idempotency-fingerprint-omits-operation: `insufficient_evidence`; Available observations do not distinguish the required categories safely.
- `c-471e1a2e40578f487b48` — idempotency-fingerprint-omits-operation: `insufficient_evidence`; Available observations do not distinguish the required categories safely.
- `c-98e9c3f45ad028a9460f` — idempotency-fingerprint-omits-operation: `insufficient_evidence`; Available observations do not distinguish the required categories safely.
- `c-bca9ae25931be305fd32` — idempotency-fingerprint-omits-operation: `insufficient_evidence`; Available observations do not distinguish the required categories safely.
- `c-76097303cf84919c0f35` — weekly-schedule-advances-six-days: `insufficient_evidence`; Available observations do not distinguish the required categories safely.
- `c-453b945eac9015ca7d7f` — weekly-schedule-advances-six-days: `insufficient_evidence`; Available observations do not distinguish the required categories safely.
- `c-79f504beed4c44dc861f` — weekly-schedule-advances-six-days: `insufficient_evidence`; Available observations do not distinguish the required categories safely.
- `c-7d8c8cac5c3f93fb323f` — weekly-schedule-advances-six-days: `insufficient_evidence`; Available observations do not distinguish the required categories safely.
- `c-72ab26de43ce340dfff1` — projection-replaces-newer-state-with-stale-event: `insufficient_evidence`; Available observations do not distinguish the required categories safely.
- `c-f06ffe783b7972e9b323` — projection-replaces-newer-state-with-stale-event: `insufficient_evidence`; Available observations do not distinguish the required categories safely.
- `c-6bb12fa13a8a9f3311b0` — projection-replaces-newer-state-with-stale-event: `insufficient_evidence`; Available observations do not distinguish the required categories safely.
- `c-57ccfd5a619f15950a30` — projection-replaces-newer-state-with-stale-event: `insufficient_evidence`; Available observations do not distinguish the required categories safely.

## Limits
- Real production-component execution only: no HTTP, PostgreSQL business transactions, rollback, concurrency, or committed-money oracle in LedgerGuard.
- All 60 cases are product defects. Five-class macro F1 and nonproduct precision/generalization are not established by this slice.
- The constant-product baseline is intentionally trivial on this one-category challenge; a perfect baseline does not validate diagnosis.
- This agent-authored public challenge is not a blinded/frozen test split. Inspected failures become regression evidence, never fresh held-out evidence.
- Four variants share each of 15 mechanisms. Case-level Wilson intervals assume independence and are only an illustration; family resampling is also limited.
- The old 200-case synthetic regression suite is not silently relabeled as real execution or independent scenario families.
- The full M6 200-case/80-independent-family, five-category leakage-controlled benchmark remains incomplete.
- Repeated API analysis recomputes the deterministic decision, but is not five independent whole-stack performance runs.
- Raw controlled producer artifacts and exported safe derivatives have finite CI retention; API UUID links require the originating database.
