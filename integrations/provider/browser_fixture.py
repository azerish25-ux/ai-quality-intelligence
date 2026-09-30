"""Trusted, disposable browser fixture using the actual API and durable worker.

The injected MockTransport exists only in this executable fixture. There is no
application flag, endpoint or request parameter that enables a test provider.
Metadata contains local synthetic login data and MUST NOT be uploaded as an artifact.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path
from uuid import uuid4

import httpx
import uvicorn
from pydantic import SecretStr
from sqlalchemy import select


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-disposable-database", action="store_true", required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    from failurelens.config import get_settings

    if get_settings().demo_mode:
        raise SystemExit(
            "Provider browser fixtures require production authentication: FAILURELENS_DEMO_MODE=false."
        )
    if not get_settings().session_cookie_secure:
        raise SystemExit("Provider browser fixtures require secure session cookies.")
    # These generated credentials are for the empty disposable fixture only.
    # Production authentication and its normal validation remain enabled.
    os.environ["FAILURELENS_BOOTSTRAP_ADMIN_USERNAME"] = (
        f"fixture-bootstrap-{uuid4().hex}"
    )
    os.environ["FAILURELENS_BOOTSTRAP_ADMIN_PASSWORD"] = (
        f"synthetic-bootstrap-{uuid4().hex}"
    )
    get_settings.cache_clear()
    get_settings().validate_security()
    from failurelens import models as m
    from failurelens.auth import create_user
    from failurelens.db import SessionLocal, initialize_database
    from failurelens.schemas import IngestionRequest
    from failurelens.service import (
        analyze_and_persist,
        create_project,
        ingest_normalized,
    )

    initialize_database()
    with SessionLocal() as session:
        if (
            session.scalar(select(m.Project.id).limit(1)) is not None
            or session.scalar(select(m.User.id).limit(1)) is not None
        ):
            raise SystemExit(
                "Provider browser fixtures require an empty disposable database."
            )
    fixtures = {}
    project_ids = []
    for browser in (
        "provider-chromium-desktop",
        "provider-chromium-narrow",
    ):
        for retry in (0, 1):
            with SessionLocal() as session:
                unique = uuid4().hex
                project = create_project(
                    session,
                    f"provider-browser-{unique}",
                    f"Provider fixture {browser} {retry}",
                )
                project_ids.append(project.id)
                password = f"synthetic-browser-{uuid4().hex}"
                admin = create_user(
                    session,
                    username=f"provider-admin-{unique}",
                    display_name="Provider browser administrator",
                    password=password,
                )
                viewer = create_user(
                    session,
                    username=f"provider-viewer-{unique}",
                    display_name="Provider browser viewer",
                    password=password,
                )
                session.add_all(
                    [
                        m.ProjectMembership(
                            project_id=project.id,
                            user_id=admin.id,
                            role=m.ProjectRole.administrator,
                        ),
                        m.ProjectMembership(
                            project_id=project.id,
                            user_id=viewer.id,
                            role=m.ProjectRole.viewer,
                        ),
                    ]
                )
                session.commit()
                entry = {
                    "project_id": project.id,
                    "username": admin.username,
                    "password": password,
                    "viewer_username": viewer.username,
                    "viewer_password": password,
                }
                for scenario in ("success", "outage", "cancel", "navigation"):
                    run = ingest_normalized(
                        session,
                        project,
                        IngestionRequest.model_validate(
                            {
                                "external_id": f"provider-{scenario}-{unique}",
                                "observations": [
                                    {
                                        "test_identity": f"provider-{scenario}",
                                        "outcome": "failed",
                                        "message": f"PROVIDER_BROWSER_{scenario.upper()}: assertion mismatch with no verified root cause",
                                    }
                                ],
                            }
                        ),
                    )
                    failure = session.scalar(
                        select(m.Failure).where(m.Failure.run_id == run.id)
                    )
                    analysis = analyze_and_persist(session, failure)
                    entry[scenario] = {
                        "run_id": run.id,
                        "failure_id": failure.id,
                        "analysis_id": analysis.id,
                    }
                fixtures[f"{browser}:{retry}"] = entry

    # API configuration contains no token. Only the injected worker receives this
    # synthetic sentinel; MockTransport cannot resolve or contact the destination.
    os.environ.update(
        {
            "FAILURELENS_PROVIDER_ENABLED": "true",
            "FAILURELENS_PROVIDER_ID": "browser-fixture",
            "FAILURELENS_PROVIDER_ALLOWED_PROJECT_IDS": ",".join(project_ids),
            "FAILURELENS_PROVIDER_ENDPOINT": "https://provider-fixture.invalid/v1/chat/completions",
            "FAILURELENS_PROVIDER_MODEL": "test-fixture-not-a-model",
            "FAILURELENS_PROVIDER_MAX_ATTEMPTS": "1",
            "FAILURELENS_PROVIDER_MIN_INTERVAL_SECONDS": "0",
            "FAILURELENS_PROVIDER_FAILURE_THRESHOLD": "20",
            "FAILURELENS_PROVIDER_MAX_RUN_REQUESTS": "5",
            "FAILURELENS_PROVIDER_MAX_RUN_RESERVED_TOKENS": "20000",
        }
    )
    os.environ.pop("FAILURELENS_PROVIDER_TOKEN", None)
    get_settings.cache_clear()
    settings = get_settings().model_copy(
        update={"provider_token": SecretStr("synthetic-fixture-not-a-credential")}
    )
    from failurelens.provider_jobs import heartbeat_provider_worker, run_provider_once
    from failurelens.providers import HTTPModelProvider

    def transport(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        context = json.loads(body["messages"][-1]["content"])
        excerpts = " ".join(item["excerpt"] for item in context["evidence"])
        if "PROVIDER_BROWSER_CANCEL" in excerpts:
            time.sleep(4)
        else:
            time.sleep(0.2)
        if "PROVIDER_BROWSER_OUTAGE" in excerpts:
            return httpx.Response(503, json={"error": "synthetic fixture unavailable"})
        proposal = {
            "category": "test_defect"
            if context["deterministic_category"] != "product_defect"
            else "product_defect",
            "hypotheses": [
                {
                    "text": 'Fixture hypothesis <img src=x onerror="window.providerInjected=true"> remains unverified.',
                    "evidence_ids": [context["evidence"][0]["id"]],
                }
            ],
            "contradictory_evidence_ids": [],
            "missing_evidence": ["Independent reproduction is missing"],
        }
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": json.dumps(proposal)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            },
        )

    stopped = threading.Event()

    def worker() -> None:
        while not stopped.is_set():
            worked = run_provider_once(
                SessionLocal,
                settings,
                provider_factory=lambda config: HTTPModelProvider(
                    config, transport=httpx.MockTransport(transport)
                ),
            )
            if not worked:
                stopped.wait(0.1)

    heartbeat_provider_worker(SessionLocal, settings)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as file:
        json.dump(fixtures, file)
    thread = threading.Thread(
        target=worker, name="provider-browser-fixture", daemon=True
    )
    thread.start()
    try:
        uvicorn.run(
            "failurelens.api:app", host="127.0.0.1", port=args.port, access_log=False
        )
    finally:
        stopped.set()
        thread.join(timeout=30)


if __name__ == "__main__":
    main()
