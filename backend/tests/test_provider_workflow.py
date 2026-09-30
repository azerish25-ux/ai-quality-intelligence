"""Application provider workflow uses fixture-only transports and real sessions."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx
import pytest
from failurelens import models as m
from failurelens.api import app
from failurelens.auth import Principal, create_auth_session, create_user
from failurelens.config import Settings
from failurelens.db import get_session
from failurelens.jobs import claim_next
from failurelens.provider_jobs import (
    ApplicationAttemptBudget,
    claim_provider_job,
    database_now,
    heartbeat_provider_worker,
    project_invocation,
    provider_preview,
    provider_status,
    recover_provider_jobs,
    run_provider_once,
    submit_model_invocation,
)
from failurelens.provider_schemas import ProviderSubmit
from failurelens.provider_service import _digest
from failurelens.providers import (
    HTTPModelProvider,
    ProviderResult,
)
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_provider_ledger import good_response, seed_scope

pytest_plugins = ("test_provider_ledger",)


def application_scope(factory):
    scope = seed_scope(factory)
    with factory.begin() as session:
        user = create_user(
            session,
            username="provider-admin",
            display_name="Provider operator",
            password="fixture-password-is-not-secret",
        )
        auth, token = create_auth_session(session, user)
        session.add(
            m.ProjectMembership(
                project_id=scope["project_id"],
                user_id=user.id,
                role=m.ProjectRole.administrator,
            )
        )
        principal = Principal(
            "user", user.id, user.display_name, user_id=user.id, session_id=auth.id
        )
    settings = Settings(
        demo_mode=False,
        session_cookie_secure=True,
        bootstrap_admin_username="provider-admin",
        bootstrap_admin_password="fixture-password-is-not-secret",
        provider_enabled="true",
        provider_id="fixture-provider",
        provider_allowed_project_ids=scope["project_id"],
        provider_endpoint="https://provider.example/private-path",
        provider_model="test-fixture-not-a-model",
        provider_token="fixture-credential",
        provider_max_attempts="1",
        provider_min_interval_seconds="0",
    )
    return scope, principal, token, settings


@pytest.fixture
def workflow(ledger_factory, monkeypatch):
    import failurelens.auth as auth_module
    import failurelens.provider_api as api_module

    scope, principal, token, settings = application_scope(ledger_factory)
    api_settings = settings.model_copy(update={"provider_token": None})
    monkeypatch.setattr(api_module, "get_settings", lambda: api_settings)
    monkeypatch.setattr(auth_module, "get_settings", lambda: api_settings)

    def sessions():
        with ledger_factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {token}"
    base = "/api/v1/projects/{project_id}/runs/{run_id}/analyses/{analysis_id}/provider".format(
        **scope
    )
    try:
        yield ledger_factory, scope, principal, settings, api_settings, client, base
    finally:
        client.close()
        app.dependency_overrides.clear()


def submit(factory, scope, principal, settings, key="one"):
    heartbeat_provider_worker(factory, settings)
    with factory.begin() as session:
        preview = provider_preview(session, settings, principal, **scope)
        request = ProviderSubmit(
            analysis_revision=preview["analysis_revision"],
            preview_digest=preview["preview_digest"],
            configuration_digest=preview["configuration_digest"],
            idempotency_key=key,
        )
        row = submit_model_invocation(
            session, settings, principal, **scope, request=request
        )
        return row.id, request


def read(factory, settings, invocation_id):
    with factory() as session:
        return project_invocation(
            session, settings, session.get(m.ModelInvocation, invocation_id)
        )


def fixture_provider(handler=good_response):
    return lambda config: HTTPModelProvider(
        config, transport=httpx.MockTransport(handler)
    )


def test_disabled_and_invalid_config_keep_deterministic_http_available(
    workflow, monkeypatch
):
    factory, scope, _principal, settings, api_settings, client, base = workflow
    monkeypatch.setattr(
        HTTPModelProvider,
        "__init__",
        lambda *a, **kw: pytest.fail("disabled transport"),
    )
    for enablement, endpoint, state in (
        ("false", settings.provider_endpoint, "disabled"),
        ("true", "http://invalid", "invalid_configuration"),
    ):
        api_settings.provider_enabled = enablement
        api_settings.provider_endpoint = endpoint
        response = client.get(base + "/preview")
        assert response.status_code == 200
        assert response.json()["availability"] == state
        assert not response.json()["can_submit"]
        assert client.get("/api/v1/runs/" + scope["run_id"]).status_code == 200
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.ModelInvocation)) == 0


def test_authenticated_admin_preview_enqueue_status_and_safe_worker_result(workflow):
    factory, _scope, principal, settings, _api_settings, client, base = workflow
    first = client.get(base + "/preview").json()
    assert first["availability"] == "worker_unavailable" and not first["can_submit"]
    heartbeat_provider_worker(factory, settings)
    preview = client.get(base + "/preview").json()
    assert preview["can_submit"] and preview["availability"] == "ready"
    assert preview["destination"]["endpoint"] == "https://provider.example"
    assert preview["evidence"] and preview["reserved_tokens_per_attempt"] > 0
    body = {
        key: preview[key]
        for key in ("analysis_revision", "preview_digest", "configuration_digest")
    }
    body["idempotency_key"] = "http-submit"
    response = client.post(base + "/invocations", json=body)
    assert response.status_code == 202, response.text
    data = response.json()
    assert data["invocation_state"] == "queued" and data["attempts"] == []
    assert (
        client.post(base + "/invocations", json=body).json()["invocation_id"]
        == data["invocation_id"]
    )
    with factory() as session:
        assert claim_next(session, "ordinary-worker", 30) is None
        event_row = session.scalar(
            select(m.AuditEvent).where(m.AuditEvent.action == "provider.submitted")
        )
        assert event_row.actor_user_id == principal.user_id
        job = session.get(m.Job, data["job_id"])
        assert {
            key: job.payload[key] for key in ("schema_version", "invocation_id")
        } == {
            "schema_version": "1.0",
            "invocation_id": data["invocation_id"],
        }
        assert set(job.payload) <= {"schema_version", "invocation_id", "traceparent"}
    assert run_provider_once(factory, settings, provider_factory=fixture_provider())
    result = client.get(base + "/invocations/" + data["invocation_id"]).json()
    assert result["invocation_state"] == "proposed" and result["proposal"]
    assert result["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}
    assert result["attempts"][0]["transport_terminated"]
    assert result["analysis_digest"] == preview["analysis_digest"]
    assert result["evidence_digest"] == preview["evidence_digest"]
    assert result["validation_status"] == "unverified_hypotheses_only"
    assert client.get(base + "/invocations").json()["items"] == [result]
    serialized = json.dumps(result)
    for private in (
        "fixture-credential",
        "/private-path",
        "owner_token",
        "lease_owner",
        "messages",
        "request_id",
    ):
        assert private not in serialized
    with factory() as session:
        assert (
            session.get(
                m.ModelProviderAdmission, _digest(settings.provider_id)
            ).active_permits
            == 0
        )


@pytest.mark.parametrize("kind", ["demo", "token", "viewer", "reviewer", "outsider"])
def test_http_role_token_demo_and_project_boundaries(workflow, kind):
    factory, scope, principal, settings, _api_settings, client, base = workflow
    heartbeat_provider_worker(factory, settings)
    preview = client.get(base + "/preview").json()
    body = {
        key: preview[key]
        for key in ("analysis_revision", "preview_digest", "configuration_digest")
    }
    body["idempotency_key"] = kind
    if kind == "demo":
        workflow[4].demo_mode = True
        client.headers.pop("Authorization")
    elif kind == "token":
        from failurelens.auth import create_project_ingestion_token

        with factory.begin() as session:
            _, token = create_project_ingestion_token(
                session,
                project_id=scope["project_id"],
                name="fixture",
                created_by_user_id=principal.user_id,
            )
        client.headers["Authorization"] = f"Bearer {token}"
    else:
        with factory.begin() as session:
            membership = session.scalar(
                select(m.ProjectMembership).where(
                    m.ProjectMembership.user_id == principal.user_id
                )
            )
            if kind == "outsider":
                session.delete(membership)
            else:
                membership.role = m.ProjectRole(kind)
    response = client.post(base + "/invocations", json=body)
    assert response.status_code == (404 if kind == "outsider" else 403)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.ModelInvocation)) == 0


def test_http_payload_cannot_supply_endpoint_prompt_or_evidence(workflow):
    factory, _scope, _principal, settings, _api_settings, client, base = workflow
    heartbeat_provider_worker(factory, settings)
    preview = client.get(base + "/preview").json()
    body = {
        key: preview[key]
        for key in ("analysis_revision", "preview_digest", "configuration_digest")
    }
    body["idempotency_key"] = "bounded"
    for key in ("endpoint", "token", "prompt", "evidence", "model"):
        result = client.post(base + "/invocations", json=body | {key: "secret-example"})
        assert result.status_code == 422 and "secret-example" not in result.text
    for key, value in (
        ("analysis_revision", 999),
        ("preview_digest", "0" * 64),
        ("configuration_digest", "0" * 64),
    ):
        assert (
            client.post(base + "/invocations", json=body | {key: value}).status_code
            == 409
        )


def test_duplicate_reconciles_after_configuration_change_and_conflicts_are_rejected(
    workflow,
):
    factory, scope, principal, settings, api_settings, client, base = workflow
    invocation_id, request = submit(factory, scope, principal, settings)
    api_settings.provider_model = "rotated-model"
    response = client.post(base + "/invocations", json=request.model_dump())
    assert (
        response.status_code == 202
        and response.json()["invocation_id"] == invocation_id
    )
    assert response.json()["reason"] == "provider_configuration_changed"
    response = client.post(
        base + "/invocations", json=request.model_dump() | {"preview_digest": "0" * 64}
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    "revocation",
    ["role", "session", "user", "evidence", "analysis", "configuration", "allowlist"],
)
def test_revocation_before_execution_never_calls_transport(workflow, revocation):
    factory, scope, principal, settings, _api_settings, _client, _base = workflow
    invocation_id, _ = submit(factory, scope, principal, settings)
    with factory.begin() as session:
        if revocation == "role":
            session.scalar(select(m.ProjectMembership)).role = m.ProjectRole.viewer
        elif revocation == "session":
            session.get(m.AuthSession, principal.session_id).revoked_at = m.utcnow()
        elif revocation == "user":
            session.get(m.User, principal.user_id).is_active = False
        elif revocation == "evidence":
            analysis = session.get(m.Analysis, scope["analysis_id"])
            session.get(
                m.Evidence, analysis.supporting_evidence_ids[0]
            ).derivative.restricted = True
        elif revocation == "analysis":
            session.get(m.Analysis, scope["analysis_id"]).summary = "changed"
    if revocation == "configuration":
        settings.provider_model = "changed-model"
    if revocation == "allowlist":
        settings.provider_allowed_project_ids = m.new_id()
    run_provider_once(
        factory, settings, provider_factory=lambda _: pytest.fail("revoked transport")
    )
    result = read(factory, settings, invocation_id)
    assert (
        result["invocation_state"] == "fallback"
        and not result["proposal"]
        and result["attempts"] == []
    )


def test_cancel_commits_before_acknowledgement_and_prevents_worker_execution(workflow):
    factory, scope, principal, settings, _api_settings, client, base = workflow
    invocation_id, _ = submit(factory, scope, principal, settings)
    response = client.post(base + "/invocations/" + invocation_id + "/cancel")
    assert response.status_code == 200 and response.json()["cancel_requested_at"]
    assert response.json()["invocation_state"] == "cancelled"
    assert not run_provider_once(
        factory, settings, provider_factory=lambda _: pytest.fail("cancelled transport")
    )
    assert (
        client.post(base + "/invocations/" + invocation_id + "/cancel").json()
        == response.json()
    )
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(m.AuditEvent)
                .where(m.AuditEvent.action == "provider.cancelled")
            )
            == 1
        )


def test_cancel_during_transport_fences_proposal_and_retains_reservation(workflow):
    factory, scope, principal, settings, _api_settings, client, base = workflow
    invocation_id, _ = submit(factory, scope, principal, settings)
    entered, release = threading.Event(), threading.Event()

    def handler(request):
        entered.set()
        assert release.wait(5)
        return good_response(request)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            run_provider_once,
            factory,
            settings,
            provider_factory=fixture_provider(handler),
        )
        assert entered.wait(5)
        response = client.post(base + "/invocations/" + invocation_id + "/cancel")
        assert (
            response.status_code == 200
            and response.json()["invocation_state"] == "cancelled"
        )
        assert response.json()["recovery_required"]
        release.set()
        assert future.result(5)
    result = read(factory, settings, invocation_id)
    assert not result["proposal"] and result["budget"]["requests"] == 1
    assert result["invocation_state"] == "cancelled"


def expire_claim(factory, invocation_id):
    with factory.begin() as session:
        row = session.get(m.ModelInvocation, invocation_id)
        row.lease_expires_at = database_now(session) - timedelta(seconds=1)


def test_recovery_before_reservation_requeues_but_after_reservation_never_resends(
    workflow,
):
    factory, scope, principal, settings, _api_settings, _client, _base = workflow
    invocation_id, _ = submit(factory, scope, principal, settings)
    first = claim_provider_job(factory, settings)
    assert first
    expire_claim(factory, invocation_id)
    assert recover_provider_jobs(factory) == 1
    second = claim_provider_job(factory, settings)
    assert second and second[3] != first[3]
    from failurelens.providers import prepare_request

    config, snapshot = second[4:]
    budget = ApplicationAttemptBudget(
        factory,
        invocation_id,
        scope["project_id"],
        scope["run_id"],
        second[3],
        config,
        settings=settings,
    )
    number = budget.reserve(
        config,
        prepare_request(config, snapshot.category, snapshot.evidence).reserved_tokens,
    )
    assert number == 1
    expire_claim(factory, invocation_id)
    assert recover_provider_jobs(factory) == 1
    assert not run_provider_once(
        factory, settings, provider_factory=lambda _: pytest.fail("uncertain resend")
    )
    result = read(factory, settings, invocation_id)
    assert result["invocation_state"] == "uncertain" and result["recovery_required"]
    assert result["budget"]["requests"] == 1
    with factory() as session:
        status = provider_status(session, settings, principal, scope["project_id"])
        assert status["availability"] == "recovery_required"
    budget.complete(
        number,
        ProviderResult(
            "proposed",
            "product_defect",
            usage={"prompt_tokens": 8, "completion_tokens": 2},
        ),
        sent=True,
        http_status=200,
    )
    result = read(factory, settings, invocation_id)
    assert result["invocation_state"] == "uncertain" and not result["proposal"]
    assert (
        result["usage"] == {"prompt_tokens": 8, "completion_tokens": 2}
        and not result["recovery_required"]
    )
    with factory() as session:
        assert (
            session.get(
                m.ModelProviderAdmission, _digest(settings.provider_id)
            ).active_permits
            == 0
        )


def test_reservation_and_permit_commit_failure_prevents_transport(workflow):
    factory, scope, principal, settings, _api_settings, _client, _base = workflow
    invocation_id, _ = submit(factory, scope, principal, settings)

    @event.listens_for(Session, "before_commit")
    def fail_commit(session):
        if session.info.get("contains_attempt") or any(
            isinstance(row, m.ModelAttempt) for row in session.new
        ):
            raise OperationalError(
                "commit failed", {}, Exception("private database text")
            )

    @event.listens_for(Session, "after_flush")
    def track_attempt(session, _):
        if any(isinstance(row, m.ModelAttempt) for row in session.new):
            session.info["contains_attempt"] = True

    try:
        with pytest.raises(OperationalError):
            run_provider_once(
                factory,
                settings,
                provider_factory=fixture_provider(
                    lambda _: pytest.fail("uncommitted transport")
                ),
            )
    finally:
        event.remove(Session, "before_commit", fail_commit)
        event.remove(Session, "after_flush", track_attempt)
    with factory() as session:
        assert (
            session.get(
                m.ModelProviderAdmission, _digest(settings.provider_id)
            ).active_permits
            == 0
        )
        assert session.get(m.ModelRunBudget, scope["run_id"]).requests == 0
    expire_claim(factory, invocation_id)
    assert recover_provider_jobs(factory) == 1
    assert run_provider_once(factory, settings, provider_factory=fixture_provider())


def test_service_circuit_and_rate_survive_adapter_and_token_rotation(workflow):
    factory, scope, principal, settings, _api_settings, _client, _base = workflow
    settings.provider_failure_threshold = "1"
    settings.provider_min_interval_seconds = "10"
    invocation_id, _ = submit(factory, scope, principal, settings)
    assert run_provider_once(
        factory,
        settings,
        provider_factory=fixture_provider(lambda _: httpx.Response(503)),
    )
    with factory() as session:
        status = provider_status(session, settings, principal, scope["project_id"])
        assert status["availability"] == "circuit_open"
    from pydantic import SecretStr

    settings.provider_token = SecretStr("rotated-fixture-credential")
    heartbeat_provider_worker(factory, settings)
    with factory() as session:
        assert (
            provider_status(session, settings, principal, scope["project_id"])[
                "availability"
            ]
            == "circuit_open"
        )
    with factory.begin() as session:
        session.get(
            m.ModelProviderAdmission, _digest(settings.provider_id)
        ).open_until = database_now(session) - timedelta(seconds=1)
    with factory() as session:
        assert (
            provider_status(session, settings, principal, scope["project_id"])[
                "availability"
            ]
            == "rate_limited"
        )
    assert read(factory, settings, invocation_id)["budget"]["requests"] == 1


def test_bounded_concurrency_survives_lease_expiry_and_adapter_recreation(workflow):
    factory, scope, principal, settings, _api_settings, _client, _base = workflow
    settings.provider_concurrency = "1"
    first, _ = submit(factory, scope, principal, settings, "first")
    second, _ = submit(factory, scope, principal, settings, "second")
    entered, release = threading.Event(), threading.Event()

    def handler(request):
        entered.set()
        assert release.wait(5)
        return good_response(request)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            run_provider_once,
            factory,
            settings,
            provider_factory=fixture_provider(handler),
        )
        assert entered.wait(5)
        expire_claim(factory, first)
        assert recover_provider_jobs(factory) == 1
        assert run_provider_once(
            factory,
            settings,
            provider_factory=fixture_provider(
                lambda _: pytest.fail("permit released on recovery")
            ),
        )
        assert read(factory, settings, second)["invocation_state"] == "queued"
        release.set()
        assert future.result(5)
    result = read(factory, settings, first)
    assert result["invocation_state"] == "uncertain" and result["proposal"] is None
    assert result["budget"]["requests"] == 1


def test_read_withholds_after_requester_evidence_or_config_revocation(workflow):
    factory, scope, principal, settings, _api_settings, client, base = workflow
    invocation_id, _ = submit(factory, scope, principal, settings)
    assert run_provider_once(factory, settings, provider_factory=fixture_provider())
    with factory.begin() as session:
        session.scalar(select(m.ProjectMembership)).role = m.ProjectRole.viewer
    response = client.get(base + "/invocations/" + invocation_id)
    assert response.status_code == 200 and response.json()["proposal"] is None
    assert response.json()["reason"] == "requester_authorization_revoked"
    assert response.json()["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}


def test_proxy_fixture_precedence_and_transport_logs_are_secret_free(
    workflow, monkeypatch, caplog
):
    import logging
    import socket

    factory, scope, principal, settings, _api_settings, _client, _base = workflow
    settings.provider_proxy = "http://provider-proxy:8080"
    settings.provider_endpoint = "https://provider.example/private-destination-canary"
    invocation_id, _ = submit(factory, scope, principal, settings)
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **kw: pytest.fail("fixture DNS escape")
    )
    monkeypatch.setattr(
        socket.socket, "connect", lambda *a, **kw: pytest.fail("fixture network escape")
    )

    def handler(request):
        logging.getLogger("httpcore.http11").debug(
            "response-provider-id-private-canary"
        )
        return good_response(request)

    with caplog.at_level(logging.DEBUG):
        assert run_provider_once(
            factory, settings, provider_factory=fixture_provider(handler)
        )
    result = read(factory, settings, invocation_id)
    assert result["invocation_state"] == "proposed"
    serialized = caplog.text + str(result)
    for value in (
        "private-destination-canary",
        "response-provider-id-private-canary",
        "fixture-credential",
    ):
        assert value not in serialized


def test_malformed_configuration_errors_never_echo_secret_urls(workflow, caplog):
    _factory, _scope, _principal, settings, api_settings, client, base = workflow
    api_settings.provider_endpoint = "https://user:private-url-canary@provider.example/"
    response = client.get(base + "/preview")
    assert response.status_code == 200
    assert response.json()["availability"] == "invalid_configuration"
    assert "private-url-canary" not in response.text + caplog.text
    api_settings.provider_endpoint = settings.provider_endpoint
    api_settings.provider_proxy = "http://user:private-proxy-canary@proxy.example:8080"
    response = client.get(base + "/preview")
    assert (
        response.status_code == 200
        and response.json()["availability"] == "invalid_configuration"
    )
    assert "private-proxy-canary" not in response.text + caplog.text


def test_cross_run_and_analysis_status_and_cancel_scope_are_not_found(workflow):
    factory, scope, principal, settings, _api_settings, client, base = workflow
    invocation_id, _ = submit(factory, scope, principal, settings)
    for key in ("project_id", "run_id", "analysis_id"):
        wrong = base.replace(scope[key], m.new_id())
        assert client.get(wrong + "/preview").status_code == 404
        assert client.get(wrong + "/invocations/" + invocation_id).status_code == 404
        assert (
            client.post(wrong + "/invocations/" + invocation_id + "/cancel").status_code
            == 404
        )
    assert read(factory, settings, invocation_id)["invocation_state"] == "queued"


def test_ordinary_worker_never_reclaims_expired_provider_job(workflow):
    factory, scope, principal, settings, _api_settings, _client, _base = workflow
    invocation_id, _ = submit(factory, scope, principal, settings)
    claimed = claim_provider_job(factory, settings)
    assert claimed
    expire_claim(factory, invocation_id)
    with factory.begin() as session:
        row = session.get(m.ModelInvocation, invocation_id)
        job = session.get(m.Job, row.job_id)
        job.lease_expires_at = database_now(session) - timedelta(seconds=1)
        job.max_attempts = 100
    with factory() as session:
        assert claim_next(session, "ordinary-reclaimer", 5) is None
    assert recover_provider_jobs(factory) == 1


def test_cancellation_failure_rolls_back_invocation_job_and_audit(workflow):
    factory, scope, principal, settings, _api_settings, client, base = workflow
    invocation_id, _ = submit(factory, scope, principal, settings)

    @event.listens_for(Session, "before_commit")
    def reject_cancel(session):
        if any(
            isinstance(row, m.AuditEvent) and row.action == "provider.cancelled"
            for row in session.new
        ):
            raise OperationalError(
                "cancel commit", {}, Exception("private database text")
            )

    try:
        with pytest.raises(OperationalError):
            client.post(base + "/invocations/" + invocation_id + "/cancel")
    finally:
        event.remove(Session, "before_commit", reject_cancel)
    result = read(factory, settings, invocation_id)
    assert (
        result["invocation_state"] == "queued" and result["cancel_requested_at"] is None
    )


def test_role_revocation_between_retry_attempts_prevents_more_transmission(workflow):
    factory, scope, principal, settings, _api_settings, _client, _base = workflow
    settings.provider_max_attempts = "2"
    invocation_id, _ = submit(factory, scope, principal, settings)
    calls = []

    def handler(request):
        calls.append(request)
        with factory.begin() as session:
            session.scalar(select(m.ProjectMembership)).role = m.ProjectRole.viewer
        return httpx.Response(503)

    assert run_provider_once(
        factory, settings, provider_factory=fixture_provider(handler)
    )
    result = read(factory, settings, invocation_id)
    assert len(calls) == 1 and len(result["attempts"]) == 1
    assert (
        not result["proposal"] and result["reason"] == "requester_authorization_revoked"
    )


def test_late_completion_rejects_another_owner_and_cannot_refund_reservation(workflow):
    factory, scope, principal, settings, _api_settings, _client, _base = workflow
    invocation_id, _ = submit(factory, scope, principal, settings)
    claimed = claim_provider_job(factory, settings)
    assert claimed
    config, snapshot = claimed[4:]
    from failurelens.providers import ProviderBoundaryError, prepare_request

    reserved = prepare_request(
        config, snapshot.category, snapshot.evidence
    ).reserved_tokens
    owner = ApplicationAttemptBudget(
        factory,
        invocation_id,
        scope["project_id"],
        scope["run_id"],
        claimed[3],
        config,
        settings=settings,
    )
    assert owner.reserve(config, reserved) == 1
    wrong = ApplicationAttemptBudget(
        factory,
        invocation_id,
        scope["project_id"],
        scope["run_id"],
        m.new_id(),
        config,
        settings=settings,
    )
    with pytest.raises(ProviderBoundaryError, match="attempt_already_completed"):
        wrong.complete(
            1,
            ProviderResult("fallback", "product_defect"),
            sent=False,
            http_status=None,
        )
    expire_claim(factory, invocation_id)
    recover_provider_jobs(factory)
    owner.complete(
        1,
        ProviderResult(
            "fallback",
            "product_defect",
            usage={"prompt_tokens": 1, "completion_tokens": 1},
        ),
        sent=True,
        http_status=200,
    )
    result = read(factory, settings, invocation_id)
    assert result["budget"]["reserved_tokens"] == reserved
    assert result["invocation_state"] == "uncertain" and not result["proposal"]


def test_full_request_is_atomic_when_audit_persistence_fails(workflow):
    factory, _scope, _principal, settings, _api_settings, client, base = workflow
    heartbeat_provider_worker(factory, settings)
    preview = client.get(base + "/preview").json()
    body = {
        key: preview[key]
        for key in ("analysis_revision", "preview_digest", "configuration_digest")
    }
    body["idempotency_key"] = "fail-before-submit-commit"

    @event.listens_for(Session, "before_commit")
    def reject_submit(session):
        if any(
            isinstance(row, m.AuditEvent) and row.action == "provider.submitted"
            for row in session.new
        ):
            raise OperationalError(
                "submit commit", {}, Exception("private database text")
            )

    try:
        with pytest.raises(OperationalError):
            client.post(base + "/invocations", json=body)
    finally:
        event.remove(Session, "before_commit", reject_submit)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.ModelInvocation)) == 0
        assert session.scalar(select(func.count()).select_from(m.ModelRunBudget)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(m.Job)
                .where(m.Job.kind.like("model_provider%"))
            )
            == 0
        )


def test_deadline_keeps_permit_until_real_transport_exit_then_reconciles_numbers(
    workflow,
):
    import time

    factory, scope, principal, settings, _api_settings, _client, _base = workflow
    settings.provider_timeout_seconds = "0.08"
    settings.provider_concurrency = "1"
    invocation_id, _ = submit(factory, scope, principal, settings)
    release = threading.Event()

    def handler(request):
        assert release.wait(5)
        return good_response(request)

    try:
        assert run_provider_once(
            factory, settings, provider_factory=fixture_provider(handler)
        )
        result = read(factory, settings, invocation_id)
        assert result["invocation_state"] == "uncertain" and result["recovery_required"]
        assert result["attempts"][0]["spend_status"] == "unknown"
        with factory() as session:
            assert (
                session.get(
                    m.ModelProviderAdmission, _digest(settings.provider_id)
                ).active_permits
                == 1
            )
        release.set()
        deadline = time.monotonic() + 3
        while result["recovery_required"] and time.monotonic() < deadline:
            threading.Event().wait(0.01)
            result = read(factory, settings, invocation_id)
        assert not result["recovery_required"]
        assert result["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}
        assert result["invocation_state"] == "uncertain" and result["proposal"] is None
        assert result["budget"]["requests"] == 1
    finally:
        release.set()


def test_preview_reports_persisted_tighter_budget_and_exhaustion(workflow):
    factory, scope, principal, settings, api_settings, client, base = workflow
    settings.provider_max_run_requests = api_settings.provider_max_run_requests = "1"
    invocation_id, _ = submit(factory, scope, principal, settings)
    assert run_provider_once(factory, settings, provider_factory=fixture_provider())
    settings.provider_max_run_requests = api_settings.provider_max_run_requests = "100"
    heartbeat_provider_worker(factory, settings)
    preview = client.get(base + "/preview").json()
    assert (
        preview["availability"] == "run_budget_exhausted" and not preview["can_submit"]
    )
    assert (
        preview["budget"]["requests"] == 1
        and preview["limits"]["max_run_requests"] == 1
    )
    assert read(factory, settings, invocation_id)["budget"]["max_requests"] == 1


def test_provider_application_migration_preserves_existing_ledger_rows(
    tmp_path, monkeypatch
):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from failurelens.config import get_settings
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.orm import sessionmaker
    from test_provider_ledger import invoke

    root = Path(__file__).resolve().parents[1]
    url = f"sqlite+pysqlite:///{tmp_path / 'provider-upgrade.db'}"
    monkeypatch.setenv("FAILURELENS_DATABASE_URL", url)
    monkeypatch.setenv("FAILURELENS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    get_settings.cache_clear()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    try:
        command.upgrade(config, "d3a5f7c9b120")
        engine = create_engine(url)
        with engine.begin() as connection:
            assert (
                "model_provider_admissions" not in inspect(connection).get_table_names()
            )
        command.upgrade(config, "head")
        factory = sessionmaker(engine, expire_on_commit=False)
        scope = seed_scope(factory)
        original = invoke(factory, scope)
        inspector = inspect(engine)
        for model in (m.ModelInvocation, m.ModelAttempt, m.ModelProviderAdmission):
            assert {
                column["name"] for column in inspector.get_columns(model.__tablename__)
            } == set(model.__table__.columns.keys())
        command.downgrade(config, "d3a5f7c9b120")
        assert "model_provider_admissions" not in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT count(*) FROM model_invocations")) == 1
            )
            assert (
                connection.scalar(text("SELECT prompt_tokens FROM model_attempts"))
                == 100
            )
        command.upgrade(config, "head")
        restored = invoke(
            factory,
            scope,
            handler=lambda _: pytest.fail("migration replayed transport"),
        )
        assert restored["proposal"] == original["proposal"]
        assert restored["usage"] == original["usage"]
        assert restored["budget"] == original["budget"]
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(m.Job)) == 0
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_direct_transport_digest_preserves_pre_proxy_library_identity():
    from dataclasses import fields, replace

    from failurelens.provider_service import _provider_digest
    from test_provider_ledger import CONFIG

    historical = _digest(
        {
            field.name: getattr(CONFIG, field.name)
            for field in fields(CONFIG)
            if field.name not in {"token", "enabled", "proxy"}
        }
    )
    assert _provider_digest(CONFIG) == historical
    assert (
        _provider_digest(replace(CONFIG, token="rotated-fixture-credential"))
        == historical
    )
    assert (
        _provider_digest(replace(CONFIG, proxy="http://provider-proxy:8080"))
        != historical
    )


def test_partial_attempt_costs_remain_dated_partial_estimates(workflow):
    factory, scope, principal, settings, api_settings, client, base = workflow
    for target in (settings, api_settings):
        target.provider_max_attempts = "2"
        target.provider_input_price_per_million = "2"
        target.provider_output_price_per_million = "4"
        target.provider_pricing_source = "Operator fixture price sheet"
        target.provider_pricing_date = "2026-09-30"
        target.provider_currency = "USD"
    invocation_id, _ = submit(factory, scope, principal, settings)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) == 1 else good_response(request)

    assert run_provider_once(
        factory, settings, provider_factory=fixture_provider(handler)
    )
    result = client.get(base + "/invocations/" + invocation_id).json()
    assert result["invocation_state"] == "proposed"
    assert result["estimated_cost"] is None and result["cost_status"] == "unknown"
    assert result["known_estimated_cost"] == pytest.approx(0.0004)
    assert not result["cost_complete"] and not result["usage_complete"]
    assert len(result["attempts"]) == 2
    assert all(
        attempt["pricing"]["date"] == "2026-09-30"
        and attempt["pricing"]["currency"] == "USD"
        for attempt in result["attempts"]
    )


@pytest.mark.parametrize("after_deadline", [False, True])
def test_unexpected_transport_exception_settles_only_after_termination(
    workflow, after_deadline, caplog
):
    import time

    factory, scope, principal, settings, _api_settings, _client, _base = workflow
    settings.provider_timeout_seconds = "0.08" if after_deadline else "2"
    invocation_id, _ = submit(factory, scope, principal, settings)
    release = threading.Event()

    def handler(_):
        if after_deadline:
            assert release.wait(5)
        raise AssertionError("private-unexpected-transport-canary")

    try:
        if after_deadline:
            assert run_provider_once(
                factory, settings, provider_factory=fixture_provider(handler)
            )
            result = read(factory, settings, invocation_id)
            assert (
                result["recovery_required"]
                and not result["attempts"][0]["transport_terminated"]
            )
        else:
            with pytest.raises(
                AssertionError, match="private-unexpected-transport-canary"
            ):
                run_provider_once(
                    factory, settings, provider_factory=fixture_provider(handler)
                )
        release.set()
        deadline = time.monotonic() + 3
        result = read(factory, settings, invocation_id)
        while (
            not result["attempts"][0]["transport_terminated"]
            and time.monotonic() < deadline
        ):
            threading.Event().wait(0.01)
            result = read(factory, settings, invocation_id)
        assert result["attempts"][0]["transport_terminated"]
        assert result["attempts"][0]["spend_status"] == "unknown"
        assert (
            result["budget"]["requests"] == 1
            and result["budget"]["reserved_tokens"] > 0
        )
        assert result["proposal"] is None and result["usage"] is None
        with factory() as session:
            assert (
                session.get(
                    m.ModelProviderAdmission, _digest(settings.provider_id)
                ).active_permits
                == 0
            )
        assert "private-unexpected-transport-canary" not in caplog.text + str(result)
    finally:
        release.set()


def test_raising_cancellation_observer_during_transport_keeps_late_settlement(
    workflow, monkeypatch, caplog
):
    import time

    from failurelens import provider_jobs

    factory, scope, principal, settings, _api_settings, _client, _base = workflow
    invocation_id, _ = submit(factory, scope, principal, settings)
    entered, release = threading.Event(), threading.Event()
    original = provider_jobs._PersistedCancellation.is_set

    def broken_observer(cancellation):
        if entered.is_set() and not release.is_set():
            raise RuntimeError("private-cancellation-observer-canary")
        return original(cancellation)

    monkeypatch.setattr(provider_jobs._PersistedCancellation, "is_set", broken_observer)

    def handler(request):
        entered.set()
        assert release.wait(5)
        return good_response(request)

    try:
        with pytest.raises(RuntimeError, match="private-cancellation-observer-canary"):
            run_provider_once(
                factory, settings, provider_factory=fixture_provider(handler)
            )
        result = read(factory, settings, invocation_id)
        assert (
            result["recovery_required"]
            and not result["attempts"][0]["transport_terminated"]
        )
        with factory() as session:
            assert (
                provider_status(session, settings, principal, scope["project_id"])[
                    "availability"
                ]
                == "recovery_required"
            )
            assert (
                session.get(
                    m.ModelProviderAdmission, _digest(settings.provider_id)
                ).active_permits
                == 1
            )
        release.set()
        deadline = time.monotonic() + 3
        while result["recovery_required"] and time.monotonic() < deadline:
            threading.Event().wait(0.01)
            result = read(factory, settings, invocation_id)
        assert (
            result["attempts"][0]["transport_terminated"]
            and not result["recovery_required"]
        )
        assert result["proposal"] is None and result["budget"]["requests"] == 1
        with factory() as session:
            assert (
                session.get(
                    m.ModelProviderAdmission, _digest(settings.provider_id)
                ).active_permits
                == 0
            )
        assert "private-cancellation-observer-canary" not in caplog.text + str(result)
    finally:
        release.set()


def test_raising_cancellation_wait_after_attempt_retains_spend_without_permit_leak(
    workflow, monkeypatch, caplog
):
    from failurelens import provider_jobs

    factory, scope, principal, settings, _api_settings, _client, _base = workflow
    settings.provider_max_attempts = "2"
    invocation_id, _ = submit(factory, scope, principal, settings)
    original = provider_jobs._PersistedCancellation.wait
    completed = threading.Event()

    def broken_wait(cancellation, timeout):
        if completed.is_set():
            raise RuntimeError("private-wait-observer-canary")
        return original(cancellation, timeout)

    def handler(_):
        completed.set()
        return httpx.Response(503)

    monkeypatch.setattr(provider_jobs._PersistedCancellation, "wait", broken_wait)
    with pytest.raises(RuntimeError, match="private-wait-observer-canary"):
        run_provider_once(factory, settings, provider_factory=fixture_provider(handler))
    result = read(factory, settings, invocation_id)
    assert result["budget"]["requests"] == 1 and result["proposal"] is None
    assert result["attempts"][0]["transport_terminated"]
    assert result["attempts"][0]["spend_status"] == "unknown"
    with factory() as session:
        assert (
            session.get(
                m.ModelProviderAdmission, _digest(settings.provider_id)
            ).active_permits
            == 0
        )
    assert "private-wait-observer-canary" not in caplog.text + str(result)


def test_each_attempt_updates_circuit_once_and_late_proposals_cannot_reset_it(workflow):
    from failurelens.providers import prepare_request

    factory, scope, principal, settings, _api_settings, _client, _base = workflow
    settings.provider_failure_threshold = "2"
    invocation_id, _ = submit(factory, scope, principal, settings)
    claimed = claim_provider_job(factory, settings)
    assert claimed
    config, snapshot = claimed[4:]
    budget = ApplicationAttemptBudget(
        factory,
        invocation_id,
        scope["project_id"],
        scope["run_id"],
        claimed[3],
        config,
        settings=settings,
    )
    assert (
        budget.reserve(
            config,
            prepare_request(
                config, snapshot.category, snapshot.evidence
            ).reserved_tokens,
        )
        == 1
    )
    budget.complete(
        1,
        ProviderResult(
            "fallback", snapshot.category, reason="transport_deadline_exceeded"
        ),
        sent=True,
        http_status=None,
        transport_terminated=False,
    )
    with factory() as session:
        row = session.get(m.ModelProviderAdmission, _digest(settings.provider_id))
        assert row.failures == 1 and row.open_until is None and row.active_permits == 1
    expire_claim(factory, invocation_id)
    recover_provider_jobs(factory)
    budget.complete(
        1,
        ProviderResult(
            "proposed",
            snapshot.category,
            usage={"prompt_tokens": 2, "completion_tokens": 1},
        ),
        sent=True,
        http_status=200,
        transport_terminated=True,
    )
    with factory() as session:
        row = session.get(m.ModelProviderAdmission, _digest(settings.provider_id))
        assert row.failures == 1 and row.open_until is None and row.active_permits == 0
    assert read(factory, settings, invocation_id)["proposal"] is None


def test_late_failed_cleanup_does_not_count_an_attempt_twice(workflow):
    from failurelens.providers import prepare_request

    factory, scope, principal, settings, _api_settings, _client, _base = workflow
    invocation_id, _ = submit(factory, scope, principal, settings)
    claimed = claim_provider_job(factory, settings)
    assert claimed
    config, snapshot = claimed[4:]
    budget = ApplicationAttemptBudget(
        factory,
        invocation_id,
        scope["project_id"],
        scope["run_id"],
        claimed[3],
        config,
        settings=settings,
    )
    assert (
        budget.reserve(
            config,
            prepare_request(
                config, snapshot.category, snapshot.evidence
            ).reserved_tokens,
        )
        == 1
    )
    result = ProviderResult(
        "fallback",
        snapshot.category,
        reason="transport_deadline_exceeded",
        usage={"prompt_tokens": 30_000, "completion_tokens": 50},
    )
    budget.complete(1, result, sent=True, http_status=None, transport_terminated=False)
    budget.complete(1, result, sent=True, http_status=None, transport_terminated=True)
    with factory() as session:
        row = session.get(m.ModelProviderAdmission, _digest(settings.provider_id))
        assert row.failures == 1 and row.active_permits == 0
    assert read(factory, settings, invocation_id)["budget"]["reserved_tokens"] == 30_050


def test_cancel_after_reservation_before_send_is_not_a_provider_outage(
    workflow, monkeypatch
):
    from failurelens.provider_jobs import cancel_model_invocation

    factory, scope, principal, settings, _api_settings, _client, _base = workflow
    invocation_id, _ = submit(factory, scope, principal, settings)
    original = ApplicationAttemptBudget.reserve

    def reserve_then_cancel(budget, config, reserved_tokens):
        result = original(budget, config, reserved_tokens)
        with factory.begin() as session:
            cancel_model_invocation(
                session, settings, principal, **scope, invocation_id=invocation_id
            )
        return result

    monkeypatch.setattr(ApplicationAttemptBudget, "reserve", reserve_then_cancel)
    assert run_provider_once(
        factory,
        settings,
        provider_factory=fixture_provider(
            lambda _: pytest.fail("cancelled pre-send transport")
        ),
    )
    result = read(factory, settings, invocation_id)
    assert (
        result["invocation_state"] == "cancelled" and result["budget"]["requests"] == 1
    )
    assert result["attempts"][0]["spend_status"] == "not_sent"
    assert result["attempts"][0]["transport_terminated"]
    with factory() as session:
        row = session.get(m.ModelProviderAdmission, _digest(settings.provider_id))
        assert row.failures == 0 and row.active_permits == 0 and row.open_until is None


@pytest.mark.parametrize("gate", ["demo_mode", "insecure_cookie"])
def test_application_auth_gate_blocks_authenticated_admin_and_fixture_worker(
    workflow, gate
):
    factory, scope, principal, settings, api_settings, client, base = workflow
    invocation_id, request = submit(factory, scope, principal, settings)
    for target in (settings, api_settings):
        if gate == "demo_mode":
            target.demo_mode = True
        else:
            target.session_cookie_secure = False
    reason = "demo_mode_enabled" if gate == "demo_mode" else "insecure_authentication"
    preview = client.get(base + "/preview").json()
    assert preview["availability"] == "disabled" and preview["reason"] == reason
    assert not preview["can_submit"]
    denied = client.post(
        base + "/invocations",
        json=request.model_dump() | {"idempotency_key": "new-disabled-request"},
    )
    assert denied.status_code == 409 and denied.json()["detail"] == reason
    assert not heartbeat_provider_worker(factory, settings)
    assert not run_provider_once(
        factory,
        settings,
        provider_factory=lambda _: pytest.fail("auth gate bypassed by fixture factory"),
    )
    result = read(factory, settings, invocation_id)
    assert result["invocation_state"] == "fallback" and result["attempts"] == []
    assert result["reason"] == reason
