import tempfile
import unittest
from pathlib import Path

from app.models.memory import MemoryRecord, MemoryStatus, MemoryType
from app.models.memory_atom import L1Atom, L1AtomExtractionMethod, L1AtomType
from app.services.memory_aggregator_service import MemoryAggregatorService
from app.services.memory_store import MemoryStore


class MemoryAggregatorServiceTests(unittest.TestCase):
    def _store(self, tmpdir: str) -> MemoryStore:
        return MemoryStore(Path(tmpdir) / "memory.sqlite3")

    def test_aggregates_active_l1_atoms_into_candidate_l2_scenario(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            for record in (
                self._atom_record(
                    "l1_root_cpu",
                    L1AtomType.ROOT_CAUSE_OBSERVATION,
                    "service-a CPUHigh current root cause is cache memory leak",
                    evidence_id="l0_root_cpu",
                    root_cause="cache memory leak",
                ),
                self._atom_record(
                    "l1_check_cpu",
                    L1AtomType.CHECK_OBSERVATION,
                    "service-a CPUHigh should first check user_cpu and system_cpu",
                    evidence_id="l0_check_cpu",
                    check_name="query_cpu_metrics(user_cpu, system_cpu)",
                ),
                self._atom_record(
                    "l1_fix_cpu",
                    L1AtomType.REMEDIATION_OBSERVATION,
                    "service-a CPUHigh can be fixed by rolling back the recent deploy",
                    evidence_id="l0_fix_cpu",
                    remediation="rollback recent deploy",
                ),
            ):
                store.upsert(record)

            service = MemoryAggregatorService(store=store)
            result = service.aggregate_from_atom_ids(
                ["l1_root_cpu", "l1_check_cpu", "l1_fix_cpu"],
                owner_id="ops-team",
            )

            self.assertEqual(result.action, "created")
            self.assertEqual(len(result.records), 1)
            scenario = result.records[0]
            self.assertEqual(scenario.status, MemoryStatus.CANDIDATE)
            self.assertEqual(scenario.memory_type, MemoryType.L2_SCENARIO)
            self.assertEqual(scenario.namespace, "memory://oncall/l2-scenarios")
            self.assertIn("Scenario: service-a CPUHigh", scenario.content)
            self.assertIn("Recommended Diagnostic Path", scenario.content)
            self.assertIn("cache memory leak", scenario.content)
            self.assertIn("rollback recent deploy", scenario.content)
            self.assertEqual(
                scenario.payload.l1_atom_ids,
                ["l1_root_cpu", "l1_check_cpu", "l1_fix_cpu"],
            )
            self.assertEqual(
                {ref["evidence_id"] for ref in scenario.payload.evidence_refs},
                {"l0_root_cpu", "l0_check_cpu", "l0_fix_cpu"},
            )
            self.assertEqual(store.get(scenario.memory_id).status, MemoryStatus.CANDIDATE)

    def test_skips_unstable_l1_atoms(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            store.upsert(
                self._atom_record(
                    "l1_root_cpu",
                    L1AtomType.ROOT_CAUSE_OBSERVATION,
                    "service-a CPUHigh current root cause is cache memory leak",
                    evidence_id="l0_root_cpu",
                    root_cause="cache memory leak",
                    status=MemoryStatus.ACTIVE,
                )
            )
            store.upsert(
                self._atom_record(
                    "l1_check_cpu",
                    L1AtomType.CHECK_OBSERVATION,
                    "service-a CPUHigh should first check user_cpu and system_cpu",
                    evidence_id="l0_check_cpu",
                    check_name="query_cpu_metrics(user_cpu, system_cpu)",
                    status=MemoryStatus.CANDIDATE,
                )
            )

            service = MemoryAggregatorService(store=store)
            result = service.aggregate_from_atom_ids(
                ["l1_root_cpu", "l1_check_cpu"],
                owner_id="ops-team",
            )

            self.assertEqual(result.action, "skipped")
            self.assertIn("at least 2 stable L1 atoms", result.skipped_reason)
            self.assertEqual(
                store.list_memories(memory_type=MemoryType.L2_SCENARIO),
                [],
            )

    def test_duplicate_scenario_is_not_inserted_twice(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            store.upsert(
                self._atom_record(
                    "l1_root_cpu",
                    L1AtomType.ROOT_CAUSE_OBSERVATION,
                    "service-a CPUHigh current root cause is cache memory leak",
                    evidence_id="l0_root_cpu",
                    root_cause="cache memory leak",
                )
            )
            store.upsert(
                self._atom_record(
                    "l1_check_cpu",
                    L1AtomType.CHECK_OBSERVATION,
                    "service-a CPUHigh should first check user_cpu and system_cpu",
                    evidence_id="l0_check_cpu",
                    check_name="query_cpu_metrics(user_cpu, system_cpu)",
                )
            )
            service = MemoryAggregatorService(store=store)

            first = service.aggregate_from_atom_ids(["l1_root_cpu", "l1_check_cpu"], owner_id="ops-team")
            second = service.aggregate_from_atom_ids(["l1_check_cpu", "l1_root_cpu"], owner_id="ops-team")

            self.assertEqual(first.action, "created")
            self.assertEqual(second.action, "duplicate")
            self.assertEqual(first.records[0].memory_id, second.records[0].memory_id)
            scenarios = store.list_memories(
                owner_id="ops-team",
                memory_type=MemoryType.L2_SCENARIO,
            )
            self.assertEqual([record.memory_id for record in scenarios], [first.records[0].memory_id])

    def _atom_record(
        self,
        atom_id: str,
        atom_type: L1AtomType,
        claim: str,
        *,
        evidence_id: str,
        root_cause: str | None = None,
        check_name: str | None = None,
        remediation: str | None = None,
        status: MemoryStatus = MemoryStatus.ACTIVE,
    ) -> MemoryRecord:
        atom = L1Atom(
            atom_id=atom_id,
            owner_id="ops-team",
            evidence_id=evidence_id,
            atom_type=atom_type,
            service="service-a",
            alert_name="CPUHigh",
            environment="prod",
            claim=claim,
            root_cause=root_cause,
            check_name=check_name,
            remediation=remediation,
            confidence=0.9,
            evidence_refs=[evidence_id],
            extraction_method=L1AtomExtractionMethod.SCHEMA_LLM_V1,
        )
        return MemoryRecord(
            memory_id=atom.atom_id,
            owner_id=atom.owner_id,
            namespace="memory://oncall/l1-atoms",
            memory_type=MemoryType.L1_ATOM,
            content=atom.claim,
            summary=atom.claim,
            payload=atom,
            source="test active L1 atom",
            evidence={
                "evidence_type": "l1_atom_candidate",
                "l0_evidence_id": evidence_id,
                "l0_evidence_refs": [evidence_id],
            },
            status=status,
            tags=["l1_atom", atom.atom_type.value],
        )


if __name__ == "__main__":
    unittest.main()
