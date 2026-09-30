"""Durable publisher-process orchestration; API history never calls transport.

Reservations do not expire. A crash/lost response cannot prove a write did not
happen. Explicit reconciliation fences the old process and reads exact write
identity before releasing a target; absence never authorizes another POST.
"""

from __future__ import annotations

import hashlib
import re
import uuid

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from . import models as m
from .github_publication import (
    GitHubPublisher,
    PublicationError,
    _marker,
    _positive_id,
    _report_text,
    _repository,
    _sha,
)
from .github_publication_schemas import (
    PublicationScopeError,
    publication_projection,
    publication_revision_identity,
    publication_scope,
)
from .github_snapshot import report_snapshot

_BOUNDARY_ERRORS = (
    RuntimeError,
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    OSError,
    SQLAlchemyError,
)

_TERMINAL = {"created", "updated", "unchanged", "stale", "failed"}
_SAFE_ERROR_CODES = {
    "github_error",
    "invalid_sha",
    "invalid_repository",
    "invalid_project",
    "invalid_publisher",
    "github_http_error",
    "github_response_limit",
    "github_transport_error",
    "github_invalid_json",
    "actor_not_verified",
    "actor_mismatch",
    "repository_mismatch",
    "pr_not_open",
    "invalid_pr_metadata",
    "comment_actor_mismatch",
    "comment_changed",
    "invalid_comment_collection",
    "invalid_comment_identity",
    "comment_lookup_limit",
    "duplicate_owned_comments",
    "invalid_comment_metadata",
    "invalid_write_receipt",
    "write_actor_mismatch",
    "write_body_mismatch",
    "write_not_observed",
    "invalid_pull_number",
    "report_limit",
    "credential_in_report",
    "scope_changed",
    "publication_fenced",
    "report_changed",
    "evidence_expired",
    "write_budget_exhausted",
    "invalid_stale_body",
    "actor_changed",
    "reservation_corrupt",
    "target_busy",
    "internal_error",
    "write_not_reconciled",
    "stale_requires_repair",
    "interrupted_before_write",
}


def _error(message, code):
    return PublicationError(message, code=code)


def _lock_project(session, project_id):
    # Same first-statement lock order as retention; serializes SQLite and PG.
    changed = session.execute(
        update(m.Project).where(m.Project.id == project_id).values(id=m.Project.id)
    )
    if changed.rowcount != 1:
        raise _error("publication project is unavailable", "scope_changed")


def _latest_write(session, publication_id):
    return session.scalar(
        select(m.GitHubPublicationWrite)
        .where(m.GitHubPublicationWrite.publication_id == publication_id)
        .order_by(m.GitHubPublicationWrite.sequence.desc())
        .limit(1)
    )


def _scope(session, publication_id):
    row = session.get(m.GitHubPublication, publication_id)
    if row is None:
        raise _error("publication not found", "scope_changed")
    try:
        target, run = publication_scope(session, row)
    except PublicationScopeError:
        raise _error(
            "publication reservation is inconsistent", "reservation_corrupt"
        ) from None
    return row, target, run


def _read(factory, publication_id):
    try:
        with factory() as session:
            row, _, _ = _scope(session, publication_id)
            return publication_projection(session, row)
    except PublicationScopeError:
        raise _error(
            "publication history is inconsistent", "reservation_corrupt"
        ) from None
    except PublicationError:
        raise
    except _BOUNDARY_ERRORS:
        raise _error(
            "publication state unavailable; reconciliation required",
            "state_unavailable",
        ) from None


def _snapshot(session, run, repository):
    if (
        not isinstance(run.repository, str)
        or run.repository.casefold() != repository.casefold()
    ):
        raise _error(
            "run repository does not match publication target", "scope_changed"
        )
    _sha(run.commit_sha)
    return report_snapshot(session, run)


def _validation_issue(row, run, snapshot):
    if run.evidence_expired_at is not None:
        return "evidence_expired"
    if (
        snapshot["report_digest"] != row.report_digest
        or _sha(run.commit_sha) != row.tested_head
    ):
        return "report_changed"
    return None


