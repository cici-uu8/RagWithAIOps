"""P7.5 hierarchical retrieval for layered oncall memory."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.models.memory import L1Atom, L2ScenarioPayload, MemoryRecord, MemoryStatus, MemoryType
from app.services.memory_retrieval_service import (
    MemoryRetrievalQuery,
    MemoryRetrievalResponse,
    MemoryRetrievalResult,
    MemoryRetrievalService,
)
from app.services.memory_scorer import LexicalMemoryScorer, MemoryScorer
from app.services.memory_store import MemoryStore, memory_store


class HierarchicalRetrievalResult(BaseModel):
    """Planner-facing layered memory retrieval result."""

    query: str
    owner_id: str = "default"
    l2_scenarios: list[MemoryRetrievalResult] = Field(default_factory=list)
    l1_atoms: list[MemoryRetrievalResult] = Field(default_factory=list)
    legacy_memories: list[MemoryRetrievalResult] = Field(default_factory=list)
    empty_message: str = "No hierarchical memory matched the query."
    trace: dict[str, Any] = Field(default_factory=dict)

    @property
    def memory_results(self) -> list[MemoryRetrievalResult]:
        """Compatibility surface for existing trace/guidance plumbing."""

        return [*self.l2_scenarios, *self.l1_atoms, *self.legacy_memories]


class HierarchicalRetrievalMetrics:
    """Counters for P7.5 hierarchical retrieval."""

    def __init__(self) -> None:
        self.hierarchical_retrieval_l2_hit_count = 0
        self.hierarchical_retrieval_l1_fallback_count = 0
        self.hierarchical_retrieval_legacy_fallback_count = 0
        self._l2_confidence_sum = 0.0
        self.hierarchical_retrieval_latency_ms = 0.0

    def record(
        self,
        *,
        l2_hits: int,
        l2_confidences: list[float],
        fallback_to_l1: bool,
        fallback_to_legacy: bool,
        latency_ms: float,
    ) -> None:
        self.hierarchical_retrieval_l2_hit_count += l2_hits
        self._l2_confidence_sum += sum(l2_confidences)
        if fallback_to_l1:
            self.hierarchical_retrieval_l1_fallback_count += 1
        if fallback_to_legacy:
            self.hierarchical_retrieval_legacy_fallback_count += 1
        self.hierarchical_retrieval_latency_ms = latency_ms

    def snapshot(self) -> dict[str, float | int]:
        if self.hierarchical_retrieval_l2_hit_count:
            avg_confidence = self._l2_confidence_sum / self.hierarchical_retrieval_l2_hit_count
        else:
            avg_confidence = 0.0
        return {
            "hierarchical_retrieval_l2_hit_count": self.hierarchical_retrieval_l2_hit_count,
            "hierarchical_retrieval_l1_fallback_count": self.hierarchical_retrieval_l1_fallback_count,
            "hierarchical_retrieval_legacy_fallback_count": self.hierarchical_retrieval_legacy_fallback_count,
            "hierarchical_retrieval_l2_avg_confidence": avg_confidence,
            "hierarchical_retrieval_latency_ms": self.hierarchical_retrieval_latency_ms,
        }


class HierarchicalRetrievalService:
    """Retrieve memory through L2 scenario -> L1 atom -> legacy memory fallback."""

    L2_NAMESPACE = "memory://oncall/l2-scenarios"
    L1_NAMESPACE = "memory://oncall/l1-atoms"
    LEGACY_NAMESPACES = [
        "memory://oncall/alert-patterns",
        "memory://oncall/plan-templates",
    ]
    LEGACY_MEMORY_TYPES = [MemoryType.ALERT_PATTERN, MemoryType.PLAN_TEMPLATE]

    def __init__(
        self,
        *,
        store: MemoryStore = memory_store,
        scorer: MemoryScorer | None = None,
        legacy_retrieval_service: MemoryRetrievalService | None = None,
        min_l2_hits: int = 1,
        min_l1_hits: int = 1,
        l2_min_confidence: float = 0.7,
    ):
        if min_l2_hits <= 0:
            raise ValueError("min_l2_hits must be positive")
        if min_l1_hits <= 0:
            raise ValueError("min_l1_hits must be positive")
        if l2_min_confidence < 0 or l2_min_confidence > 1:
            raise ValueError("l2_min_confidence must be in [0, 1]")
        self.store = store
        self.scorer = scorer or LexicalMemoryScorer()
        self.legacy_retrieval_service = legacy_retrieval_service or MemoryRetrievalService(
            store=store,
            scorer=self.scorer,
        )
        self.min_l2_hits = min_l2_hits
        self.min_l1_hits = min_l1_hits
        self.l2_min_confidence = l2_min_confidence
        self.metrics = HierarchicalRetrievalMetrics()

    def retrieve_hierarchical(
        self,
        query: str,
        *,
        owner_id: str = "default",
        top_k_l2: int = 2,
        top_k_l1: int = 3,
        top_k_legacy: int = 5,
    ) -> HierarchicalRetrievalResult:
        """Retrieve active layered memory with deterministic lexical fallback."""

        if not str(query).strip():
            raise ValueError("query is required")
        for name, value in (
            ("top_k_l2", top_k_l2),
            ("top_k_l1", top_k_l1),
            ("top_k_legacy", top_k_legacy),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")

        start = time.perf_counter()
        l2_results = self._retrieve_layer(
            query=query,
            owner_id=owner_id,
            memory_type=MemoryType.L2_SCENARIO,
            namespace=self.L2_NAMESPACE,
            top_k=top_k_l2,
        )
        l2_confidences = [self._result_confidence(result) for result in l2_results]
        fallback_to_l1, l2_fallback_reason = self._l2_fallback_decision(l2_results)
        covered_l1_atom_ids = self._covered_l1_atom_ids(l2_results)

        l1_results: list[MemoryRetrievalResult] = []
        l1_trace_items: list[dict[str, Any]] = []
        fallback_to_legacy = False
        l1_fallback_reason = None
        if fallback_to_l1:
            scored_l1 = self._retrieve_layer(
                query=query,
                owner_id=owner_id,
                memory_type=MemoryType.L1_ATOM,
                namespace=self.L1_NAMESPACE,
                top_k=top_k_l1 + len(covered_l1_atom_ids),
            )
            for result in scored_l1:
                excluded_by_l2 = result.memory_id in covered_l1_atom_ids
                l1_trace_items.append(self._l1_trace_item(result, excluded_by_l2=excluded_by_l2))
                if not excluded_by_l2 and len(l1_results) < top_k_l1:
                    l1_results.append(result)

            if len(l1_results) < self.min_l1_hits:
                fallback_to_legacy = True
                l1_fallback_reason = "insufficient_l1_hits"

        legacy_response: MemoryRetrievalResponse | None = None
        legacy_memories: list[MemoryRetrievalResult] = []
        if fallback_to_legacy:
            legacy_response = self.legacy_retrieval_service.retrieve(
                MemoryRetrievalQuery(
                    query=query,
                    owner_id=owner_id,
                    namespaces=self.LEGACY_NAMESPACES,
                    memory_types=self.LEGACY_MEMORY_TYPES,
                    top_k=top_k_legacy,
                )
            )
            legacy_memories = legacy_response.memory_results

        latency_ms = (time.perf_counter() - start) * 1000
        stale_policy = self._stale_policy_trace(query, legacy_response)
        trace = {
            "retrieval_mode": "hierarchical_lexical_v1",
            "l2_retrieval": {
                "candidate_count": len(
                    self._active_records(owner_id=owner_id, memory_type=MemoryType.L2_SCENARIO)
                ),
                "matched_scenarios": [self._l2_trace_item(result) for result in l2_results],
                "fallback_to_l1": fallback_to_l1,
                "fallback_reason": l2_fallback_reason,
            },
            "l1_retrieval": {
                "candidate_count": len(
                    self._active_records(owner_id=owner_id, memory_type=MemoryType.L1_ATOM)
                ),
                "matched_atoms": l1_trace_items,
                "fallback_to_legacy": fallback_to_legacy,
                "fallback_reason": l1_fallback_reason,
            },
            "legacy_retrieval": self._legacy_trace(legacy_response),
            "stale_policy": stale_policy,
            "retrieval_latency_ms": round(latency_ms, 3),
        }

        self.metrics.record(
            l2_hits=len(l2_results),
            l2_confidences=l2_confidences,
            fallback_to_l1=fallback_to_l1,
            fallback_to_legacy=fallback_to_legacy,
            latency_ms=round(latency_ms, 3),
        )
        trace["metrics"] = self.get_metrics()

        return HierarchicalRetrievalResult(
            query=query,
            owner_id=owner_id,
            l2_scenarios=l2_results,
            l1_atoms=l1_results,
            legacy_memories=legacy_memories,
            trace=trace,
        )

    def get_metrics(self) -> dict[str, float | int]:
        return self.metrics.snapshot()

    def _retrieve_layer(
        self,
        *,
        query: str,
        owner_id: str,
        memory_type: MemoryType,
        namespace: str,
        top_k: int,
    ) -> list[MemoryRetrievalResult]:
        scored_results: list[MemoryRetrievalResult] = []
        for record in self._active_records(owner_id=owner_id, memory_type=memory_type, namespace=namespace):
            score, matched_terms = self.scorer.score(record, query)
            if score <= 0:
                continue
            scored_results.append(self._build_result(record, score, matched_terms))

        scored_results.sort(
            key=lambda result: (
                -result.score,
                -self._result_confidence(result),
                -self._datetime_timestamp(result.updated_at),
                result.memory_id,
            )
        )
        return scored_results[:top_k]

    def _active_records(
        self,
        *,
        owner_id: str,
        memory_type: MemoryType,
        namespace: str | None = None,
    ) -> list[MemoryRecord]:
        records = self.store.list_memories(
            owner_id=owner_id,
            memory_type=memory_type,
            status=MemoryStatus.ACTIVE,
        )
        if namespace is None:
            return records
        return [record for record in records if record.namespace == namespace]

    def _l2_fallback_decision(self, l2_results: list[MemoryRetrievalResult]) -> tuple[bool, str | None]:
        if len(l2_results) < self.min_l2_hits:
            return True, "insufficient_l2_hits"
        max_confidence = max((self._result_confidence(result) for result in l2_results), default=0.0)
        if max_confidence < self.l2_min_confidence:
            return True, "low_confidence"
        return False, None

    def _build_result(
        self,
        record: MemoryRecord,
        score: float,
        matched_terms: list[str],
    ) -> MemoryRetrievalResult:
        payload = record.payload.model_dump(mode="json")
        return MemoryRetrievalResult(
            memory_id=record.memory_id,
            owner_id=record.owner_id,
            namespace=record.namespace,
            memory_type=record.memory_type,
            status=record.status,
            content=record.content,
            summary=record.summary,
            score=score,
            matched_terms=matched_terms,
            evidence_refs=self._extract_evidence_refs(record, payload),
            payload=payload,
            source=record.source,
            tags=list(record.tags),
            updated_at=record.updated_at,
        )

    def _extract_evidence_refs(
        self,
        record: MemoryRecord,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        refs = payload.get("evidence_refs")
        extracted: list[dict[str, Any]] = []
        if isinstance(refs, list):
            for ref in refs:
                if isinstance(ref, dict):
                    extracted.append(ref)
                elif isinstance(ref, str) and ref.strip():
                    extracted.append(
                        {
                            "evidence_type": "l0_evidence_ref",
                            "evidence_id": ref.strip(),
                        }
                    )
        if extracted:
            return extracted
        return [record.evidence]

    def _covered_l1_atom_ids(self, l2_results: list[MemoryRetrievalResult]) -> set[str]:
        atom_ids: set[str] = set()
        for result in l2_results:
            payload_atom_ids = result.payload.get("l1_atom_ids", [])
            if isinstance(payload_atom_ids, list):
                atom_ids.update(str(atom_id) for atom_id in payload_atom_ids if str(atom_id).strip())
        return atom_ids

    def _l2_trace_item(self, result: MemoryRetrievalResult) -> dict[str, Any]:
        return {
            "scenario_id": result.memory_id,
            "memory_id": result.memory_id,
            "scenario_key": result.payload.get("scenario_key"),
            "score": result.score,
            "matched_terms": list(result.matched_terms),
            "confidence": self._result_confidence(result),
            "l1_atom_ids": list(result.payload.get("l1_atom_ids", [])),
            "evidence_refs": list(result.evidence_refs),
        }

    def _l1_trace_item(self, result: MemoryRetrievalResult, *, excluded_by_l2: bool) -> dict[str, Any]:
        return {
            "atom_id": result.memory_id,
            "memory_id": result.memory_id,
            "score": result.score,
            "matched_terms": list(result.matched_terms),
            "excluded_by_l2": excluded_by_l2,
            "evidence_refs": list(result.evidence_refs),
        }

    def _legacy_trace(self, legacy_response: MemoryRetrievalResponse | None) -> dict[str, Any]:
        if legacy_response is None:
            return {
                "matched_memories": [],
                "stale_policy": {},
                "raw_trace": {},
            }
        return {
            "matched_memories": [
                {
                    "memory_id": result.memory_id,
                    "score": result.score,
                    "matched_terms": list(result.matched_terms),
                }
                for result in legacy_response.memory_results
            ],
            "stale_policy": legacy_response.trace.get("stale_policy", {}),
            "raw_trace": legacy_response.trace,
        }

    def _stale_policy_trace(
        self,
        query: str,
        legacy_response: MemoryRetrievalResponse | None,
    ) -> dict[str, Any]:
        if legacy_response is not None:
            return legacy_response.trace.get("stale_policy", {})
        return {
            "cue_detected": False,
            "matched_cues": [],
            "negative_cues": [],
            "stale_age_days": getattr(self.legacy_retrieval_service, "stale_age_days", None),
            "stale_penalty": getattr(self.legacy_retrieval_service, "stale_penalty", None),
            "penalized_memory_ids": [],
            "score_adjustments": [],
            "note": "legacy retrieval was not executed",
            "query": query,
        }

    def _result_confidence(self, result: MemoryRetrievalResult) -> float:
        payload_confidence = result.payload.get("confidence")
        evidence_confidence = None
        for ref in result.evidence_refs:
            if isinstance(ref, dict) and "confidence" in ref:
                evidence_confidence = ref["confidence"]
                break
        evidence_confidence = evidence_confidence or self._record_evidence_confidence(result)
        for value in (payload_confidence, evidence_confidence):
            try:
                if value is not None:
                    return max(0.0, min(float(value), 1.0))
            except (TypeError, ValueError):
                continue
        if result.memory_type == MemoryType.L2_SCENARIO:
            return 1.0
        return 0.0

    def _record_evidence_confidence(self, result: MemoryRetrievalResult) -> Any:
        record = self.store.get(result.memory_id)
        if record is None or not isinstance(record.evidence, dict):
            return None
        return record.evidence.get("confidence")

    @staticmethod
    def _datetime_timestamp(value: datetime) -> float:
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).timestamp()
        return value.replace(tzinfo=timezone.utc).timestamp()


hierarchical_retrieval_service = HierarchicalRetrievalService()
