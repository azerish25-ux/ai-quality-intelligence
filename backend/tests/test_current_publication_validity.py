"""Current publication checks over real ingestion and disposable retained bytes."""

import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from failurelens import evidence_validation, retention
from failurelens import models as m
from failurelens.auth import DEMO_PRINCIPAL
from failurelens.config import get_settings
from failurelens.github_evidence import evidence_for_report
from failurelens.github_snapshot import report_snapshot
from failurelens.history import history_context_for_failure
from failurelens.jobs import process_next
from failurelens.publication_validity import PublicationContext
from failurelens.schemas import (
    IngestionRequest,
    ReviewCreate,
)
from failurelens.schemas import (
    TestObservation as Observation,
)
from failurelens.service import (
    add_review,
    analyze_and_persist,
    create_project,
    ingest_normalized,
    select_failure_evidence,
)
from sqlalchemy import func, inspect, select


def _columns(row):
    return deepcopy(
        {
            column.key: getattr(row, column.key)
            for column in inspect(type(row)).column_attrs
        }
    )


def _case(session, *, slug="current-evidence", external="run"):
    project = create_project(session, slug, "Current evidence")
    run = ingest_normalized(
        session,
        project,
        IngestionRequest(
            external_id=external,
            repository="owner/repo",
            commit_sha="a" * 40,
            observations=[
                Observation(
                    test_identity="runner::crash",
                    outcome=m.Outcome.failed,
                    message="browser process crashed after runner exited",
                    details={"runner_diagnostic": True},
                )
            ],
        ),
    )
    failure = session.scalar(select(m.Failure).where(m.Failure.run_id == run.id))
    analysis = analyze_and_persist(session, failure)
    evidence = select_failure_evidence(session, failure)[0]
    assert analysis.category is m.Category.infrastructure_failure
    return run, analysis, evidence


@pytest.mark.parametrize("damage", ["missing", "digest", "restriction", "retention"])
@pytest.mark.parametrize("cite", [False, True])
def test_current_bytes_gate_fresh_api_projection_and_new_review(
    session_factory, request_client, damage, cite
):
    with session_factory() as session:
        run, analysis, evidence = _case(session)
        review = add_review(
            session,
            analysis,
            ReviewCreate(
                decision="accept",
                reason="Earlier evidence was inspected",
                expected_version=0,
            ),
        )
        aid, rid, eid, review_id = analysis.id, run.id, evidence.id, review.id
        stored, stored_review = _columns(analysis), _columns(review)
        path = Path(get_settings().artifact_root) / evidence.derivative.storage_path
    before = request_client.get(f"/api/v1/runs/{rid}/github-report-preview").json()
    if damage == "missing":
        path.unlink()
    elif damage == "digest":
        path.write_bytes(b"x" * path.stat().st_size)
    else:
        # A separate transaction changes the actual policy record; cached copies
        # from earlier HTTP requests must not remain authoritative.
        with session_factory.begin() as session:
            derivative = session.get(m.Evidence, eid).derivative
            if damage == "restriction":
                derivative.restricted = True
            else:
                derivative.retention_state = "expired"

    result = request_client.get(f"/api/v1/analyses/{aid}")
    assert result.status_code == 200
    projected = result.json()
    assert projected["category"] == "insufficient_evidence"
    assert projected["recorded_category"] == "infrastructure_failure"
    assert projected["claims"] == projected["supporting_evidence_ids"] == []
    assert projected["validation_results"]["status"] == "unavailable"
    assert "current_evidence_unavailable" in projected["policy_flags"]
    listed = request_client.get(f"/api/v1/runs/{rid}/failures").json()
    assert listed[0]["latest_analysis"] == projected
    assert (
        request_client.get(f"/api/v1/evidence/{eid}").status_code
        == {
            "missing": 409,
            "digest": 409,
            "restriction": 403,
            "retention": 410,
        }[damage]
    )
    current = request_client.get(f"/api/v1/runs/{rid}/github-report-preview").json()
    assert current["analyses"][0]["category"] == "insufficient_evidence"
    assert current["analyses"][0]["recorded_category"] == "infrastructure_failure"
    assert current["advisory_status"] == "HOLD_FOR_REVIEW"
    assert (
        request_client.get(
            f"/api/v1/runs/{rid}/github-evidence-export",
            params={"report_digest": before["report_digest"]},
        ).status_code
        == 409
    )
    rejected = request_client.post(
        f"/api/v1/analyses/{aid}/reviews",
        json={
            "decision": "accept",
            "reason": "Current evidence review",
            "expected_version": 1,
            "supporting_evidence_ids": [eid] if cite else [],
            "release_advice": "NO_BLOCKER_IDENTIFIED_IN_OBSERVED_SCOPE",
        },
    )
    assert rejected.status_code == 422
    with session_factory() as session:
        assert _columns(session.get(m.Analysis, aid)) == stored
        assert _columns(session.get(m.ReviewEvent, review_id)) == stored_review
        assert session.scalar(select(func.count(m.Analysis.id))) == 1
        assert session.scalar(select(func.count(m.ReviewEvent.id))) == 1


