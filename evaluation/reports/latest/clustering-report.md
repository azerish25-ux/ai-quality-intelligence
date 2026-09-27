# FailureLens deterministic clustering evaluation

- Cases: **24**
- Evaluation-only incident labels: **13**
- Predicted clusters: **13**
- Pairwise precision: **1.000**
- Pairwise recall: **1.000**
- False merges: **0**
- False splits: **0**
- Adjusted Rand index: **1.000**

## Acceptance gates
- PASS — `pairwise_precision_gte_0_95`
- PASS — `pairwise_recall_gte_0_90`
- PASS — `zero_false_merges`
- PASS — `false_splits_lte_1`
- PASS — `adjusted_rand_index_gte_0_90`
- PASS — `zero_missing_predictions`
- PASS — `zero_unexpected_predictions`

## Limitations
- All cases are synthetic and agent-authored.
- Incident labels are evaluation-only and are excluded from runtime clustering features.
- The fixture emphasizes collision boundaries and bridge prevention rather than production prevalence.
- Screenshot similarity and causal edge quality are not measured in this milestone.
