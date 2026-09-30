"""Publisher-process GitHub transport. No analysis or HTTP API path calls it.

The durable service journals/fences every comment mutation through hooks. The
standalone class retains its compatibility surface, without claiming durability.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from .telemetry import instrument

_MAX_ID = 2**63 - 1
_transport_context = threading.local()
_WRITE_METADATA = re.compile(
    r"<!-- loose-thread:write:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):([12]):([0-9a-f]{64}) -->\n"
)


class _PrivateTransportLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not getattr(_transport_context, "active", False)


_private_transport_logs = _PrivateTransportLogs()


class PublicationError(RuntimeError):
    """Fixed safe operational error; never include responses or credentials."""

    def __init__(self, message: str, *, code: str = "github_error"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PublicationResult:
    status: str
    comment_id: int | None
    tested_head: str
    current_head: str


def _sha(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise PublicationError(
            "an exact lowercase 40-character commit SHA is required", code="invalid_sha"
        )
    return value


def _repository(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 240
        or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value)
        or any(part in {".", ".."} for part in value.split("/"))
    ):
        raise PublicationError("invalid repository", code="invalid_repository")
    return value


def _positive_id(value) -> bool:
    return type(value) is int and 1 <= value <= _MAX_ID


def _marker(project: str) -> str:
    if not isinstance(project, str) or not project or len(project) > 240:
        raise PublicationError("invalid project scope", code="invalid_project")
    return (
        "<!-- loose-thread:publication:v1:"
        + hashlib.sha256(project.encode()).hexdigest()
        + " -->"
    )


def _report_text(report: str, report_digest: str | None) -> str:
    if report_digest is None:
        return report
    if not isinstance(report_digest, str) or not re.fullmatch(
        r"[0-9a-f]{64}", report_digest
    ):
        raise PublicationError("invalid report digest", code="invalid_report_digest")
    return f"<!-- loose-thread:report-digest:{report_digest} -->\n" + report


def _logical_body(body: str, marker: str) -> str:
    """Remove only our one strictly placed write-journal line, not report text."""
    header = re.match(
        re.escape(marker) + r"\n<!-- loose-thread:head:[0-9a-f]{40} -->\n", body
    )
    if not header:
        raise PublicationError(
            "malformed owned report metadata", code="invalid_comment_metadata"
        )
    rest = body[header.end() :]
    metadata = _WRITE_METADATA.match(rest)
    if metadata:
        rest = rest[metadata.end() :]
    return body[: header.end()] + rest


class GitHubPublisher:
    def __init__(
        self, token: str, *, bot_login: str = "github-actions[bot]", transport=None
    ):
        if (
            not isinstance(token, str)
            or not token
            or len(token) > 8192
            or not re.fullmatch(r"[\x21-\x7e]+", token)
            or not isinstance(bot_login, str)
            or len(bot_login) > 120
            or not re.fullmatch(r"[A-Za-z0-9_-]+\[bot\]", bot_login)
        ):
            raise PublicationError(
                "a token and explicit bot identity are required",
                code="invalid_publisher",
            )
        for name in (
            "httpx",
            "httpcore",
            "httpcore.connection",
            "httpcore.http11",
            "httpcore.http2",
            "httpcore.proxy",
            "httpcore.socks",
        ):
            transport_logger = logging.getLogger(name)
            if _private_transport_logs not in transport_logger.filters:
                transport_logger.addFilter(_private_transport_logs)
        self._credential = token
        self.bot_login = bot_login
        self.bot_user_id: int | None = None
        self.client = httpx.Client(
            base_url="https://api.github.com",
            timeout=20,
            follow_redirects=False,
            trust_env=False,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            transport=transport,
        )

    def close(self):
        active = getattr(_transport_context, "active", False)
        _transport_context.active = True
        try:
            self.client.close()
        finally:
            _transport_context.active = active

    def _request(self, method, path, **kwargs):
        active = getattr(_transport_context, "active", False)
        _transport_context.active = True
        try:
            try:
                with self.client.stream(method, path, **kwargs) as response:
                    if not 200 <= response.status_code < 300:
                        raise PublicationError(
                            f"GitHub {method} failed with HTTP {response.status_code}",
                            code="github_http_error",
                        )
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        if len(body) + len(chunk) > 8_000_000:
                            raise PublicationError(
                                "GitHub response exceeds bounded lookup limit",
                                code="github_response_limit",
                            )
                        body.extend(chunk)
            except httpx.HTTPError:
                raise PublicationError(
                    "GitHub transport failed; reconcile before retrying publication",
                    code="github_transport_error",
                ) from None
            try:
                return json.loads(body)
            except (ValueError, UnicodeError):
                raise PublicationError(
                    "GitHub returned invalid JSON", code="github_invalid_json"
                ) from None
        finally:
            _transport_context.active = active

    def verify_identity(self) -> int:
        # Fixed read-only query; never accept query text from an artifact/caller.
        viewer = self._request(
            "POST", "/graphql", json={"query": "query { viewer { login } }"}
        )
        if not isinstance(viewer, dict) or viewer.get("errors"):
            raise PublicationError(
                "authenticated GitHub identity could not be verified",
                code="actor_not_verified",
            )
        data = viewer.get("data")
        user = data.get("viewer") if isinstance(data, dict) else None
        if not isinstance(user, dict) or user.get("login") != self.bot_login:
            raise PublicationError(
                "authenticated GitHub identity is not the configured bot",
                code="actor_mismatch",
            )
        actor = self._request("GET", "/users/" + quote(self.bot_login, safe=""))
        if (
            not isinstance(actor, dict)
            or actor.get("login") != self.bot_login
            or actor.get("type") != "Bot"
            or not _positive_id(actor.get("id"))
        ):
            raise PublicationError(
                "configured GitHub identity is not a verified bot",
                code="actor_not_verified",
            )
        self.bot_user_id = actor["id"]
        return self.bot_user_id

    def _head(self, repo, number):
        pr = self._request("GET", f"/repos/{repo}/pulls/{number}")
        try:
            if pr["base"]["repo"]["full_name"].casefold() != repo.casefold():
                raise PublicationError(
                    "PR repository mismatch", code="repository_mismatch"
                )
            if pr["state"] != "open":
                raise PublicationError("PR is not open", code="pr_not_open")
            return _sha(pr["head"]["sha"])
        except (KeyError, TypeError, AttributeError):
            raise PublicationError(
                "incomplete trusted PR metadata", code="invalid_pr_metadata"
            ) from None

    def _owned(self, comment):
        owner = comment.get("user") if isinstance(comment, dict) else None
        if (
            not isinstance(owner, dict)
            or owner.get("login") != self.bot_login
            or owner.get("type") != "Bot"
        ):
            return False
        if owner.get("id") != self.bot_user_id or not _positive_id(owner.get("id")):
            raise PublicationError(
                "comment bot identity does not match authenticated bot",
                code="comment_actor_mismatch",
            )
        return True

    def _existing(self, repo, number, marker):
        found = []
        for page in range(1, 101):
            batch = self._request(
                "GET",
                f"/repos/{repo}/issues/{number}/comments",
                params={"per_page": 100, "page": page},
            )
            if not isinstance(batch, list) or len(batch) > 100:
                raise PublicationError(
                    "invalid comment collection", code="invalid_comment_collection"
                )
            for comment in batch:
                # A malformed item cannot establish absence: it could be the
                # existing owned comment with its body/author omitted or null.
                owner = comment.get("user") if isinstance(comment, dict) else None
                if (
                    not isinstance(comment, dict)
                    or not _positive_id(comment.get("id"))
                    or not isinstance(comment.get("body"), str)
                    or not isinstance(owner, dict)
                    or not isinstance(owner.get("login"), str)
                    or not owner["login"]
                    or len(owner["login"]) > 240
                    or not isinstance(owner.get("type"), str)
                    or owner["type"] not in {"User", "Bot", "Organization"}
                    or not _positive_id(owner.get("id"))
                ):
                    raise PublicationError(
                        "incomplete comment collection; no publication performed",
                        code="invalid_comment_collection",
                    )
                if comment["body"].startswith(marker + "\n") and self._owned(comment):
                    _logical_body(comment["body"], marker)
                    found.append(comment)
            if len(batch) < 100:
                break
        else:
            raise PublicationError(
                "comment pagination limit reached; no publication performed",
                code="comment_lookup_limit",
            )
        if len(found) > 1:
            raise PublicationError(
                "multiple owned report comments; manual reconciliation required",
                code="duplicate_owned_comments",
            )
        return found[0] if found else None

    @staticmethod
    def _body(marker, head, report, current=None):
        metadata = "<!-- loose-thread:head:" + head + " -->"
        if current is not None:
            explanation = (
                "The PR changed after these tests. Rerun analysis for the current head.\n"
                if head != current
                else "The stored evidence or report projection changed after this report was prepared. "
                "Revalidate evidence and rerun analysis before relying on this report.\n"
            )
            title = (
                "stale test evidence"
                if head != current
                else "report requires revalidation"
            )
            report = (
                f"## Loose Thread: {title}\n\nHOLD_FOR_REVIEW\n\n"
                f"Tested head: `{head}`\nCurrent PR head: `{current}`\n\n"
                + explanation
                + "This advisory does not approve a release or suppress failures.\n"
            )
        return marker + "\n" + metadata + "\n" + report

    def _write(
        self,
        *,
        repository,
        pull_number,
        marker,
        existing,
        body,
        tested_head,
        current_head,
        purpose,
        hooks,
    ):
        if self._credential in body:
            raise PublicationError(
                "publication body contains configured credential",
                code="credential_in_report",
            )
        # Compare a fresh owned-comment read immediately before journaling. The
        # GitHub API offers no atomic compare-and-write, so post-write checks are
        # still required; a change already visible here must never be overwritten.
        observed = self._existing(repository, pull_number, marker)
        if (existing is None and observed is not None) or (
            existing is not None
            and (
                observed is None
                or observed["id"] != existing["id"]
                or observed["body"] != existing["body"]
            )
        ):
            raise PublicationError(
                "owned comment changed before mutation", code="comment_changed"
            )
        method = "PATCH" if existing else "POST"
        comment_id = existing["id"] if existing else None
        if hooks:
            body = hooks.prepare_write(
                method=method,
                comment_id=comment_id,
                body=body,
                tested_head=tested_head,
                current_head=current_head,
                purpose=purpose,
            )
        path = (
            f"/repos/{repository}/issues/comments/{comment_id}"
            if existing
            else f"/repos/{repository}/issues/{pull_number}/comments"
        )
        result = self._request(method, path, json={"body": body})
        if (
            not isinstance(result, dict)
            or not _positive_id(result.get("id"))
            or (comment_id is not None and result["id"] != comment_id)
        ):
            raise PublicationError(
                "invalid publication receipt; reconcile before retrying",
                code="invalid_write_receipt",
            )
        if not self._owned(result):
            raise PublicationError(
                "publication receipt has unexpected author; inspect the written comment before retrying",
                code="write_actor_mismatch",
            )
        if result.get("body") != body:
            raise PublicationError(
                "publication receipt body does not match intent; reconcile before retrying",
                code="write_body_mismatch",
            )
        observed = self._existing(repository, pull_number, marker)
        if (
            observed is None
            or observed["id"] != result["id"]
            or observed["body"] != body
        ):
            raise PublicationError(
                "written comment could not be verified; reconcile before retrying",
                code="write_not_observed",
            )
        if hooks:
            hooks.confirm_write(comment_id=result["id"], body=body)
        return result

    @instrument("publication")
    def publish(
        self,
        *,
        repository: str,
        pull_number: int,
        project: str,
        tested_head: str,
        report: str,
        report_digest: str | None = None,
        hooks=None,
    ) -> PublicationResult:
        _repository(repository)
        if not _positive_id(pull_number):
            raise PublicationError(
                "invalid pull request number", code="invalid_pull_number"
            )
        tested_head = _sha(tested_head)
        marker = _marker(project)
        if not isinstance(report, str) or len(report.encode()) > 55_000:
            raise PublicationError(
                "report exceeds bounded publication limit", code="report_limit"
            )
        report = _report_text(report, report_digest)
        bot_user_id = self.verify_identity()
        if hooks:
            hooks.actor_verified(bot_user_id)
        current = self._head(repository, pull_number)
        existing = self._existing(repository, pull_number, marker)
        current = self._head(repository, pull_number)
        if hooks:
            hooks.observe(current, existing["id"] if existing else None)
        if current != tested_head:
            if existing:
                match = re.match(
                    re.escape(marker)
                    + r"\n<!-- loose-thread:head:([0-9a-f]{40}) -->\n",
                    existing["body"],
                )
                if match and match[1] != current:
                    body = self._body(marker, match[1], "", current)
                    if _logical_body(existing["body"], marker) != body:
                        self._write(
                            repository=repository,
                            pull_number=pull_number,
                            marker=marker,
                            existing=existing,
                            body=body,
                            tested_head=match[1],
                            current_head=current,
                            purpose="stale",
                            hooks=hooks,
                        )
                        current = self._head(repository, pull_number)
            return PublicationResult(
                "stale", existing["id"] if existing else None, tested_head, current
            )
        body = self._body(marker, tested_head, report)
        if existing and _logical_body(existing["body"], marker) == body:
            result, status = existing, "unchanged"
        else:
            result = self._write(
                repository=repository,
                pull_number=pull_number,
                marker=marker,
                existing=existing,
                body=body,
                tested_head=tested_head,
                current_head=current,
                purpose="report",
                hooks=hooks,
            )
            status = "updated" if existing else "created"
        current = self._head(repository, pull_number)
        if hooks:
            hooks.observe(current, result["id"])
        if current != tested_head:
            self._write(
                repository=repository,
                pull_number=pull_number,
                marker=marker,
                existing=result,
                body=self._body(marker, tested_head, "", current),
                tested_head=tested_head,
                current_head=current,
                purpose="stale",
                hooks=hooks,
            )
            current = self._head(repository, pull_number)
            status = "stale"
        return PublicationResult(status, result["id"], tested_head, current)
