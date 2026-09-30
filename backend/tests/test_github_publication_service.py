"""Durable publication with real SQL transactions and zero-network HTTP fixtures."""

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event

import httpx
import pytest
from failurelens import models as m
from failurelens.db import Base, create_database_engine
from failurelens.github_publication import GitHubPublisher, PublicationError, _marker
from failurelens.github_publication_service import (
    durable_publish,
    reconcile_publication,
)
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

A, B = "a" * 40, "b" * 40
TOKEN = "synthetic-publisher-credential-canary"
BOT = {"login": "github-actions[bot]", "type": "Bot", "id": 42}


@pytest.fixture
def publication_factory(tmp_path):
    engine = create_database_engine(
        "sqlite+pysqlite:///" + str(tmp_path / "publication.db")
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def seed(factory, *, slug="publication-project", head=A):
    with factory.begin() as session:
        project = m.Project(slug=slug, name="Publication fixture")
        session.add(project)
        session.flush()
        run = m.Run(
            project_id=project.id,
            external_id="fixture-run",
            attempt=1,
            repository="owner/repo",
            commit_sha=head,
            manifest_digest="f" * 64,
            status=m.RunStatus.complete,
            completeness="complete",
            expected_inputs=1,
            received_inputs=1,
        )
        session.add(run)
        session.flush()
        return {"project_id": project.id, "run_id": run.id}


class GitHub:
    def __init__(self):
        self.head = A
        self.comments = []
        self.requests = []
        self.writes = []
        self.viewer = BOT["login"]
        self.actor = dict(BOT)
        self.race = False

    def handle(self, request):
        self.requests.append((request.method, request.url.path))
        assert request.url.host == "api.github.com"
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        if request.url.path == "/graphql":
            assert json.loads(request.content) == {
                "query": "query { viewer { login } }"
            }
            return httpx.Response(
                200, json={"data": {"viewer": {"login": self.viewer}}}
            )
        if request.url.path.startswith("/users/"):
            return httpx.Response(200, json=self.actor)
        if "/pulls/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "state": "open",
                    "head": {"sha": self.head},
                    "base": {"repo": {"full_name": "owner/repo"}},
                },
            )
        if request.method == "GET":
            return httpx.Response(200, json=self.comments)
        body = json.loads(request.content)["body"]
        self.writes.append((request.method, body))
        if request.method == "POST":
            item = {"id": 100 + len(self.comments), "body": body, "user": dict(BOT)}
            self.comments.append(item)
        else:
            item = next(
                x
                for x in self.comments
                if x["id"] == int(request.url.path.rsplit("/", 1)[1])
            )
            item["body"] = body
        if self.race:
            self.head = B
        return httpx.Response(200, json=item)


def publish(factory, scope, server, **kwargs):
    return durable_publish(
        factory,
        run_id=scope["run_id"],
        repository="owner/repo",
        pull_number=7,
        token=TOKEN,
        transport=httpx.MockTransport(kwargs.pop("handler", server.handle)),
        **kwargs,
    )


def reconcile(factory, receipt, server, **kwargs):
    return reconcile_publication(
        factory,
        publication_id=receipt["publication_id"],
        token=TOKEN,
        transport=httpx.MockTransport(kwargs.pop("handler", server.handle)),
        **kwargs,
    )


def test_intent_actor_and_write_are_committed_before_transport(publication_factory):
    factory, server = publication_factory, GitHub()
    scope = seed(factory)
    observations = []

    def handler(request):
        # This independent write can commit during HTTP: no transaction spans it.
        with factory.begin() as session:
            project = session.get(m.Project, scope["project_id"])
            project.name = "Independent transaction"
            receipt = session.scalar(select(m.GitHubPublication))
            target = session.get(m.GitHubPublicationTarget, receipt.target_id)
            assert (
                receipt.status == "active"
                and target.active_publication_id == receipt.id
            )
            if request.method in {"POST", "PATCH"} and request.url.path != "/graphql":
                write = session.scalar(select(m.GitHubPublicationWrite))
                assert write.state == "dispatching"
                assert (
                    write.body_digest
                    == hashlib.sha256(
                        json.loads(request.content)["body"].encode()
                    ).hexdigest()
                )
                assert (
                    receipt.actor_verification == "verified"
                    and receipt.bot_user_id == 42
                )
            observations.append(receipt.id)
        return server.handle(request)

    result = publish(
        factory,
        scope,
        server,
        handler=handler,
        source_run_id="987654321",
        source_run_attempt=2,
    )
    assert result["status"] == "created" and not result["target_reserved"]
    assert result["source_verification"] == "unverified"
    assert result["actor_verification"] == "verified" and result["actor_verified_at"]
    assert result["writes"][0]["state"] == "observed"
    assert observations and set(observations) == {result["publication_id"]}
    assert TOKEN not in json.dumps(result)


