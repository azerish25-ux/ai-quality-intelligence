"""Synthetic regression fixtures: these tests are not executed LedgerGuard provenance."""

import hashlib
import io
import json
import sys
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest
from failurelens.analysis import EvidenceView, analyze_failure
from failurelens.config import get_settings
from failurelens.ingestion import parse_artifact
from failurelens.jobs import process_next
from failurelens.models import Category, Failure, Run, RunInput
from failurelens.service import analyze_and_persist, select_failure_evidence
from failurelens.transaction_evidence import (
    inspect_multiplicity,
    parse_transaction_observation,
)
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SOURCE = "10000000-0000-0000-0000-000000000001"
DEST = "20000000-0000-0000-0000-000000000001"
IDENTITY = "transport::response"


def observation(count=2):
    effects = [
        {
            "id": f"30000000-0000-0000-0000-{i:012d}",
            "journal_id": f"40000000-0000-0000-0000-{i:012d}",
            "source_id": SOURCE,
            "destination_id": DEST,
            "amount_minor": 7,
            "currency": "CAD",
        }
        for i in range(1, count + 1)
    ]
    entries = [
        {
            "journal_id": e["journal_id"],
            "account_id": account,
            "side": side,
            "amount_minor": 7,
        }
        for e in effects
        for account, side in [(SOURCE, "DEBIT"), (DEST, "CREDIT")]
    ]
    return {
        "schema_version": "transaction-observations-v1",
        "test_identity": IDENTITY,
        "attempt": 0,
        "browser": None,
        "command": {
            "source_id": SOURCE,
            "destination_id": DEST,
            "amount_minor": 7,
            "currency": "CAD",
        },
        "requests": [
            {
                "sequence": i,
                "logical_key_digest": "a" * 64,
                "intent_digest": "b" * 64,
                "response_status": None if i == 1 else 201,
                "receipt_id": None if i == 1 else effects[-1]["id"],
            }
            for i in (1, 2)
        ],
        "before": {
            "balances": [
                {"account_id": SOURCE, "posted_minor": 100},
                {"account_id": DEST, "posted_minor": 50},
            ],
            "effects": [],
            "entries": [],
        },
        "after": {
            "balances": [
                {"account_id": SOURCE, "posted_minor": 100 - count * 7},
                {"account_id": DEST, "posted_minor": 50 + count * 7},
            ],
            "effects": effects,
            "entries": entries,
        },
    }


def bundle(value=None, *, extra_test=False, targets=None, omit=False):
    value = observation() if value is None else value
    xml = b'<testsuite tests="1"><testcase classname="transport" name="response"><failure message="Transport stream ended before a usable response"/></testcase>'
    if extra_test:
        xml += b'<testcase classname="other" name="failure"><failure message="Unknown event"/></testcase>'
    xml += b"</testsuite>"
    data = {
        "report.xml": xml,
        "measurements.json": json.dumps(value).encode(),
        "events.jsonl": b'{"event":"response_stream_closed","sequence":1}\n',
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
            "id": "measurements",
            "path": "measurements.json",
            "kind": "transaction-observations-json",
            "required": True,
            "correlates_to": ["report"] if targets is None else targets,
        },
        {
            "id": "events",
            "path": "events.jsonl",
            "kind": "console-jsonl",
            "required": True,
        },
    ]
    for entry in entries:
        entry["sha256"] = hashlib.sha256(data[entry["path"]]).hexdigest()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as z:
        z.writestr(
            "manifest.json", json.dumps({"schema_version": "2.0", "inputs": entries})
        )
        for name, content in data.items():
            if not (omit and name == "measurements.json"):
                z.writestr(name, content)
    return output.getvalue()


