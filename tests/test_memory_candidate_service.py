import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.models.memory import AlertPatternPayload, MemoryRecord, MemoryStatus, MemoryType
from app.models.memory_candidate import AIOpsSessionState, SessionHistoryMessage
from app.services.memory_candidate_service import MemoryCandidateService
from app.services.memory_store import MemoryStore
from app.services.session_history_accessor import SessionHistoryAccessor


class FakeSessionHistoryAccessor:
    def __init__(self, messages: list[SessionHistoryMessage]):
        self.messages = messages
        self.calls: list[str] = []

    def get_history(self, session_id: str) -> list[SessionHistoryMessage]:
        self.calls.append(session_id)
        return list(self.messages)


class FakeAIOpsStateAccessor:
    def __init__(self, state: AIOpsSessionState | None):
        self.state = state
        self.calls: list[str] = []

    def get_state(self, session_id: str) -> AIOpsSessionState | None:
        self.calls.append(session_id)
        return self.state


class FakeCheckpointer:
    def __init__(self, checkpoint: dict):
        self.checkpoint = checkpoint
        self.configs: list[dict] = []

    def get(self, config: dict):
        self.configs.append(config)
        return (self.checkpoint,)


class FakeGraphState:
    def __init__(self, values: dict):
        self.values = values


class FakeGraph:
    def __init__(self, values: dict):
        self.values = values
        self.configs: list[dict] = []

    def get_state(self, config: dict):
        self.configs.append(config)
        return FakeGraphState(self.values)


