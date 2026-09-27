from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import Category, IngestionState, Outcome, RunStatus


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
    parameterization: str | None = Field(default=None, max_length=512)
    browser: str | None = None
    attempt: int = Field(default=0, ge=0)
    outcome: Outcome
    duration_ms: float | None = Field(default=None, ge=0)
    message: str | None = None
    exception_type: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class RunMetadata(BaseModel):
    external_id: str = Field(min_length=1, max_length=240)
    attempt: int = Field(default=1, ge=1)
    repository: str | None = Field(default=None, max_length=240)
    commit_sha: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{7,64}$")
    base_sha: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{7,64}$")
    branch: str | None = Field(default=None, max_length=240)
    framework: str = Field(default="auto", min_length=1, max_length=64)
    run_scope: Literal["full_suite", "impact_selected", "unknown"] = "unknown"
    comparison_trust: Literal[
        "self_reported", "authenticated_lookup", "trusted_workflow"
    ] = "self_reported"
    environment: str | None = Field(default=None, max_length=160)
    timezone: str | None = Field(default=None, max_length=80)
    worker_count: int | None = Field(default=None, ge=1, le=100_000)
    shard_count: int | None = Field(default=None, ge=1, le=100_000)
    expected_inputs: int | None = Field(default=None, ge=0)
    source_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone: {value}") from exc
        return value


class IngestionRequest(RunMetadata):
    schema_version: Literal["1.0"] = "1.0"
    framework: str = "normalized"
    observations: list[TestObservation] = Field(min_length=1, max_length=20_000)


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    external_id: str
    attempt: int
    repository: str | None
    commit_sha: str | None
    base_sha: str | None
    branch: str | None
    framework: str
    run_scope: str
    environment: str | None
    timezone: str | None
    worker_count: int | None
    shard_count: int | None
    status: RunStatus
    completeness: str
    expected_inputs: int | None
    received_inputs: int
    manifest_digest: str
    source_metadata: dict[str, Any]
    created_at: datetime


class RunInputRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    run_id: str
    input_id: str
    kind: str
    path: str | None
    required: bool
    status: str
    digest: str | None
    size_bytes: int | None
    media_type: str
    parser_version: str | None
    warnings: list[str]
    metadata_json: dict[str, Any]
    created_at: datetime


class ArtifactDerivativeSummary(BaseModel):
    id: str
    kind: str
    digest: str
    media_type: str
    size_bytes: int
    redaction_version: str
    approved: bool
    restricted: bool
    approval_state: str
    retention_state: str


class EvidenceRead(BaseModel):
    id: str
    project_id: str
    run_id: str
    run_input_id: str | None
    execution_id: str | None
    derivative_id: str | None
    kind: str
    provenance_kind: str
    locator_version: str
    locator: dict[str, Any]
    excerpt: str
    observation: dict[str, Any]
    content_digest: str
    parser_version: str
    extractor_version: str
    redaction_version: str
    warnings: list[str]
    derivative: ArtifactDerivativeSummary


class IngestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    external_id: str
    attempt: int
    repository: str | None
    commit_sha: str | None
    base_sha: str | None
    branch: str | None
    source_format: str
    source_metadata: dict[str, Any]
    original_name: str
    media_type: str
    source_digest: str
    source_size_bytes: int
    expected_inputs: int | None
    received_inputs: int
    state: IngestionState
    run_id: str | None
    job_id: str | None
    parser_version: str | None
    policy_version: str
    diagnostics: list[dict[str, Any]]
    error_code: str | None
    error_message: str | None
    retry_count: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class HistoryRate(BaseModel):
    numerator: int
    denominator: int
    value: float | None
    interval_95: list[float] | None
    status: str
    minimum_support: int
    definition: str


class HistoryObservationRead(BaseModel):
    run_id: str
    external_id: str
    commit_sha: str | None
    branch: str | None
    browser: str | None
    environment: str | None
    run_scope: str
    run_completeness: str
    timezone: str | None
    worker_count: int | None
    shard_count: int | None
    time_bucket: str
    observed_at: datetime
    first_outcome: str
    final_outcome: str
    attempt_count: int
    attempt_numbers: list[int]
    execution_ids: list[str]
    first_execution_id: str
    final_execution_id: str
    retry_recovered: bool
    duration_ms: float | None
    duplicate_attempt_numbers: bool


class TestHistoryRead(BaseModel):
    policy_version: str
    history_input_digest: str
    status: str
    logical_test: dict[str, Any]
    window: dict[str, Any]
    filters: dict[str, Any]
    sample_sizes: dict[str, int]
    outcomes: dict[str, dict[str, int]]
    rates: dict[str, HistoryRate]
    breakdowns: dict[str, list[dict[str, Any]]]
    sequences: dict[str, Any]
    review: dict[str, Any]
    safety: dict[str, Any]
    pagination: dict[str, int]
    observations: list[HistoryObservationRead]


