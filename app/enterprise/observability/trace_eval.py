"""Trace completeness and failure localization helpers for E9."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from pydantic import BaseModel, Field

from app.enterprise.observability.models import AuditEvent
from app.enterprise.observability.sse_contract import SseContractCheckResult

REQUIRED_TRACE_OBSERVATION_FIELDS = {
    "event_type",
    "trace_id",
    "request_id",
    "layer",
    "module",
    "decision",
    "reason",
    "latency_ms",
    "status",
}


class TraceObservation(BaseModel):
    event_type: str
    trace_id: str
    request_id: str
    layer: str
    module: str
    decision: str
    reason: str
    latency_ms: float
    status: str
    route: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class TraceIssue(BaseModel):
    code: str
    message: str
    event_type: str | None = None


class TraceCheckResult(BaseModel):
    smoke_name: str
    trace_id: str
    observations: list[TraceObservation] = Field(default_factory=list)
    issues: list[TraceIssue] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.issues


class FailureLocalization(BaseModel):
    event_type: str
    trace_id: str
    layer: str
    module: str
    decision: str
    reason: str
    status: str


class E9ObservabilityReport(BaseModel):
    positive_smokes: dict[str, TraceCheckResult] = Field(default_factory=dict)
    negative_failures: list[FailureLocalization] = Field(default_factory=list)
    sse_contract_checks: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    failure_layer: str = ""

    @property
    def passed(self) -> bool:
        return (
            all(result.passed for result in self.positive_smokes.values())
            and all(check.get("passed", False) for check in self.sse_contract_checks)
            and bool(self.negative_failures)
        )


def check_trace_completeness(
    events: Iterable[AuditEvent],
    *,
    trace_id: str,
    smoke_name: str,
) -> TraceCheckResult:
    observations = [normalize_trace_observation(event) for event in events]
    issues: list[TraceIssue] = []

    matching = [event for event in observations if event.trace_id == trace_id]
    if not matching:
        issues.append(
            TraceIssue(
                code="missing_trace_events",
                message=f"No events matched trace_id={trace_id}",
            )
        )
    if any(event.trace_id != trace_id for event in observations):
        issues.append(
            TraceIssue(
                code="trace_id_mismatch",
                message=f"One or more events did not match trace_id={trace_id}",
            )
        )

    if not any(event.event_type == "request_started" for event in matching):
        issues.append(
            TraceIssue(
                code="missing_request_started",
                message="Trace did not start with request_started",
            )
        )

    if not any(event.event_type in {"request_completed", "request_failed"} for event in matching):
        issues.append(
            TraceIssue(
                code="missing_terminal_event",
                message="Trace did not end with request_completed or request_failed",
            )
        )

    if not all(observation.layer and observation.module and observation.status for observation in matching):
        issues.append(
            TraceIssue(
                code="missing_normalized_fields",
                message="One or more normalized observations are missing required observability fields",
            )
        )

    return TraceCheckResult(
        smoke_name=smoke_name,
        trace_id=trace_id,
        observations=observations,
        issues=issues,
    )


def localize_failure(event: AuditEvent) -> FailureLocalization:
    observation = normalize_trace_observation(event)
    event_type = observation.event_type
    route = observation.route
    decision = observation.decision
    reason = observation.reason

    if event_type == "auth_failed" or route == "auth":
        layer = "L1 Auth"
        module = "auth"
    elif event_type == "request_failed" and (
        observation.status == "blocked"
        or "guardrail" in observation.reason.lower()
        or "guardrail" in str(event.error_class or "").lower()
    ):
        layer = "L2 RequestGateway / Guardrail"
        module = "guardrail"
    elif event_type == "permission_checked" and decision == "denied":
        layer = "L3 Permission"
        module = "permission"
    elif event_type in {"tool_blocked", "tool_failure", "tool_call"} and decision in {"denied", "failed"}:
        layer = "L4 Tool/Model"
        module = "tool_gateway"
    elif event_type in {"model_call", "model_visible"} and decision in {"denied", "failed"}:
        layer = "L4 Tool/Model"
        module = "model_gateway"
    elif event_type in {"rag_retrieval", "upload_saved"} or route in {"rag", "upload"}:
        layer = "L5 RAG/Domain"
        module = route or "rag"
    elif event_type == "database_query" or route in {"database_demo", "database"}:
        layer = "L6 DB"
        module = "database_demo"
    else:
        layer = "L6 Observability / Event Contract"
        module = route or "observability"

    return FailureLocalization(
        event_type=event_type,
        trace_id=observation.trace_id,
        layer=layer,
        module=module,
        decision=decision,
        reason=reason,
        status=observation.status,
    )


def build_e9_observability_report(
    *,
    positive_smokes: dict[str, TraceCheckResult],
    negative_failures: list[FailureLocalization],
    sse_contract_checks: list[SseContractCheckResult],
) -> E9ObservabilityReport:
    sse_payloads = [_sse_check_payload(check) for check in sse_contract_checks]
    summary = {
        "positive_smokes_passed": sum(1 for result in positive_smokes.values() if result.passed),
        "positive_smokes_total": len(positive_smokes),
        "negative_failures_total": len(negative_failures),
        "sse_contracts_passed": sum(1 for check in sse_contract_checks if check.passed),
        "sse_contracts_total": len(sse_contract_checks),
    }

    failure_layer = _summarize_failure_layer(
        positive_smokes=positive_smokes,
        negative_failures=negative_failures,
        sse_contract_checks=sse_contract_checks,
    )

    return E9ObservabilityReport(
        positive_smokes=positive_smokes,
        negative_failures=negative_failures,
        sse_contract_checks=sse_payloads,
        summary=summary,
        failure_layer=failure_layer,
    )


def normalize_trace_observation(event: AuditEvent) -> TraceObservation:
    metadata = dict(event.metadata)
    status = _normalize_status(event, metadata)
    reason = _normalize_reason(event, metadata)
    layer = _normalize_layer(event, metadata)
    module = _normalize_module(event, metadata)
    latency_ms = float(event.latency_ms or 0.0)

    return TraceObservation(
        event_type=event.event_type,
        trace_id=event.trace_id,
        request_id=event.request_id,
        layer=layer,
        module=module,
        decision=event.decision or "observed",
        reason=reason,
        latency_ms=latency_ms,
        status=status,
        route=event.route,
        metadata=metadata,
    )


def _normalize_layer(event: AuditEvent, metadata: dict[str, Any]) -> str:
    event_type = event.event_type
    route = event.route
    if event_type in {"request_started", "request_completed", "request_failed"}:
        return "L2 RequestGateway"
    if event_type == "permission_checked":
        return "L3 Permission"
    if event_type in {"tool_visible", "tool_blocked", "tool_call", "tool_failure"}:
        return "L4 Tool/Model"
    if event_type in {"model_visible", "model_call"}:
        return "L4 Tool/Model"
    if event_type in {"rag_retrieval", "upload_saved"} or route in {"rag", "upload"}:
        return "L5 RAG/Domain"
    if event_type == "database_query" or route in {"database_demo", "database"}:
        return "L6 DB"
    if event_type == "admin_operation" or route == "admin":
        return "L1 Auth/Admin"
    if event_type == "auth_failed" or route == "auth":
        return "L1 Auth"
    if metadata.get("layer"):
        return str(metadata["layer"])
    return "L6 Observability"


def _normalize_module(event: AuditEvent, metadata: dict[str, Any]) -> str:
    if metadata.get("module"):
        return str(metadata["module"])
    if event.route in {"chat", "chat_stream", "aiops", "upload", "permission", "tool_gateway", "model_gateway", "rag", "database_demo", "admin"}:
        return event.route
    if event.event_type == "permission_checked":
        return "permission"
    if event.event_type in {"tool_visible", "tool_blocked", "tool_call", "tool_failure"}:
        return "tool_gateway"
    if event.event_type in {"model_visible", "model_call"}:
        return "model_gateway"
    if event.event_type in {"rag_retrieval", "upload_saved"}:
        return event.route or "rag"
    if event.event_type == "database_query":
        return "database_demo"
    return event.route or "observability"


def _normalize_reason(event: AuditEvent, metadata: dict[str, Any]) -> str:
    if event.reason:
        return event.reason
    if metadata.get("reason"):
        return str(metadata["reason"])
    if metadata.get("blocked_reason"):
        return str(metadata["blocked_reason"])
    if event.error_class:
        return event.error_class
    if event.decision:
        return event.decision
    return "ok"


def _normalize_status(event: AuditEvent, metadata: dict[str, Any]) -> str:
    if metadata.get("status"):
        return str(metadata["status"])
    if event.event_type == "request_started":
        return "started"
    if event.event_type == "request_completed":
        return "completed"
    if event.event_type == "request_failed":
        return "failed"
    if event.decision in {"denied", "blocked"}:
        return "blocked"
    if event.decision == "failed" or event.error_class:
        return "failed"
    if event.decision == "allowed":
        return "completed"
    return "running"


def _sse_check_payload(check: SseContractCheckResult) -> dict[str, Any]:
    return {
        "source": check.source,
        "total_events": check.total_events,
        "issues": [asdict(issue) for issue in check.issues],
        "passed": check.passed,
    }


def _summarize_failure_layer(
    *,
    positive_smokes: dict[str, TraceCheckResult],
    negative_failures: list[FailureLocalization],
    sse_contract_checks: list[SseContractCheckResult],
) -> str:
    if any(not check.passed for check in sse_contract_checks):
        return "L6 Observability / Event Contract"
    if any(not result.passed for result in positive_smokes.values()):
        return "L6 Observability"
    if negative_failures:
        return negative_failures[0].layer
    return ""
