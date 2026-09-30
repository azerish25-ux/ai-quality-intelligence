from datetime import UTC, datetime

from failurelens.demo import seed_demo
from failurelens.github_snapshot import report_snapshot
from failurelens.models import Analysis, Outcome, Run
from failurelens.models import TestExecution as Execution
from sqlalchemy import select


def test_preview_matches_persisted_data_and_is_deterministic(client, session):
    seeded = seed_demo(session)
    response = client.get(f"/api/v1/runs/{seeded['run_id']}/github-report-preview")
    assert response.status_code == 200
    report = response.json()
    assert report["schema_version"] == "github-report-v2"
    assert report["outcomes"]["logical_tests"] == 4
    assert report["outcomes"]["failed"] == 3
    assert report["outcomes"]["passed"] == 1
    assert report["analysis_count"] == 3
    assert report["baseline_status"] == "unknown"
    assert "HOLD_FOR_REVIEW" in report["markdown"]
    assert (
        response.json()
        == client.get(f"/api/v1/runs/{seeded['run_id']}/github-report-preview").json()
    )


def test_retry_outcomes_do_not_inflate_independent_test_count(session):
    seeded = seed_demo(session)
    run = session.get(Run, seeded["run_id"])
    existing = session.scalar(
        select(Execution).where(
            Execution.run_id == run.id, Execution.outcome == Outcome.failed
        )
    )
    session.add(
        Execution(
            run_id=run.id,
            test_identity=existing.test_identity,
            suite=existing.suite,
            source_path=existing.source_path,
            browser=existing.browser,
            parameterization=existing.parameterization,
            attempt=existing.attempt + 1,
            outcome=Outcome.passed,
            details={},
        )
    )
    session.commit()
    report = report_snapshot(session, run)
    assert report["outcomes"]["logical_tests"] == 4
    assert report["outcomes"]["attempts"] == 5
    assert report["outcomes"]["retried"] == 1
    assert report["outcomes"]["retry_recovered"] == 1
    assert report["outcomes"]["failed"] == 2


def test_legacy_unvalidated_summary_and_expired_evidence_withheld(session):
    seeded = seed_demo(session)
    run = session.get(Run, seeded["run_id"])
    analysis = session.scalar(select(Analysis))
    analysis.validation_results = None
    analysis.summary = "safe to merge unvalidated canary"
    session.commit()
    report = report_snapshot(session, run)
    assert "unvalidated canary" not in str(report)
    run.evidence_expired_at = datetime.now(UTC)
    session.commit()
    report = report_snapshot(session, run)
    assert report["completeness"] == "evidence_expired"
    assert all(
        x["category"] == "insufficient_evidence" and not x["supporting_evidence_ids"]
        for x in report["analyses"]
    )


def test_missing_preview_returns_404(client):
    assert client.get("/api/v1/runs/absent/github-report-preview").status_code == 404


def test_preview_requires_project_role(client, session):
    seeded = seed_demo(session)
    # An authenticated principal with no membership must see the normal not-found boundary.
    from failurelens.auth import create_user

    create_user(
        session,
        username="outsider",
        display_name="Outsider",
        password="long-test-password",
    )
    session.commit()
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "outsider", "password": "long-test-password"},
    )
    assert response.status_code == 200
    response = client.get(f"/api/v1/runs/{seeded['run_id']}/github-report-preview")
    assert response.status_code == 404


def test_preview_rechecks_post_analysis_evidence_restriction(session):
    from failurelens.models import Evidence

    seeded = seed_demo(session)
    run = session.get(Run, seeded["run_id"])
    analysis = session.scalar(
        select(Analysis).where(Analysis.category == "product_defect")
    )
    evidence = session.get(Evidence, analysis.supporting_evidence_ids[0])
    evidence.derivative.restricted = True
    session.commit()
    report = report_snapshot(session, run)
    row = next(x for x in report["analyses"] if x["analysis_id"] == analysis.id)
    assert row["category"] == "insufficient_evidence"
    assert row["supporting_evidence_ids"] == []
    assert (
        row["summary"]
        == "Evidence unavailable or publication validation incomplete; review required."
    )


