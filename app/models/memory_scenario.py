"""L2 scenario memory models for reviewed oncall memory."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class L2ScenarioPayload(BaseModel):
    """Traceable L2 scenario payload built from stable L1 atoms."""

    scenario_key: str
    scenario_title: str
    service: Optional[str] = None
    alert_name: Optional[str] = None
    environment: Optional[str] = None
    applicable_conditions: list[str] = Field(default_factory=list)
    diagnostic_path: list[str] = Field(default_factory=list)
    common_root_causes: list[str] = Field(default_factory=list)
    remediation_steps: list[str] = Field(default_factory=list)
    supporting_claims: list[str] = Field(default_factory=list)
    l1_atom_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    scenario_markdown: str

    @field_validator(
        "scenario_key",
        "scenario_title",
        "scenario_markdown",
    )
    @classmethod
    def _require_text(cls, value: str) -> str:
        if not str(value).strip():
            raise ValueError("value is required")
        return str(value).strip()

    @field_validator(
        "service",
        "alert_name",
        "environment",
    )
    @classmethod
    def _optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = str(value).strip()
        return stripped or None

    @field_validator(
        "applicable_conditions",
        "diagnostic_path",
        "common_root_causes",
        "remediation_steps",
        "supporting_claims",
        "l1_atom_ids",
    )
    @classmethod
    def _strip_list_items(cls, value: list[str]) -> list[str]:
        return [str(item).strip() for item in value if str(item).strip()]

    @field_validator("evidence_refs")
    @classmethod
    def _require_evidence_refs(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        refs = [ref for ref in value if isinstance(ref, dict)]
        if not refs:
            raise ValueError("evidence_refs is required")
        return refs

    @model_validator(mode="after")
    def validate_payload_contract(self) -> "L2ScenarioPayload":
        if not self.l1_atom_ids:
            raise ValueError("l1_atom_ids is required")
        if not self.scenario_markdown.strip():
            raise ValueError("scenario_markdown is required")
        return self
