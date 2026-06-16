import unittest
from unittest.mock import patch

from app.models.memory import MemoryStatus, MemoryType
from app.services.memory_retrieval_service import (
    MemoryRetrievalQuery,
    MemoryRetrievalResponse,
    MemoryRetrievalResult,
)
from app.tools.memory_tool import retrieve_memory


class FakeMemoryRetrievalService:
    def __init__(self, response: MemoryRetrievalResponse):
        self.response = response
        self.calls: list[MemoryRetrievalQuery] = []

    def retrieve(self, query: MemoryRetrievalQuery) -> MemoryRetrievalResponse:
        self.calls.append(query)
        return self.response


class MemoryToolTests(unittest.TestCase):
    def test_retrieve_memory_returns_content_and_independent_artifact(self):
        response = MemoryRetrievalResponse(
            query="OOM 怎么处理",
            owner_id="default",
            namespaces=["memory://oncall/alert-patterns"],
            memory_types=[MemoryType.ALERT_PATTERN],
            memory_results=[
                MemoryRetrievalResult(
                    memory_id="mem_alert_high_memory",
                    owner_id="default",
                    namespace="memory://oncall/alert-patterns",
                    memory_type=MemoryType.ALERT_PATTERN,
                    status=MemoryStatus.ACTIVE,
                    content="HighMemoryUsage with OOM needs heap dump capture before restart.",
                    summary="HighMemoryUsage OOM heap dump before restart",
                    score=2.0,
                    matched_terms=["oom", "memory"],
                    evidence_refs=[
                        {
                            "evidence_type": "synthetic_design_fixture",
                            "note": "not real session evidence",
                        }
                    ],
                    payload={"alert_name": "HighMemoryUsage"},
                    source="design-fixture, NOT real session evidence",
                    tags=["oom"],
                    updated_at="2026-05-24T19:00:00",
                )
            ],
            empty_message="No active memory matched the query.",
            trace={"candidate_count": 1, "matched_count": 1, "returned_count": 1},
        )
        fake_service = FakeMemoryRetrievalService(response)

        import app.tools.memory_tool as memory_tool_module

        with patch.object(memory_tool_module, "memory_retrieval_service", fake_service):
            content, artifact = retrieve_memory.func(
                "OOM 怎么处理",
                namespaces=["memory://oncall/alert-patterns"],
                memory_types=["alert_pattern"],
            )

        self.assertIn("【记忆 1】", content)
        self.assertIn("HighMemoryUsage OOM heap dump before restart", content)
        self.assertEqual(len(fake_service.calls), 1)
        self.assertEqual(fake_service.calls[0].query, "OOM 怎么处理")
        self.assertEqual(fake_service.calls[0].namespaces, ["memory://oncall/alert-patterns"])
        self.assertEqual(fake_service.calls[0].memory_types, [MemoryType.ALERT_PATTERN])

        self.assertEqual(artifact["query"], "OOM 怎么处理")
        self.assertEqual(artifact["owner_id"], "default")
        self.assertEqual(artifact["status"], "ok")
        self.assertEqual(artifact["namespaces"], ["memory://oncall/alert-patterns"])
        self.assertEqual(artifact["memory_types"], ["alert_pattern"])
        self.assertEqual(artifact["trace"]["candidate_count"], 1)
        self.assertEqual(artifact["memory_results"][0]["memory_id"], "mem_alert_high_memory")
        self.assertIn("evidence_refs", artifact["memory_results"][0])
        self.assertNotIn("source_ref", artifact["memory_results"][0])
        self.assertNotIn("citation_text", artifact["memory_results"][0])

    def test_retrieve_memory_returns_empty_artifact_without_citation_fields(self):
        response = MemoryRetrievalResponse(
            query="不存在的记忆",
            owner_id="default",
            memory_results=[],
            empty_message="No active memory matched the query.",
            trace={"candidate_count": 0, "matched_count": 0, "returned_count": 0},
        )
        fake_service = FakeMemoryRetrievalService(response)

        import app.tools.memory_tool as memory_tool_module

        with patch.object(memory_tool_module, "memory_retrieval_service", fake_service):
            content, artifact = retrieve_memory.func("不存在的记忆")

        self.assertEqual(content, "No active memory matched the query.")
        self.assertEqual(artifact["status"], "empty")
        self.assertEqual(artifact["memory_results"], [])
        self.assertNotIn("source_ref", artifact)
        self.assertNotIn("citation_text", artifact)

    def test_rag_agent_default_tools_do_not_include_memory_tool(self):
        import app.services.rag_agent_service as rag_agent_service_module

        self.assertNotIn(
            "retrieve_memory",
            [tool.name for tool in rag_agent_service_module.RagAgentService().tools],
        )


if __name__ == "__main__":
    unittest.main()
