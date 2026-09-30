"""Missing evidence and stale-review boundaries use synthetic local fixtures."""

from __future__ import annotations

import pytest
from failurelens import binary_evidence as binary
from failurelens import models as m
from failurelens.auth import DEMO_PRINCIPAL
from failurelens.binary_schemas import BinaryDecisionCreate, ScreenshotReview
from failurelens.impact import apply_impact_override, get_impact_recommendation
from failurelens.schemas import ImpactOverrideCreate
from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from test_binary_evidence import ingest, review
from test_impact import (
    _create_mapping,
    _create_recommendation,
    _project,
    _run_with_changes,
)


@pytest.fixture
def approved_images(client, session):
    _, _, items, shots = ingest(client, session, trace=False)
    approved = {}
    for name, item in items.items():
        response = review(client, item, shots[name])
        assert response.status_code == 201, response.text
        approved[name] = response.json()
    return approved, shots


def _use_binary_evidence(session, approved, shots, operation):
    actual = approved["actual.png"]
    if operation == "read":
        state = binary.get_state(session, DEMO_PRINCIPAL, actual["input_id"])
        return binary.to_schema(session, state)
    if operation == "review":
        return binary.review_screenshot(
            session,
            DEMO_PRINCIPAL,
            actual["input_id"],
            ScreenshotReview(
                expected_version=actual["version"],
                reason="Rechecked source pixels for this input",
                confirm_safe=True,
            ),
            shots["actual.png"],
        )
    if operation == "decide":
        return binary.decide(
            session,
            DEMO_PRINCIPAL,
            actual["input_id"],
            BinaryDecisionCreate(
                expected_version=actual["version"],
                decision="revoke",
                reason="Revoke the exact reviewed input only",
            ),
        )
    assert operation == "compare"
    return binary.compare_images(
        session,
        DEMO_PRINCIPAL,
        approved["expected.png"]["derivative"]["id"],
        actual["derivative"]["id"],
    )


@pytest.mark.parametrize("operation", ["read", "review", "decide", "compare"])
def test_missing_binary_input_fails_closed(
    session, monkeypatch, approved_images, operation
):
    approved, shots = approved_images
    actual = approved["actual.png"]
    original_get = session.get

    def missing_input(entity, ident, *args, **kwargs):
        if entity is m.RunInput and ident == actual["input_id"]:
            return None
        return original_get(entity, ident, *args, **kwargs)

    monkeypatch.setattr(session, "get", missing_input)
    with pytest.raises(HTTPException) as error:
        _use_binary_evidence(session, approved, shots, operation)
    assert error.value.status_code == 404
    assert error.value.detail == "binary evidence not found"
    state = session.get(m.BinaryEvidence, actual["input_id"])
    assert state.version == actual["version"]
    assert session.get(m.ArtifactDerivative, actual["derivative"]["id"]).approved


@pytest.mark.parametrize("operation", ["read", "review", "decide", "compare"])
@pytest.mark.parametrize("dimension", ["project_id", "run_id"])
def test_binary_input_scope_is_revalidated(
    session, approved_images, operation, dimension
):
    approved, shots = approved_images
    actual = approved["actual.png"]
    other_project = m.Project(slug="unrelated-evidence", name="Unrelated evidence")
    session.add(other_project)
    session.flush()
    other_run = m.Run(
        project_id=other_project.id,
        external_id="unrelated-run",
        manifest_digest="0" * 64,
    )
    session.add(other_run)
    session.flush()
    item = session.get(m.RunInput, actual["input_id"])
    setattr(
        item, dimension, other_project.id if dimension == "project_id" else other_run.id
    )
    session.commit()

    with pytest.raises(HTTPException) as error:
        _use_binary_evidence(session, approved, shots, operation)
    assert error.value.status_code == 404
    assert error.value.detail == "binary evidence not found"
    state = session.get(m.BinaryEvidence, actual["input_id"])
    assert state.version == actual["version"]
    assert session.get(m.ArtifactDerivative, actual["derivative"]["id"]).approved


