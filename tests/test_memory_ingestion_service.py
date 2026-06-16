import tempfile
import unittest
from pathlib import Path

from app.models.memory_candidate import AIOpsPastStep, AIOpsSessionState
from app.services.memory_evidence_store import MemoryEvidenceStore
from app.services.memory_ingestion_service import MemoryIngestionService


class MemoryIngestionServiceTests(unittest.TestCase):
    def _store(self, tmpdir: str) -> MemoryEvidenceStore:
        return MemoryEvidenceStore(
            store_path=Path(tmpdir) / "memory_evidence.sqlite3",
            refs_dir=Path(tmpdir) / "refs",
        )

    def test_ingests_aiops_session_state_into_l0_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            service = MemoryIngestionService(store=store)
            state = AIOpsSessionState(
                session_id="session-aiops-1",
                input="service-a CPUHigh alert triggered again",
                plan_steps=["check cpu", "check deploy"],
                past_steps=[
                    AIOpsPastStep(step="check cpu", result="user_cpu=95", step_index=0),
                    AIOpsPastStep(step="check deploy", result="recent deploy found", step_index=1),
                ],
                response="Root cause: cache memory leak.",
            )

            evidence = service.ingest_aiops_diagnosis(
                state,
                owner_id="ops-team",
                key_events=[{"type": "plan", "plan": ["check cpu", "check deploy"]}],
                tool_results=[{"tool": "query_cpu_metrics", "result": {"user_cpu": 95}}],
                memory_observation={"mode": "active", "memory_ids": ["mem_1"]},
                service="service-a",
                alert_name="CPUHigh",
                environment="prod",
                evidence_id="l0_ingestion_case",
            )

            self.assertEqual(evidence.evidence_id, "l0_ingestion_case")
            self.assertEqual(evidence.session_id, "session-aiops-1")
            self.assertEqual(evidence.query, "service-a CPUHigh alert triggered again")
            self.assertEqual(evidence.diagnosis_status, "complete")
            self.assertIn("cache memory leak", evidence.final_response_preview)
            self.assertIsNotNone(evidence.final_response_ref)
            self.assertIsNotNone(evidence.key_events_ref)
            self.assertIsNotNone(evidence.tool_results_ref)
            self.assertIn("check deploy", evidence.plan_json)
            self.assertIn("recent deploy found", Path(evidence.past_steps_ref.path).read_text(encoding="utf-8"))
            self.assertEqual(store.get("l0_ingestion_case").evidence_id, "l0_ingestion_case")

    def test_partial_ingestion_uses_partial_status_when_response_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            service = MemoryIngestionService(store=store)
            state = AIOpsSessionState(
                session_id="session-aiops-2",
                input="service-b DatabaseConnectionError",
                plan_steps=["check logs"],
                past_steps=[],
                response="",
            )

            evidence = service.ingest_aiops_diagnosis(
                state,
                owner_id="ops-team",
                evidence_id="l0_ingestion_partial",
            )

            self.assertEqual(evidence.diagnosis_status, "partial")
            self.assertEqual(evidence.final_response_preview, "(empty final response)")
            self.assertTrue(store.check_integrity("l0_ingestion_partial")["ok"])


if __name__ == "__main__":
    unittest.main()
