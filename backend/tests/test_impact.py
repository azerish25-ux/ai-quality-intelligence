from __future__ import annotations

import hashlib
import json

import pytest
from sqlalchemy import select

from failurelens.models import (
    ImpactMappingSnapshot,
    ImpactOverride,
    ImpactRecommendation,
    Project,
    Run,
    RunInput,
    RunStatus,
)

BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _project(client, slug: str = "impact-project") -> dict:
    response = client.post(
        "/api/v1/projects", json={"slug": slug, "name": slug.replace("-", " ").title()}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _run_with_changes(
    session,
    project_id: str,
    *,
    files: list[dict],
    complete: bool = True,
    trust: str = "trusted_workflow",
    base_sha: str | None = BASE_SHA,
    head_sha: str | None = HEAD_SHA,
    run_base_sha: str | None = BASE_SHA,
    run_head_sha: str | None = HEAD_SHA,
    warnings: list[str] | None = None,
    external_id: str = "impact-run",
) -> tuple[Run, RunInput]:
    manifest = _digest({"external_id": external_id, "files": files})
    run = Run(
        project_id=project_id,
        external_id=external_id,
        attempt=1,
        repository="owner/repo",
        commit_sha=run_head_sha,
        base_sha=run_base_sha,
        branch="feature/impact",
        framework="changed-files",
        run_scope="full_suite",
        status=RunStatus.complete,
        completeness="complete",
        expected_inputs=1,
        received_inputs=1,
        manifest_digest=manifest,
        source_metadata={"origin": "controlled-test"},
    )
    session.add(run)
    session.flush()
    metadata = {
        "producer": "changed-files",
        "base_sha": base_sha,
        "head_sha": head_sha,
        "complete": complete,
        "trust": trust,
        "pagination": {"complete": complete},
        "files": files,
        "file_count": len(files),
    }
    changed_input = RunInput(
        project_id=project_id,
        run_id=run.id,
        input_id="changed-files",
        kind="changed-files",
        path="changed-files.json",
        required=True,
        status="accepted",
        digest=_digest(metadata),
        size_bytes=256,
        media_type="application/json",
        parser_version="changed-files-v1",
        warnings=warnings or [],
        metadata_json=metadata,
    )
    session.add(changed_input)
    session.commit()
    return run, changed_input


def _mapping_payload(
    *,
    version: str = "mapping-v1",
    trusted: bool = True,
    coverage_complete: bool = True,
    dependency: bool = False,
) -> dict:
    edges = [
        {
            "source_path": "src/checkout.py",
            "target_type": "test",
            "target_value": "checkout",
            "kind": "coverage",
            "confidence": 0.96,
            "mapping_source": "coverage.py",
            "mapping_version": "coverage-2026-09-27",
            "metadata": {"lines": [10, 11]},
        }
    ]
    if dependency:
        edges = [
            {
                "source_path": "src/core.py",
                "target_type": "file",
                "target_value": "src/checkout.py",
                "kind": "dependency",
                "confidence": 0.93,
                "mapping_source": "import-graph",
                "mapping_version": "imports-v1",
            },
            *edges,
        ]
    return {
        "version": version,
        "policy_version": "impact-policy-v1",
        "trusted": trusted,
        "coverage_complete": coverage_complete,
        "source_metadata": {"generator": "controlled-test", "trusted_revision": HEAD_SHA},
        "tests": [
            {
                "test_key": "smoke",
                "test_identity": "tests/smoke.spec.ts::critical smoke",
                "source_path": "tests/smoke.spec.ts",
                "criticality": "critical",
                "mandatory": True,
                "tags": ["smoke", "security"],
                "estimated_duration_ms": 500,
            },
            {
                "test_key": "checkout",
                "test_identity": "tests/checkout.spec.ts::submits payment",
                "source_path": "tests/checkout.spec.ts",
                "criticality": "high",
                "mandatory": False,
                "tags": ["checkout"],
                "estimated_duration_ms": 1000,
            },
            {
                "test_key": "unrelated",
                "test_identity": "tests/profile.spec.ts::updates avatar",
                "source_path": "tests/profile.spec.ts",
                "criticality": "normal",
                "mandatory": False,
                "tags": ["profile"],
                "estimated_duration_ms": 2000,
            },
        ],
        "edges": edges,
    }


def _create_mapping(client, project_id: str, **kwargs) -> dict:
    response = client.post(
        f"/api/v1/projects/{project_id}/impact-mappings",
        json=_mapping_payload(**kwargs),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_recommendation(
    client,
    project_id: str,
    run: Run,
    mapping: dict,
    *,
    pin_run_shas: bool = True,
) -> dict:
    payload = {
        "run_id": run.id,
        "mapping_snapshot_id": mapping["id"],
    }
    if pin_run_shas:
        payload.update({"base_sha": run.base_sha, "head_sha": run.commit_sha})
    response = client.post(
        f"/api/v1/projects/{project_id}/impact-recommendations",
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_focused_selection_is_explainable_persisted_and_override_audited(
    client, session
) -> None:
    project = _project(client)
    run, changed_input = _run_with_changes(
        session,
        project["id"],
        files=[{"status": "modified", "path": "src/checkout.py"}],
    )
    mapping = _create_mapping(client, project["id"])

    recommendation = _create_recommendation(client, project["id"], run, mapping)
    assert recommendation["status"] == "FOCUSED_SUBSET"
    assert recommendation["full_suite_required"] is False
    assert recommendation["comparison_trusted"] is True
    assert recommendation["mapping_complete"] is True
    assert recommendation["base_sha"] == BASE_SHA
    assert recommendation["head_sha"] == HEAD_SHA
    assert recommendation["changed_input_id"] == changed_input.id
    assert [item["test_key"] for item in recommendation["selected_tests"]] == [
        "smoke",
        "checkout",
    ]
    assert [item["test_key"] for item in recommendation["excluded_tests"]] == [
        "unrelated"
    ]
    checkout = next(
        item for item in recommendation["selected_tests"] if item["test_key"] == "checkout"
    )
    assert "mapping:coverage" in checkout["reason_codes"]
    assert checkout["mapping_edge_ids"]
    assert checkout["reasons"][0]["mapping_version"] == "coverage-2026-09-27"
    assert recommendation["metrics"]["base_selected_fraction"] == pytest.approx(2 / 3)
    assert recommendation["metrics"]["estimated_duration_reduction_ms"] == 2000

    repeated = _create_recommendation(client, project["id"], run, mapping)
    assert repeated["id"] == recommendation["id"]
    assert len(session.scalars(select(ImpactRecommendation)).all()) == 1

    listed = client.get(
        f"/api/v1/projects/{project['id']}/impact-recommendations"
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [recommendation["id"]]
    fetched = client.get(
        f"/api/v1/impact-recommendations/{recommendation['id']}"
    )
    assert fetched.status_code == 200
    assert fetched.json()["input_digest"] == recommendation["input_digest"]
    overview = client.get("/api/v1/overview").json()
    assert overview["impact_recommendations"] == 1

    include = client.post(
        f"/api/v1/impact-recommendations/{recommendation['id']}/overrides",
        json={
            "action": "include",
            "test_key": "unrelated",
            "reason": "The reviewer identified a release-risk coupling not yet represented in coverage.",
            "expected_revision": 0,
        },
    )
    assert include.status_code == 201, include.text
    included = include.json()
    assert included["current_revision"] == 1
    assert [item["test_key"] for item in included["selected_tests"]] == [
        "smoke",
        "checkout",
        "unrelated",
    ]
    overridden = next(
        item for item in included["selected_tests"] if item["test_key"] == "unrelated"
    )
    assert overridden["selection_source"].startswith("override:")
    assert included["overrides"][0]["actor"] == "Synthetic demo administrator"
    assert included["overrides"][0]["revision_before"] == 0
    assert included["overrides"][0]["revision_after"] == 1

    stale = client.post(
        f"/api/v1/impact-recommendations/{recommendation['id']}/overrides",
        json={
            "action": "exclude",
            "test_key": "checkout",
            "reason": "This deliberately uses the stale revision to verify optimistic concurrency.",
            "expected_revision": 0,
        },
    )
    assert stale.status_code == 409
    assert "revision conflict" in stale.json()["detail"]

    mandatory_exclusion = client.post(
        f"/api/v1/impact-recommendations/{recommendation['id']}/overrides",
        json={
            "action": "exclude",
            "test_key": "smoke",
            "reason": "Attempt to remove a mandatory critical test must be rejected.",
            "expected_revision": 1,
        },
    )
    assert mandatory_exclusion.status_code == 409
    assert "mandatory critical" in mandatory_exclusion.json()["detail"]
    assert len(session.scalars(select(ImpactOverride)).all()) == 1


def test_reverse_dependency_and_renamed_old_path_select_impacted_test(client, session) -> None:
    project = _project(client, "impact-dependency")
    run, _ = _run_with_changes(
        session,
        project["id"],
        external_id="impact-dependency-run",
        files=[
            {
                "status": "renamed",
                "path": "src/core-renamed.py",
                "old_path": "src/core.py",
            }
        ],
    )
    mapping = _create_mapping(client, project["id"], dependency=True)
    recommendation = _create_recommendation(client, project["id"], run, mapping)

    assert recommendation["status"] == "FOCUSED_SUBSET"
    assert {item["test_key"] for item in recommendation["selected_tests"]} == {
        "smoke",
        "checkout",
    }
    checkout = next(
        item for item in recommendation["selected_tests"] if item["test_key"] == "checkout"
    )
    mapping_reason = next(
        reason for reason in checkout["reasons"] if reason["code"] == "mapping:coverage"
    )
    assert mapping_reason["changed_path"] == "src/core.py"
    assert mapping_reason["dependency_chain"] == ["src/core.py", "src/checkout.py"]


@pytest.mark.parametrize(
    ("files", "trust", "complete", "mapping_trusted", "coverage_complete", "expected_reason"),
    [
        (
            [{"status": "modified", "path": "src/checkout.py"}],
            "self_reported",
            True,
            True,
            True,
            "changed_file_list_untrusted",
        ),
        (
            [{"status": "modified", "path": "src/checkout.py"}],
            "trusted_workflow",
            False,
            True,
            True,
            "changed_file_list_incomplete",
        ),
        (
            [{"status": "modified", "path": "src/unknown.py"}],
            "trusted_workflow",
            True,
            True,
            True,
            "unmapped_changed_files",
        ),
        (
            [{"status": "modified", "path": ".github/workflows/ci.yml"}],
            "trusted_workflow",
            True,
            True,
            True,
            "critical_ci_migration_or_test_infrastructure_changed",
        ),
        (
            [{"status": "modified", "path": "src/checkout.py"}],
            "trusted_workflow",
            True,
            False,
            True,
            "mapping_snapshot_untrusted",
        ),
        (
            [{"status": "modified", "path": "src/checkout.py"}],
            "trusted_workflow",
            True,
            True,
            False,
            "mapping_coverage_incomplete",
        ),
    ],
)
def test_incomplete_untrusted_critical_or_unmapped_inputs_force_full_suite(
    client,
    session,
    files,
    trust,
    complete,
    mapping_trusted,
    coverage_complete,
    expected_reason,
) -> None:
    project = _project(client, f"fallback-{expected_reason[:24].replace('_', '-')}")
    run, _ = _run_with_changes(
        session,
        project["id"],
        external_id=f"run-{expected_reason}",
        files=files,
        trust=trust,
        complete=complete,
        warnings=[] if complete else ["changed_file_list_incomplete"],
    )
    mapping = _create_mapping(
        client,
        project["id"],
        trusted=mapping_trusted,
        coverage_complete=coverage_complete,
    )
    recommendation = _create_recommendation(client, project["id"], run, mapping)

    assert recommendation["status"] == "FULL_SUITE_REQUIRED"
    assert recommendation["full_suite_required"] is True
    assert expected_reason in recommendation["safety_reasons"]
    assert {item["test_key"] for item in recommendation["selected_tests"]} == {
        "smoke",
        "checkout",
        "unrelated",
    }
    assert recommendation["excluded_tests"] == []

    forbidden_exclusion = client.post(
        f"/api/v1/impact-recommendations/{recommendation['id']}/overrides",
        json={
            "action": "exclude",
            "test_key": "unrelated",
            "reason": "A full-suite safety fallback must not be weakened by an override.",
            "expected_revision": 0,
        },
    )
    assert forbidden_exclusion.status_code == 409
    assert "full-suite execution is required" in forbidden_exclusion.json()["detail"]


def test_mapping_versions_are_immutable_and_paths_are_validated(client) -> None:
    project = _project(client, "impact-mapping-validation")
    first = _create_mapping(client, project["id"])
    repeated = _create_mapping(client, project["id"])
    assert repeated["id"] == first["id"]

    changed = _mapping_payload()
    changed["tests"][1]["test_identity"] = "tests/checkout.spec.ts::different identity"
    conflict = client.post(
        f"/api/v1/projects/{project['id']}/impact-mappings", json=changed
    )
    assert conflict.status_code == 422
    assert "immutable content" in conflict.json()["detail"]

    unsafe = _mapping_payload(version="mapping-unsafe")
    unsafe["edges"][0]["source_path"] = "../secrets.txt"
    response = client.post(
        f"/api/v1/projects/{project['id']}/impact-mappings", json=unsafe
    )
    assert response.status_code == 422
    assert "unsafe repository path" in response.json()["detail"]

    unknown_test = _mapping_payload(version="mapping-unknown-test")
    unknown_test["edges"][0]["target_value"] = "not-in-catalog"
    response = client.post(
        f"/api/v1/projects/{project['id']}/impact-mappings", json=unknown_test
    )
    assert response.status_code == 422
    assert "unknown test key" in response.json()["detail"]

    invalid_dependency = _mapping_payload(version="mapping-invalid-dependency")
    invalid_dependency["edges"][0]["kind"] = "dependency"
    response = client.post(
        f"/api/v1/projects/{project['id']}/impact-mappings",
        json=invalid_dependency,
    )
    assert response.status_code == 422
    assert "dependency edges must target" in response.json()["detail"]

    snapshots = client.get(
        f"/api/v1/projects/{project['id']}/impact-mappings"
    ).json()
    assert [item["id"] for item in snapshots] == [first["id"]]
    assert len(client.get(f"/api/v1/projects/{project['id']}/impact-mappings?limit=1&offset=1").json()) == 0


def test_project_and_run_isolation_prevent_cross_project_impact_analysis(
    client, session
) -> None:
    project_a = _project(client, "impact-isolation-a")
    project_b = _project(client, "impact-isolation-b")
    run_a, _ = _run_with_changes(
        session,
        project_a["id"],
        files=[{"status": "modified", "path": "src/checkout.py"}],
    )
    mapping_b = _create_mapping(client, project_b["id"])

    response = client.post(
        f"/api/v1/projects/{project_a['id']}/impact-recommendations",
        json={"run_id": run_a.id, "mapping_snapshot_id": mapping_b["id"]},
    )
    assert response.status_code == 422
    assert "mapping snapshot does not belong" in response.json()["detail"]

    missing = client.get("/api/v1/impact-recommendations/not-a-real-id")
    assert missing.status_code == 404


def test_mismatched_base_or_head_never_yields_focused_subset(client, session) -> None:
    project = _project(client, "impact-sha-mismatch")
    run, _ = _run_with_changes(
        session,
        project["id"],
        files=[{"status": "modified", "path": "src/checkout.py"}],
        run_head_sha="3" * 40,
    )
    mapping = _create_mapping(client, project["id"])
    recommendation = _create_recommendation(
        client, project["id"], run, mapping, pin_run_shas=False
    )
    assert recommendation["status"] == "FULL_SUITE_REQUIRED"
    assert "run_head_sha_mismatch" in recommendation["safety_reasons"]

def test_requested_comparison_sha_must_match_changed_file_evidence(client, session) -> None:
    project = _project(client, "impact-request-sha-mismatch")
    run, _ = _run_with_changes(
        session,
        project["id"],
        files=[{"status": "modified", "path": "src/checkout.py"}],
    )
    mapping = _create_mapping(client, project["id"])
    response = client.post(
        f"/api/v1/projects/{project['id']}/impact-recommendations",
        json={
            "run_id": run.id,
            "mapping_snapshot_id": mapping["id"],
            "base_sha": "4" * 40,
            "head_sha": HEAD_SHA,
        },
    )
    assert response.status_code == 422
    assert "requested base SHA does not match" in response.json()["detail"]
