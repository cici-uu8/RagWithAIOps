"""Human review service for Enterprise 2.0 F6."""

from __future__ import annotations

from app.enterprise.context import RequestContext
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.observability.models import AuditEvent
from app.enterprise.reviews.models import HumanReviewRequest, ReviewStatus
from app.enterprise.reviews.repository import (
    HumanReviewRepository,
    SQLiteHumanReviewRepository,
)
from app.enterprise.reviews.risk_detector import RiskDetector
from app.enterprise.tasks.models import TaskContract


class HumanReviewError(ValueError):
    pass


class HumanReviewService:
    def __init__(
        self,
        *,
        repository: HumanReviewRepository | None = None,
        audit_service: AuditService | None = None,
        risk_detector: RiskDetector | None = None,
    ):
        self.repository = repository or SQLiteHumanReviewRepository()
        self.audit_service = audit_service or AuditService()
        self.risk_detector = risk_detector or RiskDetector()

    def register_pending_review(
        self,
        context: RequestContext,
        contract: TaskContract,
        *,
        route: str,
        reason: str,
        signals: list[str] | None = None,
    ) -> HumanReviewRequest:
        existing = self.repository.get_by_task(contract.task_id)
        if existing is not None and existing.status == ReviewStatus.PENDING:
            return existing

        review = HumanReviewRequest(
            task_id=contract.task_id,
            trace_id=context.trace_id,
            request_id=context.request_id,
            user_id=context.user_id,
            route=route,
            user_goal=contract.user_goal,
            risk_level=contract.risk_level.value,
            reason=reason,
            metadata={
                "signals": signals or [],
                "requires_human_approval": contract.requires_human_approval,
                "allowed_data_sources": contract.scope.allowed_data_sources,
                "allowed_tools": contract.scope.allowed_tools,
            },
        )
        self.repository.create(review)
        self._record_review_event(
            context,
            review,
            event_type="human_review_requested",
            decision="pending_approval",
            reason=reason,
        )
        return review

    def get(self, review_id: str) -> HumanReviewRequest | None:
        return self.repository.get(review_id)

    def get_by_task(self, task_id: str) -> HumanReviewRequest | None:
        return self.repository.get_by_task(task_id)

    def list_pending(self) -> list[HumanReviewRequest]:
        return self.repository.list_pending()

    def approve(
        self,
        context: RequestContext,
        *,
        review_id: str,
        reason: str = "",
    ) -> HumanReviewRequest:
        review = self._require_review(review_id)
        updated = self.repository.update(
            review.with_decision(
                ReviewStatus.APPROVED,
                approver_user_id=context.user_id,
                reason=reason,
            )
        )
        self._record_review_event(
            context,
            updated,
            event_type="human_review_approved",
            decision="allowed",
            reason=reason or "approved",
        )
        return updated

    def reject(
        self,
        context: RequestContext,
        *,
        review_id: str,
        reason: str = "",
    ) -> HumanReviewRequest:
        review = self._require_review(review_id)
        updated = self.repository.update(
            review.with_decision(
                ReviewStatus.REJECTED,
                approver_user_id=context.user_id,
                reason=reason,
            )
        )
        self._record_review_event(
            context,
            updated,
            event_type="human_review_rejected",
            decision="denied",
            reason=reason or "rejected",
        )
        return updated

    def _require_review(self, review_id: str) -> HumanReviewRequest:
        review = self.repository.get(review_id)
        if review is None:
            raise HumanReviewError("Human review not found")
        return review

    def _record_review_event(
        self,
        context: RequestContext,
        review: HumanReviewRequest,
        *,
        event_type: str,
        decision: str,
        reason: str,
    ) -> None:
        self.audit_service.record(
            AuditEvent(
                event_type=event_type,
                route="human_review",
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision=decision,
                reason=reason,
                metadata={
                    "review_id": review.review_id,
                    "task_id": review.task_id,
                    "review_status": review.status.value,
                    "request_user_id": review.user_id,
                    "approver_user_id": review.approver_user_id,
                    "route": review.route,
                    "risk_level": review.risk_level,
                    "signals": review.metadata.get("signals", []),
                },
            )
        )


human_review_service = HumanReviewService()
