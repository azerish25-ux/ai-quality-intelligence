from __future__ import annotations

from dataclasses import replace

from failurelens.clustering import (
    ALGORITHM_VERSION,
    FEATURE_VERSION,
    FailureFeature,
    cluster_project_failures,
    generate_candidate_pairs,
    pairwise_cluster_metrics,
    propose_clusters_from_features,
    review_cluster,
)
from failurelens.models import (
    ClusterMembership,
    ClusterMembershipDecision,
    ClusterRevision,
    Failure,
    FailureCluster,
    Outcome,
)
from failurelens.schemas import IngestionRequest
from failurelens.schemas import TestObservation as Observation
from failurelens.service import create_project, ingest_normalized
from sqlalchemy import func, select


def _ingest_failure(
    session,
    project,
    *,
    external_id: str,
    test_identity: str,
    message: str,
    exception_type: str = "AssertionError",
    details: dict | None = None,
    browser: str | None = None,
    source_path: str = "tests/example.spec.ts",
):
    run = ingest_normalized(
        session,
        project,
        IngestionRequest(
            external_id=external_id,
            repository="owner/repo",
            commit_sha="abcdef0",
            expected_inputs=1,
            observations=[
                Observation(
                    test_identity=test_identity,
                    source_path=source_path,
                    browser=browser,
                    outcome=Outcome.failed,
                    message=message,
                    exception_type=exception_type,
                    details=details or {},
                )
            ],
        ),
    )
    failure = session.scalar(select(Failure).where(Failure.run_id == run.id))
    assert failure is not None
    return run, failure


def _active_clusters(session, project_id: str) -> list[FailureCluster]:
    return list(
        session.scalars(
            select(FailureCluster)
            .where(
                FailureCluster.project_id == project_id,
                FailureCluster.status == "active",
            )
            .order_by(FailureCluster.cluster_key)
        ).all()
    )


def _current_members(session, cluster: FailureCluster) -> list[ClusterMembership]:
    revision = session.scalar(
        select(ClusterRevision).where(
            ClusterRevision.cluster_id == cluster.id,
            ClusterRevision.revision == cluster.current_revision,
        )
    )
    assert revision is not None
    return list(
        session.scalars(
            select(ClusterMembership)
            .where(ClusterMembership.revision_id == revision.id)
            .order_by(ClusterMembership.failure_id)
        ).all()
    )


def test_dynamic_values_and_cross_browser_failures_cluster_together(session) -> None:
    project = create_project(session, "cluster-dynamic", "Cluster dynamic")
    _, first = _ingest_failure(
        session,
        project,
        external_id="run-1",
        test_identity="checkout::submits",
        browser="chromium",
        message=(
            "API timeout at src/checkout.ts:114 for request "
            "9d8f5d2a-8fa2-4f34-9ba1-9ea6d94f6840 on 2026-09-27T10:11:12Z"
        ),
        exception_type="TimeoutError",
        details={
            "route": "/api/payments/18742",
            "method": "POST",
            "selector": "[data-testid=submit-payment]",
            "stack_frames": ["src/checkout.ts:114", "src/client.ts:44"],
        },
    )
    _, second = _ingest_failure(
        session,
        project,
        external_id="run-2",
        test_identity="checkout::submits",
        browser="firefox",
        message=(
            "API timeout at src/checkout.ts:992 for request "
            "fd59ddbd-807c-48b0-95d1-e3c54c5961aa on 2026-09-27T10:15:18Z"
        ),
        exception_type="TimeoutError",
        details={
            "route": "/api/payments/99881",
            "method": "POST",
            "selector": "[data-testid=submit-payment]",
            "stack_frames": ["src/checkout.ts:992", "src/client.ts:88"],
        },
    )

    clusters = _active_clusters(session, project.id)
    assert len(clusters) == 1
    assert clusters[0].member_count == 2
    assert clusters[0].algorithm_version == ALGORITHM_VERSION
    assert clusters[0].feature_version == FEATURE_VERSION
    memberships = _current_members(session, clusters[0])
    assert {item.failure_id for item in memberships} == {first.id, second.id}
    non_representative = next(item for item in memberships if item.role == "member")
    assert non_representative.similarity_score >= 0.62
    assert "cross_browser_corroboration" in non_representative.score_components
    assert non_representative.conflicting_signals == []


def test_authorization_and_server_statuses_never_merge(session) -> None:
    project = create_project(session, "cluster-http", "Cluster HTTP")
    _ingest_failure(
        session,
        project,
        external_id="run-auth",
        test_identity="api::payment",
        message="payment request failed for the same endpoint",
        exception_type="HttpError",
        details={"route": "/api/payments", "method": "POST", "http_status": 401},
    )
    _ingest_failure(
        session,
        project,
        external_id="run-server",
        test_identity="api::payment",
        message="payment request failed for the same endpoint",
        exception_type="HttpError",
        details={"route": "/api/payments", "method": "POST", "http_status": 500},
    )

    clusters = _active_clusters(session, project.id)
    assert len(clusters) == 2
    assert sorted(item.member_count for item in clusters) == [1, 1]


