"""Small real artifacts exercise retention budgets without allocating large data."""

import gc
import weakref
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from failurelens import evidence_validation, publication_validity
from failurelens import models as m
from failurelens.config import get_settings
from failurelens.evidence_validation import EvidenceReadContext
from failurelens.publication_validity import PublicationContext
from failurelens.schemas import IngestionRequest
from failurelens.schemas import TestObservation as Observation
from failurelens.service import analyze_and_persist, ingest_normalized
from failurelens.storage import StorageError
from sqlalchemy import select
from test_current_publication_validity import _case, _known_flake


@pytest.fixture
def byte_sources(session):
    sources = []
    for index in range(3):
        _, _, evidence = _case(session, slug=f"cache-{index}")
        derivative = evidence.derivative
        path = Path(get_settings().artifact_root) / derivative.storage_path
        sources.append((derivative, path, path.read_bytes()))
    assert len({path for _, path, _ in sources}) == 3
    assert sum(len(content) for _, _, content in sources) < 10_000
    return sources


def _reader(monkeypatch):
    reader = Mock(wraps=evidence_validation.read_stored_bytes)
    monkeypatch.setattr(evidence_validation, "read_stored_bytes", reader)
    return reader


def test_byte_entry_limit_promotes_hits_and_rereads_evicted_content(
    byte_sources, monkeypatch
):
    monkeypatch.setattr(
        evidence_validation, "MAX_EVIDENCE_CACHE_ENTRIES", 2, raising=False
    )
    reader = _reader(monkeypatch)
    context = EvidenceReadContext()
    for index in (0, 1, 0, 2, 0):
        derivative, _, content = byte_sources[index]
        assert context.read(derivative, context.settings) == content
    assert reader.call_count == 3
    assert context.read(byte_sources[1][0], context.settings) == byte_sources[1][2]
    assert reader.call_count == 4
    assert len(context._bytes) <= 2


def test_byte_budget_evicts_even_below_entry_limit(byte_sources, monkeypatch):
    first, second = byte_sources[:2]
    budget = len(first[2]) + len(second[2]) - 1
    monkeypatch.setattr(
        evidence_validation, "MAX_EVIDENCE_CACHE_BYTES", budget, raising=False
    )
    reader = _reader(monkeypatch)
    context = EvidenceReadContext()
    for derivative, _, content in (first, second, first):
        assert context.read(derivative, context.settings) == content
        assert sum(len(value) for value in context._bytes.values()) <= budget
    assert reader.call_count == 3


@pytest.mark.parametrize("oversized", [False, True])
def test_exact_budget_caches_and_oversized_valid_content_bypasses_cache(
    byte_sources, monkeypatch, oversized
):
    derivative, _, content = byte_sources[0]
    monkeypatch.setattr(
        evidence_validation,
        "MAX_EVIDENCE_CACHE_BYTES",
        len(content) - int(oversized),
        raising=False,
    )
    reader = _reader(monkeypatch)
    context = EvidenceReadContext()
    assert context.read(derivative, context.settings) == content
    assert context.read(derivative, context.settings) == content
    assert reader.call_count == (2 if oversized else 1)
    assert len(context._bytes) == (0 if oversized else 1)


def test_evicted_bytes_are_revalidated_after_corruption(byte_sources, monkeypatch):
    monkeypatch.setattr(
        evidence_validation, "MAX_EVIDENCE_CACHE_ENTRIES", 1, raising=False
    )
    context = EvidenceReadContext()
    for derivative, _, content in byte_sources[:2]:
        assert context.read(derivative, context.settings) == content
    derivative, path, content = byte_sources[0]
    path.write_bytes(b"x" * len(content))
    with pytest.raises(StorageError):
        context.read(derivative, context.settings)


