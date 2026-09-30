"""Synthetic tests for the full-stack harness; not real LedgerGuard provenance."""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import os
import subprocess
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "integrations/ledgerguard"))
from fullstack import build_bundle, retry_proxy
from fullstack_oracle import verify_pair_observation
from test_transaction_evidence import observation

from evaluation.artifact_contract import validate_public_bundle
from evaluation.fullstack_harness import evaluate


def wire_for(value, count):
    effects = value["after"]["effects"]
    return [
        {
            "sequence": i,
            "logical_key_digest": value["requests"][i - 1]["logical_key_digest"],
            "intent_digest": value["requests"][i - 1]["intent_digest"],
            "forwarded_key_digest": ("c" if count == 1 or i == 1 else "d") * 64,
            "upstream_status": 201,
            "upstream_receipt_id": effects[0 if i == 1 else -1]["id"],
            "idempotency_replayed": "true" if count == 1 and i == 2 else "false",
        }
        for i in (1, 2)
    ]


@pytest.mark.parametrize("count", [1, 2])
def test_independent_oracle_agrees_with_actual_measurement_relations(count):
    value = observation(count)
    result = verify_pair_observation(
        value, wire_for(value, count), expected_effects=count
    )
    assert result["committed_effects"] == count
    assert result["single_effect_contract_passed"] == (count == 1)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda v, w: w[1].update(forwarded_key_digest=w[0]["forwarded_key_digest"]),
        lambda v, w: w[1].update(upstream_status=503),
        lambda v, w: w[1].update(upstream_receipt_id=w[0]["upstream_receipt_id"]),
        lambda v, w: w[1].update(idempotency_replayed="true"),
        lambda v, w: v["after"]["balances"][0].update(posted_minor=93),
        lambda v, w: v["after"]["entries"][1].update(amount_minor=8),
        lambda v, w: v["after"]["effects"].pop(),
        lambda v, w: v["requests"][1].update(intent_digest="f" * 64),
    ],
)
def test_independent_oracle_rejects_forged_wire_or_financial_measurements(mutation):
    value = observation(2)
    wire = wire_for(value, 2)
    mutation(value, wire)
    with pytest.raises(ValueError):
        verify_pair_observation(value, wire, expected_effects=2)


@pytest.mark.parametrize("corrupt", [False, True])
def test_proxy_really_loses_first_response_and_changes_only_faulty_retry_key(corrupt):
    """HTTP contract test with a deliberately synthetic receipt server, not LedgerGuard."""
    receipts = {}
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            assert self.path == "/api/v1/transfers"
            data = self.rfile.read(int(self.headers["Content-Length"]))
            key = self.headers["Idempotency-Key"]
            seen.append((key, data))
            replayed = key in receipts
            receipts.setdefault(
                key, {"id": f"30000000-0000-0000-0000-{len(receipts) + 1:012d}"}
            )
            encoded = json.dumps(receipts[key]).encode()
            self.send_response(201)
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Idempotency-Replayed", str(replayed).lower())
            self.end_headers()
            self.wfile.write(encoded)

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    try:
        with retry_proxy(upstream.server_port, corrupt) as proxy:
            for sequence in (1, 2):
                connection = http.client.HTTPConnection(
                    "127.0.0.1", proxy.server_port, timeout=5
                )
                connection.request(
                    "POST",
                    "/api/v1/transfers",
                    body=b'{"amountMinor":"7"}',
                    headers={
                        "Idempotency-Key": "same-logical-request",
                        "Cookie": "private-cookie",
                        "Content-Type": "application/json",
                    },
                )
                try:
                    if sequence == 1:
                        with pytest.raises(http.client.RemoteDisconnected):
                            connection.getresponse()
                    else:
                        response = connection.getresponse()
                        assert response.status == 201
                        response.read()
                finally:
                    connection.close()
            assert not proxy.errors and len(proxy.events) == 2
            assert len(receipts) == (2 if corrupt else 1)
            assert seen[0][1] == seen[1][1]
            assert (seen[0][0] != seen[1][0]) == corrupt
            assert "private-cookie" not in json.dumps(proxy.events)
            connection = http.client.HTTPConnection(
                "127.0.0.1", proxy.server_port, timeout=5
            )
            connection.request(
                "POST",
                "/api/v1/transfers",
                body=b"{}",
                headers={"Idempotency-Key": "third"},
            )
            response = connection.getresponse()
            assert response.status == 429
            response.read()
            connection.close()
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=5)


