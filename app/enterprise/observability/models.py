"""Audit event models for E2."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class AuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str
    route: str
    trace_id: str
    request_id: str
    user_id: str = "anonymous"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    decision: str | None = None
    reason: str | None = None
    error_class: str | None = None
    error_message: str | None = None
    latency_ms: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
