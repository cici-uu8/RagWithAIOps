import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from app.enterprise.context import (
    RequestContext,
    reset_current_request_context,
    set_current_request_context,
)
from app.models.session_memory import (
    SessionMemoryMessage,
    SessionMemorySnapshot,
    utc_now,
)
from app.services.session_memory_store import InMemorySessionMemoryStore


def _context() -> RequestContext:
    return RequestContext(
        request_id="request-rag-memory",
        trace_id="trace-rag-memory",
        user_id="user_demo_dept1",
        username="demo_user_dept1",
        department_id="dept_1",
        department_name="Department 1",
        roles=["user"],
    )


class CountingMemoryStore(InMemorySessionMemoryStore):
    def __init__(self):
        super().__init__()
        self.get_snapshot_calls = 0
        self.cleanup_calls = 0

    def get_snapshot(self, session_id: str, owner_id: str):
        self.get_snapshot_calls += 1
        return super().get_snapshot(session_id, owner_id)

    def cleanup_expired(self, *, ttl_seconds: int, owner_id: str | None = None) -> int:
        self.cleanup_calls += 1
        return super().cleanup_expired(ttl_seconds=ttl_seconds, owner_id=owner_id)


class StoreWithoutCleanup:
    def get_snapshot(self, *_args, **_kwargs):
        raise AssertionError("active mode must be blocked without cleanup policy")

    def upsert_snapshot(self, snapshot):
        return snapshot

    def append_live_message(self, *_args, **_kwargs):
        raise AssertionError("active mode must be blocked without cleanup policy")

    def clear(self):
        return None


async def _fake_profile(_context, *, include_gateway_tools=False):
    return {
        "user": {
            "user_id": "user_demo_dept1",
            "username": "demo_user_dept1",
            "department_name": "Department 1",
            "roles": ["user"],
        },
        "visible_tools": ["retrieve_knowledge"],
        "visible_kb_ids": ["process_digital_dept"],
        "feature_flags": {},
        "unavailable_reasons": {},
    }


class FakeOrchestrator:
    async def execute(self, _context, *, query, decision):
        from app.enterprise.rag.retrieval_orchestrator import OrchestrationResult

        return OrchestrationResult(
            intent=decision.intent,
            knowledge_action=decision.knowledge_action,
            handoff=decision.handoff,
            answer=f"orchestrated answer for {query}",
            actual_tool_called=False,
            actual_tool_name="",
            diagnostics=decision.to_diagnostics(),
        )


class RagAgentMemoryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import app.services.rag_agent_service as rag_agent_service_module

        self.module = rag_agent_service_module
        self.context_token = set_current_request_context(_context())
        self.addCleanup(reset_current_request_context, self.context_token)
        self.profile_patch = patch.object(
            rag_agent_service_module.profile_service,
            "build_profile",
            AsyncMock(side_effect=_fake_profile),
        )
        self.profile_patch.start()
        self.addCleanup(self.profile_patch.stop)

    async def test_memory_mode_off_does_not_read_or_inject(self):
        service = self.module.RagAgentService(
            streaming=False,
            session_memory_store=StoreWithoutCleanup(),
        )

        with patch.object(self.module.config, "rag_session_memory_mode", "off"):
            prompt = await service._build_runtime_system_prompt(session_id="session-1")

        self.assertNotIn(self.module.SESSION_MEMORY_PROMPT_HEADER, prompt)

    async def test_shadow_reads_snapshot_without_prompt_injection(self):
        store = CountingMemoryStore()
        store.upsert_snapshot(
            SessionMemorySnapshot(
                session_id="session-1",
                owner_id="user_demo_dept1",
                latest_summary="已确认 Redis backlog",
            )
        )
        service = self.module.RagAgentService(
            streaming=False,
            session_memory_store=store,
        )

        with patch.object(self.module.config, "rag_session_memory_mode", "shadow"):
            prompt = await service._build_runtime_system_prompt(session_id="session-1")

        self.assertEqual(store.get_snapshot_calls, 1)
        self.assertGreaterEqual(store.cleanup_calls, 1)
        self.assertNotIn(self.module.SESSION_MEMORY_PROMPT_HEADER, prompt)

    async def test_active_injects_bounded_non_citation_memory_context(self):
        store = InMemorySessionMemoryStore()
        store.upsert_snapshot(
            SessionMemorySnapshot(
                session_id="session-1",
                owner_id="user_demo_dept1",
                latest_summary="source_ref citation SourceRef 已确认 Redis backlog " * 20,
                live_tail=[
                    SessionMemoryMessage(role="user", content="继续排查"),
                    SessionMemoryMessage(role="assistant", content="先看队列长度"),
                ],
            )
        )
        service = self.module.RagAgentService(
            streaming=False,
            session_memory_store=store,
        )

        with (
            patch.object(self.module.config, "rag_session_memory_mode", "active"),
            patch.object(self.module.config, "rag_session_memory_max_prompt_chars", 120),
        ):
            prompt = await service._build_runtime_system_prompt(session_id="session-1")

        memory_text = prompt.split(self.module.SESSION_MEMORY_PROMPT_HEADER, 1)[1]
        self.assertIn("Redis backlog", memory_text)
        self.assertIn("[已截断]", memory_text)
        self.assertLessEqual(len(memory_text.strip()), 120)
        self.assertNotIn("source_ref", memory_text.lower())
        self.assertNotIn("sourceref", memory_text.lower())
        self.assertNotIn("citation", memory_text.lower())

    async def test_stale_summary_is_not_injected(self):
        store = InMemorySessionMemoryStore()
        store.upsert_snapshot(
            SessionMemorySnapshot(
                session_id="session-1",
                owner_id="user_demo_dept1",
                latest_summary="过期摘要不应该进入 prompt",
                updated_at=utc_now() - timedelta(days=2),
            )
        )
        service = self.module.RagAgentService(
            streaming=False,
            session_memory_store=store,
        )

        with (
            patch.object(self.module.config, "rag_session_memory_mode", "active"),
            patch.object(self.module.config, "rag_session_memory_snapshot_ttl_seconds", 3600),
        ):
            prompt = await service._build_runtime_system_prompt(session_id="session-1")

        self.assertNotIn("过期摘要", prompt)
        self.assertNotIn(self.module.SESSION_MEMORY_PROMPT_HEADER, prompt)

    async def test_active_without_cleanup_policy_falls_back_to_off(self):
        service = self.module.RagAgentService(
            streaming=False,
            session_memory_store=StoreWithoutCleanup(),
        )

        with patch.object(self.module.config, "rag_session_memory_mode", "active"):
            prompt = await service._build_runtime_system_prompt(session_id="session-1")

        self.assertNotIn(self.module.SESSION_MEMORY_PROMPT_HEADER, prompt)

    async def test_successful_query_records_live_tail_when_shadow_enabled(self):
        store = InMemorySessionMemoryStore()
        service = self.module.RagAgentService(
            streaming=False,
            retrieval_orchestrator=FakeOrchestrator(),
            session_memory_store=store,
        )

        with (
            patch.object(self.module.config, "rag_session_memory_mode", "shadow"),
            patch.object(
                self.module.document_access_service,
                "visible_kb_ids",
                return_value=["process_digital_dept"],
            ),
        ):
            answer = await service.query(
                "中车长客数字化转型",
                session_id="session-1",
                selected_kb_ids=["process_digital_dept"],
                scope_source="user_selected",
            )

        snapshot = store.get_snapshot("session-1", "user_demo_dept1")
        self.assertIsNotNone(snapshot)
        self.assertEqual([message.role for message in snapshot.live_tail], ["user", "assistant"])
        self.assertEqual(snapshot.live_tail[0].content, "中车长客数字化转型")
        self.assertEqual(snapshot.live_tail[1].content, str(answer))


if __name__ == "__main__":
    unittest.main()