def test_logical_replay_ignores_only_own_write_tag(publication_factory):
    factory, server = publication_factory, GitHub()
    scope = seed(factory)
    first = publish(factory, scope, server)
    second = publish(factory, scope, server)
    assert first["publication_id"] != second["publication_id"]
    assert second["status"] == "unchanged" and not second["writes"]
    assert len(server.writes) == 1
    with factory.begin() as session:
        session.get(m.Project, scope["project_id"]).slug = "renamed-project"
    assert publish(factory, scope, server)["status"] == "unchanged"
    with factory.begin() as session:
        session.get(m.Run, scope["run_id"]).expected_inputs = 2
    updated = publish(factory, scope, server)
    assert (
        updated["status"] == "updated"
        and updated["report_digest"] != first["report_digest"]
    )
    assert len(server.comments) == 1
    assert _marker(scope["project_id"]) in server.comments[0]["body"]


@pytest.mark.parametrize(
    "source_id,attempt",
    [
        ("1", None),
        (None, 1),
        ("0", 1),
        ("x", 1),
        ("1" * 21, 1),
        ("1", True),
        ("1", 1000001),
    ],
)
def test_source_identity_is_bounded_before_network(
    publication_factory, source_id, attempt
):
    factory, server = publication_factory, GitHub()
    with pytest.raises(PublicationError, match="bounded positive pair"):
        publish(
            factory,
            seed(factory),
            server,
            source_run_id=source_id,
            source_run_attempt=attempt,
        )
    assert not server.requests


@pytest.mark.parametrize("change", ["human", "wrong_bot", "wrong_type", "bad_id"])
def test_actor_identity_fails_before_any_comment_write(publication_factory, change):
    factory, server = publication_factory, GitHub()
    if change == "human":
        server.viewer = "human"
    elif change == "wrong_bot":
        server.viewer = "other[bot]"
    elif change == "wrong_type":
        server.actor["type"] = "User"
    else:
        server.actor["id"] = True
    result = publish(factory, seed(factory), server)
    assert result["status"] == "failed" and not result["target_reserved"]
    assert result["actor_verification"] == "not_verified"
    assert not server.writes


def lost_ack(server, *, before=False, method="POST"):
    def handler(request):
        is_write = request.method == method and "/issues/" in request.url.path
        if before and is_write:
            raise httpx.ReadTimeout(TOKEN, request=request)
        response = server.handle(request)
        if is_write:
            raise httpx.ReadTimeout(TOKEN, request=request)
        return response

    return handler


def test_lost_ack_blocks_resend_then_reconciles_exact_write(publication_factory):
    factory, server = publication_factory, GitHub()
    scope = seed(factory)
    uncertain = publish(factory, scope, server, handler=lost_ack(server))
    assert uncertain["status"] == "uncertain" and uncertain["target_reserved"]
    assert uncertain["writes"][0]["state"] == "uncertain"
    request_count = len(server.requests)
    blocked = publish(factory, scope, server)
    assert (
        blocked["error_code"] == "target_busy" and len(server.requests) == request_count
    )
    settled = reconcile(factory, uncertain, server)
    assert settled["status"] == "created" and settled["reconciled_at"]
    assert not settled["target_reserved"] and len(server.writes) == 1
    assert publish(factory, scope, server)["status"] == "unchanged"


def test_absence_never_proves_no_in_flight_post(publication_factory):
    factory, server = publication_factory, GitHub()
    scope = seed(factory)
    pending = []

    def handler(request):
        if request.method == "POST" and "/issues/" in request.url.path:
            pending.append(request)
            raise httpx.ReadTimeout("lost before observed", request=request)
        return server.handle(request)

    uncertain = publish(factory, scope, server, handler=handler)
    for _ in range(2):
        result = reconcile(factory, uncertain, server)
        assert result["status"] == "uncertain" and result["target_reserved"]
        assert result["error_code"] == "write_not_reconciled"
    assert publish(factory, scope, server)["error_code"] == "target_busy"
    assert not server.writes
    server.handle(pending[0])  # The originally dispatched request finishes late.
    assert reconcile(factory, uncertain, server)["status"] == "created"
    assert len(server.writes) == 1


