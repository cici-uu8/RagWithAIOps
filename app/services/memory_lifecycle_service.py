"""Lifecycle transitions for layered oncall memory."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models.memory import MemoryRecord, MemoryReview, MemoryReviewDecision, MemoryStatus
from app.models.memory_atom import L1Atom
from app.models.memory_conflict import MemoryConflictVerdict
from app.services.conflict_detector_service import ConflictDetectorService
from app.services.memory_store import MemoryStore, memory_store


class LifecycleMetrics:
    """Counters for P7.3 lifecycle transitions."""

    def __init__(self) -> None:
        self.lifecycle_transition_count = 0
        self.lifecycle_transition_failure_count = 0
        self.stale_suspect_marked_count = 0
        self.review_reverted_stale_suspect_count = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "lifecycle_transition_count": self.lifecycle_transition_count,
            "lifecycle_transition_failure_count": self.lifecycle_transition_failure_count,
            "stale_suspect_marked_count": self.stale_suspect_marked_count,
            "review_reverted_stale_suspect_count": self.review_reverted_stale_suspect_count,
        }


class MemoryLifecycleService:
    """Manage automatic stale marking and review-driven lifecycle transitions."""

    def __init__(
        self,
        *,
        store: MemoryStore = memory_store,
        conflict_detector: ConflictDetectorService | None = None,
    ):
        self.store = store
        self.conflict_detector = conflict_detector or ConflictDetectorService(store=store)
        self.metrics = LifecycleMetrics()

    def apply_conflicts_for_atom(self, atom_or_record: L1Atom | MemoryRecord) -> list[MemoryRecord]:
        """Mark any active memories that conflict with a fresh atom as stale_suspect."""

        results = self.conflict_detector.detect_conflicts(atom_or_record)
        updated: list[MemoryRecord] = []
        for result in results:
            try:
                if result.verdict in {MemoryConflictVerdict.POSSIBLE_CONFLICT, MemoryConflictVerdict.SUPERSESSION_CANDIDATE}:
                    updated.append(
                        self.mark_stale_suspect(
                            result.memory_id,
                            conflicting_atom_id=result.atom_id,
                            evidence_id=result.evidence_id,
                            conflict_reason=result.reason,
                            conflict_verdict=result.verdict,
                        )
                    )
            except Exception:
                self.metrics.lifecycle_transition_failure_count += 1
                raise
        return updated

    def mark_stale_suspect(
        self,
        memory_id: str,
        *,
        conflicting_atom_id: str,
        evidence_id: str,
        conflict_reason: str,
        conflict_verdict: MemoryConflictVerdict,
    ) -> MemoryRecord:
        record = self._get_record(memory_id)
        if record.status != MemoryStatus.ACTIVE:
            raise ValueError("only active memory can be marked as stale_suspect")

        transition_event = self._transition_event(
            transition="active->stale_suspect",
            trigger="conflict_detector",
            conflicting_atom_id=conflicting_atom_id,
            evidence_id=evidence_id,
            conflict_reason=conflict_reason,
            conflict_verdict=conflict_verdict.value,
        )
        evidence = self._merge_evidence(
            record.evidence,
            {
                "conflict_reason": conflict_reason,
                "conflicting_atom_id": conflicting_atom_id,
                "evidence_id": evidence_id,
                "conflict_verdict": conflict_verdict.value,
                "review_required": True,
            },
            transition_event,
        )
        updated = self.store.upsert(
            record.model_copy(
                update={
                    "status": MemoryStatus.STALE_SUSPECT,
                    "evidence": evidence,
                }
            )
        )
        self.metrics.lifecycle_transition_count += 1
        self.metrics.stale_suspect_marked_count += 1
        return updated

    def restore_active(
        self,
        memory_id: str,
        *,
        reviewer_id: str,
        decision_note: str,
        decision_source: str = "operator-workflow",
    ) -> MemoryRecord:
        record = self._get_record(memory_id)
        if record.status != MemoryStatus.STALE_SUSPECT:
            raise ValueError("only stale_suspect memory can be restored to active")

        review = self._build_review(
            decision=MemoryReviewDecision.APPROVED,
            reviewer_id=reviewer_id,
            decision_note=decision_note,
            previous_status=record.status,
            decision_source=decision_source,
        )
        transition_event = self._transition_event(
            transition="stale_suspect->active",
            trigger="operator-review",
            reviewer_id=reviewer_id,
            decision_note=decision_note,
            decision_source=decision_source,
        )
        evidence = self._merge_evidence(
            record.evidence,
            {"review_reverted": True, "review_reverted_from": "stale_suspect"},
            transition_event,
        )
        updated = self.store.upsert(
            record.model_copy(
                update={
                    "status": MemoryStatus.ACTIVE,
                    "review": review,
                    "evidence": evidence,
                }
            )
        )
        self.metrics.lifecycle_transition_count += 1
        self.metrics.review_reverted_stale_suspect_count += 1
        return updated

    def restore_stale_suspect(
        self,
        memory_id: str,
        *,
        reviewer_id: str,
        decision_note: str,
        decision_source: str = "operator-workflow",
    ) -> MemoryRecord:
        return self.restore_active(
            memory_id,
            reviewer_id=reviewer_id,
            decision_note=decision_note,
            decision_source=decision_source,
        )

    def mark_superseded(
        self,
        memory_id: str,
        *,
        superseded_by: str,
        reviewer_id: str,
        decision_note: str,
        decision_source: str = "operator-workflow",
    ) -> MemoryRecord:
        record = self._get_record(memory_id)
        if record.status not in {MemoryStatus.ACTIVE, MemoryStatus.STALE_SUSPECT}:
            raise ValueError("only active or stale_suspect memory can be superseded")
        superseded_by = self._require_text(superseded_by, "superseded_by")

        review = self._build_review(
            decision=MemoryReviewDecision.SUPERSEDED,
            reviewer_id=reviewer_id,
            decision_note=decision_note,
            previous_status=record.status,
            decision_source=decision_source,
        )
        transition_event = self._transition_event(
            transition=f"{record.status.value}->superseded",
            trigger="operator-review",
            reviewer_id=reviewer_id,
            decision_note=decision_note,
            decision_source=decision_source,
            superseded_by=superseded_by,
        )
        evidence = self._merge_evidence(
            record.evidence,
            {"superseded_by": superseded_by, "review_superseded": True},
            transition_event,
        )
        updated = self.store.upsert(
            record.model_copy(
                update={
                    "status": MemoryStatus.SUPERSEDED,
                    "review": review,
                    "evidence": evidence,
                }
            )
        )
        self.metrics.lifecycle_transition_count += 1
        return updated

    def supersede_memory(
        self,
        memory_id: str,
        *,
        superseded_by: str,
        reviewer_id: str,
        decision_note: str,
        decision_source: str = "operator-workflow",
    ) -> MemoryRecord:
        return self.mark_superseded(
            memory_id,
            superseded_by=superseded_by,
            reviewer_id=reviewer_id,
            decision_note=decision_note,
            decision_source=decision_source,
        )

    def get_metrics(self) -> dict[str, int]:
        return self.metrics.snapshot()

    def _get_record(self, memory_id: str) -> MemoryRecord:
        record = self.store.get(memory_id)
        if record is None:
            raise ValueError(f"memory record not found: {memory_id}")
        return record

    def _build_review(
        self,
        *,
        decision: MemoryReviewDecision,
        reviewer_id: str,
        decision_note: str,
        previous_status: MemoryStatus,
        decision_source: str,
    ) -> MemoryReview:
        return MemoryReview(
            decision=decision,
            reviewer_id=self._require_text(reviewer_id, "reviewer_id"),
            decision_note=self._require_text(decision_note, "decision_note"),
            previous_status=previous_status,
            decision_source=self._require_text(decision_source, "decision_source"),
            reviewed_at=datetime.now(),
        )

    def _transition_event(self, *, transition: str, trigger: str, **details: Any) -> dict[str, Any]:
        return {
            "transition": transition,
            "trigger": trigger,
            "recorded_at": datetime.now().isoformat(),
            **{key: value for key, value in details.items() if value is not None},
        }

    def _merge_evidence(
        self,
        evidence: dict[str, Any],
        updates: dict[str, Any],
        transition_event: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(evidence)
        for key, value in updates.items():
            merged[key] = value
        lifecycle_events = list(merged.get("lifecycle_events", []))
        lifecycle_events.append(transition_event)
        merged["lifecycle_events"] = lifecycle_events
        return merged

    @staticmethod
    def _require_text(value: str, field_name: str) -> str:
        if value is None or not str(value).strip():
            raise ValueError(f"{field_name} is required")
        return str(value).strip()


memory_lifecycle_service = MemoryLifecycleService()
