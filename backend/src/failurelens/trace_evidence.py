"""Version-pinned, non-executable trace evidence. Original resources stay private."""
from __future__ import annotations

import hashlib
import io
import json
import math
import time
import zipfile
from collections import Counter
from typing import Any

from .config import Settings
from .redaction import redact_text

SUPPORTED_PRODUCERS = {"1.63.0": 9}
TRACE_INDEX_VERSION = "playwright-safe-index-v2"
MAX_INDEX_EVENTS = 256
MAX_STREAM_EVENTS = 50_000
MAX_EVENT_BYTES = 1_000_000


def _text(value: Any, limit: int = 1000) -> str:
    from .ingestion import _strip_terminal_controls
    if not isinstance(value, str):
        return ""
    clean, _ = _strip_terminal_controls(value[:limit])
    return redact_text(clean).text


def _number(value: Any) -> int | float | None:
    if type(value) in {int, float} and math.isfinite(value) and value >= 0:
        return value
    return None


def _safe_event(event: dict[str, Any]) -> dict[str, Any] | None:
    from .ingestion import _sanitize_url
    kind = event.get("type")
    if kind not in {"before", "after", "input", "log", "console", "error", "event", "resource-snapshot"}:
        return None
    result: dict[str, Any] = {"type": kind}
    for key in ("callId", "parentId", "class", "method", "apiName", "messageType", "pageId"):
        if isinstance(event.get(key), str):
            result[key] = _text(event[key], 240)
    for key in ("startTime", "endTime", "time"):
        value = _number(event.get(key))
        if value is not None:
            result[key] = value
    # Never copy action params, arbitrary serialized objects, DOM, headers, bodies,
    # resource bytes, evaluation scripts or storage state into an approved index.
    if kind in {"log", "console"}:
        result["message"] = _text(event.get("text") or event.get("message"), 2000)
    error = event.get("error") or (event.get("message") if kind == "error" else None)
    if isinstance(error, dict):
        error = error.get("message") or error.get("name")
    if isinstance(error, str):
        result["error"] = _text(error, 2000)
    if kind == "event":
        # Only a protocol event name; event params are deliberately omitted.
        result["event"] = _text(event.get("method"), 240)
    if kind == "resource-snapshot":
        snapshot = event.get("snapshot")
        if not isinstance(snapshot, dict):
            return None
        request = snapshot.get("request")
        response = snapshot.get("response")
        request = request if isinstance(request, dict) else {}
        response = response if isinstance(response, dict) else {}
        result["method"] = _text(request.get("method"), 16)
        result["url"] = _text(_sanitize_url(str(request.get("url") or "")), 2048)
        status = response.get("status")
        result["status"] = status if type(status) is int and 0 <= status <= 599 else None
        result["duration_ms"] = _number(snapshot.get("time"))
        if isinstance(snapshot.get("_failureText"), str):
            result["error"] = _text(snapshot["_failureText"])
    return result