def test_process_crash_keeps_dispatch_intent_reserved(publication_factory):
    factory, server = publication_factory, GitHub()
    scope = seed(factory)

    def handler(request):
        response = server.handle(request)
        if request.method == "POST" and "/issues/" in request.url.path:
            raise SystemExit("simulated process death")
        return response

    with pytest.raises(SystemExit):
        publish(factory, scope, server, handler=handler)
    with factory() as session:
        row = session.scalar(select(m.GitHubPublication))
        assert row.status == "active"
        assert session.scalar(select(m.GitHubPublicationWrite)).state == "dispatching"
        publication_id = row.id
    result = reconcile_publication(
        factory,
        publication_id=publication_id,
        token=TOKEN,
        transport=httpx.MockTransport(server.handle),
    )
    assert result["status"] == "created" and len(server.writes) == 1


def test_head_race_journals_and_verifies_neutral_stale_patch(publication_factory):
    factory, server = publication_factory, GitHub()
    server.race = True
    result = publish(factory, seed(factory), server)
    assert result["status"] == "stale" and result["current_head"] == B
    assert [x["purpose"] for x in result["writes"]] == ["report", "stale"]
    assert all(x["state"] == "observed" for x in result["writes"])
    assert "HOLD_FOR_REVIEW" in server.comments[0]["body"]
    assert "stale test evidence" in server.comments[0]["body"]


def test_stale_patch_invalid_receipt_stays_uncertain(publication_factory):
    factory, server = publication_factory, GitHub()
    server.race = True

    def handler(request):
        response = server.handle(request)
        if request.method == "PATCH":
            return httpx.Response(
                200,
                json={
                    **response.json(),
                    "user": {"login": "human", "type": "User", "id": 99},
                },
            )
        return response

    result = publish(factory, seed(factory), server, handler=handler)
    assert result["status"] == "uncertain" and result["target_reserved"]
    assert result["writes"][1]["state"] == "uncertain"
    assert reconcile(factory, result, server)["status"] == "stale"
    assert len(server.writes) == 2


def test_readonly_reconcile_requires_explicit_stale_repair(publication_factory):
    factory, server = publication_factory, GitHub()
    scope = seed(factory)
    result = publish(factory, scope, server, handler=lost_ack(server))
    server.head = B
    readonly = reconcile(factory, result, server)
    assert (
        readonly["status"] == "uncertain"
        and readonly["error_code"] == "stale_requires_repair"
    )
    assert len(server.writes) == 1
    with factory.begin() as session:
        session.get(m.Run, scope["run_id"]).evidence_expired_at = datetime.now(UTC)
    repaired = reconcile(factory, result, server, repair_stale=True)
    assert repaired["status"] == "stale" and not repaired["target_reserved"]
    assert repaired["report_digest"] == result["report_digest"]
    assert repaired["writes"][1]["revalidated_report_digest"] != result["report_digest"]
    assert (
        len(server.writes) == 2 and "stale test evidence" in server.comments[0]["body"]
    )


def test_repair_never_overwrites_a_changed_owned_comment(publication_factory):
    factory, server = publication_factory, GitHub()
    result = publish(factory, seed(factory), server, handler=lost_ack(server))
    server.head = B
    server.comments[0]["body"] += "newer different report"
    result = reconcile(factory, result, server, repair_stale=True)
    assert result["status"] == "uncertain" and result["target_reserved"]
    assert result["error_code"] == "write_not_reconciled" and len(server.writes) == 1


def test_copied_human_marker_cannot_reconcile(publication_factory):
    factory, server = publication_factory, GitHub()
    result = publish(factory, seed(factory), server, handler=lost_ack(server))
    server.comments[0]["user"] = {"login": "human", "type": "User", "id": 99}
    result = reconcile(factory, result, server)
    assert (
        result["status"] == "uncertain"
        and result["error_code"] == "write_not_reconciled"
    )
    assert len(server.writes) == 1


