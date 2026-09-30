from datetime import datetime, timezone

from sqlalchemy import select

from failurelens.demo import seed_demo
from failurelens.models import Analysis, Run, TestExecution as Execution, Outcome
from failurelens.github_snapshot import report_snapshot


def test_preview_matches_persisted_data_and_is_deterministic(client, session):
    seeded = seed_demo(session)
    response = client.get(f"/api/v1/runs/{seeded['run_id']}/github-report-preview")
    assert response.status_code == 200
    report = response.json()
    assert report['schema_version'] == 'github-report-v2'
    assert report['outcomes']['logical_tests'] == 4
    assert report['outcomes']['failed'] == 3
    assert report['outcomes']['passed'] == 1
    assert report['analysis_count'] == 3
    assert report['baseline_status'] == 'unknown'
    assert 'HOLD_FOR_REVIEW' in report['markdown']
    assert response.json() == client.get(f"/api/v1/runs/{seeded['run_id']}/github-report-preview").json()


def test_retry_outcomes_do_not_inflate_independent_test_count(session):
    seeded = seed_demo(session)
    run = session.get(Run, seeded['run_id'])
    existing = session.scalar(select(Execution).where(Execution.run_id == run.id, Execution.outcome == Outcome.failed))
    session.add(Execution(run_id=run.id, test_identity=existing.test_identity, browser=existing.browser, parameterization=existing.parameterization, attempt=existing.attempt + 1, outcome=Outcome.passed, details={}))
    session.commit()
    report = report_snapshot(session, run)
    assert report['outcomes']['logical_tests'] == 4
    assert report['outcomes']['attempts'] == 5
    assert report['outcomes']['retried'] == 1
    assert report['outcomes']['retry_recovered'] == 1
    assert report['outcomes']['failed'] == 2


def test_legacy_unvalidated_summary_and_expired_evidence_withheld(session):
    seeded = seed_demo(session)
    run = session.get(Run, seeded['run_id'])
    analysis = session.scalar(select(Analysis))
    analysis.validation_results = None
    analysis.summary = 'safe to merge unvalidated canary'
    session.commit()
    report = report_snapshot(session, run)
    assert 'unvalidated canary' not in str(report)
    run.evidence_expired_at = datetime.now(timezone.utc)
    session.commit()
    report = report_snapshot(session, run)
    assert report['completeness'] == 'evidence_expired'
    assert all(x['category'] == 'insufficient_evidence' and not x['supporting_evidence_ids'] for x in report['analyses'])


def test_missing_preview_returns_404(client):
    assert client.get('/api/v1/runs/absent/github-report-preview').status_code == 404


def test_preview_requires_project_role(client, session):
    seeded = seed_demo(session)
    # An authenticated principal with no membership must see the normal not-found boundary.
    from failurelens.auth import create_user
    user = create_user(session, username='outsider', display_name='Outsider', password='long-test-password')
    session.commit()
    response = client.post('/api/v1/auth/login', json={'username': 'outsider', 'password': 'long-test-password'})
    assert response.status_code == 200
    response = client.get(f"/api/v1/runs/{seeded['run_id']}/github-report-preview")
    assert response.status_code == 404


def test_preview_rechecks_post_analysis_evidence_restriction(session):
    from failurelens.models import Evidence
    seeded = seed_demo(session)
    run = session.get(Run, seeded['run_id'])
    analysis = session.scalar(select(Analysis).where(Analysis.category == 'product_defect'))
    evidence = session.get(Evidence, analysis.supporting_evidence_ids[0])
    evidence.derivative.restricted = True
    session.commit()
    report = report_snapshot(session, run)
    row = next(x for x in report['analyses'] if x['analysis_id'] == analysis.id)
    assert row['category'] == 'insufficient_evidence'
    assert row['supporting_evidence_ids'] == []
    assert row['summary'] == 'Evidence unavailable or publication validation incomplete; review required.'
