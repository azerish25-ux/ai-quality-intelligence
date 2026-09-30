"""Tiny owned-filesystem regressions; no hostile-volume-owner guarantee is implied."""

from __future__ import annotations

import asyncio
import errno
import hashlib
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from failurelens import storage

CONTENT = b"owned synthetic bytes"


def store(root, content=CONTENT, *, derivative=False):
    function = storage.store_derivative_bytes if derivative else storage.store_bytes
    return function(
        content,
        root=root,
        project_id="project",
        filename="evidence.bin",
        media_type="application/octet-stream",
        max_bytes=64,
    )


def read(root, stored, *, maximum=64):
    return storage.read_stored_bytes(
        root=root,
        relative_path=stored.relative_path,
        expected_digest=stored.digest,
        expected_size=stored.size_bytes,
        max_bytes=maximum,
    )


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_real_task_cancellation_preserves_reason_and_cleans_staging(
    tmp_path, monkeypatch, cleanup_fails
):
    if cleanup_fails:

        def fail_unlink(*args, **kwargs):
            raise OSError(errno.EIO, "synthetic cleanup failure")

        monkeypatch.setattr(storage.os, "unlink", fail_unlink)

    async def scenario():
        waiting = asyncio.Event()

        async def chunks():
            yield CONTENT
            waiting.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(
            storage.store_stream(
                chunks(),
                root=tmp_path,
                project_id="project",
                filename="evidence.bin",
                media_type="application/octet-stream",
                max_bytes=64,
            )
        )
        await waiting.wait()
        task.cancel("original cancellation")
        with pytest.raises(asyncio.CancelledError, match="original cancellation"):
            await task

    asyncio.run(scenario())
    assert len(list((tmp_path / "incoming").iterdir())) == int(cleanup_fails)
    assert not (tmp_path / "sources").exists()


def test_generator_error_survives_failed_cleanup(tmp_path, monkeypatch):
    failure = RuntimeError("original producer failure")

    async def chunks():
        yield CONTENT
        raise failure

    def fail_unlink(*args, **kwargs):
        raise OSError(errno.EIO, "synthetic cleanup failure")

    monkeypatch.setattr(storage.os, "unlink", fail_unlink)
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(
            storage.store_stream(
                chunks(),
                root=tmp_path,
                project_id="project",
                filename="evidence.bin",
                media_type="application/octet-stream",
                max_bytes=64,
            )
        )
    assert caught.value is failure


@pytest.mark.parametrize(
    "chunks,code",
    [
        ([b"", b""], "empty_upload"),
        ([b"123", b"45"], "limit_exceeded"),
        ([b"", b"12", b"", b"34"], None),
    ],
)
def test_stream_boundaries_leave_no_staging_files(tmp_path, chunks, code):
    async def values():
        for value in chunks:
            yield value

    coroutine = storage.store_stream(
        values(),
        root=tmp_path,
        project_id="project",
        filename="evidence.bin",
        media_type="application/octet-stream",
        max_bytes=4,
    )
    if code:
        with pytest.raises(storage.StorageError) as caught:
            asyncio.run(coroutine)
        assert caught.value.code == code
    else:
        stored = asyncio.run(coroutine)
        assert read(tmp_path, stored, maximum=4) == b"1234"
    assert not list((tmp_path / "incoming").iterdir())


@pytest.mark.parametrize("stage", ["write", "flush", "close", "fsync", "link"])
def test_storage_failure_preserves_exception_and_existing_final(
    tmp_path, monkeypatch, stage
):
    original = store(tmp_path)
    original_path = tmp_path / original.relative_path
    original_inode = original_path.stat().st_ino
    failure = OSError(errno.EIO, "synthetic storage failure")
    fdopen = os.fdopen

    class BrokenWriter:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def write(self, content):
            if stage == "write":
                raise failure
            return self.wrapped.write(content)

        def flush(self):
            if stage == "flush":
                raise failure
            return self.wrapped.flush()

        def fileno(self):
            return self.wrapped.fileno()

        def close(self):
            self.wrapped.close()
            if stage == "close":
                raise failure

    if stage in {"write", "flush", "close"}:

        def wrapped_fdopen(fd, mode, *args, **kwargs):
            handle = fdopen(fd, mode, *args, **kwargs)
            return BrokenWriter(handle) if mode == "wb" else handle

        monkeypatch.setattr(storage.os, "fdopen", wrapped_fdopen)
    else:

        def fail(*args, **kwargs):
            raise failure

        monkeypatch.setattr(storage.os, stage, fail)
    with pytest.raises(OSError) as caught:
        store(tmp_path)
    assert caught.value is failure
    assert original_path.read_bytes() == CONTENT
    assert original_path.stat().st_ino == original_inode
    assert not list((tmp_path / "incoming").iterdir())