@pytest.mark.parametrize("error_type", [StorageError, OSError])
def test_failed_reads_release_reader_frames_and_can_recover(
    byte_sources, monkeypatch, error_type
):
    derivative, _, content = byte_sources[0]
    real_read = evidence_validation.read_stored_bytes
    retained = []

    class ReaderFrameSentinel:
        pass

    def transient_failure(**kwargs):
        if not retained:
            sentinel = ReaderFrameSentinel()
            retained.append(weakref.ref(sentinel))
            if error_type is StorageError:
                raise StorageError("synthetic_read_failure", "Synthetic read failure")
            raise OSError("Synthetic read failure")
        return real_read(**kwargs)

    monkeypatch.setattr(evidence_validation, "read_stored_bytes", transient_failure)
    context = EvidenceReadContext()

    def failed_attempt():
        with pytest.raises(error_type):
            context.read(derivative, context.settings)

    failed_attempt()
    gc.collect()
    assert retained[0]() is None
    assert not context._bytes
    assert context.read(derivative, context.settings) == content


def _three_current_analyses(session):
    project, earlier, analysis, _ = _known_flake(session)
    original = analysis.failure.execution
    run = ingest_normalized(
        session,
        project,
        IngestionRequest(
            external_id="history-cache-current",
            repository=earlier.repository,
            commit_sha=earlier.commit_sha,
            branch=earlier.branch,
            run_scope=earlier.run_scope,
            environment=earlier.environment,
            worker_count=earlier.worker_count,
            shard_count=earlier.shard_count,
            timezone=earlier.timezone,
            observations=[
                Observation(
                    test_identity=original.test_identity,
                    suite=original.suite,
                    source_path=original.source_path,
                    parameterization=original.parameterization,
                    browser=original.browser,
                    attempt=index,
                    outcome=m.Outcome.failed,
                    message=analysis.failure.message,
                    exception_type=analysis.failure.exception_type,
                    details={"measurement_sequence": 10 + index},
                )
                for index in range(3)
            ],
        ),
    )
    run.created_at = run.started_at = earlier.created_at + timedelta(days=1)
    session.commit()
    failures = list(
        session.scalars(
            select(m.Failure).where(m.Failure.run_id == run.id).order_by(m.Failure.id)
        )
    )
    analyses = [analyze_and_persist(session, failure) for failure in failures]
    assert all(row.category is m.Category.known_flake for row in analyses)
    return analyses


def test_history_lru_evicts_and_recomputes_exact_failure_scope(session, monkeypatch):
    analyses = _three_current_analyses(session)
    monkeypatch.setattr(
        publication_validity, "MAX_HISTORY_CACHE_ENTRIES", 2, raising=False
    )
    actual = publication_validity.history_context_for_failure
    calls = []

    def history(current_session, failure):
        result = actual(current_session, failure)
        calls.append(
            (failure.id, result["history_cutoff"], result["history_input_digest"])
        )
        return result

    monkeypatch.setattr(publication_validity, "history_context_for_failure", history)
    context = PublicationContext(session)
    for index in (0, 1, 0, 2, 0, 1):
        assert context.analysis(analyses[index]).valid
    assert len(calls) == 4
    assert calls[1] == calls[3]
    assert len(context._history) <= 2


@pytest.mark.parametrize("review_limit", [0, 1])
def test_oversized_history_remains_complete_and_uncached(
    session, monkeypatch, review_limit
):
    _, _, analysis, _ = _known_flake(session, cite_prior=True)
    monkeypatch.setattr(
        publication_validity,
        "MAX_HISTORY_CACHE_REVIEW_IDS",
        review_limit,
        raising=False,
    )
    actual = publication_validity.history_context_for_failure
    results = []

    def history(current_session, failure):
        result = actual(current_session, failure)
        assert len(result["review_event_ids"]) == 1
        results.append(result)
        return result

    monkeypatch.setattr(publication_validity, "history_context_for_failure", history)
    context = PublicationContext(session)
    assert context.analysis(analysis).valid
    assert context.analysis(analysis).valid
    assert len(results) == (2 if review_limit == 0 else 1)
    assert len(context._history) == (0 if review_limit == 0 else 1)
    assert all(result == results[0] for result in results)
