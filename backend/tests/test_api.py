def test_api_vertical_slice(client) -> None:
    project_response = client.post("/api/v1/projects", json={"slug": "api-project", "name": "API Project"})
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]
    ingestion = client.post(
        f"/api/v1/projects/{project_id}/ingestions",
        json={
            "external_id": "workflow-77",
            "repository": "owner/repo",
            "commit_sha": "abcdef0",
            "expected_inputs": 1,
            "observations": [{
                "test_identity": "payments::duplicate",
                "outcome": "failed",
                "message": "duplicate committed transfer caused ledger unbalanced",
                "details": {"data_integrity_violation": True},
            }],
        },
    )
    assert ingestion.status_code == 202
    run_id = ingestion.json()["id"]
    failures = client.get(f"/api/v1/runs/{run_id}/failures").json()
    assert len(failures) == 1
    analysis = client.post(f"/api/v1/failures/{failures[0]['id']}/analyses")
    assert analysis.status_code == 201
    assert analysis.json()["category"] == "product_defect"
    review = client.post(
        f"/api/v1/analyses/{analysis.json()['analysis_id']}/reviews",
        json={"decision": "accept", "reason": "Evidence demonstrates the duplicate committed effect", "expected_version": 0},
    )
    assert review.status_code == 201
    assert review.json()["version"] == 1


def test_health(client) -> None:
    assert client.get("/health/live").json() == {"status": "live"}
    assert client.get("/health/ready").json() == {"status": "ready"}


def test_overview_and_demo_seed(client) -> None:
    assert client.get("/api/v1/overview").json()["runs"] == 0
    seeded = client.post("/api/v1/demo/seed")
    assert seeded.status_code == 200
    overview = client.get("/api/v1/overview").json()
    assert overview["projects"] == 1
    assert overview["runs"] == 1
    assert overview["failures"] == 3
    assert overview["clusters"] == 2
    assert overview["analyses"] == 3
    clusters = client.get(
        f"/api/v1/projects/{seeded.json()['project_id']}/clusters"
    ).json()
    assert sorted(item["member_count"] for item in clusters) == [1, 2]


def test_evidence_endpoint_exposes_only_safe_derivative_metadata(client, session) -> None:
    from sqlalchemy import select

    from failurelens.models import Evidence, Failure

    project_response = client.post(
        "/api/v1/projects",
        json={"slug": "evidence-project", "name": "Evidence Project"},
    )
    project_id = project_response.json()["id"]
    ingestion = client.post(
        f"/api/v1/projects/{project_id}/ingestions",
        json={
            "external_id": "evidence-run",
            "observations": [
                {
                    "test_identity": "ledger::evidence",
                    "outcome": "failed",
                    "message": "duplicate committed transfer left ledger unbalanced",
                    "details": {"data_integrity_violation": True},
                }
            ],
        },
    )
    run_id = ingestion.json()["id"]
    failure = session.scalar(select(Failure).where(Failure.run_id == run_id))
    assert failure is not None
    analysis = client.post(f"/api/v1/failures/{failure.id}/analyses").json()
    evidence_id = analysis["supporting_evidence_ids"][0]

    response = client.get(f"/api/v1/evidence/{evidence_id}")
    assert response.status_code == 200
    body = response.json()
    evidence = session.get(Evidence, evidence_id)
    assert evidence is not None
    assert body["execution_id"] == failure.execution_id
    assert body["run_input_id"] == evidence.run_input_id
    assert body["provenance_kind"] == "current_execution"
    assert body["locator_version"] == "evidence-locator-v2"
    assert body["derivative"]["digest"] == body["content_digest"]
    assert body["derivative"]["approval_state"] == "auto_approved_text"
    assert "storage_path" not in body["derivative"]

    evidence.derivative.restricted = True
    session.commit()
    restricted = client.get(f"/api/v1/evidence/{evidence_id}")
    assert restricted.status_code == 403


