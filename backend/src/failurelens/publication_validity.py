"""Current, read-only publication checks; recorded decisions remain immutable."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session, selectinload

from .evidence_validation import (
    EvidenceReadContext,
    EvidenceValidationSet,
    persisted_analysis_is_publication_validated,
    validate_evidence_records,
    validate_inspectable_evidence_records,
    validate_scoped_evidence_records,
)
from .history import history_context_for_failure
from .models import (
    Analysis,
    Category,
    Evidence,
    Failure,
    ReviewEvent,
    Run,
    RunInput,
    TestExecution,
)

MAX_HISTORY_CACHE_ENTRIES = 16
MAX_HISTORY_CACHE_REVIEW_IDS = 256


@dataclass(frozen=True)
class CurrentAnalysisValidity:
    valid: bool
    reasons: tuple[str, ...] = ()


class PublicationContext:
    """One request/transaction's bytes and history, never a persistent safe flag.

    Only immutable bytes and an exact failure's original-cutoff history are reused.
    Every use independently checks the requested scope and mutable evidence policy.
    Start a fresh context after acquiring the review transaction's project lock.
    """

    def __init__(self, session: Session):
        self.session = session
        self._transaction = session.get_transaction()
        self.read_context = EvidenceReadContext()
        self._history: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()

    def require_session(self, session: Session | None) -> None:
        if session is not self.session:
            raise ValueError("publication context belongs to another session")
        current = session.get_transaction()
        if self._transaction is not None and current is not self._transaction:
            raise ValueError("publication context belongs to an earlier transaction")
        self._transaction = current

    def _require_rows(
        self,
        *rows: Analysis | Failure | Evidence | Run | RunInput | TestExecution | None,
    ) -> None:
        for row in rows:
            if row is not None:
                self.require_session(object_session(row))

    def failure_evidence(
        self, failure: Failure, rows: list[Evidence]
    ) -> EvidenceValidationSet:
        self._require_rows(failure, *rows)
        return validate_evidence_records(failure, rows, read_context=self.read_context)

    def scoped_evidence(
        self,
        run: Run,
        rows: list[Evidence],
        *,
        execution: TestExecution | None = None,
        run_input: RunInput | None = None,
    ) -> EvidenceValidationSet:
        self._require_rows(run, execution, run_input, *rows)
        return validate_scoped_evidence_records(
            run,
            rows,
            execution=execution,
            run_input=run_input,
            read_context=self.read_context,
        )

    def inspectable_evidence(
        self, run: Run, rows: list[Evidence]
    ) -> EvidenceValidationSet:
        self._require_rows(run, *rows)
        return validate_inspectable_evidence_records(
            run, rows, read_context=self.read_context
        )

    def inspectable_references(self, project_id: str, ids: set[str]) -> set[str]:
        """Resolve human citations in their own run; refresh preloaded policy rows."""
        found: set[str] = set()
        if not ids:
            return found
        rows = self.session.scalars(
            select(Evidence)
            .where(Evidence.id.in_(sorted(ids)))
            .options(
                selectinload(Evidence.artifact),
                selectinload(Evidence.derivative),
                selectinload(Evidence.run_input),
                selectinload(Evidence.execution),
            )
            .execution_options(populate_existing=True)
        ).all()
        for row in rows:
            if row.project_id != project_id:
                continue
            run = self.session.get(Run, row.run_id, populate_existing=True)
            if run is not None and run.project_id == project_id:
                found.update(self.inspectable_evidence(run, [row]).accepted_ids)
        return found

    def _review_citations_available(self, project_id: str, ids: list[str]) -> bool:
        events = self.session.scalars(
            select(ReviewEvent)
            .where(ReviewEvent.id.in_(ids))
            .options(selectinload(ReviewEvent.analysis))
            .execution_options(populate_existing=True)
        ).all()
        if len(events) != len(set(ids)):
            return False
        cited: set[str] = set()
        for event in events:
            cited.update(
                event.supporting_evidence_ids + event.contradictory_evidence_ids
            )
            # A category correction is an independent human judgment. An accept
            # endorses the machine analysis's citations, without recursively
            # using that earlier analysis's history as a new classifier input.
            if event.decision == "accept":
                cited.update(
                    event.analysis.supporting_evidence_ids
                    + event.analysis.contradictory_evidence_ids
                )
        return cited.issubset(self.inspectable_references(project_id, cited))

    def analysis(self, analysis: Analysis) -> CurrentAnalysisValidity:
        # Local import keeps evidence selection in the ingestion service without
        # introducing an import cycle in its schema projection.
        from .service import select_failure_evidence

        self._require_rows(analysis)
        failure = analysis.failure
        if failure.run.evidence_expired_at is not None:
            return CurrentAnalysisValidity(False, ("evidence_expired",))
        if not persisted_analysis_is_publication_validated(analysis):
            return CurrentAnalysisValidity(
                False, ("legacy_analysis_not_publication_validated",)
            )
        rows = select_failure_evidence(self.session, failure)
        accepted = set(self.failure_evidence(failure, rows).accepted_ids)
        cited = set(
            analysis.supporting_evidence_ids + analysis.contradictory_evidence_ids
        )
        # Original accepted inputs influenced the decision even when they were
        # not selected as a claim citation. Losing them invalidates its scope.
        original = set(
            (analysis.validation_results or {}).get("accepted_evidence_ids", [])
        )
        if not (cited | original).issubset(accepted) or (
            analysis.category is not Category.insufficient_evidence
            and not analysis.supporting_evidence_ids
        ):
            return CurrentAnalysisValidity(False, ("current_evidence_unavailable",))
        if analysis.category is Category.known_flake:
            run, execution = failure.run, failure.execution
            key = (
                failure.id,
                failure.project_id,
                failure.run_id,
                failure.execution_id,
                failure.strict_fingerprint,
                run.started_at,
                run.created_at,
                run.repository,
                run.framework,
                run.branch,
                run.environment,
                run.worker_count,
                run.shard_count,
                run.timezone,
                execution.test_identity,
                execution.suite,
                execution.source_path,
                execution.parameterization,
                execution.browser,
            )
            historical = self._history.get(key)
            if historical is None:
                historical = history_context_for_failure(self.session, failure)
                # The computed history remains complete. Large reference sets
                # bypass retention rather than truncating publication inputs.
                if len(historical["review_event_ids"]) <= MAX_HISTORY_CACHE_REVIEW_IDS:
                    while len(self._history) >= MAX_HISTORY_CACHE_ENTRIES:
                        self._history.popitem(last=False)
                    self._history[key] = historical
            else:
                self._history.move_to_end(key)
            provenance = analysis.provenance or {}
            if (
                historical["history_eligible_for_reassurance"] is not True
                or historical["history_cutoff"] != provenance.get("history_cutoff")
                or historical["policy_version"]
                != provenance.get("history_policy_version")
                or historical["history_input_digest"]
                != provenance.get("history_input_digest")
                or not self._review_citations_available(
                    failure.project_id, historical["review_event_ids"]
                )
            ):
                return CurrentAnalysisValidity(
                    False, ("historical_support_unavailable",)
                )
        return CurrentAnalysisValidity(True)