def ingest(client, session, content, slug="transactions", expected_state="succeeded"):
    project = client.post(
        "/api/v1/projects", json={"slug": slug, "name": "Synthetic transaction fixture"}
    ).json()
    response = client.post(
        f"/api/v1/projects/{project['id']}/ingestions",
        params={
            "external_id": "bundle",
            "filename": "bundle.zip",
            "repository": "example/synthetic",
            "commit_sha": "a" * 40,
            "branch": "test",
            "expected_inputs": 3,
            "source_format": "failurelens-bundle-v2",
        },
        content=content,
        headers={"content-type": "application/zip"},
    )
    assert response.status_code == 202, response.text
    assert process_next(session, "transaction-test", settings=get_settings())
    state = client.get("/api/v1/ingestions/" + response.json()["id"]).json()
    assert state["state"] == expected_state, state
    return project, state


def decision(value):
    return analyze_failure(
        message="Transport ended",
        exception_type=None,
        details={},
        evidence=[
            EvidenceView(
                id="numeric",
                kind="transaction_observation",
                excerpt=json.dumps(value),
                observation={"transaction_observation": value},
            )
        ],
    )


@pytest.mark.parametrize("count,status", [(1, "single"), (2, "duplicate")])
def test_numeric_relations(count, status):
    result = inspect_multiplicity(observation(count))
    assert result.status == status and result.count == count


def test_correlated_duplicate_supports_product_not_timeout_keyword():
    result = decision(observation())
    assert result.category == Category.product_defect
    assert result.claims[0]["predicate"] == {
        "kind": "committed_effect_multiplicity",
        "count": 2,
    }
    assert result.supporting_ids == ("numeric",)


def test_one_effect_is_not_blanket_infrastructure_or_release_reassurance():
    result = decision(observation(1))
    assert result.category == Category.insufficient_evidence and not result.claims


@pytest.mark.parametrize(
    "field",
    ["expected_category", "fault_enabled", "oracle", "root_cause", "committed_count"],
)
def test_producer_cannot_supply_answers(field):
    value = observation()
    value[field] = "product_defect"
    with pytest.raises(ValueError):
        parse_transaction_observation(json.dumps(value).encode())


@pytest.mark.parametrize("bad", [True, -1, 10**18, 7.0, "7"])
def test_minor_units_are_bounded_strict_integers(bad):
    value = observation()
    value["command"]["amount_minor"] = bad
    assert inspect_multiplicity(value).status == "invalid"


def test_duplicate_json_keys_rejected():
    with pytest.raises(ValueError):
        parse_transaction_observation(b'{"schema_version":"a","schema_version":"b"}')


def test_oversized_record_rejected():
    with pytest.raises(ValueError):
        parse_transaction_observation(b" " * 65537)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda v: v["requests"][1].update(logical_key_digest="c" * 64),
        lambda v: v["requests"][1].update(intent_digest="c" * 64),
        lambda v: v["requests"][1].update(sequence=3),
        lambda v: v["requests"][0].update(response_status=201),
        lambda v: v["requests"][1].update(response_status=503),
        lambda v: v["requests"][1].update(
            receipt_id="90000000-0000-0000-0000-000000000009"
        ),
        lambda v: v["after"]["effects"][1].update(id=v["after"]["effects"][0]["id"]),
        lambda v: v["after"]["effects"][1].update(
            journal_id=v["after"]["effects"][0]["journal_id"]
        ),
        lambda v: v["after"]["entries"].pop(),
        lambda v: v["after"]["entries"][0].update(side="CREDIT"),
        lambda v: v["after"]["entries"][0].update(amount_minor=8),
        lambda v: v["after"]["balances"][0].update(posted_minor=93),
        lambda v: v["after"]["effects"][1].update(currency="USD"),
        lambda v: v["after"]["effects"][1].update(amount_minor=8),
        lambda v: v.update(before=None),
        lambda v: v.update(after=None),
        lambda v: v["command"].update(destination_id=SOURCE),
    ],
)
def test_conflicting_missing_or_out_of_scope_measurements_abstain(mutation):
    value = observation()
    mutation(value)
    assert inspect_multiplicity(value).status not in {"single", "duplicate"}
    assert decision(value).category == Category.insufficient_evidence


def test_conflicting_observation_files_abstain():
    result = analyze_failure(
        message="Transport ended",
        exception_type=None,
        details={},
        evidence=[
            EvidenceView(
                id=str(i),
                kind="transaction_observation",
                excerpt="",
                observation={"transaction_observation": observation(i)},
            )
            for i in (1, 2)
        ],
    )
    assert result.category == Category.insufficient_evidence


