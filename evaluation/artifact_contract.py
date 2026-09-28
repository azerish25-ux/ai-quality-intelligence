"""Strict, answer-free input contract shared by the replay command and its tests."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path, PurePosixPath
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal

class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role: Literal["control", "observation"]
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(gt=0, le=1024 * 1024)

    @field_validator("path")
    @classmethod
    def relative(cls, value: str) -> str:
        p = PurePosixPath(value)
        if p.is_absolute() or ".." in p.parts or "\\" in value or str(p) != value or len(p.parts) != 2 or not value.endswith(".xml"):
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
    schema_version: Literal["artifact-replay-v1"]
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
            if ref.path in paths or not ref.path.startswith(case.case_id + "/"):
                raise ValueError("duplicate artifact or wrong case directory")
            paths.add(ref.path)
            read_artifact(root, ref)
    return manifest
