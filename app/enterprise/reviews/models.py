"""Human review models for Enterprise 2.0 F6."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class HumanReviewRequest(BaseModel):
    review_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    trace_id: str
    request_id: str
    user_id: str
    route: str
    user_goal: str = ""
    risk_level: str = "low"
    reason: str
    status: ReviewStatus = ReviewStatus.PENDING
    approver_user_id: str | None = None
    approver_reason: str | None = None
    decided_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    def with_decision(
        self,
        status: ReviewStatus,
        *,
        approver_user_id: str,
        reason: str,
    ) -> HumanReviewRequest:
        now = datetime.now(UTC)
        return self.model_copy(
            update={
                "status": status,
                "approver_user_id": approver_user_id,
                "approver_reason": reason,
                "decided_at": now,
                "updated_at": now,
            }
        )


class HumanReviewDecision(BaseModel):
    reason: str = ""


class RiskDetectionResult(BaseModel):
    requires_review: bool = False
    reason: str = "no_review_required"
    signals: list[str] = Field(default_factory=list)