def test_write_error_survives_close_and_unlink_errors(tmp_path, monkeypatch):
    failure = OSError(errno.ENOSPC, "synthetic full disk")
    fdopen = os.fdopen

    class BrokenWriter:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def write(self, content):
            raise failure

        def close(self):
            self.wrapped.close()
            raise OSError(errno.EIO, "synthetic close failure")

    def wrap(fd, mode, **kwargs):
        return BrokenWriter(fdopen(fd, mode, **kwargs))

    def fail_unlink(*args, **kwargs):
        raise OSError(errno.EIO, "synthetic unlink failure")

    monkeypatch.setattr(storage.os, "fdopen", wrap)
    monkeypatch.setattr(storage.os, "unlink", fail_unlink)
    with pytest.raises(OSError) as caught:
        store(tmp_path)
    assert caught.value is failure


@pytest.mark.parametrize("operation", ["read", "write"])
@pytest.mark.parametrize("close_fails", [False, True])
def test_fdopen_failure_closes_owned_descriptor_and_preserves_error(
    tmp_path, monkeypatch, operation, close_fails
):
    stored = store(tmp_path)
    failure = OSError(errno.ENFILE, "synthetic fdopen failure")
    owned = []
    close = os.close

    def fail_fdopen(fd, *args, **kwargs):
        owned.append(fd)
        raise failure

    def close_then_fail(fd):
        close(fd)
        if close_fails and fd in owned:
            raise OSError(errno.EIO, "synthetic descriptor close failure")

    monkeypatch.setattr(storage.os, "fdopen", fail_fdopen)
    monkeypatch.setattr(storage.os, "close", close_then_fail)
    with pytest.raises(OSError) as caught:
        if operation == "read":
            read(tmp_path, stored)
        else:
            store(tmp_path)
    assert caught.value is failure
    assert len(owned) == 1
    with pytest.raises(OSError) as closed:
        os.fstat(owned[0])
    assert closed.value.errno == errno.EBADF
    assert not list((tmp_path / "incoming").iterdir())


def test_directory_sync_failure_never_removes_published_content(tmp_path, monkeypatch):
    fsync = os.fsync

    def fail_directory_sync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EIO, "synthetic directory sync failure")
        fsync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(storage.os, "fsync", fail_directory_sync)
        for _ in range(2):
            with pytest.raises(OSError, match="directory sync"):
                store(tmp_path)
    paths = list((tmp_path / "sources").rglob("evidence.bin"))
    assert len(paths) == 1 and paths[0].read_bytes() == CONTENT
    assert not list((tmp_path / "incoming").iterdir())
    assert read(tmp_path, store(tmp_path)) == CONTENT


@pytest.mark.parametrize("preexisting", [False, True])
def test_post_publication_unlink_failure_retains_final_and_allows_retry(
    tmp_path, monkeypatch, preexisting
):
    if preexisting:
        prior = store(tmp_path)
        prior_inode = (tmp_path / prior.relative_path).stat().st_ino
    failure = OSError(errno.EIO, "synthetic staging unlink failure")

    def fail_unlink(*args, **kwargs):
        raise failure

    with monkeypatch.context() as patch:
        patch.setattr(storage.os, "unlink", fail_unlink)
        with pytest.raises(OSError) as caught:
            store(tmp_path)
    assert caught.value is failure
    finals = list((tmp_path / "sources").rglob("evidence.bin"))
    assert len(finals) == 1 and finals[0].read_bytes() == CONTENT
    if preexisting:
        assert finals[0].stat().st_ino == prior_inode
    # An OS refusing cleanup can leave a private staging link. Retrying the upload
    # validates the final; it cannot clean a prior request's unidentified orphan.
    assert len(list((tmp_path / "incoming").iterdir())) == 1
    assert read(tmp_path, store(tmp_path)) == CONTENT


