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
    safe_archive_name,
)


def test_junit_parses_failure_and_redacts_output() -> None:
    content = b'''<testsuite name="payments"><testcase classname="Transfer" name="duplicate" time="0.1"><failure type="AssertionError" message="duplicate committed">Authorization: Bearer token-123456</failure></testcase></testsuite>'''
    parsed = parse_junit_xml(content)
    assert len(parsed) == 1
    assert parsed[0].outcome == "failed"
    assert parsed[0].exception_type == "AssertionError"
    assert "token-123456" not in (parsed[0].evidence_excerpt or "")


def test_junit_rejects_entity_declaration() -> None:
    with pytest.raises(IngestionError) as exc:
        parse_junit_xml(b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><testsuite/>')
    assert exc.value.code == "unsafe_xml"


def test_playwright_preserves_attempts_and_project() -> None:
    report = {
        "suites": [{"title": "checkout", "specs": [{"title": "pays", "file": "tests/pay.spec.ts", "tests": [{"projectName": "chromium", "results": [{"status": "failed", "duration": 12, "error": {"name": "Error", "message": "HTTP 500"}}, {"status": "passed", "duration": 9}]}]}]}]
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
        archive.writestr("manifest.json", json.dumps({"schema_version": "1.0", "report": "reports/junit.xml"}))
        archive.writestr("reports/junit.xml", '<testsuite><testcase name="ok"/></testsuite>')
    parsed = parse_artifact(content.getvalue(), "bundle.zip", get_settings())
    assert parsed.source_format == "zip+junit-xml"
    assert parsed.observations[0].outcome == "passed"

    unsafe = io.BytesIO()
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../escape.xml", '<testsuite><testcase name="ok"/></testsuite>')
    with pytest.raises(IngestionError) as exc:
        parse_artifact(unsafe.getvalue(), "unsafe.zip", get_settings())
    assert exc.value.code == "unsafe_archive"


def test_junit_root_suite_preserves_nested_suites() -> None:
    parsed = parse_junit_xml(
        b'<testsuite name="root"><testcase name="outer"/><testsuite name="nested"><testcase name="inner"/></testsuite></testsuite>'
    )
    assert [item.test_identity for item in parsed] == ["outer", "inner"]
    assert [item.suite for item in parsed] == ["root", "nested"]