def _validation_error(issue):
    return _error(
        "publication evidence has expired; neutral repair or new evidence is required"
        if issue == "evidence_expired"
        else "publication report changed; neutral repair or a new report is required",
        issue,
    )


def _prepare(
    factory,
    *,
    run_id,
    repository,
    pull_number,
    bot_login,
    source_run_id,
    source_run_attempt,
):
    _repository(repository)
    if not _positive_id(pull_number):
        raise _error("invalid pull request number", "invalid_pull_number")
    if (source_run_id is not None or source_run_attempt is not None) and (
        not isinstance(source_run_id, str)
        or not re.fullmatch(r"[1-9][0-9]{0,19}", source_run_id)
        or type(source_run_attempt) is not int
        or not 1 <= source_run_attempt <= 1000000
    ):
        raise _error(
            "source run and attempt must be a bounded positive pair", "invalid_source"
        )
    with factory() as session:
        run = session.get(m.Run, run_id)
        if run is None:
            raise _error("run not found", "scope_changed")
        project_id = run.project_id
    with factory.begin() as session:
        _lock_project(session, project_id)
        run = session.get(m.Run, run_id)
        if run is None or run.project_id != project_id:
            raise _error("run not found", "scope_changed")
        snapshot = _snapshot(session, run, repository)
        revision_identity = publication_revision_identity(snapshot)
        target = session.scalar(
            select(m.GitHubPublicationTarget).where(
                m.GitHubPublicationTarget.project_id == project_id,
                m.GitHubPublicationTarget.repository == repository.lower(),
                m.GitHubPublicationTarget.pull_number == pull_number,
            )
        )
        if target is None:
            target = m.GitHubPublicationTarget(
                project_id=project_id,
                repository=repository.lower(),
                pull_number=pull_number,
            )
            session.add(target)
            session.flush()
        if target.active_publication_id:
            active, active_target, _ = _scope(session, target.active_publication_id)
            if active_target.id != target.id or active.project_id != project_id:
                raise _error(
                    "publication reservation is inconsistent", "reservation_corrupt"
                )
        row = m.GitHubPublication(
            target_id=target.id,
            project_id=project_id,
            run_id=run_id,
            publisher_id=str(uuid.uuid4()),
            actor_kind="publisher_process",
            tested_head=_sha(run.commit_sha),
            report_digest=snapshot["report_digest"],
            **revision_identity,
            bot_login=bot_login,
            source_run_id=source_run_id,
            source_run_attempt=source_run_attempt,
            source_verification="unverified" if source_run_id else "not_supplied",
            status="active",
        )
        session.add(row)
        session.flush()
        if target.active_publication_id:
            row.status, row.error_code, row.completed_at = (
                "failed",
                "target_busy",
                m.utcnow(),
            )
        elif run.evidence_expired_at is not None:
            row.status, row.error_code, row.completed_at = (
                "failed",
                "evidence_expired",
                m.utcnow(),
            )
        else:
            target.active_publication_id = row.id
        publication_id = row.id
    return publication_id, project_id, snapshot