def test_staging_name_replacement_is_detected_before_returning_metadata(
    tmp_path, monkeypatch
):
    link = os.link

    def replace_staging(source, target, *, src_dir_fd, **kwargs):
        os.rename(
            source, "moved-owned-staging", src_dir_fd=src_dir_fd, dst_dir_fd=src_dir_fd
        )
        fd = os.open(
            source, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=src_dir_fd
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(b"x" * len(CONTENT))
        return link(source, target, src_dir_fd=src_dir_fd, **kwargs)

    monkeypatch.setattr(storage.os, "link", replace_staging)
    with pytest.raises(storage.StorageError) as caught:
        store(tmp_path)
    assert caught.value.code == "storage_collision"
    # The malicious replacement is not approved and is never removed through a
    # possibly raced final pathname. Operators still own corrupted-volume repair.
    finals = list((tmp_path / "sources").rglob("evidence.bin"))
    assert len(finals) == 1 and finals[0].read_bytes() != CONTENT


@pytest.mark.parametrize("derivative", [False, True])
def test_identical_concurrent_uploads_publish_one_private_inode(
    tmp_path, monkeypatch, derivative
):
    barrier = Barrier(2)
    link = os.link

    def together(*args, **kwargs):
        barrier.wait(timeout=5)
        return link(*args, **kwargs)

    monkeypatch.setattr(storage.os, "link", together)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(store, tmp_path, derivative=derivative) for _ in range(2)
        ]
        first, second = [future.result(timeout=10) for future in futures]
    assert first == second and read(tmp_path, first) == CONTENT
    info = (tmp_path / first.relative_path).stat()
    assert stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
    assert not list((tmp_path / "incoming").iterdir())


@pytest.mark.parametrize("bad_content", [b"short", b"x" * len(CONTENT)])
def test_preexisting_digest_collision_is_never_clobbered(tmp_path, bad_content):
    stored = store(tmp_path)
    path = tmp_path / stored.relative_path
    path.write_bytes(bad_content)
    inode = path.stat().st_ino
    with pytest.raises(storage.StorageError) as caught:
        store(tmp_path)
    assert caught.value.code == "storage_collision"
    assert path.read_bytes() == bad_content and path.stat().st_ino == inode
    assert not list((tmp_path / "incoming").iterdir())


def test_identical_existing_file_permissions_are_private(tmp_path):
    stored = store(tmp_path)
    path = tmp_path / stored.relative_path
    path.chmod(0o644)
    assert store(tmp_path) == stored
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("component", ["incoming", "sources", "sources/project"])
def test_symlinked_staging_and_namespace_directories_are_rejected(tmp_path, component):
    root = tmp_path / "root"
    root.mkdir()
    target = tmp_path / "owned-sibling"
    target.mkdir()
    alias = root / component
    alias.parent.mkdir(parents=True, exist_ok=True)
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(storage.StorageError) as caught:
        store(root)
    assert caught.value.code == "unsafe_storage_path"
    assert not list(target.iterdir())


def test_configured_root_alias_remains_supported(tmp_path):
    root = tmp_path / "real-root"
    root.mkdir()
    alias = tmp_path / "configured-root"
    alias.symlink_to(root, target_is_directory=True)
    stored = store(alias)
    assert read(alias, stored) == read(root, stored) == CONTENT


