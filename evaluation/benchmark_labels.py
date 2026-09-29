"""Evaluation-only ground truth schema. Never import this from runtime replay."""
from __future__ import annotations
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field


class BenchmarkCaseLabel(BaseModel):
    # Retained execution rows contain additional immutable oracle/provenance fields.
    model_config = ConfigDict(extra="allow", strict=True)
    case_id: Annotated[str, Field(pattern=r"^c-[0-9a-f]{20}$")]
    schema_version: Literal["2.0"]
    source_kind: Literal["synthetic", "ledgerguard_executed", "other_executed"]
    source_revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    scenario_family_id: Annotated[str, Field(min_length=1, max_length=200)]
    incident_id: Annotated[str, Field(min_length=1, max_length=200)]
    artifacts: Annotated[list[str], Field(min_length=1, max_length=8)]
    history_manifest: str | None
    expected_category: Literal["product_defect", "test_defect", "infrastructure_failure", "known_flake", "insufficient_evidence"]
    root_cause: str | None
    required_evidence: Annotated[list[str], Field(min_length=1, max_length=20)]
    forbidden_claims: Annotated[list[str], Field(max_length=40)]
    severity: Literal["critical", "high", "medium", "low"]
    observability_rationale: Annotated[str, Field(min_length=1, max_length=4000)]
    oracle: Annotated[str, Field(min_length=1, max_length=4000)]
    adversarial_tags: Annotated[list[str], Field(max_length=40)]
    label_provenance: Annotated[str, Field(min_length=1, max_length=4000)]
    label_review_status: Literal["automated", "agent-reviewed", "human-reviewed"]
    split: Literal["development", "calibration", "test"]
