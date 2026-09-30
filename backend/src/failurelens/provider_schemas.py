"""Secret-free HTTP contracts for the optional provider workflow."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .providers import Proposal


class ProviderSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    analysis_revision: int = Field(ge=1)
    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    configuration_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=200)


class ProviderDestination(BaseModel):
    provider_identity: str
    endpoint: str
    model: str


class ProviderLimits(BaseModel):
    max_attempts: int
    max_output_tokens: int
    max_context_bytes: int
    max_response_bytes: int
    max_run_requests: int
    max_run_reserved_tokens: int
    concurrency: int
    min_interval_seconds: float
    timeout_seconds: float


class ProviderPricing(BaseModel):
    input_price_per_million: float | None
    output_price_per_million: float | None
    source: str | None
    date: str | None
    currency: str | None


class ProviderStatus(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    availability: Literal[
        "ready",
        "disabled",
        "invalid_configuration",
        "project_not_allowed",
        "evidence_unavailable",
        "rate_limited",
        "circuit_open",
        "recovery_required",
        "worker_unavailable",
        "concurrency_limited",
        "run_budget_exhausted",
    ]
    reason: str | None
    can_submit: bool
    configuration_digest: str | None
    destination: ProviderDestination | None
    limits: ProviderLimits | None
    pricing: ProviderPricing | None
    cost_status: Literal["unknown", "estimate_available"]
    notice: str
    admission: "ProviderAdmissionRead | None" = None


class ProviderAdmissionRead(BaseModel):
    active_permits: int
    concurrency: int
    next_allowed_at: datetime | None
    circuit_open_until: datetime | None
    recovery_required: bool
    worker_available: bool


class ProviderEvidence(BaseModel):
    id: str
    excerpt: str


class ProviderPreview(ProviderStatus):
    project_id: str
    run_id: str
    analysis_id: str
    analysis_revision: int
    analysis_digest: str | None
    evidence_digest: str | None
    preview_digest: str | None
    prompt_version: str
    evidence: list[ProviderEvidence]
    reserved_tokens_per_attempt: int | None
    budget: "ProviderBudgetRead | None" = None


class ProviderUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int


class ProviderAttemptRead(BaseModel):
    number: int
    status: str
    reason: str | None
    http_status: int | None
    reserved_tokens: int
    accounted_tokens: int
    spend_status: str
    usage: ProviderUsage | None
    estimated_cost: float | None
    cost_status: str
    pricing: ProviderPricing
    transport_terminated: bool


class ProviderBudgetRead(BaseModel):
    requests: int
    reserved_tokens: int
    max_requests: int
    max_reserved_tokens: int


class ProviderInvocationRead(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    analysis_id: str
    status: str
    deterministic_category: str
    proposal: Proposal | None
    reason: str | None
    usage: ProviderUsage | None
    estimated_cost: float | None
    cost_status: str
    known_estimated_cost: float | None
    cost_complete: bool
    prompt_version: str
    validation_status: str
    invocation_id: str
    invocation_state: str
    usage_complete: bool
    attempts: list[ProviderAttemptRead]
    budget: ProviderBudgetRead
    job_id: str | None
    analysis_revision: int
    analysis_digest: str
    evidence_digest: str
    configuration_digest: str
    preview_digest: str | None
    created_at: datetime
    completed_at: datetime | None
    cancel_requested_at: datetime | None
    recovery_required: bool


class ProviderInvocationList(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    items: list[ProviderInvocationRead]
    limit: int = 50
    truncated: bool