class _Hooks:
    def __init__(
        self,
        factory,
        publication_id,
        project_id,
        *,
        expected_status="active",
        expected_previous_write_id=None,
    ):
        self.factory, self.publication_id, self.project_id = (
            factory,
            publication_id,
            project_id,
        )
        self.expected_status = expected_status
        self.expected_previous_write_id = expected_previous_write_id
        self.confirmed_write_id = None

    def _owned(self, session):
        _lock_project(session, self.project_id)
        row, target, run = _scope(session, self.publication_id)
        if target.active_publication_id != row.id or row.status != self.expected_status:
            raise _error(
                "publication was fenced; reconcile its durable receipt",
                "publication_fenced",
            )
        return row, target, run

    def actor_verified(self, bot_user_id):
        with self.factory.begin() as session:
            row, _, _ = self._owned(session)
            if row.bot_user_id is not None and row.bot_user_id != bot_user_id:
                raise _error("authenticated bot identity changed", "actor_changed")
            row.bot_user_id, row.actor_verification, row.actor_verified_at = (
                bot_user_id,
                "verified",
                m.utcnow(),
            )

    def observe(self, current_head, comment_id):
        with self.factory.begin() as session:
            row, _, _ = self._owned(session)
            row.current_head, row.comment_id = _sha(current_head), comment_id

    def validation_issue(self):
        with self.factory.begin() as session:
            row, target, run = self._owned(session)
            return _validation_issue(
                row, run, _snapshot(session, run, target.repository)
            )

    def prepare_write(
        self, *, method, comment_id, body, tested_head, current_head, purpose
    ):
        with self.factory.begin() as session:
            row, target, run = self._owned(session)
            if row.actor_verification != "verified" or not _positive_id(
                row.bot_user_id
            ):
                raise _error(
                    "authenticated GitHub identity could not be verified",
                    "actor_not_verified",
                )
            snapshot = _snapshot(session, run, target.repository)
            marker = _marker(row.project_id)
            if purpose == "report":
                if run.evidence_expired_at is not None:
                    raise _error("publication evidence has expired", "evidence_expired")
                if (
                    snapshot["report_digest"] != row.report_digest
                    or _sha(run.commit_sha) != row.tested_head
                ):
                    raise _error(
                        "publication report changed before write", "report_changed"
                    )
                if body != GitHubPublisher._body(
                    marker,
                    row.tested_head,
                    _report_text(snapshot["markdown"], row.report_digest),
                ):
                    raise _error(
                        "publication report changed before write", "report_changed"
                    )
            elif purpose == "stale":
                # Neutral stale text is constructed here; report data cannot opt in.
                if (
                    method != "PATCH"
                    or not _positive_id(comment_id)
                    or body
                    != GitHubPublisher._body(
                        marker, _sha(tested_head), "", _sha(current_head)
                    )
                ):
                    raise _error(
                        "invalid neutral stale publication", "invalid_stale_body"
                    )
            else:
                raise _error("invalid neutral stale publication", "invalid_stale_body")
            previous = _latest_write(session, row.id)
            if self.expected_previous_write_id is not None and (
                previous is None
                or previous.id != self.expected_previous_write_id
                or previous.state != "observed"
                or previous.purpose != "report"
            ):
                raise _error(
                    "publication was fenced; reconcile its durable receipt",
                    "publication_fenced",
                )
            sequence = previous.sequence + 1 if previous else 1
            if sequence > 2 or (previous and previous.state != "observed"):
                raise _error(
                    "publication write budget exhausted; reconcile before retrying",
                    "write_budget_exhausted",
                )
            # Exact unique marker prevents a pre-existing body proving a later write.
            header, separator, report = body.partition(" -->\n")
            head_line, separator2, report = report.partition(" -->\n")
            if not separator or not separator2:
                raise _error("invalid neutral stale publication", "invalid_stale_body")
            body = (
                header
                + separator
                + head_line
                + separator2
                + f"<!-- loose-thread:write:{row.id}:{sequence}:{row.report_digest} -->\n"
                + report
            )
            write = m.GitHubPublicationWrite(
                publication_id=row.id,
                sequence=sequence,
                method=method,
                purpose=purpose,
                tested_head=_sha(tested_head),
                current_head=_sha(current_head),
                comment_id=comment_id,
                body_digest=hashlib.sha256(body.encode()).hexdigest(),
                revalidated_report_digest=snapshot["report_digest"],
                state="dispatching",
            )
            session.add(write)
            row.current_head, row.comment_id = current_head, comment_id
        return body

    def confirm_write(self, *, comment_id, body):
        with self.factory.begin() as session:
            row, _, _ = self._owned(session)
            write = _latest_write(session, row.id)
            if (
                write is None
                or write.body_digest != hashlib.sha256(body.encode()).hexdigest()
                or (write.comment_id is not None and write.comment_id != comment_id)
            ):
                raise _error(
                    "publication receipt does not match write intent",
                    "invalid_write_receipt",
                )
            write.comment_id, write.state, write.completed_at = (
                comment_id,
                "observed",
                m.utcnow(),
            )
            row.comment_id = comment_id
            self.confirmed_write_id = write.id

    def finish(self, result):
        with self.factory.begin() as session:
            row, target, run = self._owned(session)
            # A no-op and read-only reconciliation are publication boundaries too.
            # Preserve observed writes, but never present an obsolete projection
            # as a currently valid created/updated/unchanged report.
            snapshot = _snapshot(session, run, target.repository)
            issue = _validation_issue(row, run, snapshot)
            if result.status in {"created", "updated", "unchanged"} and issue:
                raise _validation_error(issue)
            latest = _latest_write(session, row.id)
            if latest is not None and (
                latest.id != self.confirmed_write_id or latest.state != "observed"
            ):
                raise _error(
                    "publication was fenced; reconcile its durable receipt",
                    "publication_fenced",
                )
            row.status, row.comment_id, row.current_head = (
                result.status,
                result.comment_id,
                result.current_head,
            )
            row.error_code, row.completed_at = None, m.utcnow()
            if self.expected_status == "reconciling":
                row.reconciled_at = m.utcnow()
            target.active_publication_id = None


