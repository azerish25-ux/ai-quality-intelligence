"""Package only workflow-declared JUnit shards; absent files stay required in manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_BUNDLE_BYTES = 250 * 1024 * 1024


def build_bundle(root: Path, output: Path, shards: list[str]) -> dict:
    if not shards or len(shards) > 100:
        raise ValueError("between one and 100 declared shards are required")
    if output.exists():
        raise ValueError("bundle destination must not exist")
    entries: list[dict[str, str | bool]] = []
    files: list[tuple[str, bytes]] = []
    seen: set[str] = set()
    total = 0
    root = root.resolve()
    for declaration in shards:
        name, separator, relative = declaration.partition("=")
        path = PurePosixPath(relative)
        if (
            not separator
            or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name)
            or name.casefold() in seen
            or path.is_absolute()
            or not path.parts
            or any(part in {"..", "."} for part in relative.split("/"))
            or "\\" in relative
            or path.suffix != ".xml"
        ):
            raise ValueError("invalid or duplicate declared shard")
        seen.add(name.casefold())
        source = root.joinpath(*path.parts)
        for parent in (source, *source.parents):
            if parent == root:
                break
            if parent.is_symlink():
                raise ValueError("symlink shard inputs are not allowed")
        archive_name = f"shards/{name}.xml"
        entry: dict[str, str | bool] = {
            "id": name,
            "kind": "junit-xml",
            "path": archive_name,
            "required": True,
            "role": "primary",
        }
        if source.exists():
            if not source.is_file() or source.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("shard is not a bounded regular file")
            with source.open("rb") as handle:
                content = handle.read(MAX_FILE_BYTES + 1)
            total += len(content)
            if len(content) > MAX_FILE_BYTES or total > MAX_BUNDLE_BYTES - 100_000:
                raise ValueError("shards exceed the bundle limit")
            entry["sha256"] = hashlib.sha256(content).hexdigest()
            files.append((archive_name, content))
        entries.append(entry)
    manifest = {"schema_version": "2.0", "inputs": entries}
    # Fixed timestamps and stored members make equal source bytes reproducible and
    # avoid compression-ratio ambiguity. No file is executed or extracted.
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_STORED) as archive:
        for name, content in [
            ("manifest.json", json.dumps(manifest, sort_keys=True).encode()),
            *files,
        ]:
            archive.writestr(
                zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), content
            )
    return {"expected_shards": len(entries), "present_shards": len(files)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--shard",
        action="append",
        required=True,
        help="workflow-defined name=relative.xml",
    )
    args = parser.parse_args()
    try:
        print(json.dumps(build_bundle(args.root, args.output, args.shard)))
    except (OSError, ValueError, zipfile.BadZipFile):
        raise SystemExit("Declared shard bundle could not be built safely") from None


if __name__ == "__main__":
    main()
