"""Adversarial trace-boundary regressions; canaries are synthetic, not secrets."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from failurelens.config import get_settings
from failurelens.jobs import process_next
from failurelens.trace_evidence import _safe_event, _text, build_trace_index


def archive_for(*events: dict) -> bytes:
    stream = [
        {"type": "context-options", "version": 9, "playwrightVersion": "1.63.0"},
        *events,
    ]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "trace.trace", "\n".join(json.dumps(event) for event in stream) + "\n"
        )
    return output.getvalue()


@pytest.mark.parametrize(
    "label", ["PRIVATE KEY", "RSA PRIVATE KEY", "EC PRIVATE KEY", "OPENSSH PRIVATE KEY"]
)
def test_trace_redacts_entire_private_key_before_clipping(label):
    value = (
        f"-----BEGIN {label}-----\n"
        + "SYNTHETIC_KEY_CANARY" * 300
        + f"\n-----END {label}-----"
    )
    safe = _text(value, 240)
    assert "SYNTHETIC_KEY_CANARY" not in safe
    assert "REDACTED:private_key" in safe
    assert len(safe) <= 240


def test_trace_withholds_unterminated_key_instead_of_approving_its_prefix():
    safe = _text("Diagnostic\n-----BEGIN PRIVATE KEY-----\nSYNTHETIC_KEY_CANARY")
    assert "SYNTHETIC_KEY_CANARY" not in safe
    assert "private_key" in safe


def test_trace_text_clipping_is_explicit_bounded_and_after_redaction():
    safe = _text("prefix " * 1000, 240)
    assert len(safe) == 240 and safe.endswith("[TRUNCATED]")
    assert "\x1b" not in _text("\x1b[31mselector failed\x1b[0m")
    assert _text(None) == ""
    # The complete email extends across the old excerpt boundary.
    value = "x " * 115 + "contact@example.com"
    assert "contact@ex" not in _text(value, 240)


def test_trace_event_type_counts_never_publish_arbitrary_artifact_keys():
    metadata, warnings = build_trace_index(
        archive_for(
            {"type": "private-person@example.com"},
            {"type": "password=SYNTHETIC_TYPE_CANARY"},
            {"type": "before", "callId": "call@1", "apiName": "page.click"},
        ),
        get_settings(),
    )
    text = json.dumps(metadata)
    assert "private-person" not in text and "SYNTHETIC_TYPE_CANARY" not in text
    assert metadata["event_type_counts"] == {
        "context-options": 1,
        "unknown": 2,
        "before": 1,
    }
    assert metadata["event_count"] == 4 and metadata["indexed_events"] == 1
    assert "trace_unknown_event_types_omitted" in warnings
    assert metadata["text_policy"] == "trace-safe-text-v2.1"
    assert (
        metadata["events"][0]["source_locator"]["text_policy"]
        == metadata["text_policy"]
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://user:SYNTHETIC_URL_CANARY@[invalid/route",
        "https://user:SYNTHETIC_URL_CANARY@example.com/path?"
        + "&".join(f"key{i}=secret" for i in range(501)),
        "javascript:SYNTHETIC_URL_CANARY",
    ],
    ids=["invalid-ipv6", "excess-query-fields", "active-scheme"],
)
def test_trace_malformed_or_unsupported_urls_are_withheld(url):
    event = _safe_event(
        {"type": "resource-snapshot", "snapshot": {"request": {"url": url}}}
    )
    assert event["url"] == "[URL OMITTED]"
    assert "SYNTHETIC_URL_CANARY" not in json.dumps(event)


def test_trace_network_context_keeps_status_and_route_without_credentials():
    event = _safe_event(
        {
            "type": "resource-snapshot",
            "snapshot": {
                "request": {
                    "method": "GET",
                    "url": "https://user:SYNTHETIC_URL_CANARY@example.com:8443/orders?token=SYNTHETIC_TOKEN#private",
                },
                "response": {"status": 503},
                "time": 12,
            },
        }
    )
    assert (
        event["method"] == "GET"
        and event["status"] == 503
        and event["duration_ms"] == 12
    )
    assert "/orders?" in event["url"] and "example.com:8443" in event["url"]
    assert "SYNTHETIC" not in event["url"] and "#private" not in event["url"]


def test_trace_safe_index_and_cited_events_do_not_serve_boundary_canaries(
    client, session
):
    project = client.post(
        "/api/v1/projects", json={"slug": "trace-canaries", "name": "Trace canaries"}
    ).json()
    trace = archive_for(
        {"type": "password=SYNTHETIC_TYPE_CANARY"},
        {
            "type": "console",
            "text": "-----BEGIN PRIVATE KEY-----\n"
            + "SYNTHETIC_KEY_CANARY" * 300
            + "\n-----END PRIVATE KEY-----",
        },
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema_version": "2.0",
                    "inputs": [
                        {
                            "id": "trace",
                            "kind": "playwright-trace",
                            "path": "trace.zip",
                            "required": True,
                        }
                    ],
                }
            ),
        )
        archive.writestr("trace.zip", trace)
    queued = client.post(
        f"/api/v1/projects/{project['id']}/ingestions",
        params={"external_id": "trace-canaries", "filename": "bundle.zip"},
        content=output.getvalue(),
        headers={"Content-Type": "application/zip"},
    )
    assert queued.status_code == 202, queued.text
    assert process_next(session, "trace-canary-worker", settings=get_settings())
    finished = client.get(f"/api/v1/ingestions/{queued.json()['id']}").json()
    assert finished["state"] == "partial", finished
    items = client.get(f"/api/v1/runs/{finished['run_id']}/binary-evidence").json()[
        "items"
    ]
    assert len(items) == 1 and items[0]["state"] == "safe_index_available"
    events = client.get(
        f"/api/v1/binary-evidence/{items[0]['input_id']}/trace-events"
    ).json()
    urls = [f"/api/v1/artifact-derivatives/{items[0]['derivative']['id']}/content"]
    urls.extend(
        f"/api/v1/artifact-derivatives/{event['evidence_derivative_id']}/content"
        for event in events["events"]
    )
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200, response.text
        assert (
            "SYNTHETIC_KEY_CANARY" not in response.text
            and "SYNTHETIC_TYPE_CANARY" not in response.text
        )
    assert events["summary"]["text_policy"] == "trace-safe-text-v2.1"
    assert events["events"][0]["source_locator"]["line"] == 3
