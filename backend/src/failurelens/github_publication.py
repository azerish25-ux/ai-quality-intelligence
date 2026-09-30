"""Opt-in GitHub issue-comment publication; never a merge/release gate.

Callers serialize publishers per repository/PR/project (see action docs). Only
server-looked-up PR metadata and comments owned by the configured bot are used.
The REST API has no conditional head+comment transaction; post-write checks make
that limitation explicit and replace a raced report with a stale advisory.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re

import httpx


class PublicationError(RuntimeError):
    """Safe operational error; response bodies/tokens must never reach logs."""


@dataclass(frozen=True)
class PublicationResult:
    status: str
    comment_id: int | None
    tested_head: str
    current_head: str


def _sha(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise PublicationError("an exact lowercase 40-character commit SHA is required")
    return value


def _marker(project: str) -> str:
    if not project or len(project) > 240:
        raise PublicationError("invalid project scope")
    return "<!-- loose-thread:publication:v1:" + hashlib.sha256(project.encode()).hexdigest() + " -->"


class GitHubPublisher:
    def __init__(self, token: str, *, bot_login: str = "github-actions[bot]", transport=None):
        if not token or not re.fullmatch(r"[A-Za-z0-9_-]+\[bot\]", bot_login):
            raise PublicationError("a token and explicit bot identity are required")
        self.bot_login = bot_login
        self.client = httpx.Client(
            base_url="https://api.github.com", timeout=20, follow_redirects=False,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"}, transport=transport,
        )

    def close(self):
        self.client.close()

    def _request(self, method, path, **kwargs):
        try:
            with self.client.stream(method, path, **kwargs) as response:
                if not 200 <= response.status_code < 300:
                    raise PublicationError(f"GitHub {method} failed with HTTP {response.status_code}")
                body = bytearray()
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > 8_000_000:
                        raise PublicationError("GitHub response exceeds bounded lookup limit")
                    body.extend(chunk)
        except httpx.HTTPError:
            raise PublicationError("GitHub transport failed; reconcile before retrying publication") from None
        try:
            return json.loads(body)
        except (ValueError, UnicodeError):
            raise PublicationError("GitHub returned invalid JSON") from None

    def _head(self, repo, number):
        pr = self._request("GET", f"/repos/{repo}/pulls/{number}")
        try:
            if pr["base"]["repo"]["full_name"].casefold() != repo.casefold():
                raise PublicationError("PR repository mismatch")
            if pr["state"] != "open":
                raise PublicationError("PR is not open")
            return _sha(pr["head"]["sha"])
        except (KeyError, TypeError):
            raise PublicationError("incomplete trusted PR metadata") from None

    def _existing(self, repo, number, marker):
        found = []
        for page in range(1, 101):
            batch = self._request("GET", f"/repos/{repo}/issues/{number}/comments",
                                  params={"per_page": 100, "page": page})
            if not isinstance(batch, list):
                raise PublicationError("invalid comment collection")
            for comment in batch:
                if (isinstance(comment, dict) and isinstance(comment.get("body"), str)
                    and comment["body"].startswith(marker + "\n")
                    and comment.get("user", {}).get("login") == self.bot_login
                    and comment.get("user", {}).get("type") == "Bot"):
                    if not isinstance(comment.get("id"), int) or comment["id"] < 1:
                        raise PublicationError("invalid comment identity")
                    found.append(comment)
            if len(batch) < 100:
                break
        else:
            raise PublicationError("comment pagination limit reached; no publication performed")
        if len(found) > 1:
            raise PublicationError("multiple owned report comments; manual reconciliation required")
        return found[0] if found else None

    @staticmethod
    def _body(marker, head, report, current=None):
        metadata = "<!-- loose-thread:head:" + head + " -->"
        if current is not None:
            report = ("## Loose Thread: stale test evidence\n\nHOLD_FOR_REVIEW\n\n"
                      f"Tested head: `{head}`\nCurrent PR head: `{current}`\n\n"
                      "The PR changed after these tests. Rerun analysis for the current head.\n"
                      "This advisory does not approve a release or suppress failures.\n")
        return marker + "\n" + metadata + "\n" + report

    def publish(self, *, repository: str, pull_number: int, project: str,
                tested_head: str, report: str) -> PublicationResult:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise PublicationError("invalid repository")
        if type(pull_number) is not int or pull_number < 1:
            raise PublicationError("invalid pull request number")
        tested_head = _sha(tested_head)
        marker = _marker(project)
        if not isinstance(report, str) or len(report.encode()) > 55_000:
            raise PublicationError("report exceeds bounded publication limit")
        current = self._head(repository, pull_number)
        existing = self._existing(repository, pull_number, marker)
        current = self._head(repository, pull_number)  # lookup may have taken time
        if current != tested_head:
            # Do not let an older run overwrite a report for the current head.
            if existing:
                match = re.match(re.escape(marker) + r"\n<!-- loose-thread:head:([0-9a-f]{40}) -->\n", existing["body"])
                if match and match[1] != current:
                    body = self._body(marker, match[1], "", current)
                    if body != existing["body"]:
                        self._request("PATCH", f"/repos/{repository}/issues/comments/{existing['id']}", json={"body": body})
            return PublicationResult("stale", existing["id"] if existing else None, tested_head, current)
        body = self._body(marker, tested_head, report)
        if existing and existing["body"] == body:
            result = existing
            status = "unchanged"
        elif existing:
            result = self._request("PATCH", f"/repos/{repository}/issues/comments/{existing['id']}", json={"body": body})
            status = "updated"
        else:
            result = self._request("POST", f"/repos/{repository}/issues/{pull_number}/comments", json={"body": body})
            status = "created"
        if not isinstance(result, dict) or type(result.get("id")) is not int or result["id"] < 1:
            raise PublicationError("invalid publication receipt; reconcile before retrying")
        owner = result.get("user")
        if not isinstance(owner, dict) or owner.get("login") != self.bot_login or owner.get("type") != "Bot":
            raise PublicationError("publication receipt has unexpected author; inspect the written comment before retrying")
        current = self._head(repository, pull_number)
        if current != tested_head:
            self._request("PATCH", f"/repos/{repository}/issues/comments/{result['id']}",
                          json={"body": self._body(marker, tested_head, "", current)})
            status = "stale"
        return PublicationResult(status, result["id"], tested_head, current)
