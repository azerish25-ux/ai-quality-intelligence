from __future__ import annotations

import hashlib
import io
import json
import re
import stat
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .config import Settings
from .redaction import redact_text

PARSER_VERSION = "ingestion-v2"


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


@dataclass(frozen=True)
class ParsedArtifact:
    source_format: str
    parser_version: str
    report_name: str
    observations: tuple[ParsedObservation, ...]
    warnings: tuple[str, ...] = ()


def safe_archive_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or "\x00" in normalized
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or re.match(r"^[A-Za-z]:", normalized)
        or any(ord(char) < 32 for char in normalized)
    ):
        raise IngestionError("unsafe_archive", f"Unsafe archive path: {name!r}")
    return str(path)


def digest_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _duration_ms(value: object, *, multiplier: float = 1.0) -> float | None:
    if value is None:
        return None
    try:
        result = float(value) * multiplier
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def parse_junit_xml(content: bytes) -> list[ParsedObservation]:
    upper = content.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise IngestionError("unsafe_xml", "DTD and entity declarations are not accepted")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise IngestionError("malformed_report", f"Malformed JUnit XML: {exc}") from exc
    root_name = root.tag.rsplit("}", 1)[-1]
    if root_name not in {"testsuite", "testsuites"}:
        raise IngestionError("unsupported_format", f"Unsupported JUnit root: {root.tag}")

    observations: list[ParsedObservation] = []
    suites = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "testsuite"]
    for suite_index, suite in enumerate(suites):
        suite_name = suite.attrib.get("name")
        cases = [node for node in list(suite) if node.tag.rsplit("}", 1)[-1] == "testcase"]
        for case_index, case in enumerate(cases):
            name = case.attrib.get("name")
            if not name:
                raise IngestionError("malformed_report", "JUnit testcase is missing name")
            classname = case.attrib.get("classname")
            identity = "::".join(part for part in [classname, name] if part)
            outcome = "passed"
            message: str | None = None
            exception_type: str | None = None
            failing: ET.Element | None = None
            skipped: ET.Element | None = None
            system_out = ""
            system_err = ""
            for child in list(case):
                kind = child.tag.rsplit("}", 1)[-1]
                if kind in {"failure", "error"} and failing is None:
                    failing = child
                elif kind == "skipped":
                    skipped = child
                elif kind == "system-out":
                    system_out = child.text or ""
                elif kind == "system-err":
                    system_err = child.text or ""
            if failing is not None:
                outcome = "failed"
                message = "\n".join(
                    value for value in [failing.attrib.get("message"), failing.text] if value
                ).strip()
                exception_type = failing.attrib.get("type")
            elif skipped is not None:
                outcome = "skipped"
                message = skipped.attrib.get("message") or skipped.text
            raw_excerpt = "\n".join(value for value in [message, system_out, system_err] if value)
            redacted = redact_text(raw_excerpt[:40_000]) if raw_excerpt else None
            observations.append(
                ParsedObservation(
                    test_identity=identity,
                    suite=suite_name,
                    source_path=case.attrib.get("file"),
                    browser=None,
                    attempt=0,
                    outcome=outcome,
                    duration_ms=_duration_ms(case.attrib.get("time"), multiplier=1000),
                    message=redacted.text if message and redacted else message,
                    exception_type=exception_type,
                    details={
                        "producer": "junit",
                        "line": case.attrib.get("line"),
                        "timestamp": case.attrib.get("timestamp"),
                        "redacted_classes": list(redacted.classes) if redacted else [],
                    },
                    evidence_excerpt=redacted.text if redacted else None,
                    evidence_locator={
                        "kind": "xml-path",
                        "suite_index": suite_index,
                        "testcase_index": case_index,
                        "suite": suite_name,
                        "testcase": identity,
                    },
                )
            )
    if not observations:
        raise IngestionError("empty_report", "JUnit report contains no testcases")
    return observations


def _playwright_error(result: dict[str, Any]) -> tuple[str | None, str | None]:
    errors = result.get("errors")
    values: list[dict[str, Any]] = []
    if isinstance(errors, list):
        values.extend(item for item in errors if isinstance(item, dict))
    error = result.get("error")
    if isinstance(error, dict):
        values.insert(0, error)
    if not values:
        return None, None
    messages: list[str] = []
    names: list[str] = []
    for item in values:
        text = item.get("message") or item.get("stack") or item.get("value")
        if text:
            messages.append(str(text))
        if item.get("name"):
            names.append(str(item["name"]))
    return "\n".join(messages) or None, names[0] if names else None


def _stream_text(items: object) -> str:
    if not isinstance(items, list):
        return ""
    result: list[str] = []
    for item in items:
        if isinstance(item, dict):
            result.append(str(item.get("text", item.get("buffer", item))))
        else:
            result.append(str(item))
    return "\n".join(result)


