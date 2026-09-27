from __future__ import annotations

import hashlib
import io
import json
import re
import stat
import struct
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Callable

from .config import Settings
from .redaction import redact_text

PARSER_VERSION = "ingestion-v3"
REGISTRY_VERSION = "adapter-registry-v1"
MANIFEST_V2 = "2.0"
MAX_MANIFEST_BYTES = 1_000_000
MAX_CONSOLE_EVENTS = 10_000
MAX_NETWORK_EVENTS = 20_000
MAX_K6_METRICS = 5_000
MAX_REST_EXCHANGES = 5_000
MAX_CHANGED_FILES = 20_000


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
    parameterization: str | None = None


@dataclass(frozen=True)
class AdapterResult:
    observations: tuple[ParsedObservation, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    restricted: bool = False


@dataclass(frozen=True)
class ParsedInput:
    input_id: str
    kind: str
    path: str | None
    required: bool
    status: str
    digest: str | None
    size_bytes: int | None
    media_type: str
    parser_version: str | None
    observations: tuple[ParsedObservation, ...] = ()
    warnings: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedArtifact:
    source_format: str
    parser_version: str
    report_name: str
    observations: tuple[ParsedObservation, ...]
    warnings: tuple[str, ...] = ()
    manifest_version: str = "standalone"
    expected_inputs: int = 1
    received_inputs: int = 1
    completeness: str = "complete"
    inputs: tuple[ParsedInput, ...] = ()


Parser = Callable[[bytes, str, Settings], AdapterResult]
Detector = Callable[[bytes, str], bool]


@dataclass(frozen=True)
class AdapterSpec:
    kind: str
    parser_version: str
    parser: Parser
    aliases: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = ()
    media_types: tuple[str, ...] = ()
    detector: Detector | None = None


_ADAPTERS: dict[str, AdapterSpec] = {}
_ALIASES: dict[str, str] = {}


def _register(spec: AdapterSpec) -> None:
    if spec.kind in _ADAPTERS:
        raise RuntimeError(f"duplicate ingestion adapter: {spec.kind}")
    _ADAPTERS[spec.kind] = spec
    for alias in (spec.kind, *spec.aliases):
        normalized = alias.strip().lower()
        if normalized in _ALIASES:
            raise RuntimeError(f"duplicate ingestion adapter alias: {normalized}")
        _ALIASES[normalized] = spec.kind


def supported_adapter_kinds() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTERS))


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


def _json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        data = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise IngestionError("malformed_report", f"Malformed {label}: {exc}") from exc
    if not isinstance(data, dict):
        raise IngestionError("unsupported_format", f"{label} root must be an object")
    return data


def _safe_json_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return "[depth-limited]"
    if isinstance(value, str):
        return redact_text(value[:10_000]).text
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:200]:
            safe_key = str(key)[:240]
            if safe_key.lower() in {
                "authorization",
                "cookie",
                "set-cookie",
                "password",
                "token",
                "access_token",
                "refresh_token",
                "api_key",
            }:
                result[safe_key] = "[REDACTED]"
            else:
                result[safe_key] = _safe_json_value(item, depth=depth + 1)
        return result
    if isinstance(value, list):
        return [_safe_json_value(item, depth=depth + 1) for item in value[:200]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(str(value)[:10_000]).text


def _sanitize_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=500)
    except ValueError:
        return redact_text(value[:2048]).text
    safe_query = urllib.parse.urlencode([(key[:240], "[REDACTED]") for key, _ in query])
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, safe_query, "")
    )[:2048]


