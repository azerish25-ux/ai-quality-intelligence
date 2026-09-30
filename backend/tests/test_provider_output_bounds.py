"""Provider output and approved-preview bounds match their public contracts."""

import json

import pytest
from failurelens import models as m
from failurelens.provider_jobs import heartbeat_provider_worker, run_provider_once
from failurelens.provider_service import _digest
from failurelens.providers import validate_proposal
from failurelens.schemas import IngestionRequest
from failurelens.schemas import TestObservation as InputObservation
from failurelens.service import analyze_and_persist, ingest_normalized
from sqlalchemy import select
from test_provider_ledger import good_response
from test_provider_workflow import fixture_provider, submit

pytest_plugins = ("test_provider_workflow",)


@pytest.mark.parametrize("field", ["hypothesis", "missing_evidence"])
@pytest.mark.parametrize(
    "character,length,expected",
    [
        ("x", 0, "fallback"),
        ("x", 1200, "proposed"),
        ("x", 1201, "fallback"),
        ("😀", 1200, "proposed"),
        ("😀", 1201, "fallback"),
    ],
)
def test_proposal_text_bounds_count_unicode_code_points(
    field, character, length, expected
):
    value = character * length
    proposal = {
        "category": "product_defect",
        "hypotheses": [],
        "contradictory_evidence_ids": [],
        "missing_evidence": [],
    }
    if field == "hypothesis":
        proposal["hypotheses"] = [{"text": value, "evidence_ids": ["e1"]}]
    else:
        proposal["missing_evidence"] = [value]
    result = validate_proposal(proposal, "product_defect", {"e1"})
    assert result.status == expected
    if expected == "fallback":
        assert result.proposal is None and result.reason == "invalid_response_schema"


@pytest.mark.parametrize("value", ["", "x" * 1201, "😀" * 1201])
def test_previously_persisted_unbounded_missing_evidence_projects_safe_fallback(
    workflow, value
):
    factory, scope, principal, settings, _api_settings, client, base = workflow
    invocation_id, _ = submit(factory, scope, principal, settings)
    assert run_provider_once(factory, settings, provider_factory=fixture_provider())
    with factory.begin() as session:
        row = session.get(m.ModelInvocation, invocation_id)
        row.proposal_json = row.proposal_json | {"missing_evidence": [value]}
    for path in (base + "/invocations/" + invocation_id, base + "/invocations"):
        response = client.get(path)
        assert response.status_code == 200
        result = response.json()
        item = result["items"][0] if "items" in result else result
        assert (
            item["status"] == "fallback" and item["reason"] == "invalid_response_schema"
        )
        assert item["proposal"] is None
        assert item["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}


def test_preview_exposes_exact_prepared_evidence_above_old_32k_ui_limit(workflow):
    factory, scope, principal, settings, api_settings, client, _base = workflow
    for config in (settings, api_settings):
        config.provider_max_context_bytes = "100000"
        config.provider_max_run_reserved_tokens = "200000"
    generic_secret = "previewfixturecanary"
    with factory() as session:
        project = session.get(m.Project, scope["project_id"])
        run = ingest_normalized(
            session,
            project,
            IngestionRequest(
                external_id="large-approved-provider-evidence",
                observations=[
                    InputObservation(
                        test_identity="large-evidence-invariant",
                        outcome="failed",
                        message="balance invariant violated: duplicate committed transfer produced double charge "
                        + "x" * 39_000
                        + " token="
                        + generic_secret,
                        details={"data_integrity_violation": True},
                    )
                ],
            ),
        )
        failure = session.scalar(select(m.Failure).where(m.Failure.run_id == run.id))
        analysis = analyze_and_persist(session, failure)
        selected = {
            "project_id": project.id,
            "run_id": run.id,
            "analysis_id": analysis.id,
        }
    heartbeat_provider_worker(factory, settings)
    base = "/api/v1/projects/{project_id}/runs/{run_id}/analyses/{analysis_id}/provider".format(
        **selected
    )
    response = client.get(base + "/preview")
    assert response.status_code == 200
    preview = response.json()
    assert preview["can_submit"]
    assert any(len(row["excerpt"]) > 32_000 for row in preview["evidence"])
    assert all(len(row["excerpt"]) <= 100_000 for row in preview["evidence"])
    assert generic_secret not in response.text
    invocation_id, _ = submit(factory, selected, principal, settings)

    def handler(request):
        context_text = json.loads(request.content)["messages"][1]["content"]
        assert len(context_text.encode()) <= 100_000
        assert json.loads(context_text)["evidence"] == preview["evidence"]
        assert generic_secret not in context_text
        with factory() as session:
            invocation = session.get(m.ModelInvocation, invocation_id)
            assert invocation.request_digest == _digest(json.loads(request.content))
            assert invocation.preview_digest == preview["preview_digest"]
        return good_response(request)

    assert run_provider_once(
        factory, settings, provider_factory=fixture_provider(handler)
    )
    assert (
        client.get(base + "/invocations/" + invocation_id).json()["invocation_state"]
        == "proposed"
    )
