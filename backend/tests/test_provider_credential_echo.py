"""A provider response cannot publish its known Authorization credential."""

from __future__ import annotations

import json
import logging
from uuid import uuid4

import httpx
import pytest
from failurelens import models as m
from failurelens.auth import create_auth_session, create_user
from failurelens.provider_jobs import run_provider_once
from failurelens.redaction import redact_text
from pydantic import SecretStr
from sqlalchemy import select
from test_provider_workflow import fixture_provider, submit

pytest_plugins = ("test_provider_workflow",)


@pytest.mark.parametrize(
    "location",
    [
        "hypothesis",
        "missing_evidence",
        "evidence_id",
        "contradictory_id",
        "category",
        "nested_text",
        "nested_extra",
        "object_key",
        "inner_json_escape",
        "outer_json_escape",
    ],
)
def test_known_credential_echo_is_rejected_before_ledger_and_viewer_projection(
    workflow, location, caplog
):
    factory, scope, principal, settings, api_settings, client, base = workflow
    # A fixture-only arbitrary value without generic secret-name or token syntax.
    credential = "".join(chr(ord("a") + int(char, 16)) for char in uuid4().hex)
    assert not redact_text(credential).replacements
    settings.provider_token = SecretStr(credential)
    for config in (settings, api_settings):
        config.provider_input_price_per_million = "2"
        config.provider_output_price_per_million = "4"
        config.provider_pricing_source = "Operator fixture price sheet"
        config.provider_pricing_date = "2026-09-30"
        config.provider_currency = "USD"
    invocation_id, _ = submit(factory, scope, principal, settings)
    calls = []

    def echo(request):
        calls.append(1)
        echoed = request.headers["Authorization"].removeprefix("Bearer ")
        context = json.loads(json.loads(request.content)["messages"][1]["content"])
        proposal = {
            "category": "product_defect",
            "hypotheses": [
                {
                    "text": "Investigate the observed effect",
                    "evidence_ids": [context["evidence"][0]["id"]],
                }
            ],
            "contradictory_evidence_ids": [],
            "missing_evidence": [],
        }
        if location in {"hypothesis", "inner_json_escape", "outer_json_escape"}:
            proposal["hypotheses"][0]["text"] = "Provider marker: " + echoed
        elif location == "missing_evidence":
            proposal["missing_evidence"] = ["Provider marker: " + echoed]
        elif location == "evidence_id":
            proposal["hypotheses"][0]["evidence_ids"] = [echoed]
        elif location == "contradictory_id":
            proposal["contradictory_evidence_ids"] = [echoed]
        elif location == "category":
            proposal["category"] = echoed
        elif location == "nested_text":
            proposal["hypotheses"][0]["text"] = json.dumps(
                {"diagnostic": {"value": echoed}}
            )
        elif location == "nested_extra":
            proposal["extra"] = {"nested": [{"value": echoed}]}
        elif location == "object_key":
            proposal[echoed] = "unexpected field"
        content = json.dumps(proposal)
        escaped = "".join(f"\\u{ord(character):04x}" for character in echoed)
        if location == "inner_json_escape":
            content = content.replace(echoed, escaped)
        body = json.dumps(
            {
                "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            }
        )
        if location == "outer_json_escape":
            body = body.replace(echoed, escaped)
        return httpx.Response(200, content=body)

    with caplog.at_level(logging.DEBUG):
        assert run_provider_once(
            factory, settings, provider_factory=fixture_provider(echo)
        )
    assert calls == [1]
    # Read through an independently authenticated viewer, keeping the requester's
    # role active so the actual provider rejection reason remains observable.
    with factory.begin() as session:
        viewer = create_user(
            session,
            username="credential-echo-viewer",
            display_name="Fixture viewer",
            password="fixture-viewer-password-only",
        )
        _, viewer_token = create_auth_session(session, viewer)
        session.add(
            m.ProjectMembership(
                project_id=scope["project_id"],
                user_id=viewer.id,
                role=m.ProjectRole.viewer,
            )
        )
    client.headers["Authorization"] = f"Bearer {viewer_token}"
    response = client.get(base + "/invocations/" + invocation_id)
    assert response.status_code == 200
    result = response.json()
    assert (
        result["invocation_state"] == "fallback"
        and result["reason"] == "sensitive_output"
    )
    assert result["proposal"] is None
    assert result["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}
    assert result["estimated_cost"] == pytest.approx(0.0004)
    assert result["attempts"][0]["spend_status"] == "reported"
    with factory() as session:
        invocation = session.get(m.ModelInvocation, invocation_id)
        assert invocation.proposal_json is None
        records = [
            dict(row)
            for table in (
                m.ModelInvocation,
                m.ModelAttempt,
                m.ModelRunBudget,
                m.Job,
                m.AuditEvent,
            )
            for row in session.execute(select(table.__table__)).mappings()
        ]
    assert credential not in response.text + str(records) + caplog.text
