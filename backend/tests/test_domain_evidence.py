"""Synthetic domain-contract tests; not LedgerGuard execution provenance."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import io
import json
import zipfile

import pytest
from sqlalchemy import select

from failurelens.analysis import EvidenceView, analyze_failure
from failurelens.config import get_settings
from failurelens.domain_evidence import inspect_domain, parse_domain_observation
from failurelens.evidence_validation import validate_decision, validate_evidence_records, validated_evidence_views
from failurelens.jobs import process_next
from failurelens.models import Category, Failure, RunInput
from failurelens.service import analyze_and_persist, select_failure_evidence

IDENTITY = "checks::observation"
BASE = dict(schema_version="domain-observations-v1", test_identity=IDENTITY, attempt=0, browser=None)


def operation(violation=True):
    return dict(**BASE, kind="operation_identity", contract="operation-is-part-of-request-identity-v1",
                scope_digest="a"*64, payload_digest="b"*64, first_operation="transfer", second_operation="refund",
                first_fingerprint="c"*64, second_fingerprint=("c" if violation else "d")*64)


def projection(violation=True):
    return dict(**BASE, kind="projection_order", contract="ignore-older-entity-events-v1", entity_digest="a"*64,
                before_version=9, event_version=8, after_version=8 if violation else 9,
                before_state_digest="b"*64, event_state_digest="c"*64,
                after_state_digest=("c" if violation else "b")*64)


def weekly(violation=True):
    return dict(**BASE, kind="weekly_recurrence", contract="weekly-same-local-wall-time-v1", timezone="America/Halifax",
                previous_occurrence="2026-01-05T09:00:00-04:00",
                next_occurrence="2026-01-11T09:00:00-04:00" if violation else "2026-01-12T09:00:00-04:00")


def decision(values):
    return analyze_failure(message="Observation differed", exception_type=None, details={}, evidence=[
        EvidenceView(id=f"ev-{i}", kind="domain_observation", excerpt="", observation={"domain_observation":v})
        for i,v in enumerate(values)])


def bundle(value, *, targets=None, extra=False, omit=False):
    report = b'<testsuite><testcase classname="checks" name="observation"><failure message="Observation differed"/></testcase>'
    if extra:
        report += b'<testcase classname="checks" name="other"><failure message="Observation differed"/></testcase>'
    report += b'</testsuite>'
    body=json.dumps(value).encode()
    entries=[dict(id="report",kind="junit-xml",path="report.xml",required=True,sha256=hashlib.sha256(report).hexdigest()),
             dict(id="measurements",kind="domain-observations-json",path="measurements.json",required=True,
                  sha256=hashlib.sha256(body).hexdigest(),correlates_to=["report"] if targets is None else targets)]
    out=io.BytesIO()
    with zipfile.ZipFile(out,"w",compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json",json.dumps(dict(schema_version="2.0",inputs=entries)))
        z.writestr("report.xml",report)
        if not omit: z.writestr("measurements.json",body)
    return out.getvalue()


def ingest(client,session,content):
    p=client.post('/api/v1/projects',json={"slug":"domain-probe","name":"Synthetic domain probe"}).json()
    queued=client.post(f"/api/v1/projects/{p['id']}/ingestions",params={"external_id":"one","filename":"bundle.zip","expected_inputs":2},
                       content=content,headers={"content-type":"application/zip"})
    assert queued.status_code==202,queued.text
    assert process_next(session,"domain-worker",settings=get_settings())
    state=client.get('/api/v1/ingestions/'+queued.json()['id']).json()
    assert state['state'] in {'succeeded','partial'},state
    return state


@pytest.mark.parametrize("factory",[operation,projection,weekly])
def test_domain_controls_and_violations(factory):
    assert inspect_domain(factory()).status=="violation"
    assert decision([factory()]).category is Category.product_defect
    assert inspect_domain(factory(False)).status=="consistent"
    assert decision([factory(False)]).category is Category.insufficient_evidence
    assert decision([factory(),factory(False)]).category is Category.insufficient_evidence


@pytest.mark.parametrize("factory,field",[(operation,"first_fingerprint"),(operation,"second_fingerprint"),
    (projection,"before_version"),(projection,"after_version"),(projection,"event_state_digest"),
    (weekly,"previous_occurrence"),(weekly,"next_occurrence")])
def test_missing_measurement_abstains(factory,field):
    value=factory();value[field]=None
    assert decision([value]).category is Category.insufficient_evidence


@pytest.mark.parametrize("mutate",[
    lambda v:v.update(after_version=True),lambda v:v.update(before_version=-1),
    lambda v:v.update(after_version=999),lambda v:v.update(after_state_digest="d"*64),
    lambda v:v.update(expected_category="product_defect"),
])
def test_invalid_and_incoherent_projection_abstain(mutate):
    value=projection();mutate(value)
    assert decision([value]).category is Category.insufficient_evidence


@pytest.mark.parametrize("previous,following,status",[
    ("2026-03-02T09:00:00-04:00","2026-03-09T09:00:00-03:00","consistent"),
    ("2026-10-26T09:00:00-03:00","2026-11-02T09:00:00-04:00","consistent"),
    ("2026-03-01T02:30:00-04:00","2026-03-08T03:30:00-03:00","incomplete"),
    ("2026-10-25T01:30:00-03:00","2026-11-01T01:30:00-04:00","incomplete"),
    ("2026-01-05T09:00:00-04:00","2026-01-12T09:00:00-03:00","invalid"),
    ("2026-01-05T09:00:00","2026-01-12T09:00:00-04:00","invalid"),
    ("2026-01-05T09:00:00-04:00","2026-01-12T10:00:00-04:00","conflicting"),
    ("2026-01-05T09:00:00-04:00","2026-01-04T09:00:00-04:00","conflicting"),
])
def test_weekly_calendar_semantics_and_dst(previous,following,status):
    value=weekly();value.update(previous_occurrence=previous,next_occurrence=following)
    assert inspect_domain(value).status==status
    assert decision([value]).category is Category.insufficient_evidence


def test_duplicate_json_keys_oversize_and_unknown_contract_rejected():
    with pytest.raises(ValueError):parse_domain_observation(b'{"kind":"operation_identity","kind":"projection_order"}')
    with pytest.raises(ValueError):parse_domain_observation(b' '*17000)
    value=operation();value['contract']='trust-the-generator'
    with pytest.raises(ValueError):parse_domain_observation(json.dumps(value).encode())


@pytest.mark.parametrize("factory",[operation,projection,weekly])
def test_domain_real_api_worker_scoped_binding_and_validated_claim(client,session,factory):
    state=ingest(client,session,bundle(factory(),extra=True))
    failures=list(session.scalars(select(Failure).where(Failure.run_id==state['run_id'])))
    assert len(failures)==2
    for failure in failures:
        result=analyze_and_persist(session,failure)
        domains=[e for e in select_failure_evidence(session,failure) if e.kind=='domain_observation']
        if failure.execution.test_identity==IDENTITY:
            assert len(domains)==1
            assert result.category is Category.product_defect
            assert result.claims[0]['validation_status']=='verified'
            assert client.get('/api/v1/artifact-derivatives/'+domains[0].derivative_id+'/content').status_code==200
        else:
            assert domains==[] and result.category is Category.insufficient_evidence
    assert all('domain_observation' not in row.metadata_json for row in session.scalars(select(RunInput)))


@pytest.mark.parametrize("mutate",[
    lambda c:c.update(text='The database is definitely responsible.'),
    lambda c:c['predicate'].update(invariant='weekly_recurrence'),
    lambda c:c['predicate'].update(forged=True),
    lambda c:c.update(evidence_ids=['different-run']),
])
def test_independent_publication_rejects_forged_domain_claim(client,session,mutate):
    state=ingest(client,session,bundle(operation()))
    failure=session.scalar(select(Failure).where(Failure.run_id==state['run_id']))
    rows=select_failure_evidence(session,failure);checked=validate_evidence_records(failure,rows)
    d=analyze_failure(message=failure.message,exception_type=None,details={},evidence=validated_evidence_views(rows,checked))
    claim=deepcopy(d.claims[0]);mutate(claim)
    result=validate_decision(failure=failure,decision=replace(d,claims=(claim,)),evidence_rows=rows,evidence_validation=checked,historical={})
    assert result.category is Category.insufficient_evidence and not result.claims


def test_missing_or_wrongly_bound_domain_does_not_create_diagnosis(client,session):
    state=ingest(client,session,bundle(operation(),targets=['unrelated']))
    failure=session.scalar(select(Failure).where(Failure.run_id==state['run_id']))
    assert analyze_and_persist(session,failure).category is Category.insufficient_evidence


@pytest.mark.parametrize("factory", [operation, projection, weekly])
def test_consistent_measurements_do_not_create_api_product_blame(client, session, factory):
    state = ingest(client, session, bundle(factory(False)))
    failure = session.scalar(select(Failure).where(Failure.run_id == state["run_id"]))
    result = analyze_and_persist(session, failure)
    assert result.category is Category.insufficient_evidence
    assert not result.claims
