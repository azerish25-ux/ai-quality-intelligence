"""No network/credentials: exercise the real HTTP client against a REST fixture."""
import json
from types import SimpleNamespace

import httpx
import pytest

from failurelens.github_publication import GitHubPublisher, PublicationError, _marker
from failurelens.github_report import render_markdown

A, B = "a" * 40, "b" * 40


class GitHub:
    def __init__(self):
        self.head = A
        self.comments = []
        self.writes = []
        self.status = 200
        self.race = False
        self.closed = False
        self.pages = None

    def handle(self, request):
        assert request.url.host == "api.github.com"
        assert request.headers["authorization"] == "Bearer fake-test-token"
        if self.status != 200:
            return httpx.Response(self.status, json={"message": "secret response should not leak"})
        if "/pulls/" in request.url.path:
            return httpx.Response(200, json={"state": "closed" if self.closed else "open", "head": {"sha": self.head}, "base": {"repo": {"full_name": "owner/repo"}}})
        if request.method == "GET":
            return httpx.Response(200, json=self.pages(int(request.url.params["page"])) if self.pages else self.comments)
        data = json.loads(request.content)
        self.writes.append((request.method, request.url.path, data))
        if request.method == "POST":
            item = {"id": 123, "body": data["body"], "user": {"login": "github-actions[bot]", "type": "Bot"}}
            self.comments.append(item)
        else:
            item = next(c for c in self.comments if c["id"] == int(request.url.path.rsplit("/", 1)[1]))
            item["body"] = data["body"]
        if self.race:
            self.head = B
        return httpx.Response(200, json=item)


@pytest.fixture
def api():
    server = GitHub()
    publisher = GitHubPublisher("fake-test-token", transport=httpx.MockTransport(server.handle))
    yield server, publisher
    publisher.close()


def publish(publisher, **kwargs):
    return publisher.publish(**({"repository": "owner/repo", "pull_number": 7, "project": "demo", "tested_head": A, "report": "HOLD_FOR_REVIEW\n"} | kwargs))


def test_create_update_and_idempotent_replay(api):
    server, publisher = api
    assert publish(publisher).status == "created"
    assert publish(publisher).status == "unchanged"
    assert len(server.writes) == 1
    assert publish(publisher, report="changed").status == "updated"
    assert len(server.comments) == 1


def test_stale_before_first_write_does_not_publish(api):
    server, publisher = api
    server.head = B
    assert publish(publisher).status == "stale"
    assert not server.writes


def test_old_report_reconciled_but_current_report_not_overwritten(api):
    server, publisher = api
    publish(publisher)
    server.head = B
    assert publish(publisher).status == "stale"
    assert "stale test evidence" in server.comments[0]["body"]
    assert publish(publisher, tested_head=B).status == "updated"
    old = server.comments[0]["body"]
    publish(publisher)
    assert server.comments[0]["body"] == old


def test_head_change_after_write_replaced_with_safe_stale_advisory(api):
    server, publisher = api
    server.race = True
    assert publish(publisher).status == "stale"
    assert len(server.writes) == 2
    assert "HOLD_FOR_REVIEW" in server.comments[0]["body"]
    assert B in server.comments[0]["body"]


@pytest.mark.parametrize("user", [{"login": "attacker", "type": "User"}, {"login": "github-actions[bot]", "type": "User"}, {"login": "other[bot]", "type": "Bot"}])
def test_spoofed_marker_is_not_updated(api, user):
    server, publisher = api
    server.comments = [{"id": 1, "body": _marker("demo") + "\nspoof", "user": user}]
    assert publish(publisher).status == "created"
    assert server.comments[0]["body"].endswith("spoof")


def test_project_scoped_markers(api):
    server, publisher = api
    publish(publisher)
    assert publish(publisher, project="other").status == "created"
    assert len(server.comments) == 2


