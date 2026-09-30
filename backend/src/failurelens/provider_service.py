"""Database-to-provider bridge: only revalidated safe derivatives may leave."""
from dataclasses import asdict

from sqlalchemy.orm import Session

from .evidence_validation import persisted_analysis_is_publication_validated, validate_evidence_records
from .models import Analysis
from .providers import HTTPModelProvider, ProviderResult, RunBudget
from .service import select_failure_evidence


def propose_for_analysis(session: Session, analysis: Analysis, provider: HTTPModelProvider,
                         *, budget: RunBudget, cancel=None) -> dict:
    category = analysis.category.value
    if not persisted_analysis_is_publication_validated(analysis):
        return asdict(ProviderResult('fallback', category, reason='unvalidated_deterministic_analysis'))
    failure = analysis.failure
    if failure.run.evidence_expired_at is not None:
        return asdict(ProviderResult('fallback', category, reason='evidence_expired'))
    rows = select_failure_evidence(session, failure)
    checks = validate_evidence_records(failure, rows)
    accepted = set(checks.accepted_ids)
    permitted = set(analysis.supporting_evidence_ids + analysis.contradictory_evidence_ids)
    evidence = [{'id': row.id, 'excerpt': row.excerpt, 'approved': True}
                for row in rows if row.id in accepted and row.id in permitted]
    result = provider.propose(deterministic_category=category, evidence=evidence, budget=budget, cancel=cancel)
    # The deterministic row is intentionally never overwritten or reclassified.
    return asdict(result)
