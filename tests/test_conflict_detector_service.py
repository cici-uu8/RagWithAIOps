import tempfile
import unittest
from pathlib import Path

from app.models.memory import AlertPatternPayload, MemoryRecord, MemoryStatus, MemoryType, PlanTemplatePayload
from app.models.memory_atom import L1Atom, L1AtomExtractionMethod, L1AtomType
from app.models.memory_conflict import MemoryConflictVerdict
from app.services.conflict_detector_service import ConflictDetectorService
from app.services.memory_store import MemoryStore


class ConflictDetectorServiceTests(unittest.TestCase):
    def _store(self, tmpdir: str) -> MemoryStore:
        return MemoryStore(Path(tmpdir) / "memory.sqlite3")

    def test_root_cause_difference_marks_possible_conflict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            store.upsert(self._alert_record("mem_active_cpu", root_cause="traffic spike"))
            service = ConflictDetectorService(store=store)
            atom = self._atom(
                atom_id="l1_atom_root",
                atom_type=L1AtomType.ROOT_CAUSE_OBSERVATION,
                claim="service-a CPUHigh 的当前根因是 cache memory leak",
                root_cause="cache memory leak",
            )

            results = service.detect_conflicts(atom)

            self.assertEqual(len(results), 1)
            result = results[0]
            self.assertEqual(result.memory_id, "mem_active_cpu")
            self.assertEqual(result.atom_id, "l1_atom_root")
            self.assertEqual(result.verdict, MemoryConflictVerdict.POSSIBLE_CONFLICT)
            self.assertEqual(result.matched_scope["service"], "service-a")
            self.assertEqual(result.matched_scope["alert_name"], "CPUHigh")
            self.assertIn("root cause", result.reason)

    def test_explicit_negates_memory_id_marks_supersession_candidate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            store.upsert(self._alert_record("mem_active_cpu", root_cause="traffic spike"))
            service = ConflictDetectorService(store=store)
            atom = self._atom(
                atom_id="l1_atom_negative",
                atom_type=L1AtomType.NEGATIVE_OBSERVATION,
                claim="service-a CPUHigh 在 2026-05-29 已确认不是 traffic spike",
                negates_memory_id="mem_active_cpu",
            )

            results = service.detect_conflicts(atom)

            self.assertEqual(len(results), 1)
            result = results[0]
            self.assertEqual(result.verdict, MemoryConflictVerdict.SUPERSESSION_CANDIDATE)
            self.assertEqual(result.memory_id, "mem_active_cpu")
            self.assertEqual(result.atom_id, "l1_atom_negative")
            self.assertIn("negates_memory_id", result.reason)

    def test_config_or_deploy_change_marks_possible_conflict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            store.upsert(self._alert_record("mem_active_cpu", root_cause="traffic spike"))
            service = ConflictDetectorService(store=store)
            atom = self._atom(
                atom_id="l1_atom_config",
                atom_type=L1AtomType.CONFIG_OR_DEPLOY_CHANGE,
                claim="service-a 的连接池配置在上周已经更新",
                environment="prod",
            )

            results = service.detect_conflicts(atom)

            self.assertEqual(len(results), 1)
            result = results[0]
            self.assertEqual(result.verdict, MemoryConflictVerdict.POSSIBLE_CONFLICT)
            self.assertEqual(result.memory_id, "mem_active_cpu")
            self.assertIn("config/deploy", result.reason)

    def test_plan_template_stop_condition_contradiction_marks_possible_conflict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            store.upsert(self._plan_record("mem_plan_cpu"))
            service = ConflictDetectorService(store=store)
            atom = self._atom(
                atom_id="l1_atom_check",
                atom_type=L1AtomType.NEGATIVE_OBSERVATION,
                claim="fresh check 已明确推翻 wait for deploy rollback 这个 stop condition",
            )

            results = service.detect_conflicts(atom)

            self.assertEqual(len(results), 1)
            result = results[0]
            self.assertEqual(result.memory_id, "mem_plan_cpu")
            self.assertEqual(result.verdict, MemoryConflictVerdict.POSSIBLE_CONFLICT)
            self.assertIn("stop condition", result.reason)

    def _alert_record(self, memory_id: str, *, root_cause: str) -> MemoryRecord:
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

    def _plan_record(self, memory_id: str) -> MemoryRecord:
        return MemoryRecord(
            memory_id=memory_id,
            owner_id="default",
            namespace="memory://oncall/plan-templates",
            memory_type=MemoryType.PLAN_TEMPLATE,
            content="service-a CPUHigh should wait for deploy rollback",
            summary="service-a CPUHigh wait for deploy rollback",
            payload=PlanTemplatePayload(
                alert_type="CPUHigh",
                plan_steps=["check deploy", "check cpu"],
                stop_conditions=["wait for deploy rollback"],
                evidence_refs=[
                    {
                        "evidence_type": "l0_evidence_ref",
                        "evidence_id": "l0_plan",
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
        negates_memory_id: str | None = None,
        environment: str | None = "prod",
    ) -> L1Atom:
        return L1Atom(
            atom_id=atom_id,
            owner_id="default",
            evidence_id="l0_atom",
            atom_type=atom_type,
            service="service-a",
            alert_name="CPUHigh",
            environment=environment,
            claim=claim,
            root_cause=root_cause,
            negates_memory_id=negates_memory_id,
            confidence=0.9,
            evidence_refs=["l0_atom"],
            extraction_method=L1AtomExtractionMethod.SCHEMA_LLM_V1,
        )


if __name__ == "__main__":
    unittest.main()
