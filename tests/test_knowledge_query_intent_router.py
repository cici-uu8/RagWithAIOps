import json
import unittest
from pathlib import Path

from app.enterprise.context import RequestContext


def _context() -> RequestContext:
    return RequestContext(
        request_id="request-query-intent",
        trace_id="trace-query-intent",
        user_id="user_demo_dept1",
        username="demo_user_dept1",
        department_id="dept_1",
        department_name="Department 1",
        roles=["user"],
    )


class KnowledgeQueryIntentRouterTests(unittest.TestCase):
    def test_routes_enterprise_knowledge_question_to_retrieve_with_auto_scope(self):
        from app.enterprise.rag.query_intent import QueryIntentRouter, QueryScope

        decision = QueryIntentRouter().classify(
            "中车长客数字化转型怎么做？",
            context=_context(),
            scope=QueryScope(visible_kb_ids=["craft_dept", "process_digital_dept"]),
        )

        self.assertEqual(decision.intent, "knowledge_qa")
        self.assertEqual(decision.knowledge_action, "retrieve")
        self.assertEqual(decision.selected_kb_ids, ["process_digital_dept"])
        self.assertEqual(decision.scope_source, "auto_visible")
        self.assertTrue(decision.requires_retrieval)
        self.assertIn("数字化", decision.reason)

    def test_user_selected_scope_is_a_strong_constraint(self):
        from app.enterprise.rag.query_intent import QueryIntentRouter, QueryScope

        decision = QueryIntentRouter().classify(
            "中车长客数字化转型怎么做？",
            context=_context(),
            scope=QueryScope(
                selected_kb_ids=["craft_dept"],
                visible_kb_ids=["craft_dept", "process_digital_dept"],
                scope_source="user_selected",
            ),
        )

        self.assertEqual(decision.intent, "knowledge_qa")
        self.assertEqual(decision.knowledge_action, "retrieve")
        self.assertEqual(decision.selected_kb_ids, ["craft_dept"])
        self.assertEqual(decision.scope_source, "user_selected")

    def test_blocks_query_targeting_invisible_kb_instead_of_retrieving_visible_kb(self):
        from app.enterprise.rag.query_intent import QueryIntentRouter, QueryScope

        decision = QueryIntentRouter().classify(
            "工艺部现场设备工艺版第 1 页内容",
            context=_context(),
            scope=QueryScope(visible_kb_ids=["process_digital_dept"]),
        )

        self.assertEqual(decision.intent, "permission_filtered")
        self.assertEqual(decision.knowledge_action, "handoff")
        self.assertEqual(decision.handoff, "permission_filtered")
        self.assertFalse(decision.requires_retrieval)
        self.assertEqual(decision.metadata["blocked_kb_ids"], ["craft_dept"])

    def test_routes_document_list_before_generic_knowledge_qa(self):
        from app.enterprise.rag.query_intent import QueryIntentRouter, QueryScope

        decision = QueryIntentRouter().classify(
            "这个知识库相关文件有什么？",
            context=_context(),
            scope=QueryScope(visible_kb_ids=["process_digital_dept"]),
        )

        self.assertEqual(decision.intent, "document_list")
        self.assertEqual(decision.knowledge_action, "list")
        self.assertTrue(decision.requires_retrieval)

    def test_routes_document_read_and_extracts_file_name(self):
        from app.enterprise.rag.query_intent import QueryIntentRouter, QueryScope

        decision = QueryIntentRouter().classify(
            "帮我总结 线上故障处理手册.pdf 这个文件",
            context=_context(),
            scope=QueryScope(visible_kb_ids=["process_digital_dept"]),
        )

        self.assertEqual(decision.intent, "document_read")
        self.assertEqual(decision.knowledge_action, "read")
        self.assertEqual(decision.metadata["file_name"], "线上故障处理手册.pdf")

    def test_routes_database_and_high_risk_away_from_knowledge_tools(self):
        from app.enterprise.rag.query_intent import QueryIntentRouter

        router = QueryIntentRouter()
        database = router.classify("查询订单表有哪些字段", context=_context())
        high_risk = router.classify("把订单金额改成 100", context=_context())

        self.assertEqual(database.intent, "database")
        self.assertEqual(database.knowledge_action, "handoff")
        self.assertEqual(database.handoff, "database")
        self.assertFalse(database.requires_retrieval)
        self.assertIn(high_risk.intent, {"database", "human_review"})
        self.assertEqual(high_risk.knowledge_action, "handoff")

    def test_routes_operational_boundary_questions_to_knowledge_qa(self):
        from app.enterprise.rag.query_intent import QueryIntentRouter, QueryScope

        router = QueryIntentRouter()
        queries = [
            "Redis 内存高和 MySQL 慢查询同时出现，应该先看哪个？",
            "服务偶尔超时，但不是每次都超时，怎么排查？",
            "Pod 没有崩溃，但一直处于 Pending 状态，是什么原因？",
            "为什么 Redis TTL 设置了，但内存还是一直涨？",
            "Scoutflo SRE playbook 里的告警严重性级别表格有哪些？",
            "CPU throttling 会导致什么告警？如果同时出现 Pod NotReady 怎么办？",
        ]

        for query in queries:
            with self.subTest(query=query):
                decision = router.classify(
                    query,
                    context=_context(),
                    scope=QueryScope(
                        selected_kb_ids=["process_digital_dept"],
                        visible_kb_ids=["process_digital_dept"],
                        scope_source="user_selected",
                    ),
                )

                self.assertEqual(decision.intent, "knowledge_qa")
                self.assertEqual(decision.knowledge_action, "retrieve")
                self.assertEqual(decision.selected_kb_ids, ["process_digital_dept"])
                self.assertEqual(decision.scope_source, "user_selected")
                self.assertTrue(decision.requires_retrieval)

    def test_routes_permission_request_and_plain_chat(self):
        from app.enterprise.rag.query_intent import QueryIntentRouter

        router = QueryIntentRouter()
        permission = router.classify("申请工艺部知识库权限", context=_context())
        plain = router.classify("你好", context=_context())

        self.assertEqual(permission.intent, "permission_request")
        self.assertEqual(permission.knowledge_action, "handoff")
        self.assertEqual(permission.handoff, "permission_request")
        self.assertEqual(plain.intent, "plain_chat")
        self.assertEqual(plain.knowledge_action, "none")
        self.assertFalse(plain.requires_retrieval)

    def test_router_evalset_cases_match_expected_intent_and_action(self):
        from app.enterprise.rag.query_intent import QueryIntentRouter, QueryScope

        evalset_path = (
            Path(__file__).resolve().parents[1]
            / "evals"
            / "enterprise"
            / "evalsets"
            / "knowledge_query_intent_evalset.jsonl"
        )
        cases = [
            json.loads(line)
            for line in evalset_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        router = QueryIntentRouter()

        for case in cases:
            with self.subTest(case=case["id"]):
                decision = router.classify(
                    case["query"],
                    context=_context(),
                    scope=QueryScope(
                        visible_kb_ids=case.get(
                            "visible_kb_ids",
                            ["craft_dept", "process_digital_dept"],
                        ),
                        selected_kb_ids=case.get("selected_kb_ids", []),
                        scope_source=case.get("scope_source", "auto_visible"),
                    ),
                )

                self.assertEqual(decision.intent, case["expected_intent"])
                self.assertEqual(decision.knowledge_action, case["expected_action"])
                if case.get("expected_handoff"):
                    self.assertEqual(decision.handoff, case["expected_handoff"])
                if case.get("expected_selected_kb_ids") is not None:
                    self.assertEqual(
                        decision.selected_kb_ids,
                        case["expected_selected_kb_ids"],
                    )


if __name__ == "__main__":
    unittest.main()
