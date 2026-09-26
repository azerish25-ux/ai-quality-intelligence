from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .redaction import redact_text

PARSER_VERSION = "ingestion-v1"


class IngestionError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ParsedObservation:
    test_identity: str
    suite: str | None
    source_path: str | None
    browser: str | None
    attempt: int
    outcome: str
    duration_ms: float | None
    message: str | None
    exception_type: str | None
    details: dict[str, Any]
    evidence_excerpt: str | None
    evidence_locator: dict[str, Any]


def safe_archive_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise IngestionError("unsafe_archive", f"Unsafe archive path: {name!r}")
    if re.match(r"^[A-Za-z]:", normalized):
        raise IngestionError("unsafe_archive", f"Drive-prefixed archive path: {name!r}")
    return str(path)


def digest_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def parse_junit_xml(content: bytes) -> list[ParsedObservation]:
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise IngestionError("unsafe_xml", "DTD and entity declarations are not accepted")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise IngestionError("malformed_report", f"Malformed JUnit XML: {exc}") from exc
    if root.tag not in {"testsuite", "testsuites"}:
        raise IngestionError("unsupported_format", f"Unsupported JUnit root: {root.tag}")

    observations: list[ParsedObservation] = []
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    for suite in suites:
        suite_name = suite.attrib.get("name")
        for case in suite.findall("testcase"):
            name = case.attrib.get("name")
            if not name:
                raise IngestionError("malformed_report", "JUnit testcase is missing name")
            classname = case.attrib.get("classname")
            identity = "::".join(part for part in [classname, name] if part)
            duration = None
            try:
                duration = float(case.attrib["time"]) * 1000 if "time" in case.attrib else None
            except ValueError:
                duration = None
            outcome = "passed"
            message = None
            exception_type = None
            failing = case.find("failure")
            error = case.find("error")
            skipped = case.find("skipped")
            node = failing if failing is not None else error
            if node is not None:
                outcome = "failed"
                message = "\n".join(filter(None, [node.attrib.get("message"), node.text])).strip()
                exception_type = node.attrib.get("type")
            elif skipped is not None:
                outcome = "skipped"
                message = skipped.attrib.get("message") or skipped.text
            system_out = case.findtext("system-out") or ""
            system_err = case.findtext("system-err") or ""
            raw_excerpt = "\n".join(filter(None, [message, system_out, system_err]))
            redacted = redact_text(raw_excerpt[:40_000]) if raw_excerpt else None
            observations.append(ParsedObservation(
                test_identity=identity,
                suite=suite_name,
                source_path=case.attrib.get("file"),
                browser=None,
                attempt=0,
                outcome=outcome,
                duration_ms=duration,
                message=redacted.text if message and redacted else message,
                exception_type=exception_type,
                details={"producer": "junit", "line": case.attrib.get("line"), "redacted_classes": list(redacted.classes) if redacted else []},
                evidence_excerpt=redacted.text if redacted else None,
                evidence_locator={"kind": "xml", "suite": suite_name, "testcase": identity},
            ))
    return observations


def parse_playwright_json(content: bytes) -> list[ParsedObservation]:
    try:
        data = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IngestionError("malformed_report", f"Malformed Playwright JSON: {exc}") from exc
    suites = data.get("suites")
    if not isinstance(suites, list):
        raise IngestionError("unsupported_format", "Playwright JSON requires a suites array")
    observations: list[ParsedObservation] = []

    def walk(suite: dict[str, Any], parents: list[str]) -> None:
        title = str(suite.get("title") or "").strip()
        lineage = parents + ([title] if title else [])
        for spec in suite.get("specs", []):
            spec_title = str(spec.get("title") or "unnamed")
            for test in spec.get("tests", []):
                project_name = test.get("projectName")
                results = test.get("results") or []
                for attempt, result in enumerate(results):
                    status = result.get("status", "unknown")
                    outcome = {"passed": "passed", "failed": "failed", "skipped": "skipped", "timedOut": "failed", "interrupted": "cancelled"}.get(status, "unknown")
                    error = result.get("error") or {}
                    message = error.get("message") or error.get("stack")
                    stdout = "\n".join(str(item.get("text", item)) if isinstance(item, dict) else str(item) for item in result.get("stdout", []))
                    stderr = "\n".join(str(item.get("text", item)) if isinstance(item, dict) else str(item) for item in result.get("stderr", []))
                    raw = "\n".join(filter(None, [message, stdout, stderr]))
                    redacted = redact_text(raw[:40_000]) if raw else None
                    observations.append(ParsedObservation(
                        test_identity="::".join(lineage + [spec_title]),
                        suite=" / ".join(lineage) or None,
                        source_path=(spec.get("file") or suite.get("file")),
                        browser=project_name,
                        attempt=attempt,
                        outcome=outcome,
                        duration_ms=float(result["duration"]) if result.get("duration") is not None else None,
                        message=redacted.text if message and redacted else message,
                        exception_type=error.get("name"),
                        details={"producer": "playwright-json", "status": status, "retry": attempt, "redacted_classes": list(redacted.classes) if redacted else []},
                        evidence_excerpt=redacted.text if redacted else None,
                        evidence_locator={"kind": "json-pointer", "suite": lineage, "spec": spec_title, "attempt": attempt},
                    ))
        for child in suite.get("suites", []):
            walk(child, lineage)

    for suite in suites:
        walk(suite, [])
    return observations
