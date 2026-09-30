"""Provider approval and execution must retain the analysis's current support."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from failurelens import models as m
from failurelens.config import get_settings
from failurelens.jobs import process_next
from failurelens.provider_jobs import heartbeat_provider_worker, run_provider_once
from failurelens.provider_service import propose_for_analysis
from failurelens.providers import HTTPModelProvider, RunBudget
from failurelens.schemas import RunMetadata
from failurelens.service import create_project, enqueue_artifact_ingestion
from failurelens.storage import store_bytes
from sqlalchemy import inspect, select
from test_contract_evidence import bundle
from test_current_publication_validity import _known_flake
from test_diagnostic_contracts import diagnostic
from test_provider_ledger import good_response
from test_provider_workflow import fixture_provider

pytest_plugins = ("test_provider_workflow",)


def _columns(row):
    return deepcopy(
        {column.key: getattr(row, column.key) for column in inspect(type(row)).columns}
    )


def _recorded_decisions(factory, project_id):
    with factory() as session:
        analyses = list(
            session.scalars(
                select(m.Analysis)
                .join(m.Failure)
                .where(m.Failure.project_id == project_id)
            )
        )
        reviews = list(
            session.scalars(
                select(m.ReviewEvent)
                .join(m.Analysis)
                .join(m.Failure)
                .where(m.Failure.project_id == project_id)
            )
        )
        return {
            "analyses": {row.id: _columns(row) for row in analyses},
            "reviews": {row.id: _columns(row) for row in reviews},
        }


def _uncited_input_case(session):
    settings = get_settings()
    project = create_project(session, "provider-uncited", "Provider uncited input")
    content = bundle(diagnostic("runner_memory_limit"), extra=True)
    stored = store_bytes(
        content,
        root=settings.artifact_root,
        project_id=project.id,
        filename="observations.zip",
        media_type="application/zip",
        max_bytes=settings.max_file_bytes,
    )
    ingestion = enqueue_artifact_ingestion(
        session,
        project,
        RunMetadata(
            external_id="original-accepted-input",
            repository="owner/repo",
            commit_sha="a" * 40,
            expected_inputs=2,
        ),
        stored,
        source_format="failurelens-bundle-v2",
        settings=settings,
    )
    assert process_next(session, "provider-current-support", settings=settings)
    session.refresh(ingestion)
    assert ingestion.state is m.IngestionState.succeeded
    failure = session.scalar(
        select(m.Failure)
        .join(m.TestExecution)
        .where(
            m.Failure.run_id == ingestion.run_id,
            m.TestExecution.test_identity == "measurement::result",
        )
    )
    analysis = session.scalar(
        select(m.Analysis)
        .where(m.Analysis.failure_id == failure.id)
        .order_by(m.Analysis.revision.desc())
    )
    assert analysis.category is m.Category.infrastructure_failure
    cited = set(analysis.supporting_evidence_ids + analysis.contradictory_evidence_ids)
    uncited = set(analysis.validation_results["accepted_evidence_ids"]) - cited
    assert uncited
    lost = session.get(m.Evidence, min(uncited))
    assert lost.execution_id == failure.execution_id
    return project, failure.run, analysis, lost


def _historical_citation_case(session):
    project, run, analysis, priors = _known_flake(session, cite_prior=True)
    review = session.scalar(
        select(m.ReviewEvent)
        .join(m.Analysis)
        .join(m.Failure)
        .where(m.Failure.run_id == priors[0].id)
    )
    assert review.supporting_evidence_ids
    lost = session.get(m.Evidence, review.supporting_evidence_ids[0])
    assert lost.run_id != run.id
    assert analysis.category is m.Category.known_flake
    return project, run, analysis, lost


@pytest.fixture(params=["original_uncited_input", "historical_citation"])
def support_case(workflow, request):
    factory, _, principal, settings, api_settings, client, _ = workflow
    with factory() as session:
        seed = (
            _uncited_input_case
            if request.param == "original_uncited_input"
            else _historical_citation_case
        )
        project, run, analysis, lost = seed(session)
        session.add(
            m.ProjectMembership(
                project_id=project.id,
                user_id=principal.user_id,
                role=m.ProjectRole.administrator,
            )
        )
        session.commit()
        scope = {
            "project_id": project.id,
            "run_id": run.id,
            "analysis_id": analysis.id,
        }
        root = Path(get_settings().artifact_root)
        lost_path = root / lost.derivative.storage_path
        cited = set(
            analysis.supporting_evidence_ids + analysis.contradictory_evidence_ids
        )
        cited_paths = {
            root / session.get(m.Evidence, identifier).derivative.storage_path
            for identifier in cited
        }
        assert lost.id not in cited and lost_path not in cited_paths
        retained = {}
        derivatives = session.scalars(
            select(m.ArtifactDerivative).where(
                m.ArtifactDerivative.project_id == project.id
            )
        )
        for row in derivatives:
            path = root / row.storage_path
            if path.is_file():
                retained[path] = path.read_bytes()
        artifacts = session.scalars(
            select(m.Artifact).join(m.Run).where(m.Run.project_id == project.id)
        )
        for row in artifacts:
            path = root / row.safe_storage_path
            if path.is_file():
                retained[path] = path.read_bytes()
        assert lost_path in retained and cited_paths <= retained.keys()
        category = analysis.category.value
    for config in (settings, api_settings):
        config.provider_allowed_project_ids = scope["project_id"]
        config.provider_max_attempts = "2"
    assert heartbeat_provider_worker(factory, settings)
    base = (
        "/api/v1/projects/{project_id}/runs/{run_id}/analyses/{analysis_id}/provider"
    ).format(**scope)
    case = {
        "factory": factory,
        "settings": settings,
        "client": client,
        "base": base,
        "scope": scope,
        "category": category,
        "lost_path": lost_path,
        "lost": False,
    }
    recorded = _recorded_decisions(factory, scope["project_id"])
    yield case
    assert _recorded_decisions(factory, scope["project_id"]) == recorded
    for path, content in retained.items():
        if case["lost"] and path == lost_path:
            assert not path.exists()
        else:
            assert path.read_bytes() == content


def _approval(case):
    response = case["client"].get(case["base"] + "/preview")
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["availability"] == "ready" and preview["can_submit"]
    assert preview["evidence"]
    body = {
        key: preview[key]
        for key in ("analysis_revision", "preview_digest", "configuration_digest")
    }
    body["idempotency_key"] = "current-support"
    return preview, body


def _enqueue(case):
    preview, body = _approval(case)
    response = case["client"].post(case["base"] + "/invocations", json=body)
    assert response.status_code == 202, response.text
    result = response.json()
    assert result["invocation_state"] == "queued" and result["attempts"] == []
    return preview, body, result["invocation_id"]


def _lose_support(case):
    assert not case["lost"]
    case["lost_path"].unlink()
    case["lost"] = True


def _assert_analysis_withheld(case):
    response = case["client"].get("/api/v1/analyses/" + case["scope"]["analysis_id"])
    assert response.status_code == 200, response.text
    current = response.json()
    assert current["category"] == "insufficient_evidence"
    assert current["recorded_category"] == case["category"]
    assert current["claims"] == current["supporting_evidence_ids"] == []


def _result(case, invocation_id):
    response = case["client"].get(case["base"] + "/invocations/" + invocation_id)
    assert response.status_code == 200, response.text
    return response.json()


def test_current_support_loss_disables_provider_preview(support_case):
    case = support_case
    _approval(case)
    _lose_support(case)
    _assert_analysis_withheld(case)
    response = case["client"].get(case["base"] + "/preview")
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["availability"] == "evidence_unavailable"
    assert not preview["can_submit"]
    assert preview["preview_digest"] is None and preview["evidence"] == []


def test_current_support_loss_rejects_stale_provider_approval(support_case):
    case = support_case
    _, body = _approval(case)
    _lose_support(case)
    _assert_analysis_withheld(case)
    response = case["client"].post(case["base"] + "/invocations", json=body)
    assert response.status_code == 409, response.text
    with case["factory"]() as session:
        assert (
            session.scalar(
                select(m.ModelInvocation.id).where(
                    m.ModelInvocation.analysis_id == case["scope"]["analysis_id"]
                )
            )
            is None
        )


def test_queued_provider_rechecks_current_analysis_support(support_case):
    case = support_case
    _, _, invocation_id = _enqueue(case)
    _lose_support(case)
    _assert_analysis_withheld(case)
    calls = []

    def handler(request):
        calls.append(request)
        return good_response(request, category=case["category"])

    run_provider_once(
        case["factory"], case["settings"], provider_factory=fixture_provider(handler)
    )
    assert calls == []
    result = _result(case, invocation_id)
    assert result["status"] == "fallback" and result["proposal"] is None
    assert result["attempts"] == [] and result["budget"]["requests"] == 0


def test_retry_rechecks_support_without_replaying_or_refunding(support_case):
    case = support_case
    _, _, invocation_id = _enqueue(case)
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            _lose_support(case)
            return httpx.Response(503)
        return good_response(request, category=case["category"])

    assert run_provider_once(
        case["factory"], case["settings"], provider_factory=fixture_provider(handler)
    )
    assert len(calls) == 1
    _assert_analysis_withheld(case)
    result = _result(case, invocation_id)
    assert result["status"] == "fallback" and result["proposal"] is None
    assert len(result["attempts"]) == result["budget"]["requests"] == 1
    assert result["budget"]["reserved_tokens"] > 0
    assert result["attempts"][0]["http_status"] == 503


def test_support_lost_during_transport_withholds_proposal_but_retains_usage(
    support_case,
):
    case = support_case
    _, _, invocation_id = _enqueue(case)
    calls = []

    def handler(request):
        calls.append(request)
        _lose_support(case)
        return good_response(request, category=case["category"])

    assert run_provider_once(
        case["factory"], case["settings"], provider_factory=fixture_provider(handler)
    )
    assert len(calls) == 1
    _assert_analysis_withheld(case)
    result = _result(case, invocation_id)
    assert result["status"] == "fallback" and result["proposal"] is None
    assert result["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}
    assert len(result["attempts"]) == result["budget"]["requests"] == 1
    assert result["attempts"][0]["transport_terminated"]
    with case["factory"]() as session:
        assert session.get(m.ModelInvocation, invocation_id).proposal_json is None


def test_completed_provider_projection_rechecks_support_without_rewriting_receipt(
    support_case,
):
    case = support_case
    _, body, invocation_id = _enqueue(case)
    calls = []

    def handler(request):
        calls.append(request)
        return good_response(request, category=case["category"])

    assert run_provider_once(
        case["factory"], case["settings"], provider_factory=fixture_provider(handler)
    )
    before = _result(case, invocation_id)
    assert before["status"] == "proposed" and before["proposal"]
    with case["factory"]() as session:
        recorded = _columns(session.get(m.ModelInvocation, invocation_id))
        attempts = {
            row.id: _columns(row)
            for row in session.scalars(
                select(m.ModelAttempt).where(
                    m.ModelAttempt.invocation_id == invocation_id
                )
            )
        }
    _lose_support(case)
    _assert_analysis_withheld(case)
    after = _result(case, invocation_id)
    assert after["status"] == "fallback" and after["proposal"] is None
    assert after["invocation_state"] == "proposed"
    for key in ("usage", "attempts", "budget", "analysis_digest", "evidence_digest"):
        assert after[key] == before[key]
    listed = case["client"].get(case["base"] + "/invocations")
    assert listed.status_code == 200 and listed.json()["items"] == [after]
    replay = case["client"].post(case["base"] + "/invocations", json=body)
    assert replay.status_code == 202 and replay.json() == after
    assert len(calls) == 1
    with case["factory"]() as session:
        assert _columns(session.get(m.ModelInvocation, invocation_id)) == recorded
        assert {
            row.id: _columns(row)
            for row in session.scalars(
                select(m.ModelAttempt).where(
                    m.ModelAttempt.invocation_id == invocation_id
                )
            )
        } == attempts


def test_compatibility_provider_helper_rechecks_current_support(support_case):
    case = support_case
    config, state = case["settings"].provider_configuration()
    assert state == "ready" and config is not None
    calls = []

    def handler(request):
        calls.append(request)
        return good_response(request, category=case["category"])

    provider = HTTPModelProvider(config, transport=httpx.MockTransport(handler))
    budget = RunBudget()
    try:
        with case["factory"]() as session:
            analysis = session.get(m.Analysis, case["scope"]["analysis_id"])
            before = propose_for_analysis(session, analysis, provider, budget=budget)
        assert before["status"] == "proposed" and before["proposal"]
        spent = (budget.requests, budget.reserved_tokens)
        _lose_support(case)
        _assert_analysis_withheld(case)
        with case["factory"]() as session:
            analysis = session.get(m.Analysis, case["scope"]["analysis_id"])
            after = propose_for_analysis(session, analysis, provider, budget=budget)
        assert after["status"] == "fallback" and after["proposal"] is None
        assert len(calls) == 1
        assert (budget.requests, budget.reserved_tokens) == spent
    finally:
        provider.close()


def test_compatibility_helper_withholds_support_lost_during_transport(support_case):
    case = support_case
    config, state = case["settings"].provider_configuration()
    assert state == "ready" and config is not None
    calls = []

    def handler(request):
        calls.append(request)
        _lose_support(case)
        return good_response(request, category=case["category"])

    provider = HTTPModelProvider(config, transport=httpx.MockTransport(handler))
    budget = RunBudget()
    try:
        with case["factory"]() as session:
            analysis = session.get(m.Analysis, case["scope"]["analysis_id"])
            result = propose_for_analysis(session, analysis, provider, budget=budget)
        assert len(calls) == budget.requests == 1
        assert budget.reserved_tokens > 0
        _assert_analysis_withheld(case)
        assert result["status"] == "fallback" and result["proposal"] is None
        assert result["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}
    finally:
        provider.close()


def test_compatibility_retry_rechecks_support_without_refunding(support_case):
    case = support_case
    config, state = case["settings"].provider_configuration()
    assert state == "ready" and config is not None
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            _lose_support(case)
            return httpx.Response(503)
        return good_response(request, category=case["category"])

    provider = HTTPModelProvider(config, transport=httpx.MockTransport(handler))
    budget = RunBudget()
    try:
        with case["factory"]() as session:
            analysis = session.get(m.Analysis, case["scope"]["analysis_id"])
            result = propose_for_analysis(session, analysis, provider, budget=budget)
        assert len(calls) == budget.requests == 1
        assert budget.reserved_tokens > 0
        _assert_analysis_withheld(case)
        assert result["status"] == "fallback" and result["proposal"] is None
    finally:
        provider.close()


@pytest.mark.parametrize("support_case", ["original_uncited_input"], indirect=True)
def test_compatibility_helper_refreshes_run_expired_by_another_session(support_case):
    case = support_case
    config, state = case["settings"].provider_configuration()
    assert state == "ready" and config is not None
    calls = []

    def handler(request):
        calls.append(request)
        with case["factory"].begin() as other:
            other.get(m.Run, case["scope"]["run_id"]).evidence_expired_at = m.utcnow()
        return good_response(request, category=case["category"])

    provider = HTTPModelProvider(config, transport=httpx.MockTransport(handler))
    budget = RunBudget()
    try:
        with case["factory"]() as session:
            analysis = session.get(m.Analysis, case["scope"]["analysis_id"])
            assert analysis.failure.run.evidence_expired_at is None
            result = propose_for_analysis(session, analysis, provider, budget=budget)
        assert len(calls) == budget.requests == 1
        assert result["status"] == "fallback" and result["proposal"] is None
        assert result["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}
        with case["factory"]() as session:
            assert (
                session.get(m.Run, case["scope"]["run_id"]).evidence_expired_at
                is not None
            )
    finally:
        provider.close()


@pytest.mark.parametrize("support_case", ["original_uncited_input"], indirect=True)
def test_compatibility_helper_preserves_uncommitted_caller_work(support_case):
    case = support_case
    config, state = case["settings"].provider_configuration()
    assert state == "ready" and config is not None
    slug = "caller-owned-uncommitted-work"
    calls = []

    def handler(request):
        calls.append(request)
        with case["factory"]() as observer:
            assert (
                observer.scalar(select(m.Project.id).where(m.Project.slug == slug))
                is None
            )
        return good_response(request, category=case["category"])

    provider = HTTPModelProvider(config, transport=httpx.MockTransport(handler))
    try:
        with case["factory"]() as session:
            analysis = session.get(m.Analysis, case["scope"]["analysis_id"])
            pending = m.Project(slug=slug, name="Caller-owned transaction")
            session.add(pending)
            result = propose_for_analysis(
                session, analysis, provider, budget=RunBudget()
            )
            assert result["status"] == "proposed" and result["proposal"]
            assert pending in session and pending.name == "Caller-owned transaction"
            assert (
                session.scalar(select(m.Project).where(m.Project.slug == slug))
                is pending
            )
            assert session.in_transaction()
            with case["factory"]() as observer:
                assert (
                    observer.scalar(select(m.Project.id).where(m.Project.slug == slug))
                    is None
                )
            session.rollback()
        assert len(calls) == 1
        with case["factory"]() as observer:
            assert (
                observer.scalar(select(m.Project.id).where(m.Project.slug == slug))
                is None
            )
    finally:
        provider.close()


@pytest.mark.parametrize("support_case", ["original_uncited_input"], indirect=True)
def test_compatibility_helper_rejects_disabled_autoflush_without_losing_work(
    support_case,
):
    case = support_case
    config, state = case["settings"].provider_configuration()
    assert state == "ready" and config is not None
    slug = "caller-owned-no-autoflush"
    calls = []

    def handler(request):
        calls.append(request)
        return good_response(request, category=case["category"])

    provider = HTTPModelProvider(config, transport=httpx.MockTransport(handler))
    try:
        with case["factory"]() as session:
            analysis = session.get(m.Analysis, case["scope"]["analysis_id"])
            original_summary = analysis.summary
            analysis.summary = "Caller-owned pending summary"
            pending = m.Project(slug=slug, name="Caller-owned pending project")
            session.add(pending)
            with session.no_autoflush:
                result = propose_for_analysis(
                    session, analysis, provider, budget=RunBudget()
                )
                assert result["status"] == "fallback" and result["proposal"] is None
                assert result["reason"] == "unsupported_session_configuration"
                assert calls == []
                assert analysis.summary == "Caller-owned pending summary"
                assert analysis in session.dirty and pending in session.new
            session.rollback()
        with case["factory"]() as observer:
            assert (
                observer.get(m.Analysis, case["scope"]["analysis_id"]).summary
                == original_summary
            )
            assert (
                observer.scalar(select(m.Project.id).where(m.Project.slug == slug))
                is None
            )
    finally:
        provider.close()