def _known_flake(session, *, cite_prior=False):
    project = create_project(session, "prior-retention", "Prior retention")
    base = m.utcnow() - timedelta(days=94)

    def ingest(index, outcomes):
        run = ingest_normalized(
            session,
            project,
            IngestionRequest(
                external_id=f"history-{index}",
                repository="owner/repo",
                commit_sha="a" * 40,
                branch="main",
                run_scope="full_suite",
                environment="ci-linux",
                worker_count=4,
                shard_count=2,
                timezone="UTC",
                observations=[
                    Observation(
                        test_identity="checkout::reviewed-timing",
                        suite="checkout",
                        source_path="tests/checkout.spec.ts",
                        parameterization="CAD",
                        browser="chromium",
                        attempt=attempt,
                        outcome=outcome,
                        message="reviewed harness timing instability"
                        if outcome is m.Outcome.failed
                        else None,
                        exception_type="HarnessTimeout"
                        if outcome is m.Outcome.failed
                        else None,
                        details={
                            "retry_recovered": outcome is m.Outcome.passed
                            and attempt > 0,
                            # Separate actual derivative bytes between runs;
                            # content-addressed storage otherwise shares the
                            # identical historical and current fixture file.
                            "measurement_sequence": index,
                        },
                    )
                    for attempt, outcome in enumerate(outcomes)
                ],
            ),
        )
        run.created_at = run.started_at = base + timedelta(days=index)
        session.commit()
        return run

    priors = [
        ingest(i, outcomes)
        for i, outcomes in enumerate(
            [
                [m.Outcome.failed, m.Outcome.passed],
                [m.Outcome.passed],
                [m.Outcome.failed],
                [m.Outcome.passed],
                [m.Outcome.failed, m.Outcome.passed],
            ]
        )
    ]
    prior_failure = session.scalar(
        select(m.Failure).where(m.Failure.run_id == priors[0].id)
    )
    prior_analysis = analyze_and_persist(session, prior_failure)
    event = add_review(
        session,
        prior_analysis,
        ReviewCreate(
            decision="category_correction",
            proposed_category="known_flake",
            reason="Independently reviewed synthetic fixture instability",
            expected_version=0,
            supporting_evidence_ids=prior_analysis.supporting_evidence_ids
            if cite_prior
            else [],
        ),
    )
    event.created_at = base + timedelta(hours=12)
    session.commit()
    current = ingest(6, [m.Outcome.failed])
    failure = session.scalar(select(m.Failure).where(m.Failure.run_id == current.id))
    analysis = analyze_and_persist(session, failure)
    assert analysis.category is m.Category.known_flake
    return project, current, analysis, priors


def _cleanup(session, project):
    job = retention.enqueue(
        session, project.id, retention.preview(session, project.id), DEMO_PRINCIPAL
    )
    for _ in range(20):
        process_next(session, "publication-retention-test", settings=get_settings())
        session.refresh(job)
        if job.state not in {m.JobState.queued, m.JobState.running}:
            break
    assert job.state is m.JobState.succeeded
    session.expire_all()