def test_duplicate_owned_markers_stay_closed(publication_factory):
    factory, server = publication_factory, GitHub()
    result = publish(factory, seed(factory), server, handler=lost_ack(server))
    server.comments.append({**server.comments[0], "id": 999})
    result = reconcile(factory, result, server, repair_stale=True)
    assert (
        result["status"] == "uncertain"
        and result["error_code"] == "duplicate_owned_comments"
    )
    assert len(server.writes) == 1


def test_report_changes_during_reads_block_rich_write(publication_factory):
    factory, server = publication_factory, GitHub()
    scope = seed(factory)

    def handler(request):
        if "/pulls/" in request.url.path:
            with factory.begin() as session:
                session.get(m.Run, scope["run_id"]).expected_inputs = 2
        return server.handle(request)

    result = publish(factory, scope, server, handler=handler)
    assert result["status"] == "failed" and result["error_code"] == "report_changed"
    assert not result["writes"] and not server.writes


def test_expired_evidence_before_intent_has_zero_egress(publication_factory):
    factory, server = publication_factory, GitHub()
    scope = seed(factory)
    with factory.begin() as session:
        session.get(m.Run, scope["run_id"]).evidence_expired_at = datetime.now(UTC)
    result = publish(factory, scope, server)
    assert result["status"] == "failed" and result["error_code"] == "evidence_expired"
    assert not server.requests


def test_missing_reservation_receipt_cannot_be_released(publication_factory):
    factory, server = publication_factory, GitHub()
    scope = seed(factory)
    publish(factory, scope, server)
    with factory.begin() as session:
        session.scalar(
            select(m.GitHubPublicationTarget)
        ).active_publication_id = "missing-receipt"
    count = len(server.requests)
    with pytest.raises(PublicationError):
        publish(factory, scope, server)
    assert len(server.requests) == count


def test_transport_logs_and_errors_do_not_expose_credential(
    publication_factory, caplog, monkeypatch
):
    factory, server = publication_factory, GitHub()
    scope = seed(factory)
    monkeypatch.setenv("HTTPS_PROXY", "http://ambient-proxy.invalid")

    def handler(request):
        logging.getLogger("httpcore.http11").debug("response headers: %s", TOKEN)
        return server.handle(request)

    with caplog.at_level(logging.DEBUG):
        result = publish(factory, scope, server, handler=handler)
        logging.getLogger("httpcore.http11").debug("outside-publication-visible")
    assert result["status"] == "created" and TOKEN not in caplog.text
    assert "outside-publication-visible" in caplog.text
    publisher = GitHubPublisher(TOKEN, transport=httpx.MockTransport(server.handle))
    try:
        assert publisher.client._trust_env is False
    finally:
        publisher.close()


def test_literal_configured_credential_cannot_be_published():
    server = GitHub()
    publisher = GitHubPublisher(TOKEN, transport=httpx.MockTransport(server.handle))
    try:
        with pytest.raises(PublicationError, match="configured credential"):
            publisher.publish(
                repository="owner/repo",
                pull_number=7,
                project="p",
                tested_head=A,
                report="accidental " + TOKEN,
            )
    finally:
        publisher.close()
    assert not server.writes


def scenario_serialized(factory):
    scope, server = seed(factory), GitHub()
    entered, release = Event(), Event()

    def handler(request):
        if request.method == "POST" and "/issues/" in request.url.path:
            entered.set()
            assert release.wait(10)
        return server.handle(request)

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(publish, factory, scope, server, handler=handler)
        assert entered.wait(10)
        try:
            second = publish(factory, scope, server)
            assert second["error_code"] == "target_busy"
        finally:
            release.set()
        assert first.result(timeout=10)["status"] == "created"
    assert len(server.writes) == 1


def test_parallel_publisher_cannot_bypass_database_reservation(publication_factory):
    scenario_serialized(publication_factory)


def scenario_fenced_late_write(factory):
    scope, server = seed(factory), GitHub()
    entered, release = Event(), Event()

    def handler(request):
        if request.method == "POST" and "/issues/" in request.url.path:
            entered.set()
            assert release.wait(10)
        return server.handle(request)

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(publish, factory, scope, server, handler=handler)
        assert entered.wait(10)
        try:
            with factory() as session:
                publication_id = session.scalar(select(m.GitHubPublication.id))
            receipt = {"publication_id": publication_id}
            unresolved = reconcile(factory, receipt, server)
            assert unresolved["status"] == "uncertain" and unresolved["target_reserved"]
            assert publish(factory, scope, server)["error_code"] == "target_busy"
        finally:
            release.set()
        assert first.result(timeout=10)["status"] == "uncertain"
    assert reconcile(factory, receipt, server)["status"] == "created"
    assert len(server.writes) == 1


