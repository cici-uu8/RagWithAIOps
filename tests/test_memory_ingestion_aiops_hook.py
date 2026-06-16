import tempfile
import unittest
from pathlib import Path

from app.models.memory_candidate import AIOpsSessionState
from app.services.aiops_service import AIOpsService
from app.services.memory_evidence_store import MemoryEvidenceStore


class FakeGraph:
    def __init__(self, values: dict):
        self.values = values

    def get_state(self, _config: dict):
        class State:
            def __init__(self, values: dict):
                self.values = values

        return State(self.values)


class MemoryIngestionHookTests(unittest.IsolatedAsyncioTestCase):
    async def test_diagnose_can_ingest_l0_evidence_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_store_path = Path(tmpdir) / "memory_evidence.sqlite3"
            refs_dir = Path(tmpdir) / "refs"

            service = AIOpsService.__new__(AIOpsService)
            service.graph = FakeGraph(
                {
                    "input": "service-a CPUHigh alert triggered again",
                    "plan": ["check cpu", "check deploy"],
                    "past_steps": [],
                    "response": "Root cause: cache memory leak.",
                }
            )

            async def fake_execute(*_args, **_kwargs):
                yield {
                    "type": "complete",
                    "stage": "complete",
                    "message": "任务执行完成",
                    "response": "Root cause: cache memory leak.",
                }

            service.execute = fake_execute

            events = [
                event
                async for event in service.diagnose(
                    session_id="session-ingest-hook",
                    query="service-a CPUHigh alert triggered again",
                    memory_owner_id="ops-team",
                    enable_memory_evidence_ingestion=True,
                    memory_evidence_store_path=str(evidence_store_path),
                )
            ]

            self.assertEqual(events[0]["stage"], "diagnosis_complete")
            self.assertTrue(events[0]["memory_evidence_ingested"])
            self.assertIn("memory_evidence_id", events[0])

            store = MemoryEvidenceStore(store_path=evidence_store_path, refs_dir=refs_dir)
            evidence = store.get(events[0]["memory_evidence_id"])

            self.assertIsNotNone(evidence)
            self.assertEqual(evidence.session_id, "session-ingest-hook")
            self.assertEqual(evidence.owner_id, "ops-team")
            self.assertIn("cache memory leak", evidence.final_response_preview)


if __name__ == "__main__":
    unittest.main()