@pytest.mark.parametrize("cite", [False, True])
def test_prior_expiry_withholds_current_reassurance_without_rewriting_history(
    session_factory, request_client, cite
):
    with session_factory() as session:
        project, run, analysis, priors = _known_flake(session)
        review = add_review(
            session,
            analysis,
            ReviewCreate(
                decision="accept",
                reason="Earlier prior history was available",
                expected_version=0,
            ),
        )
        aid, rid, pid, review_id = analysis.id, run.id, project.id, review.id
        stored, stored_review = _columns(analysis), _columns(review)
        evidence_ids = list(analysis.supporting_evidence_ids)
    before = request_client.get(f"/api/v1/runs/{rid}/github-report-preview").json()
    assert before["advisory_status"] == "NO_BLOCKER_IDENTIFIED_IN_OBSERVED_SCOPE"
    assert (
        request_client.get(f"/api/v1/analyses/{aid}").json()["category"]
        == "known_flake"
    )
    with session_factory() as session:
        _cleanup(session, session.get(m.Project, pid))
        current = session.get(m.Analysis, aid)
        assert current.failure.run.evidence_expired_at is None
        assert all(
            session.get(m.Run, row.id).evidence_expired_at is not None for row in priors
        )
        assert not history_context_for_failure(session, current.failure)[
            "history_eligible_for_reassurance"
        ]
    projected = request_client.get(f"/api/v1/analyses/{aid}").json()
    assert projected["category"] == "insufficient_evidence"
    assert projected["recorded_category"] == "known_flake"
    assert "historical_support_unavailable" in projected["policy_flags"]
    current = request_client.get(f"/api/v1/runs/{rid}/github-report-preview").json()
    assert current["advisory_status"] == "HOLD_FOR_REVIEW"
    assert current["analyses"][0]["category"] == "insufficient_evidence"
    assert "historical_support_unavailable" in current["advisory_reasons"]
    assert (
        request_client.get(
            f"/api/v1/runs/{rid}/github-evidence-export",
            params={"report_digest": before["report_digest"]},
        ).status_code
        == 409
    )
    with (
        session_factory() as session,
        pytest.raises(ValueError, match="report evidence changed"),
    ):
        evidence_for_report(session, session.get(m.Run, rid), before)
    rejected = request_client.post(
        f"/api/v1/analyses/{aid}/reviews",
        json={
            "decision": "accept",
            "reason": "Current prior-history review",
            "expected_version": 1,
            "supporting_evidence_ids": evidence_ids if cite else [],
            "release_advice": "NO_BLOCKER_IDENTIFIED_IN_OBSERVED_SCOPE",
        },
    )
    assert rejected.status_code == 422
    with session_factory() as session:
        assert _columns(session.get(m.Analysis, aid)) == stored
        assert _columns(session.get(m.ReviewEvent, review_id)) == stored_review


def test_retention_between_publication_prepare_and_write_invalidates_digest(
    session_factory,
):
    from backend.tests.test_github_publication_service import GitHub, publish

    with session_factory() as session:
        project, run, _, _ = _known_flake(session)
        pid, rid = project.id, run.id
    server = GitHub()
    cleaned = False

    def handle(request):
        nonlocal cleaned
        if "/pulls/" in request.url.path and not cleaned:
            cleaned = True
            with session_factory() as session:
                _cleanup(session, session.get(m.Project, pid))
        return server.handle(request)

    result = publish(
        session_factory, {"project_id": pid, "run_id": rid}, server, handler=handle
    )
    assert result["status"] == "failed" and result["error_code"] == "report_changed"
    assert not server.writes


def test_preview_and_export_reuse_bytes_only_inside_the_request(
    session, request_client, monkeypatch
):
    run, analysis, evidence = _case(session)
    reader = Mock(wraps=evidence_validation.read_stored_bytes)
    monkeypatch.setattr(evidence_validation, "read_stored_bytes", reader)
    preview = request_client.get(f"/api/v1/runs/{run.id}/github-report-preview")
    assert preview.status_code == 200
    assert reader.call_count == 1
    exported = request_client.get(
        f"/api/v1/runs/{run.id}/github-evidence-export",
        params={"report_digest": preview.json()["report_digest"]},
    )
    assert exported.status_code == 200
    assert reader.call_count == 2
    (Path(get_settings().artifact_root) / evidence.derivative.storage_path).unlink()
    assert (
        request_client.get(f"/api/v1/analyses/{analysis.id}").json()["category"]
        == "insufficient_evidence"
    )
    assert reader.call_count == 3


def test_cached_bytes_never_authorize_a_different_scope_or_changed_policy(session):
    _run, analysis, evidence = _case(session)
    foreign_run, foreign_analysis, _ = _case(session, slug="other-project")
    context = PublicationContext(session)
    assert context.failure_evidence(analysis.failure, [evidence]).accepted_ids == (
        evidence.id,
    )
    assert not context.failure_evidence(
        foreign_analysis.failure, [evidence]
    ).accepted_ids
    assert not context.scoped_evidence(
        foreign_run, [evidence], execution=evidence.execution
    ).accepted_ids
    evidence.derivative.restricted = True
    assert not context.failure_evidence(analysis.failure, [evidence]).accepted_ids
    assert not context.analysis(analysis).valid


