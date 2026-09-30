from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import re
from typing import Iterable, Iterator

from .redaction_keys import KeyMaterial, RedactionKeyError, valid_key_reference

REDACTION_VERSION = "redaction-v3"
ALGORITHM = "hmac-sha256-128"


@dataclass
class RedactionContext:
    project_id: str
    key_reference: str
    key_source: str
    _project_key: bytes = field(repr=False)
    _issued: set[str] = field(default_factory=set, repr=False)
    preexisting_markers: bool = False
    legacy_unscoped_markers: bool = False

    @classmethod
    def from_key(cls, project_id: str, key: KeyMaterial) -> RedactionContext:
        if (not project_id or not valid_key_reference(key.reference)
                or key.source not in {"local", "operator"} or not 32 <= len(key.material) <= 256):
            raise RedactionKeyError("redaction_context_invalid")
        domain = json.dumps(["failurelens-project-redaction-key-v3", key.reference, project_id],
                            separators=(",", ":")).encode()
        derived = hmac.digest(key.material, domain, "sha256")
        return cls(project_id, key.reference, key.source, derived)

    def provenance(self) -> dict:
        return {"version": REDACTION_VERSION, "algorithm": ALGORITHM,
                "correlation_scope": "project", "project_id": self.project_id,
                "key_ref": self.key_reference, "key_source": self.key_source,
                "preexisting_markers": self.preexisting_markers,
                "legacy_unscoped_markers": self.legacy_unscoped_markers}


_CONTEXT: ContextVar[RedactionContext | None] = ContextVar("project_redaction", default=None)


@contextmanager
def redaction_scope(context: RedactionContext) -> Iterator[RedactionContext]:
    token = _CONTEXT.set(context)
    try:
        yield context
    finally:
        _CONTEXT.reset(token)


def current_redaction_context() -> RedactionContext | None:
    return _CONTEXT.get()


def redaction_provenance(project_id: str | None = None) -> dict:
    context = current_redaction_context()
    if context is None:
        if project_id is not None:
            raise RedactionKeyError("redaction_project_context_missing")
        return {"version": REDACTION_VERSION, "algorithm": "suppression",
                "correlation_scope": "none", "project_id": None, "key_ref": None,
                "key_source": None, "preexisting_markers": False,
                "legacy_unscoped_markers": False}
    if project_id is not None and context.project_id != project_id:
        raise RedactionKeyError("redaction_project_context_mismatch")
    return context.provenance()


def valid_project_provenance(value: object, project_id: str) -> bool:
    public_fields = {"version", "algorithm", "correlation_scope", "project_id", "key_ref", "key_source",
                     "preexisting_markers", "legacy_unscoped_markers", "classes"}
    return (isinstance(value, dict) and set(value) <= public_fields and value.get("version") == REDACTION_VERSION
            and value.get("algorithm") == ALGORITHM and value.get("correlation_scope") == "project"
            and value.get("project_id") == project_id and valid_key_reference(value.get("key_ref"))
            and value.get("key_source") in {"local", "operator"}
            and type(value.get("preexisting_markers")) is bool
            and type(value.get("legacy_unscoped_markers")) is bool)


@dataclass(frozen=True)
class RedactionResult:
    text: str
    classes: tuple[str, ...]
    replacements: int


_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I | re.S)),
    ("authorization", re.compile(r"(?i)\b(authorization\s*:\s*)(?:bearer|basic)\s+[^\s,;]+")),
    ("cookie", re.compile(r"(?im)^((?:set-)?cookie\s*:\s*)[^\r\n]+")),
    ("api_key", re.compile(r"(?i)\b((?:api[_-]?key|access[_-]?token|token|secret|password)\s*[=:]\s*)[\"']?[^\s,;\"']+")),
    ("session", re.compile(r"(?i)\b((?:session(?:[_-]?id)?|sid)\s*[=:]\s*)[\"']?[^\s,;\"']+")),
    ("transaction_id", re.compile(r"(?i)\b((?:transaction[_-]?id|tx[_-]?id)\s*[=:]\s*)[\"']?[^\s,;\"']+")),
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    # Numeric fragments inside identifiers/digests are not phone tokens.
    ("phone", re.compile(r"(?<![\w])(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}(?![\w])")),
)
_MARKER = re.compile(
    r"\[REDACTED:(?P<kind>private_key|authorization|cookie|api_key|email|phone|session|transaction_id|malformed_marker)"
    r"(?::[0-9a-f]{10}|:hmac-v3:[0-9a-f]{32}|:unscoped|:incomplete)?\]"
)
_MARKER_START = re.compile(r"\[REDACTED:", re.I)
_CORRELATION_CLASSES = frozenset({"email", "phone", "session", "transaction_id"})
_ANALYTIC_FIELD = re.compile(r"^(?:(?:expected|actual|asserted|observed|before|after)_)?(?:amount(?:_minor)?|balance(?:_minor)?|status(?:_code)?|response_status|posted_minor)$", re.I)
_NUMERIC = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_ANALYTIC_PREFIX = re.compile(r"(?i)(?<![\w])((?:(?:expected|actual|asserted|observed|before|after)_)?(?:amount(?:_minor)?|balance(?:_minor)?|status(?:_code)?|response_status|posted_minor))\s*[=:]\s*[\"']?[+-]?$" )


