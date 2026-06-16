"""Conflict detection models for layered oncall memory."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.memory import MemoryType


class MemoryConflictVerdict(StrEnum):
    """Rule-based conflict verdicts for P7.3."""

    NO_CONFLICT = "no_conflict"
    POSSIBLE_CONFLICT = "possible_conflict"
    SUPERSESSION_CANDIDATE = "supersession_candidate"


class MemoryConflictResult(BaseModel):
    """Traceable conflict detection result for one existing memory row."""

    memory_id: str
    atom_id: str
    owner_id: str
    memory_type: MemoryType
    verdict: MemoryConflictVerdict
    reason: str
    evidence_id: str
    matched_scope: Dict[str, Any] = Field(default_factory=dict)
    review_required: bool = False
    evidence_refs: List[str] = Field(default_factory=list)
    old_claim: Optional[str] = None
    new_claim: Optional[str] = None

    @field_validator("memory_id", "atom_id", "owner_id", "reason", "evidence_id")
    @classmethod
    def _require_text(cls, value: str) -> str:
        if not str(value).strip():
            raise ValueError("value is required")
        return str(value).strip()
