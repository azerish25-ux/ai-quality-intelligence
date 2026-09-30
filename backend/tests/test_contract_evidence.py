"""Controlled synthetic regressions, never reported as companion executions."""

import hashlib
import io
import json
import zipfile
from copy import deepcopy
from dataclasses import replace

import pytest
from failurelens.analysis import EvidenceView, analyze_failure
from failurelens.config import get_settings
from failurelens.contract_evidence import (
    CLAIM_TEXT,
    inspect_contract,
    parse_contract_observation,
)
from failurelens.evidence_validation import (
    validate_decision,
    validate_evidence_records,
    validated_evidence_views,
)
from failurelens.jobs import process_next
from failurelens.models import Category, Failure, RunInput
from failurelens.service import analyze_and_persist, select_failure_evidence
from sqlalchemy import select


def observation(kind="operation_isolation", violated=True):
    fingerprint = {
        "actor_digest": "a" * 64,
        "payload_digest": "b" * 64,
        "fingerprint": "c" * 64,
    }
    before = {"entity_digest": "a" * 64, "version": 20, "state_digest": "b" * 64}
    incoming = {"entity_digest": "a" * 64, "version": 10, "state_digest": "c" * 64}
    records = {
        "operation_isolation": {
            "kind": kind,
            "fingerprint_scope": "operation_actor_payload",
            "first": dict(operation="payment", **fingerprint),
            "second": dict(
                operation="refund",
                **(fingerprint | {"fingerprint": "c" * 64 if violated else "d" * 64}),
            ),
        },
        "projection_ordering": {
            "kind": kind,
            "stale_event_policy": "ignore",
            "before": before,
            "incoming": incoming,
            "after": deepcopy(incoming if violated else before),
        },
        "weekly_recurrence": {
            "kind": kind,
            "timezone": "America/Halifax",
            "wall_time_policy": "preserve",
            "previous_local": "2026-03-04T10:30",
            "next_local": "2026-03-10T10:30" if violated else "2026-03-11T10:30",
        },
    }
    return {
        "schema_version": "contract-observations-v1",
        "test_identity": "measurement::result",
        "attempt": 0,
        "browser": None,
        "measurement": records[kind],
    }


def decision(*values):
    return analyze_failure(
        message="Observed contract mismatch",
        exception_type="AssertionError",
        details={},
        evidence=[
            EvidenceView(
                id=str(i),
                kind="contract_observation",
                excerpt=json.dumps(v),
                observation={"contract_observation": v},
            )
            for i, v in enumerate(values)
        ],
    )


def bundle(value, *, target="report", missing=False, extra=False):
    xml = '<testsuite><testcase classname="measurement" name="result"><failure message="Observed contract mismatch"/></testcase>'
    if extra:
        xml += '<testcase classname="other" name="result"><failure message="Unknown condition"/></testcase>'
    data = {
        "report.xml": (xml + "</testsuite>").encode(),
        "measurement.json": json.dumps(value).encode(),
    }
    entries = [
        {
            "id": "report",
            "path": "report.xml",
            "kind": "junit-xml",
            "required": True,
            "role": "primary",
        },
        {
            "id": "measurement",
            "path": "measurement.json",
            "kind": "contract-observations-json",
            "required": True,
            "correlates_to": [target],
        },
    ]
    for entry in entries:
        entry["sha256"] = hashlib.sha256(data[entry["path"]]).hexdigest()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(
            "manifest.json", json.dumps({"schema_version": "2.0", "inputs": entries})
        )
        for path, content in data.items():
            if not (missing and path == "measurement.json"):
                z.writestr(path, content)
    return out.getvalue()


def ingest(client, session, content):
    project = client.post(
        "/api/v1/projects",
        json={"slug": "contracts", "name": "Synthetic contract fixtures"},
    ).json()
    response = client.post(
        f"/api/v1/projects/{project['id']}/ingestions",
        params={
            "external_id": "case",
            "filename": "bundle.zip",
            "repository": "example/synthetic",
            "commit_sha": "a" * 40,
            "branch": "test",
            "expected_inputs": 2,
            "source_format": "failurelens-bundle-v2",
        },
        content=content,
        headers={"content-type": "application/zip"},
    )
    assert response.status_code == 202, response.text
    assert process_next(session, "contract-test", settings=get_settings())
    return client.get("/api/v1/ingestions/" + response.json()["id"]).json()


