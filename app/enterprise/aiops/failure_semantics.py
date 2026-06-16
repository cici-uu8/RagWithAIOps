"""Shared AIOps failure labels for SSE, audit, eval, and smoke gates."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class AIOpsFailureLabel(StrEnum):
    MISSING_REQUIRED_TOOL = "missing_required_tool"
    MCP_TIMEOUT = "mcp_timeout"
    MCP_PROVIDER_ERROR = "mcp_provider_error"
    LLM_TIMEOUT = "llm_timeout"
    STRUCTURED_OUTPUT_RECOVERED = "structured_output_recovered"
    RECOVERED_INFRA_ERROR = "recovered_infra_error"
    STRUCTURED_OUTPUT_FAILED = "structured_output_failed"
    INFRA_ERROR = "infra_error"
    TOOL_PERMISSION_DENIED = "tool_permission_denied"


RECOVERED_LABELS = frozenset(
    {
        AIOpsFailureLabel.STRUCTURED_OUTPUT_RECOVERED,
        AIOpsFailureLabel.RECOVERED_INFRA_ERROR,
    }
)

HARD_FAILURE_LABELS = {
    AIOpsFailureLabel.MISSING_REQUIRED_TOOL,
    AIOpsFailureLabel.MCP_TIMEOUT,
    AIOpsFailureLabel.MCP_PROVIDER_ERROR,
    AIOpsFailureLabel.LLM_TIMEOUT,
    AIOpsFailureLabel.STRUCTURED_OUTPUT_FAILED,
    AIOpsFailureLabel.INFRA_ERROR,
    AIOpsFailureLabel.TOOL_PERMISSION_DENIED,
}


class AIOpsFailureSemantics:
    @classmethod
    def classify_exception(cls, error: BaseException | str | None) -> AIOpsFailureLabel:
        text = _error_text(error)
        lowered = text.lower()
        error_type = type(error).__name__ if isinstance(error, BaseException) else ""

        if "missing_required_tool" in lowered or "missing required tool" in lowered:
            return AIOpsFailureLabel.MISSING_REQUIRED_TOOL
        if "permission" in lowered or error_type == "ToolAccessDenied":
            return AIOpsFailureLabel.TOOL_PERMISSION_DENIED
        if "structured output" in lowered and (
            "failed in primary and fallback" in lowered
            or "returned none" in lowered
            or "failed" in lowered
        ):
            return AIOpsFailureLabel.STRUCTURED_OUTPUT_FAILED
        if "timed out" in lowered or "timeout" in lowered or error_type == "TimeoutError":
            if _looks_like_mcp_stage(lowered) or "get_tools" in lowered or "tool invocation" in lowered:
                return AIOpsFailureLabel.MCP_TIMEOUT
            return AIOpsFailureLabel.LLM_TIMEOUT
        if "mcp" in lowered or "all connection attempts failed" in lowered:
            return AIOpsFailureLabel.MCP_PROVIDER_ERROR
        return AIOpsFailureLabel.INFRA_ERROR

    @classmethod
    def classify_event(cls, event: dict[str, Any]) -> AIOpsFailureLabel | None:
        existing = event.get("failure_semantics")
        if existing:
            return AIOpsFailureLabel(str(existing))
        if event.get("structured_output_recovered") is True:
            return AIOpsFailureLabel.STRUCTURED_OUTPUT_RECOVERED
        message = event.get("infra_error_message") or event.get("message")
        if event.get("infra_error"):
            return cls.classify_exception(str(message or "infra_error"))
        if event.get("type") == "error" or event.get("status") in {"failed", "blocked"}:
            return cls.classify_exception(str(message or "infra_error"))
        return None

    @classmethod
    def to_degradation_event(
        cls,
        error_or_event: BaseException | str | dict[str, Any],
        *,
        label: AIOpsFailureLabel | str | None = None,
        stage: str | None = None,
    ) -> dict[str, Any]:
        payload = dict(error_or_event) if isinstance(error_or_event, dict) else {}
        active_label = AIOpsFailureLabel(str(label)) if label else (
            cls.classify_event(payload)
            if payload
            else cls.classify_exception(error_or_event)
        )
        if active_label is None:
            active_label = AIOpsFailureLabel.INFRA_ERROR
        hard_failure = active_label in HARD_FAILURE_LABELS
        payload["failure_semantics"] = active_label.value
        payload["failure_semantics_hard_failure"] = hard_failure
        payload["hard_failure"] = hard_failure
        payload["degradation"] = not hard_failure
        if stage and not payload.get("stage"):
            payload["stage"] = stage
        return payload

    @classmethod
    def to_sse_error(cls, error_or_event: BaseException | str | dict[str, Any]) -> dict[str, Any]:
        event = cls.to_degradation_event(error_or_event)
        return {
            "failure_semantics": event["failure_semantics"],
            "failure_semantics_hard_failure": event["failure_semantics_hard_failure"],
            "degradation": event["degradation"],
        }

    @classmethod
    def to_audit_metadata(cls, error_or_event: BaseException | str | dict[str, Any]) -> dict[str, Any]:
        event = cls.to_degradation_event(error_or_event)
        return {
            "failure_semantics": event["failure_semantics"],
            "failure_semantics_hard_failure": event["failure_semantics_hard_failure"],
            "degradation": event["degradation"],
        }

    @classmethod
    def to_eval_label(cls, error_or_event: BaseException | str | dict[str, Any]) -> str:
        event = cls.to_degradation_event(error_or_event)
        return str(event["failure_semantics"])


def _error_text(error: BaseException | str | None) -> str:
    if error is None:
        return ""
    if isinstance(error, BaseException):
        return f"{type(error).__name__}: {error}"
    return str(error)


def _looks_like_mcp_stage(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "mcp",
            "get_tools",
            "tool invocation",
            "query_active_alerts",
            "query_metric_series",
            "search_service_logs",
        )
    )
