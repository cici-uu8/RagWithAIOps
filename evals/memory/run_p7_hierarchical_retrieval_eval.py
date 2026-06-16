"""Deterministic eval for P7.5 hierarchical retrieval."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.models.memory import AlertPatternPayload, L1Atom, L2ScenarioPayload, MemoryRecord, MemoryStatus, MemoryType
from app.models.memory_atom import L1AtomExtractionMethod, L1AtomType
from app.services.hierarchical_retrieval_service import HierarchicalRetrievalService
from app.services.memory_store import MemoryStore


def _l1_record(memory_id: str, *, atom_type: L1AtomType = L1AtomType.ROOT_CAUSE_OBSERVATION) -> MemoryRecord:
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
        source="p7_eval_fixture",
        evidence={"evidence_type": "l1_atom_candidate", "l0_evidence_refs": [f"l0_{memory_id}"]},
        status=MemoryStatus.ACTIVE,
        tags=["l1_atom", atom.atom_type.value],
    )


def _l2_record(memory_id: str, *, l1_atom_ids: list[str], confidence: float = 0.95) -> MemoryRecord:
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
        scenario_markdown="# Scenario: service-a CPUHigh (prod)",
    )
    return MemoryRecord(
        memory_id=memory_id,
        owner_id="ops-team",
        namespace="memory://oncall/l2-scenarios",
        memory_type=MemoryType.L2_SCENARIO,
        content=payload.scenario_markdown,
        summary=payload.scenario_title,
        payload=payload,
        source="p7_eval_fixture",
        evidence={
            "evidence_type": "l2_scenario_candidate",
            "scenario_key": payload.scenario_key,
            "l1_atom_ids": l1_atom_ids,
            "l0_evidence_refs": [ref["evidence_id"] for ref in payload.evidence_refs],
            "confidence": confidence,
        },
        status=MemoryStatus.ACTIVE,
        tags=["l2_scenario", "service-a", "CPUHigh"],
    )


def _legacy_record(memory_id: str, updated_at: datetime) -> MemoryRecord:
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
        source="p7_eval_fixture",
        evidence={"evidence_type": "seed_memory", "service": "service-a", "alert_name": "CPUHigh"},
        status=MemoryStatus.ACTIVE,
        tags=["cpu", "cache"],
        created_at=updated_at,
        updated_at=updated_at,
    )


def run_eval() -> Dict[str, Any]:
    cases: list[dict[str, Any]] = []
    latencies: list[float] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        store = MemoryStore(Path(tmpdir) / "memory.sqlite3")
        store.upsert(_l2_record("l2_cpu_scenario", l1_atom_ids=["l1_cpu_root", "l1_cpu_check"]))
        store.upsert(_l1_record("l1_cpu_root"))
        store.upsert(_l1_record("l1_cpu_check", atom_type=L1AtomType.CHECK_OBSERVATION))

        service = HierarchicalRetrievalService(store=store)
        start = time.perf_counter()
        response = service.retrieve_hierarchical(
            "service-a CPUHigh cache memory leak",
            owner_id="ops-team",
            top_k_l2=2,
            top_k_l1=3,
            top_k_legacy=3,
        )
        latencies.append((time.perf_counter() - start) * 1000)
        cases.append(
            {
                "case_id": "l2_hit",
                "passed": [item.memory_id for item in response.l2_scenarios] == ["l2_cpu_scenario"],
                "returned_l2_ids": [item.memory_id for item in response.l2_scenarios],
                "returned_l1_ids": [item.memory_id for item in response.l1_atoms],
                "returned_legacy_ids": [item.memory_id for item in response.legacy_memories],
                "trace": response.trace,
            }
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        store = MemoryStore(Path(tmpdir) / "memory.sqlite3")
        store.upsert(_l1_record("l1_cpu_root"))

        service = HierarchicalRetrievalService(store=store)
        start = time.perf_counter()
        response = service.retrieve_hierarchical(
            "service-a CPUHigh cache memory leak",
            owner_id="ops-team",
            top_k_l2=2,
            top_k_l1=3,
            top_k_legacy=3,
        )
        latencies.append((time.perf_counter() - start) * 1000)
        cases.append(
            {
                "case_id": "l1_fallback",
                "passed": [item.memory_id for item in response.l1_atoms] == ["l1_cpu_root"],
                "returned_l2_ids": [item.memory_id for item in response.l2_scenarios],
                "returned_l1_ids": [item.memory_id for item in response.l1_atoms],
                "returned_legacy_ids": [item.memory_id for item in response.legacy_memories],
                "trace": response.trace,
            }
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        store = MemoryStore(Path(tmpdir) / "memory.sqlite3")
        now = datetime.now(timezone.utc)
        store.upsert(
            _legacy_record("mem_old_cpu_high", updated_at=now - timedelta(days=14)),
            preserve_timestamps=True,
        )
        store.upsert(
            _legacy_record("mem_new_cpu_high", updated_at=now - timedelta(days=1)),
            preserve_timestamps=True,
        )

        service = HierarchicalRetrievalService(store=store, min_l1_hits=2)
        start = time.perf_counter()
        response = service.retrieve_hierarchical(
            "service-a CPUHigh fixed last week but alert triggered again",
            owner_id="default",
            top_k_l2=2,
            top_k_l1=1,
            top_k_legacy=2,
        )
        latencies.append((time.perf_counter() - start) * 1000)
        cases.append(
            {
                "case_id": "legacy_fallback",
                "passed": [item.memory_id for item in response.legacy_memories]
                == ["mem_new_cpu_high", "mem_old_cpu_high"],
                "returned_l2_ids": [item.memory_id for item in response.l2_scenarios],
                "returned_l1_ids": [item.memory_id for item in response.l1_atoms],
                "returned_legacy_ids": [item.memory_id for item in response.legacy_memories],
                "trace": response.trace,
            }
        )

    l2_hit_count = sum(len(case["trace"]["l2_retrieval"]["matched_scenarios"]) for case in cases)
    l2_confidence_sum = sum(
        item["confidence"]
        for case in cases
        for item in case["trace"]["l2_retrieval"]["matched_scenarios"]
    )
    l1_fallback_count = sum(1 for case in cases if case["trace"]["l2_retrieval"]["fallback_to_l1"])
    legacy_fallback_count = sum(1 for case in cases if case["trace"]["l1_retrieval"]["fallback_to_legacy"])
    summary = {
        "cases_total": len(cases),
        "cases_passed": sum(1 for case in cases if case["passed"]),
        "trace_complete_cases": sum(
            1
            for case in cases
            if all(key in case["trace"] for key in ("l2_retrieval", "l1_retrieval", "legacy_retrieval", "stale_policy"))
        ),
        "hierarchical_retrieval_l2_hit_count": l2_hit_count,
        "hierarchical_retrieval_l1_fallback_count": l1_fallback_count,
        "hierarchical_retrieval_legacy_fallback_count": legacy_fallback_count,
        "hierarchical_retrieval_l2_avg_confidence": round(l2_confidence_sum / l2_hit_count, 3)
        if l2_hit_count
        else 0.0,
        "latency_ms_avg": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
    }

    return {
        "eval_name": "p7_hierarchical_retrieval_eval",
        "eval_status": "valid",
        "continue_rollout": True,
        "metrics": summary,
        "results": cases,
    }


def save_report(report: Dict[str, Any]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(__file__).parent / f"p7_hierarchical_retrieval_eval_{timestamp}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def main() -> int:
    report = run_eval()
    output_path = save_report(report)
    metrics = report["metrics"]
    print(f"p7_hierarchical_retrieval_eval report: {output_path}")
    print(
        "metrics: "
        f"cases_total={metrics['cases_total']} "
        f"cases_passed={metrics['cases_passed']} "
        f"trace_complete_cases={metrics['trace_complete_cases']} "
        f"l2_hit_count={metrics['hierarchical_retrieval_l2_hit_count']} "
        f"l1_fallback_count={metrics['hierarchical_retrieval_l1_fallback_count']} "
        f"legacy_fallback_count={metrics['hierarchical_retrieval_legacy_fallback_count']} "
        f"l2_avg_confidence={metrics['hierarchical_retrieval_l2_avg_confidence']:.3f} "
        f"latency_ms_avg={metrics['latency_ms_avg']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