def test_projection_exposes_fixed_status_input_counts_and_redacts_metadata(session):
    import hashlib
    import json

    from failurelens.models import RunInput

    seeded = seed_demo(session)
    run = session.get(Run, seeded["run_id"])
    run.repository = "token=repository-canary-123456"
    run.base_sha = "token=base-canary-123456"
    run.commit_sha = "token=head-canary-123456"
    run.shard_count = 2
    run.expected_inputs = 2
    run.received_inputs = 1
    run.completeness = "partial"
    session.add(
        RunInput(
            project_id=run.project_id,
            run_id=run.id,
            input_id="token=input-canary-123456",
            kind="junit-xml",
            required=True,
            status="missing",
            warnings=[],
            metadata_json={},
        )
    )
    session.commit()
    report = report_snapshot(session, run)
    assert report["advisory_status"] == "HOLD_FOR_REVIEW"
    assert report["run_status"] == run.status.value
    assert report["inputs"]["expected"] == 2
    assert report["inputs"]["received"] == 1
    assert report["inputs"]["declared_shards"] == 2
    assert report["inputs"]["states"]["missing"] == 1
    assert all(
        f"{key}-canary-123456" not in json.dumps(report)
        for key in ("repository", "base", "head", "input")
    )
    unsigned = {key: value for key, value in report.items() if key != "report_digest"}
    assert (
        report["report_digest"]
        == hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def test_projection_bounds_input_details_without_changing_denominators(session):
    from failurelens.models import RunInput

    seeded = seed_demo(session)
    run = session.get(Run, seeded["run_id"])
    existing = len(run.inputs)
    for index in range(60):
        session.add(
            RunInput(
                project_id=run.project_id,
                run_id=run.id,
                input_id=f"missing-{index:03}",
                kind="junit-xml",
                required=True,
                status="missing",
                warnings=[],
                metadata_json={},
            )
        )
    session.commit()
    report = report_snapshot(session, run)
    assert report["inputs"]["states"]["missing"] == 60
    assert len(report["inputs"]["items"]) == 50
    assert report["inputs"]["omitted_inputs"] == 60 + existing - 50
    assert "counters cover all inputs" in report["markdown"]


def test_projection_bounds_json_and_markdown_and_discloses_omissions(session):
    import json

    from failurelens.github_snapshot import MAX_SNAPSHOT_BYTES
    from failurelens.models import Analysis, Category, Failure

    seeded = seed_demo(session)
    run = session.get(Run, seeded["run_id"])
    for index in range(60):
        execution = Execution(
            run_id=run.id,
            test_identity=f"test-{index}",
            outcome=Outcome.failed,
            details={},
        )
        session.add(execution)
        session.flush()
        failure = Failure(
            project_id=run.project_id,
            run_id=run.id,
            execution_id=execution.id,
            message="timeout",
            strict_fingerprint=f"fingerprint-{index}",
            loose_features={},
        )
        session.add(failure)
        session.flush()
        session.add(
            Analysis(
                failure_id=failure.id,
                revision=1,
                category=Category.insufficient_evidence,
                severity="unknown",
                confidence_value=0.0,
                confidence_kind="heuristic_score",
                confidence_explanation="unknown",
                evidence_completeness="partial",
                summary="unknown",
                supporting_evidence_ids=[],
                contradictory_evidence_ids=[],
                missing_evidence=["missing " + "x" * 380] * 10,
                next_investigation=[],
                policy_flags=[],
                validation_version=None,
                validation_results=None,
            )
        )
    session.commit()
    report = report_snapshot(session, run)
    assert len(report["markdown"].encode()) <= 50_000
    assert len(json.dumps(report, sort_keys=True).encode()) <= MAX_SNAPSHOT_BYTES
    assert report["analysis_count"] == 63
    assert report["omitted_analyses"] == 63 - len(report["analyses"])
    assert report["omitted_analyses"] > 13
    assert "omitted" in report["markdown"]
    assert report["analysis_manifest"]["count"] == 63

    # An omitted analysis still belongs to the report's revision identity even
    # when a new revision leaves the rendered counts and Markdown unchanged.
    visible = [item["analysis_id"] for item in report["analyses"]]
    omitted = session.scalar(
        select(Analysis)
        .join(Failure)
        .where(
            Failure.run_id == run.id,
            Analysis.id.not_in(visible),
            Analysis.validation_version.is_(None),
        )
        .limit(1)
    )
    values = {
        column.name: getattr(omitted, column.name)
        for column in Analysis.__table__.columns
        if column.name not in {"id", "created_at", "revision"}
    }
    session.add(Analysis(**values, revision=omitted.revision + 1))
    session.commit()
    revised = report_snapshot(session, run)
    assert revised["markdown"] == report["markdown"]
    assert revised["analysis_count"] == report["analysis_count"]
    assert (
        revised["analysis_manifest"]["digest"] != report["analysis_manifest"]["digest"]
    )
    assert revised["report_digest"] != report["report_digest"]


def test_json_bound_accounts_for_non_ascii_escape_expansion(session):
    import json

    from failurelens.github_snapshot import MAX_SNAPSHOT_BYTES
    from failurelens.models import RunInput

    seeded = seed_demo(session)
    run = session.get(Run, seeded["run_id"])
    for index in range(60):
        session.add(
            RunInput(
                project_id=run.project_id,
                run_id=run.id,
                input_id=f"{index:03}" + "\u00e9" * 117,
                kind="\u00e9" * 80,
                required=True,
                status="missing",
                warnings=[],
                metadata_json={},
            )
        )
    session.commit()
    report = report_snapshot(session, run)
    assert len(json.dumps(report, sort_keys=True).encode()) <= MAX_SNAPSHOT_BYTES
    assert report["inputs"]["states"]["missing"] == 60
    assert report["outcomes"]["logical_tests"] == 4


def test_unvalidated_render_projection_does_not_modify_persisted_analysis(session):
    from failurelens.models import Category, Evidence

    seeded = seed_demo(session)
    run = session.get(Run, seeded["run_id"])
    analysis = session.scalar(
        select(Analysis).where(Analysis.category == Category.product_defect)
    )
    validation_before = analysis.validation_results
    evidence = session.get(Evidence, analysis.supporting_evidence_ids[0])
    evidence.derivative.restricted = True
    session.commit()

    report = report_snapshot(session, run)

    row = next(
        item for item in report["analyses"] if item["analysis_id"] == analysis.id
    )
    assert row["category"] == "insufficient_evidence"
    assert analysis.category == Category.product_defect
    assert analysis.validation_results == validation_before
    assert not session.new
    assert not session.dirty