def test_adapter_preserves_primitive_measurements_not_verdicts():
    parsed = parse_artifact(bundle(), "bundle.zip", get_settings())
    assert parsed.expected_inputs == 3 and parsed.received_inputs == 3
    assert len(parsed.observations) == 1 and parsed.completeness == "complete"
    assert parsed.inputs[1].metadata["transaction_observation"] == observation()


def test_real_api_worker_links_all_artifacts_without_cross_execution_leak(
    client, session
):
    _, state = ingest(client, session, bundle(extra_test=True))
    run = session.get(Run, state["run_id"])
    assert run.expected_inputs == 3 and run.completeness == "complete"
    failures = list(session.scalars(select(Failure).where(Failure.run_id == run.id)))
    assert len(failures) == 2
    for failure in failures:
        result = analyze_and_persist(session, failure)
        numeric = [
            e
            for e in select_failure_evidence(session, failure)
            if e.kind == "transaction_observation"
        ]
        if failure.execution.test_identity == IDENTITY:
            assert len(numeric) == 1 and result.category == Category.product_defect
            assert result.claims[0]["validation_status"] == "verified"
            evidence = client.get("/api/v1/evidence/" + numeric[0].id)
            assert (
                evidence.status_code == 200
                and evidence.json()["excerpt"] == numeric[0].excerpt
            )
        else:
            assert numeric == [] and result.category == Category.insufficient_evidence
    assert all(
        "transaction_observation" not in item.metadata_json
        for item in session.scalars(select(RunInput).where(RunInput.run_id == run.id))
    )


@pytest.mark.parametrize(
    "value,targets", [(observation(1), None), (observation(), ["other"])]
)
def test_control_and_wrong_input_binding_do_not_publish_product(
    client, session, value, targets
):
    _, state = ingest(client, session, bundle(value, targets=targets))
    failure = session.scalar(select(Failure).where(Failure.run_id == state["run_id"]))
    assert (
        analyze_and_persist(session, failure).category == Category.insufficient_evidence
    )


def test_changed_derivative_is_not_citable(client, session):
    _, state = ingest(client, session, bundle())
    failure = session.scalar(select(Failure).where(Failure.run_id == state["run_id"]))
    ev = next(
        e
        for e in select_failure_evidence(session, failure)
        if e.kind == "transaction_observation"
    )
    path = get_settings().artifact_root / ev.derivative.storage_path
    path.write_bytes(b"{}")
    assert (
        analyze_and_persist(session, failure).category == Category.insufficient_evidence
    )


def test_mismatched_typed_claim_count_is_rejected(client, session):
    from dataclasses import replace

    from failurelens.evidence_validation import (
        validate_decision,
        validate_evidence_records,
        validated_evidence_views,
    )

    _, state = ingest(client, session, bundle())
    failure = session.scalar(select(Failure).where(Failure.run_id == state["run_id"]))
    rows = select_failure_evidence(session, failure)
    checks = validate_evidence_records(failure, rows)
    d = analyze_failure(
        message=failure.message,
        exception_type=None,
        details={},
        evidence=validated_evidence_views(rows, checks),
    )
    claim = deepcopy(d.claims[0])
    claim["predicate"]["count"] = 3
    checked = validate_decision(
        failure=failure,
        decision=replace(d, claims=(claim,)),
        evidence_rows=rows,
        evidence_validation=checks,
        historical={},
    )
    assert checked.category == Category.insufficient_evidence and not checked.claims


def test_missing_required_measurement_is_partial_not_fabricated_success(
    client, session
):
    _, state = ingest(client, session, bundle(omit=True), expected_state="partial")
    run = session.get(Run, state["run_id"])
    assert run.completeness == "partial" and run.received_inputs == 2
    failure = session.scalar(select(Failure).where(Failure.run_id == run.id))
    assert (
        analyze_and_persist(session, failure).category == Category.insufficient_evidence
    )
