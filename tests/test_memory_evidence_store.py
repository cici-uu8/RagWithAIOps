import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.services.memory_evidence_store import MemoryEvidenceStore


class MemoryEvidenceStoreTests(unittest.TestCase):
    def _store(self, tmpdir: str) -> MemoryEvidenceStore:
        return MemoryEvidenceStore(
            store_path=Path(tmpdir) / "memory_evidence.sqlite3",
            refs_dir=Path(tmpdir) / "refs",
        )

    def test_create_aiops_evidence_persists_metadata_and_refs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)

            evidence = store.create_aiops_evidence(
                evidence_id="l0_aiops_test_001",
                session_id="session-1",
                owner_id="ops-team",
                query="service-a CPUHigh alert triggered again",
                service="service-a",
                alert_name="CPUHigh",
                environment="prod",
                plan=["check cpu", "check deploy"],
                past_steps=[{"step": "check cpu", "result": "user_cpu=95", "step_index": 0}],
                final_response="Root cause: cache memory leak.",
                key_events=[{"type": "plan", "plan": ["check cpu"]}],
                tool_results=[{"tool": "query_cpu_metrics", "result": {"user_cpu": 95}}],
                memory_observation={"mode": "active", "memory_ids": ["mem_1"]},
            )

            reloaded = store.get("l0_aiops_test_001")

            self.assertIsNotNone(reloaded)
            self.assertEqual(reloaded.owner_id, "ops-team")
            self.assertEqual(reloaded.service, "service-a")
            self.assertEqual(reloaded.alert_name, "CPUHigh")
            self.assertEqual(reloaded.diagnosis_status, "complete")
            self.assertIn("cache memory leak", reloaded.final_response_preview)
            self.assertIsNotNone(reloaded.final_response_ref)
            self.assertIsNotNone(reloaded.past_steps_ref)
            self.assertIsNotNone(reloaded.key_events_ref)
            self.assertIsNotNone(reloaded.tool_results_ref)
            self.assertIn("active", reloaded.memory_observation_json)

            manifest = json.loads(reloaded.refs_manifest_json)
            self.assertEqual(manifest["evidence_id"], evidence.evidence_id)
            self.assertEqual(len(manifest["refs"]), 5)
            for ref in manifest["refs"]:
                self.assertTrue(Path(ref["path"]).exists())

            integrity = store.check_integrity(evidence.evidence_id)
            self.assertTrue(integrity["ok"])
            self.assertEqual(integrity["refs_checked"], 5)

            listed = store.list_evidence(owner_id="ops-team", session_id="session-1")
            self.assertEqual([item.evidence_id for item in listed], ["l0_aiops_test_001"])

    def test_integrity_reports_missing_ref(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            evidence = store.create_aiops_evidence(
                evidence_id="l0_aiops_missing_ref",
                session_id="session-missing",
                query="service-b DatabaseConnectionError",
                plan=[],
                past_steps=[],
                final_response="done",
            )
            Path(evidence.final_response_ref.path).unlink()

            integrity = store.check_integrity(evidence.evidence_id)

            self.assertFalse(integrity["ok"])
            self.assertEqual(integrity["missing_refs"][0]["ref_type"], "final_response")

    def test_cleanup_expired_evidence_dry_run_keeps_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            old_created_at = datetime.now() - timedelta(days=60)
            evidence = store.create_aiops_evidence(
                evidence_id="l0_aiops_old",
                session_id="session-old",
                query="service-c HighMemoryUsage",
                plan=[],
                past_steps=[],
                final_response="old report",
                created_at=old_created_at,
            )

            plan = store.cleanup_expired_evidence(retention_days=30, dry_run=True)

            self.assertTrue(Path(evidence.final_response_ref.path).exists())
            self.assertEqual(plan["planned_delete_count"], 1)
            self.assertEqual(plan["deleted_count"], 0)
            self.assertEqual(store.get(evidence.evidence_id).evidence_id, evidence.evidence_id)


if __name__ == "__main__":
    unittest.main()
