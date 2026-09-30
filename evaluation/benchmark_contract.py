"""Answer-free artifact contract for the general, multi-category replay process."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_FILE = 1024 * 1024


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unique_json(data: bytes):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON member")
            result[key] = value
        return result

    return json.loads(data, object_pairs_hook=unique)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class InputRef(Strict):
    path: str
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    bytes: Annotated[int, Field(gt=0, le=MAX_FILE)]
    source_format: Literal["junit-xml", "failurelens-bundle-v2"]
    expected_inputs: Annotated[int, Field(ge=1, le=8)] = 1

    @field_validator("path")
    @classmethod
    def safe_relative(cls, value):
        p = PurePosixPath(value)
        if (
            p.is_absolute()
            or len(p.parts) != 2
            or ".." in p.parts
            or "\\" in value
            or str(p) != value
            or not value.endswith((".xml", ".zip"))
        ):
            raise ValueError("Unsafe public input path")
        return value


class PriorInput(Strict):
    artifact: InputRef
    review_reason: Annotated[str, Field(min_length=10, max_length=2000)] | None = None


class PublicCase(Strict):
    case_id: Annotated[str, Field(pattern=r"^c-[0-9a-f]{20}$")]
    repository: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]
    source_revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    current: InputRef
    control: InputRef | None = None
    prior: Annotated[list[PriorInput], Field(max_length=8)] = Field(
        default_factory=list
    )
    later: InputRef | None = None

    @model_validator(mode="after")
    def scoped_paths(self):
        refs = [
            self.current,
            self.control,
            self.later,
            *(p.artifact for p in self.prior),
        ]
        paths = [r.path for r in refs if r is not None]
        if len(paths) != len(set(paths)) or any(
            not p.startswith(self.case_id + "/") for p in paths
        ):
            raise ValueError("Duplicate or cross-case input path")
        return self


class PublicManifest(Strict):
    schema_version: Literal["benchmark-input-v1"]
    cases: Annotated[list[PublicCase], Field(min_length=1, max_length=1000)]

    @model_validator(mode="after")
    def distinct_ids(self):
        if len({c.case_id for c in self.cases}) != len(self.cases):
            raise ValueError("Duplicate case IDs")
        return self


def safe_read(root: Path, path: str, limit: int = MAX_FILE) -> bytes:
    base = root.resolve()
    target = root / path
    if (
        target.is_symlink()
        or not target.resolve().is_relative_to(base)
        or any(
            p.is_symlink()
            for p in target.parents
            if p != root.parent and p.is_relative_to(root)
        )
    ):
        raise ValueError("Input escapes its authorized directory")
    if not target.is_file() or target.stat().st_size > limit:
        raise ValueError("Input is missing, non-regular, or oversized")
    with target.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Input exceeds its byte limit")
    return data


def read_input(root: Path, ref: InputRef) -> bytes:
    data = safe_read(root, ref.path)
    if len(data) != ref.bytes or digest(data) != ref.sha256:
        raise ValueError("Input differs from its frozen digest or byte count")
    if ref.source_format == "failurelens-bundle-v2":
        validate_bundle(data, ref.expected_inputs)
    elif ref.expected_inputs != 1 or not ref.path.endswith(".xml"):
        raise ValueError("Standalone JUnit requires exactly one XML input")
    return data


def validate_bundle(data: bytes, count: int) -> dict[str, bytes]:
    """Allow documented public artifacts only, with exact manifest coverage."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        if (
            len(infos) != count + 1
            or "manifest.json" not in names
            or len(names) != len(set(names))
            or sum(i.file_size for i in infos) > MAX_FILE
            or any(
                i.file_size > 256 * 1024
                or i.flag_bits & 1
                or "/" in i.filename
                or "\\" in i.filename
                or i.filename.startswith(".")
                or stat.S_IFMT(i.external_attr >> 16) not in {0, stat.S_IFREG}
                or i.file_size > max(i.compress_size, 1) * 100
                for i in infos
            )
        ):
            raise ValueError("Unsafe public bundle")
        manifest = unique_json(archive.read("manifest.json"))
        if (
            not isinstance(manifest, dict)
            or set(manifest) != {"schema_version", "inputs"}
            or manifest["schema_version"] != "2.0"
            or not isinstance(manifest["inputs"], list)
            or len(manifest["inputs"]) != count
        ):
            raise ValueError("Invalid public bundle manifest")
        files, identifiers = {}, set()
        for entry in manifest["inputs"]:
            if (
                not isinstance(entry, dict)
                or set(entry)
                - {"id", "path", "kind", "required", "sha256", "correlates_to"}
                or entry.get("kind")
                not in {"junit-xml", "console-jsonl", "domain-observations-json"}
                or entry.get("required") is not True
                or not isinstance(entry.get("id"), str)
            ):
                raise ValueError("Unsupported public input metadata")
            path = entry.get("path")
            if (
                path not in names
                or path == "manifest.json"
                or path in files
                or entry["id"] in identifiers
            ):
                raise ValueError("Duplicate or missing public bundle member")
            content = archive.read(path)
            if digest(content) != entry.get("sha256"):
                raise ValueError("Inner artifact digest mismatch")
            files[path] = content
            identifiers.add(entry["id"])
        if set(files) != set(names) - {"manifest.json"}:
            raise ValueError("Unmanifested public artifact")
        return files


def load_inputs(root: Path) -> PublicManifest:
    value = PublicManifest.model_validate(
        unique_json(safe_read(root, "manifest.json", 4 * MAX_FILE))
    )
    for case in value.cases:
        for ref in [
            case.current,
            case.control,
            case.later,
            *(p.artifact for p in case.prior),
        ]:
            if ref is not None:
                read_input(root, ref)
    return value
