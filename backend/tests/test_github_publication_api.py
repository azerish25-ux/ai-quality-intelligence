"""Authorized bounded receipt reads have no publisher/network capability."""

from datetime import UTC, datetime, timedelta

import pytest
from failurelens import models as m
from failurelens.api import app
from failurelens.auth import Principal, current_principal
from failurelens.github_publication import GitHubPublisher
from sqlalchemy.orm import sessionmaker
from test_github_publication_service import A, seed


def history(session, *, count=1, slug="history-project"):
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    scope = seed(factory, slug=slug)
    target = m.GitHubPublicationTarget(
        project_id=scope["project_id"], repository="owner/repo", pull_number=7
    )
    session.add(target)
    session.flush()
    ids = []
    for index in range(count):
        row = m.GitHubPublication(
            target_id=target.id,
            project_id=scope["project_id"],
            run_id=scope["run_id"],
            publisher_id=m.new_id(),
            tested_head=A,
            report_digest="d" * 64,
            report_schema_version="github-report-v2",
            analysis_manifest_digest="a" * 64,
            analysis_count=0,
            analysis_revisions=[],
            omitted_analysis_revisions=0,
            bot_login="github-actions[bot]",
            status="failed",
            error_code="actor_not_verified",
            created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index),
            completed_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index),
        )
        session.add(row)
        session.flush()
        ids.append(row.id)
    session.commit()
    return scope, ids, target.id


def override_principal(principal):
    app.dependency_overrides[current_principal] = lambda: principal


def test_history_filters_in_sql_and_paginates_without_transport(
    client, session, monkeypatch
):
    scope, ids, _ = history(session, count=123)
    other, other_ids, _ = history(session, count=5, slug="other-history-project")
    monkeypatch.setattr(
        GitHubPublisher,
        "__init__",
        lambda *a, **k: pytest.fail("history instantiated publisher transport"),
    )
    url = f"/api/v1/projects/{scope['project_id']}/github-publications"
    first = client.get(url, params={"limit": 100, "run_id": scope["run_id"]})
    assert first.status_code == 200
    data = first.json()
    assert data["schema_version"] == "github-publications-v1"
    assert len(data["items"]) == 100 and data["has_more"] and data["next_offset"] == 100
    second = client.get(url, params={"limit": 100, "offset": 100}).json()
    assert (
        len(second["items"]) == 23
        and not second["has_more"]
        and second["next_offset"] is None
    )
    actual = [row["publication_id"] for row in data["items"] + second["items"]]
    assert actual == ids[::-1] and not set(actual) & set(other_ids)
    detail = client.get(url + "/" + ids[0])
    assert detail.status_code == 200 and detail.json()["run_id"] == scope["run_id"]
    assert detail.headers["cache-control"] == "no-store, private"
    assert client.get(url, params={"run_id": other["run_id"]}).status_code == 404
    assert client.get(url + "/" + other_ids[0]).status_code == 404
    assert client.post(url, json={}).status_code == 405
    assert client.post(url + "/" + ids[0] + "/reconcile", json={}).status_code == 404


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"offset": 1000001}]
)
def test_history_pagination_bounds(client, session, params):
    scope, _, _ = history(session)
    assert (
        client.get(
            f"/api/v1/projects/{scope['project_id']}/github-publications", params=params
        ).status_code
        == 422
    )


def test_history_viewer_access_and_outsider_not_found(client, session):
    scope, ids, _ = history(session)
    user = m.User(
        username="history-reader",
        display_name="History reader",
        password_hash="fixture-password-hash",
    )
    session.add(user)
    session.flush()
    session.add(
        m.ProjectMembership(
            project_id=scope["project_id"], user_id=user.id, role=m.ProjectRole.viewer
        )
    )
    session.commit()
    url = f"/api/v1/projects/{scope['project_id']}/github-publications"
    override_principal(
        Principal(
            kind="user",
            actor_id=user.id,
            user_id=user.id,
            display_name="History reader",
        )
    )
    assert client.get(url).status_code == 200
    assert client.get(url + "/" + ids[0]).status_code == 200
    override_principal(
        Principal(
            kind="user",
            actor_id="outsider",
            user_id="outsider",
            display_name="Outsider",
        )
    )
    assert client.get(url).status_code == 404
    assert client.get(url + "/" + ids[0]).status_code == 404
    override_principal(
        Principal(
            kind="ingestion_token",
            actor_id="fixture-token",
            project_id=scope["project_id"],
            display_name="Ingestion",
            scopes=("ingest",),
        )
    )
    assert client.get(url).status_code == 403


@pytest.mark.parametrize(
    "corruption",
    [
        "target_project",
        "run_project",
        "missing_active",
        "mismatched_active",
        "terminal_active",
    ],
)
def test_history_rechecks_scope_and_reservation_bindings(client, session, corruption):
    scope, ids, target_id = history(session)
    other, other_ids, _ = history(session, slug="other-history-project")
    target = session.get(m.GitHubPublicationTarget, target_id)
    row = session.get(m.GitHubPublication, ids[0])
    if corruption == "target_project":
        target.pull_number = 8
        target.project_id = other["project_id"]
    elif corruption == "run_project":
        row.run_id = other["run_id"]
    elif corruption == "missing_active":
        target.active_publication_id = "missing"
    elif corruption == "mismatched_active":
        target.active_publication_id = other_ids[0]
    else:
        target.active_publication_id = row.id
    session.commit()
    url = f"/api/v1/projects/{scope['project_id']}/github-publications"
    assert client.get(url).status_code == 409
    assert client.get(url + "/" + ids[0]).status_code == 409


def test_history_returns_revision_identity_and_withholds_malformed_text_fields(
    client, session
):
    scope, ids, _ = history(session)
    row = session.get(m.GitHubPublication, ids[0])
    reference = {"analysis_id": m.new_id(), "failure_id": m.new_id(), "revision": 3}
    row.analysis_count = 1
    row.analysis_revisions = [reference]
    session.commit()
    url = f"/api/v1/projects/{scope['project_id']}/github-publications/{ids[0]}"
    response = client.get(url)
    assert response.status_code == 200
    body = response.json()
    assert body["report_schema_version"] == "github-report-v2"
    assert body["analysis_manifest_digest"] == "a" * 64
    assert body["analysis_count"] == 1 and body["omitted_analysis_revisions"] == 0
    assert body["analysis_revisions"] == [reference]
    row.analysis_revisions = [{**reference, "summary": "ledger-private-text-canary"}]
    session.commit()
    rejected = client.get(url)
    assert rejected.status_code == 409
    assert "ledger-private-text-canary" not in rejected.text
