from __future__ import annotations

import io
import json
import stat
import struct
import zipfile

import pytest

import failurelens.ingestion as ingestion
from failurelens.config import Settings, get_settings
from failurelens.ingestion import IngestionError, parse_artifact, parse_junit_xml, parse_playwright_json, parse_pytest_json


def _bundle(manifest: dict, files: dict[str, bytes | str]) -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for path, payload in files.items():
            archive.writestr(path, payload)
    return target.getvalue()


def _trace_zip(payload: bytes = b'{"type":"before"}\n') -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("trace.trace", payload)
    return target.getvalue()


def _jpeg(width: int, height: int) -> bytes:
    # Minimal SOI + baseline SOF segment; the adapter intentionally reads metadata only.
    return (
        b"\xff\xd8"
        + b"\xff\xc0"
        + b"\x00\x11"
        + b"\x08"
        + struct.pack(">HH", height, width)
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
        + b"\xff\xd9"
    )


def test_junit_preserves_properties_skips_and_captured_output() -> None:
    parsed = parse_junit_xml(
        b'''<testsuite name="api"><properties><property name="browser" value="firefox"/></properties><testcase classname="Status" name="offline" time="0.25" file="tests/status.py" line="9"><skipped message="maintenance"/><system-out>email=alice@example.com</system-out><system-err>warning</system-err></testcase></testsuite>'''
    )
    item = parsed[0]
    assert item.outcome == "skipped"
    assert item.duration_ms == pytest.approx(250)
    assert item.details["properties"] == {"browser": "firefox"}
    assert "alice@example.com" not in (item.evidence_excerpt or "")


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"<not-junit/>", "unsupported_format"),
        (b"<testsuite><testcase/></testsuite>", "malformed_report"),
        (b"<testsuite/>", "empty_report"),
        (b"<testsuite>", "malformed_report"),
    ],
)
def test_junit_rejects_invalid_structures(content: bytes, code: str) -> None:
    with pytest.raises(IngestionError) as exc:
        parse_junit_xml(content)
    assert exc.value.code == code