def analytic_scalar(name: str, value: object) -> bool:
    return bool(_ANALYTIC_FIELD.fullmatch(name) and isinstance(value, str) and _NUMERIC.fullmatch(value))


def _marker_candidates(text: str) -> Iterator[tuple[int, int]]:
    end = 0
    for match in _MARKER_START.finditer(text):
        if match.start() < end:
            continue
        depth, end = 1, match.end()
        while end < len(text) and text[end] not in "\r\n":
            char = text[end]
            depth += (char == "[") - (char == "]")
            end += 1
            if depth == 0:
                break
        yield match.start(), end


def _known_marker(value: str) -> re.Match[str] | None:
    match = _MARKER.fullmatch(value)
    if match is None:
        return None
    kind = match.group("kind")
    tail = value[len("[REDACTED:") + len(kind):-1]
    if re.fullmatch(r":[0-9a-f]{10}", tail) and kind in {"transaction_id", "malformed_marker"}:
        return None
    if tail == ":incomplete" and kind != "private_key":
        return None
    if (tail == ":unscoped" or tail.startswith(":hmac-v3:")) and kind not in _CORRELATION_CLASSES:
        return None
    return match


def _record_marker(marker: str) -> str:
    context = current_redaction_context()
    if context is not None and marker not in context._issued:
        context.preexisting_markers = True
        if ":hmac-v3:" not in marker:
            context.legacy_unscoped_markers = True
    return marker


def _replacement(kind: str, value: str) -> str:
    context = current_redaction_context()
    if kind not in _CORRELATION_CLASSES:
        token = f"[REDACTED:{kind}]"
    elif context is None:
        # No project/key means no correlation promise and no guessable digest.
        token = f"[REDACTED:{kind}:unscoped]"
    else:
        domain = json.dumps(["failurelens-pseudonym-v3", kind, value],
                            ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        digest = hmac.new(context._project_key, domain, hashlib.sha256).hexdigest()[:32]
        token = f"[REDACTED:{kind}:hmac-v3:{digest}]"
    if context is not None and len(context._issued) < 20_000:
        context._issued.add(token)
    return token


_SENSITIVE_FIELD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("authorization", re.compile(r"^(?:authorization|authorization_header|auth_header)$", re.I)),
    ("cookie", re.compile(r"^(?:(?:set_)?cookie|cookies)$", re.I)),
    ("api_key", re.compile(r"^(?:.*_)?(?:api_key|apikey|access_token|refresh_token|auth_token|token|secret|client_secret|password|passwd)$", re.I)),
    ("email", re.compile(r"^(?:.*_)?(?:email|email_address|e_mail)$", re.I)),
    ("phone", re.compile(r"^(?:.*_)?(?:phone|phone_number|mobile|telephone)$", re.I)),
    ("session", re.compile(r"^(?:.*_)?(?:session|session_id|sessionid|sid)$", re.I)),
    ("transaction_id", re.compile(r"^(?:transaction_id|transactionid|tx_id|txid)$", re.I)),
)


def sensitive_field_class(name: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")
    for kind, pattern in _SENSITIVE_FIELD_PATTERNS:
        if pattern.fullmatch(normalized):
            return kind
    return None


def redact_sensitive_field(name: str, value: object) -> RedactionResult | None:
    kind = sensitive_field_class(name)
    if kind is None or value is None:
        return None
    raw = str(value)
    if _known_marker(raw):
        return RedactionResult(_record_marker(raw), (kind,), 0)
    # Hash the complete bounded source value, never a shared truncated prefix.
    return RedactionResult(_replacement(kind, raw), (kind,), 1)


def redact_text(text: str) -> RedactionResult:
    classes: list[str] = []
    replacements = 0
    safe = text.replace("\x00", "")
    safe = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "[CONTROL_SEQUENCE_REMOVED]", safe)

    def redact_segment(segment: str) -> str:
        nonlocal replacements
        for kind, pattern in _PATTERNS:
            def repl(match: re.Match[str]) -> str:
                nonlocal replacements
                # Named analytical numbers are evidence, not phone numbers.
                if kind == "phone" and _ANALYTIC_PREFIX.search(segment[:match.start()]):
                    return match.group(0)
                replacements += 1
                classes.append(kind)
                if match.lastindex:
                    prefix = match.group(1)
                    secret = match.group(0)[len(prefix):].lstrip("\"'")
                    return prefix + _replacement(kind, secret)
                return _replacement(kind, match.group(0))
            segment = pattern.sub(repl, segment)
        return segment

    # Preserve old markers exactly. A project key cannot upgrade a prior digest
    # without its original value. Already-generated v3 tokens are idempotent too.
    pieces: list[str] = []
    position = 0
    for start, end in _marker_candidates(safe):
        pieces.append(redact_segment(safe[position:start]))
        marker = safe[start:end]
        known = _known_marker(marker)
        if known:
            pieces.append(_record_marker(marker))
            classes.append(known.group("kind"))
        else:
            # A wrapper is untrusted input, not a license to publish its tail.
            pieces.append(_replacement("malformed_marker", marker))
            classes.append("malformed_marker")
            replacements += 1
        position = end
    pieces.append(redact_segment(safe[position:]))
    return RedactionResult("".join(pieces), tuple(sorted(set(classes))), replacements)


def contains_sensitive_canary(text: str, canaries: Iterable[str]) -> bool:
    lowered = text.casefold()
    return any(canary.casefold() in lowered for canary in canaries)