def test_reconciliation_fences_in_flight_publisher(publication_factory):
    scenario_fenced_late_write(publication_factory)


def test_same_markdown_different_snapshot_digest_requires_update(publication_factory):
    factory, server = publication_factory, GitHub()
    scope = seed(factory)
    first = publish(factory, scope, server)
    with factory.begin() as session:
        original = session.get(m.Run, scope["run_id"])
        other = m.Run(
            project_id=original.project_id,
            external_id=original.external_id,
            attempt=original.attempt,
            repository=original.repository,
            commit_sha=original.commit_sha,
            manifest_digest="e" * 64,
            status=original.status,
            completeness=original.completeness,
            expected_inputs=original.expected_inputs,
            received_inputs=original.received_inputs,
        )
        session.add(other)
        session.flush()
        other_scope = {"project_id": original.project_id, "run_id": other.id}
    second = publish(factory, other_scope, server)
    assert second["status"] == "updated"
    assert second["report_digest"] != first["report_digest"] and len(server.writes) == 2
    assert second["report_digest"] in server.comments[0]["body"]


def test_old_run_cannot_overwrite_current_head_report(publication_factory):
    factory, server = publication_factory, GitHub()
    scope = seed(factory, head=B)
    server.head = B
    assert publish(factory, scope, server)["status"] == "created"
    with factory.begin() as session:
        session.get(m.Run, scope["run_id"]).commit_sha = A
    old = publish(factory, scope, server)
    assert old["status"] == "stale" and not old["writes"]
    assert len(server.writes) == 1


def test_stale_existing_journal_uses_actual_written_tested_sha(publication_factory):
    factory, server = publication_factory, GitHub()
    scope = seed(factory)
    publish(factory, scope, server)
    with factory.begin() as session:
        session.get(m.Run, scope["run_id"]).commit_sha = "c" * 40
    server.head = B
    result = publish(factory, scope, server)
    assert result["status"] == "stale" and result["tested_head"] == "c" * 40
    assert result["writes"][0]["tested_head"] == A
    assert result["writes"][0]["purpose"] == "stale"


def test_identity_query_errors_cannot_mutate_comment(publication_factory):
    factory, server = publication_factory, GitHub()

    def handler(request):
        return httpx.Response(
            200,
            json={
                "data": {"viewer": {"login": BOT["login"]}},
                "errors": [{"message": TOKEN}],
            },
        )

    result = publish(factory, seed(factory), server, handler=handler)
    assert result["status"] == "failed" and result["error_code"] == "actor_not_verified"
    assert TOKEN not in json.dumps(result) and not result["writes"]


def test_owned_comment_numeric_actor_mismatch_is_not_adopted(publication_factory):
    factory, server = publication_factory, GitHub()
    scope = seed(factory)
    publish(factory, scope, server)
    server.comments[0]["user"]["id"] = 99
    result = publish(factory, scope, server)
    assert (
        result["status"] == "failed"
        and result["error_code"] == "comment_actor_mismatch"
    )
    assert len(server.writes) == 1


def test_fencing_before_dispatch_prevents_late_new_post(publication_factory):
    factory, server = publication_factory, GitHub()
    scope = seed(factory)
    entered, release = Event(), Event()
    heads = 0

    def handler(request):
        nonlocal heads
        if "/pulls/" in request.url.path:
            heads += 1
            if heads == 2:
                entered.set()
                assert release.wait(10)
        return server.handle(request)

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(publish, factory, scope, server, handler=handler)
        assert entered.wait(10)
        try:
            with factory() as session:
                publication_id = session.scalar(select(m.GitHubPublication.id))
            interrupted = reconcile(factory, {"publication_id": publication_id}, server)
            assert interrupted["error_code"] == "interrupted_before_write"
            assert not interrupted["target_reserved"] and not interrupted["writes"]
            assert publish(factory, scope, server)["status"] == "created"
        finally:
            release.set()
        assert first.result(timeout=10)["status"] == "failed"
    assert len(server.writes) == 1


