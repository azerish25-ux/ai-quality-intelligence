from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from failurelens.auth import create_user
from failurelens.config import get_settings
from failurelens.evidence_validation import validate_scoped_evidence_records
from failurelens.github_evidence import (
    build_evidence_export,
    canonical_export_bytes,
    evidence_for_report,
    export_descriptor,
)
from failurelens.github_snapshot import report_snapshot
from failurelens.models import Analysis, Evidence, Failure, Outcome
from failurelens.schemas import IngestionRequest
from failurelens.schemas import TestObservation as Observation
from failurelens.service import analyze_and_persist, create_project, ingest_normalized
from sqlalchemy import select


def make_run(
    session, *, slug="export", external="head", outcome=Outcome.failed, message=None
):
    project = create_project(session, slug, slug.title())
    run = ingest_normalized(
        session,
        project,
        IngestionRequest(
            external_id=external,
            repository="owner/repository",
            commit_sha="a" * 40,
            observations=[
                Observation(
                    test_identity="observed::case",
                    outcome=outcome,
                    message=message
                    or "duplicate committed transfer left ledger unbalanced",
                    details={"data_integrity_violation": True},
                )
            ],
        ),
    )
    for failure in session.scalars(select(Failure).where(Failure.run_id == run.id)):
        analyze_and_persist(session, failure)
    session.commit()
    evidence = session.scalar(select(Evidence).where(Evidence.run_id == run.id))
    assert evidence is not None
    return run, evidence


def test_export_matches_report_and_retains_exact_inert_approved_bytes(session):
    run, evidence = make_run(
        session,
        message=(
            "duplicate committed transfer left ledger unbalanced; "
            "Authorization: Bearer synthetic-export-canary; <script>untrusted()</script>"
        ),
    )
    snapshot = report_snapshot(session, run)
    document = evidence_for_report(session, run, snapshot)
    assert document["items"]
    assert document["items"][0]["excerpt"] == evidence.excerpt
    assert (
        document["items"][0]["quotation_status"] == "exact_approved_derivative_excerpt"
    )
    assert document["distribution_status"] == "not_published"
    assert export_descriptor(document) == snapshot["evidence_export"]
    unsigned = {k: v for k, v in document.items() if k != "evidence_digest"}
    assert (
        sha256(canonical_export_bytes(unsigned)).hexdigest()
        == document["evidence_digest"]
    )
    encoded = canonical_export_bytes(document)
    assert b"synthetic-export-canary" not in encoded
    assert b"storage_path" not in encoded
    assert str(get_settings().artifact_root).encode() not in encoded
    assert evidence_for_report(session, run, snapshot) == document
    assert not session.new and not session.dirty


@pytest.mark.parametrize("outcome", [Outcome.passed, Outcome.skipped])
def test_real_nonfailure_execution_evidence_needs_no_fabricated_failure(
    session, outcome
):
    run, evidence = make_run(
        session, outcome=outcome, message="Observed fixture outcome"
    )
    assert evidence.execution.failure is None
    checks = validate_scoped_evidence_records(
        run, [evidence], execution=evidence.execution
    )
    assert checks.accepted_ids == (evidence.id,)
    document = build_evidence_export(
        session, run, analysis_ids=[], additional_evidence_ids=[evidence.id]
    )
    assert document["counts"]["exported"] == 1
    assert document["items"][0]["observation"]["outcome"] == outcome.value


@pytest.mark.parametrize(
    "damage",
    [
        "restriction",
        "expiry",
        "digest",
        "excerpt",
        "observation",
        "locator",
        "redaction",
    ],
)
def test_export_revalidates_each_publication_boundary(session, damage):
    run, evidence = make_run(session)
    snapshot = report_snapshot(session, run)
    assert snapshot["evidence_export"]["counts"]["exported"]
    if damage == "restriction":
        evidence.derivative.restricted = True
    elif damage == "expiry":
        run.evidence_expired_at = datetime.now(UTC)
    elif damage == "digest":
        (
            Path(get_settings().artifact_root) / evidence.derivative.storage_path
        ).write_bytes(b"tampered")
    elif damage == "excerpt":
        evidence.excerpt = "forged excerpt"
    elif damage == "observation":
        evidence.observation = {"outcome": "passed", "message": "forged observation"}
    elif damage == "locator":
        evidence.locator = {
            **evidence.locator,
            "derivative": {"kind": "json-pointer", "pointer": "/absent"},
        }
    else:
        evidence.derivative.metadata_json = {"redaction": {"scope": "wrong-project"}}
    with pytest.raises(ValueError, match="report evidence changed"):
        evidence_for_report(session, run, snapshot)
    current = report_snapshot(session, run)
    current_export = evidence_for_report(session, run, current)
    assert not current_export["items"]


