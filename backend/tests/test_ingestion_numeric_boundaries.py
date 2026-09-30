from __future__ import annotations

import hashlib
import json

import pytest
from failurelens.config import get_settings
from failurelens.ingestion import parse_artifact, parse_junit_xml, parse_pytest_json
from failurelens.models import Failure, PerformanceObservation
from failurelens.models import TestExecution as Execution
from failurelens.schemas import RunMetadata
from failurelens.service import create_project, ingest_parsed_report
from sqlalchemy import select


@pytest.mark.parametrize("duration", ["inf", "-inf", "NaN", "1e309"])
def test_junit_nonfinite_duration_remains_unavailable(duration: str) -> None:
    content = (
        f'<testsuite><testcase name="checkout" time="{duration}">'
        '<failure message="assertion failed"/></testcase></testsuite>'
    ).encode()

    observation = parse_junit_xml(content)[0]

    assert observation.duration_ms is None
    assert observation.outcome == "failed"
    assert observation.message == "assertion failed"


def test_pytest_oversized_duration_does_not_lose_failed_observation() -> None:
    content = json.dumps(
        {
            "tests": [
                {
                    "nodeid": "test_checkout.py::test_charge",
                    "outcome": "failed",
                    "call": {
                        "duration": 10**400,
                        "crash": {"message": "AssertionError: charge rejected"},
                    },
                }
            ]
        }
    ).encode()

    observation = parse_pytest_json(content)[0]

    assert observation.duration_ms is None
    assert observation.outcome == "failed"
    assert observation.exception_type == "AssertionError"


@pytest.mark.parametrize("status", [float("inf"), float("-inf"), float("nan")])
def test_har_nonfinite_status_preserves_network_failure(status: float) -> None:
    content = json.dumps(
        {
            "log": {
                "entries": [
                    {
                        "request": {"method": "POST", "url": "https://example.test"},
                        "response": {"status": status},
                        "_error": "connection failed",
                    }
                ]
            }
        }
    ).encode()

    observation = parse_artifact(content, "report.har", get_settings()).observations[0]

    assert observation.outcome == "failed"
    assert observation.exception_type == "NetworkError"
    assert observation.details["status"] is None
    assert observation.message is not None
    assert "connection failed" in observation.message


@pytest.mark.parametrize("count", [float("inf"), float("nan"), 10**400])
def test_k6_invalid_count_preserves_valid_measurement_and_failure(
    session, count
) -> None:
    project = create_project(session, "numeric-boundary", "Numeric boundary")
    content = json.dumps(
        {
            "metrics": {
                "http_req_duration": {
                    "type": "trend",
                    "contains": "time",
                    "values": {"avg": 250, "count": count},
                    "thresholds": {"avg<200": {"ok": False}},
                }
            }
        }
    ).encode()
    parsed = parse_artifact(
        content, "summary.json", get_settings(), source_format="k6-summary-json"
    )
    run = ingest_parsed_report(
        session,
        project,
        RunMetadata(external_id="invalid-sample-count"),
        parsed.observations,
        source_name="summary.json",
        source_digest=hashlib.sha256(content).hexdigest(),
        source_size_bytes=len(content),
        storage_path="test://invalid-sample-count",
        media_type="application/json",
        source_format=parsed.source_format,
        parser_version=parsed.parser_version,
        input_records=parsed.inputs,
    )
    measurements = list(
        session.scalars(
            select(PerformanceObservation).where(
                PerformanceObservation.run_id == run.id
            )
        )
    )

    assert len(measurements) == 1
    assert measurements[0].statistic == "avg"
    assert measurements[0].canonical_value == 250
    assert measurements[0].sample_count is None
    assert measurements[0].threshold_status == "failed"
    assert session.scalar(select(Failure).where(Failure.run_id == run.id)) is not None
    execution = session.scalar(select(Execution).where(Execution.run_id == run.id))
    assert execution is not None and execution.outcome.value == "failed"