def _strip_terminal_controls(value: str) -> tuple[str, bool]:
    ansi = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
    cleaned = ansi.sub("", value)
    transformed = cleaned != value
    filtered = "".join(
        char for char in cleaned if char in "\n\r\t" or ord(char) >= 32
    )
    return filtered, transformed or filtered != cleaned


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
        properties: dict[str, str] = {}
        for child in list(suite):
            if child.tag.rsplit("}", 1)[-1] != "properties":
                continue
            for prop in list(child):
                if prop.tag.rsplit("}", 1)[-1] == "property" and prop.attrib.get("name"):
                    properties[prop.attrib["name"]] = str(
                        prop.attrib.get("value") or prop.text or ""
                    )[:2000]
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
                        "properties": _safe_json_value(properties),
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
    data = _json_object(content, "Playwright JSON")
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
                    for attachment in (
                        result.get("attachments", [])
                        if isinstance(result.get("attachments"), list)
                        else []
                    ):
                        if not isinstance(attachment, dict):
                            continue
                        attachments.append(
                            {
                                "name": str(attachment.get("name") or "attachment")[:240],
                                "contentType": str(
                                    attachment.get("contentType") or "application/octet-stream"
                                )[:160],
                                "path": str(attachment.get("path") or "")[:1024] or None,
                            }
                        )
                    attempt = result.get("retry")
                    if not isinstance(attempt, int) or attempt < 0:
                        attempt = result_index
                    retry_recovered = outcome == "passed" and had_failure
                    location = spec.get("location")
                    source_path = spec.get("file") or suite.get("file")
                    if not source_path and isinstance(location, dict):
                        source_path = location.get("file")
                    observations.append(
                        ParsedObservation(
                            test_identity=identity,
                            suite=" / ".join(lineage) or None,
                            source_path=str(source_path) if source_path else None,
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


def parse_pytest_json(content: bytes) -> list[ParsedObservation]:
    data = _json_object(content, "pytest-json-report")
    tests = data.get("tests")
    if not isinstance(tests, list):
        raise IngestionError("unsupported_format", "pytest JSON report requires a tests array")
    observations: list[ParsedObservation] = []
    for index, test in enumerate(tests):
        if not isinstance(test, dict):
            continue
        nodeid = str(test.get("nodeid") or "").strip()
        if not nodeid:
            raise IngestionError("malformed_report", "pytest test entry is missing nodeid")
        raw_outcome = str(test.get("outcome") or "unknown")
        outcome = {
            "passed": "passed",
            "failed": "failed",
            "skipped": "skipped",
            "xfailed": "skipped",
            "xpassed": "failed",
        }.get(raw_outcome, "unknown")
        phases: dict[str, Any] = {}
        messages: list[str] = []
        exception_type: str | None = None
        total_duration = 0.0
        for phase_name in ("setup", "call", "teardown"):
            phase = test.get(phase_name)
            if not isinstance(phase, dict):
                continue
            crash = phase.get("crash") if isinstance(phase.get("crash"), dict) else {}
            longrepr = phase.get("longrepr")
            message = crash.get("message") or longrepr
            if message:
                messages.append(f"{phase_name}: {message}")
            if not exception_type and crash.get("message"):
                exception_type = str(crash.get("message")).split(":", 1)[0][:240]
            duration = _duration_ms(phase.get("duration"), multiplier=1000)
            if duration is not None:
                total_duration += duration
            phases[phase_name] = {
                "outcome": phase.get("outcome"),
                "duration_ms": duration,
                "crash": _safe_json_value(crash),
                "stdout": redact_text(str(phase.get("stdout") or "")[:10_000]).text,
                "stderr": redact_text(str(phase.get("stderr") or "")[:10_000]).text,
            }
        raw = "\n".join(messages)
        redacted = redact_text(raw[:40_000]) if raw else None
        parameterization = None
        match = re.search(r"\[([^\]]+)\]$", nodeid)
        if match:
            parameterization = match.group(1)[:512]
        source_path = nodeid.split("::", 1)[0]
        observations.append(
            ParsedObservation(
                test_identity=nodeid,
                suite="pytest",
                source_path=source_path,
                browser=None,
                attempt=0,
                outcome=outcome,
                duration_ms=total_duration or _duration_ms(test.get("duration"), multiplier=1000),
                message=redacted.text if redacted else None,
                exception_type=exception_type,
                details={
                    "producer": "pytest-json-report",
                    "raw_outcome": raw_outcome,
                    "keywords": [str(item)[:240] for item in test.get("keywords", [])[:100]]
                    if isinstance(test.get("keywords"), list)
                    else [],
                    "wasxfail": test.get("wasxfail"),
                    "phases": phases,
                    "redacted_classes": list(redacted.classes) if redacted else [],
                },
                evidence_excerpt=redacted.text if redacted else None,
                evidence_locator={"kind": "json-pointer", "pointer": f"/tests/{index}"},
                parameterization=parameterization,
            )
        )
    collectors = data.get("collectors", [])
    if isinstance(collectors, list):
        for index, collector in enumerate(collectors):
            if not isinstance(collector, dict) or collector.get("outcome") != "failed":
                continue
            nodeid = str(collector.get("nodeid") or f"collector-{index}")
            raw = str(collector.get("longrepr") or collector.get("result") or "collection failed")
            redacted = redact_text(raw[:40_000])
            observations.append(
                ParsedObservation(
                    test_identity=f"collection::{nodeid}",
                    suite="pytest collection",
                    source_path=nodeid.split("::", 1)[0],
                    browser=None,
                    attempt=0,
                    outcome="failed",
                    duration_ms=None,
                    message=redacted.text,
                    exception_type="CollectionError",
                    details={"producer": "pytest-json-report", "collection_error": True},
                    evidence_excerpt=redacted.text,
                    evidence_locator={
                        "kind": "json-pointer",
                        "pointer": f"/collectors/{index}",
                    },
                )
            )
    if not observations:
        raise IngestionError("empty_report", "pytest JSON report contains no tests or collection errors")
    return observations


def _junit_adapter(content: bytes, _: str, __: Settings) -> AdapterResult:
    return AdapterResult(observations=tuple(parse_junit_xml(content)))


def _rest_assured_junit_adapter(content: bytes, _: str, __: Settings) -> AdapterResult:
    observations = []
    for observation in parse_junit_xml(content):
        observations.append(
            ParsedObservation(
                **{
                    **observation.__dict__,
                    "details": {**observation.details, "producer": "rest-assured-junit"},
                }
            )
        )
    return AdapterResult(observations=tuple(observations))


def _playwright_adapter(content: bytes, _: str, __: Settings) -> AdapterResult:
    return AdapterResult(observations=tuple(parse_playwright_json(content)))


def _pytest_adapter(content: bytes, _: str, __: Settings) -> AdapterResult:
    data = _json_object(content, "pytest-json-report")
    return AdapterResult(
        observations=tuple(parse_pytest_json(content)),
        metadata={
            "producer": "pytest-json-report",
            "exitcode": data.get("exitcode"),
            "summary": _safe_json_value(data.get("summary", {})),
            "environment": _safe_json_value(data.get("environment", {})),
        },
    )


def _k6_adapter(content: bytes, _: str, __: Settings) -> AdapterResult:
    data = _json_object(content, "k6 summary JSON")
    metrics = data.get("metrics")
    if not isinstance(metrics, dict):
        raise IngestionError("unsupported_format", "k6 summary requires a metrics object")
    observations: list[ParsedObservation] = []
    metric_summaries: dict[str, Any] = {}
    metric_items = list(metrics.items())
    metrics_truncated = len(metric_items) > MAX_K6_METRICS
    for metric_name, metric in metric_items[:MAX_K6_METRICS]:
        if not isinstance(metric, dict):
            continue
        values = metric.get("values") if isinstance(metric.get("values"), dict) else {}
        thresholds = metric.get("thresholds") if isinstance(metric.get("thresholds"), dict) else {}
        safe_values = {
            str(key)[:120]: value
            for key, value in list(values.items())[:100]
            if isinstance(value, (int, float, bool))
        }
        threshold_summary: dict[str, bool | None] = {}
        for threshold_name, threshold in list(thresholds.items())[:100]:
            ok: bool | None
            if isinstance(threshold, dict):
                ok = threshold.get("ok") if isinstance(threshold.get("ok"), bool) else None
            elif isinstance(threshold, bool):
                ok = threshold
            else:
                ok = None
            threshold_summary[str(threshold_name)[:240]] = ok
            if ok is False:
                message = (
                    f"k6 threshold failed: {metric_name} {threshold_name}; "
                    f"exported values={json.dumps(safe_values, sort_keys=True)}"
                )
                observations.append(
                    ParsedObservation(
                        test_identity=f"k6::{metric_name}::{threshold_name}",
                        suite="k6 thresholds",
                        source_path=None,
                        browser=None,
                        attempt=0,
                        outcome="failed",
                        duration_ms=None,
                        message=message,
                        exception_type="PerformanceThresholdError",
                        details={
                            "producer": "k6-handleSummary",
                            "metric": metric_name,
                            "metric_type": metric.get("type"),
                            "contains": metric.get("contains"),
                            "threshold": threshold_name,
                            "values": safe_values,
                        },
                        evidence_excerpt=message,
                        evidence_locator={
                            "kind": "json-pointer",
                            "pointer": f"/metrics/{_json_pointer_escape(str(metric_name))}/thresholds/{_json_pointer_escape(str(threshold_name))}",
                        },
                    )
                )
        metric_summaries[str(metric_name)[:240]] = {
            "type": metric.get("type"),
            "contains": metric.get("contains"),
            "values": safe_values,
            "thresholds": threshold_summary,
        }
    return AdapterResult(
        observations=tuple(observations),
        metadata={
            "producer": "k6-handleSummary",
            "metrics": metric_summaries,
            "threshold_failures": len(observations),
            "state": _safe_json_value(data.get("state", {})),
        },
        warnings=(
            "performance_observations_are_not_aggregated_quantiles",
            *(("metric_limit_reached",) if metrics_truncated else ()),
        ),
    )


def _console_text_adapter(content: bytes, _: str, settings: Settings) -> AdapterResult:
    try:
        raw = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IngestionError("malformed_encoding", "Console text must be UTF-8") from exc
    cleaned, transformed = _strip_terminal_controls(raw)
    retained = cleaned[: settings.analysis_text_budget]
    redacted = redact_text(retained)
    warnings = []
    if transformed:
        warnings.append("terminal_controls_removed")
    if len(cleaned) > len(retained):
        warnings.append("content_truncated")
    return AdapterResult(
        metadata={
            "producer": "console-text",
            "line_count": cleaned.count("\n") + (1 if cleaned else 0),
            "original_characters": len(cleaned),
            "retained_characters": len(retained),
            "safe_preview": redacted.text,
            "redacted_classes": list(redacted.classes),
        },
        warnings=tuple(warnings),
    )


def _console_jsonl_adapter(content: bytes, _: str, settings: Settings) -> AdapterResult:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IngestionError("malformed_encoding", "Console JSONL must be UTF-8") from exc
    events: list[dict[str, Any]] = []
    error_events = 0
    events_truncated = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        if len(events) >= MAX_CONSOLE_EVENTS:
            events_truncated = True
            break
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IngestionError(
                "malformed_report", f"Console JSONL line {line_number} is invalid: {exc}"
            ) from exc
        if not isinstance(event, dict):
            raise IngestionError(
                "malformed_report", f"Console JSONL line {line_number} must be an object"
            )
        safe_event = _safe_json_value(event)
        events.append(safe_event)
        level = str(event.get("level") or event.get("severity") or "").lower()
        if level in {"error", "fatal", "critical"}:
            error_events += 1
    if not events:
        raise IngestionError("empty_report", "Console JSONL contains no events")
    preview = "\n".join(json.dumps(event, sort_keys=True) for event in events)
    return AdapterResult(
        metadata={
            "producer": "console-jsonl",
            "event_count": len(events),
            "error_event_count": error_events,
            "safe_preview": preview[: settings.analysis_text_budget],
        },
        warnings=(
            *(("content_truncated",) if len(preview) > settings.analysis_text_budget else ()),
            *(("event_limit_reached",) if events_truncated else ()),
        ),
    )


def _har_adapter(content: bytes, _: str, __: Settings) -> AdapterResult:
    data = _json_object(content, "HAR")
    log = data.get("log")
    if not isinstance(log, dict) or not isinstance(log.get("entries"), list):
        raise IngestionError("unsupported_format", "HAR requires log.entries")
    entries = log["entries"]
    observations: list[ParsedObservation] = []
    status_counts: dict[str, int] = {}
    entries_truncated = len(entries) > MAX_NETWORK_EVENTS
    for index, entry in enumerate(entries[:MAX_NETWORK_EVENTS]):
        if not isinstance(entry, dict):
            continue
        request = entry.get("request") if isinstance(entry.get("request"), dict) else {}
        response = entry.get("response") if isinstance(entry.get("response"), dict) else {}
        method = str(request.get("method") or "GET")[:32]
        url = _sanitize_url(str(request.get("url") or ""))
        status_value = response.get("status")
        try:
            status = int(status_value)
        except (TypeError, ValueError):
            status = 0
        status_counts[str(status)] = status_counts.get(str(status), 0) + 1
        error = entry.get("_error") or response.get("_error")
        if status >= 400 or error:
            message = f"HAR network failure: {method} {url} returned {status or 'unknown'}"
            if error:
                message += f"; error={redact_text(str(error)[:2000]).text}"
            observations.append(
                ParsedObservation(
                    test_identity=f"network::{method}::{url}",
                    suite="HAR network",
                    source_path=None,
                    browser=None,
                    attempt=0,
                    outcome="failed",
                    duration_ms=_duration_ms(entry.get("time")),
                    message=message,
                    exception_type="HttpError" if status else "NetworkError",
                    details={
                        "producer": "har-1.2",
                        "method": method,
                        "url": url,
                        "status": status or None,
                        "timings": _safe_json_value(entry.get("timings", {})),
                    },
                    evidence_excerpt=message,
                    evidence_locator={
                        "kind": "json-pointer",
                        "pointer": f"/log/entries/{index}",
                    },
                )
            )
    return AdapterResult(
        observations=tuple(observations),
        metadata={
            "producer": "har",
            "version": log.get("version"),
            "entry_count": len(entries),
            "status_counts": status_counts,
            "failed_event_count": len(observations),
            "retained_entry_count": min(len(entries), MAX_NETWORK_EVENTS),
        },
        warnings=("event_limit_reached",) if entries_truncated else (),
    )


def _network_jsonl_adapter(content: bytes, _: str, __: Settings) -> AdapterResult:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IngestionError("malformed_encoding", "Network JSONL must be UTF-8") from exc
    observations: list[ParsedObservation] = []
    count = 0
    events_truncated = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        if count >= MAX_NETWORK_EVENTS:
            events_truncated = True
            break
        count += 1
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IngestionError(
                "malformed_report", f"Network JSONL line {line_number} is invalid: {exc}"
            ) from exc
        if not isinstance(event, dict):
            raise IngestionError(
                "malformed_report", f"Network JSONL line {line_number} must be an object"
            )
        method = str(event.get("method") or "GET")[:32]
        url = _sanitize_url(str(event.get("url") or event.get("route") or ""))
        status_value = event.get("status")
        try:
            status = int(status_value) if status_value is not None else 0
        except (TypeError, ValueError):
            status = 0
        error = event.get("error")
        attempt_value = event.get("attempt", 0)
        try:
            attempt = max(int(attempt_value or 0), 0)
        except (TypeError, ValueError) as exc:
            raise IngestionError(
                "malformed_report", f"Network JSONL line {line_number} has an invalid attempt"
            ) from exc
        if status >= 400 or error:
            message = f"Network event failure: {method} {url} returned {status or 'unknown'}"
            if error:
                message += f"; error={redact_text(str(error)[:2000]).text}"
            observations.append(
                ParsedObservation(
                    test_identity=f"network::{method}::{url}",
                    suite="network-jsonl",
                    source_path=None,
                    browser=str(event.get("browser"))[:80] if event.get("browser") else None,
                    attempt=attempt,
                    outcome="failed",
                    duration_ms=_duration_ms(event.get("duration_ms")),
                    message=message,
                    exception_type="HttpError" if status else "NetworkError",
                    details={
                        "producer": "network-jsonl",
                        "method": method,
                        "url": url,
                        "status": status or None,
                        "timestamp": event.get("timestamp"),
                    },
                    evidence_excerpt=message,
                    evidence_locator={"kind": "text-line", "line": line_number},
                )
            )
    if count == 0:
        raise IngestionError("empty_report", "Network JSONL contains no events")
    return AdapterResult(
        observations=tuple(observations),
        metadata={"producer": "network-jsonl", "event_count": count},
        warnings=("event_limit_reached",) if events_truncated else (),
    )


def _rest_assured_evidence_adapter(content: bytes, _: str, settings: Settings) -> AdapterResult:
    data = _json_object(content, "REST Assured evidence")
    exchanges = data.get("exchanges")
    if not isinstance(exchanges, list):
        raise IngestionError("unsupported_format", "REST Assured evidence requires exchanges")
    safe_exchanges: list[dict[str, Any]] = []
    exchanges_truncated = len(exchanges) > MAX_REST_EXCHANGES
    for exchange in exchanges[:MAX_REST_EXCHANGES]:
        if not isinstance(exchange, dict):
            continue
        safe_exchanges.append(
            {
                "test_identity": str(exchange.get("test_identity") or "")[:512] or None,
                "method": str(exchange.get("method") or "GET")[:32],
                "route": _sanitize_url(str(exchange.get("route") or exchange.get("url") or "")),
                "status": exchange.get("status"),
                "assertion": redact_text(str(exchange.get("assertion") or "")[:5000]).text,
                "request": _safe_json_value(exchange.get("request", {})),
                "response": _safe_json_value(exchange.get("response", {})),
            }
        )
    preview = json.dumps(safe_exchanges, sort_keys=True)
    return AdapterResult(
        metadata={
            "producer": "rest-assured-evidence",
            "exchange_count": len(safe_exchanges),
            "safe_preview": preview[: settings.analysis_text_budget],
        },
        warnings=(
            *(("content_truncated",) if len(preview) > settings.analysis_text_budget else ()),
            *(("event_limit_reached",) if exchanges_truncated else ()),
        ),
    )


def _github_metadata_adapter(content: bytes, _: str, __: Settings) -> AdapterResult:
    data = _json_object(content, "GitHub metadata")
    commit_sha = data.get("commit_sha") or data.get("head_sha")
    for field, value in {
        "commit_sha": commit_sha,
        "base_sha": data.get("base_sha"),
        "parent_sha": data.get("parent_sha"),
    }.items():
        if value is not None and not re.fullmatch(r"[0-9a-fA-F]{7,64}", str(value)):
            raise IngestionError("malformed_report", f"GitHub metadata has an invalid {field}")
    safe = {
        "repository": str(data.get("repository") or "")[:240] or None,
        "commit_sha": str(commit_sha) if commit_sha else None,
        "base_sha": str(data.get("base_sha") or "")[:64] or None,
        "parent_sha": str(data.get("parent_sha") or "")[:64] or None,
        "branch": str(data.get("branch") or "")[:240] or None,
        "pull_request": data.get("pull_request"),
        "workflow": str(data.get("workflow") or "")[:240] or None,
        "run_id": str(data.get("run_id") or "")[:120] or None,
        "run_attempt": data.get("run_attempt"),
        "trigger": str(data.get("trigger") or "")[:120] or None,
        "author_display": redact_text(str(data.get("author_display") or "")[:240]).text or None,
        "trust": str(data.get("trust") or "self_reported")[:80],
    }
    return AdapterResult(metadata={"producer": "github-metadata", **safe})


def _changed_files_adapter(content: bytes, _: str, __: Settings) -> AdapterResult:
    data = _json_object(content, "changed-file list")
    trust = str(data.get("trust") or "self_reported").casefold()
    if trust not in {"self_reported", "authenticated_lookup", "trusted_workflow"}:
        raise IngestionError(
            "malformed_report",
            "Changed-file input trust must be self_reported, authenticated_lookup, or trusted_workflow",
        )
    files = data.get("files")
    if not isinstance(files, list):
        raise IngestionError("unsupported_format", "Changed-file input requires a files array")
    for field in ("base_sha", "head_sha"):
        value = data.get(field)
        if value is not None and not re.fullmatch(r"[0-9a-fA-F]{7,64}", str(value)):
            raise IngestionError("malformed_report", f"Changed-file input has an invalid {field}")
    files_truncated = len(files) > MAX_CHANGED_FILES
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(files[:MAX_CHANGED_FILES]):
        if isinstance(item, str):
            item = {"path": item, "status": "modified"}
        if not isinstance(item, dict):
            raise IngestionError(
                "malformed_report", f"Changed-file entry {index} must be an object or path"
            )
        status = str(item.get("status") or "modified").lower()
        if status not in {"added", "modified", "deleted", "renamed", "copied"}:
            raise IngestionError("malformed_report", f"Unsupported changed-file status: {status}")
        path = item.get("path") or item.get("new_path")
        if not isinstance(path, str) or not path.strip():
            raise IngestionError("malformed_report", f"Changed-file entry {index} has no path")
        safe_path = safe_archive_name(path)
        old_path = item.get("old_path")
        normalized.append(
            {
                "status": status,
                "path": safe_path,
                "old_path": safe_archive_name(old_path) if isinstance(old_path, str) else None,
                "coverage_reference": str(item.get("coverage_reference") or "")[:1024] or None,
                "diff_reference": str(item.get("diff_reference") or "")[:1024] or None,
            }
        )
    complete = data.get("complete")
    if not isinstance(complete, bool):
        complete = False
    warnings = (
        *(("changed_file_list_incomplete",) if not complete else ()),
        *(("file_limit_reached",) if files_truncated else ()),
    )
    return AdapterResult(
        metadata={
            "producer": "changed-files",
            "base_sha": data.get("base_sha"),
            "head_sha": data.get("head_sha"),
            "complete": complete,
            # Artifact bytes are untrusted data.  Preserve the producer's claim for
            # audit only; the effective trust level is bound later from authenticated
            # ingestion metadata at the service boundary.
            "declared_trust": trust,
            "trust": "self_reported",
            "trust_source": "artifact_default",
            "pagination": _safe_json_value(data.get("pagination", {})),
            "files": normalized,
            "file_count": len(normalized),
        },
        warnings=warnings,
    )


def _image_dimensions(content: bytes) -> tuple[str, int, int]:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(content) < 24 or content[12:16] != b"IHDR":
            raise IngestionError("malformed_report", "PNG is missing a valid IHDR")
        width, height = struct.unpack(">II", content[16:24])
        return "image/png", width, height
    if content.startswith(b"\xff\xd8"):
        position = 2
        while position + 4 <= len(content):
            if content[position] != 0xFF:
                position += 1
                continue
            marker = content[position + 1]
            position += 2
            if marker in {0xD8, 0xD9}:
                continue
            if position + 2 > len(content):
                break
            length = int.from_bytes(content[position : position + 2], "big")
            if length < 2 or position + length > len(content):
                break
            if marker in {
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            }:
                if length < 7:
                    break
                height = int.from_bytes(content[position + 3 : position + 5], "big")
                width = int.from_bytes(content[position + 5 : position + 7], "big")
                return "image/jpeg", width, height
            position += length
        raise IngestionError("malformed_report", "JPEG dimensions could not be decoded")
    raise IngestionError("unsupported_format", "Screenshot must be PNG or JPEG")


def _screenshot_adapter(content: bytes, _: str, settings: Settings) -> AdapterResult:
    media_type, width, height = _image_dimensions(content)
    if width <= 0 or height <= 0:
        raise IngestionError("malformed_report", "Screenshot dimensions must be positive")
    pixels = width * height
    if pixels > settings.max_image_pixels:
        raise IngestionError(
            "limit_exceeded",
            f"Screenshot has {pixels} pixels, exceeding {settings.max_image_pixels}",
        )
    return AdapterResult(
        metadata={
            "producer": "screenshot",
            "media_type": media_type,
            "width": width,
            "height": height,
            "pixels": pixels,
            "review_state": "restricted",
            "safe_derivative": "metadata-only",
        },
        warnings=("pixel_content_not_sanitized", "review_required_before_display"),
        restricted=True,
    )


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == stat.S_IFLNK


def _validate_zip_infos(
    infos: list[zipfile.ZipInfo],
    settings: Settings,
    *,
    allow_nested_paths: set[str] | None = None,
) -> dict[str, zipfile.ZipInfo]:
    if len(infos) > settings.max_archive_entries:
        raise IngestionError("limit_exceeded", "ZIP archive has too many entries")
    allowed = {item.casefold() for item in (allow_nested_paths or set())}
    normalized_names: dict[str, zipfile.ZipInfo] = {}
    expanded = 0
    for info in infos:
        safe = safe_archive_name(info.filename)
        folded = safe.casefold()
        if folded in normalized_names:
            raise IngestionError("unsafe_archive", "ZIP contains colliding normalized paths")
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
        suffix = PurePosixPath(safe).suffix.lower()
        if suffix in {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar"} and folded not in allowed:
            raise IngestionError("unsafe_archive", "Nested archives are not accepted")
    return normalized_names


def _trace_adapter(content: bytes, _: str, settings: Settings) -> AdapterResult:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise IngestionError("malformed_report", "Playwright trace archive is malformed") from exc
    with archive:
        names = _validate_zip_infos(archive.infolist(), settings)
        trace_candidates = [
            info for name, info in names.items() if name.endswith("trace.trace") or name == "trace.trace"
        ]
        if not trace_candidates:
            raise IngestionError("unsupported_format", "Playwright trace archive has no trace.trace")
        event_count = 0
        error_count = 0
        action_count = 0
        for trace_info in trace_candidates[:20]:
            if trace_info.file_size > settings.max_file_bytes:
                raise IngestionError("limit_exceeded", "Trace event stream exceeds file limit")
            raw = archive.read(trace_info)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise IngestionError("malformed_encoding", "Trace event stream must be UTF-8") from exc
            for line in text.splitlines()[:50_000]:
                if not line.strip():
                    continue
                event_count += 1
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                event_type = str(event.get("type") or "").lower()
                if event_type in {"before", "after", "action"}:
                    action_count += 1
                if event_type in {"error", "console"} and (
                    event_type == "error" or str(event.get("messageType") or "").lower() == "error"
                ):
                    error_count += 1
        return AdapterResult(
            metadata={
                "producer": "playwright-trace",
                "archive_entries": len(names),
                "trace_streams": len(trace_candidates),
                "event_count": event_count,
                "action_count": action_count,
                "error_event_count": error_count,
                "review_state": "restricted",
                "safe_derivative": "bounded-metadata-index",
            },
            warnings=("trace_original_restricted", "trace_dom_and_network_not_sanitized"),
            restricted=True,
        )


def _json_pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _looks_like_json_key(content: bytes, key: str) -> bool:
    try:
        data = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and key in data


def _detect_pytest(content: bytes, _: str) -> bool:
    try:
        data = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and isinstance(data.get("tests"), list) and (
        "summary" in data or "exitcode" in data or "collectors" in data
    )


def _detect_changed_files(content: bytes, filename: str) -> bool:
    try:
        data = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "changes" in filename.lower()
    return isinstance(data, dict) and isinstance(data.get("files"), list) and (
        "base_sha" in data or "head_sha" in data or "complete" in data
    )


def _detect_github_metadata(content: bytes, filename: str) -> bool:
    try:
        data = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "github" in filename.lower()
    return isinstance(data, dict) and (
        "repository" in data and ("commit_sha" in data or "head_sha" in data)
    )


def _register_adapters() -> None:
    _register(
        AdapterSpec(
            kind="junit-xml",
            parser_version="junit-v3",
            parser=_junit_adapter,
            aliases=("junit", "xml"),
            suffixes=(".xml",),
            media_types=("application/xml", "text/xml"),
            detector=lambda content, _: content.lstrip().startswith(b"<"),
        )
    )
    _register(
        AdapterSpec(
            kind="rest-assured-junit",
            parser_version="rest-assured-junit-v1",
            parser=_rest_assured_junit_adapter,
            aliases=("rest-assured",),
        )
    )
    _register(
        AdapterSpec(
            kind="playwright-json",
            parser_version="playwright-json-v3",
            parser=_playwright_adapter,
            aliases=("playwright",),
            suffixes=(".json",),
            detector=lambda content, _: _looks_like_json_key(content, "suites"),
        )
    )
    _register(
        AdapterSpec(
            kind="pytest-json-report",
            parser_version="pytest-json-report-v1",
            parser=_pytest_adapter,
            aliases=("pytest-json", "pytest"),
            suffixes=(".json",),
            detector=_detect_pytest,
        )
    )
    _register(
        AdapterSpec(
            kind="k6-summary-json",
            parser_version="k6-summary-v1",
            parser=_k6_adapter,
            aliases=("k6", "k6-summary"),
            suffixes=(".json",),
            detector=lambda content, _: _looks_like_json_key(content, "metrics"),
        )
    )
    _register(
        AdapterSpec(
            kind="console-text",
            parser_version="console-text-v1",
            parser=_console_text_adapter,
            aliases=("text-log", "log"),
            suffixes=(".log", ".txt"),
            media_types=("text/plain",),
        )
    )
    _register(
        AdapterSpec(
            kind="console-jsonl",
            parser_version="console-jsonl-v1",
            parser=_console_jsonl_adapter,
            aliases=("jsonl-log",),
            suffixes=(".jsonl",),
        )
    )
    _register(
        AdapterSpec(
            kind="har",
            parser_version="har-v1",
            parser=_har_adapter,
            aliases=("har-1.2",),
            suffixes=(".har",),
            detector=lambda content, _: _looks_like_json_key(content, "log"),
        )
    )
    _register(
        AdapterSpec(
            kind="network-jsonl",
            parser_version="network-jsonl-v1",
            parser=_network_jsonl_adapter,
            aliases=("network-log",),
            suffixes=(".jsonl",),
        )
    )
    _register(
        AdapterSpec(
            kind="rest-assured-evidence",
            parser_version="rest-assured-evidence-v1",
            parser=_rest_assured_evidence_adapter,
            aliases=("rest-assured-http-json",),
            suffixes=(".json",),
            detector=lambda content, _: _looks_like_json_key(content, "exchanges"),
        )
    )
    _register(
        AdapterSpec(
            kind="github-metadata",
            parser_version="github-metadata-v1",
            parser=_github_metadata_adapter,
            aliases=("github-commit-metadata",),
            suffixes=(".json",),
            detector=_detect_github_metadata,
        )
    )
    _register(
        AdapterSpec(
            kind="changed-files",
            parser_version="changed-files-v1",
            parser=_changed_files_adapter,
            aliases=("changed-file-list", "changes"),
            suffixes=(".json",),
            detector=_detect_changed_files,
        )
    )
    _register(
        AdapterSpec(
            kind="screenshot",
            parser_version="screenshot-metadata-v1",
            parser=_screenshot_adapter,
            aliases=("png", "jpeg", "image"),
            suffixes=(".png", ".jpg", ".jpeg"),
            media_types=("image/png", "image/jpeg"),
            detector=lambda content, _: content.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8")),
        )
    )
    _register(
        AdapterSpec(
            kind="playwright-trace",
            parser_version="playwright-trace-index-v1",
            parser=_trace_adapter,
            aliases=("trace",),
            suffixes=(".zip",),
        )
    )


_register_adapters()


def _resolve_adapter(
    content: bytes,
    filename: str,
    *,
    kind: str = "auto",
    media_type: str | None = None,
) -> AdapterSpec:
    requested = kind.strip().lower()
    if requested != "auto":
        canonical = _ALIASES.get(requested)
        if not canonical:
            raise IngestionError("unsupported_format", f"Unsupported input kind: {kind}")
        return _ADAPTERS[canonical]

    normalized_media = (media_type or "").split(";", 1)[0].strip().lower()
    suffix = PurePosixPath(filename).suffix.lower()
    candidates: list[AdapterSpec] = []
    for spec in _ADAPTERS.values():
        if spec.kind == "playwright-trace":
            continue
        if spec.detector and spec.detector(content, filename):
            candidates.append(spec)
    if candidates:
        priority = {
            "pytest-json-report": 10,
            "playwright-json": 20,
            "k6-summary-json": 30,
            "har": 40,
            "rest-assured-evidence": 50,
            "changed-files": 60,
            "github-metadata": 70,
            "junit-xml": 80,
            "screenshot": 90,
        }
        return sorted(candidates, key=lambda item: priority.get(item.kind, 100))[0]
    if suffix == ".json" or normalized_media in {
        "application/json",
        "application/json-report",
    }:
        try:
            json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IngestionError("malformed_report", f"Malformed JSON input: {exc}") from exc

    media_candidates = [spec for spec in _ADAPTERS.values() if normalized_media in spec.media_types]
    if len(media_candidates) == 1:
        return media_candidates[0]
    suffix_candidates = [spec for spec in _ADAPTERS.values() if suffix in spec.suffixes]
    if suffix == ".jsonl":
        lowered = filename.lower()
        return _ADAPTERS["network-jsonl"] if "network" in lowered or "har" in lowered else _ADAPTERS["console-jsonl"]
    if suffix_candidates:
        non_json = [spec for spec in suffix_candidates if suffix != ".json"]
        if len(non_json) == 1:
            return non_json[0]
    raise IngestionError("unsupported_format", f"Unable to detect input type for {filename!r}")


def _parse_input_bytes(
    content: bytes,
    filename: str,
    settings: Settings,
    *,
    kind: str = "auto",
    media_type: str | None = None,
) -> tuple[AdapterSpec, AdapterResult]:
    spec = _resolve_adapter(content, filename, kind=kind, media_type=media_type)
    result = spec.parser(content, filename, settings)
    return spec, result


def _parsed_input(
    *,
    input_id: str,
    spec: AdapterSpec,
    result: AdapterResult,
    path: str,
    required: bool,
    content: bytes,
    media_type: str,
    metadata: dict[str, Any] | None = None,
) -> ParsedInput:
    combined_metadata = {
        **(metadata or {}),
        **result.metadata,
        "registry_version": REGISTRY_VERSION,
    }
    return ParsedInput(
        input_id=input_id,
        kind=spec.kind,
        path=path,
        required=required,
        status="restricted" if result.restricted else "accepted",
        digest=digest_bytes(content),
        size_bytes=len(content),
        media_type=media_type,
        parser_version=spec.parser_version,
        observations=result.observations,
        warnings=result.warnings,
        metadata=combined_metadata,
    )


def _standalone_artifact(
    content: bytes,
    filename: str,
    settings: Settings,
    *,
    source_format: str = "auto",
    media_type: str | None = None,
) -> ParsedArtifact:
    spec, result = _parse_input_bytes(
        content,
        filename,
        settings,
        kind=source_format,
        media_type=media_type,
    )
    item = _parsed_input(
        input_id="input-1",
        spec=spec,
        result=result,
        path=filename,
        required=True,
        content=content,
        media_type=media_type or _guess_media_type(filename, spec.kind),
    )
    return ParsedArtifact(
        source_format=spec.kind,
        parser_version=spec.parser_version,
        report_name=filename,
        observations=item.observations,
        warnings=item.warnings,
        manifest_version="standalone",
        expected_inputs=1,
        received_inputs=1,
        completeness="complete" if item.status == "accepted" else "partial",
        inputs=(item,),
    )


def _guess_media_type(path: str, kind: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    return {
        ".xml": "application/xml",
        ".json": "application/json",
        ".jsonl": "application/x-ndjson",
        ".txt": "text/plain",
        ".log": "text/plain",
        ".har": "application/json",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".zip": "application/zip",
    }.get(suffix, "application/octet-stream" if kind != "console-text" else "text/plain")


def _manifest_input_id(value: object, index: int) -> str:
    input_id = str(value or f"input-{index + 1}").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}", input_id):
        raise IngestionError("malformed_report", f"Invalid manifest input id: {input_id!r}")
    return input_id


def _parse_manifest_v2(
    archive: zipfile.ZipFile,
    normalized_names: dict[str, zipfile.ZipInfo],
    manifest: dict[str, Any],
    settings: Settings,
) -> ParsedArtifact:
    entries = manifest.get("inputs")
    if not isinstance(entries, list) or not entries:
        raise IngestionError("malformed_report", "Manifest v2 requires a non-empty inputs array")
    if len(entries) > settings.max_archive_entries:
        raise IngestionError("limit_exceeded", "Manifest declares too many inputs")
    parsed_inputs: list[ParsedInput] = []
    observations: list[ParsedObservation] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    required_count = 0
    required_received = 0
    required_complete = True
    primary_name: str | None = None

    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            raise IngestionError("malformed_report", f"Manifest input {index} must be an object")
        input_id = _manifest_input_id(raw_entry.get("id"), index)
        if input_id in seen_ids:
            raise IngestionError("malformed_report", f"Duplicate manifest input id: {input_id}")
        seen_ids.add(input_id)
        required = raw_entry.get("required", True)
        if not isinstance(required, bool):
            raise IngestionError("malformed_report", f"Manifest input {input_id} required must be boolean")
        if required:
            required_count += 1
        path_value = raw_entry.get("path")
        if not isinstance(path_value, str):
            raise IngestionError("malformed_report", f"Manifest input {input_id} requires a path")
        path = safe_archive_name(path_value)
        path_key = path.casefold()
        if path_key in seen_paths:
            raise IngestionError("malformed_report", f"Duplicate manifest input path: {path}")
        seen_paths.add(path_key)
        kind = str(raw_entry.get("kind") or "auto")[:80]
        media_type = str(raw_entry.get("media_type") or _guess_media_type(path, kind))[:160]
        entry_metadata = raw_entry.get("metadata")
        if entry_metadata is not None and not isinstance(entry_metadata, dict):
            raise IngestionError("malformed_report", f"Manifest input {input_id} metadata must be an object")
        safe_metadata = _safe_json_value(entry_metadata or {})
        info = normalized_names.get(path.casefold())
        if info is None or info.is_dir():
            if required:
                required_complete = False
            warning = f"missing_input:{input_id}"
            warnings.append(warning)
            parsed_inputs.append(
                ParsedInput(
                    input_id=input_id,
                    kind=kind,
                    path=path,
                    required=required,
                    status="missing",
                    digest=None,
                    size_bytes=None,
                    media_type=media_type,
                    parser_version=None,
                    warnings=("missing_attachment",),
                    metadata=safe_metadata,
                )
            )
            continue
        if required:
            required_received += 1
        if info.file_size > settings.max_file_bytes:
            if required:
                required_complete = False
            parsed_inputs.append(
                ParsedInput(
                    input_id=input_id,
                    kind=kind,
                    path=path,
                    required=required,
                    status="rejected",
                    digest=None,
                    size_bytes=info.file_size,
                    media_type=media_type,
                    parser_version=None,
                    warnings=("limit_exceeded",),
                    metadata=safe_metadata,
                )
            )
            warnings.append(f"rejected_input:{input_id}:limit_exceeded")
            continue
        content = archive.read(info)
        expected_digest = raw_entry.get("sha256")
        actual_digest = digest_bytes(content)
        if expected_digest is not None and (
            not isinstance(expected_digest, str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_digest)
            or expected_digest.lower() != actual_digest
        ):
            if required:
                required_complete = False
            parsed_inputs.append(
                ParsedInput(
                    input_id=input_id,
                    kind=kind,
                    path=path,
                    required=required,
                    status="rejected",
                    digest=actual_digest,
                    size_bytes=len(content),
                    media_type=media_type,
                    parser_version=None,
                    warnings=("digest_mismatch",),
                    metadata=safe_metadata,
                )
            )
            warnings.append(f"rejected_input:{input_id}:digest_mismatch")
            continue
        try:
            spec, result = _parse_input_bytes(
                content,
                path,
                settings,
                kind=kind,
                media_type=media_type,
            )
        except IngestionError as exc:
            if required:
                required_complete = False
            status = "unsupported" if exc.code in {"unsupported_format", "unsupported_schema"} else "rejected"
            parsed_inputs.append(
                ParsedInput(
                    input_id=input_id,
                    kind=kind,
                    path=path,
                    required=required,
                    status=status,
                    digest=actual_digest,
                    size_bytes=len(content),
                    media_type=media_type,
                    parser_version=None,
                    warnings=(exc.code,),
                    metadata={**safe_metadata, "safe_error": str(exc)[:2000]},
                )
            )
            warnings.append(f"{status}_input:{input_id}:{exc.code}")
            continue
        item = _parsed_input(
            input_id=input_id,
            spec=spec,
            result=result,
            path=path,
            required=required,
            content=content,
            media_type=media_type,
            metadata={
                **safe_metadata,
                "role": str(raw_entry.get("role") or "supporting")[:80],
                "correlates_to": [str(value)[:120] for value in raw_entry.get("correlates_to", [])[:100]]
                if isinstance(raw_entry.get("correlates_to"), list)
                else [],
            },
        )
        parsed_inputs.append(item)
        if required and item.status != "accepted":
            required_complete = False
        observations.extend(item.observations)
        warnings.extend(f"{input_id}:{warning}" for warning in item.warnings)
        if primary_name is None and (
            raw_entry.get("role") == "primary" or item.observations
        ):
            primary_name = path

    usable = [item for item in parsed_inputs if item.status in {"accepted", "restricted"}]
    completeness = "complete" if required_complete and usable else "partial"
    fallback_name = next((item.path for item in parsed_inputs if item.path), "manifest.json")
    return ParsedArtifact(
        source_format="failurelens-bundle-v2",
        parser_version=f"zip-v2/{REGISTRY_VERSION}",
        report_name=primary_name or (usable[0].path if usable else fallback_name) or "manifest.json",
        observations=tuple(observations),
        warnings=tuple(warnings),
        manifest_version=MANIFEST_V2,
        expected_inputs=required_count,
        received_inputs=required_received,
        completeness=completeness,
        inputs=tuple(parsed_inputs),
    )


def parse_zip_bundle(content: bytes, filename: str, settings: Settings) -> ParsedArtifact:
    if len(content) > settings.max_bundle_bytes:
        raise IngestionError("limit_exceeded", "ZIP bundle exceeds configured upload limit")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise IngestionError("malformed_report", "ZIP bundle is malformed") from exc
    with archive:
        infos = archive.infolist()
        # Manifest v2 may intentionally include a Playwright trace ZIP. Only declared trace paths
        # are exempted from the generic nested-archive rejection.
        manifest_raw: dict[str, Any] | None = None
        manifest_member = next(
            (info for info in infos if info.filename.replace("\\", "/").casefold() == "manifest.json"),
            None,
        )
        if manifest_member is not None:
            if manifest_member.file_size > min(settings.max_file_bytes, MAX_MANIFEST_BYTES):
                raise IngestionError("limit_exceeded", "Bundle manifest.json exceeds its size limit")
            try:
                decoded = json.loads(archive.read(manifest_member))
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError, RecursionError) as exc:
                raise IngestionError("malformed_report", "Bundle manifest.json is invalid") from exc
            if not isinstance(decoded, dict):
                raise IngestionError("malformed_report", "Bundle manifest.json must be an object")
            manifest_raw = decoded
        allowed_nested: set[str] = set()
        if manifest_raw and manifest_raw.get("schema_version") == MANIFEST_V2:
            entries = manifest_raw.get("inputs")
            if isinstance(entries, list):
                for entry in entries:
                    if (
                        isinstance(entry, dict)
                        and str(entry.get("kind") or "").lower() in {"playwright-trace", "trace"}
                        and isinstance(entry.get("path"), str)
                    ):
                        allowed_nested.add(safe_archive_name(entry["path"]))
        normalized_names = _validate_zip_infos(infos, settings, allow_nested_paths=allowed_nested)

        if manifest_raw is not None:
            schema_version = manifest_raw.get("schema_version")
            if schema_version == MANIFEST_V2:
                return _parse_manifest_v2(archive, normalized_names, manifest_raw, settings)
            if schema_version != "1.0":
                raise IngestionError(
                    "unsupported_schema",
                    f"Bundle manifest schema {schema_version!r} is unsupported",
                )
            candidate = manifest_raw.get("report")
            if not isinstance(candidate, str):
                raise IngestionError("malformed_report", "Bundle manifest v1 requires a report path")
            report_name = safe_archive_name(candidate)
            info = normalized_names.get(report_name.casefold())
            if info is None or info.is_dir():
                raise IngestionError("missing_attachment", "Bundle manifest report path is absent")
            if info.file_size > settings.max_file_bytes:
                raise IngestionError("limit_exceeded", "Report inside bundle exceeds configured file limit")
            report_content = archive.read(info)
            parsed = _standalone_artifact(report_content, report_name, settings)
            item = ParsedInput(
                **{
                    **parsed.inputs[0].__dict__,
                    "input_id": "report",
                    "path": report_name,
                }
            )
            return ParsedArtifact(
                source_format=f"zip+{parsed.source_format}",
                parser_version=f"zip-v1/{parsed.parser_version}",
                report_name=report_name,
                observations=parsed.observations,
                warnings=parsed.warnings,
                manifest_version="1.0",
                expected_inputs=1,
                received_inputs=1,
                completeness=parsed.completeness,
                inputs=(item,),
            )

        # A standalone Playwright trace ZIP is not a FailureLens bundle.
        lowered_names = set(normalized_names)
        if any(name.endswith("trace.trace") or name == "trace.trace" for name in lowered_names):
            return _standalone_artifact(
                content,
                filename,
                settings,
                source_format="playwright-trace",
                media_type="application/zip",
            )

        candidates = [
            info.filename
            for info in infos
            if not info.is_dir()
            and PurePosixPath(info.filename).suffix.lower()
            in {".xml", ".json", ".jsonl", ".har", ".log", ".txt", ".png", ".jpg", ".jpeg"}
            and info.filename.casefold() != "manifest.json"
        ]
        if len(candidates) != 1:
            raise IngestionError(
                "ambiguous_bundle",
                "Bundle without manifest.json must contain exactly one supported input",
            )
        report_name = safe_archive_name(candidates[0])
        info = normalized_names[report_name.casefold()]
        if info.file_size > settings.max_file_bytes:
            raise IngestionError("limit_exceeded", "Input inside bundle exceeds configured file limit")
        parsed = _standalone_artifact(archive.read(info), report_name, settings)
        item = ParsedInput(
            **{
                **parsed.inputs[0].__dict__,
                "input_id": "input-1",
                "path": report_name,
                "warnings": (*parsed.inputs[0].warnings, "bundle_manifest_missing"),
            }
        )
        return ParsedArtifact(
            source_format=f"zip+{parsed.source_format}",
            parser_version=f"zip-v1/{parsed.parser_version}",
            report_name=report_name,
            observations=parsed.observations,
            warnings=("bundle_manifest_missing", *parsed.warnings),
            manifest_version="implicit-v1",
            expected_inputs=1,
            received_inputs=1,
            completeness=parsed.completeness,
            inputs=(item,),
        )


def parse_artifact(
    content: bytes,
    filename: str,
    settings: Settings,
    *,
    source_format: str = "auto",
    media_type: str | None = None,
) -> ParsedArtifact:
    if not content:
        raise IngestionError("empty_upload", "Artifact is empty")
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix == ".zip" or content.startswith(b"PK\x03\x04"):
        if source_format.strip().lower() in {"playwright-trace", "trace"}:
            if len(content) > settings.max_file_bytes:
                raise IngestionError("limit_exceeded", "Trace exceeds configured file limit")
            return _standalone_artifact(
                content,
                filename,
                settings,
                source_format="playwright-trace",
                media_type=media_type or "application/zip",
            )
        return parse_zip_bundle(content, filename, settings)
    if len(content) > settings.max_file_bytes:
        raise IngestionError("limit_exceeded", "Artifact exceeds configured file limit")
    return _standalone_artifact(
        content,
        filename,
        settings,
        source_format=source_format,
        media_type=media_type,
    )