def test_generic_timeouts_with_different_selectors_never_merge(session) -> None:
    project = create_project(session, "cluster-selector", "Cluster selector")
    for index, selector in enumerate(("#pay-now", "#cancel-order"), start=1):
        _ingest_failure(
            session,
            project,
            external_id=f"run-{index}",
            test_identity="ui::checkout",
            message="Timeout waiting for selector",
            exception_type="TimeoutError",
            details={"selector": selector},
        )
    assert len(_active_clusters(session, project.id)) == 2


def test_assertion_negation_and_direction_remain_distinct(session) -> None:
    project = create_project(session, "cluster-assertion", "Cluster assertion")
    _ingest_failure(
        session,
        project,
        external_id="run-positive",
        test_identity="ledger::balance",
        message="balance assertion failed",
        details={"assertion": "expected balance == 0"},
    )
    _ingest_failure(
        session,
        project,
        external_id="run-negated",
        test_identity="ledger::balance",
        message="balance assertion failed",
        details={"assertion": "expected balance != 0"},
    )
    assert len(_active_clusters(session, project.id)) == 2


def _feature(
    failure_id: str,
    *,
    route: str | None = None,
    selector: str | None = None,
    frames: tuple[str, ...] = (),
) -> FailureFeature:
    return FailureFeature(
        failure_id=failure_id,
        project_id="project",
        run_id=f"run-{failure_id}",
        stable_order=(failure_id,),
        strict_fingerprint=f"strict-{failure_id}",
        normalized_message="shared checkout timeout signature",
        message_tokens=frozenset({"shared", "checkout", "signature"}),
        exception_type="timeouterror",
        exception_family="timeout",
        route=route,
        method="post" if route else None,
        http_status=None,
        selector=selector,
        assertion=None,
        assertion_signature=("none", False),
        stack_frames=frames,
        source_path="tests/checkout.spec.ts",
        browser="chromium",
        test_identity="checkout payment submit",
    )


def test_complete_link_blocks_transitive_bridge_cluster() -> None:
    a = _feature("a", route="/api/payments", frames=("src/a.ts",))
    b = _feature(
        "b",
        route="/api/payments",
        selector="#pay",
        frames=("src/a.ts", "src/c.ts"),
    )
    c = _feature("c", selector="#pay", frames=("src/c.ts",))

    proposals = propose_clusters_from_features([a, b, c])
    groups = [set(item.failure_ids) for item in proposals]
    assert {"a", "b"} in groups
    assert {"c"} in groups
    assert not any(group == {"a", "b", "c"} for group in groups)


def test_outlier_is_retained_as_singleton_with_uncertainty(session) -> None:
    project = create_project(session, "cluster-outlier", "Cluster outlier")
    _ingest_failure(
        session,
        project,
        external_id="run-1",
        test_identity="unique::failure",
        message="entirely unique failure signal",
        exception_type="UniqueFailure",
    )
    cluster = _active_clusters(session, project.id)[0]
    revision = session.scalar(
        select(ClusterRevision).where(
            ClusterRevision.cluster_id == cluster.id,
            ClusterRevision.revision == cluster.current_revision,
        )
    )
    assert cluster.uncertainty == "singleton"
    assert revision is not None
    assert "singleton_outlier" in revision.uncertainty_flags


def test_reprocessing_is_idempotent_and_version_change_appends_revision(
    session, monkeypatch
) -> None:
    project = create_project(session, "cluster-idempotent", "Cluster idempotent")
    request = IngestionRequest(
        external_id="run-1",
        observations=[
            Observation(
                test_identity="same::failure",
                outcome=Outcome.failed,
                message="same stable failure",
                exception_type="StableError",
            )
        ],
    )
    first_run = ingest_normalized(session, project, request)
    second_run = ingest_normalized(session, project, request)
    assert first_run.id == second_run.id
    cluster = _active_clusters(session, project.id)[0]
    assert cluster.current_revision == 1
    assert session.scalar(select(func.count(ClusterRevision.id))) == 1

    monkeypatch.setattr(
        "failurelens.clustering.ALGORITHM_VERSION", "explainable-complete-link-v2-test"
    )
    cluster_project_failures(session, project.id)
    session.refresh(cluster)
    assert cluster.current_revision == 2
    assert session.scalar(select(func.count(ClusterRevision.id))) == 2


