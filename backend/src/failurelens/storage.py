from __future__ import annotations

from .telemetry import instrument

import hashlib
import os
import re
import uuid
from collections.abc import AsyncIterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class StorageError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class StoredUpload:
    relative_path: str
    digest: str
    size_bytes: int
    original_name: str
    media_type: str


def safe_filename(name: str) -> str:
    value = name.strip().replace("\\", "/")
    if not value or len(value) > 1024 or "\x00" in value:
        raise StorageError("unsafe_filename", "Filename is empty or invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or len(path.parts) != 1 or path.name in {"", ".", ".."}:
        raise StorageError("unsafe_filename", "Filename must be a single relative path component")
    if re.match(r"^[A-Za-z]:", value) or any(ord(char) < 32 for char in value):
        raise StorageError("unsafe_filename", "Filename contains a drive prefix or control character")
    return path.name


def _resolve_under(root: Path, relative_path: str) -> Path:
    if ".redaction" in PurePosixPath(relative_path).parts:
        raise StorageError("reserved_storage_path", "Private operational state is not evidence storage")
    root_resolved = root.resolve()
    candidate = (root_resolved / relative_path).resolve()
    try:
        relative = candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise StorageError("unsafe_storage_path", "Stored artifact path escapes the configured root") from exc
    if ".redaction" in relative.parts:
        raise StorageError("reserved_storage_path", "Private operational state is not evidence storage")
    return candidate


def _final_relative_path(project_id: str, digest: str, filename: str) -> str:
    return PurePosixPath("sources", project_id, digest[:2], digest, filename).as_posix()


def _derivative_relative_path(project_id: str, digest: str, filename: str) -> str:
    return PurePosixPath("derivatives", project_id, digest[:2], digest, filename).as_posix()


def _finalize(
    *,
    root: Path,
    temporary: Path,
    project_id: str,
    filename: str,
    digest: str,
    size_bytes: int,
    media_type: str,
    namespace: str = "sources",
) -> StoredUpload:
    if namespace == "sources":
        relative = _final_relative_path(project_id, digest, filename)
    elif namespace == "derivatives":
        relative = _derivative_relative_path(project_id, digest, filename)
    else:
        raise StorageError("unsafe_storage_namespace", "Unsupported storage namespace")
    destination = _resolve_under(root, relative)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.exists():
        existing_size = destination.stat().st_size
        if existing_size != size_bytes:
            temporary.unlink(missing_ok=True)
            raise StorageError("storage_collision", "Existing digest path has an unexpected size")
        existing_digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        if existing_digest != digest:
            temporary.unlink(missing_ok=True)
            raise StorageError("storage_collision", "Existing digest path has unexpected content")
        temporary.unlink(missing_ok=True)
    else:
        os.replace(temporary, destination)
        destination.chmod(0o600)
    return StoredUpload(
        relative_path=relative,
        digest=digest,
        size_bytes=size_bytes,
        original_name=filename,
        media_type=media_type or "application/octet-stream",
    )


async def store_stream(
    chunks: AsyncIterable[bytes],
    *,
    root: Path,
    project_id: str,
    filename: str,
    media_type: str,
    max_bytes: int,
) -> StoredUpload:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    incoming = root / "incoming"
    incoming.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = safe_filename(filename)
    temporary = incoming / f"{uuid.uuid4()}.part"
    digest = hashlib.sha256()
    size = 0
    try:
        with temporary.open("xb") as handle:
            os.chmod(temporary, 0o600)
            async for chunk in chunks:
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_bytes:
                    raise StorageError("limit_exceeded", f"Upload exceeds the {max_bytes}-byte file limit")
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if size == 0:
            raise StorageError("empty_upload", "Uploaded artifact is empty")
        return _finalize(
            root=root,
            temporary=temporary,
            project_id=project_id,
            filename=name,
            digest=digest.hexdigest(),
            size_bytes=size,
            media_type=media_type,
            namespace="sources",
        )
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


@instrument("persistence")
def store_bytes(
    content: bytes,
    *,
    root: Path,
    project_id: str,
    filename: str,
    media_type: str = "application/octet-stream",
    max_bytes: int,
) -> StoredUpload:
    if not content:
        raise StorageError("empty_upload", "Uploaded artifact is empty")
    if len(content) > max_bytes:
        raise StorageError("limit_exceeded", f"Upload exceeds the {max_bytes}-byte file limit")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    incoming = root / "incoming"
    incoming.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = safe_filename(filename)
    temporary = incoming / f"{uuid.uuid4()}.part"
    try:
        with temporary.open("xb") as handle:
            os.chmod(temporary, 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return _finalize(
            root=root,
            temporary=temporary,
            project_id=project_id,
            filename=name,
            digest=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            media_type=media_type,
            namespace="sources",
        )
    except Exception:
        temporary.unlink(missing_ok=True)
        raise



@instrument("persistence")
def store_derivative_bytes(
    content: bytes,
    *,
    root: Path,
    project_id: str,
    filename: str,
    media_type: str,
    max_bytes: int,
) -> StoredUpload:
    """Store an immutable, content-addressed safe derivative.

    Derivatives live outside the restricted source namespace so authorization and
    retention policies can distinguish reviewed/sanitized material from originals.
    The bytes are still private by default; publication is controlled by database
    metadata rather than the filesystem path.
    """
    if not content:
        raise StorageError("empty_derivative", "Safe derivative is empty")
    if len(content) > max_bytes:
        raise StorageError("limit_exceeded", f"Derivative exceeds the {max_bytes}-byte file limit")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    incoming = root / "incoming"
    incoming.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = safe_filename(filename)
    temporary = incoming / f"{uuid.uuid4()}.part"
    try:
        with temporary.open("xb") as handle:
            os.chmod(temporary, 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return _finalize(
            root=root,
            temporary=temporary,
            project_id=project_id,
            filename=name,
            digest=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            media_type=media_type,
            namespace="derivatives",
        )
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

def read_stored_bytes(
    *,
    root: Path,
    relative_path: str,
    expected_digest: str,
    expected_size: int,
    max_bytes: int,
) -> bytes:
    path = _resolve_under(root, relative_path)
    try:
        size = path.stat().st_size
    except FileNotFoundError as exc:
        raise StorageError("storage_missing", "Stored source artifact no longer exists") from exc
    if size != expected_size:
        raise StorageError("storage_size_mismatch", "Stored source artifact size changed")
    if size > max_bytes:
        raise StorageError("limit_exceeded", "Stored source artifact exceeds the configured limit")
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_digest:
        raise StorageError("digest_mismatch", "Stored source artifact digest changed")
    return content