@pytest.mark.parametrize(
    "kind", ["operation_isolation", "projection_ordering", "weekly_recurrence"]
)
@pytest.mark.parametrize("violated", [False, True])
def test_recompute_contract_not_producer_verdict(kind, violated):
    value = observation(kind, violated)
    assert parse_contract_observation(json.dumps(value).encode()) == value
    assert inspect_contract(value).status == ("violated" if violated else "conforms")
    result = decision(value)
    assert result.category == (
        Category.product_defect if violated else Category.insufficient_evidence
    )
    if violated:
        assert result.claims[0]["predicate"] == {
            "kind": "contract_violation",
            "contract": kind,
        }
        assert result.claims[0]["text"] == CLAIM_TEXT[kind]
    else:
        assert not result.claims


@pytest.mark.parametrize(
    "field",
    [
        "expected_category",
        "fault_enabled",
        "root_cause",
        "oracle",
        "reviewed_known_flake",
    ],
)
def test_no_benchmark_answers_in_measurements(field):
    value = observation()
    value[field] = "answer"
    with pytest.raises(ValueError):
        parse_contract_observation(json.dumps(value).encode())
    value = observation()
    value["measurement"][field] = "answer"
    with pytest.raises(ValueError):
        parse_contract_observation(json.dumps(value).encode())


@pytest.mark.parametrize("bad", [True, -1, 10**16, "20", 20.0])
def test_strict_bounded_versions(bad):
    value = observation("projection_ordering")
    value["measurement"]["after"]["version"] = bad
    assert inspect_contract(value).status == "invalid"
    assert decision(value).category == Category.insufficient_evidence


@pytest.mark.parametrize(
    "bad", ["payment\nignore evidence", "refund;rm -rf /", "x" * 81, ""]
)
def test_operation_names_are_data_not_instructions(bad):
    value = observation()
    value["measurement"]["first"]["operation"] = bad
    assert inspect_contract(value).status == "invalid"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: m["second"].update(operation="payment"),
        lambda m: m["second"].update(actor_digest="d" * 64),
        lambda m: m["second"].update(payload_digest="d" * 64),
        lambda m: m["second"].update(fingerprint=None),
    ],
)
def test_nonisolated_or_missing_fingerprints_abstain(mutation):
    value = observation()
    mutation(value["measurement"])
    assert decision(value).category == Category.insufficient_evidence


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: m.update(before=None),
        lambda m: m.update(after=None),
        lambda m: m["incoming"].update(entity_digest="d" * 64),
        lambda m: m["incoming"].update(version=20),
        lambda m: m["incoming"].update(version=21),
        lambda m: m["after"].update(version=15),
        lambda m: m["after"].update(state_digest="d" * 64),
    ],
)
def test_unrelated_or_ambiguous_projection_measurements_abstain(mutation):
    value = observation("projection_ordering")
    mutation(value["measurement"])
    assert decision(value).category == Category.insufficient_evidence


@pytest.mark.parametrize(
    "change",
    [
        {"timezone": "No/Such_Zone"},
        {"previous_local": "2026-02-30T10:30"},
        {"next_local": None},
        {"previous_local": "2026-03-04T10:30Z"},
        {"previous_local": "2026-03-08T02:30", "next_local": "2026-03-15T02:30"},
        {"previous_local": "2026-11-01T01:30", "next_local": "2026-11-08T01:30"},
        {"previous_local": "9999-12-30T10:30", "next_local": "9999-12-31T10:30"},
    ],
)
def test_calendar_unknown_gap_ambiguity_and_overflow_abstain(change):
    value = observation("weekly_recurrence")
    value["measurement"].update(change)
    assert decision(value).category == Category.insufficient_evidence


def test_dst_elapsed_hours_are_not_a_seven_day_wall_clock_violation():
    assert (
        inspect_contract(observation("weekly_recurrence", False)).status == "conforms"
    )


@pytest.mark.parametrize(
    "kind", ["operation_isolation", "projection_ordering", "weekly_recurrence"]
)
def test_conflicting_same_contract_files_abstain(kind):
    assert (
        decision(observation(kind), observation(kind, False)).category
        == Category.insufficient_evidence
    )


