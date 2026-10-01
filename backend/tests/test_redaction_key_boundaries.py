"""Private key failures preserve existing state; all material is synthetic."""

from __future__ import annotations

import base64
import errno
import hashlib
import json
import os
import stat

import pytest
from failurelens import redaction_keys as keys
from failurelens.config import Settings
from pydantic import SecretStr


def _tree(root):
    return {
        path.relative_to(root).as_posix(): (
            stat.S_IMODE(path.stat().st_mode),
            path.stat().st_nlink,
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
        )
        for path in sorted(root.rglob("*"))
    }


def _initialized(tmp_path):
    settings = Settings(artifact_root=tmp_path / "artifacts")
    expected = keys.load_key(settings, allow_local_create=True)
    assert keys.load_key(settings).material == expected.material
    return settings, expected


@pytest.mark.parametrize(
    "damage",
    [
        "array",
        "scalar",
        "missing-key",
        "extra-field",
        "unknown-version",
        "invalid-reference",
        "operator-reference",
        "null-key",
        "numeric-key",
        "array-key",
        "oversized-encoded-key",
    ],
)
def test_malformed_private_record_never_regenerates_or_rewrites_storage(
    tmp_path, monkeypatch, damage
):
    settings, expected = _initialized(tmp_path)
    path = settings.artifact_root / keys.PRIVATE_DIRECTORY / keys.KEY_FILE
    original = path.read_bytes()
    record = json.loads(original)
    if damage == "array":
        record = [record]
    elif damage == "scalar":
        record = 42
    elif damage == "missing-key":
        record.pop("key")
    elif damage == "extra-field":
        record["unexpected"] = "field"
    else:
        field, value = {
            "unknown-version": ("version", "future-version"),
            "invalid-reference": ("key_ref", "../invalid"),
            "operator-reference": ("key_ref", "operator-v1"),
            "null-key": ("key", None),
            "numeric-key": ("key", 42),
            "array-key": ("key", ["invalid"]),
            "oversized-encoded-key": ("key", base64.b64encode(b"x" * 259).decode()),
        }[damage]
        record[field] = value
    path.write_text(json.dumps(record))
    before = _tree(settings.artifact_root)

    def forbid_publish(*args, **kwargs):
        pytest.fail("a rejected existing key must not publish replacement state")

    monkeypatch.setattr(keys, "_publish", forbid_publish)
    with pytest.raises(keys.RedactionKeyError) as error:
        keys.load_key(settings, allow_local_create=True)
    assert error.value.code == "redaction_key_invalid"
    assert str(error.value) == "redaction_key_invalid"
    assert _tree(settings.artifact_root) == before
    # Repairing the operator-owned input restores the original identity/material.
    path.write_bytes(original)
    restored = keys.load_key(settings)
    assert (restored.reference, restored.material) == (
        expected.reference,
        expected.material,
    )


@pytest.mark.parametrize(
    ("active", "reference", "expected_error"),
    [
        ("operator-v1", None, "redaction_keyring_missing"),
        (None, "operator-v1", "redaction_key_missing"),
        (None, "../invalid", "redaction_key_reference_invalid"),
        (None, "x" * 97, "redaction_key_reference_invalid"),
        (None, "local-v1-other", "redaction_key_reference_mismatch"),
    ],
)
def test_missing_or_invalid_reference_never_falls_back_to_existing_local_material(
    tmp_path, active, reference, expected_error
):
    settings, expected = _initialized(tmp_path)
    before = _tree(settings.artifact_root)
    changed = settings.model_copy(update={"redaction_active_key_ref": active})
    with pytest.raises(keys.RedactionKeyError) as error:
        keys.load_key(changed, expected_reference=reference, allow_local_create=True)
    assert str(error.value) == expected_error
    assert _tree(settings.artifact_root) == before
    assert (
        keys.load_key(settings, expected_reference=expected.reference).material
        == expected.material
    )


def test_oversized_operator_keyring_rejects_before_creating_private_state(tmp_path):
    settings = Settings(
        artifact_root=tmp_path / "new-root",
        redaction_active_key_ref="operator-v1",
        redaction_keyring=SecretStr(" " * 32769),
    )
    with pytest.raises(keys.RedactionKeyError) as error:
        keys.load_key(settings, allow_local_create=True)
    assert str(error.value) == "redaction_keyring_invalid"
    assert not settings.artifact_root.exists()


def test_operator_rotation_preserves_correctly_pinned_local_material(tmp_path):
    settings, local = _initialized(tmp_path)
    before = _tree(settings.artifact_root)
    operator_bytes = b"x" * 32
    rotated = settings.model_copy(
        update={
            "redaction_active_key_ref": "operator-v1",
            "redaction_keyring": SecretStr(
                json.dumps({"operator-v1": base64.b64encode(operator_bytes).decode()})
            ),
        }
    )
    active = keys.load_key(rotated)
    assert (active.reference, active.source, active.material) == (
        "operator-v1",
        "operator",
        operator_bytes,
    )
    pinned = keys.load_key(rotated, expected_reference=local.reference)
    assert (pinned.reference, pinned.source, pinned.material) == (
        local.reference,
        "local",
        local.material,
    )
    with pytest.raises(
        keys.RedactionKeyError, match="^redaction_key_reference_mismatch$"
    ):
        keys.load_key(
            rotated, expected_reference="local-v1-wrong", allow_local_create=True
        )
    assert _tree(settings.artifact_root) == before


def test_key_growth_between_stat_and_read_rejects_and_closes_the_descriptor(
    tmp_path, monkeypatch
):
    settings, expected = _initialized(tmp_path)
    path = settings.artifact_root / keys.PRIVATE_DIRECTORY / keys.KEY_FILE
    original = path.read_bytes()
    marker_path = path.parent / keys.MARKER_FILE
    marker = marker_path.read_bytes()
    inode = path.stat().st_ino
    read = os.read
    descriptors = []

    def grow_before_read(descriptor, count):
        if os.fstat(descriptor).st_ino == inode:
            # _read already checked the smaller fstat size; use the real fd read.
            descriptors.append(descriptor)
            path.write_bytes(original + b" " * keys.MAX_KEY_FILE_BYTES)
        return read(descriptor, count)

    with monkeypatch.context() as patch:
        patch.setattr(keys.os, "read", grow_before_read)
        with pytest.raises(keys.RedactionKeyError, match="^redaction_key_invalid$"):
            keys.load_key(settings, allow_local_create=True)
    assert len(descriptors) == 1
    with pytest.raises(OSError) as error:
        os.fstat(descriptors[0])
    assert error.value.errno == errno.EBADF
    assert path.read_bytes() == original + b" " * keys.MAX_KEY_FILE_BYTES
    assert marker_path.read_bytes() == marker
    assert sorted(item.name for item in path.parent.iterdir()) == sorted(
        [keys.KEY_FILE, keys.MARKER_FILE]
    )
    path.write_bytes(original)
    assert keys.load_key(settings).material == expected.material


def test_atomic_publication_preserves_existing_winner_and_removes_its_temporary(
    tmp_path,
):
    settings, expected = _initialized(tmp_path)
    directory_path = settings.artifact_root / keys.PRIVATE_DIRECTORY
    before = _tree(settings.artifact_root)
    descriptor = os.open(directory_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        keys._publish(descriptor, keys.KEY_FILE, b"replacement must not win")
    finally:
        os.close(descriptor)
    assert _tree(settings.artifact_root) == before
    assert keys.load_key(settings).material == expected.material
