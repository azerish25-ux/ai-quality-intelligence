"""Actual child-process checks with synthetic canaries, not OS sandbox claims."""

from __future__ import annotations

import io
import json
import os
import subprocess
import uuid
from pathlib import Path

from failurelens import image_codec
from failurelens.config import Settings
from PIL import Image


def png_bytes():
    target = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(target, format="PNG")
    return target.getvalue()


def test_image_child_has_isolated_startup_without_parent_settings_or_descriptors(
    tmp_path, monkeypatch
):
    names = [
        "FAILURELENS_DATABASE_URL",
        "FAILURELENS_PROVIDER_TOKEN",
        "FAILURELENS_BOOTSTRAP_ADMIN_PASSWORD",
        "OTEL_EXPORTER_OTLP_HEADERS",
        "UNRECOGNIZED_PARENT_SETTING",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
    ]
    for name in names:
        monkeypatch.setenv(name, f"image-parent-fixture-{uuid.uuid4()}")
    private = tmp_path / "parent-only.txt"
    private.write_text("synthetic parent-only data")
    descriptor = os.open(private, os.O_RDONLY)
    os.set_inheritable(descriptor, True)
    original_run = subprocess.run
    probe = (
        "import json,os,sys\n"
        "names=json.loads(sys.argv[1])\n"
        "try:\n os.fstat(int(sys.argv[2])); inherited=True\n"
        "except OSError:\n inherited=False\n"
        "print(json.dumps({'encoded_bytes':0,'isolated':sys.flags.isolated,"
        "'present':[name for name in names if name in os.environ],"
        "'inherited_descriptor':inherited}))\n"
    )

    def observe_child(command, **kwargs):
        # Retain the exact production interpreter options and launch settings;
        # replace only the worker body with a trusted, source-free environment probe.
        prefix = command[: command.index("-m")] if "-m" in command else command[:-1]
        return original_run(
            [*prefix, "-c", probe, json.dumps(names), str(descriptor)], **kwargs
        )

    monkeypatch.setattr(image_codec.subprocess, "run", observe_child)
    try:
        metadata, payload = image_codec.decode_image(png_bytes(), Settings())
    finally:
        os.close(descriptor)
    assert payload == b""
    assert metadata["isolated"] == 1
    assert metadata["present"] == []
    assert metadata["inherited_descriptor"] is False


def test_image_child_ignores_untrusted_pythonpath_startup(tmp_path, monkeypatch):
    untrusted = tmp_path / "untrusted-imports"
    untrusted.mkdir()
    marker = tmp_path / "startup-hook-executed"
    (untrusted / "sitecustomize.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('synthetic startup hook')\n"
    )
    source = Path(image_codec.__file__).resolve().parents[1]
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join((str(untrusted), str(source))))
    metadata, payload = image_codec.decode_image(png_bytes(), Settings(), encode=True)
    assert metadata["width"] == metadata["height"] == 4
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    assert not marker.exists()
