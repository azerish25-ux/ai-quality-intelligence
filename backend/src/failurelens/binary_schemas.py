"""Public contracts for safe binary inspection. Storage paths never cross this boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .schemas import ArtifactDerivativeSummary


class PixelMask(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    x: StrictInt = Field(ge=0)
    y: StrictInt = Field(ge=0)
    width: StrictInt = Field(gt=0)
    height: StrictInt = Field(gt=0)


class ScreenshotReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: StrictInt = Field(ge=0)
    reason: str = Field(min_length=10, max_length=1000)
    confirm_safe: Literal[True]
    masks: list[PixelMask] = Field(default_factory=list, max_length=64)


class BinaryDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: StrictInt = Field(ge=0)
    decision: Literal["reject", "revoke"]
    reason: str = Field(min_length=10, max_length=1000)


class BinaryDecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    version: int
    decision: str
    derivative_id: str | None
    actor_display: str
    reason: str
    masks: list[PixelMask]
    created_at: datetime


class BinaryEvidenceRead(BaseModel):
    input_id: str
    manifest_input_id: str
    project_id: str
    run_id: str
    kind: str
    path: str | None
    source_digest: str | None
    source_bytes: int | None
    source_status: str
    state: str
    version: int
    execution_id: str | None
    correlation: str
    relationship: str | None
    width: int | None
    height: int | None
    coordinate_system: str | None
    comparison_context: dict[str, Any]
    derivative: ArtifactDerivativeSummary | None
    warnings: list[str]
    decisions: list[BinaryDecisionRead]
    decisions_total: int
    original_policy: Literal[
        "not_retained; reviewer_resupplies_digest_bound_original"
    ] = "not_retained; reviewer_resupplies_digest_bound_original"


class BinaryEvidencePage(BaseModel):
    items: list[BinaryEvidenceRead]
    total: int
    offset: int
    limit: int


class ImageComparisonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_derivative_id: str
    actual_derivative_id: str


class ImageComparisonRead(BaseModel):
    status: Literal["COMPARABLE", "INCOMPATIBLE", "INSUFFICIENT_CONTEXT"]
    reasons: list[str]
    expected_derivative_id: str
    actual_derivative_id: str
    algorithm: Literal["dhash-64-v1"] = "dhash-64-v1"
    similarity: float | None
    hamming_distance: int | None
    advisory: str = "Perceptual similarity is not root-cause evidence. Masked pixels may increase similarity."