def build_trace_index(content: bytes, settings: Settings) -> tuple[dict[str, Any], tuple[str, ...]]:
    from .ingestion import IngestionError, _validate_zip_infos
    start = time.monotonic()
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise IngestionError("malformed_report", "Invalid Playwright trace archive") from exc
    counts: Counter[str] = Counter()
    events: list[dict[str, Any]] = []
    streams: list[dict[str, Any]] = []
    versions: set[int] = set()
    producers: set[str] = set()
    omitted = 0
    errors = 0
    total = 0
    source_digest = hashlib.sha256(content).hexdigest()
    with archive:
        names = _validate_zip_infos(archive.infolist(), settings)
        trace_names = sorted(name for name in names if name.endswith(".trace"))
        network_names = sorted(name for name in names if name.endswith(".network"))
        if not trace_names:
            raise IngestionError("unsupported_format", "Trace has no .trace event stream")
        if len(trace_names) + len(network_names) > 20:
            raise IngestionError("limit_exceeded", "Trace has too many event streams")
        for name in [*trace_names, *network_names]:
            info = names[name]
            if info.file_size > settings.max_file_bytes:
                raise IngestionError("limit_exceeded", "Trace event stream exceeds file limit")
            try:
                with archive.open(info) as handle:
                    raw = handle.read(settings.max_file_bytes + 1)
            except (zipfile.BadZipFile, EOFError, RuntimeError, OSError) as exc:
                raise IngestionError("malformed_report", "Trace entry integrity check failed") from exc
            if len(raw) > settings.max_file_bytes:
                raise IngestionError("limit_exceeded", "Trace expanded bytes exceed file limit")
            entry_digest = hashlib.sha256(raw).hexdigest()
            stream_events = 0
            header_seen = name in network_names
            for line_number, line in enumerate(io.BytesIO(raw), 1):
                if time.monotonic() - start > 10:
                    raise IngestionError("limit_exceeded", "Trace processing time limit exceeded")
                if not line.strip():
                    continue
                if len(line) > MAX_EVENT_BYTES:
                    raise IngestionError("limit_exceeded", "Trace event exceeds byte limit")
                if total >= MAX_STREAM_EVENTS:
                    raise IngestionError("limit_exceeded", "Trace exceeds event limit")
                try:
                    event = json.loads(line)
                except UnicodeDecodeError as exc:
                    raise IngestionError("malformed_encoding", "Trace events must be UTF-8") from exc
                except (ValueError, RecursionError) as exc:
                    raise IngestionError("malformed_report", "Malformed trace event JSON") from exc
                if not isinstance(event, dict) or not isinstance(event.get("type"), str) or len(event["type"]) > 80:
                    raise IngestionError("malformed_report", "Trace event requires a type")
                if not header_seen:
                    if event["type"] != "context-options":
                        raise IngestionError("unsupported_trace_version", "Trace version declaration is missing")
                    version, producer = event.get("version"), event.get("playwrightVersion")
                    if type(version) is not int or version not in SUPPORTED_PRODUCERS.values():
                        raise IngestionError("unsupported_trace_version", "Trace schema version is unsupported")
                    if not isinstance(producer, str) or SUPPORTED_PRODUCERS.get(producer) != version:
                        raise IngestionError("unsupported_trace_producer", "Trace producer version is not fixture-supported")
                    versions.add(version)
                    producers.add(producer)
                    header_seen = True
                elif event["type"] == "context-options":
                    if (type(event.get("version")) is not int
                            or not isinstance(event.get("playwrightVersion"), str)
                            or SUPPORTED_PRODUCERS.get(event.get("playwrightVersion", "")) != event.get("version")):
                        raise IngestionError("unsupported_trace_version", "Trace has conflicting version declarations")
                total += 1
                stream_events += 1
                counts[event["type"]] += 1
                safe = _safe_event(event)
                if safe is None:
                    continue
                errors += bool(safe.get("error") or safe.get("messageType") == "error")
                if len(events) >= MAX_INDEX_EVENTS:
                    omitted += 1
                    continue
                locator = {"kind": "trace-event", "entry": _text(info.filename, 1024),
                           "line": line_number, "entry_digest": entry_digest,
                           "source_digest": source_digest, "entry_index": archive.infolist().index(info)}
                events.append({"event": safe, "source_locator": locator,
                               "text": json.dumps(safe, ensure_ascii=False, sort_keys=True)})
            if not header_seen:
                raise IngestionError("unsupported_trace_version", "Trace stream is empty")
            streams.append({"entry": _text(info.filename, 1024), "digest": entry_digest,
                            "events": stream_events, "bytes": len(raw)})
    warnings = ["trace_original_restricted", "trace_dom_and_network_not_sanitized"]
    if omitted:
        warnings.append("trace_index_truncated")
    metadata = {
        "producer": "playwright-trace", "index_version": TRACE_INDEX_VERSION,
        "producer_versions": sorted(producers), "schema_versions": sorted(versions),
        "archive_entries": len(names), "trace_streams": len(trace_names), "streams": streams,
        "event_count": total, "event_type_counts": dict(counts),
        "action_count": sum(counts[k] for k in ("before", "after", "action")),
        "error_event_count": errors,
        "indexed_events": len(events), "omitted_index_events": omitted, "truncated": bool(omitted),
        "resource_count": len([n for n in names if n.startswith("resources/")]),
        "resource_policy": "names-and-bytes-not-published; no DOM, scripts, headers, bodies or pixels",
        "review_state": "restricted", "safe_derivative": TRACE_INDEX_VERSION, "events": events,
    }
    return metadata, tuple(warnings)
