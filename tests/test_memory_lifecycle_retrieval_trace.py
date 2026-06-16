import tempfile
import unittest
from pathlib import Path

from app.models.memory import AlertPatternPayload, MemoryRecord, MemoryStatus, MemoryType
from app.services.memory_retrieval_service import MemoryRetrievalQuery, MemoryRetrievalService
from app.services.memory_store import MemoryStore


class MemoryLifecycleRetrievalTraceTests(unittest.TestCase):
    def test_stale_suspect_and_superseded_memory_are_skipped_with_trace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory.sqlite3")
            store.upsert(self._alert_record("mem_active_cpu", MemoryStatus.ACTIVE, root_cause="traffic spike"))
            store.upsert(self._alert_record("mem_stale_cpu", MemoryStatus.STALE_SUSPECT, root_cause="cache leak"))
            store.upsert(self._alert_record("mem_superseded_cpu", MemoryStatus.SUPERSEDED, root_cause="bad deploy"))
            service = MemoryRetrievalService(store=store)

            response = service.retrieve(
                MemoryRetrievalQuery(
                    query="service-a CPUHigh root cause",
                    owner_id="default",
                    top_k=5,
                )
            )

            self.assertEqual([result.memory_id for result in response.memory_results], ["mem_active_cpu"])
            lifecycle_trace = response.trace["lifecycle_filter"]
            self.assertEqual(lifecycle_trace["skipped_count"], 2)
            skipped = {item["memory_id"]: item for item in lifecycle_trace["skipped_memory"]}
            self.assertEqual(skipped["mem_stale_cpu"]["status"], "stale_suspect")
            self.assertEqual(skipped["mem_superseded_cpu"]["status"], "superseded")
            self.assertIn("not active", skipped["mem_stale_cpu"]["reason"])
            self.assertIn("not active", skipped["mem_superseded_cpu"]["reason"])

    def _alert_record(
        self,
        memory_id: str,
        status: MemoryStatus,
        *,
        root_cause: str,
    ) -> MemoryRecord:
        return MemoryRecord(
            memory_id=memory_id,
            owner_id="default",
            namespace="memory://oncall/alert-patterns",
            memory_type=MemoryType.ALERT_PATTERN,
            content=f"service-a CPUHigh root cause is {root_cause}",
            summary=f"service-a CPUHigh {root_cause}",
            payload=AlertPatternPayload(
                alert_name="CPUHigh",
                service="service-a",
                signal_keys=["cpu_usage", "deploy"],
                root_cause=root_cause,
                fix="follow current runbook",
                evidence_refs=[
                    {
                        "evidence_type": "l0_evidence_ref",
                        "evidence_id": f"l0_{memory_id}",
                    }
                ],
            ),
            source="seeded lifecycle retrieval trace memory",
            evidence={
                "evidence_type": "seed_memory",
                "service": "service-a",
                "alert_name": "CPUHigh",
            },
            status=status,
        )


if __name__ == "__main__":
    unittest.main()
