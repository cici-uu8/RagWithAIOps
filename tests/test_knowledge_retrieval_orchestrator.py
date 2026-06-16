import unittest

from app.enterprise.context import RequestContext
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink


def _context() -> RequestContext:
    return RequestContext(
        request_id="request-orchestrator",
        trace_id="trace-orchestrator",
        user_id="user_demo_dept1",
        username="demo_user_dept1",
        department_id="dept_1",
        department_name="Department 1",
        roles=["user"],
    )


class FakeFacade:
    def __init__(self):
        self.calls = []

    async def execute(self, context, tool_id, arguments):
        self.calls.append((context, tool_id, arguments))
        if tool_id == "list_knowledge_documents":
            return {
                "documents": [{"doc_id": "doc-guide", "file_name": "数字化方案.md", "kb_id": "process_digital_dept"}],
                "total": 1,
                "kb_ids": ["process_digital_dept"],
                "message": "",
            }
        if tool_id == "retrieve_knowledge":
            return "检索上下文：中车长客数字化转型方案来自流程与数字化部资料。"
        raise AssertionError(f"unexpected tool: {tool_id}")


class KnowledgeRetrievalOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_document_list_executes_list_tool_through_facade_and_audits_decision(self):
        from app.enterprise.rag.query_intent import QueryIntentRouter, QueryScope
        from app.enterprise.rag.retrieval_orchestrator import KnowledgeRetrievalOrchestrator

        sink = InMemoryAuditSink()
        audit_service = AuditService(sinks=[sink])
        facade = FakeFacade()
        decision = QueryIntentRouter().classify(
            "相关文件有什么",
            context=_context(),
            scope=QueryScope(selected_kb_ids=["process_digital_dept"], scope_source="user_selected"),
        )

        result = await KnowledgeRetrievalOrchestrator(
            tool_execution_facade=facade,
            audit_service=audit_service,
        ).execute(_context(), query="相关文件有什么", decision=decision)

        self.assertEqual(
            [(call[1], call[2]) for call in facade.calls],
            [("list_knowledge_documents", {"kb_id": "process_digital_dept"})],
        )
        self.assertEqual(result.intent, "document_list")
        self.assertEqual(result.knowledge_action, "list")
        self.assertTrue(result.actual_tool_called)
        self.assertEqual(result.actual_tool_name, "list_knowledge_documents")
        self.assertIn("数字化方案.md", result.answer)
        self.assertTrue(
            any(
                event.event_type == "query_intent_decision"
                and event.metadata["intent"] == "document_list"
                and event.metadata["actual_tool_called"] is True
                for event in sink.events
            )
        )

    async def test_knowledge_qa_executes_retrieve_with_selected_scope(self):
        from app.enterprise.rag.query_intent import QueryIntentRouter, QueryScope
        from app.enterprise.rag.retrieval_orchestrator import KnowledgeRetrievalOrchestrator

        facade = FakeFacade()
        decision = QueryIntentRouter().classify(
            "中车长客数字化转型",
            context=_context(),
            scope=QueryScope(selected_kb_ids=["process_digital_dept"], scope_source="user_selected"),
        )

        result = await KnowledgeRetrievalOrchestrator(tool_execution_facade=facade).execute(
            _context(),
            query="中车长客数字化转型",
            decision=decision,
        )

        self.assertEqual(
            [(call[1], call[2]) for call in facade.calls],
            [
                (
                    "retrieve_knowledge",
                    {
                        "query": "中车长客数字化转型",
                        "knowledge_base_ids": ["process_digital_dept"],
                    },
                )
            ],
        )
        self.assertEqual(result.intent, "knowledge_qa")
        self.assertEqual(result.actual_tool_name, "retrieve_knowledge")
        self.assertIn("检索上下文", result.answer)
        self.assertEqual(result.diagnostics["selected_kb_ids"], ["process_digital_dept"])

    async def test_knowledge_qa_adds_scope_note_for_non_oncall_enterprise_topic(self):
        from app.enterprise.rag.query_intent import QueryIntentRouter, QueryScope
        from app.enterprise.rag.retrieval_orchestrator import KnowledgeRetrievalOrchestrator

        facade = FakeFacade()
        decision = QueryIntentRouter().classify(
            "中车长客的数字化转型成果有哪些？",
            context=_context(),
            scope=QueryScope(selected_kb_ids=["process_digital_dept"], scope_source="user_selected"),
        )

        result = await KnowledgeRetrievalOrchestrator(tool_execution_facade=facade).execute(
            _context(),
            query="中车长客的数字化转型成果有哪些？",
            decision=decision,
        )

        self.assertIn("检索上下文", result.answer)
        self.assertIn("非故障排查", result.answer)
        self.assertIn("知识范围", result.answer)

    async def test_knowledge_qa_carries_retrieval_diagnostics_from_tool_artifact(self):
        from app.enterprise.rag.query_intent import QueryIntentRouter, QueryScope
        from app.enterprise.rag.retrieval_orchestrator import KnowledgeRetrievalOrchestrator

        class DiagnosticsFacade(FakeFacade):
            async def execute(self, context, tool_id, arguments):
                self.calls.append((context, tool_id, arguments))
                return "没有找到相关信息。", {
                    "diagnostics": {
                        "no_result_reason": "retrieval_no_hit",
                        "selected_kb_ids": ["process_digital_dept"],
                        "tool_called": True,
                    }
                }

        decision = QueryIntentRouter().classify(
            "中车长客数字化转型",
            context=_context(),
            scope=QueryScope(selected_kb_ids=["process_digital_dept"], scope_source="user_selected"),
        )

        result = await KnowledgeRetrievalOrchestrator(
            tool_execution_facade=DiagnosticsFacade()
        ).execute(_context(), query="中车长客数字化转型", decision=decision)

        self.assertEqual(result.answer, "没有找到相关信息。")
        self.assertEqual(result.diagnostics["rag_diagnostics"]["no_result_reason"], "retrieval_no_hit")
        self.assertEqual(result.diagnostics["rag_diagnostics"]["selected_kb_ids"], ["process_digital_dept"])

    async def test_query_intent_audit_includes_tool_diagnostics_for_no_hit_explanation(self):
        from app.enterprise.rag.query_intent import QueryIntentRouter, QueryScope
        from app.enterprise.rag.retrieval_orchestrator import KnowledgeRetrievalOrchestrator

        class DiagnosticsFacade(FakeFacade):
            async def execute(self, context, tool_id, arguments):
                self.calls.append((context, tool_id, arguments))
                return "没有找到相关信息。", {
                    "diagnostics": {
                        "no_result_reason": "retrieval_no_hit",
                        "selected_kb_ids": ["process_digital_dept"],
                        "tool_called": True,
                    }
                }

        sink = InMemoryAuditSink()
        audit_service = AuditService(sinks=[sink])
        decision = QueryIntentRouter().classify(
            "中车长客数字化转型",
            context=_context(),
            scope=QueryScope(selected_kb_ids=["process_digital_dept"], scope_source="user_selected"),
        )

        await KnowledgeRetrievalOrchestrator(
            tool_execution_facade=DiagnosticsFacade(),
            audit_service=audit_service,
        ).execute(_context(), query="中车长客数字化转型", decision=decision)

        event = next(event for event in sink.events if event.event_type == "query_intent_decision")
        self.assertEqual(event.metadata["actual_tool_name"], "retrieve_knowledge")
        self.assertEqual(event.metadata["rag_diagnostics"]["no_result_reason"], "retrieval_no_hit")
        self.assertEqual(event.metadata["rag_diagnostics"]["tool_called"], True)

    async def test_document_read_uses_retrieve_tool_with_file_filter(self):
        from app.enterprise.rag.query_intent import QueryIntentRouter, QueryScope
        from app.enterprise.rag.retrieval_orchestrator import KnowledgeRetrievalOrchestrator

        facade = FakeFacade()
        decision = QueryIntentRouter().classify(
            "总结 线上故障处理手册.pdf",
            context=_context(),
            scope=QueryScope(visible_kb_ids=["process_digital_dept"]),
        )

        await KnowledgeRetrievalOrchestrator(tool_execution_facade=facade).execute(
            _context(),
            query="总结 线上故障处理手册.pdf",
            decision=decision,
        )

        self.assertEqual(
            facade.calls[0][1:],
            (
                "retrieve_knowledge",
                {
                    "query": "总结 线上故障处理手册.pdf",
                    "knowledge_base_ids": ["process_digital_dept"],
                    "file_name": "线上故障处理手册.pdf",
                },
            ),
        )

    async def test_handoff_intents_do_not_call_knowledge_tools(self):
        from app.enterprise.rag.query_intent import QueryIntentRouter
        from app.enterprise.rag.retrieval_orchestrator import KnowledgeRetrievalOrchestrator

        facade = FakeFacade()
        decision = QueryIntentRouter().classify("查询订单表有哪些字段", context=_context())

        result = await KnowledgeRetrievalOrchestrator(tool_execution_facade=facade).execute(
            _context(),
            query="查询订单表有哪些字段",
            decision=decision,
        )

        self.assertEqual(facade.calls, [])
        self.assertEqual(result.intent, "database")
        self.assertEqual(result.handoff, "database")
        self.assertFalse(result.actual_tool_called)
        self.assertIn("数据库", result.answer)
        self.assertIn("权限", result.answer)
        self.assertIn("表", result.answer)


if __name__ == "__main__":
    unittest.main()
