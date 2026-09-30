from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
import uuid
from collections.abc import AsyncIterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Literal

from .telemetry import instrument

# Evidence storage requires these filesystem semantics. The configured root may
# be an operator-owned alias; components below the opened root must not be links.
_DESCRIPTOR_STORAGE_SUPPORTED = (
    all(hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK"))
    and {os.open, os.mkdir, os.unlink, os.link, os.stat}.issubset(os.supports_dir_fd)
    and os.link in os.supports_follow_symlinks
)


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
        raise StorageError(
            "unsafe_filename", "Filename must be a single relative path component"
        )
    if re.match(r"^[A-Za-z]:", value) or any(ord(char) < 32 for char in value):
        raise StorageError(
            "unsafe_filename", "Filename contains a drive prefix or control character"
        )
    return path.name


def _resolve_under(root: Path, relative_path: str) -> Path:
    path = PurePosixPath(relative_path)
    if ".redaction" in path.parts:
        raise StorageError(
            "reserved_storage_path", "Private operational state is not evidence storage"
        )
    if (
        not path.parts
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in relative_path
        or "\x00" in relative_path
    ):
        raise StorageError("unsafe_storage_path", "Stored artifact path is invalid")
    try:
        root_resolved = root.resolve()
        candidate = (root_resolved / path).resolve()
        relative = candidate.relative_to(root_resolved)
    except (ValueError, OSError, RuntimeError) as exc:
        raise StorageError(
            "unsafe_storage_path", "Stored artifact path escapes the configured root"
        ) from exc
    if ".redaction" in relative.parts:
        raise StorageError(
            "reserved_storage_path", "Private operational state is not evidence storage"
        )
    if any(
        root_resolved.joinpath(*path.parts[:i]).is_symlink()
        for i in range(1, len(path.parts) + 1)
    ):
        raise StorageError(
            "unsafe_storage_path", "Stored artifact path contains a symlink"
        )
    return root_resolved / path


@contextmanager
def _root_directory(root: Path, *, create: bool = False) -> Iterator[int]:
    if not _DESCRIPTOR_STORAGE_SUPPORTED:
        raise StorageError(
            "storage_unsupported",
            "Evidence storage requires no-follow directory descriptors and hard links",
        )
    # A configured root alias is trusted, unlike artifact-controlled components.
    root = root.resolve()
    if create:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _directory_at(
    root: int, parts: tuple[str, ...], *, create: bool = False
) -> Iterator[int]:
    descriptor = os.dup(root)
    try:
        for part in parts:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            try:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
            except OSError as exc:
                if isinstance(exc, FileNotFoundError):
                    raise
                raise StorageError(
                    "unsafe_storage_path", "Artifact directory is unavailable or unsafe"
                ) from exc
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _temporary_file(root: Path) -> Iterator[tuple[int, int, str, BinaryIO]]:
    with (
        _root_directory(root, create=True) as root_fd,
        _directory_at(root_fd, ("incoming",), create=True) as incoming_fd,
    ):
        name = f"{uuid.uuid4()}.part"
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=incoming_fd,
        )
        handle = None
        try:
            handle = _file_handle(descriptor, "wb")
            yield root_fd, incoming_fd, name, handle
            handle.close()
        except BaseException:
            # Cancellation, write/flush errors and the original traceback must
            # survive OS failures in close or cleanup. Never remove a final file.
            if handle is not None:
                try:
                    handle.close()
                except OSError:
                    pass
            try:
                os.unlink(name, dir_fd=incoming_fd)
            except OSError:
                pass
            raise
        else:
            os.unlink(name, dir_fd=incoming_fd)


