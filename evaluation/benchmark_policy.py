"""Versioned acceptance policy; never infer targets from measured results."""

CATEGORIES = (
    "product_defect",
    "test_defect",
    "infrastructure_failure",
    "known_flake",
    "insufficient_evidence",
)
POLICY = {
    "schema_version": "benchmark-policy-v1",
    "minimum_cases": 200,
    "minimum_families": 80,
    "minimum_category_counts": dict(zip(CATEGORIES, (80, 30, 30, 30, 30))),
    "minimum_executed_cases": 60,
    "minimum_executed_families": 15,
    "minimum_test_cases": 100,
    "minimum_test_products": 40,
    "minimum_test_product_families": 20,
    "product_recall_minimum": 0.90,
    "macro_f1_minimum": 0.80,
    "decision_coverage_minimum": 0.75,
    "dangerous_dismissal_maximum": 0.05,
    "critical_high_dangerous_dismissals_maximum": 0,
    "repetitions": 5,
    "minimum_adversarial_cases": 40,
}
