"""Deterministic routing providers for Enterprise 2.0 F3 shadow mode."""

from __future__ import annotations

import re
from typing import Any, Protocol

from app.enterprise.context import RequestContext
from app.enterprise.routing.models import RoutingDecision


class RoutingProvider(Protocol):
    name: str

    def evaluate(
        self,
        context: RequestContext,
        *,
        route: str,
        payload: dict[str, Any],
    ) -> RoutingDecision | None:
        ...


class RuleRoutingProvider:
    """First-pass deterministic route classifier.

    This provider is intentionally conservative: it only emits shadow decisions
    and never executes tools or changes the caller's current route.
    """

    name = "rules"

    def evaluate(
        self,
        context: RequestContext,
        *,
        route: str,
        payload: dict[str, Any],
    ) -> RoutingDecision:
        del context
        actual_route = route.lower()
        text = _payload_text(payload)

        if _is_admin_route(actual_route, text):
            return RoutingDecision(
                route="admin",
                provider=self.name,
                reason="admin route or admin-management intent detected",
                risk_level="medium",
                required_capabilities=["admin_api", "permission_check"],
                fallback_route="chat",
                confidence=0.92,
            )

        high_risk_reason = _high_risk_reason(payload, text)
        if high_risk_reason:
            return RoutingDecision(
                route="human_review",
                provider=self.name,
                reason=high_risk_reason,
                risk_level="high",
                required_capabilities=["human_review", "audit"],
                fallback_route="aiops" if actual_route == "aiops" else "chat",
                confidence=0.95,
            )

        if _is_database_intent(text):
            return RoutingDecision(
                route="database",
                provider=self.name,
                reason="database query or schema-inspection intent detected",
                risk_level="medium" if _is_database_write_intent(text) else "low",
                required_capabilities=["safe_sql", "database_permission"],
                fallback_route="chat",
                confidence=0.84,
            )

        if _is_aiops_route(actual_route, text):
            return RoutingDecision(
                route="aiops",
                provider=self.name,
                reason="AIOps route or incident-diagnosis intent detected",
                risk_level="medium",
                required_capabilities=["planner", "tool_call", "audit"],
                fallback_route="rag",
                confidence=0.88,
            )

        if _is_rag_intent(text):
            return RoutingDecision(
                route="rag",
                provider=self.name,
                reason="knowledge retrieval or documentation intent detected",
                risk_level="low",
                required_capabilities=["retrieval", "citation"],
                fallback_route="chat",
                confidence=0.8,
            )

        return RoutingDecision(
            route="chat",
            provider=self.name,
            reason="no specialized route intent detected",
            risk_level="low",
            required_capabilities=[],
            fallback_route=None,
            confidence=0.62,
        )


class KeywordRoutingProvider:
    """Lightweight keyword classifier kept separate from hard routing rules."""

    name = "classifier"

    def evaluate(
        self,
        context: RequestContext,
        *,
        route: str,
        payload: dict[str, Any],
    ) -> RoutingDecision | None:
        del context, route
        text = _payload_text(payload)
        if _is_aiops_route("", text):
            return RoutingDecision(
                route="aiops",
                provider=self.name,
                reason="keyword classifier matched incident-diagnosis terms",
                risk_level="medium",
                required_capabilities=["planner"],
                fallback_route="rag",
                confidence=0.7,
            )
        if _is_database_intent(text):
            return RoutingDecision(
                route="database",
                provider=self.name,
                reason="keyword classifier matched database terms",
                risk_level="medium" if _is_database_write_intent(text) else "low",
                required_capabilities=["safe_sql"],
                fallback_route="chat",
                confidence=0.68,
            )
        if _is_rag_intent(text):
            return RoutingDecision(
                route="rag",
                provider=self.name,
                reason="keyword classifier matched knowledge terms",
                risk_level="low",
                required_capabilities=["retrieval"],
                fallback_route="chat",
                confidence=0.66,
            )
        return None