def test_related_evidence_requires_explicit_prior_same_project_scope(session):
    prior, evidence = make_run(session, external="prior", outcome=Outcome.passed)
    primary, _ = make_run(session, external="primary")
    denied = build_evidence_export(
        session, primary, analysis_ids=[], additional_evidence_ids=[evidence.id]
    )
    assert denied["counts"]["rejected"] == 1
    allowed = build_evidence_export(
        session,
        primary,
        analysis_ids=[],
        additional_evidence_ids=[evidence.id],
        allowed_related_run_ids=[prior.id],
    )
    assert allowed["counts"]["exported"] == 1
    assert allowed["items"][0]["run_id"] == prior.id
    prior.created_at = primary.created_at + timedelta(seconds=1)
    future = build_evidence_export(
        session,
        primary,
        analysis_ids=[],
        additional_evidence_ids=[evidence.id],
        allowed_related_run_ids=[prior.id],
    )
    assert future["counts"]["rejected"] == 1
    foreign, other = make_run(session, slug="foreign", outcome=Outcome.passed)
    foreign.created_at = primary.created_at - timedelta(seconds=1)
    denied = build_evidence_export(
        session,
        primary,
        analysis_ids=[],
        additional_evidence_ids=[other.id],
        allowed_related_run_ids=[foreign.id],
    )
    assert denied["counts"]["rejected"] == 1
    assert other.excerpt not in str(denied["items"])


def test_scoped_validator_rejects_foreign_execution_and_input(session):
    run, evidence = make_run(session)
    _, foreign = make_run(session, slug="foreign", outcome=Outcome.passed)
    assert not validate_scoped_evidence_records(run, [evidence]).accepted_ids
    assert not validate_scoped_evidence_records(
        run, [evidence], execution=foreign.execution
    ).accepted_ids
    assert not validate_scoped_evidence_records(
        run, [evidence], execution=evidence.execution, run_input=foreign.run_input
    ).accepted_ids
    evidence.run_input = foreign.run_input
    session.flush()
    assert not validate_scoped_evidence_records(
        run, [evidence], execution=evidence.execution
    ).accepted_ids


def test_export_source_locator_comes_from_immutable_payload_not_mutable_row(session):
    run, evidence = make_run(session, outcome=Outcome.passed)
    original = dict(evidence.locator["source"])
    evidence.locator = {
        **evidence.locator,
        "source": {"kind": "json-pointer", "pointer": "/forged"},
    }
    document = build_evidence_export(
        session, run, analysis_ids=[], additional_evidence_ids=[evidence.id]
    )
    assert document["items"][0]["locator"]["source"]["pointer"] == original["pointer"]


def test_export_omits_whole_oversized_quotes_and_discloses_reference_limits(session):
    run, evidence = make_run(session, outcome=Outcome.passed, message="🌐" * 2000)
    document = build_evidence_export(
        session,
        run,
        analysis_ids=[],
        additional_evidence_ids=[evidence.id],
        max_bytes=4096,
        omitted_section_reference_hints=3,
        omitted_related_run_hints=2,
    )
    assert len(canonical_export_bytes(document)) <= 4096
    assert document["counts"]["requested"] == document["counts"]["omitted"] == 1
    assert document["counts"]["exported"] == 0
    assert document["counts"]["omitted_section_reference_hints"] == 3
    assert document["counts"]["omitted_related_run_hints"] == 2
    assert document["items"] == []


def test_export_withholds_unvalidated_analysis_and_unknown_references(session):
    run, _ = make_run(session)
    analysis = session.scalar(
        select(Analysis).join(Failure).where(Failure.run_id == run.id)
    )
    analysis.validation_results = None
    document = build_evidence_export(
        session,
        run,
        analysis_ids=[analysis.id],
        additional_evidence_ids=["missing", "../invalid"],
    )
    assert document["counts"]["unavailable_analyses"] == 1
    assert document["counts"]["unavailable"] == 1
    assert document["counts"]["invalid_reference_entries"] == 1
    assert not document["items"]


def test_evidence_download_requires_authorized_project(client, session):
    run, _ = make_run(session)
    response = client.get(f"/api/v1/runs/{run.id}/github-evidence-export")
    assert response.status_code == 200
    assert response.json()["project_id"] == run.project_id
    create_user(
        session,
        username="outside-export",
        display_name="Outside",
        password="long-test-password",
    )
    session.commit()
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "outside-export", "password": "long-test-password"},
        ).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/runs/{run.id}/github-evidence-export").status_code == 404
    )
    assert client.get("/api/v1/runs/absent/github-evidence-export").status_code == 404


def test_http_download_preserves_canonical_bytes_and_rejects_stale_report(
    client, session
):
    run, evidence = make_run(session)
    report_response = client.get(f"/api/v1/runs/{run.id}/github-report-preview")
    snapshot = report_response.json()
    assert report_response.content == canonical_export_bytes(snapshot)
    endpoint = f"/api/v1/runs/{run.id}/github-evidence-export"
    response = client.get(endpoint, params={"report_digest": snapshot["report_digest"]})
    assert response.status_code == 200
    assert response.content == canonical_export_bytes(response.json())
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="evidence.json"'
    )
    assert response.json()["evidence_digest"] == snapshot["evidence_export"]["digest"]
    evidence.derivative.restricted = True
    session.commit()
    assert (
        client.get(
            endpoint, params={"report_digest": snapshot["report_digest"]}
        ).status_code
        == 409
    )
    assert client.get(endpoint, params={"report_digest": "invalid"}).status_code == 422
