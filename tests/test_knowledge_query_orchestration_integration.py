import unittest
from unittest.mock import patch

from app.enterprise.context import (
    RequestContext,
    reset_current_request_context,
    set_current_request_context,
)


def _context() -> RequestContext:
    return RequestContext(
        request_id="request-query-orchestration",
        trace_id="trace-query-orchestration",
        user_id="user_demo_dept1",
        username="demo_user_dept1",
        department_id="dept_1",
        department_name="Department 1",
        roles=["user"],
    )


class FakeOrchestrator:
    def __init__(self):
        self.calls = []

    async def execute(self, context, *, query, decision):
        from app.enterprise.rag.retrieval_orchestrator import OrchestrationResult

        self.calls.append((context, query, decision))
        return OrchestrationResult(
            intent=decision.intent,
            knowledge_action=decision.knowledge_action,
            handoff=decision.handoff,
            answer=f"orchestrated:{decision.intent}:{','.join(decision.selected_kb_ids)}",
            actual_tool_called=decision.requires_retrieval,
            actual_tool_name="retrieve_knowledge" if decision.requires_retrieval else "",
            diagnostics=decision.to_diagnostics(),
        )


class KnowledgeQueryOrchestrationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def test_chat_request_accepts_selected_kb_scope_aliases(self):
        from app.models.request import ChatRequest

        request = ChatRequest(
            Id="session-router",
            Question="中车长客数字化转型",
            SelectedKbIds=["process_digital_dept"],
            ScopeSource="user_selected",
        )

        self.assertEqual(request.selected_kb_ids, ["process_digital_dept"])
        self.assertEqual(request.scope_source, "user_selected")
        payload = request.model_dump(by_alias=True)
        self.assertEqual(payload["SelectedKbIds"], ["process_digital_dept"])
        self.assertEqual(payload["ScopeSource"], "user_selected")

    async def test_rag_agent_uses_orchestrator_for_knowledge_question_with_request_context(self):
        import app.services.rag_agent_service as rag_agent_service_module

        orchestrator = FakeOrchestrator()
        service = rag_agent_service_module.RagAgentService(
            streaming=False,
            retrieval_orchestrator=orchestrator,
        )
        token = set_current_request_context(_context())
        self.addCleanup(reset_current_request_context, token)

        with (
            patch.object(
                rag_agent_service_module.document_access_service,
                "visible_kb_ids",
                return_value=["craft_dept", "process_digital_dept"],
            ),
            patch.object(
                rag_agent_service_module,
                "create_agent",
                side_effect=AssertionError("knowledge intent should not enter legacy agent"),
            ),
        ):
            answer = await service.query(
                "中车长客数字化转型",
                session_id="session-router",
                selected_kb_ids=["process_digital_dept"],
                scope_source="user_selected",
            )

        self.assertEqual(answer, "orchestrated:knowledge_qa:process_digital_dept")
        self.assertEqual(len(orchestrator.calls), 1)
        _context_arg, _query, decision = orchestrator.calls[0]
        self.assertEqual(decision.intent, "knowledge_qa")
        self.assertEqual(decision.selected_kb_ids, ["process_digital_dept"])
        self.assertEqual(decision.scope_source, "user_selected")
        self.assertEqual(answer.query_intent_diagnostics["intent"], "knowledge_qa")
        self.assertEqual(answer.query_intent_diagnostics["selected_kb_ids"], ["process_digital_dept"])

    async def test_rag_agent_orchestrates_operational_boundary_questions(self):
        import app.services.rag_agent_service as rag_agent_service_module

        orchestrator = FakeOrchestrator()
        service = rag_agent_service_module.RagAgentService(
            streaming=False,
            retrieval_orchestrator=orchestrator,
        )
        token = set_current_request_context(_context())
        self.addCleanup(reset_current_request_context, token)
        queries = [
            "Redis 内存高和 MySQL 慢查询同时出现，应该先看哪个？",
            "服务偶尔超时，但不是每次都超时，怎么排查？",
            "为什么 Redis TTL 设置了，但内存还是一直涨？",
            "Scoutflo SRE playbook 里的告警严重性级别表格有哪些？",
            "CPU throttling 会导致什么告警？如果同时出现 Pod NotReady 怎么办？",
        ]

        with (
            patch.object(
                rag_agent_service_module.document_access_service,
                "visible_kb_ids",
                return_value=["process_digital_dept"],
            ),
            patch.object(
                rag_agent_service_module,
                "create_agent",
                side_effect=AssertionError("operational knowledge intent should not enter legacy agent"),
            ),
        ):
            for query in queries:
                with self.subTest(query=query):
                    answer = await service.query(
                        query,
                        session_id=f"session-router-{len(orchestrator.calls)}",
                        selected_kb_ids=["process_digital_dept"],
                        scope_source="user_selected",
                    )

                    self.assertEqual(answer, "orchestrated:knowledge_qa:process_digital_dept")
                    self.assertEqual(answer.query_intent_diagnostics["intent"], "knowledge_qa")
                    self.assertEqual(
                        answer.query_intent_diagnostics["selected_kb_ids"],
                        ["process_digital_dept"],
                    )

        self.assertEqual(len(orchestrator.calls), len(queries))

    async def test_rag_agent_stream_emits_query_intent_diagnostics_for_orchestrated_path(self):
        import app.services.rag_agent_service as rag_agent_service_module

        orchestrator = FakeOrchestrator()
        service = rag_agent_service_module.RagAgentService(
            streaming=False,
            retrieval_orchestrator=orchestrator,
        )
        token = set_current_request_context(_context())
        self.addCleanup(reset_current_request_context, token)

        with patch.object(
            rag_agent_service_module.document_access_service,
            "visible_kb_ids",
            return_value=["craft_dept", "process_digital_dept"],
        ):
            chunks = [
                chunk
                async for chunk in service.query_stream(
                    "中车长客数字化转型",
                    session_id="session-router",
                    selected_kb_ids=["process_digital_dept"],
                    scope_source="user_selected",
                )
            ]

        diagnostics_chunks = [
            chunk for chunk in chunks if chunk.get("type") == "query_intent_diagnostics"
        ]
        self.assertEqual(len(diagnostics_chunks), 1)
        self.assertEqual(diagnostics_chunks[0]["data"]["intent"], "knowledge_qa")
        self.assertEqual(diagnostics_chunks[0]["data"]["selected_kb_ids"], ["process_digital_dept"])
        self.assertEqual(chunks[-1]["type"], "complete")

    async def test_chat_adapter_returns_query_intent_diagnostics_when_present(self):
        from app.enterprise.adapters.chat_adapter import ChatAdapter
        from app.enterprise.gateway.guardrail_providers import NoOpGuardrailProvider
        from app.enterprise.gateway.guardrail_service import GuardrailService
        from app.enterprise.gateway.rate_limit_service import NoOpRateLimitService
        from app.enterprise.gateway.request_gateway import RequestGateway
        from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
        from app.models.request import ChatRequest
        from app.services.rag_agent_service import QueryOrchestrationAnswer

        class FakeRagService:
            async def query(self, *_args, **_kwargs):
                return QueryOrchestrationAnswer(
                    "orchestrated answer",
                    {
                        "intent": "knowledge_qa",
                        "knowledge_action": "retrieve",
                        "selected_kb_ids": ["process_digital_dept"],
                    },
                )

        gateway = RequestGateway(
            audit_service=AuditService(sinks=[InMemoryAuditSink()]),
            guardrail_service=GuardrailService(providers=[NoOpGuardrailProvider()]),
            rate_limit_service=NoOpRateLimitService(),
        )

        response = await ChatAdapter(FakeRagService(), gateway=gateway).chat(
            ChatRequest(
                Id="session-router",
                Question="中车长客数字化转型",
                SelectedKbIds=["process_digital_dept"],
                ScopeSource="user_selected",
            ),
            {
                "X-Trace-Id": "trace-query-intent-http",
                "X-Request-Id": "request-query-intent-http",
                "X-User-Id": "user_demo_dept1",
                "X-Username": "demo_user_dept1",
                "X-Department-Id": "dept_1",
                "X-Department-Name": "Department 1",
                "X-Roles": "user",
            },
        )

        self.assertEqual(response["data"]["answer"], "orchestrated answer")
        self.assertEqual(
            response["data"]["query_intent_diagnostics"]["intent"],
            "knowledge_qa",
        )
        self.assertEqual(
            response["data"]["query_intent_diagnostics"]["selected_kb_ids"],
            ["process_digital_dept"],
        )


class KnowledgeFrontendScopeTests(unittest.TestCase):
    def test_static_app_sends_selected_kb_scope_with_chat_requests(self):
        from pathlib import Path

        static_root = Path(__file__).resolve().parents[1] / "static"
        js = (static_root / "app.js").read_text(encoding="utf-8")
        html = (static_root / "index.html").read_text(encoding="utf-8")

        self.assertIn("knowledgeScopeSelect", html)
        self.assertIn("selectedKnowledgeBaseIds", js)
        self.assertIn("buildChatRequestBody(message)", js)
        self.assertIn("SelectedKbIds: this.selectedKnowledgeBaseIds()", js)
        self.assertIn("ScopeSource: selectedKbIds.length > 0 ? 'user_selected' : 'auto_visible'", js)


if __name__ == "__main__":
    unittest.main()
