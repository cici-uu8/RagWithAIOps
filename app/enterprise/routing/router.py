"""Strategy routing shadow service for Enterprise 2.0 F3."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from loguru import logger

from app.enterprise.context import RequestContext
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.observability.models import AuditEvent
from app.enterprise.routing.models import (
    RoutingComparisonReport,
    RoutingConfusionCase,
    RoutingDecision,
)
from app.enterprise.routing.providers import (
    KeywordRoutingProvider,
    LlmShadowRoutingProvider,
    RoutingProvider,
    RuleRoutingProvider,
)


class StrategyRouter:
    """Shadow-only routing evaluator.

    The router produces explainable decisions and audit evidence. It never
    dispatches requests and should not be used as an execution router in F3.
    """

    def __init__(self, providers: Sequence[RoutingProvider] | None = None):
        self.providers = list(providers) if providers is not None else [
            RuleRoutingProvider(),
            KeywordRoutingProvider(),
            LlmShadowRoutingProvider(),
        ]

    def evaluate(
        self,
        context: RequestContext,
        *,
        route: str,
        payload: dict[str, Any],
    ) -> RoutingDecision:
        for provider in self.providers:
            decision = provider.evaluate(context, route=route, payload=payload)
            if decision is not None:
                return _with_shadow_diagnostics(
                    decision,
                    actual_route=route,
                    payload=payload,
                )
        fallback_decision = RoutingDecision(
            route="chat",
            provider="rules",
            reason="no routing provider produced a decision",
            risk_level="low",
            required_capabilities=[],
            fallback_route=None,
            confidence=0.0,
        )
        return _with_shadow_diagnostics(
            fallback_decision,
            actual_route=route,
            payload=payload,
        )

    def record_shadow_decision(
        self,
        *,
        audit_service: AuditService,
        context: RequestContext,
        actual_route: str,
        payload: dict[str, Any],
    ) -> RoutingDecision | None:
        try:
            decision = self.evaluate(context, route=actual_route, payload=payload)
            audit_service.record(
                AuditEvent(
                    event_type="routing_decision",
                    route=actual_route,
                    trace_id=context.trace_id,
                    request_id=context.request_id,
                    user_id=context.user_id,
                    decision="shadow",
                    reason=decision.reason,
                    metadata=_decision_metadata(
                        context=context,
                        actual_route=actual_route,
                        decision=decision,
                    ),
                )
            )
            return decision
        except Exception as exc:
            logger.warning("Strategy routing shadow failed: {}", exc)
            audit_service.record(
                AuditEvent(
                    event_type="routing_decision",
                    route=actual_route,
                    trace_id=context.trace_id,
                    request_id=context.request_id,
                    user_id=context.user_id,
                    decision="failed",
                    reason="routing_shadow_failed",
                    error_class=type(exc).__name__,
                    metadata={
                        "actual_route": actual_route,
                        "trace_id": context.trace_id,
                        "request_id": context.request_id,
                    },
                )
            )
            return None


def build_routing_comparison_report(
    events: Iterable[AuditEvent | dict[str, Any]],
) -> RoutingComparisonReport:
    total = 0
    matched = 0
    confusion_cases: list[RoutingConfusionCase] = []
    risk_mistakes: list[RoutingConfusionCase] = []

    for event in events:
        metadata = _event_metadata(event)
        if _event_type(event) != "routing_decision":
            continue
        actual_route = str(metadata.get("actual_route") or _event_route(event))
        suggested_route = str(metadata.get("suggested_route") or metadata.get("route") or "")
        if not actual_route or not suggested_route:
            continue

        total += 1
        case = RoutingConfusionCase(
            trace_id=str(metadata.get("trace_id") or _event_trace_id(event)),
            request_id=str(metadata.get("request_id") or _event_request_id(event)),
            actual_route=actual_route,
            suggested_route=suggested_route,
            provider=str(metadata.get("provider") or ""),
            reason=str(metadata.get("reason") or _event_reason(event) or ""),
        )
        if actual_route == suggested_route:
            matched += 1
        else:
            confusion_cases.append(case)
        if metadata.get("risk_level") == "high" and suggested_route != "human_review":
            risk_mistakes.append(case)

    match_rate = round(matched / total, 4) if total else 0.0
    return RoutingComparisonReport(
        total_decisions=total,
        matched_decisions=matched,
        match_rate=match_rate,
        confusion_cases=confusion_cases,
        risk_mistakes=risk_mistakes,
    )


def _decision_metadata(
    *,
    context: RequestContext,
    actual_route: str,
    decision: RoutingDecision,
) -> dict[str, Any]:
    return {
        "actual_route": actual_route,
        "suggested_route": decision.route,
        "provider": decision.provider,
        "reason": decision.reason,
        "risk_level": decision.risk_level,
        "required_capabilities": decision.required_capabilities,
        "fallback_route": decision.fallback_route,
        "confidence": decision.confidence,
        "trace_id": context.trace_id,
        "request_id": context.request_id,
        **decision.metadata,
    }


def _with_shadow_diagnostics(
    decision: RoutingDecision,
    *,
    actual_route: str,
    payload: dict[str, Any],
) -> RoutingDecision:
    existing = decision.metadata.get("routing_diagnostics")
    existing_diagnostics = existing if isinstance(existing, dict) else {}
    diagnostics = {
        "domain": _infer_domain(decision.route),
        "intent": _infer_intent(decision, payload=payload),
        "approval_required": _approval_required(decision),
        "execution_mode": _infer_execution_mode(decision.route),
        "actual_route": actual_route,
        "shadow_only": True,
        **existing_diagnostics,
    }
    return decision.model_copy(
        update={
            "metadata": {
                **decision.metadata,
                "routing_diagnostics": diagnostics,
            }
        }
    )


def _infer_domain(route: str) -> str:
    return {
        "admin": "admin",
        "aiops": "aiops",
        "chat": "general",
        "database": "database",
        "human_review": "governance",
        "rag": "knowledge",
    }.get(route, "general")


def _infer_intent(decision: RoutingDecision, *, payload: dict[str, Any]) -> str:
    if decision.route == "human_review":
        return "approval_required"
    if decision.route == "database":
        return "database_write" if decision.risk_level in {"medium", "high"} else "database_read"
    if decision.route == "aiops":
        return "incident_diagnosis"
    if decision.route == "rag":
        return "knowledge_retrieval"
    if decision.route == "admin":
        return "admin_management"
    if _payload_mentions_documents(payload):
        return "knowledge_or_document_question"
    return "plain_chat"


def _approval_required(decision: RoutingDecision) -> bool:
    return (
        decision.route == "human_review"
        or decision.risk_level == "high"
        or "human_review" in decision.required_capabilities
    )


def _infer_execution_mode(route: str) -> str:
    return {
        "admin": "admin_api",
        "aiops": "agent_workflow",
        "chat": "direct_response",
        "database": "governed_tool",
        "human_review": "approval_gate",
        "rag": "retrieval",
    }.get(route, "direct_response")


def _payload_mentions_documents(payload: dict[str, Any]) -> bool:
    text = " ".join(str(value) for value in payload.values()).lower()
    return any(term in text for term in ("document", "runbook", "knowledge", "文档", "手册"))


def _event_metadata(event: AuditEvent | dict[str, Any]) -> dict[str, Any]:
    if isinstance(event, AuditEvent):
        return event.metadata
    metadata = event.get("metadata") or {}
    return metadata if isinstance(metadata, dict) else {}


def _event_type(event: AuditEvent | dict[str, Any]) -> str:
    return event.event_type if isinstance(event, AuditEvent) else str(event.get("event_type") or "")


def _event_route(event: AuditEvent | dict[str, Any]) -> str:
    return event.route if isinstance(event, AuditEvent) else str(event.get("route") or "")


def _event_trace_id(event: AuditEvent | dict[str, Any]) -> str:
    return event.trace_id if isinstance(event, AuditEvent) else str(event.get("trace_id") or "")


def _event_request_id(event: AuditEvent | dict[str, Any]) -> str:
    return event.request_id if isinstance(event, AuditEvent) else str(event.get("request_id") or "")


def _event_reason(event: AuditEvent | dict[str, Any]) -> str | None:
    return event.reason if isinstance(event, AuditEvent) else event.get("reason")


strategy_router = StrategyRouter()