def test_human_cross_run_citations_are_available_in_their_own_scope(
    session_factory, request_client
):
    with session_factory() as session:
        _, analysis, _ = _case(session)
        _, _, other = _case(session, external="other-run")
        _, _, foreign = _case(session, slug="foreign-project")
        aid, other_id, foreign_id = analysis.id, other.id, foreign.id
        path = Path(get_settings().artifact_root) / other.derivative.storage_path
    body = {
        "decision": "needs_more_evidence",
        "reason": "Compare another run",
        "expected_version": 0,
    }
    assert (
        request_client.post(
            f"/api/v1/analyses/{aid}/reviews",
            json={
                **body,
                "supporting_evidence_ids": [foreign_id],
            },
        ).status_code
        == 422
    )
    assert (
        request_client.post(
            f"/api/v1/analyses/{aid}/reviews",
            json={
                **body,
                "supporting_evidence_ids": [other_id],
            },
        ).status_code
        == 201
    )
    path.unlink()
    assert (
        request_client.post(
            f"/api/v1/analyses/{aid}/reviews",
            json={
                **body,
                "expected_version": 1,
                "supporting_evidence_ids": [other_id],
            },
        ).status_code
        == 422
    )
    assert (
        request_client.post(
            f"/api/v1/analyses/{aid}/reviews",
            json={
                **body,
                "expected_version": 1,
            },
        ).status_code
        == 201
    )


def test_revalidation_keeps_original_cutoff_and_ignores_future_review(
    session_factory, request_client
):
    with session_factory() as session:
        _, run, analysis, priors = _known_flake(session)
        aid, rid = analysis.id, run.id
        before = report_snapshot(session, run)
        prior_failure = session.scalar(
            select(m.Failure).where(m.Failure.run_id == priors[0].id)
        )
        prior_analysis = session.scalar(
            select(m.Analysis).where(m.Analysis.failure_id == prior_failure.id)
        )
        later = add_review(
            session,
            prior_analysis,
            ReviewCreate(
                decision="reject",
                reason="A later review must not enter the earlier cutoff",
                expected_version=1,
            ),
        )
        assert later.created_at > run.created_at
    result = request_client.get(f"/api/v1/analyses/{aid}").json()
    assert result["category"] == "known_flake"
    assert (
        request_client.get(f"/api/v1/runs/{rid}/github-report-preview").json() == before
    )


def test_publication_context_cannot_cross_session_boundaries(session_factory):
    with session_factory() as first:
        run, analysis, _ = _case(first)
        context = PublicationContext(first)
        assert context.analysis(analysis).valid
        with session_factory() as second:
            other_run = second.get(m.Run, run.id)
            with pytest.raises(ValueError, match="another session"):
                report_snapshot(second, other_run, context=context)
            with pytest.raises(ValueError, match="another session"):
                context.analysis(second.get(m.Analysis, analysis.id))
        first.commit()
        with pytest.raises(ValueError, match="earlier transaction"):
            context.analysis(analysis)


@pytest.mark.parametrize("cite_prior", [False, True])
def test_prior_review_citations_are_rechecked_without_reinterpreting_uncited_judgment(
    session_factory, request_client, cite_prior
):
    with session_factory() as session:
        _, run, analysis, priors = _known_flake(session, cite_prior=cite_prior)
        aid, rid = analysis.id, run.id
        prior = session.scalar(
            select(m.Evidence).where(
                m.Evidence.run_id == priors[0].id,
                m.Evidence.execution.has(m.TestExecution.outcome == m.Outcome.failed),
            )
        )
        path = Path(get_settings().artifact_root) / prior.derivative.storage_path
        assert path not in {
            Path(get_settings().artifact_root) / row.derivative.storage_path
            for row in select_failure_evidence(session, analysis.failure)
        }
    before = request_client.get(f"/api/v1/runs/{rid}/github-report-preview").json()
    path.unlink()
    result = request_client.get(f"/api/v1/analyses/{aid}").json()
    assert result["category"] == (
        "insufficient_evidence" if cite_prior else "known_flake"
    )
    current = request_client.get(f"/api/v1/runs/{rid}/github-report-preview").json()
    if cite_prior:
        assert current["advisory_status"] == "HOLD_FOR_REVIEW"
        assert current["report_digest"] != before["report_digest"]
    else:
        assert current["advisory_status"] == "NO_BLOCKER_IDENTIFIED_IN_OBSERVED_SCOPE"