def _file_handle(
    descriptor: int, mode: Literal["rb", "wb"], *, buffering: int = -1
) -> BinaryIO:
    try:
        return os.fdopen(descriptor, mode, buffering=buffering)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _read_at(
    directory: int,
    filename: str,
    *,
    expected_digest: str,
    expected_size: int,
    max_bytes: int,
    make_private: bool = False,
) -> bytes:
    try:
        descriptor = os.open(
            filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
    except FileNotFoundError as exc:
        raise StorageError(
            "storage_missing", "Stored artifact no longer exists"
        ) from exc
    except OSError as exc:
        raise StorageError(
            "unsafe_storage_path", "Stored artifact is unavailable or unsafe"
        ) from exc
    with _file_handle(descriptor, "rb", buffering=0) as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise StorageError(
                "unsafe_storage_path", "Stored artifact is not a regular file"
            )
        if before.st_size != expected_size or expected_size < 0:
            raise StorageError("storage_size_mismatch", "Stored artifact size changed")
        if before.st_size > max_bytes or max_bytes < 0:
            raise StorageError(
                "limit_exceeded", "Stored artifact exceeds the configured limit"
            )
        content = handle.read(min(expected_size, max_bytes) + 1)
        after = os.fstat(handle.fileno())
        if len(content) > max_bytes:
            raise StorageError(
                "limit_exceeded", "Stored artifact exceeds the configured limit"
            )
        if len(content) != expected_size or after.st_size != expected_size:
            raise StorageError("storage_size_mismatch", "Stored artifact size changed")
        if hashlib.sha256(content).hexdigest() != expected_digest:
            raise StorageError("digest_mismatch", "Stored artifact digest changed")
        if make_private:
            os.fchmod(handle.fileno(), 0o600)
            os.fsync(handle.fileno())
        return content


def _final_relative_path(project_id: str, digest: str, filename: str) -> str:
    return PurePosixPath("sources", project_id, digest[:2], digest, filename).as_posix()


def _derivative_relative_path(project_id: str, digest: str, filename: str) -> str:
    return PurePosixPath(
        "derivatives", project_id, digest[:2], digest, filename
    ).as_posix()


def _finalize(
    *,
    root: Path,
    root_fd: int,
    incoming_fd: int,
    staging_fd: int,
    temporary: str,
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
    _resolve_under(root, relative)
    parts = PurePosixPath(relative).parts
    with _directory_at(root_fd, parts[:-1], create=True) as destination:
        try:
            # Atomic exclusive publication: a concurrent winner is validated,
            # never overwritten. The staging descriptor remains open until here.
            os.link(
                temporary,
                parts[-1],
                src_dir_fd=incoming_fd,
                dst_dir_fd=destination,
                follow_symlinks=False,
            )
        except FileExistsError:
            try:
                _read_at(
                    destination,
                    parts[-1],
                    expected_digest=digest,
                    expected_size=size_bytes,
                    max_bytes=size_bytes,
                    make_private=True,
                )
            except StorageError as exc:
                raise StorageError(
                    "storage_collision",
                    "Existing digest path failed integrity validation",
                ) from exc
        except OSError as exc:
            if exc.errno in {errno.EXDEV, errno.ENOSYS, errno.EOPNOTSUPP, errno.EPERM}:
                raise StorageError(
                    "storage_unsupported",
                    "Evidence storage requires exclusive hard links on one filesystem",
                ) from exc
            raise
        else:
            staging = os.fstat(staging_fd)
            published = os.stat(parts[-1], dir_fd=destination, follow_symlinks=False)
            if (published.st_dev, published.st_ino) != (staging.st_dev, staging.st_ino):
                raise StorageError(
                    "storage_collision", "Staging identity changed before publication"
                )
        # A previous attempt may have linked the final but failed directory sync.
        # Identical retries must complete the same durability step too.
        os.fsync(destination)
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
    name = safe_filename(filename)
    digest = hashlib.sha256()
    size = 0
    with _temporary_file(root) as (root_fd, incoming_fd, temporary, handle):
        async for chunk in chunks:
            if not chunk:
                continue
            size += len(chunk)
            if size > max_bytes:
                raise StorageError(
                    "limit_exceeded",
                    f"Upload exceeds the {max_bytes}-byte file limit",
                )
            digest.update(chunk)
            handle.write(chunk)
        handle.flush()
        os.fsync(handle.fileno())
        if size == 0:
            raise StorageError("empty_upload", "Uploaded artifact is empty")
        return _finalize(
            root=root,
            root_fd=root_fd,
            incoming_fd=incoming_fd,
            staging_fd=handle.fileno(),
            temporary=temporary,
            project_id=project_id,
            filename=name,
            digest=digest.hexdigest(),
            size_bytes=size,
            media_type=media_type,
            namespace="sources",
        )


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
        raise StorageError(
            "limit_exceeded", f"Upload exceeds the {max_bytes}-byte file limit"
        )
    name = safe_filename(filename)
    with _temporary_file(root) as (root_fd, incoming_fd, temporary, handle):
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        return _finalize(
            root=root,
            root_fd=root_fd,
            incoming_fd=incoming_fd,
            staging_fd=handle.fileno(),
            temporary=temporary,
            project_id=project_id,
            filename=name,
            digest=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            media_type=media_type,
            namespace="sources",
        )


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
        raise StorageError(
            "limit_exceeded", f"Derivative exceeds the {max_bytes}-byte file limit"
        )
    name = safe_filename(filename)
    with _temporary_file(root) as (root_fd, incoming_fd, temporary, handle):
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        return _finalize(
            root=root,
            root_fd=root_fd,
            incoming_fd=incoming_fd,
            staging_fd=handle.fileno(),
            temporary=temporary,
            project_id=project_id,
            filename=name,
            digest=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            media_type=media_type,
            namespace="derivatives",
        )


def read_stored_bytes(
    *,
    root: Path,
    relative_path: str,
    expected_digest: str,
    expected_size: int,
    max_bytes: int,
) -> bytes:
    _resolve_under(root, relative_path)
    parts = PurePosixPath(relative_path).parts
    try:
        with (
            _root_directory(root) as root_fd,
            _directory_at(root_fd, parts[:-1]) as directory,
        ):
            return _read_at(
                directory,
                parts[-1],
                expected_digest=expected_digest,
                expected_size=expected_size,
                max_bytes=max_bytes,
            )
    except FileNotFoundError as exc:
        raise StorageError(
            "storage_missing", "Stored source artifact no longer exists"
        ) from exc