def test_replay_bundle_rejects_labels_tampering_duplicate_members_and_traversal():
    content = build_bundle(observation(2), wire_for(observation(2), 2))
    assert len(validate_public_bundle(content, 3)) == 3
    with zipfile.ZipFile(io.BytesIO(content)) as original:
        files = {i.filename: original.read(i) for i in original.infolist()}
    for mutation in ("label", "tamper", "duplicate", "path"):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            modified = dict(files)
            if mutation == "label":
                manifest = json.loads(files["manifest.json"])
                manifest["expected_category"] = "product_defect"
                modified["manifest.json"] = json.dumps(manifest).encode()
            elif mutation == "tamper":
                modified["measurements.json"] = b"{}"
            elif mutation == "path":
                modified["../labels.json"] = b"{}"
            for path, data in modified.items():
                archive.writestr(path, data)
            if mutation == "duplicate":
                with pytest.warns(UserWarning):
                    archive.writestr("report.xml", files["report.xml"])
        with pytest.raises(ValueError):
            validate_public_bundle(stream.getvalue(), 3)


def synthetic_corpus(root):
    root.mkdir()
    cases = []
    labels = []
    for number in range(4):
        case_id = f"c-{number:020x}"
        refs = []
        roles = []
        for role, count in [("control", 1), ("observation", 2)]:
            value = observation(count)
            # Random digests can contain phone-shaped digit runs; they are not PII.
            for request in value["requests"]:
                request["logical_key_digest"] = "a" * 24 + "4165550123" + "b" * 30
            wire = wire_for(value, count)
            content = build_bundle(value, wire)
            path = root / "inputs" / case_id / f"{count}.zip"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            sha = hashlib.sha256(content).hexdigest()
            refs.append(
                {
                    "role": role,
                    "path": f"{case_id}/{count}.zip",
                    "sha256": sha,
                    "bytes": len(content),
                    "source_format": "failurelens-bundle-v2",
                    "expected_inputs": 3,
                }
            )
            roles.append(
                {
                    "role": role,
                    "wire_requests": wire,
                    "oracle": verify_pair_observation(
                        value, wire, expected_effects=count
                    ),
                    "input_digest": sha,
                    "global_reconciliation": "PASS",
                    "expected_category": "product_defect"
                    if count == 2
                    else "insufficient_evidence",
                }
            )
        cases.append(
            {
                "case_id": case_id,
                "repository": "example/synthetic-test-only",
                "source_revision": "a" * 40,
                "inputs": refs,
            }
        )
        # Mocked ground truth tests scorer behavior, never retained as actual provenance.
        labels.append(
            {
                "case_id": case_id,
                "scenario_family_id": "lost-response-retry-key-corruption",
                "source_kind": "ledgerguard_executed",
                "split": "development",
                "roles": roles,
            }
        )
    (root / "inputs/manifest.json").write_text(
        json.dumps({"schema_version": "artifact-replay-v2", "cases": cases})
    )
    (root / "ground-truth.json").write_text(json.dumps(labels))
    (root / "provenance.json").write_text(
        json.dumps(
            {
                "source_dirty": False,
                "source_revision": "b" * 40,
                "ledgerguard_revision": "a" * 40,
                "limitations": ["SYNTHETIC UNIT TEST ONLY"],
            }
        )
    )


