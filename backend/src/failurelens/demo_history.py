"""Explicit reproducible synthetic history; never evaluation ground truth."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from .config import get_settings
from .models import Failure, ReviewEvent
from .retention import policy_for
from .schemas import IngestionRequest, ReviewCreate
from .service import add_review, analyze_and_persist, create_project, ingest_normalized

VERSION = 'synthetic-history-v1'
START = datetime(2026, 1, 1, tzinfo=UTC)


def seed_history(session):
    if not get_settings().demo_mode:
        raise ValueError('Synthetic history requires explicitly enabled demo mode')
    project = create_project(session, VERSION, 'Synthetic history · 100 runs · not benchmark data')
    # Keep this explicitly synthetic historical example usable across current dates.
    retention = policy_for(session, project.id)
    retention.source_days = retention.evidence_days = 3650
    session.commit()
    last = None
    for number in range(100):
        observations = []
        browser = ('chromium', 'firefox', 'webkit')[number % 3]
        for test in range(10):
            outcome, message, exception, details = 'passed', None, None, {}
            if test == 0 and (number % 6 == 0 or number in (87, 99)):
                outcome, message, exception = 'failed', 'reviewed harness timing instability', 'HarnessTimeout'
            elif test == 1 and number % 10 == 9:
                outcome, message, exception = 'failed', 'duplicate committed transfer left ledger unbalanced', 'LedgerInvariantError'
                details = {'data_integrity_violation': True}
            elif test == 2 and number % 9 == 0:
                outcome, message, exception = 'failed', 'Timeout waiting for checkout selector', 'TimeoutError'
            elif test == 8 and number % 5 == 0:
                outcome = 'skipped'
            elif test == 9 and number % 13 == 0:
                outcome = 'cancelled'
            item = dict(test_identity=f'history::test-{test:02d}', source_path=f'tests/synthetic_{test:02d}.py',
                        browser=browser, attempt=0, outcome=outcome, message=message,
                        exception_type=exception, duration_ms=40 + test * 7, details=details)
            observations.append(item)
            if test == 0 and outcome == 'failed' and number % 12 == 0:
                observations.append(item | {'attempt': 1, 'outcome': 'passed', 'message': None,
                                            'exception_type': None, 'details': {'retry_recovered': True}})
        last = ingest_normalized(session, project, IngestionRequest(
            external_id=f'{VERSION}-{number:03d}', repository='synthetic/history-demonstration',
            commit_sha=f'{number:040x}', branch='feature-demo' if number % 7 == 2 else 'main',
            run_scope='impact_selected' if number % 11 == 5 else 'full_suite', environment='synthetic-local',
            timezone='America/Halifax', worker_count=1 + number % 4, shard_count=2,
            expected_inputs=2 if number % 17 == 4 else 1,
            source_metadata={'synthetic': True, 'seed_version': VERSION, 'not_evaluation_ground_truth': True},
            observations=observations,
        ))
        stamp = START + timedelta(days=number)
        last.started_at = stamp
        last.ended_at = stamp + timedelta(minutes=5)
        last.created_at = stamp
        session.commit()
        # Seed only the initial synthetic review and final three-type walkthrough.
        if number in (0, 87, 99):
            failures = session.scalars(select(Failure).where(Failure.run_id == last.id)).all()
            for failure in failures:
                analysis = analyze_and_persist(session, failure)
                if number in (0, 87) and failure.execution.test_identity == 'history::test-00':
                    exists = session.scalar(select(ReviewEvent).where(ReviewEvent.analysis_id == analysis.id))
                    if not exists:
                        review = add_review(session, analysis, ReviewCreate(
                            decision='category_correction', proposed_category='known_flake',
                            reason='Synthetic reviewed harness timing reproduction for demonstration only; not human adjudication.',
                            expected_version=0), actor='synthetic-demo-fixture')
                        review.created_at = stamp + timedelta(hours=12)
                        session.commit()
    return {'project_id': project.id, 'run_id': last.id, 'seed_version': VERSION,
            'run_count': 100, 'logical_observations': 1000, 'start': START.isoformat(),
            'end': (START + timedelta(days=99)).isoformat(), 'synthetic': True,
            'notice': 'History demonstration only; does not increase the labeled evaluation denominator.'}
