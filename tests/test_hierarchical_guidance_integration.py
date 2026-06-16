import unittest
from datetime import datetime, timezone

from app.models.memory import MemoryStatus, MemoryType
from app.services.hierarchical_retrieval_service import HierarchicalRetrievalResult
from app.services.memory_guidance_service import MemoryGuidanceService
from app.services.memory_retrieval_service import MemoryRetrievalResult


class HierarchicalGuidanceIntegrationTests(unittest.TestCase):
    def test_l2_scenario_guidance_format(self):
        result = HierarchicalRetrievalResult(
            query="service-a CPUHigh",
            owner_id="ops-team",
            l2_scenarios=[
                self._result(
                    "l2_cpu_scenario",
                    MemoryType.L2_SCENARIO,
                    payload={
                        "scenario_title": "Scenario: service-a CPUHigh",
                        "applicable_conditions": ["service-a", "CPUHigh", "prod"],
                        "diagnostic_path": ["query_cpu_metrics(user_cpu, system_cpu)"],
                        "common_root_causes": ["cache memory leak"],
                        "remediation_steps": ["rollback recent deploy"],
                        "l1_atom_ids": ["l1_cpu_root", "l1_cpu_check"],
                        "evidence_refs": [{"evidence_id": "l0_cpu_root"}],
                    },
                )
            ],
            trace={"retrieval_mode": "hierarchical_lexical_v1"},
        )

        guidance = MemoryGuidanceService.format_hierarchical_guidance(result)

        self.assertIn("基于历史场景经验", guidance)
        self.assertIn("service-a", guidance)
        self.assertIn("query_cpu_metrics", guidance)
        self.assertIn("cache memory leak", guidance)
        self.assertIn("rollback recent deploy", guidance)
        self.assertIn("l1_cpu_root", guidance)
        self.assertIn("l0_cpu_root", guidance)
        self.assertIn("不是文档 citation", guidance)

    def test_l1_atom_guidance_format(self):
        result = HierarchicalRetrievalResult(
            query="service-a CPUHigh",
            owner_id="ops-team",
            l1_atoms=[
                self._result(
                    "l1_cpu_root",
                    MemoryType.L1_ATOM,
                    payload={
                        "claim": "service-a CPUHigh current root cause is cache memory leak",
                        "root_cause": "cache memory leak",
                        "check_name": "query_cpu_metrics",
                        "remediation": "rollback recent deploy",
                        "evidence_refs": ["l0_cpu_root"],
                    },
                )
            ],
            trace={"retrieval_mode": "hierarchical_lexical_v1"},
        )

        guidance = MemoryGuidanceService.format_hierarchical_guidance(result)

        self.assertIn("基于历史原子观测", guidance)
        self.assertIn("service-a CPUHigh current root cause", guidance)
        self.assertIn("cache memory leak", guidance)
        self.assertIn("query_cpu_metrics", guidance)
        self.assertIn("rollback recent deploy", guidance)
        self.assertIn("l0_cpu_root", guidance)

    def test_legacy_memory_guidance_format(self):
        result = HierarchicalRetrievalResult(
            query="service-a CPUHigh",
            owner_id="default",
            legacy_memories=[
                self._result(
                    "mem_alert_cpu_high",
                    MemoryType.ALERT_PATTERN,
                    payload={
                        "alert_name": "CPUHigh",
                        "service": "service-a",
                        "root_cause": "cache memory leak",
                    },
                )
            ],
            trace={"retrieval_mode": "hierarchical_lexical_v1"},
        )

        guidance = MemoryGuidanceService.format_hierarchical_guidance(result)

        self.assertIn("基于历史记忆（待聚合）", guidance)
        self.assertIn("运行时记忆指导", guidance)
        self.assertIn("mem_alert_cpu_high", guidance)

    def test_guidance_preserves_current_observation_priority(self):
        result = HierarchicalRetrievalResult(
            query="service-a CPUHigh",
            owner_id="ops-team",
            l2_scenarios=[
                self._result(
                    "l2_cpu_scenario",
                    MemoryType.L2_SCENARIO,
                    payload={
                        "scenario_title": "Scenario: service-a CPUHigh",
                        "applicable_conditions": ["service-a"],
                        "diagnostic_path": ["query_cpu_metrics"],
                        "common_root_causes": ["cache memory leak"],
                        "remediation_steps": [],
                        "l1_atom_ids": ["l1_cpu_root"],
                        "evidence_refs": [{"evidence_id": "l0_cpu_root"}],
                    },
                )
            ],
            trace={"retrieval_mode": "hierarchical_lexical_v1"},
        )

        guidance = MemoryGuidanceService.format_hierarchical_guidance(result)

        self.assertIn("当前工具观测", guidance)
        self.assertIn("优先", guidance)
        self.assertIn("当前观测明确反驳", guidance)

    def _result(
        self,
        memory_id: str,
        memory_type: MemoryType,
        *,
        payload: dict,
    ) -> MemoryRetrievalResult:
        now = datetime.now(timezone.utc)
        return MemoryRetrievalResult(
            memory_id=memory_id,
            owner_id="ops-team",
            namespace=f"memory://oncall/{memory_type.value}",
            memory_type=memory_type,
            status=MemoryStatus.ACTIVE,
            content=f"{memory_id} content",
            summary=f"{memory_id} summary",
            score=1.0,
            matched_terms=["service-a", "CPUHigh"],
            evidence_refs=[{"evidence_id": "l0_cpu_root"}],
            payload=payload,
            source="unit-test",
            tags=[],
            updated_at=now,
        )


if __name__ == "__main__":
    unittest.main()
