"""Deterministic query-intent routing for knowledge chat v1."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from app.enterprise.context import RequestContext

KnowledgeIntent = Literal[
    "document_list",
    "knowledge_qa",
    "document_read",
    "plain_chat",
    "database",
    "permission_request",
    "permission_filtered",
    "human_review",
]
KnowledgeAction = Literal["list", "retrieve", "read", "none", "handoff"]
IntentProvider = Literal["rules", "llm_classifier"]
ScopeSource = Literal["user_selected", "auto_visible"]

PROCESS_DIGITAL_KB_ID = "process_digital_dept"
CRAFT_KB_ID = "craft_dept"
REJECTED_CURRENT_KB_ID = "rejected_current_kb"


@dataclass(frozen=True)
class QueryScope:
    selected_kb_ids: list[str] = field(default_factory=list)
    visible_kb_ids: list[str] = field(default_factory=list)
    selected_doc_ids: list[str] = field(default_factory=list)
    scope_source: ScopeSource = "auto_visible"


@dataclass(frozen=True)
class QueryIntentDecision:
    intent: KnowledgeIntent
    knowledge_action: KnowledgeAction
    provider: IntentProvider
    confidence: float
    selected_kb_ids: list[str]
    selected_doc_ids: list[str]
    scope_source: ScopeSource
    requires_retrieval: bool
    handoff: str | None
    fallback_intent: KnowledgeIntent | None
    reason: str
    fallback_reason: str = ""
    metadata: dict[str, str | list[str]] = field(default_factory=dict)

    def to_diagnostics(self) -> dict:
        return {
            "intent": self.intent,
            "knowledge_action": self.knowledge_action,
            "provider": self.provider,
            "confidence": self.confidence,
            "selected_kb_ids": list(self.selected_kb_ids),
            "selected_doc_ids": list(self.selected_doc_ids),
            "scope_source": self.scope_source,
            "requires_retrieval": self.requires_retrieval,
            "handoff": self.handoff,
            "fallback_intent": self.fallback_intent,
            "reason": self.reason,
            "fallback_reason": self.fallback_reason,
            "metadata": dict(self.metadata),
        }


class QueryIntentRouter:
    """Rules-first router for knowledge-specific chat intents."""

    def classify(
        self,
        query: str,
        *,
        context: RequestContext | None = None,
        scope: QueryScope | None = None,
    ) -> QueryIntentDecision:
        del context
        normalized = _normalize_query(query)
        active_scope = scope or QueryScope()
        selected_kb_ids, scope_source, scope_reason = self._selected_kb_scope(
            normalized,
            active_scope,
        )
        selected_doc_ids = _dedupe(active_scope.selected_doc_ids)

        blocked_kb_ids = _missing_requested_kb_ids(
            normalized,
            visible_kb_ids=_dedupe(active_scope.visible_kb_ids),
        )
        if blocked_kb_ids:
            return self._decision(
                "permission_filtered",
                "handoff",
                selected_kb_ids,
                selected_doc_ids,
                scope_source,
                False,
                "permission_filtered",
                "用户问题指向当前不可见或不属于当前知识库范围的资料，不能用其他可见资料硬答。",
                confidence=0.93,
                metadata={
                    "requested_kb_ids": infer_requested_kb_ids(normalized),
                    "blocked_kb_ids": blocked_kb_ids,
                },
            )

        if _is_permission_request(normalized):
            return self._decision(
                "permission_request",
                "handoff",
                selected_kb_ids,
                selected_doc_ids,
                scope_source,
                False,
                "permission_request",
                "用户明确请求权限申请，应进入权限申请入口。",
                confidence=0.94,
            )

        if _is_database_intent(normalized):
            intent: KnowledgeIntent = "human_review" if _is_high_risk_database_intent(normalized) else "database"
            handoff = "human_review" if intent == "human_review" else "database"
            return self._decision(
                intent,
                "handoff",
                selected_kb_ids,
                selected_doc_ids,
                scope_source,
                False,
                handoff,
                "数据库或高风险操作意图应进入数据库安全边界，不能由知识库回答吞掉。",
                confidence=0.92 if intent == "human_review" else 0.88,
            )

        if _is_document_list_intent(normalized):
            return self._decision(
                "document_list",
                "list",
                selected_kb_ids,
                selected_doc_ids,
                scope_source,
                True,
                None,
                f"文件清单类问题，应列出可见知识库文档。{scope_reason}",
                confidence=0.9,
            )

        file_name = _extract_file_name(normalized)
        if _is_document_read_intent(normalized):
            metadata: dict[str, str | list[str]] = {}
            if file_name:
                metadata["file_name"] = file_name
            return self._decision(
                "document_read",
                "read",
                selected_kb_ids,
                selected_doc_ids,
                scope_source,
                True,
                None,
                f"用户要求打开、读取或总结具体文件，应进入文件限定检索。{scope_reason}",
                confidence=0.86 if file_name else 0.76,
                metadata=metadata,
            )

        if _is_knowledge_qa_intent(normalized):
            return self._decision(
                "knowledge_qa",
                "retrieve",
                selected_kb_ids,
                selected_doc_ids,
                scope_source,
                True,
                None,
                f"企业资料知识问答，应检索可见资料后回答。{scope_reason}",
                confidence=0.84,
            )

        return self._decision(
            "plain_chat",
            "none",
            selected_kb_ids,
            selected_doc_ids,
            scope_source,
            False,
            None,
            "未命中知识库、文档、数据库、权限或人工审批意图，按普通对话处理。",
            confidence=0.68,
        )

    def _selected_kb_scope(
        self,
        query: str,
        scope: QueryScope,
    ) -> tuple[list[str], ScopeSource, str]:
        selected = _dedupe(scope.selected_kb_ids)
        visible = _dedupe(scope.visible_kb_ids)
        if selected:
            return selected, "user_selected", "用户选择的知识库 scope 是强约束。"

        selected = self._auto_kb_ids(query, visible)
        if _matches(query, _PROCESS_PATTERNS):
            return selected, "auto_visible", "auto 命中流程与数字化关键词，使用流程与数字化知识库候选。"
        if _matches(query, _CRAFT_PATTERNS):
            return selected, "auto_visible", "auto 命中工艺/设备关键词，使用工艺知识库候选。"
        return selected, "auto_visible", "未手动选择知识库，使用当前用户可见范围自动候选。"

    def _auto_kb_ids(self, query: str, visible_kb_ids: list[str]) -> list[str]:
        if not visible_kb_ids:
            return []
        if _matches(query, _PROCESS_PATTERNS):
            return [kb_id for kb_id in visible_kb_ids if kb_id == PROCESS_DIGITAL_KB_ID] or visible_kb_ids
        if _matches(query, _CRAFT_PATTERNS):
            return [kb_id for kb_id in visible_kb_ids if kb_id == CRAFT_KB_ID] or visible_kb_ids
        return visible_kb_ids

    def _decision(
        self,
        intent: KnowledgeIntent,
        action: KnowledgeAction,
        selected_kb_ids: list[str],
        selected_doc_ids: list[str],
        scope_source: ScopeSource,
        requires_retrieval: bool,
        handoff: str | None,
        reason: str,
        *,
        confidence: float,
        metadata: dict[str, str | list[str]] | None = None,
    ) -> QueryIntentDecision:
        return QueryIntentDecision(
            intent=intent,
            knowledge_action=action,
            provider="rules",
            confidence=confidence,
            selected_kb_ids=list(selected_kb_ids),
            selected_doc_ids=list(selected_doc_ids),
            scope_source=scope_source,
            requires_retrieval=requires_retrieval,
            handoff=handoff,
            fallback_intent="plain_chat" if requires_retrieval else None,
            reason=reason,
            metadata=metadata or {},
        )


_DOCUMENT_LIST_PATTERNS = (
    r"相关文件.*(什么|哪些|有什么)",
    r"(有哪些|列出|查看).*(文档|文件|资料)",
    r"(知识库|资料库).*有什么",
)
_DOCUMENT_READ_PATTERNS = (
    r"(打开|读取|读一下|看一下|总结|概括).*(文件|文档|\.pdf|\.md|\.txt|手册|方案)",
    r"(这个|该).*(文件|文档).*(讲了什么|主要讲什么|总结)",
)
_KNOWLEDGE_QA_PATTERNS = (
    r"中车长客",
    r"数字化转型",
    r"线上故障",
    r"故障.*(处理|排查|复盘|怎么)",
    r"(redis|mysql|慢查询|ttl|内存).*(同时出现|先看|优先|哪个|为什么|根因|涨|增长)",
    r"(服务|接口).*(超时|响应慢|不可用).*(排查|处理|怎么办|怎么查)",
    r"(pod|kubernetes|kube).*(pending|notready|调度|状态|原因|为什么)",
    r"(sre|playbook|runbook|告警).*(严重性|级别|表格|有哪些)",
    r"(cpu|throttling|pod|notready|告警).*(导致|同时出现|怎么办|怎么处理)",
    r"(制度|流程|手册|方案|政策|工艺|智能运维)",
)
_PROCESS_PATTERNS = (
    r"中车长客",
    r"数字化",
    r"线上故障",
    r"智能运维",
    r"prometheus",
    r"alertmanager",
    r"mcp",
    r"api",
)
_CRAFT_PATTERNS = (
    r"工艺",
    r"设备",
    r"检修",
    r"安全隔离",
    r"loto",
    r"环保",
)
_OUT_OF_SCOPE_PATTERNS = (
    r"环保监测",
    r"土壤",
    r"地下水",
    r"温室气体",
    r"排放报告",
    r"合规披露",
)
_DATABASE_PATTERNS = (
    r"(数据库|订单表|表结构|字段|\bsql\b|select|insert|update|delete|drop|alter|create\s+table)",
    r"(查询|查看).*(表|字段)",
    r"把.+(改成|更新为|删除)",
    r"创建.*表",
)
_HIGH_RISK_DATABASE_PATTERNS = (
    r"(drop|alter|delete|truncate)",
    r"(删除|授权|生产|ddl)",
)
_PERMISSION_PATTERNS = (
    r"(申请|开通|要).*(权限|授权)",
    r"permission",
    r"grant",
)
_FILE_NAME_PATTERN = re.compile(r"([\w\-\u4e00-\u9fff]+(?:\.pdf|\.md|\.markdown|\.txt|\.docx?))", re.IGNORECASE)
_GREETING_PATTERN = re.compile(r"^(你好|您好|hello|hi|嗨)[。！!,.，\s]*$", re.IGNORECASE)


def _normalize_query(query: str) -> str:
    return (query or "").strip()


def _is_permission_request(query: str) -> bool:
    return _matches(query, _PERMISSION_PATTERNS)


def _is_database_intent(query: str) -> bool:
    return _matches(query, _DATABASE_PATTERNS)


def _is_high_risk_database_intent(query: str) -> bool:
    return _matches(query, _HIGH_RISK_DATABASE_PATTERNS) or bool(re.search(r"改成|更新为|创建", query, re.IGNORECASE))


def _is_document_list_intent(query: str) -> bool:
    return _matches(query, _DOCUMENT_LIST_PATTERNS)


def _is_document_read_intent(query: str) -> bool:
    return _matches(query, _DOCUMENT_READ_PATTERNS)


def _is_knowledge_qa_intent(query: str) -> bool:
    if _GREETING_PATTERN.match(query):
        return False
    return _matches(query, _KNOWLEDGE_QA_PATTERNS)


def _extract_file_name(query: str) -> str:
    match = _FILE_NAME_PATTERN.search(query)
    return match.group(1) if match else ""


def infer_requested_kb_ids(query: str) -> list[str]:
    """Infer explicit KB targets mentioned by the query text."""

    normalized = _normalize_query(query)
    requested: list[str] = []
    if _matches(normalized, _PROCESS_PATTERNS):
        requested.append(PROCESS_DIGITAL_KB_ID)
    if _matches(normalized, _CRAFT_PATTERNS):
        requested.append(CRAFT_KB_ID)
    if _matches(normalized, _OUT_OF_SCOPE_PATTERNS):
        requested.append(REJECTED_CURRENT_KB_ID)
    return _dedupe(requested)


def _missing_requested_kb_ids(query: str, *, visible_kb_ids: list[str]) -> list[str]:
    visible = set(visible_kb_ids)
    if not visible:
        return []
    requested = infer_requested_kb_ids(query)
    return [kb_id for kb_id in requested if kb_id not in visible]


def _matches(query: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, query, re.IGNORECASE) for pattern in patterns)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


query_intent_router = QueryIntentRouter()
