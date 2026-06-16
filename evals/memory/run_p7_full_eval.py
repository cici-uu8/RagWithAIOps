"""Deterministic full-chain eval for P7 layered oncall memory."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

planner_module = importlib.import_module("app.agent.aiops.planner")
from app.agent.aiops.planner import Plan
from app.models.memory import AlertPatternPayload, MemoryRecord, MemoryStatus, MemoryType
from app.models.memory_candidate import AIOpsPastStep, AIOpsSessionState
from app.services.conflict_detector_service import ConflictDetectorService
from app.services.hierarchical_retrieval_service import HierarchicalRetrievalService
from app.services.memory_aggregator_service import MemoryAggregatorService
from app.services.memory_evidence_store import MemoryEvidenceStore
from app.services.memory_extractor_service import MemoryExtractorService
from app.services.memory_guidance_provider import MemoryGuidanceProvider
from app.services.memory_ingestion_service import MemoryIngestionService
from app.services.memory_lifecycle_service import MemoryLifecycleService
from app.services.memory_retrieval_service import MemoryRetrievalQuery, MemoryRetrievalService
from app.services.memory_review_service import MemoryReviewService
from app.services.memory_store import MemoryStore
from app.services.memory_trace_service import MemoryTraceService


class FakeExtractionChain:
    """Deterministic stand-in for schema-bound extraction."""

    def __init__(self, responses_by_evidence_id: dict[str, list[dict[str, Any]]]):
        self.responses_by_evidence_id = responses_by_evidence_id
        self.calls: list[dict[str, Any]] = []

    def invoke(self, payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        self.calls.append(payload)
        evidence_payload = json.loads(payload["evidence_json"])
        evidence_id = evidence_payload["evidence_id"]
        return {"atoms": list(self.responses_by_evidence_id.get(evidence_id, []))}


def _case_result(
    case_id: str,
    checks: list[dict[str, Any]],
    *,
    artifacts: dict[str, Any] | None = None,
    trace_complete: bool = False,
    latency_ms: float | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
        "trace_complete": trace_complete,
        "latency_ms": round(latency_ms, 3) if latency_ms is not None else None,
        "artifacts": artifacts or {},
    }


def _check(name: str, passed: bool, **details: Any) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), **details}


def _memory_store(root: Path) -> MemoryStore:
    return MemoryStore(root / "memory.sqlite3")


def _evidence_store(root: Path) -> MemoryEvidenceStore:
    return MemoryEvidenceStore(
        store_path=root / "memory_evidence.sqlite3",
        refs_dir=root / "refs",
    )


def _provider(root: Path) -> MemoryGuidanceProvider:
    return MemoryGuidanceProvider(
        trace_service=MemoryTraceService(trace_dir=str(root / "traces"))
    )


def _aiops_state(
    *,
    session_id: str,
    input_text: str,
    response: str,
) -> AIOpsSessionState:
    return AIOpsSessionState(
        session_id=session_id,
        input=input_text,
        plan_steps=[
            "check cpu metrics",
            "check recent deploy",
            "confirm remediation",
        ],
        past_steps=[
            AIOpsPastStep(step="check cpu metrics", result="user_cpu=95, system_cpu=8", step_index=0),
            AIOpsPastStep(step="check recent deploy", result="deploy v42 rolled out 30m ago", step_index=1),
        ],
        response=response,
    )


def _active_alert_record(
    memory_id: str,
    *,
    owner_id: str = "ops-team",
    root_cause: str,
    fix: str = "scale replicas",
    updated_at: datetime | None = None,
) -> MemoryRecord:
    updated_at = updated_at or datetime.now(timezone.utc)
    return MemoryRecord(
        memory_id=memory_id,
        owner_id=owner_id,
        namespace="memory://oncall/alert-patterns",
        memory_type=MemoryType.ALERT_PATTERN,
        content=f"service-a CPUHigh root cause is {root_cause}",
        summary=f"service-a CPUHigh {root_cause}",
        payload=AlertPatternPayload(
            alert_name="CPUHigh",
            service="service-a",
            severity="critical",
            signal_keys=["cpu_usage", "deploy"],
            metric_patterns=["cpu > 85%"],
            log_patterns=[],
            root_cause=root_cause,
            fix=fix,
            evidence_refs=[
                {
                    "evidence_type": "seed_memory",
                    "evidence_id": f"l0_{memory_id}",
                }
            ],
        ),
        source="p7_full_eval_fixture",
        evidence={
            "evidence_type": "seed_memory",
            "service": "service-a",
            "alert_name": "CPUHigh",
            "environment": "prod",
        },
        status=MemoryStatus.ACTIVE,
        tags=["p7_full_eval", "cpu", "service-a"],
        created_at=updated_at,
        updated_at=updated_at,
    )


def _cpu_layered_atoms(evidence_id: str) -> list[dict[str, Any]]:
    return [
        {
            "atom_type": "root_cause_observation",
            "service": "service-a",
            "alert_name": "CPUHigh",
            "environment": "prod",
            "claim": "service-a CPUHigh current root cause is cache memory leak",
            "root_cause": "cache memory leak",
            "confidence": 0.95,
            "evidence_refs": [evidence_id],
        },
        {
            "atom_type": "check_observation",
            "service": "service-a",
            "alert_name": "CPUHigh",
            "environment": "prod",
            "claim": "service-a CPUHigh should first check user_cpu and system_cpu",
            "check_name": "query_cpu_metrics(user_cpu, system_cpu)",
            "confidence": 0.9,
            "evidence_refs": [evidence_id],
        },
        {
            "atom_type": "remediation_observation",
            "service": "service-a",
            "alert_name": "CPUHigh",
            "environment": "prod",
            "claim": "service-a CPUHigh can be fixed by rollback recent deploy",
            "remediation": "rollback recent deploy",
            "confidence": 0.88,
            "evidence_refs": [evidence_id],
        },
        {
            "atom_type": "negative_observation",
            "service": "service-a",
            "alert_name": "CPUHigh",
            "claim": "invalid atom intentionally misses evidence_refs",
            "confidence": 0.8,
        },
    ]


def _conflict_atoms(evidence_id: str) -> list[dict[str, Any]]:
    return [
        {
            "atom_type": "negative_observation",
            "service": "service-a",
            "alert_name": "CPUHigh",
            "environment": "prod",
            "claim": "service-a CPUHigh is not traffic spike after fresh checks",
            "negates_memory_id": "mem_active_cpu_restore",
            "confidence": 0.9,
            "evidence_refs": [evidence_id],
        },
        {
            "atom_type": "negative_observation",
            "service": "service-a",
            "alert_name": "CPUHigh",
            "environment": "prod",
            "claim": "service-a CPUHigh is not cache memory leak after current deploy verification",
            "negates_memory_id": "mem_active_cpu_supersede",
            "confidence": 0.9,
            "evidence_refs": [evidence_id],
        },
    ]


async def _planner_probe(
    *,
    provider: MemoryGuidanceProvider,
    store_path: Path,
    input_text: str,
    owner_id: str,
) -> dict[str, Any]:
    captured: dict[str, Any] = {"experience_context": ""}

    with patch("app.agent.aiops.planner.retrieve_knowledge") as mock_retrieve, patch(
        "app.agent.aiops.planner.get_mcp_tools_with_retry"
    ) as mock_mcp, patch("app.agent.aiops.planner.planner_prompt") as mock_prompt, patch(
        "app.agent.aiops.planner.ChatQwen"
    ) as mock_chat, patch("app.agent.aiops.planner.memory_guidance_provider", provider):
        mock_retrieve.ainvoke = AsyncMock(return_value="Document: always verify current metrics before reuse.")
        mock_mcp.return_value = []
        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = MagicMock()
        mock_chat.return_value = mock_llm

        mock_chain = MagicMock()

        async def capture_ainvoke(payload: dict[str, Any]) -> Plan:
            captured["experience_context"] = payload.get("experience_context", "")
            captured["tools_description"] = payload.get("tools_description", "")
            return Plan(steps=["check current cpu metrics", "verify deploy state", "write diagnosis"])

        mock_chain.ainvoke = AsyncMock(side_effect=capture_ainvoke)
        mock_prompt.__or__ = MagicMock(return_value=mock_chain)

        planner_result = await planner_module.planner(
            {
                "input": input_text,
                "memory_mode": "active",
                "memory_owner_id": owner_id,
                "memory_store_path": str(store_path),
            }
        )

    return {
        "planner_result": planner_result,
        "captured_experience_context": captured["experience_context"],
    }


def _run_layered_planner_case(root: Path) -> dict[str, Any]:
    start = time.perf_counter()
    root.mkdir(parents=True, exist_ok=True)
    evidence_store = _evidence_store(root)
    store = _memory_store(root)
    ingestion = MemoryIngestionService(store=evidence_store)
    review = MemoryReviewService(store=store)

    evidence_id = "l0_p7_full_cpu"
    evidence = ingestion.ingest_aiops_diagnosis(
        _aiops_state(
            session_id="session-p7-full-cpu",
            input_text="service-a CPUHigh alert triggered again",
            response="Root cause: cache memory leak. Remediation: rollback recent deploy.",
        ),
        owner_id="ops-team",
        key_events=[{"type": "root_cause", "value": "cache memory leak"}],
        tool_results=[{"tool": "query_cpu_metrics", "result": {"user_cpu": 95, "system_cpu": 8}}],
        memory_observation={"mode": "active", "memory_ids": []},
        service="service-a",
        alert_name="CPUHigh",
        environment="prod",
        evidence_id=evidence_id,
    )
    evidence_store.create_aiops_evidence(
        evidence_id="l0_p7_full_old_cleanup",
        session_id="session-p7-full-old",
        owner_id="ops-team",
        query="old cleanup candidate",
        service="service-z",
        alert_name="OldAlert",
        environment="prod",
        plan=[],
        past_steps=[],
        final_response="old evidence",
        key_events=[],
        created_at=datetime.now() - timedelta(days=60),
    )
    integrity = evidence_store.check_integrity(evidence.evidence_id)
    cleanup_plan = evidence_store.cleanup_expired_evidence(owner_id="ops-team", retention_days=30, dry_run=True)

    extractor = MemoryExtractorService(
        evidence_store=evidence_store,
        store=store,
        extraction_chain=FakeExtractionChain({evidence_id: _cpu_layered_atoms(evidence_id)}),
    )
    atoms = extractor.extract_atoms_from_evidence(evidence_id)
    atom_records = [store.get(atom.atom_id) for atom in atoms]
    active_atoms = [
        review.approve_candidate(
            atom.atom_id,
            reviewer_id="p7-full-eval",
            decision_note="approve deterministic L1 atom for full-chain eval",
        )
        for atom in atoms
    ]

    aggregator = MemoryAggregatorService(store=store)
    aggregation = aggregator.aggregate_from_atom_ids([atom.atom_id for atom in atoms], owner_id="ops-team")
    scenario = aggregation.records[0] if aggregation.records else None
    active_scenario = None
    if scenario is not None:
        active_scenario = review.approve_candidate(
            scenario.memory_id,
            reviewer_id="p7-full-eval",
            decision_note="approve deterministic L2 scenario for full-chain eval",
        )

    provider = _provider(root)
    provider_result = provider.build(
        {
            "input": "service-a CPUHigh cache memory leak rollback recent deploy",
            "memory_mode": "active",
            "memory_owner_id": "ops-team",
            "memory_store_path": str(root / "memory.sqlite3"),
        }
    )
    provider_trace = (provider_result.observation or {}).get("retrieval_trace", {})
    planner_probe = asyncio.run(
        _planner_probe(
            provider=provider,
            store_path=root / "memory.sqlite3",
            input_text="service-a CPUHigh cache memory leak rollback recent deploy",
            owner_id="ops-team",
        )
    )
    context = planner_probe["captured_experience_context"]
    memory_pos = context.find("分层运行时记忆指导")
    doc_pos = context.find("相关经验文档")
    planner_observation = planner_probe["planner_result"].get("memory_observation", {})

    checks = [
        _check("l0_integrity_ok", integrity.get("ok") is True, refs_checked=integrity.get("refs_checked")),
        _check(
            "l0_cleanup_dry_run_ok",
            cleanup_plan["dry_run"] is True
            and cleanup_plan["planned_delete_count"] == 1
            and cleanup_plan["deleted_count"] == 0,
            planned_delete_count=cleanup_plan["planned_delete_count"],
        ),
        _check("l1_extracted_three_valid_atoms", len(atoms) == 3, atom_count=len(atoms)),
        _check(
            "l1_schema_failure_recorded",
            extractor.get_metrics()["extraction_schema_failure_count"] == 1,
            metrics=extractor.get_metrics(),
        ),
        _check(
            "l1_candidate_records_stored",
            all(record is not None and record.status == MemoryStatus.CANDIDATE for record in atom_records),
        ),
        _check(
            "l1_approved_active",
            all(record.status == MemoryStatus.ACTIVE for record in active_atoms),
            active_atom_ids=[record.memory_id for record in active_atoms],
        ),
        _check("l2_candidate_created", aggregation.action == "created" and scenario is not None),
        _check(
            "l2_approved_active",
            active_scenario is not None and active_scenario.status == MemoryStatus.ACTIVE,
            scenario_id=getattr(active_scenario, "memory_id", None),
        ),
        _check(
            "provider_hit_l2_scenario",
            (provider_result.observation or {}).get("memory_ids") == ([active_scenario.memory_id] if active_scenario else []),
            memory_ids=(provider_result.observation or {}).get("memory_ids", []),
        ),
        _check(
            "provider_guidance_contains_trace_refs",
            "基于历史场景经验" in provider_result.guidance_text
            and evidence_id in provider_result.guidance_text
            and all(atom.atom_id in provider_result.guidance_text for atom in atoms),
        ),
        _check(
            "planner_injected_memory_guidance",
            "分层运行时记忆指导" in context
            and (active_scenario is not None and active_scenario.memory_id in str(planner_observation.get("memory_ids", []))),
        ),
        _check(
            "planner_kept_document_context_after_memory",
            memory_pos >= 0 and doc_pos > memory_pos,
            memory_pos=memory_pos,
            document_pos=doc_pos,
        ),
    ]
    trace_complete = all(key in provider_trace for key in ("l2_retrieval", "l1_retrieval", "legacy_retrieval", "stale_policy"))
    return _case_result(
        "l0_l1_l2_to_planner_guidance",
        checks,
        trace_complete=trace_complete,
        latency_ms=(time.perf_counter() - start) * 1000,
        artifacts={
            "evidence_id": evidence_id,
            "l1_atom_ids": [atom.atom_id for atom in atoms],
            "l2_scenario_id": active_scenario.memory_id if active_scenario else None,
            "provider_memory_ids": (provider_result.observation or {}).get("memory_ids", []),
            "planner_plan": planner_probe["planner_result"].get("plan", []),
            "planner_memory_ids": planner_observation.get("memory_ids", []),
            "retrieval_trace": provider_trace,
            "experience_context_preview": context[:1200],
        },
    )


def _run_conflict_lifecycle_case(root: Path) -> dict[str, Any]:
    start = time.perf_counter()
    root.mkdir(parents=True, exist_ok=True)
    evidence_store = _evidence_store(root)
    store = _memory_store(root)
    ingestion = MemoryIngestionService(store=evidence_store)

    store.upsert(_active_alert_record("mem_active_cpu_restore", root_cause="traffic spike"))
    store.upsert(_active_alert_record("mem_active_cpu_supersede", root_cause="cache memory leak"))

    evidence_id = "l0_p7_full_conflict"
    evidence = ingestion.ingest_aiops_diagnosis(
        _aiops_state(
            session_id="session-p7-full-conflict",
            input_text="service-a CPUHigh was rechecked after deploy",
            response="Fresh checks show the old root-cause assumptions are no longer valid.",
        ),
        owner_id="ops-team",
        key_events=[{"type": "fresh_check", "value": "old root causes denied"}],
        tool_results=[{"tool": "query_cpu_metrics", "result": {"user_cpu": 45, "system_cpu": 6}}],
        service="service-a",
        alert_name="CPUHigh",
        environment="prod",
        evidence_id=evidence_id,
    )

    extractor = MemoryExtractorService(
        evidence_store=evidence_store,
        store=store,
        extraction_chain=FakeExtractionChain({evidence.evidence_id: _conflict_atoms(evidence.evidence_id)}),
    )
    atoms = extractor.extract_atoms_from_evidence(evidence.evidence_id)
    atoms_by_negated = {atom.negates_memory_id: atom for atom in atoms}
    detector = ConflictDetectorService(store=store)
    lifecycle = MemoryLifecycleService(store=store, conflict_detector=detector)
    review = MemoryReviewService(store=store)

    restore_atom = atoms_by_negated["mem_active_cpu_restore"]
    supersede_atom = atoms_by_negated["mem_active_cpu_supersede"]
    restore_conflicts = detector.detect_conflicts(restore_atom)
    lifecycle.apply_conflicts_for_atom(restore_atom)
    stale_restore = store.get("mem_active_cpu_restore")
    restored = review.restore_stale_suspect(
        "mem_active_cpu_restore",
        reviewer_id="ops-lead",
        decision_note="operator confirmed this old memory should remain active",
    )

    supersede_conflicts = detector.detect_conflicts(supersede_atom)
    lifecycle.apply_conflicts_for_atom(supersede_atom)
    stale_supersede = store.get("mem_active_cpu_supersede")
    superseded = review.supersede_memory(
        "mem_active_cpu_supersede",
        superseded_by=supersede_atom.atom_id,
        reviewer_id="ops-lead",
        decision_note="fresh evidence replaces old cache-leak hypothesis",
    )

    retrieval = MemoryRetrievalService(store=store).retrieve(
        MemoryRetrievalQuery(
            query="service-a CPUHigh",
            owner_id="ops-team",
            top_k=5,
        )
    )
    returned_ids = [result.memory_id for result in retrieval.memory_results]
    skipped_ids = [
        item["memory_id"]
        for item in retrieval.trace.get("lifecycle_filter", {}).get("skipped_memory", [])
    ]

    checks = [
        _check("conflict_atoms_extracted", len(atoms) == 2, atom_ids=[atom.atom_id for atom in atoms]),
        _check(
            "restore_conflict_detected",
            [result.memory_id for result in restore_conflicts] == ["mem_active_cpu_restore"],
            verdicts=[result.verdict.value for result in restore_conflicts],
        ),
        _check("restore_marked_stale_suspect", stale_restore.status == MemoryStatus.STALE_SUSPECT),
        _check("restore_review_reactivated_active", restored.status == MemoryStatus.ACTIVE),
        _check(
            "supersede_conflict_detected",
            [result.memory_id for result in supersede_conflicts] == ["mem_active_cpu_supersede"],
            verdicts=[result.verdict.value for result in supersede_conflicts],
        ),
        _check("supersede_marked_stale_suspect", stale_supersede.status == MemoryStatus.STALE_SUSPECT),
        _check("supersede_review_marked_superseded", superseded.status == MemoryStatus.SUPERSEDED),
        _check(
            "lifecycle_events_written",
            bool(restored.evidence.get("lifecycle_events")) and bool(superseded.evidence.get("lifecycle_events")),
        ),
        _check(
            "superseded_memory_filtered_from_retrieval",
            "mem_active_cpu_restore" in returned_ids
            and "mem_active_cpu_supersede" not in returned_ids
            and "mem_active_cpu_supersede" in skipped_ids,
            returned_ids=returned_ids,
            skipped_ids=skipped_ids,
        ),
    ]
    return _case_result(
        "conflict_lifecycle_state_machine",
        checks,
        trace_complete=bool(retrieval.trace.get("lifecycle_filter")),
        latency_ms=(time.perf_counter() - start) * 1000,
        artifacts={
            "evidence_id": evidence_id,
            "atom_ids": [atom.atom_id for atom in atoms],
            "restore_status": restored.status.value,
            "superseded_status": superseded.status.value,
            "retrieval_trace": retrieval.trace,
            "lifecycle_metrics": lifecycle.get_metrics(),
            "conflict_metrics": detector.get_metrics(),
        },
    )


def _run_legacy_fallback_case(root: Path) -> dict[str, Any]:
    start = time.perf_counter()
    root.mkdir(parents=True, exist_ok=True)
    store = _memory_store(root)
    now = datetime.now(timezone.utc)
    store.upsert(
        _active_alert_record(
            "mem_old_cpu_high",
            owner_id="default",
            root_cause="cache memory leak",
            fix="restart cache worker",
            updated_at=now - timedelta(days=14),
        ),
        preserve_timestamps=True,
    )
    store.upsert(
        _active_alert_record(
            "mem_new_cpu_high",
            owner_id="default",
            root_cause="recent deploy rollback needed",
            fix="rollback recent deploy",
            updated_at=now - timedelta(days=1),
        ),
        preserve_timestamps=True,
    )

    provider = _provider(root)
    provider_result = provider.build(
        {
            "input": "service-a CPUHigh fixed last week but alert triggered again",
            "memory_mode": "active",
            "memory_owner_id": "default",
            "memory_store_path": str(root / "memory.sqlite3"),
        }
    )
    observation = provider_result.observation or {}
    trace = observation.get("retrieval_trace", {})
    stale_policy = trace.get("stale_policy", {})
    legacy_trace = trace.get("legacy_retrieval", {})
    memory_ids = observation.get("memory_ids", [])

    checks = [
        _check("legacy_guidance_present", bool(provider_result.guidance_text)),
        _check(
            "legacy_fallback_memory_order",
            memory_ids == ["mem_new_cpu_high", "mem_old_cpu_high"],
            memory_ids=memory_ids,
        ),
        _check("legacy_trace_has_no_l2_l1_hits", not trace.get("l2_retrieval", {}).get("matched_scenarios") and not trace.get("l1_retrieval", {}).get("matched_atoms")),
        _check("stale_policy_cue_detected", stale_policy.get("cue_detected") is True, matched_cues=stale_policy.get("matched_cues", [])),
        _check(
            "stale_policy_penalized_old_memory",
            stale_policy.get("penalized_memory_ids") == ["mem_old_cpu_high"],
            penalized_memory_ids=stale_policy.get("penalized_memory_ids", []),
        ),
        _check(
            "legacy_guidance_header_present",
            "基于历史记忆（待聚合）" in provider_result.guidance_text
            and "当前工具观测" in provider_result.guidance_text,
        ),
    ]
    trace_complete = all(key in trace for key in ("l2_retrieval", "l1_retrieval", "legacy_retrieval", "stale_policy"))
    return _case_result(
        "legacy_fallback_with_stale_policy",
        checks,
        trace_complete=trace_complete,
        latency_ms=(time.perf_counter() - start) * 1000,
        artifacts={
            "memory_ids": memory_ids,
            "legacy_matched_memories": legacy_trace.get("matched_memories", []),
            "stale_policy": stale_policy,
            "guidance_preview": provider_result.guidance_text[:1000],
        },
    )


def _summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    checks = [check for case in cases for check in case["checks"]]
    latencies = [case["latency_ms"] for case in cases if case["latency_ms"] is not None]
    first_case_artifacts = cases[0].get("artifacts", {}) if cases else {}
    conflict_artifacts = cases[1].get("artifacts", {}) if len(cases) > 1 else {}
    return {
        "cases_total": len(cases),
        "cases_passed": sum(1 for case in cases if case["passed"]),
        "checks_total": len(checks),
        "checks_passed": sum(1 for check in checks if check["passed"]),
        "trace_complete_cases": sum(1 for case in cases if case.get("trace_complete")),
        "l1_atoms_extracted": len(first_case_artifacts.get("l1_atom_ids", [])),
        "l2_scenarios_activated": 1 if first_case_artifacts.get("l2_scenario_id") else 0,
        "planner_guidance_injected": 1 if first_case_artifacts.get("planner_memory_ids") else 0,
        "lifecycle_transition_count": conflict_artifacts.get("lifecycle_metrics", {}).get("lifecycle_transition_count", 0),
        "latency_ms_avg": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
    }


def run_eval() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        cases = [
            _run_layered_planner_case(root / "layered_planner"),
            _run_conflict_lifecycle_case(root / "conflict_lifecycle"),
            _run_legacy_fallback_case(root / "legacy_fallback"),
        ]

    metrics = _summarize(cases)
    all_passed = metrics["cases_total"] == metrics["cases_passed"] and metrics["checks_total"] == metrics["checks_passed"]
    return {
        "eval_name": "p7_full_eval",
        "eval_status": "valid" if all_passed else "failed",
        "continue_rollout": bool(all_passed),
        "continue_rollout_scope": "local_p7_validation_only",
        "scope": {
            "deterministic": True,
            "uses_real_oncall_evidence": False,
            "external_llm_calls": False,
            "shadow_mode_real_oncall_validation": "not_in_scope",
            "gate_a1_real_oncall_evidence": "not_passed",
        },
        "metrics": metrics,
        "results": cases,
    }


def save_report(report: dict[str, Any]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(__file__).parent / f"p7_full_eval_{timestamp}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def main() -> int:
    report = run_eval()
    output_path = save_report(report)
    metrics = report["metrics"]
    print(f"p7_full_eval report: {output_path}")
    print(
        "metrics: "
        f"cases_passed={metrics['cases_passed']}/{metrics['cases_total']} "
        f"checks_passed={metrics['checks_passed']}/{metrics['checks_total']} "
        f"trace_complete_cases={metrics['trace_complete_cases']} "
        f"latency_ms_avg={metrics['latency_ms_avg']:.3f}"
    )
    return 0 if report["eval_status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