def test_bundle_replay_persists_real_api_decisions_and_scorer_rejects_forgery(tmp_path):
    corpus = tmp_path / "corpus"
    synthetic_corpus(corpus)
    env = {
        **os.environ,
        "FAILURELENS_DATABASE_URL": f"sqlite+pysqlite:///{tmp_path}/db.sqlite",
        "FAILURELENS_DEMO_MODE": "true",
        "FAILURELENS_ARTIFACT_ROOT": str(tmp_path / "private"),
    }
    replay = tmp_path / "replay"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "evaluation/replay.py"),
            "--inputs",
            str(corpus / "inputs"),
            "--output",
            str(replay),
            "--repeats",
            "5",
            "--confirm-disposable-database",
        ],
        check=False,
        env=env,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    metrics, rows = evaluate(corpus, replay)
    assert metrics["product_defect_recall"] == 1 and metrics["control_abstentions"] == 4
    assert (
        metrics["case_count"] == 8
        and metrics["family_count"] == 1
        and metrics["verified_numeric_evidence"] == 8
    )
    assert (
        metrics["integrity_acceptance"]["postgresql_pipeline"] is False
    )  # Never call SQLite a PostgreSQL execution.
    assert len(rows) == 8 and metrics["macro_f1"] is None
    original = (replay / "predictions.json").read_text()
    for mutation in (
        "repeats",
        "mix_roles",
        "claim",
        "bytes",
        "claim_text",
        "empty_claims",
        "input_roles",
    ):
        data = json.loads(original)
        if mutation == "repeats":
            data["cases"][0]["repeat_digests"]["observation"][0].pop()
        elif mutation == "mix_roles":
            data["cases"][0]["run_links"]["observation"] = data["cases"][0][
                "run_links"
            ]["control"]
        elif mutation == "claim":
            data["cases"][0]["role_analyses"]["observation"][0]["claims"][0][
                "predicate"
            ]["count"] = 3
        elif mutation == "bytes":
            data["cases"][0]["evidence"][0]["sha256"] = "0" * 64
        elif mutation == "input_roles":
            data["cases"][0]["inputs"][1]["role"] = "control"
        else:
            analysis = data["cases"][0]["role_analyses"]["observation"][0]
            if mutation == "claim_text":
                analysis["claims"][0]["text"] = (
                    "LedgerGuard is conclusively at fault; all other systems are safe."
                )
            else:
                analysis["claims"] = []
            from evaluation.fullstack_harness import SUBSTANTIVE

            recomputed = hashlib.sha256(
                json.dumps(
                    {key: analysis[key] for key in SUBSTANTIVE}, sort_keys=True
                ).encode()
            ).hexdigest()
            data["cases"][0]["repeat_digests"]["observation"] = [[recomputed] * 5]
        (replay / "predictions.json").write_text(json.dumps(data))
        with pytest.raises(ValueError):
            evaluate(corpus, replay)
    (replay / "predictions.json").write_text(original)


def test_fullstack_metrics_api_missing_corrupt_and_available(
    client, tmp_path, monkeypatch
):
    from failurelens.config import get_settings

    path = tmp_path / "metrics.json"
    monkeypatch.setenv("FAILURELENS_FULLSTACK_EVALUATION_METRICS_PATH", str(path))
    get_settings.cache_clear()
    assert client.get("/api/v1/evaluations/fullstack").json()["status"] == "not_loaded"
    path.write_text("{}")
    assert client.get("/api/v1/evaluations/fullstack").status_code == 503
    path.write_text(
        json.dumps({"evaluation_scope": "http_postgresql_fault_proxy", "case_count": 8})
    )
    response = client.get("/api/v1/evaluations/fullstack")
    assert response.status_code == 200 and response.json()["metrics"]["case_count"] == 8
    monkeypatch.setenv("FAILURELENS_DEMO_MODE", "false")
    get_settings.cache_clear()
    assert client.get("/api/v1/evaluations/fullstack").status_code == 401


@pytest.mark.parametrize(
    "response_body, expected_error",
    [
        (b"synthetic-invalid-json-canary", "JSONDecodeError"),
        (b'{"id": null, "secret": "synthetic-upstream-canary"}', "ValueError"),
    ],
)
def test_proxy_rejects_invalid_upstream_receipts_without_logging_body(
    response_body, expected_error
):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(201)
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    try:
        with retry_proxy(upstream.server_port, False) as proxy:
            connection = http.client.HTTPConnection(
                "127.0.0.1", proxy.server_port, timeout=5
            )
            try:
                connection.request(
                    "POST",
                    "/api/v1/transfers",
                    body=b"{}",
                    headers={"Idempotency-Key": "synthetic"},
                )
                response = connection.getresponse()
                assert response.status == 502
                response.read()
            finally:
                connection.close()
            assert proxy.errors == [expected_error]
            assert not proxy.events
            assert "canary" not in json.dumps(proxy.errors)
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=5)
    assert not thread.is_alive()
