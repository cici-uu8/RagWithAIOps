import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models.memory import AlertPatternPayload, L1Atom, L2ScenarioPayload, MemoryRecord, MemoryStatus, MemoryType
from app.models.memory_atom import L1AtomExtractionMethod, L1AtomType
from app.services.hierarchical_retrieval_service import HierarchicalRetrievalService
from app.services.memory_store import MemoryStore


class HierarchicalRetrievalServiceTests(unittest.TestCase):
    def _store(self, tmpdir: str) -> MemoryStore:
        return MemoryStore(Path(tmpdir) / "memory.sqlite3")

    def test_l2_scenario_hit_does_not_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            store.upsert(self._l2_record("l2_cpu_scenario", status=MemoryStatus.ACTIVE))
            store.upsert(self._l1_record("l1_cpu_root", status=MemoryStatus.ACTIVE))

            service = HierarchicalRetrievalService(store=store)
            response = service.retrieve_hierarchical(
                "service-a CPUHigh cache memory leak",
                owner_id="ops-team",
                top_k_l2=2,
                top_k_l1=3,
            )

            self.assertEqual([item.memory_id for item in response.l2_scenarios], ["l2_cpu_scenario"])
            self.assertEqual(response.l1_atoms, [])
            self.assertEqual(response.legacy_memories, [])
            self.assertFalse(response.trace["l2_retrieval"]["fallback_to_l1"])
            self.assertIsNone(response.trace["l2_retrieval"]["fallback_reason"])

    def test_l2_insufficient_hits_falls_back_to_l1(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            store.upsert(self._l1_record("l1_cpu_root", status=MemoryStatus.ACTIVE))

            service = HierarchicalRetrievalService(store=store)
            response = service.retrieve_hierarchical(
                "service-a CPUHigh cache memory leak",
                owner_id="ops-team",
                top_k_l2=2,
                top_k_l1=3,
            )

            self.assertEqual(response.l2_scenarios, [])
            self.assertEqual([item.memory_id for item in response.l1_atoms], ["l1_cpu_root"])
            self.assertFalse(response.trace["l1_retrieval"]["fallback_to_legacy"])
            self.assertEqual(response.trace["l2_retrieval"]["fallback_reason"], "insufficient_l2_hits")

    def test_l2_low_confidence_falls_back_to_l1(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            store.upsert(
                self._l2_record(
                    "l2_cpu_scenario",
                    status=MemoryStatus.ACTIVE,
                    confidence=0.4,
                    l1_atom_ids=["l1_scenario_support"],
                )
            )
            store.upsert(self._l1_record("l1_cpu_root", status=MemoryStatus.ACTIVE))

            service = HierarchicalRetrievalService(store=store, l2_min_confidence=0.7)
            response = service.retrieve_hierarchical(
                "service-a CPUHigh cache memory leak",
                owner_id="ops-team",
                top_k_l2=2,
                top_k_l1=3,
            )

            self.assertEqual([item.memory_id for item in response.l2_scenarios], ["l2_cpu_scenario"])
            self.assertEqual([item.memory_id for item in response.l1_atoms], ["l1_cpu_root"])
            self.assertEqual(response.trace["l2_retrieval"]["fallback_reason"], "low_confidence")

    def test_l1_excludes_atoms_already_covered_by_l2(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            store.upsert(
                self._l2_record(
                    "l2_cpu_scenario",
                    status=MemoryStatus.ACTIVE,
                    confidence=0.4,
                    l1_atom_ids=["l1_cpu_root"],
                )
            )
            store.upsert(self._l1_record("l1_cpu_root", status=MemoryStatus.ACTIVE))
            store.upsert(self._l1_record("l1_cpu_check", status=MemoryStatus.ACTIVE, atom_type=L1AtomType.CHECK_OBSERVATION))

            service = HierarchicalRetrievalService(store=store, l2_min_confidence=0.7)
            response = service.retrieve_hierarchical(
                "service-a CPUHigh cache memory leak",
                owner_id="ops-team",
                top_k_l2=2,
                top_k_l1=3,
            )

            self.assertEqual([item.memory_id for item in response.l1_atoms], ["l1_cpu_check"])
            self.assertTrue(
                any(item["excluded_by_l2"] for item in response.trace["l1_retrieval"]["matched_atoms"])
            )
            self.assertEqual(
                {item["memory_id"] for item in response.trace["l1_retrieval"]["matched_atoms"]},
                {"l1_cpu_root", "l1_cpu_check"},
            )

    def test_l1_insufficient_hits_falls_back_to_legacy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            store.upsert(self._legacy_alert_record("mem_alert_cpu_high"))

            service = HierarchicalRetrievalService(store=store, min_l1_hits=2)
            response = service.retrieve_hierarchical(
                "service-a CPUHigh alert triggered again",
                owner_id="default",
                top_k_l2=2,
                top_k_l1=1,
                top_k_legacy=3,
            )

            self.assertEqual(response.l2_scenarios, [])
            self.assertEqual(response.l1_atoms, [])
            self.assertEqual([item.memory_id for item in response.legacy_memories], ["mem_alert_cpu_high"])
            self.assertTrue(response.trace["l1_retrieval"]["fallback_to_legacy"])
            self.assertEqual(response.trace["l1_retrieval"]["fallback_reason"], "insufficient_l1_hits")

    def test_legacy_fallback_preserves_stale_policy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            now = datetime.now(timezone.utc)
            store.upsert(
                self._legacy_alert_record("mem_old_cpu_high", updated_at=now - timedelta(days=14)),
                preserve_timestamps=True,
            )
            store.upsert(
                self._legacy_alert_record("mem_new_cpu_high", updated_at=now - timedelta(days=1)),
                preserve_timestamps=True,
            )

            service = HierarchicalRetrievalService(store=store, min_l1_hits=2)
            response = service.retrieve_hierarchical(
                "service-a CPUHigh fixed last week but alert triggered again",
                owner_id="default",
                top_k_l2=2,
                top_k_l1=1,
                top_k_legacy=2,
            )

            self.assertEqual(
                [item.memory_id for item in response.legacy_memories],
                ["mem_new_cpu_high", "mem_old_cpu_high"],
            )
            self.assertEqual(response.trace["legacy_retrieval"]["stale_policy"]["penalized_memory_ids"], ["mem_old_cpu_high"])
            self.assertEqual(response.trace["stale_policy"]["penalized_memory_ids"], ["mem_old_cpu_high"])

    def test_trace_contains_all_layers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            store.upsert(self._legacy_alert_record("mem_alert_cpu_high"))

            service = HierarchicalRetrievalService(store=store, min_l1_hits=2)
            response = service.retrieve_hierarchical(
                "service-a CPUHigh alert triggered again",
                owner_id="default",
                top_k_l2=2,
                top_k_l1=1,
                top_k_legacy=3,
            )

            self.assertIn("l2_retrieval", response.trace)
            self.assertIn("l1_retrieval", response.trace)
            self.assertIn("legacy_retrieval", response.trace)
            self.assertIn("stale_policy", response.trace)
            self.assertIn("retrieval_latency_ms", response.trace)

    def _l1_record(
        self,
        memory_id: str,
        *,
        status: MemoryStatus,
        atom_type: L1AtomType = L1AtomType.ROOT_CAUSE_OBSERVATION,
    ) -> MemoryRecord:
        atom = L1Atom(
            atom_id=memory_id,
            owner_id="ops-team",
            evidence_id=f"l0_{memory_id}",
            atom_type=atom_type,
            service="service-a",
            alert_name="CPUHigh",
            environment="prod",
            claim="service-a CPUHigh current root cause is cache memory leak",
            root_cause="cache memory leak",
            check_name="query_cpu_metrics(user_cpu, system_cpu)",
            remediation="rollback recent deploy",
            confidence=0.95,
            evidence_refs=[f"l0_{memory_id}"],
            extraction_method=L1AtomExtractionMethod.SCHEMA_LLM_V1,
        )
        return MemoryRecord(
            memory_id=memory_id,
            owner_id="ops-team",
            namespace="memory://oncall/l1-atoms",
            memory_type=MemoryType.L1_ATOM,
            content=atom.claim,
            summary=atom.claim,
            payload=atom,
            source="test active L1 atom",
            evidence={"evidence_type": "l1_atom_candidate", "l0_evidence_refs": [f"l0_{memory_id}"]},
            status=status,
            tags=["l1_atom", atom.atom_type.value],
        )

    def _l2_record(
        self,
        memory_id: str,
        *,
        status: MemoryStatus,
        confidence: float = 0.95,
        l1_atom_ids: list[str] | None = None,
    ) -> MemoryRecord:
        l1_atom_ids = l1_atom_ids or ["l1_cpu_root", "l1_cpu_check"]
        payload = L2ScenarioPayload(
            scenario_key="owner=ops-team|service=service-a|alert=CPUHigh|environment=prod",
            scenario_title="Scenario: service-a CPUHigh (prod)",
            service="service-a",
            alert_name="CPUHigh",
            environment="prod",
            applicable_conditions=["service-a", "CPUHigh", "prod"],
            diagnostic_path=["query_cpu_metrics(user_cpu, system_cpu)"],
            common_root_causes=["cache memory leak"],
            remediation_steps=["rollback recent deploy"],
            supporting_claims=["service-a CPUHigh current root cause is cache memory leak"],
            l1_atom_ids=l1_atom_ids,
            evidence_refs=[
                {
                    "evidence_type": "l2_scenario_support",
                    "scenario_key": "owner=ops-team|service=service-a|alert=CPUHigh|environment=prod",
                    "source_atom_id": l1_atom_ids[0],
                    "atom_type": "root_cause_observation",
                    "evidence_id": f"l0_{l1_atom_ids[0]}",
                    "claim": "service-a CPUHigh current root cause is cache memory leak",
                }
            ],
            scenario_markdown="# Scenario: service-a CPUHigh (prod)\n\n## Applicable Conditions\n- service-a\n- CPUHigh\n- prod",
        )
        return MemoryRecord(
            memory_id=memory_id,
            owner_id="ops-team",
            namespace="memory://oncall/l2-scenarios",
            memory_type=MemoryType.L2_SCENARIO,
            content=payload.scenario_markdown,
            summary=payload.scenario_title,
            payload=payload,
            source="test active L2 scenario",
            evidence={
                "evidence_type": "l2_scenario_candidate",
                "scenario_key": payload.scenario_key,
                "l1_atom_ids": l1_atom_ids,
                "l0_evidence_refs": [ref["evidence_id"] for ref in payload.evidence_refs],
                "confidence": confidence,
            },
            status=status,
            tags=["l2_scenario", "service-a", "CPUHigh"],
        )

    def _legacy_alert_record(self, memory_id: str, *, updated_at: datetime | None = None) -> MemoryRecord:
        if updated_at is None:
            updated_at = datetime.now(timezone.utc)
        summary = "service-a CPUHigh cache memory leak"
        return MemoryRecord(
            memory_id=memory_id,
            owner_id="default",
            namespace="memory://oncall/alert-patterns",
            memory_type=MemoryType.ALERT_PATTERN,
            content=summary,
            summary=summary,
            payload=AlertPatternPayload(
                alert_name="CPUHigh",
                service="service-a",
                severity="critical",
                signal_keys=["cpu"],
                metric_patterns=[],
                log_patterns=[],
                root_cause="cache memory leak",
                fix="restart cache worker",
                evidence_refs=[{"evidence_type": "l0_evidence_ref", "evidence_id": f"l0_{memory_id}"}],
            ),
            source="unit-test",
            evidence={"evidence_type": "seed_memory", "service": "service-a", "alert_name": "CPUHigh"},
            status=MemoryStatus.ACTIVE,
            tags=["cpu", "cache"],
            created_at=updated_at,
            updated_at=updated_at,
        )


if __name__ == "__main__":
    unittest.main()
