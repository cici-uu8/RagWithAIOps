import tempfile
import unittest
from pathlib import Path

from app.models.memory import MemoryStatus, MemoryType
from app.services.memory_evidence_store import MemoryEvidenceStore
from app.services.memory_extractor_service import MemoryExtractorService
from app.services.memory_store import MemoryStore


class FakeExtractionChain:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []

    def invoke(self, payload: dict):
        self.calls.append(payload)
        return self.response


class FlakyExtractionChain:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []
        self.fail_once = True

    def invoke(self, payload: dict):
        self.calls.append(payload)
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("transient timeout")
        return self.response


class MemoryExtractorServiceTests(unittest.TestCase):
    def _evidence_store(self, tmpdir: str) -> MemoryEvidenceStore:
        return MemoryEvidenceStore(
            store_path=Path(tmpdir) / "memory_evidence.sqlite3",
            refs_dir=Path(tmpdir) / "refs",
        )

    def _memory_store(self, tmpdir: str) -> MemoryStore:
        return MemoryStore(Path(tmpdir) / "memory.sqlite3")

    def _service(self, tmpdir: str, response, *, transient_retry_count: int = 1) -> MemoryExtractorService:
        evidence_store = self._evidence_store(tmpdir)
        memory_store = self._memory_store(tmpdir)
        return MemoryExtractorService(
            evidence_store=evidence_store,
            store=memory_store,
            extraction_chain=FakeExtractionChain(response),
            transient_retry_count=transient_retry_count,
        )

    def _create_evidence(
        self,
        evidence_store: MemoryEvidenceStore,
        *,
        evidence_id: str,
        session_id: str,
        query: str,
        service: str | None = "service-a",
        alert_name: str | None = "CPUHigh",
        environment: str | None = "prod",
        final_response: str = "Root cause: cache memory leak.",
        plan: list[str] | None = None,
        key_events: list[dict] | None = None,
        tool_results: list[dict] | None = None,
        diagnosis_status: str = "complete",
    ):
        return evidence_store.create_aiops_evidence(
            evidence_id=evidence_id,
            session_id=session_id,
            owner_id="ops-team",
            query=query,
            service=service,
            alert_name=alert_name,
            environment=environment,
            plan=plan or ["check cpu", "check deploy"],
            past_steps=[{"step": "check cpu", "result": "user_cpu=95", "step_index": 0}],
            final_response=final_response,
            key_events=key_events
            or [{"type": "final", "result": "Root cause: cache memory leak."}],
            tool_results=tool_results or [{"tool": "query_cpu_metrics", "result": {"user_cpu": 95}}],
            diagnosis_status=diagnosis_status,
        )

    def test_extract_root_cause_observation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_store = self._evidence_store(tmpdir)
            memory_store = self._memory_store(tmpdir)
            self._create_evidence(
                evidence_store,
                evidence_id="l0_atom_root",
                session_id="session-aiops-1",
                query="service-a CPUHigh alert triggered again",
            )
            service = MemoryExtractorService(
                evidence_store=evidence_store,
                store=memory_store,
                extraction_chain=FakeExtractionChain(
                    {
                        "atoms": [
                            {
                                "atom_type": "root_cause_observation",
                                "service": "service-a",
                                "alert_name": "CPUHigh",
                                "environment": "prod",
                                "claim": "service-a CPUHigh 的当前根因是 cache memory leak",
                                "root_cause": "cache memory leak",
                                "confidence": 0.95,
                                "evidence_refs": ["l0_atom_root"],
                            }
                        ]
                    }
                ),
            )

            atoms = service.extract_atoms_from_evidence("l0_atom_root")

            self.assertEqual(len(atoms), 1)
            atom = atoms[0]
            self.assertEqual(atom.atom_type, "root_cause_observation")
            self.assertEqual(atom.status, "candidate")
            self.assertEqual(atom.evidence_id, "l0_atom_root")
            self.assertEqual(atom.evidence_refs, ["l0_atom_root"])
            self.assertEqual(atom.service, "service-a")
            self.assertEqual(atom.alert_name, "CPUHigh")
            self.assertEqual(atom.confidence, 0.95)

            stored = memory_store.get(atom.atom_id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.status, MemoryStatus.CANDIDATE)
            self.assertEqual(stored.memory_type, MemoryType.L1_ATOM)
            self.assertEqual(stored.payload.atom_type, "root_cause_observation")
            self.assertEqual(stored.payload.evidence_refs, ["l0_atom_root"])

    def test_extract_check_observation(self):
        self._extract_single_atom(
            atom_type="check_observation",
            atom_payload={
                "atom_type": "check_observation",
                "service": "service-a",
                "alert_name": "CPUHigh",
                "claim": "service-a CPUHigh 场景下必须先查 user_cpu 和 system_cpu",
                "check_name": "query_cpu_metrics(user_cpu, system_cpu)",
                "confidence": 0.85,
                "evidence_refs": ["l0_atom_check"],
            },
            evidence_id="l0_atom_check",
            query="service-a CPUHigh should check cpu first",
        )

    def test_extract_remediation_observation(self):
        self._extract_single_atom(
            atom_type="remediation_observation",
            atom_payload={
                "atom_type": "remediation_observation",
                "service": "service-a",
                "alert_name": "CPUHigh",
                "claim": "service-a CPUHigh 可通过 rollback recent deploy 修复",
                "remediation": "rollback recent deploy",
                "confidence": 0.9,
                "evidence_refs": ["l0_atom_fix"],
            },
            evidence_id="l0_atom_fix",
            query="service-a CPUHigh rollback guidance",
        )

    def test_extract_negative_observation(self):
        self._extract_single_atom(
            atom_type="negative_observation",
            atom_payload={
                "atom_type": "negative_observation",
                "service": "service-b",
                "alert_name": "DatabaseConnectionError",
                "claim": "service-b DatabaseConnectionError 在 2026-05-29 已确认不是 connection pool leak",
                "confidence": 0.88,
                "evidence_refs": ["l0_atom_negative"],
            },
            evidence_id="l0_atom_negative",
            query="service-b DatabaseConnectionError not connection pool leak",
            service="service-b",
            alert_name="DatabaseConnectionError",
        )

    def test_extract_config_or_deploy_change(self):
        self._extract_single_atom(
            atom_type="config_or_deploy_change",
            atom_payload={
                "atom_type": "config_or_deploy_change",
                "service": "service-c",
                "alert_name": "ConnectionPoolLeak",
                "claim": "service-c 的连接池配置在上周已经更新",
                "confidence": 0.8,
                "evidence_refs": ["l0_atom_config"],
            },
            evidence_id="l0_atom_config",
            query="service-c connection pool config updated last week",
        )

    def test_extraction_schema_validation_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_store = self._evidence_store(tmpdir)
            memory_store = self._memory_store(tmpdir)
            self._create_evidence(
                evidence_store,
                evidence_id="l0_atom_bad",
                session_id="session-aiops-2",
                query="service-a CPUHigh alert triggered again",
            )
            service = MemoryExtractorService(
                evidence_store=evidence_store,
                store=memory_store,
                extraction_chain=FakeExtractionChain(
                    {
                        "atoms": [
                            {
                                "atom_type": "root_cause_observation",
                                "service": "service-a",
                                "alert_name": "CPUHigh",
                                "confidence": 0.95,
                                "evidence_refs": ["l0_atom_bad"],
                            }
                        ]
                    }
                ),
            )

            atoms = service.extract_atoms_from_evidence("l0_atom_bad")

            self.assertEqual(atoms, [])
            self.assertEqual(service.get_metrics()["extraction_schema_failure_count"], 1)
            self.assertEqual(
                memory_store.list_memories(memory_type=MemoryType.L1_ATOM, status=MemoryStatus.CANDIDATE),
                [],
            )

    def test_extraction_missing_evidence_refs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_store = self._evidence_store(tmpdir)
            memory_store = self._memory_store(tmpdir)
            self._create_evidence(
                evidence_store,
                evidence_id="l0_atom_missing_refs",
                session_id="session-aiops-3",
                query="service-a CPUHigh alert triggered again",
            )
            service = MemoryExtractorService(
                evidence_store=evidence_store,
                store=memory_store,
                extraction_chain=FakeExtractionChain(
                    {
                        "atoms": [
                            {
                                "atom_type": "check_observation",
                                "service": "service-a",
                                "alert_name": "CPUHigh",
                                "claim": "service-a CPUHigh 必须先查 user_cpu",
                                "check_name": "query_cpu_metrics",
                                "confidence": 0.8,
                                "evidence_refs": [],
                            }
                        ]
                    }
                ),
            )

            atoms = service.extract_atoms_from_evidence("l0_atom_missing_refs")

            self.assertEqual(atoms, [])
            self.assertEqual(service.get_metrics()["extraction_schema_failure_count"], 1)

    def test_extraction_empty_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_store = self._evidence_store(tmpdir)
            memory_store = self._memory_store(tmpdir)
            self._create_evidence(
                evidence_store,
                evidence_id="l0_atom_empty",
                session_id="session-aiops-4",
                query="service-a CPUHigh alert triggered again",
            )
            service = MemoryExtractorService(
                evidence_store=evidence_store,
                store=memory_store,
                extraction_chain=FakeExtractionChain({"atoms": []}),
            )

            atoms = service.extract_atoms_from_evidence("l0_atom_empty")

            self.assertEqual(atoms, [])
            self.assertEqual(service.get_metrics()["extraction_empty_count"], 1)

    def test_extraction_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_store = self._evidence_store(tmpdir)
            memory_store = self._memory_store(tmpdir)

            self._create_evidence(
                evidence_store,
                evidence_id="l0_atom_metrics_ok",
                session_id="session-aiops-5",
                query="service-a CPUHigh alert triggered again",
            )
            self._create_evidence(
                evidence_store,
                evidence_id="l0_atom_metrics_empty",
                session_id="session-aiops-6",
                query="service-a CPUHigh alert triggered again",
            )
            self._create_evidence(
                evidence_store,
                evidence_id="l0_atom_metrics_bad",
                session_id="session-aiops-7",
                query="service-a CPUHigh alert triggered again",
            )

            service = MemoryExtractorService(
                evidence_store=evidence_store,
                store=memory_store,
                extraction_chain=FakeExtractionChain(
                    {
                        "atoms": [
                            {
                                "atom_type": "remediation_observation",
                                "service": "service-a",
                                "alert_name": "CPUHigh",
                                "claim": "service-a CPUHigh 可通过 rollback recent deploy 修复",
                                "remediation": "rollback recent deploy",
                                "confidence": 0.9,
                                "evidence_refs": ["l0_atom_metrics_ok"],
                            }
                        ]
                    }
                ),
            )

            service.extract_atoms_from_evidence("l0_atom_metrics_ok")
            service.extraction_chain = FakeExtractionChain({"atoms": []})
            service.extract_atoms_from_evidence("l0_atom_metrics_empty")
            service.extraction_chain = FakeExtractionChain(
                {
                    "atoms": [
                        {
                            "atom_type": "check_observation",
                            "service": "service-a",
                            "alert_name": "CPUHigh",
                            "claim": "",
                            "check_name": "query_cpu_metrics",
                            "confidence": 0.8,
                            "evidence_refs": ["l0_atom_metrics_bad"],
                        }
                    ]
                }
            )
            service.extract_atoms_from_evidence("l0_atom_metrics_bad")

            metrics = service.get_metrics()
            self.assertEqual(metrics["extraction_attempt_count"], 3)
            self.assertEqual(metrics["extraction_success_count"], 1)
            self.assertEqual(metrics["extraction_empty_count"], 1)
            self.assertEqual(metrics["extraction_schema_failure_count"], 1)

    def test_transient_failure_retries_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_store = self._evidence_store(tmpdir)
            memory_store = self._memory_store(tmpdir)
            self._create_evidence(
                evidence_store,
                evidence_id="l0_atom_retry",
                session_id="session-aiops-8",
                query="service-a CPUHigh alert triggered again",
            )
            service = MemoryExtractorService(
                evidence_store=evidence_store,
                store=memory_store,
                extraction_chain=FlakyExtractionChain(
                    {
                        "atoms": [
                            {
                                "atom_type": "check_observation",
                                "service": "service-a",
                                "alert_name": "CPUHigh",
                                "claim": "service-a CPUHigh 场景下必须先查 user_cpu 和 system_cpu",
                                "check_name": "query_cpu_metrics(user_cpu, system_cpu)",
                                "confidence": 0.8,
                                "evidence_refs": ["l0_atom_retry"],
                            }
                        ]
                    }
                ),
                transient_retry_count=1,
            )

            atoms = service.extract_atoms_from_evidence("l0_atom_retry")

            self.assertEqual(len(atoms), 1)
            self.assertEqual(len(service.extraction_chain.calls), 2)
            self.assertEqual(service.get_metrics()["transient_failed_count"], 0)

    def _extract_single_atom(
        self,
        *,
        atom_type: str,
        atom_payload: dict,
        evidence_id: str,
        query: str,
        service: str | None = "service-a",
        alert_name: str | None = "CPUHigh",
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_store = self._evidence_store(tmpdir)
            memory_store = self._memory_store(tmpdir)
            self._create_evidence(
                evidence_store,
                evidence_id=evidence_id,
                session_id=f"session-{evidence_id}",
                query=query,
                service=service,
                alert_name=alert_name,
            )
            service_obj = MemoryExtractorService(
                evidence_store=evidence_store,
                store=memory_store,
                extraction_chain=FakeExtractionChain({"atoms": [atom_payload]}),
            )

            atoms = service_obj.extract_atoms_from_evidence(evidence_id)

            self.assertEqual(len(atoms), 1)
            atom = atoms[0]
            self.assertEqual(atom.atom_type, atom_type)
            self.assertEqual(atom.evidence_id, evidence_id)
            self.assertEqual(atom.evidence_refs, [evidence_id])
            self.assertEqual(atom.status, "candidate")
            stored = memory_store.get(atom.atom_id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.status, MemoryStatus.CANDIDATE)
            self.assertEqual(stored.memory_type, MemoryType.L1_ATOM)
            self.assertEqual(stored.payload.atom_type, atom_type)
            self.assertEqual(stored.payload.evidence_refs, [evidence_id])


if __name__ == "__main__":
    unittest.main()
