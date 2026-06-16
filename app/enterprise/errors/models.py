"""Structured enterprise error models for F5."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ErrorClass(StrEnum):
    AUTH_FAILED = "auth_failed"
    PERMISSION_DENIED = "permission_denied"
    GUARDRAIL_BLOCKED = "guardrail_blocked"
    MODEL_UNAVAILABLE = "model_unavailable"
    TOOL_FAILED = "tool_failed"
    RETRIEVAL_LOW_CONFIDENCE = "retrieval_low_confidence"
    SQL_BLOCKED = "sql_blocked"
    STREAM_INTERRUPTED = "stream_interrupted"


class RecoveryDecision(StrEnum):
    ABORT = "abort"
    RETRY = "retry"
    FALLBACK = "fallback"
    PARTIAL = "partial"
    REQUEST_MORE_INFO = "request_more_info"
    RECOVERABLE_ERROR = "recoverable_error"


@dataclass(frozen=True)
class ErrorContext:
    error_class: ErrorClass | str
    stage: str
    reason: str | None = None
    source_error_class: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.error_class, ErrorClass):
            object.__setattr__(self, "error_class", ErrorClass(str(self.error_class)))


@dataclass(frozen=True)
class RecoveryPlan:
    error_class: ErrorClass
    stage: str
    decision: RecoveryDecision
    status: str
    user_message: str
    recoverable: bool
    retryable: bool
    fallback_allowed: bool
    audit_category: str
    reason: str | None = None
