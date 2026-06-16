import tempfile
import unittest
from pathlib import Path

from app.models.memory import (
    AlertPatternPayload,
    MemoryRecord,
    MemoryReviewDecision,
    MemoryStatus,
    MemoryType,
)
from app.models.memory_atom import L1Atom, L1AtomExtractionMethod, L1AtomType
from app.services.conflict_detector_service import ConflictDetectorService
from app.services.memory_lifecycle_service import MemoryLifecycleService
from app.services.memory_review_service import MemoryReviewService
from app.services.memory_store import MemoryStore


class MemoryLifecycleServiceTests(unittest.TestCase):
    def _store(self, tmpdir: str) -> MemoryStore:
        return MemoryStore(Path(tmpdir) / "memory.sqlite3")

    def test_apply_conflicts_for_atom_marks_active_memory_stale_suspect(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            store.upsert(self._active_alert_record("mem_active_cpu", root_cause="traffic spike"))
            detector = ConflictDetectorService(store=store)
            service = MemoryLifecycleService(store=store, conflict_detector=detector)
            atom = self._atom(
                atom_id="l1_atom_root",
                atom_type=L1AtomType.ROOT_CAUSE_OBSERVATION,
                claim="service-a CPUHigh 的当前根因是 cache memory leak",
                root_cause="cache memory leak",
            )

            updated = service.apply_conflicts_for_atom(atom)

            self.assertEqual([record.memory_id for record in updated], ["mem_active_cpu"])
            reloaded = store.get("mem_active_cpu")
            self.assertEqual(reloaded.status, MemoryStatus.STALE_SUSPECT)
            self.assertEqual(reloaded.evidence["conflicting_atom_id"], "l1_atom_root")
            self.assertEqual(reloaded.evidence["conflict_reason"], "root cause differs")
            self.assertEqual(reloaded.evidence["lifecycle_events"][-1]["transition"], "active->stale_suspect")
            self.assertEqual(service.get_metrics()["stale_suspect_marked_count"], 1)

    def test_review_can_restore_stale_suspect_to_active(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            store.upsert(
                self._active_alert_record("mem_active_cpu", root_cause="traffic spike").model_copy(
                    update={
                        "status": MemoryStatus.STALE_SUSPECT,
                        "evidence": {
                            "evidence_type": "seed_memory",
                            "conflicting_atom_id": "l1_atom_root",
                            "conflict_reason": "root cause differs",
                            "lifecycle_events": [
                                {
                                    "transition": "active->stale_suspect",
                                    "trigger": "conflict_detector",
                                }
                            ],
                        },
                    }
                )
            )
            service = MemoryReviewService(store=store)

            restored = service.restore_stale_suspect(
                "mem_active_cpu",
                reviewer_id="ops-lead",
                decision_note="fresh checks still support the original root cause",
            )

            self.assertEqual(restored.status, MemoryStatus.ACTIVE)
            self.assertEqual(restored.review.decision, MemoryReviewDecision.APPROVED)
            self.assertEqual(restored.review.previous_status, MemoryStatus.STALE_SUSPECT)
            self.assertEqual(restored.review.reviewer_id, "ops-lead")
            self.assertEqual(restored.evidence["lifecycle_events"][-1]["transition"], "stale_suspect->active")

    def test_review_can_supersede_active_memory_with_audit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            store.upsert(self._active_alert_record("mem_active_cpu", root_cause="traffic spike"))
            service = MemoryReviewService(store=store)

            superseded = service.supersede_memory(
                "mem_active_cpu",
                superseded_by="l1_atom_root",
                reviewer_id="ops-lead",
                decision_note="fresh evidence replaces the earlier root cause",
            )

            self.assertEqual(superseded.status, MemoryStatus.SUPERSEDED)
            self.assertEqual(superseded.review.decision, MemoryReviewDecision.SUPERSEDED)
            self.assertEqual(superseded.review.previous_status, MemoryStatus.ACTIVE)
            self.assertEqual(superseded.evidence["superseded_by"], "l1_atom_root")
            self.assertEqual(superseded.evidence["lifecycle_events"][-1]["transition"], "active->superseded")

    def test_review_queue_can_filter_stale_suspect_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            service = MemoryReviewService(store=store)
            store.upsert(self._active_alert_record("mem_active_cpu", root_cause="traffic spike"))
            store.upsert(
                self._active_alert_record("mem_stale_cpu", root_cause="cache memory leak").model_copy(
                    update={
                        "status": MemoryStatus.STALE_SUSPECT,
                        "evidence": {
                            "evidence_type": "seed_memory",
                            "lifecycle_events": [],
                        },
                    }
                )
            )

            queue = service.list_review_queue(statuses=(MemoryStatus.STALE_SUSPECT,))

            self.assertEqual([record.memory_id for record in queue], ["mem_stale_cpu"])

    def _active_alert_record(self, memory_id: str, *, root_cause: str) -> MemoryRecord:
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
                fix="scale replicas",
                evidence_refs=[
                    {
                        "evidence_type": "l0_evidence_ref",
                        "evidence_id": "l0_cpu",
                    }
                ],
            ),
            source="seeded active memory",
            evidence={
                "evidence_type": "seed_memory",
                "service": "service-a",
                "alert_name": "CPUHigh",
            },
            status=MemoryStatus.ACTIVE,
        )

    def _atom(
        self,
        *,
        atom_id: str,
        atom_type: L1AtomType,
        claim: str,
        root_cause: str | None = None,
    ) -> L1Atom:
        return L1Atom(
            atom_id=atom_id,
            owner_id="default",
            evidence_id="l0_atom",
            atom_type=atom_type,
            service="service-a",
            alert_name="CPUHigh",
            environment="prod",
            claim=claim,
            root_cause=root_cause,
            confidence=0.9,
            evidence_refs=["l0_atom"],
            extraction_method=L1AtomExtractionMethod.SCHEMA_LLM_V1,
        )


if __name__ == "__main__":
    unittest.main()
