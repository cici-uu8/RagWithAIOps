"""L1 atom candidate models for reviewed oncall memory."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class L1AtomType(StrEnum):
    """Supported P7.2 oncall atom types."""

    ROOT_CAUSE_OBSERVATION = "root_cause_observation"
    CHECK_OBSERVATION = "check_observation"
    REMEDIATION_OBSERVATION = "remediation_observation"
    NEGATIVE_OBSERVATION = "negative_observation"
    CONFIG_OR_DEPLOY_CHANGE = "config_or_deploy_change"


class L1AtomExtractionMethod(StrEnum):
    """How an L1 atom candidate was extracted."""

    SCHEMA_LLM_V1 = "schema_llm_v1"
    RULE_V1 = "rule_v1"
    MANUAL = "manual"


class L1Atom(BaseModel):
    """One traceable atomic memory candidate derived from L0 evidence."""

    atom_id: str
    owner_id: str = "default"
    evidence_id: str
    atom_type: L1AtomType
    service: Optional[str] = None
    alert_name: Optional[str] = None
    environment: Optional[str] = None
    claim: str
    root_cause: Optional[str] = None
    check_name: Optional[str] = None
    remediation: Optional[str] = None
    negates_memory_id: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence_refs: list[str] = Field(default_factory=list)
    extraction_method: L1AtomExtractionMethod = L1AtomExtractionMethod.SCHEMA_LLM_V1
    status: Literal["candidate"] = "candidate"
    created_at: datetime = Field(default_factory=datetime.now)

    @field_validator("atom_id", "owner_id", "evidence_id", "claim")
    @classmethod
    def _require_text(cls, value: str) -> str:
        if not str(value).strip():
            raise ValueError("value is required")
        return str(value).strip()

    @field_validator("service", "alert_name", "environment", "root_cause", "check_name", "remediation", "negates_memory_id")
    @classmethod
    def _optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = str(value).strip()
        return stripped or None

    @field_validator("evidence_refs")
    @classmethod
    def _require_evidence_refs(cls, value: list[str]) -> list[str]:
        refs = [str(item).strip() for item in value if str(item).strip()]
        if not refs:
            raise ValueError("evidence_refs is required")
        return refs

    @model_validator(mode="after")
    def validate_atom_contract(self) -> "L1Atom":
        if self.evidence_id not in self.evidence_refs:
            raise ValueError("evidence_refs must include evidence_id")
        if self.atom_type in {
            L1AtomType.ROOT_CAUSE_OBSERVATION,
            L1AtomType.NEGATIVE_OBSERVATION,
        } and not (self.service or self.alert_name):
            raise ValueError("root_cause_observation and negative_observation require service or alert_name")
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until must not be earlier than valid_from")
        return self