def test_finalization_rejects_parent_swap_before_descriptor_open(tmp_path, monkeypatch):
    root = tmp_path / "root"
    outside = tmp_path / "owned-sibling"
    outside.mkdir()
    resolve = storage._resolve_under

    def switch_parent(root, relative):
        destination = resolve(root, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.parent.rename(destination.parent.with_name("saved"))
        destination.parent.symlink_to(outside, target_is_directory=True)
        return destination

    monkeypatch.setattr(storage, "_resolve_under", switch_parent)
    with pytest.raises(storage.StorageError) as caught:
        store(root)
    assert caught.value.code == "unsafe_storage_path"
    assert not list(outside.iterdir())
    assert not list((root / "incoming").iterdir())


def test_open_destination_descriptor_does_not_follow_later_parent_alias(
    tmp_path, monkeypatch
):
    root = tmp_path / "root"
    outside = tmp_path / "owned-sibling"
    outside.mkdir()
    digest = hashlib.sha256(CONTENT).hexdigest()
    parent = root / "sources" / "project" / digest[:2] / digest
    saved = parent.with_name("moved-owned-directory")
    link = os.link

    def switch_parent(*args, **kwargs):
        parent.rename(saved)
        parent.symlink_to(outside, target_is_directory=True)
        return link(*args, **kwargs)

    monkeypatch.setattr(storage.os, "link", switch_parent)
    stored = store(root)
    assert not list(outside.iterdir())
    assert (saved / "evidence.bin").read_bytes() == CONTENT
    # Pinning prevents redirected I/O; it cannot stop a volume owner renaming
    # directories. The now-aliased metadata path fails closed on the next read.
    with pytest.raises(storage.StorageError) as caught:
        read(root, stored)
    assert caught.value.code == "unsafe_storage_path"


@pytest.mark.parametrize("replace", [False, True])
def test_reads_use_the_open_descriptor_and_bound_growth(tmp_path, monkeypatch, replace):
    stored = store(tmp_path, b"A")
    path = tmp_path / stored.relative_path
    target_inode = path.stat().st_ino
    fstat = os.fstat
    fdopen = os.fdopen
    changed = False
    requested = []

    def change_after_stat(fd):
        nonlocal changed
        info = fstat(fd)
        if info.st_ino == target_inode and not changed:
            changed = True
            if replace:
                path.rename(path.with_name("saved-original"))
                path.write_bytes(b"B" * 16)
            else:
                path.write_bytes(b"A" * 16)
        return info

    class ObservedReader:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def fileno(self):
            return self.handle.fileno()

        def read(self, size):
            requested.append(size)
            return self.handle.read(size)

    def observed_fdopen(fd, mode, *args, **kwargs):
        assert mode == "rb" and kwargs.get("buffering") == 0
        return ObservedReader(fdopen(fd, mode, *args, **kwargs))

    monkeypatch.setattr(storage.os, "fstat", change_after_stat)
    monkeypatch.setattr(storage.os, "fdopen", observed_fdopen)
    if replace:
        assert read(tmp_path, stored, maximum=1) == b"A"
    else:
        with pytest.raises(storage.StorageError) as caught:
            read(tmp_path, stored, maximum=1)
        assert caught.value.code == "limit_exceeded"
    assert requested == [2]


@pytest.mark.parametrize(
    "change,code",
    [
        ("missing", "storage_missing"),
        ("size", "storage_size_mismatch"),
        ("digest", "digest_mismatch"),
        ("limit", "limit_exceeded"),
        ("symlink", "unsafe_storage_path"),
        ("fifo", "unsafe_storage_path"),
    ],
)
def test_reads_fail_closed_for_unavailable_or_changed_files(tmp_path, change, code):
    stored = store(tmp_path)
    path = tmp_path / stored.relative_path
    if change in {"missing", "symlink", "fifo"}:
        path.unlink()
    if change == "size":
        path.write_bytes(b"short")
    elif change == "digest":
        path.write_bytes(b"x" * len(CONTENT))
    elif change == "symlink":
        target = tmp_path / "owned-target"
        target.write_bytes(CONTENT)
        path.symlink_to(target)
    elif change == "fifo":
        os.mkfifo(path, 0o600)
    with pytest.raises(storage.StorageError) as caught:
        read(tmp_path, stored, maximum=1 if change == "limit" else 64)
    assert caught.value.code == code


@pytest.mark.parametrize(
    "relative", ["../outside", "/absolute", "sources/../file", "a\\b", "a\x00b"]
)
def test_invalid_storage_paths_are_rejected_before_open(tmp_path, relative):
    with pytest.raises(storage.StorageError) as caught:
        storage.read_stored_bytes(
            root=tmp_path,
            relative_path=relative,
            expected_digest="0" * 64,
            expected_size=0,
            max_bytes=64,
        )
    assert caught.value.code == "unsafe_storage_path"


def test_missing_descriptor_capabilities_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_DESCRIPTOR_STORAGE_SUPPORTED", False)
    with pytest.raises(storage.StorageError) as caught:
        store(tmp_path)
    assert caught.value.code == "storage_unsupported"
    assert not (tmp_path / "incoming").exists()


@pytest.mark.parametrize("error", [errno.EXDEV, errno.EOPNOTSUPP])
def test_unsupported_hard_link_filesystems_fail_without_replacement(
    tmp_path, monkeypatch, error
):
    def unsupported(*args, **kwargs):
        raise OSError(error, "synthetic unsupported filesystem")

    monkeypatch.setattr(storage.os, "link", unsupported)
    with pytest.raises(storage.StorageError) as caught:
        store(tmp_path)
    assert caught.value.code == "storage_unsupported"
    assert not list((tmp_path / "incoming").iterdir())
    assert not list((tmp_path / "sources").rglob("evidence.bin"))
