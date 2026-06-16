"""Models for user permission requests."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


class PermissionRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PermissionRequestCreateRequest(BaseModel):
    resource_type: str = Field(..., min_length=1)
    resource_id: str = Field(..., min_length=1)
    action: str = Field(..., min_length=1)
    reason: str | None = None


class PermissionRequestDecisionRequest(BaseModel):
    reason: str | None = None


class PermissionRequestRecord(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    requester_user_id: str
    requester_username: str
    requester_department_id: str
    requester_department_name: str
    resource_type: str
    resource_id: str
    action: str
    reason: str | None = None
    status: PermissionRequestStatus = PermissionRequestStatus.PENDING
    approver_user_id: str | None = None
    approver_reason: str | None = None
    grant_id: str | None = None
    review_queue: str
    requires_global_review: bool = False
    candidate_department_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    decided_at: datetime | None = None
