"""Task contract models for Enterprise 2.0 F1."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TaskStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class TaskScope(BaseModel):
    allowed_data_sources: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)


class TaskContractCreate(BaseModel):
    user_goal: str
    scope: TaskScope = Field(default_factory=TaskScope)
    success_criteria: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    requires_human_approval: bool = False
    latency_budget_ms: int = 30000
    cost_budget: dict[str, Any] | None = None
    expected_outputs: list[str] = Field(default_factory=list)


class TaskContract(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    trace_id: str
    request_id: str
    user_id: str
    user_goal: str
    scope: TaskScope = Field(default_factory=TaskScope)
    success_criteria: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    requires_human_approval: bool = False
    latency_budget_ms: int = 30000
    cost_budget: dict[str, Any] | None = None
    expected_outputs: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def with_status(self, status: TaskStatus) -> TaskContract:
        return self.model_copy(
            update={
                "status": status,
                "updated_at": datetime.now(UTC),
            }
        )


class ContractValidationIssue(BaseModel):
    code: str
    message: str
    resource_type: str | None = None
    resource_id: str | None = None
    action: str | None = None


class ContractValidationResult(BaseModel):
    allowed: bool
    requires_approval: bool = False
    issues: list[ContractValidationIssue] = Field(default_factory=list)


class TaskContractCreateResult(BaseModel):
    can_execute: bool
    decision: str
    reason: str
    contract: TaskContract
    validation: ContractValidationResult