class LlmShadowRoutingProvider:
    """Disabled LLM-shadow provider placeholder.

    F3 must not introduce a network LLM router. This provider records that the
    LLM shadow slot exists, but the rule provider remains authoritative for the
    current MVP.
    """

    name = "llm_shadow"

    def evaluate(
        self,
        context: RequestContext,
        *,
        route: str,
        payload: dict[str, Any],
    ) -> RoutingDecision | None:
        del context, route, payload
        return None


_ADMIN_PATTERN = re.compile(
    r"\b(create|update|disable|delete|grant|revoke|list)\s+(user|role|grant|permission)s?\b",
    re.IGNORECASE,
)
_AIOPS_PATTERN = re.compile(
    r"(aiops|alert|incident|diagnose|diagnosis|root cause|prometheus|grafana|"
    r"告警|故障|诊断|根因|运维|重启服务)",
    re.IGNORECASE,
)
_RAG_PATTERN = re.compile(
    r"(runbook|document|documentation|knowledge|kb-|citation|source|policy|"
    r"how do i|what is|explain|where is|文档|知识库|手册|说明|解释|引用|来源)",
    re.IGNORECASE,
)
_DB_EXPLICIT_PATTERN = re.compile(
    r"(\bsafe_select\b|\blist_tables\b|\bdescribe_table\b|\bshow\s+tables\b|"
    r"\bdescribe\s+table\b|\blist\s+database\s+tables\b|\bquery\s+(the\s+)?database\b|"
    r"\bselect\b.+\bfrom\b|\bfrom\b.+\btable\b|\bdatabase\s+rows?\b|"
    r"\btable\s+(schema|columns?)\b|数据库表|查询数据库|表结构|字段)",
    re.IGNORECASE,
)
_DB_WRITE_PATTERN = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create\s+table)\b",
    re.IGNORECASE,
)
_HIGH_RISK_PATTERN = re.compile(
    r"(\bgrant\s+all\b|\ball\s+permissions\b|\bdrop\s+database\b|\bdelete\s+database\b|"
    r"\brestart\s+(production|service)\b|\bdeploy\s+to\s+production\b|"
    r"全量授权|删除数据库|生产重启|重启生产|发布生产)",
    re.IGNORECASE,
)


def _payload_text(value: Any) -> str:
    parts: list[str] = []

    def collect(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, str):
            parts.append(item)
            return
        if isinstance(item, dict):
            for child in item.values():
                collect(child)
            return
        if isinstance(item, list | tuple | set):
            for child in item:
                collect(child)
            return
        parts.append(str(item))

    collect(value)
    return " ".join(parts)


def _is_admin_route(route: str, text: str) -> bool:
    return route.startswith("admin") or bool(_ADMIN_PATTERN.search(text))


def _is_aiops_route(route: str, text: str) -> bool:
    return route == "aiops" or bool(_AIOPS_PATTERN.search(text))


def _is_rag_intent(text: str) -> bool:
    return bool(_RAG_PATTERN.search(text))


def _is_database_intent(text: str) -> bool:
    if _is_rag_intent(text) and not _DB_EXPLICIT_PATTERN.search(text):
        return False
    return bool(_DB_EXPLICIT_PATTERN.search(text))


def _is_database_write_intent(text: str) -> bool:
    return bool(_DB_WRITE_PATTERN.search(text))


def _high_risk_reason(payload: dict[str, Any], text: str) -> str | None:
    contract = payload.get("task_contract")
    if isinstance(contract, dict):
        if contract.get("requires_human_approval"):
            return "task contract requires human approval"
        risk_level = str(contract.get("risk_level") or "").lower()
        if risk_level in {"high", "critical"}:
            return f"task contract risk level is {risk_level}"
    if _HIGH_RISK_PATTERN.search(text):
        return "high-risk operation intent detected"
    return None
