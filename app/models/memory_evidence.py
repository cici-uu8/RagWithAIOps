"""L0 raw evidence models for reviewed oncall memory."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator, field_validator


class EvidenceRefType(StrEnum):
    """Kinds of raw evidence refs stored outside SQLite."""

    FINAL_RESPONSE = "final_response"
    PAST_STEPS = "past_steps"
    KEY_EVENTS = "key_events"
    TOOL_RESULTS = "tool_results"
    MEMORY_OBSERVATION = "memory_observation"


class EvidenceRef(BaseModel):
    """Pointer to a raw evidence artifact on disk."""

    ref_id: str
    evidence_id: str
    ref_type: EvidenceRefType
    path: str
    sha256: str
    size_bytes: int
    created_at: datetime = Field(default_factory=datetime.now)

    @field_validator("ref_id", "evidence_id", "path", "sha256")
    @classmethod
    def _require_text(cls, value: str) -> str:
        if not str(value).strip():
            raise ValueError("value is required")
        return str(value).strip()

    @field_validator("size_bytes")
    @classmethod
    def _require_size(cls, value: int) -> int:
        if value < 0:
            raise ValueError("size_bytes must be non-negative")
        return value


class L0Evidence(BaseModel):
    """Immutable raw evidence captured from a completed diagnosis."""

    evidence_id: str
    session_id: str
    owner_id: str = "default"
    source_type: Literal["aiops_diagnosis"] = "aiops_diagnosis"
    query: str
    service: Optional[str] = None
    alert_name: Optional[str] = None
    environment: Optional[str] = None
    final_response_preview: str
    final_response_ref: Optional[EvidenceRef] = None
    plan_json: str
    past_steps_ref: Optional[EvidenceRef] = None
    key_events_ref: Optional[EvidenceRef] = None
    tool_results_ref: Optional[EvidenceRef] = None
    memory_observation_json: Optional[str] = None
    diagnosis_status: Literal["complete", "partial", "failed"] = "complete"
    created_at: datetime = Field(default_factory=datetime.now)
    evidence_size_bytes: int = 0
    refs_manifest_json: str = Field(default='{"refs":[]}')

    @field_validator("evidence_id", "session_id", "owner_id", "query", "plan_json", "final_response_preview")
    @classmethod
    def _require_text(cls, value: str) -> str:
        if not str(value).strip():
            raise ValueError("value is required")
        return str(value).strip()

    @field_validator("evidence_size_bytes")
    @classmethod
    def _require_size(cls, value: int) -> int:
        if value < 0:
            raise ValueError("evidence_size_bytes must be non-negative")
        return value

    @model_validator(mode="after")
    def validate_evidence_contract(self) -> "L0Evidence":
        if self.final_response_ref is not None and self.final_response_ref.evidence_id != self.evidence_id:
            raise ValueError("final_response_ref must point to the same evidence_id")
        for ref_name in ("past_steps_ref", "key_events_ref", "tool_results_ref"):
            ref = getattr(self, ref_name)
            if ref is not None and ref.evidence_id != self.evidence_id:
                raise ValueError(f"{ref_name} must point to the same evidence_id")
        if self.refs_manifest_json and self.refs_manifest_json.strip():
            try:
                import json

                manifest = json.loads(self.refs_manifest_json)
            except Exception as exc:  # pragma: no cover - defensive validation
                raise ValueError("refs_manifest_json must be valid JSON") from exc
            if not isinstance(manifest, dict) or "refs" not in manifest:
                raise ValueError("refs_manifest_json must contain refs")
        return self
