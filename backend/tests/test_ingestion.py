import io
import json
import zipfile

import pytest
from failurelens.config import get_settings
from failurelens.ingestion import (
    IngestionError,
    parse_artifact,
    parse_junit_xml,
    parse_playwright_json,
    parse_pytest_json,
    safe_archive_name,
    supported_adapter_kinds,
)
from PIL import Image


def test_junit_parses_failure_and_redacts_output() -> None:
    content = b"""<testsuite name="payments"><testcase classname="Transfer" name="duplicate" time="0.1"><failure type="AssertionError" message="duplicate committed">Authorization: Bearer token-123456</failure></testcase></testsuite>"""
    parsed = parse_junit_xml(content)
    assert len(parsed) == 1
    assert parsed[0].outcome == "failed"
    assert parsed[0].exception_type == "AssertionError"
    assert "token-123456" not in (parsed[0].evidence_excerpt or "")


def test_junit_rejects_entity_declaration() -> None:
    with pytest.raises(IngestionError) as exc:
        parse_junit_xml(
            b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><testsuite/>'
        )
    assert exc.value.code == "unsafe_xml"


def test_playwright_preserves_attempts_and_project() -> None:
    report = {
        "suites": [
            {
                "title": "checkout",
                "specs": [
                    {
                        "title": "pays",
                        "file": "tests/pay.spec.ts",
                        "tests": [
                            {
                                "projectName": "chromium",
                                "results": [
                                    {
                                        "status": "failed",
                                        "duration": 12,
                                        "error": {
                                            "name": "Error",
                                            "message": "HTTP 500",
                                        },
                                    },
                                    {"status": "passed", "duration": 9},
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    parsed = parse_playwright_json(json.dumps(report).encode())
    assert [item.attempt for item in parsed] == [0, 1]
    assert [item.outcome for item in parsed] == ["failed", "passed"]
    assert parsed[0].browser == "chromium"
    assert parsed[1].details["retry_recovered"] is True


def test_archive_paths_are_bounded() -> None:
    assert safe_archive_name("reports/junit.xml") == "reports/junit.xml"
    for name in ["../secret", "/absolute", "C:/windows/path", "a/../../b"]:
        with pytest.raises(IngestionError):
            safe_archive_name(name)


def test_zip_bundle_manifest_and_bomb_controls() -> None:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({"schema_version": "1.0", "report": "reports/junit.xml"}),
        )
        archive.writestr(
            "reports/junit.xml", '<testsuite><testcase name="ok"/></testsuite>'
        )
    parsed = parse_artifact(content.getvalue(), "bundle.zip", get_settings())
    assert parsed.source_format == "zip+junit-xml"
    assert parsed.observations[0].outcome == "passed"

    unsafe = io.BytesIO()
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr(
            "../escape.xml", '<testsuite><testcase name="ok"/></testsuite>'
        )
    with pytest.raises(IngestionError) as exc:
        parse_artifact(unsafe.getvalue(), "unsafe.zip", get_settings())
    assert exc.value.code == "unsafe_archive"


def test_junit_root_suite_preserves_nested_suites() -> None:
    parsed = parse_junit_xml(
        b'<testsuite name="root"><testcase name="outer"/><testsuite name="nested"><testcase name="inner"/></testsuite></testsuite>'
    )
    assert [item.test_identity for item in parsed] == ["outer", "inner"]
    assert [item.suite for item in parsed] == ["root", "nested"]


def _bundle_v2(manifest: dict, files: dict[str, bytes | str]) -> bytes:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for path, payload in files.items():
            archive.writestr(path, payload)
    return content.getvalue()


def test_manifest_v2_accounts_for_inputs_not_test_observations() -> None:
    junit = b'<testsuite><testcase name="one"/><testcase name="two"/></testsuite>'
    changes = json.dumps(
        {
            "base_sha": "abcdef0",
            "head_sha": "1234567",
            "complete": True,
            "files": [{"status": "modified", "path": "src/payments.py"}],
        }
    ).encode()
    manifest = {
        "schema_version": "2.0",
        "inputs": [
            {
                "id": "tests",
                "kind": "junit-xml",
                "path": "reports/junit.xml",
                "required": True,
                "role": "primary",
            },
            {
                "id": "changes",
                "kind": "changed-files",
                "path": "metadata/changes.json",
                "required": True,
            },
            {
                "id": "console",
                "kind": "console-text",
                "path": "logs/console.log",
                "required": False,
            },
            {
                "id": "expected-shot",
                "kind": "screenshot",
                "path": "screenshots/expected.png",
                "required": True,
            },
        ],
    }
    parsed = parse_artifact(
        _bundle_v2(
            manifest,
            {
                "reports/junit.xml": junit,
                "metadata/changes.json": changes,
                "logs/console.log": "Authorization: Bearer secret-token\nready",
            },
        ),
        "bundle.zip",
        get_settings(),
    )

    assert parsed.manifest_version == "2.0"
    assert parsed.expected_inputs == 3
    assert parsed.received_inputs == 2
    assert parsed.completeness == "partial"
    assert len(parsed.observations) == 2
    assert {item.input_id: item.status for item in parsed.inputs} == {
        "tests": "accepted",
        "changes": "accepted",
        "console": "accepted",
        "expected-shot": "missing",
    }
    console = next(item for item in parsed.inputs if item.input_id == "console")
    assert "secret-token" not in console.metadata["safe_preview"]


def test_manifest_v2_digest_mismatch_is_rejected_without_losing_other_inputs() -> None:
    junit = b'<testsuite><testcase name="ok"/></testsuite>'
    manifest = {
        "schema_version": "2.0",
        "inputs": [
            {
                "id": "tests",
                "kind": "junit-xml",
                "path": "junit.xml",
                "required": True,
                "sha256": "0" * 64,
            },
            {
                "id": "changes",
                "kind": "changed-files",
                "path": "changes.json",
                "required": False,
            },
        ],
    }
    parsed = parse_artifact(
        _bundle_v2(
            manifest,
            {
                "junit.xml": junit,
                "changes.json": json.dumps({"complete": True, "files": []}),
            },
        ),
        "bundle.zip",
        get_settings(),
    )
    tests_input = next(item for item in parsed.inputs if item.input_id == "tests")
    assert tests_input.status == "rejected"
    assert tests_input.warnings == ("digest_mismatch",)
    assert parsed.completeness == "partial"
    assert parsed.received_inputs == 1


def test_pytest_json_preserves_phases_parameterization_and_xfail() -> None:
    report = {
        "created": 1,
        "exitcode": 1,
        "summary": {"failed": 1},
        "tests": [
            {
                "nodeid": "tests/test_payments.py::test_amount[CAD]",
                "outcome": "failed",
                "keywords": ["test_amount", "CAD"],
                "setup": {"outcome": "passed", "duration": 0.01},
                "call": {
                    "outcome": "failed",
                    "duration": 0.02,
                    "crash": {"message": "AssertionError: expected 10 got 11"},
                    "stdout": "email=user@example.com",
                },
                "teardown": {"outcome": "passed", "duration": 0.01},
            }
        ],
    }
    parsed = parse_pytest_json(json.dumps(report).encode())
    assert len(parsed) == 1
    assert parsed[0].parameterization == "CAD"
    assert parsed[0].duration_ms == pytest.approx(40)
    assert parsed[0].details["phases"]["call"]["outcome"] == "failed"
    assert "user@example.com" not in json.dumps(parsed[0].details)


def test_k6_thresholds_are_preserved_without_inventing_quantiles() -> None:
    report = {
        "metrics": {
            "http_req_duration": {
                "type": "trend",
                "contains": "time",
                "values": {"avg": 120, "p(95)": 310},
                "thresholds": {"p(95)<250": {"ok": False}},
            }
        },
        "state": {"isStdOutTTY": False},
    }
    parsed = parse_artifact(
        json.dumps(report).encode(),
        "k6-summary.json",
        get_settings(),
        source_format="k6-summary-json",
    )
    assert parsed.source_format == "k6-summary-json"
    assert parsed.observations[0].outcome == "failed"
    assert parsed.observations[0].details["values"] == {"avg": 120, "p(95)": 310}
    assert "p(99)" not in json.dumps(parsed.inputs[0].metadata)


def test_screenshot_metadata_is_restricted_and_pixel_bounded() -> None:
    output = io.BytesIO()
    Image.new("RGB", (320, 200), (23, 91, 171)).save(output, format="PNG")
    png = output.getvalue()
    parsed = parse_artifact(png, "failure.png", get_settings())
    assert parsed.inputs[0].status == "restricted"
    assert parsed.completeness == "partial"
    assert parsed.inputs[0].metadata["width"] == 320
    assert parsed.inputs[0].metadata["height"] == 200
    assert parsed.inputs[0].metadata["safe_derivative"] == "metadata-only"


def test_manifest_allows_only_declared_playwright_trace_archives() -> None:
    trace = io.BytesIO()
    with zipfile.ZipFile(trace, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "trace.trace",
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "context-options",
                            "version": 9,
                            "playwrightVersion": "1.63.0",
                        }
                    ),
                    json.dumps({"type": "before", "apiName": "page.click"}),
                    json.dumps({"type": "error", "message": "selector failed"}),
                ]
            ),
        )
    manifest = {
        "schema_version": "2.0",
        "inputs": [
            {
                "id": "trace",
                "kind": "playwright-trace",
                "path": "artifacts/trace.zip",
                "required": True,
            }
        ],
    }
    parsed = parse_artifact(
        _bundle_v2(manifest, {"artifacts/trace.zip": trace.getvalue()}),
        "bundle.zip",
        get_settings(),
    )
    assert parsed.completeness == "partial"
    assert parsed.expected_inputs == 1
    assert parsed.received_inputs == 1
    assert parsed.inputs[0].status == "restricted"
    assert parsed.inputs[0].metadata["event_count"] == 3
    assert parsed.inputs[0].metadata["error_event_count"] == 1


def test_registry_exposes_declared_m2_adapter_families() -> None:
    kinds = set(supported_adapter_kinds())
    assert {
        "junit-xml",
        "playwright-json",
        "pytest-json-report",
        "rest-assured-junit",
        "rest-assured-evidence",
        "k6-summary-json",
        "console-text",
        "console-jsonl",
        "har",
        "network-jsonl",
        "screenshot",
        "playwright-trace",
        "github-metadata",
        "changed-files",
    } <= kinds


def test_manifest_v2_required_restricted_input_is_partial() -> None:
    output = io.BytesIO()
    Image.new("RGB", (2, 2), (23, 91, 171)).save(output, format="PNG")
    image = output.getvalue()
    manifest = {
        "schema_version": "2.0",
        "inputs": [
            {
                "id": "screenshot",
                "kind": "screenshot",
                "path": "shot.png",
                "required": True,
            }
        ],
    }
    parsed = parse_artifact(
        _bundle_v2(manifest, {"shot.png": image}), "bundle.zip", get_settings()
    )
    assert parsed.expected_inputs == 1
    assert parsed.received_inputs == 1
    assert parsed.completeness == "partial"
    assert parsed.inputs[0].status == "restricted"


def test_manifest_v2_rejected_only_preserves_safe_status_record() -> None:
    manifest = {
        "schema_version": "2.0",
        "inputs": [
            {
                "id": "unknown",
                "kind": "made-up-format",
                "path": "unknown.bin",
                "required": True,
            }
        ],
    }
    parsed = parse_artifact(
        _bundle_v2(manifest, {"unknown.bin": b"untrusted bytes"}),
        "bundle.zip",
        get_settings(),
    )
    assert parsed.expected_inputs == 1
    assert parsed.received_inputs == 1
    assert parsed.completeness == "partial"
    assert parsed.observations == ()
    assert parsed.inputs[0].status == "unsupported"
    assert parsed.inputs[0].warnings == ("unsupported_format",)


def test_manifest_v2_optional_only_rejection_is_not_complete() -> None:
    manifest = {
        "schema_version": "2.0",
        "inputs": [
            {
                "id": "optional-unknown",
                "kind": "made-up-format",
                "path": "unknown.bin",
                "required": False,
            }
        ],
    }
    parsed = parse_artifact(
        _bundle_v2(manifest, {"unknown.bin": b"untrusted bytes"}),
        "bundle.zip",
        get_settings(),
    )
    assert parsed.expected_inputs == 0
    assert parsed.received_inputs == 0
    assert parsed.completeness == "partial"
    assert parsed.inputs[0].status == "unsupported"
