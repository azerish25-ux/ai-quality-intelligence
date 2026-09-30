"""Database-backed governance queries: filter before pagination, never a recent window."""

from __future__ import annotations

from sqlalchemy import String, case, cast, func, or_, select
from sqlalchemy.orm import Session

from .models import Analysis, AuditEvent, Failure, ReviewEvent, Run, TestExecution
from .schemas import ReviewQueueItem, ReviewQueuePage

RESOLVED = ("accept", "reject", "category_correction")


def review_queue_page(
    session: Session,
    project_id: str,
    *,
    status: str = "pending",
    category: str | None = None,
    search: str = "",
    sort: str = "newest",
    limit: int = 25,
    offset: int = 0,
) -> ReviewQueuePage:
    latest = (
        select(
            Analysis.failure_id.label("failure_id"),
            func.max(Analysis.revision).label("revision"),
        )
        .join(Failure, Failure.id == Analysis.failure_id)
        .where(Failure.project_id == project_id)
        .group_by(Analysis.failure_id)
        .subquery()
    )
    last_review = (
        select(
            ReviewEvent.analysis_id.label("analysis_id"),
            func.max(ReviewEvent.version).label("version"),
        )
        .join(Analysis, Analysis.id == ReviewEvent.analysis_id)
        .join(Failure, Failure.id == Analysis.failure_id)
        .where(Failure.project_id == project_id)
        .group_by(ReviewEvent.analysis_id)
        .subquery()
    )
    query = (
        select(
            Analysis,
            Failure.run_id,
            TestExecution.test_identity,
            ReviewEvent.version,
            ReviewEvent.decision,
            Run.evidence_expired_at,
        )
        .join(
            latest,
            (latest.c.failure_id == Analysis.failure_id)
            & (latest.c.revision == Analysis.revision),
        )
        .join(Failure, Failure.id == Analysis.failure_id)
        .join(Run, Run.id == Failure.run_id)
        .join(TestExecution, TestExecution.id == Failure.execution_id)
        .outerjoin(last_review, last_review.c.analysis_id == Analysis.id)
        .outerjoin(
            ReviewEvent,
            (ReviewEvent.analysis_id == Analysis.id)
            & (ReviewEvent.version == last_review.c.version),
        )
        .where(Failure.project_id == project_id)
    )
    if status == "pending":
        query = query.where(
            or_(ReviewEvent.decision.is_(None), ~ReviewEvent.decision.in_(RESOLVED))
        )
    elif status == "reviewed":
        query = query.where(ReviewEvent.decision.in_(RESOLVED))
    elif status == "needs_more_evidence":
        query = query.where(ReviewEvent.decision == "needs_more_evidence")
    elif status != "all":
        raise ValueError("unsupported review status")
    if category:
        query = query.where(Analysis.category == category)
    if search.strip():
        # autoescape means '%' and '_' are literal search text, not arbitrary wildcards.
        query = query.where(
            or_(
                *[
                    func.lower(cast(column, String)).contains(
                        search.strip().lower(), autoescape=True
                    )
                    for column in (
                        TestExecution.test_identity,
                        Analysis.summary,
                        Analysis.category,
                        Analysis.severity,
                        func.coalesce(ReviewEvent.decision, "unreviewed"),
                    )
                ]
            )
        )
    total = (
        session.scalar(
            select(func.count()).select_from(query.order_by(None).subquery())
        )
        or 0
    )
    order = {
        "newest": (Analysis.created_at.desc(), Analysis.id.desc()),
        "oldest": (Analysis.created_at.asc(), Analysis.id.asc()),
        "severity": (
            case(
                {"critical": 0, "high": 1, "medium": 2, "low": 3},
                value=Analysis.severity,
                else_=4,
            ),
            Analysis.created_at.desc(),
            Analysis.id.desc(),
        ),
        "test": (TestExecution.test_identity.asc(), Analysis.id.asc()),
    }.get(sort)
    if order is None:
        raise ValueError("unsupported review sort")
    rows = session.execute(query.order_by(*order).offset(offset).limit(limit)).all()
    return ReviewQueuePage(
        items=[
            ReviewQueueItem(
                analysis_id=a.id,
                failure_id=a.failure_id,
                run_id=run_id,
                project_id=project_id,
                test_identity=identity,
                category=a.category,
                severity=a.severity,
                summary="Evidence expired; recorded diagnosis is historical."
                if expired
                else a.summary,
                evidence_completeness="expired" if expired else a.evidence_completeness,
                policy_flags=sorted(
                    {*a.policy_flags, *(["evidence_expired"] if expired else [])}
                ),
                latest_review_version=version or 0,
                latest_review_decision=decision,
                created_at=a.created_at,
            )
            for a, run_id, identity, version, decision, expired in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def audit_query(
    project_id: str,
    *,
    action: str = "",
    outcome: str = "",
    search: str = "",
    sort: str = "newest",
):
    query = select(AuditEvent).where(AuditEvent.project_id == project_id)
    if action:
        query = query.where(AuditEvent.action == action)
    if outcome:
        query = query.where(AuditEvent.outcome == outcome)
    if search.strip():
        query = query.where(
            or_(
                *[
                    func.lower(cast(column, String)).contains(
                        search.strip().lower(), autoescape=True
                    )
                    for column in (
                        AuditEvent.actor_display,
                        AuditEvent.actor_kind,
                        AuditEvent.action,
                        AuditEvent.resource_type,
                        AuditEvent.resource_id,
                        AuditEvent.reason,
                    )
                ]
            )
        )
    if sort not in {"newest", "oldest"}:
        raise ValueError("unsupported audit sort")
    return query.order_by(
        AuditEvent.created_at.asc()
        if sort == "oldest"
        else AuditEvent.created_at.desc(),
        AuditEvent.id.asc() if sort == "oldest" else AuditEvent.id.desc(),
    )