def _failed(factory, publication_id, project_id, exc, *, expected_status="active"):
    code = (
        exc.code
        if isinstance(exc, PublicationError) and exc.code in _SAFE_ERROR_CODES
        else "internal_error"
    )
    with factory.begin() as session:
        _lock_project(session, project_id)
        row, target, _ = _scope(session, publication_id)
        if target.active_publication_id != row.id or row.status != expected_status:
            return
        write = _latest_write(session, row.id)
        row.error_code = code
        if write:
            row.status = "uncertain"
            if write.state != "observed":
                write.state, write.error_code = "uncertain", code
        else:
            row.status, row.completed_at = "failed", m.utcnow()
            target.active_publication_id = None


def durable_publish(
    factory,
    *,
    run_id: str,
    repository: str,
    pull_number: int,
    token: str,
    bot_login: str = "github-actions[bot]",
    source_run_id: str | None = None,
    source_run_attempt: int | None = None,
    transport=None,
) -> dict:
    publisher = GitHubPublisher(token, bot_login=bot_login, transport=transport)
    try:
        publication_id, project_id, snapshot = _prepare(
            factory,
            run_id=run_id,
            repository=repository,
            pull_number=pull_number,
            bot_login=bot_login,
            source_run_id=source_run_id,
            source_run_attempt=source_run_attempt,
        )
        receipt = _read(factory, publication_id)
        if receipt["status"] != "active":
            return receipt
        hooks = _Hooks(factory, publication_id, project_id)
        try:
            result = publisher.publish(
                repository=repository,
                pull_number=pull_number,
                project=project_id,
                tested_head=receipt["tested_head"],
                report=snapshot["markdown"],
                report_digest=receipt["report_digest"],
                hooks=hooks,
            )
            hooks.finish(result)
        except _BOUNDARY_ERRORS as exc:
            _failed(factory, publication_id, project_id, exc)
        return _read(factory, publication_id)
    except PublicationError:
        raise
    except _BOUNDARY_ERRORS:
        raise _error(
            "publication state unavailable; reconciliation required",
            "state_unavailable",
        ) from None
    finally:
        publisher.close()


def _fence_reconciliation(factory, publication_id):
    with factory() as session:
        row, _, _ = _scope(session, publication_id)
        project_id = row.project_id
    with factory.begin() as session:
        _lock_project(session, project_id)
        row, target, _ = _scope(session, publication_id)
        if target.active_publication_id != row.id:
            if row.status not in _TERMINAL:
                raise _error(
                    "publication reservation is inconsistent", "reservation_corrupt"
                )
            return project_id, False
        row.status, row.error_code = "reconciling", None
        if _latest_write(session, row.id) is None:
            # The committed fence prevents the interrupted process starting a write.
            row.status, row.error_code = "failed", "interrupted_before_write"
            row.completed_at, row.reconciled_at = m.utcnow(), m.utcnow()
            target.active_publication_id = None
            return project_id, False
    return project_id, True


