"""Adapter for the memory operator control plane."""

from __future__ import annotations

from app.enterprise.context import RequestContext
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.observability.models import AuditEvent
from app.models.memory import MemoryRecord
from app.services.memory_review_service import MemoryReviewService, memory_review_service
from app.services.memory_store import MemoryStore, memory_store


class MemoryOperatorAdapter:
    def __init__(
        self,
        *,
        review_service: MemoryReviewService | None = None,
        store: MemoryStore | None = None,
        audit_service: AuditService | None = None,
    ):
        self.review_service = review_service or memory_review_service
        self.store = store or memory_store
        self.audit_service = audit_service or AuditService()

    def list_review_queue(self, context: RequestContext, *, owner_id: str = "default", limit: int = 20) -> dict:
        records = self.review_service.list_review_queue(owner_id=owner_id)
        return {
            "owner_id": owner_id,
            "limit": limit,
            "total": len(records),
            "items": [self._record_payload(record) for record in records[:limit]],
        }

    def approve(
        self,
        context: RequestContext,
        memory_id: str,
        *,
        decision_note: str,
    ) -> dict:
        record = self.review_service.approve_candidate(
            memory_id,
            reviewer_id=context.user_id,
            decision_note=decision_note,
        )
        self._record_domain_audit(
            context,
            decision="approved",
            memory_id=record.memory_id,
            owner_id=record.owner_id,
            memory_status=record.status.value,
            decision_note=decision_note,
        )
        return {"record": self._record_payload(record)}

    def reject(
        self,
        context: RequestContext,
        memory_id: str,
        *,
        decision_note: str,
    ) -> dict:
        record = self.review_service.reject_candidate(
            memory_id,
            reviewer_id=context.user_id,
            decision_note=decision_note,
        )
        self._record_domain_audit(
            context,
            decision="rejected",
            memory_id=record.memory_id,
            owner_id=record.owner_id,
            memory_status=record.status.value,
            decision_note=decision_note,
        )
        return {"record": self._record_payload(record)}

    def validation_status(self, context: RequestContext, *, owner_id: str = "default") -> dict:
        return self.store.get_validation_policy_status(owner_id=owner_id)

    def deprecation_preview(self, context: RequestContext, *, owner_id: str = "default") -> dict:
        plan = self.review_service.build_owner_deprecation_plan(owner_id=owner_id)
        return {"plan": plan}

    def deprecate_owner(
        self,
        context: RequestContext,
        *,
        owner_id: str,
        confirm_owner_id: str,
        decision_note: str,
    ) -> dict:
        if confirm_owner_id != owner_id:
            raise ValueError("confirm_owner_id must match owner_id")
        records = self.review_service.deprecate_owner_memories(
            owner_id=owner_id,
            reviewer_id=context.user_id,
            decision_note=decision_note,
        )
        self._record_domain_audit(
            context,
            decision="deprecated",
            memory_id=owner_id,
            owner_id=owner_id,
            memory_status="deprecated",
            decision_note=decision_note,
            metadata={
                "destructive_delete": False,
                "records_deprecated": len(records),
                "confirm_owner_id": confirm_owner_id,
            },
        )
        return {
            "owner_id": owner_id,
            "confirm_owner_id": confirm_owner_id,
            "records": [self._record_payload(record) for record in records],
            "destructive_delete": False,
        }

    def _record_domain_audit(
        self,
        context: RequestContext,
        *,
        decision: str,
        memory_id: str,
        owner_id: str,
        memory_status: str,
        decision_note: str,
        metadata: dict | None = None,
    ) -> None:
        self.audit_service.record(
            AuditEvent(
                event_type="memory_review",
                route="memory_operator",
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision=decision,
                reason=decision_note,
                metadata={
                    "memory_id": memory_id,
                    "owner_id": owner_id,
                    "memory_status": memory_status,
                    **(metadata or {}),
                },
            )
        )

    def _record_payload(self, record: MemoryRecord) -> dict:
        return record.model_dump(mode="json")


memory_operator_adapter = MemoryOperatorAdapter()
