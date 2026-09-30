"""Private operational key storage. This module never stores evidence or logs keys."""

from __future__ import annotations

import base64
import binascii
import fcntl
import json
import os
import re
import secrets
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Settings

PRIVATE_DIRECTORY = ".redaction"
KEY_FILE = "installation-key-v1.json"
MARKER_FILE = "initialized-v1"
MAX_KEY_FILE_BYTES = 8192
KEY_LOCK_TIMEOUT_SECONDS = 1.0
_KEY_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")


class RedactionKeyError(ValueError):
    """Fixed error codes only: never include a key, configuration value or file body."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class KeyMaterial:
    reference: str
    source: str
    material: bytes = field(repr=False)


def valid_key_reference(value: object) -> bool:
    return isinstance(value, str) and _KEY_REF.fullmatch(value) is not None


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise RedactionKeyError("redaction_keyring_invalid")
        result[name] = value
    return result


def _decode_key(value: object) -> bytes:
    if not isinstance(value, str) or len(value) > 344:
        raise RedactionKeyError("redaction_key_invalid")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise RedactionKeyError("redaction_key_invalid") from None
    if not 32 <= len(decoded) <= 256:
        raise RedactionKeyError("redaction_key_invalid")
    return decoded


def _check_private(info: os.stat_result, *, directory: bool = False) -> None:
    kind_ok = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (
        not kind_ok
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
        or (not directory and info.st_nlink != 1)
    ):
        raise RedactionKeyError("redaction_key_permissions_unsafe")


def _read(directory: int, name: str) -> bytes | None:
    try:
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(descriptor)
        _check_private(info)
        if info.st_size > MAX_KEY_FILE_BYTES:
            raise RedactionKeyError("redaction_key_invalid")
        value = os.read(descriptor, MAX_KEY_FILE_BYTES + 1)
        if len(value) > MAX_KEY_FILE_BYTES:
            raise RedactionKeyError("redaction_key_invalid")
        return value
    finally:
        os.close(descriptor)


def _publish(directory: int, name: str, content: bytes) -> None:
    """Publish complete, fsynced bytes atomically, without replacing a winner."""
    temporary = ".pending-" + secrets.token_hex(16)
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(
                temporary,
                name,
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
        except FileExistsError:
            pass
    finally:
        os.unlink(temporary, dir_fd=directory)
    os.fsync(directory)


def _lock_directory(directory: int) -> None:
    deadline = time.monotonic() + KEY_LOCK_TIMEOUT_SECONDS
    while True:
        try:
            fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RedactionKeyError("redaction_key_storage_busy") from None
            time.sleep(min(0.02, remaining))


def _local_key(root: Path, *, allow_create: bool) -> KeyMaterial:
    # The artifact root can be readable but cannot be writable by other users.
    # Open directory descriptors keep file operations attached to validated paths.
    if allow_create:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        root_info = os.fstat(root_fd)
        if root_info.st_uid != os.geteuid() or root_info.st_mode & 0o022:
            raise RedactionKeyError("redaction_key_permissions_unsafe")
        if allow_create:
            try:
                os.mkdir(PRIVATE_DIRECTORY, 0o700, dir_fd=root_fd)
            except FileExistsError:
                pass
        directory = os.open(
            PRIVATE_DIRECTORY,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=root_fd,
        )
    finally:
        os.close(root_fd)
    try:
        _check_private(os.fstat(directory), directory=True)
        # Serialize creators/readers until the hard-link temporary is removed.
        _lock_directory(directory)
        marker = _read(directory, MARKER_FILE)
        value = _read(directory, KEY_FILE)
        if value is None:
            if marker is not None or not allow_create:
                raise RedactionKeyError("redaction_key_missing")
            material = {
                "version": "installation-key-v1",
                "key_ref": "local-v1-" + secrets.token_hex(12),
                "key": base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
            }
            _publish(
                directory,
                KEY_FILE,
                json.dumps(material, separators=(",", ":")).encode(),
            )
            value = _read(directory, KEY_FILE)
        try:
            record = json.loads(value or b"", object_pairs_hook=_unique_object)
        except (ValueError, UnicodeError):
            raise RedactionKeyError("redaction_key_invalid") from None
        if (
            not isinstance(record, dict)
            or set(record) != {"version", "key_ref", "key"}
            or record["version"] != "installation-key-v1"
            or not valid_key_reference(record["key_ref"])
            or not record["key_ref"].startswith("local-v1-")
        ):
            raise RedactionKeyError("redaction_key_invalid")
        key = KeyMaterial(record["key_ref"], "local", _decode_key(record["key"]))
        expected_marker = (key.reference + "\n").encode("ascii")
        if marker is None:
            _publish(directory, MARKER_FILE, expected_marker)
            marker = _read(directory, MARKER_FILE)
        if marker != expected_marker:
            raise RedactionKeyError("redaction_key_reference_mismatch")
        return key
    finally:
        os.close(directory)


def load_key(
    settings: Settings,
    *,
    expected_reference: str | None = None,
    allow_local_create: bool = False,
) -> KeyMaterial:
    """Resolve a server-selected key. Missing pinned keys never select another key."""
    try:
        configured = settings.redaction_keyring
        active = settings.redaction_active_key_ref
        reference = expected_reference or active
        if reference is not None and not valid_key_reference(reference):
            raise RedactionKeyError("redaction_key_reference_invalid")
        if configured is not None:
            raw = configured.get_secret_value()
            if len(raw) > 32_768:
                raise RedactionKeyError("redaction_keyring_invalid")
            try:
                ring = json.loads(raw, object_pairs_hook=_unique_object)
            except (ValueError, UnicodeError):
                raise RedactionKeyError("redaction_keyring_invalid") from None
            if (
                not isinstance(ring, dict)
                or not ring
                or len(ring) > 64
                or any(
                    not valid_key_reference(k) or k.startswith("local-v1-")
                    for k in ring
                )
            ):
                raise RedactionKeyError("redaction_keyring_invalid")
            if active is None or not valid_key_reference(active) or active not in ring:
                raise RedactionKeyError("redaction_active_key_missing")
            if reference is not None and reference in ring:
                return KeyMaterial(reference, "operator", _decode_key(ring[reference]))
            if reference is None or not reference.startswith("local-v1-"):
                raise RedactionKeyError("redaction_key_missing")
        elif active is not None:
            raise RedactionKeyError("redaction_keyring_missing")
        elif reference is not None and not reference.startswith("local-v1-"):
            raise RedactionKeyError("redaction_key_missing")
        key = _local_key(
            settings.artifact_root,
            allow_create=allow_local_create and reference is None,
        )
        if reference is not None and key.reference != reference:
            raise RedactionKeyError("redaction_key_reference_mismatch")
        return key
    except FileNotFoundError:
        raise RedactionKeyError("redaction_key_missing") from None
    except OSError:
        raise RedactionKeyError("redaction_key_storage_unavailable") from None