def _observe_intent(publisher, receipt, write):
    marker = _marker(receipt["project_id"])
    current = publisher._head(receipt["repository"], receipt["pull_number"])
    existing = publisher._existing(
        receipt["repository"], receipt["pull_number"], marker
    )
    current = publisher._head(receipt["repository"], receipt["pull_number"])
    expected_tag = f"<!-- loose-thread:write:{receipt['publication_id']}:{write['sequence']}:{receipt['report_digest']} -->\n"
    expected_start = (
        marker
        + "\n<!-- loose-thread:head:"
        + write["tested_head"]
        + " -->\n"
        + expected_tag
    )
    if (
        existing is None
        or not existing["body"].startswith(expected_start)
        or hashlib.sha256(existing["body"].encode()).hexdigest() != write["body_digest"]
        or (write["comment_id"] is not None and existing["id"] != write["comment_id"])
    ):
        raise _error(
            "write remains uncertain; absence does not prove no in-flight write",
            "write_not_reconciled",
        )
    return existing, current


def reconcile_publication(
    factory,
    *,
    publication_id: str,
    token: str,
    repair_stale: bool = False,
    transport=None,
) -> dict:
    if type(repair_stale) is not bool:
        raise _error(
            "stale repair must be an explicit boolean option", "invalid_repair_option"
        )
    receipt = _read(factory, publication_id)
    publisher = GitHubPublisher(
        token, bot_login=receipt["bot_login"], transport=transport
    )
    try:
        project_id, needs_lookup = _fence_reconciliation(factory, publication_id)
        if not needs_lookup:
            return _read(factory, publication_id)
        hooks = _Hooks(
            factory, publication_id, project_id, expected_status="reconciling"
        )
        try:
            hooks.actor_verified(publisher.verify_identity())
            receipt = _read(factory, publication_id)
            write = receipt["writes"][-1]
            existing, current = _observe_intent(publisher, receipt, write)
            hooks.confirm_write(comment_id=existing["id"], body=existing["body"])
            hooks.observe(current, existing["id"])
            issue = hooks.validation_issue()
            if write["purpose"] == "report" and (
                current != write["tested_head"] or issue
            ):
                if not repair_stale:
                    if issue:
                        raise _validation_error(issue)
                    raise _error(
                        "observed report is stale; explicit neutral repair required",
                        "stale_requires_repair",
                    )
                # Repeat trusted lookup immediately before repair; never replace a
                # newer/mismatched body from another publisher or human operator.
                existing, current = _observe_intent(publisher, receipt, write)
                issue = hooks.validation_issue()
                if current == write["tested_head"] and issue is None:
                    status = "created" if write["method"] == "POST" else "updated"
                else:
                    hooks.expected_previous_write_id = write["write_id"]
                    publisher._write(
                        repository=receipt["repository"],
                        pull_number=receipt["pull_number"],
                        marker=_marker(project_id),
                        existing=existing,
                        body=publisher._body(
                            _marker(project_id), write["tested_head"], "", current
                        ),
                        tested_head=write["tested_head"],
                        current_head=current,
                        purpose="stale",
                        hooks=hooks,
                    )
                    current = publisher._head(
                        receipt["repository"], receipt["pull_number"]
                    )
                    status = "stale"
            else:
                status = (
                    "stale"
                    if write["purpose"] == "stale"
                    else ("created" if write["method"] == "POST" else "updated")
                )
            from .github_publication import PublicationResult

            hooks.finish(
                PublicationResult(
                    status, existing["id"], receipt["tested_head"], current
                )
            )
        except _BOUNDARY_ERRORS as exc:
            _failed(
                factory, publication_id, project_id, exc, expected_status="reconciling"
            )
        return _read(factory, publication_id)
    except PublicationError:
        raise
    except _BOUNDARY_ERRORS:
        raise _error(
            "publication state unavailable; reconciliation required",
            "state_unavailable",
        ) from None
    finally:
        publisher.close()
