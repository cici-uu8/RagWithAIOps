"""Models for Enterprise 2.0 trace trajectory evaluation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.enterprise.observability.models import AuditEvent


class ExpectedSseContract(BaseModel):
    must_include_trace_id: bool = True
    must_include_request_id: bool = True
    allowed_event_types: list[str] = Field(default_factory=list)


class ExpectedContractScope(BaseModel):
    allowed_data_sources: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)


class ExpectedTaskContract(BaseModel):
    required_scope: ExpectedContractScope = Field(default_factory=ExpectedContractScope)
    forbidden_tools: list[str] = Field(default_factory=list)
    requires_human_approval: bool | None = None
    success_criteria_keywords: list[str] = Field(default_factory=list)


class TrajectoryExpectation(BaseModel):
    final_status: str
    required_stages: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    required_audit_events: list[str] = Field(default_factory=list)
    sse: ExpectedSseContract | None = None
    expected_contract: ExpectedTaskContract | None = None


class TraceSource(BaseModel):
    kind: Literal["inline", "jsonl", "sqlite"] = "inline"
    trace_id: str
    request_id: str | None = None
    route: str | None = None
    path: str | None = None
    task_contract_path: str | None = None
    audit_events: list[dict[str, Any]] = Field(default_factory=list)
    sse_events: list[dict[str, Any]] = Field(default_factory=list)
    task_contracts: list[dict[str, Any]] = Field(default_factory=list)


class ExpectedTrajectory(BaseModel):
    eval_id: str
    input: dict[str, Any] = Field(default_factory=dict)
    expected: TrajectoryExpectation
    trace_source: TraceSource


class ObservedTaskContract(BaseModel):
    task_contract_id: str
    status: str = ""
    risk_level: str = ""
    requires_human_approval: bool = False
    allowed_data_sources: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)


class ActualTrajectory(BaseModel):
    trace_id: str
    request_id: str
    route: str
    source_kind: str
    audit_events: list[AuditEvent] = Field(default_factory=list)
    sse_events: list[dict[str, Any]] = Field(default_factory=list)
    observed_stages: list[str] = Field(default_factory=list)
    observed_tools: list[str] = Field(default_factory=list)
    observed_data_sources: list[str] = Field(default_factory=list)
    observed_audit_events: list[str] = Field(default_factory=list)
    terminal_status: str = "unknown"
    task_contract: ObservedTaskContract | None = None


class TrajectoryMismatch(BaseModel):
    code: str
    category: str
    message: str
    stage: str | None = None
    event_type: str | None = None
    tool_id: str | None = None


class TraceEvalResult(BaseModel):
    eval_id: str
    mode: str = "reference"
    outcome: str = "passed"
    trace_id: str
    request_id: str
    route: str
    final_status: str
    passed: bool
    mismatches: list[TrajectoryMismatch] = Field(default_factory=list)


class TraceEvalReport(BaseModel):
    evalset_path: str
    mode: str = "reference"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    summary: dict[str, Any] = Field(default_factory=dict)
    results: list[TraceEvalResult] = Field(default_factory=list)
    report_json_path: str | None = None
    report_markdown_path: str | None = None