def parse_playwright_json(content: bytes) -> list[ParsedObservation]:
    try:
        data = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IngestionError("malformed_report", f"Malformed Playwright JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise IngestionError("unsupported_format", "Playwright JSON root must be an object")
    suites = data.get("suites")
    if not isinstance(suites, list):
        raise IngestionError("unsupported_format", "Playwright JSON requires a suites array")
    observations: list[ParsedObservation] = []

    def walk(suite: dict[str, Any], parents: list[str], suite_path: list[int]) -> None:
        title = str(suite.get("title") or "").strip()
        lineage = parents + ([title] if title else [])
        specs = suite.get("specs", [])
        if not isinstance(specs, list):
            raise IngestionError("malformed_report", "Playwright suite specs must be an array")
        for spec_index, spec in enumerate(specs):
            if not isinstance(spec, dict):
                continue
            spec_title = str(spec.get("title") or "unnamed")
            tests = spec.get("tests", [])
            if not isinstance(tests, list):
                raise IngestionError("malformed_report", "Playwright spec tests must be an array")
            for test_index, test in enumerate(tests):
                if not isinstance(test, dict):
                    continue
                project_name = test.get("projectName")
                test_id = test.get("testId") or spec.get("id")
                identity = str(test_id) if test_id else "::".join(lineage + [spec_title])
                results = test.get("results") or []
                if not isinstance(results, list):
                    raise IngestionError("malformed_report", "Playwright test results must be an array")
                if not results:
                    status = str(test.get("status") or "unknown")
                    results = [{"status": status}]
                had_failure = False
                for result_index, result in enumerate(results):
                    if not isinstance(result, dict):
                        continue
                    status = str(result.get("status", "unknown"))
                    outcome = {
                        "passed": "passed",
                        "failed": "failed",
                        "skipped": "skipped",
                        "timedOut": "failed",
                        "interrupted": "cancelled",
                    }.get(status, "unknown")
                    message, exception_type = _playwright_error(result)
                    stdout = _stream_text(result.get("stdout"))
                    stderr = _stream_text(result.get("stderr"))
                    raw = "\n".join(value for value in [message, stdout, stderr] if value)
                    redacted = redact_text(raw[:40_000]) if raw else None
                    attachments = []
                    for attachment in result.get("attachments", []) if isinstance(result.get("attachments"), list) else []:
                        if not isinstance(attachment, dict):
                            continue
                        attachments.append(
                            {
                                "name": str(attachment.get("name") or "attachment")[:240],
                                "contentType": str(attachment.get("contentType") or "application/octet-stream")[:160],
                                "path": str(attachment.get("path") or "")[:1024] or None,
                            }
                        )
                    attempt = result.get("retry")
                    if not isinstance(attempt, int) or attempt < 0:
                        attempt = result_index
                    retry_recovered = outcome == "passed" and had_failure
                    observations.append(
                        ParsedObservation(
                            test_identity=identity,
                            suite=" / ".join(lineage) or None,
                            source_path=(
                                (spec.get("file") or suite.get("file"))
                                or (spec.get("location") or {}).get("file")
                                if isinstance(spec.get("location"), dict)
                                else spec.get("file") or suite.get("file")
                            ),
                            browser=str(project_name) if project_name is not None else None,
                            attempt=attempt,
                            outcome=outcome,
                            duration_ms=_duration_ms(result.get("duration")),
                            message=redacted.text if message and redacted else message,
                            exception_type=exception_type,
                            details={
                                "producer": "playwright-json",
                                "status": status,
                                "retry": attempt,
                                "retry_recovered": retry_recovered,
                                "attachments": attachments,
                                "worker_index": result.get("workerIndex"),
                                "parallel_index": result.get("parallelIndex"),
                                "redacted_classes": list(redacted.classes) if redacted else [],
                            },
                            evidence_excerpt=redacted.text if redacted else None,
                            evidence_locator={
                                "kind": "json-pointer",
                                "pointer": f"/suites/{'/suites/'.join(str(index) for index in suite_path)}/specs/{spec_index}/tests/{test_index}/results/{result_index}",
                                "suite": lineage,
                                "spec": spec_title,
                                "attempt": attempt,
                            },
                        )
                    )
                    had_failure = had_failure or outcome == "failed"
        children = suite.get("suites", [])
        if not isinstance(children, list):
            raise IngestionError("malformed_report", "Playwright child suites must be an array")
        for child_index, child in enumerate(children):
            if isinstance(child, dict):
                walk(child, lineage, suite_path + [child_index])

    for suite_index, suite in enumerate(suites):
        if isinstance(suite, dict):
            walk(suite, [], [suite_index])
    if not observations:
        raise IngestionError("empty_report", "Playwright JSON report contains no test results")
    return observations


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == stat.S_IFLNK


def _parse_report_bytes(content: bytes, report_name: str) -> ParsedArtifact:
    suffix = PurePosixPath(report_name).suffix.lower()
    stripped = content.lstrip()
    if suffix == ".xml" or stripped.startswith(b"<"):
        observations = parse_junit_xml(content)
        return ParsedArtifact("junit-xml", "junit-v2", report_name, tuple(observations))
    if suffix == ".json" or stripped.startswith((b"{", b"[")):
        observations = parse_playwright_json(content)
        return ParsedArtifact("playwright-json", "playwright-json-v2", report_name, tuple(observations))
    raise IngestionError("unsupported_format", f"Unsupported report type for {report_name!r}")


def parse_zip_bundle(content: bytes, filename: str, settings: Settings) -> ParsedArtifact:
    if len(content) > settings.max_bundle_bytes:
        raise IngestionError("limit_exceeded", "ZIP bundle exceeds configured upload limit")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise IngestionError("malformed_report", "ZIP bundle is malformed") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > settings.max_archive_entries:
            raise IngestionError("limit_exceeded", "ZIP bundle has too many entries")
        normalized_names: dict[str, zipfile.ZipInfo] = {}
        expanded = 0
        for info in infos:
            safe = safe_archive_name(info.filename)
            folded = safe.casefold()
            if folded in normalized_names:
                raise IngestionError("unsafe_archive", "ZIP bundle contains colliding normalized paths")
            normalized_names[folded] = info
            if info.flag_bits & 0x1:
                raise IngestionError("unsafe_archive", "Encrypted ZIP entries are not accepted")
            if _is_symlink(info):
                raise IngestionError("unsafe_archive", "ZIP symlinks are not accepted")
            expanded += info.file_size
            if expanded > settings.max_expanded_bytes:
                raise IngestionError("limit_exceeded", "ZIP expanded content exceeds configured limit")
            if info.file_size and info.compress_size == 0:
                raise IngestionError("unsafe_archive", "ZIP entry has an invalid compression size")
            if info.file_size and info.compress_size:
                ratio = info.file_size / info.compress_size
                if ratio > settings.max_compression_ratio:
                    raise IngestionError("unsafe_archive", "ZIP compression ratio exceeds configured limit")
            if PurePosixPath(safe).suffix.lower() in {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar"}:
                raise IngestionError("unsafe_archive", "Nested archives are not accepted")

        manifest_info = normalized_names.get("manifest.json")
        report_name: str | None = None
        warnings: list[str] = []
        if manifest_info is not None:
            try:
                manifest = json.loads(archive.read(manifest_info))
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
                raise IngestionError("malformed_report", "Bundle manifest.json is invalid") from exc
            if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0":
                raise IngestionError("unsupported_schema", "Bundle manifest requires schema_version 1.0")
            candidate = manifest.get("report")
            if not isinstance(candidate, str):
                raise IngestionError("malformed_report", "Bundle manifest requires a report path")
            report_name = safe_archive_name(candidate)
            if report_name.casefold() not in normalized_names:
                raise IngestionError("missing_attachment", "Bundle manifest report path is absent")
        else:
            candidates = [
                info.filename
                for info in infos
                if not info.is_dir() and PurePosixPath(info.filename).suffix.lower() in {".xml", ".json"}
            ]
            candidates = [candidate for candidate in candidates if candidate.casefold() != "manifest.json"]
            if len(candidates) != 1:
                raise IngestionError(
                    "ambiguous_bundle",
                    "Bundle without manifest.json must contain exactly one XML or JSON report",
                )
            report_name = safe_archive_name(candidates[0])
            warnings.append("bundle_manifest_missing")

        info = normalized_names[report_name.casefold()]
        if info.file_size > settings.max_file_bytes:
            raise IngestionError("limit_exceeded", "Report inside bundle exceeds configured file limit")
        report_content = archive.read(info)
        parsed = _parse_report_bytes(report_content, report_name)
        return ParsedArtifact(
            source_format=f"zip+{parsed.source_format}",
            parser_version=f"zip-v1/{parsed.parser_version}",
            report_name=report_name,
            observations=parsed.observations,
            warnings=tuple(warnings),
        )


def parse_artifact(content: bytes, filename: str, settings: Settings) -> ParsedArtifact:
    if not content:
        raise IngestionError("empty_upload", "Artifact is empty")
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix == ".zip" or content.startswith(b"PK\x03\x04"):
        return parse_zip_bundle(content, filename, settings)
    if len(content) > settings.max_file_bytes:
        raise IngestionError("limit_exceeded", "Artifact exceeds configured file limit")
    return _parse_report_bytes(content, filename)
