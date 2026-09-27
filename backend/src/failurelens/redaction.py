from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable

REDACTION_VERSION = "redaction-v1"


@dataclass(frozen=True)
class RedactionResult:
    text: str
    classes: tuple[str, ...]
    replacements: int


_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I | re.S)),
    ("authorization", re.compile(r"(?im)^(authorization\s*:\s*)(?:bearer|basic)\s+[^\r\n]+")),
    ("cookie", re.compile(r"(?im)^((?:set-)?cookie\s*:\s*)[^\r\n]+")),
    ("api_key", re.compile(r"(?i)\b((?:api[_-]?key|access[_-]?token|token|secret|password)\s*[=:]\s*)[\"']?[^\s,;\"']{6,}")),
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("phone", re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}(?!\d)")),
    ("session", re.compile(r"(?i)\b((?:session(?:id)?|sid)\s*[=:]\s*)[\"']?[^\s,;\"']{6,}")),
)


def _replacement(kind: str, value: str) -> str:
    digest = sha256(value.encode("utf-8", errors="replace")).hexdigest()[:10]
    return f"[REDACTED:{kind}:{digest}]"


def redact_text(text: str) -> RedactionResult:
    classes: list[str] = []
    replacements = 0
    safe = text.replace("\x00", "")
    safe = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "[CONTROL_SEQUENCE_REMOVED]", safe)

    for kind, pattern in _PATTERNS:
        def repl(match: re.Match[str]) -> str:
            nonlocal replacements
            replacements += 1
            classes.append(kind)
            if match.lastindex:
                prefix = match.group(1)
                secret = match.group(0)[len(prefix):]
                return prefix + _replacement(kind, secret)
            return _replacement(kind, match.group(0))

        safe = pattern.sub(repl, safe)
    return RedactionResult(safe, tuple(sorted(set(classes))), replacements)


def contains_sensitive_canary(text: str, canaries: Iterable[str]) -> bool:
    lowered = text.casefold()
    return any(canary.casefold() in lowered for canary in canaries)
