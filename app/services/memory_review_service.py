"""Operator review workflow for durable oncall memory candidates."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from app.models.memory import (
    MemoryRecord,
    MemoryReview,
    MemoryReviewDecision,
    MemoryStatus,
    MemoryType,
)
from app.services.memory_lifecycle_service import MemoryLifecycleService
from app.services.memory_store import MemoryStore, memory_store


class MemoryReviewService:
    """Promote or reject memory candidates only after explicit operator review."""

    def __init__(self, *, store: MemoryStore = memory_store):
        self.store = store
        self.lifecycle_service = MemoryLifecycleService(store=store)

    def list_review_queue(
        self,
        *,
        owner_id: str = "default",
        statuses: Iterable[MemoryStatus] = (MemoryStatus.CANDIDATE, MemoryStatus.CONFLICT),
    ) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        for status in statuses:
            records.extend(self.store.list_memories(owner_id=owner_id, status=status))
        return sorted(records, key=lambda record: (record.updated_at, record.memory_id))

    def build_owner_deprecation_plan(self, *, owner_id: str = "default") -> dict:
        """Preview owner-scoped rollback without mutating or deleting records."""
        records = self._owner_deprecation_records(owner_id=owner_id)
        return {
            "owner_id": owner_id,
            "rollback_action": "mark_memory_records_deprecated",
            "destructive_delete": False,
            "records_to_deprecate": len(records),
            "records": [self._deprecation_plan_item(record) for record in records],
            "p5_prompt_integration": "blocked_default_off",
        }

    def deprecate_owner_memories(
        self,
        *,
        owner_id: str = "default",
        reviewer_id: str,
        decision_note: str,
        decision_source: str = "operator-workflow",
    ) -> list[MemoryRecord]:
        """Mark all non-deprecated owner records as deprecated after explicit review."""
        updated_records: list[MemoryRecord] = []
        for record in self._owner_deprecation_records(owner_id=owner_id):
            review = self._build_review(
                decision=MemoryReviewDecision.DEPRECATED,
                reviewer_id=reviewer_id,
                decision_note=decision_note,
                previous_status=record.status,
                decision_source=decision_source,
            )
            updated_records.append(
                self.store.upsert(
                    record.model_copy(
                        update={
                            "status": MemoryStatus.DEPRECATED,
                            "review": review,
                            "candidate_review_deadline": None,
                        }
                    )
                )
            )
        return updated_records

    def approve_candidate(
        self,
        memory_id: str,
        *,
        reviewer_id: str,
        decision_note: str,
        decision_source: str = "operator-workflow",
    ) -> MemoryRecord:
        record = self._get_reviewable(memory_id)
        if record.status != MemoryStatus.CANDIDATE:
            raise ValueError("only candidate memory can be approved; resolve conflicts manually first")
        if record.memory_type == MemoryType.CANDIDATE_SUMMARY:
            raise ValueError("candidate_summary cannot be promoted to active memory")

        review = self._build_review(
            decision=MemoryReviewDecision.APPROVED,
            reviewer_id=reviewer_id,
            decision_note=decision_note,
            previous_status=record.status,
            decision_source=decision_source,
        )
        return self.store.upsert(
            record.model_copy(
                update={
                    "status": MemoryStatus.ACTIVE,
                    "review": review,
                    "candidate_review_deadline": None,
                }
            )
        )

    def reject_candidate(
        self,
        memory_id: str,
        *,
        reviewer_id: str,
        decision_note: str,
        decision_source: str = "operator-workflow",
    ) -> MemoryRecord:
        record = self._get_reviewable(memory_id)
        review = self._build_review(
            decision=MemoryReviewDecision.REJECTED,
            reviewer_id=reviewer_id,
            decision_note=decision_note,
            previous_status=record.status,
            decision_source=decision_source,
        )
        return self.store.upsert(
            record.model_copy(
                update={
                    "status": MemoryStatus.DEPRECATED,
                    "review": review,
                    "candidate_review_deadline": None,
                }
            )
        )

    def restore_stale_suspect(
        self,
        memory_id: str,
        *,
        reviewer_id: str,
        decision_note: str,
        decision_source: str = "operator-workflow",
    ) -> MemoryRecord:
        record = self._get_by_status(memory_id, {MemoryStatus.STALE_SUSPECT})
        return self.lifecycle_service.restore_stale_suspect(
            record.memory_id,
            reviewer_id=reviewer_id,
            decision_note=decision_note,
            decision_source=decision_source,
        )

    def supersede_memory(
        self,
        memory_id: str,
        *,
        superseded_by: str,
        reviewer_id: str,
        decision_note: str,
        decision_source: str = "operator-workflow",
    ) -> MemoryRecord:
        record = self._get_by_status(memory_id, {MemoryStatus.ACTIVE, MemoryStatus.STALE_SUSPECT})
        return self.lifecycle_service.supersede_memory(
            record.memory_id,
            superseded_by=superseded_by,
            reviewer_id=reviewer_id,
            decision_note=decision_note,
            decision_source=decision_source,
        )

    def _get_reviewable(self, memory_id: str) -> MemoryRecord:
        record = self.store.get(memory_id)
        if record is None:
            raise ValueError(f"memory record not found: {memory_id}")
        if record.status not in {MemoryStatus.CANDIDATE, MemoryStatus.CONFLICT}:
            raise ValueError(f"memory record is not reviewable: {record.status.value}")
        return record

    def _get_by_status(self, memory_id: str, statuses: set[MemoryStatus]) -> MemoryRecord:
        record = self.store.get(memory_id)
        if record is None:
            raise ValueError(f"memory record not found: {memory_id}")
        if record.status not in statuses:
            allowed = ", ".join(status.value for status in sorted(statuses, key=lambda item: item.value))
            raise ValueError(f"memory record status must be one of: {allowed}")
        return record

    def _owner_deprecation_records(self, *, owner_id: str) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        for status in (
            MemoryStatus.ACTIVE,
            MemoryStatus.CANDIDATE,
            MemoryStatus.CONFLICT,
            MemoryStatus.STALE_SUSPECT,
            MemoryStatus.SUPERSEDED,
        ):
            records.extend(self.store.list_memories(owner_id=owner_id, status=status))
        return sorted(records, key=lambda record: (record.updated_at, record.memory_id))

    def _deprecation_plan_item(self, record: MemoryRecord) -> dict:
        return {
            "memory_id": record.memory_id,
            "owner_id": record.owner_id,
            "namespace": record.namespace,
            "memory_type": record.memory_type.value,
            "status": record.status.value,
            "summary": record.summary,
            "updated_at": record.updated_at.isoformat(),
        }

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
            reviewer_id=reviewer_id.strip(),
            decision_note=decision_note.strip(),
            previous_status=previous_status,
            decision_source=decision_source.strip(),
            reviewed_at=datetime.now(),
        )


memory_review_service = MemoryReviewService()
