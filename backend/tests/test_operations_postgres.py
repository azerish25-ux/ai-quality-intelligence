"""Real PostgreSQL locking coverage. Never silently substitute SQLite for this lane."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from failurelens import accounts, models as m, retention
from failurelens.auth import DEMO_PRINCIPAL, Principal, create_auth_session, create_user
from failurelens.config import Settings
from failurelens.db import Base
from failurelens.governance import review_queue_page
from failurelens.jobs import process_next
from failurelens.schemas import IngestionRequest
from failurelens.service import analyze_and_persist, create_project, ingest_normalized

PASSWORD = "postgres-concurrency-test-password"


@pytest.fixture
def pg_factory(tmp_path):
    url = os.environ.get("FAILURELENS_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("a real PostgreSQL FAILURELENS_DATABASE_URL is required")
    schema = "m53_" + uuid4().hex
    admin_engine = create_engine(url)
    with admin_engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    # Only this disposable schema, not public: create_all must not discover and
    # reuse the CI application's public tables or native enum types.
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, expire_on_commit=False), Settings(
            database_url=url, artifact_root=tmp_path / "artifacts", demo_mode=True)
    finally:
        engine.dispose()
        with admin_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


def _admin(session, username):
    user = create_user(session, username=username, display_name=username,
                       password=PASSWORD, system_admin=True)
    auth_session, _ = create_auth_session(session, user, settings=Settings(demo_mode=True))
    session.commit()
    return user.id, Principal(kind="user", actor_id=user.id, user_id=user.id,
        display_name=user.display_name, session_id=auth_session.id, system_admin=True)


def test_postgres_two_administrators_cannot_disable_each_other(pg_factory):
    factory, _ = pg_factory
    with factory() as session:
        first, first_actor = _admin(session, "first-admin")
        second, second_actor = _admin(session, "second-admin")
    barrier = Barrier(2)

    def deactivate(actor, target):
        with factory() as session:
            barrier.wait(timeout=10)
            try:
                accounts.change_account(session, actor, target, password=PASSWORD,
                    active=False, expected_version=0, reason="Concurrent disable test")
                return 200
            except HTTPException as exc:
                session.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(deactivate, first_actor, second)
        b = executor.submit(deactivate, second_actor, first)
        results = [a.result(timeout=20), b.result(timeout=20)]
    assert results.count(200) == 1
    assert all(status in {200, 401, 409} for status in results)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.User).where(
            m.User.is_system_admin.is_(True), m.User.is_active.is_(True))) == 1


def test_postgres_recovery_token_is_consumed_once_under_contention(pg_factory):
    factory, _ = pg_factory
    with factory() as session:
        user = create_user(session, username="recover-once", display_name="Recovery",
                           password=PASSWORD, system_admin=False)
        session.commit()
        _, _, raw = accounts.issue_recovery(session, DEMO_PRINCIPAL, user.id,
            password="", expected_version=0, reason="Controlled recovery test")
    barrier = Barrier(2)

    def redeem():
        with factory() as session:
            barrier.wait(timeout=10)
            try:
                accounts.redeem_recovery(session, raw, "postgres-new-recovery-password")
                return 204
            except HTTPException as exc:
                session.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        a, b = executor.submit(redeem), executor.submit(redeem)
        assert sorted([a.result(timeout=20), b.result(timeout=20)]) == [204, 400]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.AuditEvent).where(
            m.AuditEvent.action == "auth.recovery_completed")) == 1


def test_postgres_native_enum_review_search_and_retention_worker(pg_factory, monkeypatch):
    factory, settings = pg_factory
    monkeypatch.setenv("FAILURELENS_ARTIFACT_ROOT", str(settings.artifact_root))
    from failurelens.config import get_settings
    get_settings.cache_clear()
    try:
        with factory() as session:
            project = create_project(session, "postgres-governance", "Postgres Governance")
            run = ingest_normalized(session, project, IngestionRequest.model_validate({
                "external_id": "old", "observations": [{"test_identity": "older-payment",
                "outcome": "failed", "message": "duplicate transfer committed and ledger became unbalanced",
                "details": {"data_integrity_violation": True}}]}))
            failure = session.scalar(select(m.Failure).where(m.Failure.run_id == run.id))
            analyze_and_persist(session, failure)
            run.created_at = m.utcnow() - timedelta(days=100)
            session.commit()
            assert review_queue_page(session, project.id, search="product_defect").total == 1
            job = retention.enqueue(session, project.id, retention.preview(session, project.id), DEMO_PRINCIPAL)
            for _ in range(10):
                process_next(session, "postgres-worker", settings=settings)
                session.refresh(job)
                if job.state not in {m.JobState.queued, m.JobState.running}:
                    break
            assert job.state == m.JobState.succeeded
            session.refresh(run)
            assert run.evidence_expired_at is not None
            assert review_queue_page(session, project.id, search="older-payment").items[0].evidence_completeness == "expired"
    finally:
        get_settings.cache_clear()


def test_postgres_binary_review_optimistic_revision_and_expiry_serialization(pg_factory, monkeypatch):
    from failurelens.binary_evidence import review_screenshot, decide
    from failurelens.binary_schemas import ScreenshotReview, BinaryDecisionCreate
    from failurelens.service import enqueue_artifact_ingestion
    from failurelens.schemas import RunMetadata
    from failurelens.storage import store_bytes
    from failurelens.config import get_settings
    from test_binary_evidence import image_bytes
    factory, settings = pg_factory
    monkeypatch.setenv('FAILURELENS_ARTIFACT_ROOT', str(settings.artifact_root))
    get_settings.cache_clear()
    image = image_bytes()
    try:
        with factory() as session:
            project = create_project(session, 'binary-contention', 'Binary contention')
            stored = store_bytes(image, root=settings.artifact_root, project_id=project.id, filename='actual.png',
                                 media_type='image/png', max_bytes=settings.max_file_bytes)
            ingestion = enqueue_artifact_ingestion(session, project, RunMetadata(external_id='binary-concurrency'), stored, settings=settings)
            assert process_next(session, 'pg-binary-worker', settings=settings)
            session.refresh(ingestion)
            state = session.scalar(select(m.BinaryEvidence).where(m.BinaryEvidence.run_id == ingestion.run_id))
            input_id, run_id, project_id = state.input_id, state.run_id, project.id
        barrier = Barrier(2)
        def submit():
            with factory() as session:
                barrier.wait(timeout=10)
                try:
                    review_screenshot(session, DEMO_PRINCIPAL, input_id, ScreenshotReview(
                        expected_version=0, reason='Concurrent approved screenshot review', confirm_safe=True), image, settings)
                    return 201
                except HTTPException as exc:
                    session.rollback(); return exc.status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            first, second = executor.submit(submit), executor.submit(submit)
            assert sorted([first.result(timeout=30), second.result(timeout=30)]) == [201, 409]
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(m.BinaryEvidenceDecision)) == 1
            retention.lock_project(session, project_id)
            retention._scrub_run(session, session.get(m.Run, run_id), 1)
            session.commit()
        with factory() as session:
            with pytest.raises(HTTPException) as error:
                review_screenshot(session, DEMO_PRINCIPAL, input_id, ScreenshotReview(
                    expected_version=1, reason='Expired screenshot must not be approved', confirm_safe=True), image, settings)
            assert error.value.status_code == 410
            session.rollback()
            assert not session.scalar(select(m.ArtifactDerivative).where(m.ArtifactDerivative.approved.is_(True), m.ArtifactDerivative.retention_state == "active"))
    finally:
        get_settings.cache_clear()