def test_cluster_api_exposes_explanations_revisions_and_review(client) -> None:
    project = client.post(
        "/api/v1/projects",
        json={"slug": "cluster-api", "name": "Cluster API"},
    ).json()
    run_ids: list[str] = []
    failure_ids: list[str] = []
    for index, browser in enumerate(("chromium", "firefox"), start=1):
        response = client.post(
            f"/api/v1/projects/{project['id']}/ingestions",
            json={
                "external_id": f"cluster-run-{index}",
                "repository": "owner/repo",
                "commit_sha": "abcdef0",
                "observations": [
                    {
                        "test_identity": "checkout::payment",
                        "source_path": "tests/checkout.spec.ts",
                        "browser": browser,
                        "outcome": "failed",
                        "message": f"request failed at src/checkout.ts:{100 + index}",
                        "exception_type": "CheckoutError",
                        "details": {
                            "route": "/api/payments/12345",
                            "method": "POST",
                            "stack_frames": [f"src/checkout.ts:{100 + index}"],
                        },
                    }
                ],
            },
        )
        assert response.status_code == 202
        run_id = response.json()["id"]
        run_ids.append(run_id)
        failure_ids.append(client.get(f"/api/v1/runs/{run_id}/failures").json()[0]["id"])

    overview = client.get("/api/v1/overview").json()
    assert overview["clusters"] == 1
    clusters = client.get(f"/api/v1/projects/{project['id']}/clusters").json()
    assert len(clusters) == 1
    paged_clusters = client.get(
        f"/api/v1/projects/{project['id']}/clusters?limit=1&offset=0"
    ).json()
    assert [item["id"] for item in paged_clusters] == [clusters[0]["id"]]
    cluster = clusters[0]
    assert cluster["member_count"] == 2
    assert cluster["representative_test_identity"] == "checkout::payment"

    run_clusters = client.get(
        f"/api/v1/runs/{run_ids[0]}/clusters?limit=1&offset=0"
    )
    assert run_clusters.status_code == 200
    assert [item["id"] for item in run_clusters.json()] == [cluster["id"]]

    detail = client.get(f"/api/v1/clusters/{cluster['id']}").json()
    assert detail["current"]["member_count"] == 2
    assert len(detail["current"]["memberships"]) == 2
    member = next(
        item for item in detail["current"]["memberships"] if item["role"] == "member"
    )
    assert member["similarity_score"] >= 0.62
    assert member["score_components"]
    assert member["matching_signals"]

    revisions = client.get(f"/api/v1/clusters/{cluster['id']}/revisions")
    assert revisions.status_code == 200
    assert [item["revision"] for item in revisions.json()] == [2, 1]
    revision_page = client.get(
        f"/api/v1/clusters/{cluster['id']}/revisions?limit=1&offset=1"
    )
    assert revision_page.status_code == 200
    assert [item["revision"] for item in revision_page.json()] == [1]

    split = client.post(
        f"/api/v1/clusters/{cluster['id']}/reviews",
        json={
            "decision": "split",
            "reason": "One failure has separately verified ownership",
            "expected_revision": detail["current_revision"],
            "failure_ids": [failure_ids[-1]],
        },
    )
    assert split.status_code == 201
    assert split.json()["member_count"] == 1
    assert split.json()["decisions"][0]["decision"] == "split"

    active = client.get(f"/api/v1/projects/{project['id']}/clusters").json()
    assert len(active) == 2
    assert sorted(item["member_count"] for item in active) == [1, 1]

    stale = client.post(
        f"/api/v1/clusters/{cluster['id']}/reviews",
        json={
            "decision": "confirm",
            "reason": "Stale request should be rejected",
            "expected_revision": detail["current_revision"],
        },
    )
    assert stale.status_code == 409


