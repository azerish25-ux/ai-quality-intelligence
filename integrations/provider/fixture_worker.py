"""Trusted synthetic worker fixture. This file is not in the application image."""

from __future__ import annotations

import argparse
import json
import signal
import threading

import httpx
from failurelens.config import get_settings
from failurelens.db import SessionLocal
from failurelens.provider_jobs import run_provider_once
from failurelens.providers import HTTPModelProvider, ProviderConfig

ENDPOINT = "https://provider.fixture.invalid/v1/chat/completions"
TOKEN = "synthetic-worker-only-canary-534"
PRIVATE = "synthetic-evidence-canary-935"
OUTAGE = "synthetic_outage_marker_706"


def response(request: httpx.Request) -> httpx.Response:
    assert str(request.url) == ENDPOINT
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert PRIVATE not in request.content.decode()
    payload = json.loads(request.content)
    assert payload["model"] == "test-fixture-not-a-model"
    context = json.loads(payload["messages"][1]["content"])
    if OUTAGE in json.dumps(context):
        raise httpx.ConnectError("synthetic-transport-canary-716", request=request)
    proposal = {
        "category": "product_defect",
        "hypotheses": [
            {
                "text": "Inspect the synthetic duplicate effect",
                "evidence_ids": [context["evidence"][0]["id"]],
            }
        ],
        "contradictory_evidence_ids": [],
        "missing_evidence": [],
    }
    return httpx.Response(
        200,
        json={
            "choices": [
                {"finish_reason": "stop", "message": {"content": json.dumps(proposal)}}
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        },
    )


def provider(config: ProviderConfig) -> HTTPModelProvider:
    # Trusted constructor injection keeps the configured digest intact, while
    # making actual HTTP requests impossible. No environment switch enables it.
    return HTTPModelProvider(config, transport=httpx.MockTransport(response))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-disposable-stack", action="store_true", required=True
    )
    parser.parse_args()
    settings = get_settings()
    config, state = settings.provider_configuration()
    assert state == "ready" and config is not None
    assert not settings.demo_mode and settings.session_cookie_secure
    assert config.endpoint == ENDPOINT and config.token == TOKEN
    assert config.model == "test-fixture-not-a-model"
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    print("provider_fixture_ready", flush=True)
    while not stop.is_set():
        if not run_provider_once(SessionLocal, settings, provider_factory=provider):
            stop.wait(0.1)


if __name__ == "__main__":
    main()
