"""Durable oncall memory domain models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, model_validator

from app.models.memory_atom import L1Atom
from app.models.memory_scenario import L2ScenarioPayload


class MemoryStatus(StrEnum):
    """Lifecycle status for durable oncall memory records."""

    ACTIVE = "active"
    CANDIDATE = "candidate"
    CONFLICT = "conflict"
    STALE_SUSPECT = "stale_suspect"
    SUPERSEDED = "superseded"
    DEPRECATED = "deprecated"


class MemoryReviewDecision(StrEnum):
    """Operator review decision for a memory candidate."""

    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    DEPRECATED = "deprecated"


class MemoryType(StrEnum):
    """Supported durable memory payload kinds."""

    ALERT_PATTERN = "alert_pattern"
    PLAN_TEMPLATE = "plan_template"
    PREFERENCE = "preference"
    RUNTIME_CONTEXT = "runtime_context"
    CANDIDATE_SUMMARY = "candidate_summary"
    L1_ATOM = "l1_atom"
    L2_SCENARIO = "l2_scenario"


class AlertPatternPayload(BaseModel):
    """Alert pattern -> root cause -> fix memory payload."""

    alert_name: str
    service: Optional[str] = None
    severity: Optional[str] = None
    signal_keys: List[str] = Field(default_factory=list)
    metric_patterns: List[str] = Field(default_factory=list)
    log_patterns: List[str] = Field(default_factory=list)
    root_cause: str
    fix: Optional[str] = None
    evidence_refs: List[Dict[str, Any]] = Field(default_factory=list)


class PlanTemplatePayload(BaseModel):
    """Successful diagnosis plan template payload."""

    alert_type: str
    plan_steps: List[str] = Field(default_factory=list)
    tool_hints: List[Dict[str, Any]] = Field(default_factory=list)
    success_criteria: List[str] = Field(default_factory=list)
    stop_conditions: List[str] = Field(default_factory=list)
    evidence_refs: List[Dict[str, Any]] = Field(default_factory=list)


class PreferencePayload(BaseModel):
    """Runtime preference payload."""

    preference_scope: str
    preference: str
    applies_to: List[str] = Field(default_factory=list)
    source_event: Dict[str, Any]


class RuntimeContextPayload(BaseModel):
    """Non-document runtime context payload."""

    context_key: str
    context_value: str
    expires_at: Optional[datetime] = None
    evidence_refs: List[Dict[str, Any]] = Field(default_factory=list)


class CandidateSummaryPayload(BaseModel):
    """Reviewed-later summary extracted from a session candidate."""

    candidate_kind: str
    summary: str
    evidence_refs: List[Dict[str, Any]] = Field(default_factory=list)


class MemoryReview(BaseModel):
    """Auditable operator decision attached to reviewed memory records."""

    decision: MemoryReviewDecision
    reviewer_id: str
    decision_note: str
    previous_status: MemoryStatus
    decision_source: str = "operator-workflow"
    reviewed_at: datetime = Field(default_factory=datetime.now)

    @model_validator(mode="after")
    def validate_review_contract(self) -> "MemoryReview":
        if not self.reviewer_id.strip():
            raise ValueError("reviewer_id is required")
        if not self.decision_note.strip():
            raise ValueError("decision_note is required")
        if not self.decision_source.strip():
            raise ValueError("decision_source is required")
        return self


MemoryPayload = Union[
    AlertPatternPayload,
    PlanTemplatePayload,
    PreferencePayload,
    RuntimeContextPayload,
    CandidateSummaryPayload,
    L1Atom,
    L2ScenarioPayload,
]


class MemoryRecord(BaseModel):
    """Source-of-truth durable oncall memory record."""

    memory_id: str
    schema_version: int = 1
    owner_id: str = "default"
    namespace: str
    memory_type: MemoryType
    content: str
    summary: str
    payload: MemoryPayload
    source: str
    evidence: Dict[str, Any]
    status: MemoryStatus
    review: Optional[MemoryReview] = None
    candidate_review_deadline: Optional[datetime] = None
    tags: List[str] = Field(default_factory=list)
    last_accessed_at: Optional[datetime] = None
    access_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @model_validator(mode="after")
    def validate_memory_contract(self) -> "MemoryRecord":
        if self.schema_version != 1:
            raise ValueError("schema_version must be 1")
        if not self.owner_id.strip():
            raise ValueError("owner_id is required")
        if not self.namespace.strip():
            raise ValueError("namespace is required")
        if not self.content.strip():
            raise ValueError("content is required")
        if not self.summary.strip():
            raise ValueError("summary is required")
        if not self.source.strip():
            raise ValueError("source is required")
        if not self.evidence:
            raise ValueError("evidence is required")
        if "raw_messages" in self.evidence or "raw_memory_saver_history" in self.evidence:
            raise ValueError("raw MemorySaver history must not be stored as durable memory evidence")
        if self.access_count < 0:
            raise ValueError("access_count must be non-negative")

        expected_payload_type = {
            MemoryType.ALERT_PATTERN: AlertPatternPayload,
            MemoryType.PLAN_TEMPLATE: PlanTemplatePayload,
            MemoryType.PREFERENCE: PreferencePayload,
            MemoryType.RUNTIME_CONTEXT: RuntimeContextPayload,
            MemoryType.CANDIDATE_SUMMARY: CandidateSummaryPayload,
            MemoryType.L1_ATOM: L1Atom,
            MemoryType.L2_SCENARIO: L2ScenarioPayload,
        }[self.memory_type]
        if not isinstance(self.payload, expected_payload_type):
            raise ValueError(f"payload must match memory_type {self.memory_type}")
        return self