@pytest.mark.parametrize("target", ["original_uncited", "sibling_execution"])
def test_original_analysis_scope_protects_uncited_inputs_but_not_unrelated_executions(
    session, request_client, target
):
    from test_contract_evidence import bundle, ingest
    from test_diagnostic_contracts import diagnostic

    state = ingest(
        request_client, session, bundle(diagnostic("runner_memory_limit"), extra=True)
    )
    assert state["state"] == "succeeded"
    failure = session.scalar(
        select(m.Failure)
        .join(m.TestExecution)
        .where(
            m.Failure.run_id == state["run_id"],
            m.TestExecution.test_identity == "measurement::result",
        )
    )
    analysis = analyze_and_persist(session, failure)
    assert analysis.category is m.Category.infrastructure_failure
    evidence = list(
        session.scalars(select(m.Evidence).where(m.Evidence.run_id == failure.run_id))
    )
    original = set(analysis.validation_results["accepted_evidence_ids"])
    if target == "original_uncited":
        lost = next(
            row
            for row in evidence
            if row.id in original and row.id not in analysis.supporting_evidence_ids
        )
    else:
        lost = next(row for row in evidence if row.execution_id != failure.execution_id)
        assert lost.id not in original
    # Distinct diagnostic input remains properly bound and inspectable.
    cited = session.get(m.Evidence, analysis.supporting_evidence_ids[0])
    assert cited.run_input.input_id != failure.execution.details["input_id"]
    assert request_client.get(f"/api/v1/evidence/{cited.id}").status_code == 200
    before = request_client.get(f"/api/v1/analyses/{analysis.id}").json()
    assert before["category"] == "infrastructure_failure"
    (Path(get_settings().artifact_root) / lost.derivative.storage_path).unlink()
    after = request_client.get(f"/api/v1/analyses/{analysis.id}").json()
    assert after["category"] == (
        "insufficient_evidence"
        if target == "original_uncited"
        else "infrastructure_failure"
    )


def test_review_refreshes_policy_preloaded_before_another_transaction(session_factory):
    with session_factory() as first:
        _, analysis, evidence = _case(first)
        assert not evidence.derivative.restricted
        with session_factory.begin() as second:
            second.get(m.ArtifactDerivative, evidence.derivative_id).restricted = True
        with pytest.raises(ValueError, match="reassuring release advice"):
            add_review(
                first,
                analysis,
                ReviewCreate(
                    decision="accept",
                    reason="Recheck after concurrent revocation",
                    expected_version=0,
                    supporting_evidence_ids=[evidence.id],
                    release_advice="NO_BLOCKER_IDENTIFIED_IN_OBSERVED_SCOPE",
                ),
            )
        assert first.scalar(select(func.count(m.ReviewEvent.id))) == 0


@pytest.mark.parametrize("kind", ["trace", "metric"])
def test_real_supplemental_producers_remain_inspectable_without_classification_scope(
    session, request_client, kind
):
    if kind == "trace":
        from test_binary_evidence import ingest

        _, run_id, _, _ = ingest(request_client, session)
        provenance = "supplemental_trace"
    else:
        project = request_client.post(
            "/api/v1/projects",
            json={
                "slug": "metric-inspection",
                "name": "Metric inspection",
            },
        ).json()
        payload = {
            "metrics": {
                "http_req_duration": {
                    "type": "trend",
                    "contains": "time",
                    "values": {"avg": 100.0, "p(95)": 120.0, "count": 600},
                    "thresholds": {"p(95)<250": {"ok": True}},
                }
            }
        }
        accepted = request_client.post(
            f"/api/v1/projects/{project['id']}/ingestions",
            params={
                "external_id": "metric-case",
                "filename": "summary.json",
                "source_format": "k6-summary-json",
            },
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )
        assert accepted.status_code == 202
        assert process_next(session, "metric-inspection", settings=get_settings())
        state = request_client.get(f"/api/v1/ingestions/{accepted.json()['id']}").json()
        assert state["state"] == "succeeded"
        run_id = state["run_id"]
        provenance = "current_run_metric"
    evidence = session.scalar(
        select(m.Evidence)
        .where(
            m.Evidence.run_id == run_id,
            m.Evidence.provenance_kind == provenance,
        )
        .order_by(m.Evidence.id)
    )
    assert evidence is not None
    run = session.get(m.Run, run_id)
    response = request_client.get(f"/api/v1/evidence/{evidence.id}")
    assert response.status_code == 200, response.text
    assert response.json()["excerpt"] == evidence.excerpt
    assert response.json()["provenance_kind"] == provenance
    context = PublicationContext(session)
    assert context.inspectable_evidence(run, [evidence]).accepted_ids == (evidence.id,)
    assert not context.scoped_evidence(
        run,
        [evidence],
        execution=evidence.execution,
        run_input=evidence.run_input,
    ).accepted_ids
    if kind == "trace":
        failure = session.scalar(select(m.Failure).where(m.Failure.run_id == run_id))
        assert evidence.id not in {
            row.id for row in select_failure_evidence(session, failure)
        }
