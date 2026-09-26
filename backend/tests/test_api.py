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
        json={"actor": "reviewer@example.test", "decision": "accept", "reason": "Evidence demonstrates the duplicate committed effect", "expected_version": 0},
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
    assert overview["failures"] == 2
    assert overview["analyses"] == 2
