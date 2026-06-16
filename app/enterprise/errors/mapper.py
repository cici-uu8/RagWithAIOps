"""Helpers that map exceptions to F5 error classes and SSE/audit shapes."""

from __future__ import annotations

import asyncio
from typing import Any

from app.enterprise.errors.models import ErrorClass, ErrorContext, RecoveryPlan
from app.enterprise.errors.recovery import RecoveryStrategy


def map_exception_to_error_context(
    exc: BaseException,
    *,
    stage: str,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ErrorContext:
    error_class = _classify_exception(exc)
    source_error_class = type(exc).__name__
    mapped_reason = reason or getattr(exc, "reason", None)
    cause = getattr(exc, "cause", None)
    if cause is not None:
        source_error_class = type(cause).__name__
    return ErrorContext(
        error_class=error_class,
        stage=stage,
        reason=mapped_reason,
        source_error_class=source_error_class,
        metadata=metadata or {},
    )


def build_error_event(
    context: ErrorContext,
    *,
    trace_id: str,
    request_id: str,
    event_type: str = "error",
    strategy: RecoveryStrategy | None = None,
) -> dict[str, Any]:
    plan = (strategy or RecoveryStrategy()).decide(context)
    data = {
        "error_class": plan.error_class.value,
        "decision": plan.decision.value,
        "recoverable": plan.recoverable,
        "retryable": plan.retryable,
        "fallback_allowed": plan.fallback_allowed,
        "user_message": plan.user_message,
        "stage": plan.stage,
        "audit_category": plan.audit_category,
    }
    if plan.reason:
        data["reason"] = plan.reason
    if context.source_error_class:
        data["source_error_class"] = context.source_error_class
    return {
        "type": event_type,
        "trace_id": trace_id,
        "request_id": request_id,
        "stage": plan.stage,
        "status": plan.status,
        "message": plan.user_message,
        "error_class": plan.error_class.value,
        "decision": plan.decision.value,
        "reason": plan.reason,
        "data": data,
    }


def recovery_metadata(
    plan: RecoveryPlan,
    *,
    source_error_class: str | None = None,
    source_error_classes: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "error_class": plan.error_class.value,
        "stage": plan.stage,
        "status": plan.status,
        "recovery_decision": plan.decision.value,
        "user_message": plan.user_message,
        "recoverable": plan.recoverable,
        "retryable": plan.retryable,
        "fallback_allowed": plan.fallback_allowed,
        "audit_category": plan.audit_category,
    }
    if source_error_class:
        metadata["source_error_class"] = source_error_class
    if source_error_classes is not None:
        metadata["source_error_classes"] = source_error_classes
    if extra:
        metadata.update(extra)
    return metadata


def _classify_exception(exc: BaseException) -> ErrorClass:
    if isinstance(exc, asyncio.CancelledError):
        return ErrorClass.STREAM_INTERRUPTED

    name = type(exc).__name__
    if name == "RequestBlocked":
        return ErrorClass.GUARDRAIL_BLOCKED
    if name == "RateLimitBlocked":
        return ErrorClass.PERMISSION_DENIED
    if name in {"ToolAccessDenied", "ModelAccessDenied"}:
        return ErrorClass.PERMISSION_DENIED
    if name == "ModelGatewayError":
        return ErrorClass.MODEL_UNAVAILABLE
    if name == "SafeSqlBlocked":
        return ErrorClass.SQL_BLOCKED
    if name == "ToolExecutionError":
        cause = getattr(exc, "cause", None)
        if cause is not None and type(cause).__name__ == "SafeSqlBlocked":
            return ErrorClass.SQL_BLOCKED
        return ErrorClass.TOOL_FAILED
    if isinstance(exc, PermissionError):
        return ErrorClass.PERMISSION_DENIED
    return ErrorClass.TOOL_FAILED
