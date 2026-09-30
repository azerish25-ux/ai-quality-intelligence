"""Real isolated worker behavior, with separate direct and instrumented launches.

These tests never alter image_codec's production launch or substitute worker code.
The original parent-environment/import/descriptor canaries remain uninstrumented.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import coverage
import pytest
from failurelens import image_codec
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts/isolated_worker_coverage.py"
WORKER = Path(image_codec.__file__).resolve().with_name("image_worker.py")


def image_bytes(format_name: str = "PNG", animated: bool = False) -> bytes:
    target = io.BytesIO()
    first = Image.new("RGB", (4, 4), (10, 20, 30))
    if animated:
        first.save(
            target,
            format="PNG",
            save_all=True,
            append_images=[Image.new("RGB", (4, 4), "red")],
            duration=100,
        )
    else:
        first.save(target, format=format_name)
    return target.getvalue()


def options(**updates):
    return {
        "max_bytes": 1024 * 1024,
        "max_pixels": 1024,
        "encode": False,
        "masks": [],
        **updates,
    }


def launch(content: bytes, settings: dict, tmp_path: Path, instrumented: bool):
    environment = {"PATH": os.defpath}
    if os.name == "nt" and "SYSTEMROOT" in os.environ:
        environment["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    command = [sys.executable, "-I", str(WORKER)]
    shard = None
    if instrumented:
        active = coverage.Coverage.current()
        # Explicit destination, never a coverage/configuration environment variable
        # in the isolated child. Without an active measurement use test temp space.
        base = (
            Path(active.config.data_file).resolve()
            if active
            else tmp_path / ".coverage"
        )
        shard = base.with_name(base.name + ".image-worker-" + uuid.uuid4().hex)
        command = [
            sys.executable,
            "-I",
            str(WRAPPER),
            str(WORKER),
            hashlib.sha256(WORKER.read_bytes()).hexdigest(),
            str(shard),
            str(WORKER.parent),
        ]
    result = subprocess.run(
        command,
        input=json.dumps(settings).encode() + b"\n" + content,
        env=environment,
        close_fds=True,
        capture_output=True,
        timeout=12,
        check=False,
    )
    assert result.returncode == 0
    if shard is not None:
        data = coverage.CoverageData(basename=str(shard))
        data.read()
        assert data.has_arcs()
        assert {name for name in data.measured_files() if data.arcs(name)} == {
            str(WORKER)
        }
        assert data.arcs(str(WORKER))
    header, payload = result.stdout.split(b"\n", 1)
    return json.loads(header), payload


@pytest.mark.parametrize("format_name", ["PNG", "JPEG"])
@pytest.mark.parametrize("encode,preview", [(False, None), (True, None), (True, 2)])
def test_instrumented_worker_preserves_actual_success_output(
    tmp_path, format_name, encode, preview
):
    content = image_bytes(format_name)
    settings = options(encode=encode, preview_size=preview)
    actual = launch(content, settings, tmp_path, False)
    measured = launch(content, settings, tmp_path, True)
    assert measured == actual
    metadata, payload = measured
    assert (metadata["width"], metadata["height"]) == (4, 4)
    assert metadata["media_type"] == (
        "image/png" if format_name == "PNG" else "image/jpeg"
    )
    assert metadata["encoded_bytes"] == len(payload)
    if encode:
        with Image.open(io.BytesIO(payload)) as decoded:
            assert decoded.size == ((2, 2) if preview else (4, 4))
            assert decoded.mode == "RGB"
    else:
        assert payload == b""


@pytest.mark.parametrize(
    "settings,error",
    [
        (options(max_pixels=15), "limit_exceeded"),
        (
            options(masks=[{"x": 0, "y": 0, "width": 1, "height": 1}] * 65),
            "invalid_mask",
        ),
        (options(masks=[{"x": -1, "y": 0, "width": 1, "height": 1}]), "invalid_mask"),
        (options(masks=[{"x": 0, "y": -1, "width": 1, "height": 1}]), "invalid_mask"),
        (options(masks=[{"x": 0, "y": 0, "width": 0, "height": 1}]), "invalid_mask"),
        (options(masks=[{"x": 0, "y": 0, "width": 1, "height": 0}]), "invalid_mask"),
        (options(masks=[{"x": 3, "y": 0, "width": 2, "height": 1}]), "invalid_mask"),
        (options(masks=[{"x": 0, "y": 3, "width": 1, "height": 2}]), "invalid_mask"),
        (options(masks=[{"x": True, "y": 0, "width": 1, "height": 1}]), "invalid_mask"),
        (options(masks=[{}]), "malformed_image"),
        (options(max_bytes="invalid"), "malformed_image"),
    ],
)
def test_instrumented_worker_preserves_rejection_output(tmp_path, settings, error):
    content = image_bytes()
    actual = launch(content, settings, tmp_path, False)
    measured = launch(content, settings, tmp_path, True)
    assert measured == actual == ({"error": error}, b"")


@pytest.mark.parametrize(
    "case,error",
    [
        ("empty", "limit_exceeded"),
        ("oversized", "limit_exceeded"),
        ("malformed", "malformed_image"),
        ("animated", "unsupported_image_frames"),
    ],
)
def test_instrumented_worker_preserves_content_rejections(tmp_path, case, error):
    content = image_bytes(animated=case == "animated")
    settings = options()
    if case == "empty":
        content = b""
    elif case == "oversized":
        settings["max_bytes"] = len(content) - 1
    elif case == "malformed":
        content = b"\x89PNG\r\n\x1a\ninvalid pixels"
    assert (
        launch(content, settings, tmp_path, True)
        == launch(content, settings, tmp_path, False)
        == ({"error": error}, b"")
    )


def test_instrumented_worker_burns_in_opaque_mask(tmp_path):
    settings = options(encode=True, masks=[{"x": 1, "y": 1, "width": 2, "height": 2}])
    actual = launch(image_bytes(), settings, tmp_path, False)
    measured = launch(image_bytes(), settings, tmp_path, True)
    assert measured == actual
    with Image.open(io.BytesIO(measured[1])) as decoded:
        assert decoded.getpixel((1, 1)) == decoded.getpixel((2, 2)) == (0, 0, 0)
        assert decoded.getpixel((0, 0)) == (10, 20, 30)


def test_wrapper_rejects_stale_worker_digest_without_measurement(tmp_path):
    shard = tmp_path / ".coverage.rejected"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(WRAPPER),
            str(WORKER),
            "stale",
            str(shard),
            str(WORKER.parent),
        ],
        input=b"",
        env={"PATH": os.defpath},
        close_fds=True,
        capture_output=True,
        timeout=12,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == b""
    assert not shard.exists()


def test_wrapper_rejects_dangling_output_symlink(tmp_path):
    target = tmp_path / "must-not-create"
    shard = tmp_path / ".coverage.symlink"
    shard.symlink_to(target)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(WRAPPER),
            str(WORKER),
            hashlib.sha256(WORKER.read_bytes()).hexdigest(),
            str(shard),
            str(WORKER.parent),
        ],
        input=b"",
        env={"PATH": os.defpath},
        close_fds=True,
        capture_output=True,
        timeout=12,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == b""
    assert not target.exists()