def test_visible_comment_change_after_head_lookup_is_not_overwritten(
    publication_factory,
):
    factory, server = publication_factory, GitHub()
    scope = seed(factory)
    publish(factory, scope, server)
    with factory.begin() as session:
        session.get(m.Run, scope["run_id"]).expected_inputs = 2
    heads = 0

    def handler(request):
        nonlocal heads
        response = server.handle(request)
        if "/pulls/" in request.url.path:
            heads += 1
            if heads == 2:
                server.comments[0]["body"] += "A newer report is now visible"
        return response

    result = publish(factory, scope, server, handler=handler)
    assert result["status"] == "failed" and result["error_code"] == "comment_changed"
    assert len(server.writes) == 1


def test_cli_persists_receipt_and_explicit_repair_uses_same_identity(
    publication_factory, monkeypatch, capsys
):
    import sys

    from failurelens import cli, github_publication_service

    factory, server = publication_factory, GitHub()
    scope = seed(factory)
    handler = lost_ack(server)
    actual = GitHubPublisher

    def fixture_publisher(token, *, bot_login, transport=None):
        assert token == TOKEN
        return actual(
            token, bot_login=bot_login, transport=httpx.MockTransport(handler)
        )

    monkeypatch.setattr(
        github_publication_service, "GitHubPublisher", fixture_publisher
    )
    # Preserve the strict body construction boundary used by the service.
    fixture_publisher._body = actual._body
    monkeypatch.setattr(cli, "SessionLocal", factory)
    monkeypatch.setattr(cli, "initialize_database", lambda: None)
    monkeypatch.setenv("FAILURELENS_GITHUB_TOKEN", TOKEN)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "failurelens",
            "publish-github",
            "--run",
            scope["run_id"],
            "--repository",
            "owner/repo",
            "--pull-number",
            "7",
            "--source-run-id",
            "12345",
            "--source-run-attempt",
            "2",
        ],
    )
    with pytest.raises(SystemExit) as failure:
        cli.main()
    assert failure.value.code == 2
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "uncertain" and receipt["source_run_id"] == "12345"
    handler = server.handle
    server.head = B
    monkeypatch.setattr(
        sys,
        "argv",
        ["failurelens", "reconcile-github", "--publication", receipt["publication_id"]],
    )
    with pytest.raises(SystemExit) as failure:
        cli.main()
    assert failure.value.code == 2
    readonly = json.loads(capsys.readouterr().out)
    assert readonly["error_code"] == "stale_requires_repair" and len(server.writes) == 1
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "failurelens",
            "reconcile-github",
            "--publication",
            receipt["publication_id"],
            "--repair-stale",
        ],
    )
    cli.main()
    repaired = json.loads(capsys.readouterr().out)
    assert (
        repaired["status"] == "stale"
        and repaired["publication_id"] == receipt["publication_id"]
    )
    assert len(server.writes) == 2 and TOKEN not in json.dumps(repaired)


def scenario_simultaneous_admission(factory):
    from concurrent.futures import FIRST_COMPLETED, wait
    from threading import Barrier

    scope, server = seed(factory), GitHub()
    barrier, release = Barrier(2), Event()

    def handler(request):
        if request.url.path == "/graphql":
            assert release.wait(10)
        return server.handle(request)

    def invoke():
        barrier.wait(timeout=10)
        return publish(factory, scope, server, handler=handler)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke) for _ in range(2)]
        try:
            done, pending = wait(futures, timeout=10, return_when=FIRST_COMPLETED)
            assert len(done) == 1 and len(pending) == 1
            assert next(iter(done)).result()["error_code"] == "target_busy"
        finally:
            release.set()
        results = [future.result(timeout=10) for future in futures]
    assert {row["status"] for row in results} == {"created", "failed"}
    assert len(server.writes) == 1
    with factory() as session:
        assert len(list(session.scalars(select(m.GitHubPublicationTarget)))) == 1
        assert len(list(session.scalars(select(m.GitHubPublication)))) == 2


def test_simultaneous_admission_creates_one_reserved_target(publication_factory):
    scenario_simultaneous_admission(publication_factory)