class MemoryCandidateServiceTests(unittest.TestCase):
    def _store(self, tmpdir: str) -> MemoryStore:
        return MemoryStore(Path(tmpdir) / "memory.sqlite3")

    def test_session_history_accessor_normalizes_messages_without_raw_history(self):
        checkpointer = FakeCheckpointer(
            {
                "channel_values": {
                    "messages": [
                        SystemMessage(content="system"),
                        HumanMessage(content="CPUHigh 怎么处理"),
                        AIMessage(content="先确认 CPU 指标和最近发布。"),
                    ]
                }
            }
        )
        accessor = SessionHistoryAccessor(checkpointer)

        history = accessor.get_history("session-rag-1")

        self.assertEqual(
            [item.model_dump(exclude_none=True) for item in history],
            [
                {
                    "role": "user",
                    "content": "CPUHigh 怎么处理",
                    "message_index": 1,
                },
                {
                    "role": "assistant",
                    "content": "先确认 CPU 指标和最近发布。",
                    "message_index": 2,
                },
            ],
        )
        self.assertEqual(checkpointer.configs[0]["configurable"]["thread_id"], "session-rag-1")

    def test_session_history_accessor_api_dicts_keep_timestamp_field(self):
        checkpointer = FakeCheckpointer(
            {
                "channel_values": {
                    "messages": [
                        HumanMessage(content="CPUHigh 怎么处理"),
                    ]
                }
            }
        )
        accessor = SessionHistoryAccessor(checkpointer)

        history = accessor.get_history_dicts("session-rag-1")

        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[0]["content"], "CPUHigh 怎么处理")
        self.assertIn("timestamp", history[0])
        self.assertNotIn("message_index", history[0])

    def test_rag_agent_get_session_history_delegates_to_session_history_accessor(self):
        from app.services.rag_agent_service import RagAgentService

        fake_checkpointer = object()
        fake_history = [
            {
                "role": "user",
                "content": "CPUHigh 怎么处理",
                "timestamp": "2026-05-24T12:00:00",
            }
        ]
        service = object.__new__(RagAgentService)
        service.checkpointer = fake_checkpointer

        with patch("app.services.rag_agent_service.SessionHistoryAccessor") as accessor_cls:
            accessor_cls.return_value.get_history_dicts.return_value = fake_history

            history = RagAgentService.get_session_history(service, "session-rag-1")

        accessor_cls.assert_called_once_with(fake_checkpointer)
        accessor_cls.return_value.get_history_dicts.assert_called_once_with("session-rag-1")
        self.assertEqual(history, fake_history)

    def test_aiops_service_get_session_state_delegates_to_graph_state_accessor(self):
        from app.services.aiops_service import AIOpsService

        graph = FakeGraph(
            {
                "input": "CPUHigh on checkout-api",
                "plan": ["检查 CPU 利用率", "检查最近发布"],
                "past_steps": [],
                "response": "完成诊断。",
            }
        )
        service = object.__new__(AIOpsService)
        service.graph = graph

        state = AIOpsService.get_session_state(service, "session-aiops-1")

        self.assertEqual(state.session_id, "session-aiops-1")
        self.assertEqual(state.plan_steps, ["检查 CPU 利用率", "检查最近发布"])
        self.assertEqual(graph.configs[0]["configurable"]["thread_id"], "session-aiops-1")

    def test_extracts_rag_session_candidate_as_candidate_summary_only(self):
        messages = [
            SessionHistoryMessage(role="user", content="CPUHigh 第二次又从零开始了", message_index=0),
            SessionHistoryMessage(role="assistant", content="这次先看 CPU 指标和最近发布", message_index=1),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            service = MemoryCandidateService(
                store=store,
                session_history_accessor=FakeSessionHistoryAccessor(messages),
            )

            result = service.extract_from_rag_session("session-rag-1")

            self.assertIsNone(result.skipped_reason)
            self.assertEqual(len(result.records), 1)
            record = result.records[0]
            self.assertEqual(record.status, MemoryStatus.CANDIDATE)
            self.assertEqual(record.memory_type, MemoryType.CANDIDATE_SUMMARY)
            self.assertEqual(record.namespace, "memory://candidate/session")
            self.assertEqual(record.source, "session-candidate, NOT reviewed active memory")
            self.assertEqual(record.evidence["session_id"], "session-rag-1")
            self.assertEqual(record.evidence["source_type"], "rag_chat")
            self.assertIn("message_refs", record.evidence)
            self.assertNotIn("raw_messages", record.evidence)
            self.assertEqual(store.get(record.memory_id).status, MemoryStatus.CANDIDATE)

    def test_extracts_aiops_plan_template_candidate_from_normalized_state(self):
        state = AIOpsSessionState(
            session_id="session-aiops-1",
            input="CPUHigh on checkout-api",
            plan_steps=["检查 CPU 利用率", "检查最近发布", "检查错误日志"],
            past_steps=[],
            response="根因结论: 最近发布导致 CPU 飙高。",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            service = MemoryCandidateService(
                store=store,
                aiops_state_accessor=FakeAIOpsStateAccessor(state),
            )

            result = service.extract_from_aiops_session("session-aiops-1")

            self.assertIsNone(result.skipped_reason)
            self.assertEqual(len(result.records), 1)
            record = result.records[0]
            self.assertEqual(record.status, MemoryStatus.CANDIDATE)
            self.assertEqual(record.memory_type, MemoryType.PLAN_TEMPLATE)
            self.assertEqual(record.namespace, "memory://oncall/plan-templates")
            self.assertEqual(record.payload.alert_type, "CPUHigh on checkout-api")
            self.assertEqual(record.payload.plan_steps, state.plan_steps)
            self.assertEqual(record.payload.evidence_refs[0]["session_id"], "session-aiops-1")
            self.assertNotIn("raw_memory_saver_history", record.evidence)

    def test_duplicate_plan_candidate_is_not_inserted_twice(self):
        first_state = AIOpsSessionState(
            session_id="session-aiops-1",
            input="CPUHigh on checkout-api",
            plan_steps=["检查 CPU 利用率", "检查最近发布"],
            past_steps=[],
            response="完成诊断。",
        )
        second_state = first_state.model_copy(update={"session_id": "session-aiops-2"})

        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            service = MemoryCandidateService(
                store=store,
                aiops_state_accessor=FakeAIOpsStateAccessor(first_state),
            )
            first = service.extract_from_aiops_session("session-aiops-1").records[0]

            service.aiops_state_accessor = FakeAIOpsStateAccessor(second_state)
            second_result = service.extract_from_aiops_session("session-aiops-2")

            candidates = store.list_memories(
                memory_type=MemoryType.PLAN_TEMPLATE,
                status=MemoryStatus.CANDIDATE,
            )
            self.assertEqual(len(candidates), 1)
            self.assertEqual(second_result.records[0].memory_id, first.memory_id)
            self.assertEqual(second_result.action, "duplicate")

    def test_conflicting_alert_candidate_is_stored_as_conflict_not_active(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            service = MemoryCandidateService(store=store)
            active = self._alert_record(
                memory_id="mem_active_cpu",
                root_cause="traffic spike",
                fix="scale replicas",
                status=MemoryStatus.ACTIVE,
            )
            store.upsert(active)

            candidate = self._alert_record(
                memory_id="mem_candidate_cpu",
                root_cause="bad deploy",
                fix="rollback release",
                status=MemoryStatus.CANDIDATE,
            )

            stored = service.store_candidate(candidate)

            self.assertEqual(stored.status, MemoryStatus.CONFLICT)
            self.assertEqual(stored.evidence["conflicts_with"], ["mem_active_cpu"])
            self.assertEqual(store.get("mem_candidate_cpu").status, MemoryStatus.CONFLICT)

    def test_store_candidate_forces_candidate_status_without_promotion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            service = MemoryCandidateService(store=store)
            record = self._alert_record(
                memory_id="mem_unreviewed_cpu",
                root_cause="traffic spike",
                fix="scale replicas",
                status=MemoryStatus.ACTIVE,
            )

            stored = service.store_candidate(record)

            self.assertEqual(stored.status, MemoryStatus.CANDIDATE)
            self.assertEqual(store.get("mem_unreviewed_cpu").status, MemoryStatus.CANDIDATE)

    def _alert_record(
        self,
        *,
        memory_id: str,
        root_cause: str,
        fix: str,
        status: MemoryStatus,
    ) -> MemoryRecord:
        return MemoryRecord(
            memory_id=memory_id,
            owner_id="default",
            namespace="memory://oncall/alert-patterns",
            memory_type=MemoryType.ALERT_PATTERN,
            content=f"CPUHigh root cause is {root_cause}; fix is {fix}.",
            summary=f"CPUHigh {root_cause} {fix}",
            payload=AlertPatternPayload(
                alert_name="CPUHigh",
                service="checkout-api",
                signal_keys=["cpu_usage", "deployment"],
                root_cause=root_cause,
                fix=fix,
                evidence_refs=[
                    {
                        "evidence_type": "session_candidate",
                        "session_id": "session-aiops-1",
                        "source_type": "aiops_diagnosis",
                    }
                ],
            ),
            source="session-candidate, NOT reviewed active memory",
            evidence={
                "evidence_type": "session_candidate",
                "session_id": "session-aiops-1",
                "source_type": "aiops_diagnosis",
            },
            status=status,
        )


if __name__ == "__main__":
    unittest.main()