def test_playwright_preserves_attachment_stream_and_interrupted_result() -> None:
    report = {
        "suites": [
            {
                "title": "root",
                "suites": [
                    {
                        "title": "nested",
                        "specs": [
                            {
                                "title": "checkout",
                                "location": {"file": "tests/checkout.spec.ts"},
                                "tests": [
                                    {
                                        "projectName": "webkit",
                                        "results": [
                                            {
                                                "status": "interrupted",
                                                "retry": -1,
                                                "duration": "7",
                                                "errors": [{"name": "RunnerError", "stack": "token=secret"}],
                                                "stdout": [{"text": "hello"}, "world"],
                                                "stderr": [{"buffer": "bad"}],
                                                "attachments": [
                                                    {"name": "trace", "contentType": "application/zip", "path": "trace.zip"},
                                                    "ignored",
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    item = parse_playwright_json(json.dumps(report).encode())[0]
    assert item.outcome == "cancelled"
    assert item.attempt == 0
    assert item.source_path == "tests/checkout.spec.ts"
    assert item.details["attachments"][0]["name"] == "trace"
    assert "secret" not in (item.evidence_excerpt or "")


@pytest.mark.parametrize(
    "report",
    [
        {},
        {"suites": "wrong"},
        {"suites": [{"specs": "wrong"}]},
        {"suites": [{"specs": [{"tests": "wrong"}]}]},
        {"suites": [{"specs": [{"tests": [{"results": "wrong"}]}]}]},
        {"suites": []},
    ],
)
def test_playwright_rejects_malformed_or_empty_reports(report: dict) -> None:
    with pytest.raises(IngestionError):
        parse_playwright_json(json.dumps(report).encode())


def test_pytest_collection_error_xpass_and_duration_fallback() -> None:
    report = {
        "summary": {"failed": 2},
        "tests": [
            {
                "nodeid": "tests/test_x.py::test_xpass",
                "outcome": "xpassed",
                "duration": 0.5,
                "wasxfail": "known issue",
            }
        ],
        "collectors": [
            {
                "nodeid": "tests/test_broken.py",
                "outcome": "failed",
                "longrepr": "ImportError: user@example.com",
            }
        ],
    }
    parsed = parse_pytest_json(json.dumps(report).encode())
    assert [item.outcome for item in parsed] == ["failed", "failed"]
    assert parsed[0].duration_ms == pytest.approx(500)
    assert parsed[1].exception_type == "CollectionError"
    assert "user@example.com" not in (parsed[1].message or "")


@pytest.mark.parametrize(
    "report",
    [
        {},
        {"tests": [{}]},
        {"tests": []},
    ],
)
def test_pytest_rejects_missing_identity_or_empty_report(report: dict) -> None:
    with pytest.raises(IngestionError):
        parse_pytest_json(json.dumps(report).encode())


def test_console_text_strips_controls_redacts_and_reports_truncation() -> None:
    settings = Settings(analysis_text_budget=1000)
    raw = "\x1b[31mERROR\x1b[0m email=alice@example.com\n" + "x" * 1200
    parsed = parse_artifact(raw.encode(), "console.log", settings)
    item = parsed.inputs[0]
    assert item.kind == "console-text"
    assert "terminal_controls_removed" in item.warnings
    assert "content_truncated" in item.warnings
    assert "alice@example.com" not in item.metadata["safe_preview"]
    assert item.metadata["retained_characters"] == 1000


def test_console_text_rejects_non_utf8() -> None:
    with pytest.raises(IngestionError) as exc:
        parse_artifact(b"\xff\xfe", "console.log", get_settings())
    assert exc.value.code == "malformed_encoding"


def test_console_jsonl_redacts_sensitive_fields_and_counts_errors() -> None:
    payload = "\n".join(
        [
            json.dumps({"level": "info", "message": "ok", "authorization": "Bearer secret"}),
            json.dumps({"severity": "critical", "message": "email=alice@example.com"}),
        ]
    )
    parsed = parse_artifact(payload.encode(), "console.jsonl", get_settings())
    metadata = parsed.inputs[0].metadata
    assert metadata["event_count"] == 2
    assert metadata["error_event_count"] == 1
    assert "secret" not in metadata["safe_preview"]
    assert "alice@example.com" not in metadata["safe_preview"]


@pytest.mark.parametrize("payload", [b"\n", b"not-json\n", b"[]\n", b"\xff"])
def test_console_jsonl_rejects_invalid_inputs(payload: bytes) -> None:
    with pytest.raises(IngestionError):
        parse_artifact(payload, "console.jsonl", get_settings())


def test_har_failure_sanitizes_query_and_network_error() -> None:
    report = {
        "log": {
            "version": "1.2",
            "entries": [
                {
                    "time": 12.5,
                    "request": {"method": "POST", "url": "https://example.test/pay?token=secret&x=1"},
                    "response": {"status": 503},
                    "timings": {"wait": 10},
                },
                {
                    "request": {"url": "https://example.test/socket"},
                    "response": {"status": "bad", "_error": "email=alice@example.com"},
                },
            ],
        }
    }
    parsed = parse_artifact(json.dumps(report).encode(), "network.har", get_settings())
    assert len(parsed.observations) == 2
    assert parsed.observations[0].details["status"] == 503
    assert "secret" not in parsed.observations[0].details["url"]
    assert "%5BREDACTED%5D" in parsed.observations[0].details["url"]
    assert "alice@example.com" not in (parsed.observations[1].message or "")
    assert parsed.inputs[0].metadata["status_counts"] == {"503": 1, "0": 1}


@pytest.mark.parametrize("report", [{}, {"log": {}}, {"log": {"entries": "wrong"}}])
def test_har_rejects_invalid_shape(report: dict) -> None:
    with pytest.raises(IngestionError) as exc:
        parse_artifact(json.dumps(report).encode(), "network.har", get_settings())
    assert exc.value.code in {"unsupported_format", "malformed_report"}


def test_network_jsonl_records_failure_dimensions() -> None:
    payload = "\n".join(
        [
            json.dumps({"method": "GET", "url": "https://a.test/x?q=secret", "status": 200}),
            json.dumps(
                {
                    "method": "PATCH",
                    "route": "https://a.test/pay?id=123",
                    "status": "500",
                    "browser": "chromium",
                    "attempt": 2,
                    "duration_ms": 45,
                    "timestamp": "2026-01-01T00:00:00Z",
                }
            ),
        ]
    )
    parsed = parse_artifact(payload.encode(), "network-events.jsonl", get_settings())
    assert parsed.inputs[0].metadata["event_count"] == 2
    assert len(parsed.observations) == 1
    item = parsed.observations[0]
    assert item.browser == "chromium"
    assert item.attempt == 2
    assert item.duration_ms == 45
    assert item.evidence_locator == {"kind": "text-line", "line": 2}


@pytest.mark.parametrize("payload", [b"", b"not-json", b"[]", b"\xff"])
def test_network_jsonl_rejects_invalid_inputs(payload: bytes) -> None:
    with pytest.raises(IngestionError):
        parse_artifact(payload, "network.jsonl", get_settings())


def test_rest_assured_adapters_preserve_producer_and_safe_exchange_preview() -> None:
    junit = b'<testsuite><testcase name="api"><failure type="AssertionError">status 500</failure></testcase></testsuite>'
    parsed_junit = parse_artifact(
        junit,
        "rest-results.xml",
        get_settings(),
        source_format="rest-assured-junit",
    )
    assert parsed_junit.observations[0].details["producer"] == "rest-assured-junit"

    evidence = {
        "exchanges": [
            {
                "test_identity": "api",
                "method": "POST",
                "route": "https://example.test/pay?token=secret",
                "status": 500,
                "assertion": "expected 201; email=alice@example.com",
                "request": {"authorization": "Bearer secret", "amount": 10},
                "response": {"token": "secret", "status": "failed"},
            },
            "ignored",
        ]
    }
    parsed = parse_artifact(json.dumps(evidence).encode(), "rest-evidence.json", get_settings())
    preview = parsed.inputs[0].metadata["safe_preview"]
    assert parsed.inputs[0].metadata["exchange_count"] == 1
    assert "Bearer secret" not in preview
    assert "alice@example.com" not in preview
    assert "%5BREDACTED%5D" in preview


@pytest.mark.parametrize("report", [{}, {"exchanges": "wrong"}])
def test_rest_assured_evidence_rejects_invalid_shape(report: dict) -> None:
    with pytest.raises(IngestionError):
        parse_artifact(
            json.dumps(report).encode(),
            "rest-evidence.json",
            get_settings(),
            source_format="rest-assured-evidence",
        )


def test_github_metadata_and_changed_files_preserve_trust_and_completeness() -> None:
    metadata = {
        "repository": "owner/repo",
        "commit_sha": "abcdef0",
        "base_sha": "1234567",
        "branch": "feature",
        "pull_request": 42,
        "workflow": "CI",
        "run_id": 100,
        "run_attempt": 2,
        "trigger": "pull_request",
        "author_display": "alice@example.com",
        "trust": "authenticated_lookup",
    }
    parsed_metadata = parse_artifact(json.dumps(metadata).encode(), "github.json", get_settings())
    stored = parsed_metadata.inputs[0].metadata
    assert stored["trust"] == "authenticated_lookup"
    assert stored["author_display"] != "alice@example.com"

    changes = {
        "base_sha": "abcdef0",
        "head_sha": "1234567",
        "complete": False,
        "trust": "authenticated_lookup",
        "pagination": {"page": 1, "has_more": True},
        "files": [
            "src/a.py",
            {
                "status": "renamed",
                "old_path": "src/old.py",
                "new_path": "src/new.py",
                "coverage_reference": "coverage.json#/src/new.py",
                "diff_reference": "diff.patch#L1",
            },
        ],
    }
    parsed_changes = parse_artifact(json.dumps(changes).encode(), "changes.json", get_settings())
    change_input = parsed_changes.inputs[0]
    assert change_input.metadata["file_count"] == 2
    assert change_input.metadata["declared_trust"] == "authenticated_lookup"
    assert change_input.metadata["trust"] == "self_reported"
    assert change_input.metadata["trust_source"] == "artifact_default"
    assert change_input.metadata["files"][1]["old_path"] == "src/old.py"
    assert change_input.warnings == ("changed_file_list_incomplete",)


def test_github_metadata_and_changed_files_reject_invalid_values() -> None:
    with pytest.raises(IngestionError) as invalid_sha:
        parse_artifact(
            json.dumps({"repository": "o/r", "commit_sha": "not-a-sha"}).encode(),
            "github.json",
            get_settings(),
        )
    assert invalid_sha.value.code == "malformed_report"

    for report in [
        {},
        {"files": [42], "complete": True},
        {"files": [{"status": "unknown", "path": "x"}], "complete": True},
        {"files": [{"status": "modified"}], "complete": True},
        {"files": [{"status": "modified", "path": "../escape"}], "complete": True},
        {
            "files": [{"status": "modified", "path": "src/a.py"}],
            "complete": True,
            "trust": "made_up_trust",
        },
    ]:
        with pytest.raises(IngestionError):
            parse_artifact(
                json.dumps(report).encode(),
                "changes.json",
                get_settings(),
                source_format="changed-files",
            )


def test_screenshot_jpeg_metadata_and_bounds() -> None:
    parsed = parse_artifact(_jpeg(640, 480), "shot.jpg", get_settings())
    assert parsed.inputs[0].status == "restricted"
    assert parsed.inputs[0].metadata["media_type"] == "image/jpeg"
    assert parsed.inputs[0].metadata["pixels"] == 640 * 480

    with pytest.raises(IngestionError) as too_large:
        parse_artifact(_jpeg(5001, 5001), "huge.jpg", get_settings())
    assert too_large.value.code == "limit_exceeded"

    for malformed in [b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff\xd9", b"not-image"]:
        with pytest.raises(IngestionError):
            parse_artifact(malformed, "shot.jpg", get_settings(), source_format="screenshot")


def test_trace_validation_rejects_malformed_missing_and_binary_streams() -> None:
    with pytest.raises(IngestionError) as malformed:
        parse_artifact(b"not-zip", "trace.zip", get_settings(), source_format="playwright-trace")
    assert malformed.value.code == "malformed_report"

    no_trace = io.BytesIO()
    with zipfile.ZipFile(no_trace, "w") as archive:
        archive.writestr("other.txt", "x")
    with pytest.raises(IngestionError) as missing:
        parse_artifact(no_trace.getvalue(), "trace.zip", get_settings(), source_format="playwright-trace")
    assert missing.value.code == "unsupported_format"

    with pytest.raises(IngestionError) as encoding:
        parse_artifact(_trace_zip(b"\xff"), "trace.zip", get_settings(), source_format="playwright-trace")
    assert encoding.value.code == "malformed_encoding"


def test_archive_rejects_collisions_symlinks_nested_archives_and_ambiguity() -> None:
    collision = io.BytesIO()
    with zipfile.ZipFile(collision, "w") as archive:
        archive.writestr("A.xml", '<testsuite><testcase name="a"/></testsuite>')
        archive.writestr("a.XML", '<testsuite><testcase name="b"/></testsuite>')
    with pytest.raises(IngestionError) as collision_error:
        parse_artifact(collision.getvalue(), "bundle.zip", get_settings())
    assert collision_error.value.code == "unsafe_archive"

    symlink = io.BytesIO()
    with zipfile.ZipFile(symlink, "w") as archive:
        info = zipfile.ZipInfo("link.xml")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "target")
    with pytest.raises(IngestionError) as symlink_error:
        parse_artifact(symlink.getvalue(), "bundle.zip", get_settings())
    assert symlink_error.value.code == "unsafe_archive"

    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w") as archive:
        archive.writestr("nested.zip", _trace_zip())
    with pytest.raises(IngestionError) as nested_error:
        parse_artifact(nested.getvalue(), "bundle.zip", get_settings())
    assert nested_error.value.code == "unsafe_archive"

    ambiguous = io.BytesIO()
    with zipfile.ZipFile(ambiguous, "w") as archive:
        archive.writestr("one.xml", '<testsuite><testcase name="one"/></testsuite>')
        archive.writestr("two.xml", '<testsuite><testcase name="two"/></testsuite>')
    with pytest.raises(IngestionError) as ambiguity:
        parse_artifact(ambiguous.getvalue(), "bundle.zip", get_settings())
    assert ambiguity.value.code == "ambiguous_bundle"


def test_implicit_bundle_and_standalone_trace_detection() -> None:
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("result.xml", '<testsuite><testcase name="ok"/></testsuite>')
    parsed = parse_artifact(bundle.getvalue(), "result.zip", get_settings())
    assert parsed.manifest_version == "implicit-v1"
    assert "bundle_manifest_missing" in parsed.warnings

    trace = parse_artifact(_trace_zip(), "trace.zip", get_settings())
    assert trace.source_format == "playwright-trace"
    assert trace.inputs[0].status == "restricted"
    assert trace.completeness == "partial"


def test_manifest_v2_validates_contract_and_degrades_bad_inputs() -> None:
    invalid_manifests = [
        {"schema_version": "2.0", "inputs": []},
        {"schema_version": "2.0", "inputs": ["wrong"]},
        {"schema_version": "2.0", "inputs": [{"id": "bad id", "path": "a.log"}]},
        {
            "schema_version": "2.0",
            "inputs": [
                {"id": "same", "path": "a.log"},
                {"id": "same", "path": "b.log"},
            ],
        },
        {"schema_version": "2.0", "inputs": [{"id": "x", "required": "yes", "path": "a.log"}]},
        {"schema_version": "2.0", "inputs": [{"id": "x"}]},
        {"schema_version": "2.0", "inputs": [{"id": "x", "path": "a.log", "metadata": []}]},
    ]
    for manifest in invalid_manifests:
        with pytest.raises(IngestionError):
            parse_artifact(_bundle(manifest, {"a.log": "ok", "b.log": "ok"}), "bundle.zip", get_settings())

    manifest = {
        "schema_version": "2.0",
        "inputs": [
            {"id": "good", "kind": "console-text", "path": "good.log", "required": True},
            {"id": "unsupported", "kind": "made-up", "path": "unknown.bin", "required": True},
            {"id": "optional-bad", "kind": "console-jsonl", "path": "bad.jsonl", "required": False},
        ],
    }
    parsed = parse_artifact(
        _bundle(manifest, {"good.log": "ok", "unknown.bin": b"x", "bad.jsonl": "not-json"}),
        "bundle.zip",
        get_settings(),
    )
    by_id = {item.input_id: item for item in parsed.inputs}
    assert by_id["good"].status == "accepted"
    assert by_id["unsupported"].status == "unsupported"
    assert by_id["optional-bad"].status == "rejected"
    assert parsed.completeness == "partial"
    assert parsed.expected_inputs == 2
    assert parsed.received_inputs == 2


def test_bundle_manifest_versions_and_paths_are_validated() -> None:
    with pytest.raises(IngestionError) as unsupported:
        parse_artifact(
            _bundle({"schema_version": "9.9", "inputs": []}, {}),
            "bundle.zip",
            get_settings(),
        )
    assert unsupported.value.code == "unsupported_schema"

    with pytest.raises(IngestionError):
        parse_artifact(_bundle({"schema_version": "1.0"}, {}), "bundle.zip", get_settings())

    with pytest.raises(IngestionError):
        parse_artifact(
            _bundle({"schema_version": "1.0", "report": "missing.xml"}, {}),
            "bundle.zip",
            get_settings(),
        )


def test_explicit_adapter_alias_media_detection_and_unknown_json() -> None:
    parsed = parse_artifact(
        b'<testsuite><testcase name="ok"/></testsuite>',
        "results.data",
        get_settings(),
        source_format="xml",
        media_type="application/octet-stream",
    )
    assert parsed.source_format == "junit-xml"

    parsed_text = parse_artifact(b"hello", "unknown.data", get_settings(), media_type="text/plain")
    assert parsed_text.source_format == "console-text"

    with pytest.raises(IngestionError) as unknown_kind:
        parse_artifact(b"x", "x.bin", get_settings(), source_format="made-up")
    assert unknown_kind.value.code == "unsupported_format"

    with pytest.raises(IngestionError) as malformed_json:
        parse_artifact(b"{", "result.json", get_settings())
    assert malformed_json.value.code == "malformed_report"

    with pytest.raises(IngestionError) as unknown_json:
        parse_artifact(json.dumps({"unrecognized": True}).encode(), "result.json", get_settings())
    assert unknown_json.value.code == "unsupported_format"


def test_empty_and_size_limited_uploads_are_rejected() -> None:
    with pytest.raises(IngestionError) as empty:
        parse_artifact(b"", "empty.log", get_settings())
    assert empty.value.code == "empty_upload"

    settings = Settings(max_file_bytes=1024, max_bundle_bytes=1024)
    with pytest.raises(IngestionError) as ordinary:
        parse_artifact(b"x" * 1025, "large.log", settings)
    assert ordinary.value.code == "limit_exceeded"

    oversized_zip = b"PK\x03\x04" + b"x" * 1021
    with pytest.raises(IngestionError) as bundle:
        parse_artifact(oversized_zip, "large.zip", settings)
    assert bundle.value.code == "limit_exceeded"


def test_adapter_limits_are_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingestion, "MAX_CONSOLE_EVENTS", 1)
    monkeypatch.setattr(ingestion, "MAX_NETWORK_EVENTS", 1)
    monkeypatch.setattr(ingestion, "MAX_K6_METRICS", 1)
    monkeypatch.setattr(ingestion, "MAX_REST_EXCHANGES", 1)
    monkeypatch.setattr(ingestion, "MAX_CHANGED_FILES", 1)

    console = parse_artifact(
        b'{"level":"info"}\n{"level":"error"}\n',
        "console.jsonl",
        get_settings(),
    )
    assert "event_limit_reached" in console.inputs[0].warnings

    network = parse_artifact(
        b'{"status":200,"url":"https://a.test"}\n{"status":500,"url":"https://b.test"}\n',
        "network.jsonl",
        get_settings(),
        source_format="network-jsonl",
    )
    assert "event_limit_reached" in network.inputs[0].warnings

    k6 = parse_artifact(
        json.dumps({"metrics": {"a": {"values": {}}, "b": {"values": {}}}}).encode(),
        "k6.json",
        get_settings(),
        source_format="k6-summary",
    )
    assert "metric_limit_reached" in k6.inputs[0].warnings

    rest = parse_artifact(
        json.dumps({"exchanges": [{"route": "/a"}, {"route": "/b"}]}).encode(),
        "rest.json",
        get_settings(),
        source_format="rest-assured-evidence",
    )
    assert "event_limit_reached" in rest.inputs[0].warnings

    changes = parse_artifact(
        json.dumps({"complete": True, "files": ["a.py", "b.py"]}).encode(),
        "changes.json",
        get_settings(),
    )
    assert "file_limit_reached" in changes.inputs[0].warnings

    har = parse_artifact(
        json.dumps(
            {
                "log": {
                    "entries": [
                        {"request": {"url": "https://a.test"}, "response": {"status": 200}},
                        {"request": {"url": "https://b.test"}, "response": {"status": 500}},
                    ]
                }
            }
        ).encode(),
        "network.har",
        get_settings(),
    )
    assert "event_limit_reached" in har.inputs[0].warnings


def test_network_jsonl_invalid_attempt_is_structured() -> None:
    with pytest.raises(IngestionError) as exc:
        parse_artifact(
            b'{"status":500,"url":"https://a.test","attempt":"many"}\n',
            "network.jsonl",
            get_settings(),
            source_format="network-jsonl",
        )
    assert exc.value.code == "malformed_report"


def test_manifest_rejects_duplicate_paths_and_oversized_metadata() -> None:
    duplicate = {
        "schema_version": "2.0",
        "inputs": [
            {"id": "one", "path": "same.log", "kind": "console-text"},
            {"id": "two", "path": "same.log", "kind": "console-text"},
        ],
    }
    with pytest.raises(IngestionError) as duplicate_error:
        parse_artifact(_bundle(duplicate, {"same.log": "ok"}), "bundle.zip", get_settings())
    assert duplicate_error.value.code == "malformed_report"

    oversized = {
        "schema_version": "2.0",
        "padding": "x" * 2_000,
        "inputs": [{"id": "one", "path": "one.log", "kind": "console-text"}],
    }
    with pytest.raises(IngestionError) as oversized_error:
        parse_artifact(
            _bundle(oversized, {"one.log": "ok"}),
            "bundle.zip",
            Settings(max_file_bytes=1_024),
        )
    assert oversized_error.value.code == "limit_exceeded"


def test_metadata_sha_fields_are_validated() -> None:
    with pytest.raises(IngestionError) as github_error:
        parse_artifact(
            json.dumps({"repository": "o/r", "commit_sha": "abcdef0", "base_sha": "bad"}).encode(),
            "github.json",
            get_settings(),
        )
    assert github_error.value.code == "malformed_report"

    with pytest.raises(IngestionError) as changes_error:
        parse_artifact(
            json.dumps({"head_sha": "bad", "files": ["a.py"]}).encode(),
            "changes.json",
            get_settings(),
        )
    assert changes_error.value.code == "malformed_report"
