"""Publication receipts identify full report revisions without retaining prose."""

import copy
import hashlib
import json

import pytest
from failurelens import models as m
from failurelens.github_publication_schemas import (
    AnalysisRevisionReference,
    PublicationScopeError,
    publication_revision_identity,
)
from failurelens.github_snapshot import report_snapshot
from pydantic import ValidationError
from sqlalchemy import select
from test_github_publication_service import GitHub, publish, seed

pytest_plugins = ("test_github_publication_service",)


def revision_snapshot():
    refs = [{"analysis_id": m.new_id(), "failure_id": m.new_id(), "revision": 2}]
    digest = hashlib.sha256(
        json.dumps(
            {"schema_version": "report-analysis-revisions-v1", "items": refs},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return {
        "schema_version": "github-report-v2",
        "analysis_manifest": {
            "schema_version": "report-analysis-revisions-v1",
            "count": 1,
            "digest": digest,
        },
        "analysis_count": 1,
        "analyses": [
            {
                **refs[0],
                "summary": "private analysis prose",
                "supporting_evidence_ids": ["private evidence reference"],
            }
        ],
        "omitted_analyses": 0,
    }


@pytest.mark.parametrize(
    "revision", [True, False, 0, -1, "2", None, 1.5, [], {}, 2147483648]
)
def test_analysis_revision_requires_positive_integer(revision):
    snapshot = revision_snapshot()
    snapshot["analyses"][0]["revision"] = revision
    with pytest.raises(PublicationScopeError, match="revision identity"):
        publication_revision_identity(snapshot)


@pytest.mark.parametrize(
    "corruption",
    [
        "manifest_version",
        "report_version",
        "manifest_digest",
        "boolean_manifest_count",
        "boolean_count",
        "count_mismatch",
        "missing_count",
        "negative_omitted",
        "boolean_omitted",
        "omitted_mismatch",
        "malformed_analysis_id",
        "malformed_failure_id",
        "duplicate_analysis",
        "duplicate_failure",
        "too_many_refs",
        "invalid_details",
    ],
)
def test_revision_manifest_rejects_inconsistent_or_unbounded_shapes(corruption):
    snapshot = revision_snapshot()
    if corruption == "manifest_version":
        snapshot["analysis_manifest"]["schema_version"] = "unrecognized"
    elif corruption == "report_version":
        snapshot["schema_version"] = "unrecognized"
    elif corruption == "manifest_digest":
        snapshot["analysis_manifest"]["digest"] = "not-a-digest"
    elif corruption == "boolean_manifest_count":
        snapshot["analysis_manifest"]["count"] = True
    elif corruption == "boolean_count":
        snapshot["analysis_count"] = True
    elif corruption == "count_mismatch":
        snapshot["analysis_manifest"]["count"] = 2
    elif corruption == "missing_count":
        del snapshot["analysis_count"]
    elif corruption == "negative_omitted":
        snapshot["omitted_analyses"] = -1
    elif corruption == "boolean_omitted":
        snapshot["omitted_analyses"] = False
    elif corruption == "omitted_mismatch":
        snapshot["omitted_analyses"] = 1
    elif corruption == "malformed_analysis_id":
        snapshot["analyses"][0]["analysis_id"] = "text-instead-of-identifier"
    elif corruption == "malformed_failure_id":
        snapshot["analyses"][0]["failure_id"] = True
    elif corruption in {"duplicate_analysis", "duplicate_failure"}:
        duplicate = copy.deepcopy(snapshot["analyses"][0])
        if corruption == "duplicate_failure":
            duplicate["analysis_id"] = m.new_id()
        snapshot["analyses"].append(duplicate)
        snapshot["analysis_count"] = snapshot["analysis_manifest"]["count"] = 2
    elif corruption == "too_many_refs":
        snapshot["analyses"] = [
            {"analysis_id": m.new_id(), "failure_id": m.new_id(), "revision": 1}
            for _ in range(51)
        ]
        snapshot["analysis_count"] = snapshot["analysis_manifest"]["count"] = 51
    else:
        snapshot["analyses"] = [None]
    with pytest.raises(PublicationScopeError, match="revision identity"):
        publication_revision_identity(snapshot)


def test_revision_reference_model_rejects_text_or_evidence_fields():
    snapshot = revision_snapshot()
    with pytest.raises(ValidationError):
        AnalysisRevisionReference.model_validate(snapshot["analyses"][0])
    stored = publication_revision_identity(snapshot)
    assert stored["analysis_revisions"] == [
        {
            key: snapshot["analyses"][0][key]
            for key in ("analysis_id", "failure_id", "revision")
        }
    ]
    assert "private" not in json.dumps(stored)


def add_analyses(factory, scope, count):
    with factory.begin() as session:
        for index in range(count):
            execution = m.TestExecution(
                run_id=scope["run_id"],
                test_identity=f"revision-fixture-{index}",
                outcome=m.Outcome.failed,
            )
            session.add(execution)
            session.flush()
            failure = m.Failure(
                project_id=scope["project_id"],
                run_id=scope["run_id"],
                execution_id=execution.id,
                message="source-private-canary",
                strict_fingerprint="e" * 64,
            )
            session.add(failure)
            session.flush()
            session.add(
                m.Analysis(
                    failure_id=failure.id,
                    revision=1,
                    category=m.Category.insufficient_evidence,
                    confidence_explanation="explanation-private-canary",
                    evidence_completeness="partial",
                    summary="analysis-private-canary",
                )
            )


def test_durable_revision_round_trip_is_bounded_and_contains_no_analysis_text(
    publication_factory,
):
    factory, server = publication_factory, GitHub()
    scope = seed(factory)
    add_analyses(factory, scope, 52)
    with factory() as session:
        snapshot = report_snapshot(session, session.get(m.Run, scope["run_id"]))
    result = publish(factory, scope, server)
    assert result["status"] == "created"
    assert result["report_schema_version"] == snapshot["schema_version"]
    assert result["analysis_manifest_digest"] == snapshot["analysis_manifest"]["digest"]
    assert result["analysis_count"] == 52
    assert len(result["analysis_revisions"]) == len(snapshot["analyses"]) <= 50
    assert result["omitted_analysis_revisions"] == 52 - len(snapshot["analyses"])
    assert result["analysis_revisions"] == [
        {key: item[key] for key in ("analysis_id", "failure_id", "revision")}
        for item in snapshot["analyses"]
    ]
    with factory() as session:
        row = session.get(m.GitHubPublication, result["publication_id"])
        persisted = {
            column.name: getattr(row, column.name)
            for column in m.GitHubPublication.__table__.columns
        }
        assert row.analysis_manifest_digest == snapshot["analysis_manifest"]["digest"]
        assert row.analysis_revisions == result["analysis_revisions"]
    assert "private-canary" not in json.dumps(result)
    assert "private-canary" not in json.dumps(persisted, default=str)


def test_new_analysis_revision_does_not_rewrite_historical_receipt(publication_factory):
    factory, server = publication_factory, GitHub()
    scope = seed(factory)
    add_analyses(factory, scope, 1)
    first = publish(factory, scope, server)
    with factory.begin() as session:
        original = session.scalar(select(m.Analysis))
        revision = m.Analysis(
            failure_id=original.failure_id,
            revision=2,
            category=m.Category.insufficient_evidence,
            confidence_explanation="new explanation",
            evidence_completeness="partial",
            summary="new analysis",
        )
        session.add(revision)
        session.flush()
        next_id = revision.id
    second = publish(factory, scope, server)
    assert second["status"] == "updated"
    assert second["analysis_manifest_digest"] != first["analysis_manifest_digest"]
    assert second["analysis_revisions"][0]["analysis_id"] == next_id
    assert second["analysis_revisions"][0]["revision"] == 2
    with factory() as session:
        historical = session.get(m.GitHubPublication, first["publication_id"])
        assert historical.analysis_revisions == first["analysis_revisions"]
        assert historical.analysis_revisions[0]["revision"] == 1


def test_malformed_snapshot_revision_has_no_durable_intent_or_network(
    publication_factory, monkeypatch
):
    from failurelens import github_publication_service
    from failurelens.github_publication import PublicationError

    factory, server = publication_factory, GitHub()
    scope = seed(factory)
    add_analyses(factory, scope, 1)
    actual_snapshot = github_publication_service.report_snapshot

    def malformed_snapshot(session, run):
        snapshot = actual_snapshot(session, run)
        snapshot["analyses"][0]["revision"] = True
        return snapshot

    monkeypatch.setattr(
        github_publication_service, "report_snapshot", malformed_snapshot
    )
    with pytest.raises(PublicationError):
        publish(factory, scope, server)
    assert not server.requests
    with factory() as session:
        assert session.scalar(select(m.GitHubPublication.id)) is None
        assert session.scalar(select(m.GitHubPublicationTarget.id)) is None
