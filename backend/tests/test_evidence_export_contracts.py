"""Synthetic export and prior-review contracts without any GitHub mutation."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from failurelens import models as m
from failurelens.config import get_settings
from failurelens.github_evidence import (
    MAX_EXPORT_BYTES,
    MAX_REFERENCES,
    build_evidence_export,
    canonical_export_bytes,
    evidence_for_report,
)
from failurelens.github_snapshot import report_snapshot
from failurelens.publication_validity import PublicationContext
from failurelens.schemas import ReviewCreate
from failurelens.service import add_review
from sqlalchemy import inspect, select
from test_github_evidence import make_run


def _records(factory):
    with factory() as reader:
        return {
            (model.__name__, row.id): json.dumps(
                {
                    column.key: getattr(row, column.key)
                    for column in inspect(model).column_attrs
                },
                sort_keys=True,
                default=str,
            )
            for model in (
                m.Run,
                m.Evidence,
                m.ArtifactDerivative,
                m.Analysis,
                m.ReviewEvent,
            )
            for row in reader.scalars(select(model))
        }


INVALID_EXPORT_ARGUMENTS = [
    pytest.param({"analysis_ids": "not-a-list"}, id="analysis-list-type"),
    pytest.param({"analysis_ids": [1]}, id="analysis-id-type"),
    pytest.param({"analysis_ids": ["id"] * 51}, id="analysis-list-bound"),
    pytest.param(
        {"additional_evidence_ids": {"id": "value"}}, id="extra-evidence-list-type"
    ),
    pytest.param(
        {"additional_evidence_ids": ["id"] * (MAX_REFERENCES + 1)},
        id="extra-evidence-bound",
    ),
    pytest.param({"allowed_related_run_ids": "not-a-list"}, id="related-run-list-type"),
    pytest.param({"allowed_related_run_ids": ["id"] * 101}, id="related-run-bound"),
    pytest.param({"max_bytes": True}, id="boolean-byte-limit"),
    pytest.param({"max_bytes": 4096.0}, id="noninteger-byte-limit"),
    pytest.param({"max_bytes": 4095}, id="byte-limit-too-small"),
    pytest.param({"max_bytes": MAX_EXPORT_BYTES + 1}, id="byte-limit-too-large"),
    pytest.param({"omitted_section_reference_hints": -1}, id="negative-section-hints"),
    pytest.param({"omitted_section_reference_hints": True}, id="boolean-section-hints"),
    pytest.param(
        {"omitted_section_reference_hints": 10**9 + 1}, id="oversized-section-hints"
    ),
    pytest.param({"omitted_related_run_hints": -1}, id="negative-related-hints"),
    pytest.param({"omitted_related_run_hints": 1.5}, id="noninteger-related-hints"),
    pytest.param(
        {"omitted_related_run_hints": 10**9 + 1}, id="oversized-related-hints"
    ),
]


@pytest.mark.parametrize("changes", INVALID_EXPORT_ARGUMENTS)
def test_invalid_export_request_preserves_data_and_still_allows_a_valid_export(
    session, session_factory, changes
):
    run, evidence = make_run(session, outcome=m.Outcome.passed)
    arguments = {"analysis_ids": [], "additional_evidence_ids": [evidence.id]}
    control = build_evidence_export(session, run, **arguments)
    assert control["counts"]["exported"] == 1
    before = _records(session_factory)
    path = Path(get_settings().artifact_root) / evidence.derivative.storage_path
    original_bytes = path.read_bytes()
    with pytest.raises(
        ValueError, match="^evidence export request exceeds supported bounds$"
    ):
        build_evidence_export(session, run, **{**arguments, **changes})
    assert not session.new and not session.dirty
    session.commit()
    assert _records(session_factory) == before
    assert path.read_bytes() == original_bytes
    assert build_evidence_export(session, run, **arguments) == control


@pytest.mark.parametrize("field", ["run_id", "project_id"])
def test_report_export_rejects_wrong_snapshot_scope_without_modifying_it(
    session, session_factory, field
):
    run, _ = make_run(session)
    snapshot = report_snapshot(session, run)
    valid = evidence_for_report(session, run, snapshot)
    assert valid["items"]
    changed = deepcopy(snapshot)
    changed[field] = "unrelated-scope"
    before_snapshot = deepcopy(changed)
    before = _records(session_factory)
    with pytest.raises(ValueError, match="^report evidence scope does not match$"):
        evidence_for_report(session, run, changed)
    assert changed == before_snapshot
    assert evidence_for_report(session, run, snapshot) == valid
    session.commit()
    assert _records(session_factory) == before


def test_invalid_analysis_reference_is_disclosed_without_blocking_valid_evidence(
    session,
):
    run, evidence = make_run(session, outcome=m.Outcome.passed)
    document = build_evidence_export(
        session,
        run,
        analysis_ids=["invalid/reference"],
        additional_evidence_ids=[evidence.id],
    )
    assert document["analysis_ids"] == []
    assert document["counts"]["unavailable_analyses"] == 1
    assert document["counts"]["exported"] == 1
    assert document["items"][0]["evidence_id"] == evidence.id
    assert b"invalid/reference" not in canonical_export_bytes(document)
    unsigned = {
        key: value for key, value in document.items() if key != "evidence_digest"
    }
    assert (
        hashlib.sha256(canonical_export_bytes(unsigned)).hexdigest()
        == document["evidence_digest"]
    )


@pytest.mark.parametrize("missing", ["event", "inherited-analysis-citation"])
def test_prior_acceptance_requires_its_event_and_inherited_analysis_citations(
    session, session_factory, missing
):
    run, _ = make_run(session)
    analysis = session.scalar(
        select(m.Analysis).where(m.Analysis.failure.has(m.Failure.run_id == run.id))
    )
    assert analysis.supporting_evidence_ids
    event = add_review(
        session,
        analysis,
        ReviewCreate(
            decision="accept", reason="Synthetic supported finding", expected_version=0
        ),
    )
    assert (
        event.supporting_evidence_ids == [] and event.contradictory_evidence_ids == []
    )
    assert PublicationContext(session)._review_citations_available(
        run.project_id, [event.id]
    )
    before = _records(session_factory)
    if missing == "event":
        assert not PublicationContext(session)._review_citations_available(
            run.project_id, [event.id, "missing-review"]
        )
    else:
        cited = session.get(m.Evidence, analysis.supporting_evidence_ids[0])
        path = Path(get_settings().artifact_root) / cited.derivative.storage_path
        preserved = path.with_name(path.name + ".preserved-for-boundary-test")
        path.rename(preserved)
        try:
            assert not PublicationContext(session)._review_citations_available(
                run.project_id, [event.id]
            )
            assert _records(session_factory) == before
        finally:
            preserved.rename(path)
    assert PublicationContext(session)._review_citations_available(
        run.project_id, [event.id, event.id]
    )
    session.commit()
    assert _records(session_factory) == before


def test_reference_cannot_claim_a_project_when_its_run_belongs_elsewhere(
    session, session_factory
):
    current, owned = make_run(session, outcome=m.Outcome.passed)
    foreign_run, foreign = make_run(
        session, slug="foreign-reference", outcome=m.Outcome.passed
    )
    assert foreign_run.project_id != current.project_id
    foreign.project_id = current.project_id
    session.commit()
    before = _records(session_factory)
    found = PublicationContext(session).inspectable_references(
        current.project_id, {owned.id, foreign.id}
    )
    assert found == {owned.id}
    session.commit()
    assert _records(session_factory) == before
