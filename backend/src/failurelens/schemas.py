from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import Category, Outcome, RunStatus


class ProjectCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,118}[a-z0-9]$")
    name: str = Field(min_length=1, max_length=240)


class ProjectRead(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime


class TestObservation(BaseModel):
    test_identity: str = Field(min_length=1, max_length=512)
    suite: str | None = None
    source_path: str | None = None
    browser: str | None = None
    attempt: int = Field(default=0, ge=0)
    outcome: Outcome
    duration_ms: float | None = Field(default=None, ge=0)
    message: str | None = None
    exception_type: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class IngestionRequest(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    external_id: str = Field(min_length=1, max_length=240)
    attempt: int = Field(default=1, ge=1)
    repository: str | None = None
    commit_sha: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{7,64}$")
    base_sha: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{7,64}$")
    branch: str | None = None
    framework: str = "normalized"
    expected_inputs: int | None = Field(default=None, ge=0)
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    observations: list[TestObservation] = Field(min_length=1, max_length=20_000)


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    external_id: str
    attempt: int
    repository: str | None
    commit_sha: str | None
    branch: str | None
    framework: str
    status: RunStatus
    completeness: str
    expected_inputs: int | None
    received_inputs: int
    manifest_digest: str
    created_at: datetime


class Confidence(BaseModel):
    value: float | None
    kind: str
    explanation: str


class AnalysisResult(BaseModel):
    analysis_id: str
    analysis_version: str
    failure_id: str
    run_id: str
    category: Category
    severity: str
    confidence: Confidence
    evidence_completeness: str
    summary: str
    claims: list[dict[str, Any]]
    supporting_evidence_ids: list[str]
    contradictory_evidence_ids: list[str]
    missing_evidence: list[str]
    hypotheses: list[dict[str, Any]]
    similar_failures: list[dict[str, Any]] = Field(default_factory=list)
    suspected_changes: list[dict[str, Any]] = Field(default_factory=list)
    next_investigation: list[dict[str, Any]]
    abstention_reason: str | None
    policy_flags: list[str]
    provenance: dict[str, Any]


class ReviewCreate(BaseModel):
    actor: str = Field(min_length=1, max_length=240)
    decision: Literal["accept", "reject", "needs_more_evidence", "category_correction"]
    proposed_category: Category | None = None
    reason: str = Field(min_length=3, max_length=5000)
    expected_version: int = Field(ge=0)
