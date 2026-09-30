from __future__ import annotations

import hashlib
import json
import re
from typing import Any

NORMALIZATION_VERSION = "fingerprint-v1"

_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_TIMESTAMP = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ][0-9:.+-]+Z?\b", re.IGNORECASE)
_PORT = re.compile(r"(?<=:)(?:[1-9]\d{3,4})\b")
_LINE = re.compile(r"(?P<path>[\w./\\-]+):\d+(?::\d+)?")
_HEX = re.compile(r"\b[0-9a-f]{16,64}\b", re.IGNORECASE)


def normalize_message(message: str) -> str:
    value = message.strip().lower()
    value = _UUID.sub("<uuid>", value)
    value = _TIMESTAMP.sub("<timestamp>", value)
    value = _PORT.sub("<port>", value)
    value = _LINE.sub(lambda m: f"{m.group('path')}:<line>", value)
    value = _HEX.sub("<hex>", value)
    value = re.sub(r"\s+", " ", value)
    return value[:8000]


def make_fingerprint(
    message: str, exception_type: str | None, details: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any]]:
    details = details or {}
    features = {
        "version": NORMALIZATION_VERSION,
        "exception_type": (exception_type or "unknown").lower(),
        "message": normalize_message(message),
        "http_status": details.get("http_status"),
        "route": details.get("route"),
        "selector": details.get("selector"),
        "assertion": details.get("assertion"),
    }
    canonical = json.dumps(
        features, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), features
