"""Knowledge retrieval orchestration for query-intent decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.enterprise.context import RequestContext
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.observability.models import AuditEvent
from app.enterprise.rag.answer_generator import AnswerGenerator, answer_generator
from app.enterprise.rag.query_intent import QueryIntentDecision
from app.enterprise.tools.facade import ToolExecutionFacade
from app.enterprise.tools.local_provider import build_local_agent_tool_execution_facade


@dataclass(frozen=True)
class OrchestrationResult:
    intent: str
    knowledge_action: str
    handoff: str | None
    answer: str
    raw_tool_result: Any = None
    actual_tool_called: bool = False
    actual_tool_name: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)


class KnowledgeRetrievalOrchestrator:
    """Turn a QueryIntentDecision into permission-aware tool calls."""

    def __init__(
        self,
        *,
        tool_execution_facade: ToolExecutionFacade | None = None,
        audit_service: AuditService | None = None,
        answer_generator: AnswerGenerator | None = None,
    ):
        self.tool_execution_facade = tool_execution_facade or build_local_agent_tool_execution_facade()
        self.audit_service = audit_service or AuditService()
        self.answer_generator = answer_generator or answer_generator_default()

    async def execute(
        self,
        context: RequestContext,
        *,
        query: str,
        decision: QueryIntentDecision,
    ) -> OrchestrationResult:
        tool_name = ""
        tool_result: Any = None
        tool_content: Any = None
        tool_artifact: dict[str, Any] | None = None
        actual_tool_called = False

        if decision.knowledge_action == "list":
            tool_name = "list_knowledge_documents"
            tool_result = await self.tool_execution_facade.execute(
                context,
                tool_name,
                self._list_arguments(decision),
            )
            tool_content = tool_result
            actual_tool_called = True
        elif decision.knowledge_action in {"retrieve", "read"}:
            tool_name = "retrieve_knowledge"
            tool_result = await self.tool_execution_facade.execute(
                context,
                tool_name,
                self._retrieve_arguments(query, decision),
            )
            tool_content, tool_artifact = self._split_tool_result(tool_result)
            actual_tool_called = True

        answer = self.answer_generator.build_answer(
            query=query,
            decision=decision,
            tool_result=tool_content,
        )
        result = OrchestrationResult(
            intent=decision.intent,
            knowledge_action=decision.knowledge_action,
            handoff=decision.handoff,
            answer=answer,
            raw_tool_result=tool_result,
            actual_tool_called=actual_tool_called,
            actual_tool_name=tool_name,
            diagnostics={
                **decision.to_diagnostics(),
                "actual_tool_called": actual_tool_called,
                "actual_tool_name": tool_name,
                **self._artifact_diagnostics(tool_artifact),
            },
        )
        self._record_decision(context, query=query, decision=decision, result=result)
        return result

    def _split_tool_result(self, tool_result: Any) -> tuple[Any, dict[str, Any] | None]:
        if (
            isinstance(tool_result, tuple)
            and len(tool_result) == 2
            and isinstance(tool_result[1], dict)
        ):
            return tool_result[0], tool_result[1]
        return tool_result, None

    def _artifact_diagnostics(self, tool_artifact: dict[str, Any] | None) -> dict[str, Any]:
        if not tool_artifact:
            return {}
        diagnostics = tool_artifact.get("diagnostics")
        if isinstance(diagnostics, dict):
            return {"rag_diagnostics": diagnostics}
        return {}

    def _list_arguments(self, decision: QueryIntentDecision) -> dict[str, Any]:
        if len(decision.selected_kb_ids) == 1:
            return {"kb_id": decision.selected_kb_ids[0]}
        return {}

    def _retrieve_arguments(
        self,
        query: str,
        decision: QueryIntentDecision,
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {"query": query}
        if decision.selected_kb_ids:
            arguments["knowledge_base_ids"] = list(decision.selected_kb_ids)
        if decision.selected_doc_ids:
            arguments["doc_id"] = decision.selected_doc_ids[0]
        file_name = decision.metadata.get("file_name")
        if isinstance(file_name, str) and file_name:
            arguments["file_name"] = file_name
        return arguments

    def _record_decision(
        self,
        context: RequestContext,
        *,
        query: str,
        decision: QueryIntentDecision,
        result: OrchestrationResult,
    ) -> None:
        self.audit_service.record(
            AuditEvent(
                event_type="query_intent_decision",
                route="rag_query_intent",
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision="allowed",
                reason=decision.reason,
                metadata={
                    "query": query,
                    "intent": decision.intent,
                    "knowledge_action": decision.knowledge_action,
                    "provider": decision.provider,
                    "confidence": decision.confidence,
                    "selected_kb_ids": list(decision.selected_kb_ids),
                    "selected_doc_ids": list(decision.selected_doc_ids),
                    "scope_source": decision.scope_source,
                    "actual_tool_called": result.actual_tool_called,
                    "actual_tool_name": result.actual_tool_name,
                    "fallback_reason": decision.fallback_reason,
                    "handoff": decision.handoff,
                    "rag_diagnostics": result.diagnostics.get("rag_diagnostics"),
                },
            )
        )


def answer_generator_default() -> AnswerGenerator:
    return answer_generator
