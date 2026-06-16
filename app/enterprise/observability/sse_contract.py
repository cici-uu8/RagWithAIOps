"""SSE event contract helpers for E9 observability checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

REQUIRED_SSE_FIELDS = {
    "type",
    "trace_id",
    "request_id",
    "stage",
    "status",
    "message",
    "data",
}

_COMMON_FIELDS = REQUIRED_SSE_FIELDS | {
    "error_class",
    "reason",
    "decision",
    "latency_ms",
    "recoverable",
    "retryable",
    "fallback_allowed",
    "user_message",
}

_STAGE_BY_TYPE = {
    "blocked": "request_blocked",
    "complete": "done",
    "content": "content",
    "debug": "debug",
    "done": "done",
    "error": "error",
    "plan": "plan",
    "report": "report",
    "search_results": "retrieval",
    "step_complete": "tool",
    "status": "status",
    "tool_call": "tool",
}

_STATUS_BY_TYPE = {
    "blocked": "blocked",
    "complete": "completed",
    "done": "completed",
    "error": "failed",
    "plan": "completed",
    "report": "completed",
    "search_results": "completed",
    "step_complete": "completed",
}

_MESSAGE_BY_TYPE = {
    "blocked": "Request blocked",
    "complete": "Request completed",
    "content": "Streaming content",
    "debug": "Debug event",
    "done": "Request completed",
    "error": "Request failed",
    "plan": "Plan created",
    "report": "Report generated",
    "search_results": "Retrieval results",
    "step_complete": "Step completed",
    "status": "Status update",
    "tool_call": "Tool call",
}


@dataclass(frozen=True)
class SseContractIssue:
    source: str
    event_index: int
    event_type: str
    missing_fields: list[str]


@dataclass(frozen=True)
class SseContractCheckResult:
    source: str
    total_events: int
    issues: list[SseContractIssue]

    @property
    def passed(self) -> bool:
        return not self.issues


def normalize_sse_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = dict(event)
    event_type = str(payload.get("type") or "stage")
    payload["type"] = event_type
    payload.setdefault("trace_id", "")
    payload.setdefault("request_id", "")
    payload.setdefault("stage", _infer_stage(payload))
    payload.setdefault("status", _infer_status(payload))
    payload.setdefault("message", _infer_message(payload))
    if "data" not in payload:
        payload["data"] = _infer_data(payload)
    return payload


def check_sse_contract(
    events: list[dict[str, Any]],
    *,
    source: str,
) -> SseContractCheckResult:
    issues: list[SseContractIssue] = []
    for index, event in enumerate(events):
        missing = [
            field
            for field in sorted(REQUIRED_SSE_FIELDS)
            if field not in event or event[field] in (None, "")
        ]
        if missing:
            issues.append(
                SseContractIssue(
                    source=source,
                    event_index=index,
                    event_type=str(event.get("type") or "unknown"),
                    missing_fields=missing,
                )
            )
    return SseContractCheckResult(
        source=source,
        total_events=len(events),
        issues=issues,
    )


def _infer_stage(payload: dict[str, Any]) -> str:
    event_type = str(payload.get("type") or "")
    return _STAGE_BY_TYPE.get(event_type, event_type or "stage")


def _infer_status(payload: dict[str, Any]) -> str:
    event_type = str(payload.get("type") or "")
    if payload.get("error_class"):
        return "failed"
    if payload.get("reason") and event_type == "blocked":
        return "blocked"
    return _STATUS_BY_TYPE.get(event_type, "running")


def _infer_message(payload: dict[str, Any]) -> str:
    existing = payload.get("message")
    if existing:
        return str(existing)
    event_type = str(payload.get("type") or "")
    data = payload.get("data")
    if isinstance(data, str) and event_type in {"blocked", "error"}:
        return data
    return _MESSAGE_BY_TYPE.get(event_type, event_type or "Event")


def _infer_data(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in _COMMON_FIELDS
    }