def test_review_handles_state_deleted_before_lock_refresh(client, session, monkeypatch):
    _, _, items, _ = ingest(client, session, trace=False)
    input_id = items["actual.png"]["input_id"]

    def delete_before_refresh(locked_session, project_id):
        assert project_id == items["actual.png"]["project_id"]
        locked_session.execute(
            delete(m.BinaryEvidence).where(m.BinaryEvidence.input_id == input_id)
        )

    monkeypatch.setattr(binary, "lock_project", delete_before_refresh)
    with pytest.raises(HTTPException) as error:
        binary.get_state(session, DEMO_PRINCIPAL, input_id, review=True)
    assert error.value.status_code == 404
    assert error.value.detail == "binary evidence not found"


@pytest.mark.parametrize(
    "key,value",
    [
        ("viewport_width", True),
        ("viewport_height", 24.0),
        ("viewport_width", 0),
        ("device_scale_factor", True),
        ("device_scale_factor", None),
        ("device_scale_factor", "1"),
        ("device_scale_factor", 0),
        ("device_scale_factor", 11),
    ],
)
def test_invalid_numeric_context_never_produces_similarity(
    session, approved_images, key, value
):
    approved, shots = approved_images
    for image in approved.values():
        item = session.get(m.RunInput, image["input_id"])
        item.metadata_json = {
            **item.metadata_json,
            "comparison_context": {
                **item.metadata_json["comparison_context"],
                key: value,
            },
        }
    session.commit()
    result = _use_binary_evidence(session, approved, shots, "compare")
    assert result.status == "INSUFFICIENT_CONTEXT"
    assert f"missing_{key}" in result.reasons
    assert result.similarity is None and result.hamming_distance is None


def test_override_rejects_revision_changed_after_object_was_loaded(client, session):
    project = _project(client)
    run, _ = _run_with_changes(
        session,
        project["id"],
        files=[{"status": "modified", "path": "src/checkout.py"}],
    )
    mapping = _create_mapping(client, project["id"])
    created = _create_recommendation(client, project["id"], run, mapping)
    recommendation = get_impact_recommendation(session, created["id"])
    assert recommendation is not None
    assert recommendation.current_revision == 0
    with Session(session.get_bind()) as competing_session:
        competing_session.execute(
            update(m.ImpactRecommendation)
            .where(m.ImpactRecommendation.id == recommendation.id)
            .values(current_revision=1)
        )
        competing_session.commit()
    assert recommendation.current_revision == 0

    with pytest.raises(ValueError, match="revision conflict"):
        apply_impact_override(
            session,
            recommendation,
            ImpactOverrideCreate(
                expected_revision=0,
                test_key="unrelated",
                action="include",
                reason="Review identified additional coupling requiring this test",
            ),
            principal=DEMO_PRINCIPAL,
        )
    assert session.get(m.ImpactRecommendation, created["id"]).current_revision == 1
    assert not session.scalars(select(m.ImpactOverride)).all()
    assert not session.scalars(
        select(m.AuditEvent).where(m.AuditEvent.action == "impact.override_created")
    ).all()


@pytest.mark.parametrize("files", [[None], [{"path": 123}]])
def test_malformed_changed_file_metadata_retains_validation_response(
    client, session, files
):
    project = _project(client)
    run, _ = _run_with_changes(session, project["id"], files=files)
    mapping = _create_mapping(client, project["id"])
    response = client.post(
        f"/api/v1/projects/{project['id']}/impact-recommendations",
        json={"run_id": run.id, "mapping_snapshot_id": mapping["id"]},
    )
    assert response.status_code == 422, response.text
    assert "changed-file metadata entry 0" in response.json()["detail"]
    assert not session.scalars(select(m.ImpactRecommendation)).all()
