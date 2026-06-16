"""Sidecar lexical retrieval for durable oncall memory records."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.memory import MemoryRecord, MemoryStatus, MemoryType
from app.services.memory_scorer import LexicalMemoryScorer, MemoryScorer
from app.services.memory_store import MemoryStore, memory_store


class MemoryRetrievalQuery(BaseModel):
    """Query shape for sidecar memory retrieval."""

    query: str = Field(..., description="Natural-language memory lookup query")
    owner_id: str = Field("default", description="Tenant/user/team memory owner")
    namespaces: List[str] = Field(default_factory=list, description="Optional namespace filters")
    memory_types: List[MemoryType] = Field(default_factory=list, description="Optional memory type filters")
    top_k: int = Field(3, description="Maximum number of memory records to return")

    @field_validator("query", "owner_id")
    @classmethod
    def _require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value is required")
        return value

    @model_validator(mode="after")
    def _validate_limits(self) -> "MemoryRetrievalQuery":
        if self.top_k <= 0:
            raise ValueError("top_k must be positive")
        return self


class MemoryRetrievalResult(BaseModel):
    """Independent memory hit result, intentionally not a RAG citation DTO."""

    memory_id: str
    owner_id: str
    namespace: str
    memory_type: MemoryType
    status: MemoryStatus
    content: str
    summary: str
    score: float
    matched_terms: List[str] = Field(default_factory=list)
    evidence_refs: List[Dict[str, Any]] = Field(default_factory=list)
    payload: Dict[str, Any] = Field(default_factory=dict)
    source: str
    tags: List[str] = Field(default_factory=list)
    updated_at: datetime


class MemoryRetrievalResponse(BaseModel):
    """Sidecar memory retrieval response."""

    query: str
    owner_id: str
    namespaces: List[str] = Field(default_factory=list)
    memory_types: List[MemoryType] = Field(default_factory=list)
    memory_results: List[MemoryRetrievalResult] = Field(default_factory=list)
    empty_message: str
    trace: Dict[str, Any] = Field(default_factory=dict)


class MemoryRetrievalService:
    """Retrieve active durable memory without touching document RAG retrieval."""

    EMPTY_MESSAGE = "No active memory matched the query."
    STALE_CUES = [
        "fixed last week",
        "fixed yesterday",
        "already fixed",
        "resolved last week",
        "resolved yesterday",
        "recent deploy changed architecture",
        "recent deploy",
        "deploy changed architecture",
        "config updated",
        "configuration updated",
        "config was updated",
        "configuration was updated",
        "updated last week",
        "changed recently",
        "recent change",
        "database index was added yesterday",
        "index was added yesterday",
        "connection pool config was updated",
        "no longer the issue",
        "not the same issue",
        "上周已修复",
        "昨天已修复",
        "已经修复",
        "已解决",
        "前几天解决了",
        "配置已更新",
        "已经改过配置",
        "最近部署已变更",
        "数据库索引已添加",
        "最近变更",
        "最近改动",
        "不再是这个问题",
        "已经不是这个问题",
        "当前已经修复",
        "目前已经修复",
    ]
    NEGATIVE_STALE_CUES = [
        "fixed parameter",
        "fixed value",
        "fixed interval",
        "fixed threshold",
        "固定参数",
        "固定值",
        "固定阈值",
        "固定间隔",
        "最近有没有类似案例",
        "最近类似案例",
        "最近的历史案例",
        "recent similar incident",
        "recent similar case",
        "recent history",
    ]

    def __init__(
        self,
        store: MemoryStore = memory_store,
        scorer: MemoryScorer | None = None,
        stale_age_days: int = 7,
        stale_penalty: float = 0.5,
    ):
        if stale_age_days <= 0:
            raise ValueError("stale_age_days must be positive")
        if stale_penalty <= 0 or stale_penalty > 1:
            raise ValueError("stale_penalty must be in (0, 1]")
        self.store = store
        self.scorer = scorer or LexicalMemoryScorer()
        self.stale_age_days = stale_age_days
        self.stale_penalty = stale_penalty

    def retrieve(self, query: MemoryRetrievalQuery) -> MemoryRetrievalResponse:
        start_time = time.time()
        success = False

        try:
            candidates = self._filter_active_candidates(query)
            stale_policy_trace = self._build_stale_policy_trace(query.query)
            lifecycle_filter_trace = self._build_lifecycle_filter_trace(query)
            scored_results = []
            for record in candidates:
                score, matched_terms = self.scorer.score(record, query.query)
                if score > 0:
                    final_score = self._apply_stale_penalty(record, score, stale_policy_trace)
                    scored_results.append(self._build_result(record, final_score, matched_terms))
            scored_results.sort(
                key=lambda result: (
                    -result.score,
                    self._sort_datetime_key(result.updated_at),
                    result.memory_id,
                )
            )

            memory_results = scored_results[: query.top_k]
            for result in memory_results:
                self.store.record_access(result.memory_id)

            success = True
            return MemoryRetrievalResponse(
                query=query.query,
                owner_id=query.owner_id,
                namespaces=list(query.namespaces),
                memory_types=list(query.memory_types),
                memory_results=memory_results,
                empty_message=self.EMPTY_MESSAGE,
                trace={
                    "candidate_count": len(candidates),
                    "matched_count": len(scored_results),
                    "returned_count": len(memory_results),
                    "retrieval_mode": getattr(
                        self.scorer,
                        "retrieval_mode",
                        self.scorer.__class__.__name__,
                    ),
                    "stale_policy": stale_policy_trace,
                    "lifecycle_filter": lifecycle_filter_trace,
                },
            )
        finally:
            # 记录指标
            from app.services.shadow_mode_metrics import shadow_metrics
            latency_ms = (time.time() - start_time) * 1000
            shadow_metrics.record_memory_recall(success=success, latency_ms=latency_ms)

    def _filter_active_candidates(self, query: MemoryRetrievalQuery) -> List[MemoryRecord]:
        records = self.store.list_memories(owner_id=query.owner_id, status=MemoryStatus.ACTIVE)
        return self._apply_query_filters(records, query)

    def _filter_lifecycle_skipped_records(self, query: MemoryRetrievalQuery) -> List[MemoryRecord]:
        records: list[MemoryRecord] = []
        for status in (MemoryStatus.STALE_SUSPECT, MemoryStatus.SUPERSEDED):
            records.extend(self.store.list_memories(owner_id=query.owner_id, status=status))
        return self._apply_query_filters(records, query)

    def _apply_query_filters(
        self,
        records: List[MemoryRecord],
        query: MemoryRetrievalQuery,
    ) -> List[MemoryRecord]:
        namespace_filter = set(query.namespaces)
        type_filter = set(query.memory_types)
        return [
            record
            for record in records
            if (not namespace_filter or record.namespace in namespace_filter)
            and (not type_filter or record.memory_type in type_filter)
        ]

    def _build_lifecycle_filter_trace(self, query: MemoryRetrievalQuery) -> Dict[str, Any]:
        skipped_records = []
        for record in self._filter_lifecycle_skipped_records(query):
            score, matched_terms = self.scorer.score(record, query.query)
            if score <= 0:
                continue
            skipped_records.append(
                {
                    "memory_id": record.memory_id,
                    "status": record.status.value,
                    "score": score,
                    "matched_terms": matched_terms,
                    "reason": f"status={record.status.value} is not active; default retrieval only injects active memory",
                }
            )
        return {
            "active_only": True,
            "skipped_statuses": [MemoryStatus.STALE_SUSPECT.value, MemoryStatus.SUPERSEDED.value],
            "skipped_count": len(skipped_records),
            "skipped_memory": skipped_records,
        }

    def _build_result(
        self,
        record: MemoryRecord,
        score: float,
        matched_terms: List[str],
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
        payload: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        refs = payload.get("evidence_refs")
        if isinstance(refs, list):
            return [ref for ref in refs if isinstance(ref, dict)]
        source_event = payload.get("source_event")
        if isinstance(source_event, dict):
            return [source_event]
        return [record.evidence]

    def _build_stale_policy_trace(self, query_text: str) -> Dict[str, Any]:
        normalized = query_text.lower()
        matched_cues = [cue for cue in self.STALE_CUES if cue.lower() in normalized]
        negative_cues = [cue for cue in self.NEGATIVE_STALE_CUES if cue.lower() in normalized]
        return {
            "cue_detected": bool(matched_cues) and not negative_cues,
            "matched_cues": matched_cues,
            "negative_cues": negative_cues,
            "stale_age_days": self.stale_age_days,
            "stale_penalty": self.stale_penalty,
            "penalized_memory_ids": [],
            "score_adjustments": [],
        }

    def _apply_stale_penalty(
        self,
        record: MemoryRecord,
        base_score: float,
        stale_policy_trace: Dict[str, Any],
    ) -> float:
        age_days = self._record_age_days(record)
        should_penalize = (
            stale_policy_trace["cue_detected"]
            and age_days > self.stale_age_days
        )
        if not should_penalize:
            return base_score

        final_score = base_score * self.stale_penalty
        stale_policy_trace["penalized_memory_ids"].append(record.memory_id)
        stale_policy_trace["score_adjustments"].append(
            {
                "memory_id": record.memory_id,
                "base_score": base_score,
                "final_score": final_score,
                "age_days": age_days,
                "reason": "stale cue detected and memory age exceeded stale_age_days",
            }
        )
        return final_score

    @staticmethod
    def _record_age_days(record: MemoryRecord) -> int:
        updated_at = record.updated_at
        now = datetime.now(updated_at.tzinfo) if updated_at.tzinfo else datetime.now()
        return max((now - updated_at).days, 0)

    @staticmethod
    def _sort_datetime_key(value: datetime) -> datetime:
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value


memory_retrieval_service = MemoryRetrievalService()