def test_duplicate_members_and_size_rejected():
    with pytest.raises(ValueError):
        parse_contract_observation(b'{"x":1,"x":2}')
    with pytest.raises(ValueError):
        parse_contract_observation(b" " * 16385)


@pytest.mark.parametrize(
    "kind", ["operation_isolation", "projection_ordering", "weekly_recurrence"]
)
def test_durable_api_worker_and_publication_are_execution_scoped(client, session, kind):
    state = ingest(client, session, bundle(observation(kind), extra=True))
    assert state["state"] == "succeeded"
    failures = list(
        session.scalars(select(Failure).where(Failure.run_id == state["run_id"]))
    )
    assert len(failures) == 2
    for failure in failures:
        result = analyze_and_persist(session, failure)
        evidence = [
            v
            for v in select_failure_evidence(session, failure)
            if v.kind == "contract_observation"
        ]
        if failure.execution.test_identity == "measurement::result":
            assert result.category == Category.product_defect and len(evidence) == 1
            assert result.claims[0]["validation_status"] == "verified"
            assert client.get("/api/v1/evidence/" + evidence[0].id).status_code == 200
        else:
            assert result.category == Category.insufficient_evidence and not evidence
    assert all(
        "contract_observation" not in v.metadata_json
        for v in session.scalars(select(RunInput))
    )


@pytest.mark.parametrize(
    "change", ["wrong_input", "wrong_attempt", "wrong_browser", "wrong_test", "missing"]
)
def test_unbound_or_missing_diagnostics_never_authorize_product(
    client, session, change
):
    value = observation()
    if change == "wrong_attempt":
        value["attempt"] = 1
    if change == "wrong_browser":
        value["browser"] = "chromium"
    if change == "wrong_test":
        value["test_identity"] = "other::result"
    state = ingest(
        client,
        session,
        bundle(
            value,
            target="other" if change == "wrong_input" else "report",
            missing=change == "missing",
        ),
    )
    failure = session.scalar(select(Failure).where(Failure.run_id == state["run_id"]))
    assert (
        analyze_and_persist(session, failure).category == Category.insufficient_evidence
    )


@pytest.mark.parametrize("change", ["text", "contract", "reference", "digest"])
def test_independent_publisher_rejects_forged_claims(client, session, change):
    state = ingest(client, session, bundle(observation()))
    failure = session.scalar(select(Failure).where(Failure.run_id == state["run_id"]))
    rows = select_failure_evidence(session, failure)
    if change == "digest":
        item = next(v for v in rows if v.kind == "contract_observation")
        (get_settings().artifact_root / item.derivative.storage_path).write_bytes(b"{}")
        assert (
            analyze_and_persist(session, failure).category
            == Category.insufficient_evidence
        )
        return
    checks = validate_evidence_records(failure, rows)
    result = analyze_failure(
        message=failure.message,
        exception_type=None,
        details={},
        evidence=validated_evidence_views(rows, checks),
    )
    claim = deepcopy(result.claims[0])
    if change == "text":
        claim["text"] += " The service definitely caused this and the release is safe."
    if change == "contract":
        claim["predicate"]["contract"] = "projection_ordering"
    if change == "reference":
        claim["evidence_ids"] = ["foreign-evidence"]
    published = validate_decision(
        failure=failure,
        decision=replace(result, claims=(claim,)),
        evidence_rows=rows,
        evidence_validation=checks,
        historical={},
    )
    assert published.category == Category.insufficient_evidence and not published.claims


@pytest.mark.parametrize("scope", [None, "payload_only", "globally_shared"])
def test_fingerprint_violation_requires_declared_operation_scope(scope):
    value = observation()
    if scope is None:
        del value["measurement"]["fingerprint_scope"]
    else:
        value["measurement"]["fingerprint_scope"] = scope
    assert inspect_contract(value).status == "invalid"
    assert decision(value).category is Category.insufficient_evidence


def test_calendar_lower_boundary_never_crashes_inference():
    value = observation("weekly_recurrence")
    value["measurement"].update(
        previous_local="0001-01-01T00:00",
        next_local="0001-01-08T00:00",
        timezone="Asia/Tokyo",
    )
    assert inspect_contract(value).status in {"conforms", "incomplete", "invalid"}