@pytest.mark.parametrize("drift", ["expired", "report_changed"])
def test_identical_comment_revalidates_current_snapshot_before_unchanged(
    publication_factory, drift
):
    factory, server = publication_factory, GitHub()
    scope = seed(factory)
    original = publish(factory, scope, server)
    changed = False

    def handler(request):
        nonlocal changed
        if "/pulls/" in request.url.path and not changed:
            changed = True
            with factory.begin() as session:
                run = session.get(m.Run, scope["run_id"])
                if drift == "expired":
                    run.evidence_expired_at = datetime.now(UTC)
                else:
                    run.expected_inputs = 2
        return server.handle(request)

    result = publish(factory, scope, server, handler=handler)
    assert result["status"] == "failed" and not result["target_reserved"]
    assert result["error_code"] == (
        "evidence_expired" if drift == "expired" else "report_changed"
    )
    assert not result["writes"] and len(server.writes) == 1
    with factory() as session:
        original_row = session.get(m.GitHubPublication, original["publication_id"])
        assert original_row.status == "created"
        assert session.scalar(select(m.GitHubPublicationWrite)).state == "observed"


@pytest.mark.parametrize("drift", ["expired", "report_changed"])
def test_reconcile_observed_write_rejects_validation_drift_and_allows_neutral_repair(
    publication_factory, drift
):
    factory, server = publication_factory, GitHub()
    scope = seed(factory)
    result = publish(factory, scope, server, handler=lost_ack(server))
    with factory.begin() as session:
        run = session.get(m.Run, scope["run_id"])
        if drift == "expired":
            run.evidence_expired_at = datetime.now(UTC)
        else:
            run.expected_inputs = 2
    readonly = reconcile(factory, result, server)
    assert readonly["status"] == "uncertain" and readonly["target_reserved"]
    assert readonly["error_code"] == (
        "evidence_expired" if drift == "expired" else "report_changed"
    )
    assert readonly["writes"][0]["state"] == "observed"
    assert readonly["tested_head"] == readonly["current_head"] == A
    assert len(server.writes) == 1
    repaired = reconcile(factory, result, server, repair_stale=True)
    assert repaired["status"] == "stale" and not repaired["target_reserved"]
    assert repaired["tested_head"] == repaired["current_head"] == A
    assert repaired["report_digest"] == result["report_digest"]
    assert repaired["writes"][1]["revalidated_report_digest"] != result["report_digest"]
    body = server.comments[0]["body"]
    assert "HOLD_FOR_REVIEW" in body and "evidence or report projection changed" in body
    assert "The PR changed after these tests" not in body
    assert len(server.writes) == 2


def test_final_success_check_preserves_observed_write_when_evidence_expires(
    publication_factory,
):
    factory, server = publication_factory, GitHub()
    scope = seed(factory)

    def handler(request):
        if server.writes and "/pulls/" in request.url.path:
            with factory.begin() as session:
                session.get(m.Run, scope["run_id"]).evidence_expired_at = datetime.now(
                    UTC
                )
        return server.handle(request)

    result = publish(factory, scope, server, handler=handler)
    assert result["status"] == "uncertain" and result["target_reserved"]
    assert result["error_code"] == "evidence_expired"
    assert result["writes"][0]["state"] == "observed" and len(server.writes) == 1


@pytest.mark.parametrize(
    "entry",
    [
        None,
        "malformed",
        5,
        {},
        {"id": 12, "body": None, "user": BOT},
        {"id": True, "body": "text", "user": BOT},
        {"id": 12, "body": "text", "user": None},
        {"id": 12, "body": "text", "user": {"login": BOT["login"], "type": "Bot"}},
        {"id": 12, "body": "text", "user": {**BOT, "login": None}},
        {"id": 12, "body": "text", "user": {**BOT, "type": []}},
        {"id": 12, "body": "text", "user": {**BOT, "id": True}},
    ],
)
def test_malformed_comment_entry_cannot_authorize_absence_or_post(
    publication_factory, entry
):
    factory, server = publication_factory, GitHub()

    def handler(request):
        if request.method == "GET" and request.url.path.endswith("/comments"):
            return httpx.Response(200, json=[entry])
        return server.handle(request)

    result = publish(factory, seed(factory), server, handler=handler)
    assert (
        result["status"] == "failed"
        and result["error_code"] == "invalid_comment_collection"
    )
    assert not result["writes"] and not server.writes
