import tempfile
import unittest
from pathlib import Path

from app.models.memory import MemoryRecord, MemoryStatus, MemoryType
from app.models.memory_atom import L1Atom, L1AtomExtractionMethod, L1AtomType
from app.services.memory_aggregator_service import MemoryAggregatorService
from app.services.memory_store import MemoryStore


class L2ScenarioTraceabilityTests(unittest.TestCase):
    def test_l2_scenario_keeps_l1_and_l0_refs_after_sqlite_reload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "memory.sqlite3"
            store = MemoryStore(store_path)
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
                    "service-a CPUHigh should first check CPU metrics",
                    evidence_id="l0_check_cpu",
                    check_name="query_cpu_metrics",
                )
            )

            result = MemoryAggregatorService(store=store).aggregate_from_atom_ids(
                ["l1_root_cpu", "l1_check_cpu"],
                owner_id="ops-team",
            )
            memory_id = result.records[0].memory_id

            reloaded = MemoryStore(store_path).get(memory_id)

            self.assertIsNotNone(reloaded)
            self.assertEqual(reloaded.memory_type, MemoryType.L2_SCENARIO)
            self.assertEqual(reloaded.payload.l1_atom_ids, ["l1_root_cpu", "l1_check_cpu"])
            self.assertEqual(reloaded.evidence["l1_atom_ids"], ["l1_root_cpu", "l1_check_cpu"])
            self.assertEqual(
                {ref["evidence_id"] for ref in reloaded.payload.evidence_refs},
                {"l0_root_cpu", "l0_check_cpu"},
            )
            self.assertEqual(
                {ref["source_atom_id"] for ref in reloaded.payload.evidence_refs},
                {"l1_root_cpu", "l1_check_cpu"},
            )
            self.assertIn("l1_root_cpu", reloaded.content)
            self.assertIn("l0_root_cpu", reloaded.content)

    def _atom_record(
        self,
        atom_id: str,
        atom_type: L1AtomType,
        claim: str,
        *,
        evidence_id: str,
        root_cause: str | None = None,
        check_name: str | None = None,
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
            status=MemoryStatus.ACTIVE,
            tags=["l1_atom", atom.atom_type.value],
        )


if __name__ == "__main__":
    unittest.main()