def test_human_split_is_append_only_and_locks_both_clusters(session) -> None:
    project = create_project(session, "cluster-split", "Cluster split")
    failures = []
    for index in range(3):
        _, failure = _ingest_failure(
            session,
            project,
            external_id=f"run-{index}",
            test_identity="checkout::same",
            message=f"same error at src/app.ts:{100 + index}",
            exception_type="CheckoutError",
            details={"route": "/api/checkout", "method": "POST"},
        )
        failures.append(failure)
    cluster = _active_clusters(session, project.id)[0]
    event = review_cluster(
        session,
        cluster,
        actor="reviewer@example.test",
        decision="split",
        reason="One execution has a separately verified cause",
        expected_revision=cluster.current_revision,
        failure_ids=[failures[-1].id],
    )

    clusters = _active_clusters(session, project.id)
    assert len(clusters) == 2
    assert sorted(item.member_count for item in clusters) == [1, 2]
    assert event.target_cluster_id is not None
    assert event.failure_ids == [failures[-1].id]
    assert session.scalar(select(func.count(ClusterMembershipDecision.id))) == 1
    assert session.scalar(select(func.count(ClusterRevision.id))) >= 5

    revision_counts = {item.id: item.current_revision for item in clusters}
    cluster_project_failures(session, project.id)
    for item in clusters:
        session.refresh(item)
        assert item.current_revision == revision_counts[item.id]


def test_human_merge_preserves_source_history_and_supersedes_source(session) -> None:
    project = create_project(session, "cluster-merge", "Cluster merge")
    _, first = _ingest_failure(
        session,
        project,
        external_id="run-1",
        test_identity="first::failure",
        message="authorization failure",
        exception_type="AuthError",
        details={"http_status": 401},
    )
    _, second = _ingest_failure(
        session,
        project,
        external_id="run-2",
        test_identity="second::failure",
        message="database failure",
        exception_type="DatabaseError",
        details={"http_status": 500},
    )
    clusters = _active_clusters(session, project.id)
    assert len(clusters) == 2
    source, target = clusters
    review_cluster(
        session,
        source,
        actor="reviewer@example.test",
        decision="merge",
        reason="External incident record confirms a shared upstream outage",
        expected_revision=source.current_revision,
        target_cluster_id=target.id,
    )
    session.refresh(source)
    session.refresh(target)
    assert source.status == "superseded"
    assert source.superseded_by_cluster_id == target.id
    assert source.member_count == 0
    assert target.member_count == 2
    assert {item.failure_id for item in _current_members(session, target)} == {
        first.id,
        second.id,
    }
    event = session.scalar(
        select(ClusterMembershipDecision).where(
            ClusterMembershipDecision.cluster_id == source.id
        )
    )
    assert event is not None
    assert set(event.failure_ids) == {first.id}


def test_clusters_are_project_isolated(session) -> None:
    left = create_project(session, "cluster-left", "Cluster left")
    right = create_project(session, "cluster-right", "Cluster right")
    for project, external_id in ((left, "left-run"), (right, "right-run")):
        _ingest_failure(
            session,
            project,
            external_id=external_id,
            test_identity="shared::failure",
            message="identical failure across projects",
            exception_type="SharedError",
        )
    left_cluster = _active_clusters(session, left.id)[0]
    right_cluster = _active_clusters(session, right.id)[0]
    assert left_cluster.id != right_cluster.id
    assert left_cluster.project_id != right_cluster.project_id
    assert left_cluster.cluster_key == right_cluster.cluster_key


def test_pairwise_cluster_metrics_reports_false_merges_and_splits() -> None:
    truth = {"a": "i1", "b": "i1", "c": "i2", "d": "i2"}
    perfect = pairwise_cluster_metrics(truth, truth)
    assert perfect["pairwise_precision"] == 1.0
    assert perfect["pairwise_recall"] == 1.0
    assert perfect["adjusted_rand_index"] == 1.0
    assert perfect["missing_predictions"] == 0

    predicted = {"a": "p1", "b": "p2", "c": "p2", "d": "p2"}
    measured = pairwise_cluster_metrics(predicted, truth)
    assert measured["false_merges"] > 0
    assert measured["false_splits"] > 0

    missing = pairwise_cluster_metrics({"a": "i1"}, truth)
    assert missing["case_count"] == 4
    assert missing["missing_predictions"] == 3
    assert missing["pairwise_recall"] < 1.0


def test_large_exact_fingerprint_block_uses_bounded_star_candidates() -> None:
    features = [
        replace(
            _feature(f"failure-{index:03d}"),
            strict_fingerprint="shared-strict-fingerprint",
        )
        for index in range(205)
    ]

    candidate_pairs = generate_candidate_pairs(features)
    strict_pairs = [
        pair
        for pair, reasons in candidate_pairs.items()
        if "strict:shared-strict-fingerprint" in reasons
    ]
    assert len(strict_pairs) == 204

    proposals = propose_clusters_from_features(features)
    assert len(proposals) == 1
    assert len(proposals[0].members) == 205
