from __future__ import annotations

import pytest
from failurelens.models import Ingestion
from failurelens.service import create_project
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


@pytest.mark.parametrize(
    "metadata, expected_scope, expected_trust",
    [
        ({}, "unknown", "self_reported"),
        (
            {"run_scope": "full_suite", "comparison_trust": "trusted_workflow"},
            "full_suite",
            "trusted_workflow",
        ),
        (
            {
                "run_scope": "impact_selected",
                "comparison_trust": "authenticated_lookup",
            },
            "impact_selected",
            "authenticated_lookup",
        ),
    ],
)
def test_raw_ingestion_query_metadata_keeps_defaults_and_allowed_values(
    client: TestClient,
    session: Session,
    metadata: dict[str, str],
    expected_scope: str,
    expected_trust: str,
) -> None:
    project = create_project(session, "parameter-contract", "Parameter contract")
    response = client.post(
        f"/api/v1/projects/{project.id}/ingestions",
        params={"external_id": "parameter-run", "filename": "report.xml", **metadata},
        content=b'<testsuite><testcase name="passing"/></testsuite>',
        headers={"content-type": "application/xml"},
    )
    assert response.status_code == 202, response.text
    ingestion = session.get(Ingestion, response.json()["id"])
    assert ingestion is not None
    assert ingestion.attempt == 1
    assert ingestion.source_format == "auto"
    assert ingestion.source_metadata["run_scope"] == expected_scope
    assert ingestion.source_metadata["comparison_trust"] == expected_trust
    assert ingestion.source_metadata["transport"] == "raw-http"


@pytest.mark.parametrize(
    "method, path, parameter, value",
    [
        ("POST", "/projects/missing/ingestions", "run_scope", "everything"),
        ("POST", "/projects/missing/ingestions", "comparison_trust", "trusted"),
        ("POST", "/projects/missing/ingestions", "attempt", "0"),
        ("GET", "/runs/missing/binary-evidence", "limit", "101"),
        ("GET", "/binary-evidence/missing/trace-events", "offset", "-1"),
        ("GET", "/auth/sessions", "limit", "101"),
    ],
)
def test_router_query_constraints_reject_invalid_values_before_resource_lookup(
    client: TestClient,
    method: str,
    path: str,
    parameter: str,
    value: str,
) -> None:
    response = client.request(method, f"/api/v1{path}", params={parameter: value})
    assert response.status_code == 422, response.text
    errors = response.json()["detail"]
    assert [error["loc"] for error in errors] == [["query", parameter]]
    assert all("input" not in error for error in errors)