class ImpactTestCreate(BaseModel):
    test_key: str = Field(min_length=1, max_length=240)
    test_identity: str = Field(min_length=1, max_length=512)
    source_path: str | None = Field(default=None, max_length=1024)
    criticality: Literal["normal", "high", "critical"] = "normal"
    mandatory: bool = False
    tags: list[str] = Field(default_factory=list, max_length=40)
    estimated_duration_ms: float | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImpactMappingEdgeCreate(BaseModel):
    source_path: str = Field(min_length=1, max_length=1024)
    target_type: Literal["test", "file"]
    target_value: str = Field(min_length=1, max_length=1024)
    kind: Literal[
        "file_to_test",
        "coverage",
        "api_ownership",
        "ownership",
        "historical_failure",
        "dependency",
    ]
    confidence: float = Field(ge=0, le=1)
    mapping_source: str = Field(min_length=1, max_length=120)
    mapping_version: str = Field(min_length=1, max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImpactMappingSnapshotCreate(BaseModel):
    version: str = Field(min_length=1, max_length=80)
    policy_version: str = Field(default="impact-policy-v1", min_length=1, max_length=80)
    trusted: bool = False
    coverage_complete: bool = False
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    tests: list[ImpactTestCreate] = Field(min_length=1, max_length=20_000)
    edges: list[ImpactMappingEdgeCreate] = Field(default_factory=list, max_length=200_000)


class ImpactMappingSnapshotRead(BaseModel):
    id: str
    project_id: str
    version: str
    policy_version: str
    source_digest: str
    trusted: bool
    coverage_complete: bool
    source_metadata: dict[str, Any]
    test_count: int
    edge_count: int
    created_at: datetime


class ImpactRecommendationCreate(BaseModel):
    run_id: str = Field(min_length=1, max_length=36)
    mapping_snapshot_id: str = Field(min_length=1, max_length=36)
    changed_input_id: str | None = Field(default=None, min_length=1, max_length=36)
    base_sha: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{7,64}$")
    head_sha: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{7,64}$")


class ImpactOverrideCreate(BaseModel):
    actor: str = Field(min_length=1, max_length=240)
    action: Literal["include", "exclude"]
    test_key: str = Field(min_length=1, max_length=240)
    reason: str = Field(min_length=3, max_length=5000)
    expected_revision: int = Field(ge=0)


class ImpactOverrideRead(BaseModel):
    id: str
    actor: str
    action: str
    test_key: str
    reason: str
    revision_before: int
    revision_after: int
    created_at: datetime


class ImpactRecommendationItemRead(BaseModel):
    id: str
    test_key: str
    test_identity: str
    source_path: str | None
    criticality: str
    mandatory: bool
    base_selected: bool
    effective_selected: bool
    selection_source: str
    rank: int | None
    score: float
    confidence: str
    reason_codes: list[str]
    reasons: list[dict[str, Any]]
    mapping_edge_ids: list[str]
    exclusion_reason: str | None


class ImpactRecommendationRead(BaseModel):
    id: str
    project_id: str
    run_id: str
    changed_input_id: str
    mapping_snapshot_id: str
    base_sha: str | None
    head_sha: str | None
    input_digest: str
    changed_files_digest: str
    engine_version: str
    policy_version: str
    status: str
    current_revision: int
    comparison_trusted: bool
    mapping_complete: bool
    full_suite_required: bool
    summary: str
    changed_files: list[dict[str, Any]]
    safety_reasons: list[str]
    metrics: dict[str, Any]
    selected_tests: list[ImpactRecommendationItemRead]
    excluded_tests: list[ImpactRecommendationItemRead]
    overrides: list[ImpactOverrideRead]
    created_at: datetime
    updated_at: datetime


class PerformancePolicyCreate(BaseModel):
    version: str = Field(default="performance-policy-v1", min_length=1, max_length=80)
    relative_tolerance: float = Field(default=0.10, ge=0, le=10)
    absolute_tolerance: float = Field(default=0.0, ge=0)
    min_baseline_runs: int = Field(default=3, ge=1, le=10_000)
    max_baseline_age_days: int = Field(default=30, ge=1, le=3650)
    require_trusted: bool = True
    required_dimensions: list[str] = Field(
        default_factory=lambda: [
            "repository",
            "workload",
            "environment",
            "browser",
            "run_scope",
            "producer",
            "producer_version",
            "load_profile",
            "region",
            "executor",
        ],
        min_length=1,
        max_length=40,
    )
    direction_overrides: dict[str, Literal["lower_is_better", "higher_is_better", "neutral"]] = Field(
        default_factory=dict
    )

    @field_validator("required_dimensions")
    @classmethod
    def normalize_dimensions(cls, value: list[str]) -> list[str]:
        normalized = sorted({item.strip() for item in value if item.strip()})
        if not normalized:
            raise ValueError("at least one compatibility dimension is required")
        if any(len(item) > 80 for item in normalized):
            raise ValueError("compatibility dimension names must be at most 80 characters")
        return normalized


class PerformancePolicyRead(PerformancePolicyCreate):
    id: str
    project_id: str
    created_at: datetime


class PerformanceObservationRead(BaseModel):
    id: str
    project_id: str
    run_id: str
    run_input_id: str | None
    execution_id: str | None
    evidence_id: str
    metric_key: str
    metric_name: str
    metric_scope: str
    statistic: str
    direction: str
    original_value: float
    original_unit: str
    canonical_value: float
    canonical_unit: str
    sample_count: int | None
    producer: str
    producer_version: str | None
    workload: str
    dimension_signature: str
    dimensions: dict[str, Any]
    threshold_status: str
    threshold_details: dict[str, Any]
    source_digest: str
    source_locator: dict[str, Any]
    observed_at: datetime
    created_at: datetime


class PerformanceBaselineCreate(BaseModel):
    current_observation_id: str = Field(min_length=1, max_length=36)
    policy_id: str | None = Field(default=None, min_length=1, max_length=36)


class PerformanceBaselineMemberRead(BaseModel):
    observation_id: str
    run_id: str
    evidence_id: str
    external_id: str
    commit_sha: str | None
    observed_at: datetime
    canonical_value: float
    canonical_unit: str
    sample_count: int | None
    position: int


class PerformanceBaselineRead(BaseModel):
    id: str
    project_id: str
    current_run_id: str
    current_observation_id: str
    policy_id: str
    input_digest: str
    status: str
    cutoff_at: datetime
    cohort_dimensions: dict[str, Any]
    compatibility: dict[str, Any]
    rejected_candidates: list[dict[str, Any]]
    run_count: int
    sample_count: int
    baseline_value: float | None
    baseline_min: float | None
    baseline_max: float | None
    baseline_mad: float | None
    baseline_age_seconds: float | None
    aggregation: str
    members: list[PerformanceBaselineMemberRead]
    created_at: datetime


class PerformanceComparisonCreate(BaseModel):
    policy_id: str | None = Field(default=None, min_length=1, max_length=36)
    observation_ids: list[str] = Field(default_factory=list, max_length=5000)


class PerformanceComparisonRead(BaseModel):
    id: str
    project_id: str
    current_run_id: str
    current_observation_id: str
    baseline_snapshot_id: str
    policy_id: str
    engine_version: str
    input_digest: str
    status: str
    metric_name: str
    metric_scope: str
    statistic: str
    direction: str
    workload: str
    canonical_unit: str
    current_value: float
    baseline_value: float | None
    absolute_change: float | None
    relative_change: float | None
    allowed_absolute_change: float
    allowed_relative_change: float
    current_sample_count: int | None
    baseline_run_count: int
    baseline_sample_count: int
    threshold_status: str
    effect_size: float | None
    uncertainty: dict[str, Any]
    compatibility: dict[str, Any]
    confounders: list[str]
    current_evidence_id: str
    baseline_evidence_ids: list[str]
    next_measurement: str
    summary: str
    baseline: PerformanceBaselineRead
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
    validation_version: str | None = None
    validation_results: dict[str, Any] | None = None


class ReviewCreate(BaseModel):
    actor: str = Field(min_length=1, max_length=240)
    decision: Literal["accept", "reject", "needs_more_evidence", "category_correction"]
    proposed_category: Category | None = None
    reason: str = Field(min_length=3, max_length=5000)
    expected_version: int = Field(ge=0)


class ClusterMemberRead(BaseModel):
    failure_id: str
    run_id: str
    test_identity: str
    message: str
    exception_type: str | None
    role: str
    similarity_score: float | None
    score_components: dict[str, float]
    matching_signals: list[str]
    conflicting_signals: list[str]
    candidate_reasons: list[str]
    assignment_kind: str


class ClusterRevisionRead(BaseModel):
    id: str
    cluster_id: str
    revision: int
    reason: str
    algorithm_version: str
    feature_version: str
    representative_failure_id: str | None
    member_count: int
    score_summary: dict[str, Any]
    uncertainty_flags: list[str]
    created_at: datetime
    memberships: list[ClusterMemberRead] = Field(default_factory=list)


class ClusterDecisionRead(BaseModel):
    id: str
    cluster_id: str
    actor: str
    decision: str
    reason: str
    failure_ids: list[str]
    target_cluster_id: str | None
    revision_before: int
    revision_after: int
    created_at: datetime


class ClusterSummary(BaseModel):
    id: str
    project_id: str
    cluster_key: str
    algorithm_version: str
    feature_version: str
    current_revision: int
    representative_failure_id: str | None
    representative_test_identity: str | None
    member_count: int
    uncertainty: str
    status: str
    superseded_by_cluster_id: str | None
    created_at: datetime
    updated_at: datetime


class ClusterDetail(ClusterSummary):
    current: ClusterRevisionRead | None
    decisions: list[ClusterDecisionRead] = Field(default_factory=list)


class ClusterReviewCreate(BaseModel):
    actor: str = Field(min_length=1, max_length=240)
    decision: Literal["confirm", "split", "merge"]
    reason: str = Field(min_length=3, max_length=5000)
    expected_revision: int = Field(ge=1)
    failure_ids: list[str] = Field(default_factory=list, max_length=1000)
    target_cluster_id: str | None = None
