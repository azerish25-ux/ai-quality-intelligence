"""Strict, answer-free input contract shared by the replay command and its tests."""
from __future__ import annotations
import hashlib
import json
import io
import stat
import zipfile
from pathlib import Path, PurePosixPath
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal

class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role: Literal["control", "observation"]
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(gt=0, le=1024 * 1024)
    source_format: Literal["junit-xml", "failurelens-bundle-v2"] = "junit-xml"
    expected_inputs: int = Field(default=1, ge=1, le=16)

    @field_validator("path")
    @classmethod
    def relative(cls, value: str) -> str:
        p = PurePosixPath(value)
        if p.is_absolute() or ".." in p.parts or "\\" in value or str(p) != value or len(p.parts) != 2 or not value.endswith((".xml", ".zip")):
            raise ValueError("unsafe artifact path")
        return value

class ReplayCase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: str = Field(pattern=r"^c-[0-9a-f]{20}$")
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    inputs: list[ArtifactRef] = Field(min_length=2, max_length=2)

class ReplayManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["artifact-replay-v1", "artifact-replay-v2"]
    cases: list[ReplayCase] = Field(min_length=1, max_length=1000)


def read_artifact(root: Path, ref: ArtifactRef) -> bytes:
    path = root / ref.path
    if any(p.is_symlink() for p in (path, path.parent)) or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("artifact escapes input directory")
    with path.open("rb") as handle:
        content = handle.read(1024 * 1024 + 1)
    if len(content) != ref.bytes or hashlib.sha256(content).hexdigest() != ref.sha256:
        raise ValueError("artifact byte count or digest differs from the frozen manifest")
    return content


def load_manifest(root: Path) -> ReplayManifest:
    path = root / "manifest.json"
    if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("unsafe or oversized replay manifest")
    manifest = ReplayManifest.model_validate(json.loads(path.read_bytes()))
    ids, paths = set(), set()
    for case in manifest.cases:
        if case.case_id in ids or {ref.role for ref in case.inputs} != {"control", "observation"}:
            raise ValueError("duplicate case or invalid control/observation pair")
        ids.add(case.case_id)
        for ref in case.inputs:
            if manifest.schema_version == "artifact-replay-v1":
                if ref.source_format != "junit-xml" or not ref.path.endswith(".xml") or ref.expected_inputs != 1:
                    raise ValueError("v1 requires standalone XML inputs")
            elif ref.source_format != "failurelens-bundle-v2" or not ref.path.endswith(".zip") or ref.expected_inputs < 2:
                raise ValueError("v2 requires multi-artifact bundles")
            if ref.path in paths or not ref.path.startswith(case.case_id + "/"):
                raise ValueError("duplicate artifact or wrong case directory")
            paths.add(ref.path)
            content = read_artifact(root, ref)
            if manifest.schema_version == "artifact-replay-v2":
                validate_public_bundle(content, ref.expected_inputs)
    return manifest


def validate_public_bundle(content: bytes, expected_inputs: int) -> dict[str, bytes]:
    """Strict replay view: no labels, arbitrary ZIP members or hidden metadata."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        if (len(infos) != expected_inputs + 1 or len(names) != len(set(names))
                or "manifest.json" not in names or sum(i.file_size for i in infos) > 1024 * 1024
                or any(i.file_size > 256 * 1024 or i.flag_bits & 1
                       or stat.S_ISLNK(i.external_attr >> 16)
                       or (stat.S_IFMT(i.external_attr >> 16) not in (0, stat.S_IFREG))
                       or "/" in i.filename or "\\" in i.filename or i.filename.startswith(".")
                       for i in infos)):
            raise ValueError("Unsafe replay bundle")
        manifest = json.loads(archive.read("manifest.json"))
        if set(manifest) != {"schema_version", "inputs"} or manifest["schema_version"] != "2.0":
            raise ValueError("Replay bundle cannot include private metadata")
        entries = manifest["inputs"]
        if not isinstance(entries, list) or len(entries) != expected_inputs:
            raise ValueError("Replay bundle input count differs")
        paths, ids = set(), set()
        result = {}
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) - {"id","path","kind","required","sha256","role","correlates_to"}:
                raise ValueError("Unsupported replay input metadata")
            if entry.get("kind") not in {"junit-xml", "transaction-observations-json", "console-jsonl"} or entry.get("required") is not True:
                raise ValueError("Unsupported replay input kind or requirement")
            path, identifier = entry.get("path"), entry.get("id")
            if (not isinstance(path,str) or path not in names or path == "manifest.json" or path in paths
                    or not isinstance(identifier,str) or identifier in ids):
                raise ValueError("Repeated or missing replay input")
            data = archive.read(path)
            if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
                raise ValueError("Replay inner artifact digest mismatch")
            result[path] = data
            paths.add(path); ids.add(identifier)
        if paths != set(names) - {"manifest.json"}:
            raise ValueError("Undeclared replay artifact")
        return result
