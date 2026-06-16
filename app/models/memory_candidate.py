"""Normalized source models for session-derived memory candidates."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.memory import MemoryRecord


class SessionHistoryMessage(BaseModel):
    """Stable RAG chat history item exposed to candidate extraction."""

    role: Literal["user", "assistant"]
    content: str
    message_index: int = Field(..., ge=0)
    timestamp: Optional[str] = None

    @field_validator("content")
    @classmethod
    def _require_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content is required")
        return value


class AIOpsPastStep(BaseModel):
    """Normalized Plan-Execute-Replan executed step."""

    step: str
    result: str
    step_index: int = Field(..., ge=0)


class AIOpsSessionState(BaseModel):
    """Stable AIOps graph state exposed to candidate extraction."""

    session_id: str
    input: str
    plan_steps: list[str] = Field(default_factory=list)
    past_steps: list[AIOpsPastStep] = Field(default_factory=list)
    response: str = ""

    @field_validator("session_id", "input")
    @classmethod
    def _require_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value is required")
        return value


class MemoryCandidateExtractionResult(BaseModel):
    """Result of an explicit operator-triggered candidate extraction."""

    session_id: str
    source_type: Literal["rag_chat", "aiops_diagnosis"]
    action: Literal["created", "duplicate", "conflict", "skipped"]
    records: list[MemoryRecord] = Field(default_factory=list)
    skipped_reason: Optional[str] = None
