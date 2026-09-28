"""Isolated PNG/JPEG validation and irreversible pixel masking."""
from __future__ import annotations

import json
import subprocess
import sys
from threading import BoundedSemaphore
from typing import Any

from .config import Settings


_CODEC_SLOTS = BoundedSemaphore(2)


class ImageCodecError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def decode_image(content: bytes, settings: Settings, *, masks: list[dict[str, int]] | None = None,
                 encode: bool = False, preview_size: int | None = None) -> tuple[dict[str, Any], bytes]:
    if len(content) > settings.max_file_bytes:
        raise ImageCodecError("limit_exceeded")
    if not content.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8")):
        raise ImageCodecError("unsupported_format")
    options = {"max_bytes": settings.max_file_bytes, "max_pixels": settings.max_image_pixels,
               "masks": masks or [], "encode": encode, "preview_size": preview_size}
    if not _CODEC_SLOTS.acquire(timeout=1):
        raise ImageCodecError("image_capacity_exceeded")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "failurelens.image_worker"],
            input=json.dumps(options).encode() + b"\n" + content,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=12, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ImageCodecError("image_processing_timeout") from exc
    finally:
        _CODEC_SLOTS.release()
    if result.returncode:
        raise ImageCodecError("image_processing_failed")
    try:
        header, output = result.stdout.split(b"\n", 1)
        metadata = json.loads(header)
        if "error" in metadata:
            raise ImageCodecError(metadata["error"])
        if metadata["encoded_bytes"] != len(output) or len(output) > settings.max_file_bytes:
            raise ValueError("invalid codec response")
    except (KeyError, ValueError, TypeError) as exc:
        if isinstance(exc, ImageCodecError):
            raise
        raise ImageCodecError("image_processing_failed") from exc
    return metadata, output