def test_cluster_detail_includes_incoming_merge_decision(client) -> None:
    project = client.post(
        "/api/v1/projects",
        json={"slug": "cluster-merge-api", "name": "Cluster merge API"},
    ).json()
    for external_id, test_identity, message, exception_type, status in (
        ("merge-run-auth", "api::auth", "authorization failed", "AuthError", 401),
        ("merge-run-db", "api::database", "database failed", "DatabaseError", 500),
    ):
        response = client.post(
            f"/api/v1/projects/{project['id']}/ingestions",
            json={
                "external_id": external_id,
                "observations": [
                    {
                        "test_identity": test_identity,
                        "outcome": "failed",
                        "message": message,
                        "exception_type": exception_type,
                        "details": {"http_status": status},
                    }
                ],
            },
        )
        assert response.status_code == 202

    clusters = client.get(f"/api/v1/projects/{project['id']}/clusters").json()
    assert len(clusters) == 2
    source, target = clusters
    merged = client.post(
        f"/api/v1/clusters/{source['id']}/reviews",
        json={
            "decision": "merge",
            "reason": "A reviewed incident record links both observations",
            "expected_revision": source["current_revision"],
            "target_cluster_id": target["id"],
        },
    )
    assert merged.status_code == 201
    assert merged.json()["status"] == "superseded"

    target_detail = client.get(f"/api/v1/clusters/{target['id']}")
    assert target_detail.status_code == 200
    decisions = target_detail.json()["decisions"]
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "merge"
    assert decisions[0]["cluster_id"] == source["id"]
    assert decisions[0]["target_cluster_id"] == target["id"]


def test_run_detail_envelope_matches_openapi_and_lifecycle_fields(client, session) -> None:
    from datetime import timedelta
    from failurelens.models import Run, utcnow
    from failurelens.schemas import RunDetailRead

    seeded = client.post('/api/v1/demo/seed').json()
    run = session.get(Run, seeded['run_id'])
    run.evidence_expired_at = utcnow() - timedelta(seconds=1)
    session.commit()
    response = client.get(f"/api/v1/runs/{run.id}")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {'run', 'failure_types', 'failure_count'}
    parsed = RunDetailRead.model_validate(payload)
    assert parsed.run.id == run.id
    assert parsed.run.project_id == seeded['project_id']
    assert parsed.run.evidence_expired_at is not None
    assert parsed.failure_count == 3
    schema = client.get('/openapi.json').json()
    response_schema = schema['paths']['/api/v1/runs/{run_id}']['get']['responses']['200']['content']['application/json']['schema']
    assert response_schema['$ref'] == '#/components/schemas/RunDetailRead'


def test_demo_seed_returns_its_own_run_when_newer_runs_exist(client) -> None:
    seeded = client.post('/api/v1/demo/seed').json()
    newer = client.post(f"/api/v1/projects/{seeded['project_id']}/ingestions", json={
        'external_id': 'newer-non-demo-run',
        'observations': [{'test_identity': 'passing-control', 'outcome': 'passed'}],
    })
    assert newer.status_code == 202
    assert newer.json()['id'] != seeded['run_id']
    repeated = client.post('/api/v1/demo/seed')
    assert repeated.status_code == 200
    assert repeated.json() == seeded
    assert client.get(f"/api/v1/runs/{seeded['run_id']}").json()['failure_count'] == 3


def test_run_detail_keeps_failures_without_exception_types(client) -> None:
    project = client.post('/api/v1/projects', json={'slug': 'untyped-failure', 'name': 'Untyped'}).json()
    response = client.post(f"/api/v1/projects/{project['id']}/ingestions", json={
        'external_id': 'missing-exception-type',
        'observations': [{'test_identity': 'unknown-error', 'outcome': 'failed', 'message': 'ambiguous failure'}],
    })
    assert response.status_code == 202
    detail = client.get(f"/api/v1/runs/{response.json()['id']}")
    assert detail.status_code == 200
    assert detail.json()['failure_count'] == 1
    assert sum(detail.json()['failure_types'].values()) == 1