def test_duplicates_fail_closed(api):
    server, publisher = api
    publish(publisher)
    server.comments.append(dict(server.comments[0], id=456))
    with pytest.raises(PublicationError, match="multiple"):
        publish(publisher)
    assert len(server.writes) == 1


def test_paginated_comment_lookup(api):
    server, publisher = api
    publish(publisher)
    existing = server.comments.copy()
    server.pages = lambda page: ([{"id": n, "body": "unrelated"} for n in range(100)] if page == 1 else existing)
    assert publish(publisher).status == "unchanged"


def test_pagination_limit_fails_without_writes(api):
    server, publisher = api
    server.pages = lambda _: [{"body": "unrelated"}] * 100
    with pytest.raises(PublicationError, match="pagination"):
        publish(publisher)
    assert not server.writes


@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
def test_errors_are_bounded_and_redacted(api, status):
    server, publisher = api
    server.status = status
    with pytest.raises(PublicationError) as error:
        publish(publisher)
    assert "secret" not in str(error.value)
    assert not server.writes


@pytest.mark.parametrize("kwargs", [{"repository": "owner/repo/../other"}, {"pull_number": True}, {"pull_number": 0}, {"tested_head": "abc123"}, {"tested_head": "A" * 40}, {"report": "x" * 55_001}, {"project": ""}])
def test_invalid_inputs_fail_before_write(api, kwargs):
    server, publisher = api
    with pytest.raises(PublicationError):
        publish(publisher, **kwargs)
    assert not server.writes


def test_closed_pr_is_not_written(api):
    server, publisher = api
    server.closed = True
    with pytest.raises(PublicationError, match="not open"):
        publish(publisher)
    assert not server.writes


def test_empty_analysis_and_metadata_injection_are_safe():
    run = SimpleNamespace(commit_sha="`\n@team <script>", base_sha=A, external_id="`\n<!-- forged -->", attempt=1, completeness="complete", received_inputs=1, expected_inputs=1)
    body = render_markdown(run, [])
    assert "HOLD_FOR_REVIEW" in body
    assert "@team" not in body and "<script>" not in body and "<!-- forged -->" not in body


def test_lost_write_ack_is_reconciled_without_duplicate(api):
    server, first = api
    def handler(request):
        response = server.handle(request)
        if request.method == "POST":
            raise httpx.ReadTimeout("simulated lost acknowledgement", request=request)
        return response
    uncertain = GitHubPublisher("fake-test-token", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(PublicationError, match="reconcile"):
            publish(uncertain)
    finally:
        uncertain.close()
    assert len(server.comments) == 1
    assert publish(first).status == "unchanged"
    assert len(server.comments) == 1


def test_invalid_bot_identity_rejected():
    for bot in ["human", "evil/../[bot]", "", "github-actions[bot]\n"]:
        with pytest.raises(PublicationError):
            GitHubPublisher("fake", bot_login=bot)


def test_actual_receipt_must_match_configured_bot(api):
    server, _ = api
    def handler(request):
        result = server.handle(request)
        if request.method == 'POST':
            payload = result.json()
            payload['user'] = {'login': 'human-user', 'type': 'User'}
            return httpx.Response(200, json=payload)
        return result
    publisher = GitHubPublisher('fake-test-token', transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(PublicationError, match='unexpected author'):
            publish(publisher)
        assert len(server.writes) == 1
    finally:
        publisher.close()


def test_response_size_is_enforced_while_streaming():
    class LargeBody(httpx.SyncByteStream):
        def __iter__(self):
            yield b'x' * 4_000_001
            yield b'x' * 4_000_001
            raise AssertionError('must stop reading after the bounded limit')
    publisher = GitHubPublisher('fake-test-token', transport=httpx.MockTransport(
        lambda _: httpx.Response(200, stream=LargeBody())))
    try:
        with pytest.raises(PublicationError, match='bounded lookup'):
            publish(publisher)
    finally:
        publisher.close()
