"""Trace extractors for Enterprise 2.0 trajectory evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.enterprise.observability.audit_service import SQLiteAuditSink
from app.enterprise.observability.models import AuditEvent
from evals.enterprise.models import ActualTrajectory, ObservedTaskContract, TraceSource


class AuditTraceExtractor:
    """Load an actual trace from inline fixtures, JSONL audit, or SQLite audit."""

    def extract(self, source: TraceSource) -> ActualTrajectory:
        events = self._load_audit_events(source)
        trace_id = source.trace_id
        request_id = source.request_id or _first_request_id(events) or _first_sse_value(source.sse_events, "request_id")
        route = source.route or _first_route(events)
        task_contract = _task_contract_for_trace(source, events)
        return ActualTrajectory(
            trace_id=trace_id,
            request_id=request_id or "",
            route=route or "",
            source_kind=source.kind,
            audit_events=events,
            sse_events=[dict(event) for event in source.sse_events],
            observed_stages=_ordered_unique(_stage_for_event(event) for event in events),
            observed_tools=_ordered_unique(tool for event in events for tool in _tools_for_event(event)),
            observed_data_sources=_ordered_unique(source for event in events for source in _data_sources_for_event(event)),
            observed_audit_events=[event.event_type for event in events],
            terminal_status=_terminal_status(events, source.sse_events),
            task_contract=task_contract,
        )

    def _load_audit_events(self, source: TraceSource) -> list[AuditEvent]:
        if source.kind == "inline":
            events = [AuditEvent.model_validate(event) for event in source.audit_events]
        elif source.kind == "jsonl":
            events = self._load_jsonl(source)
        elif source.kind == "sqlite":
            events = self._load_sqlite(source)
        else:
            raise ValueError(f"Unsupported trace source kind: {source.kind}")

        return [
            event
            for event in events
            if event.trace_id == source.trace_id
            and (source.request_id is None or event.request_id == source.request_id)
        ]

    def _load_jsonl(self, source: TraceSource) -> list[AuditEvent]:
        path = _require_path(source)
        events: list[AuditEvent] = []
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                stripped = line.strip()
                if not stripped:
                    continue
                events.append(AuditEvent.model_validate(json.loads(stripped)))
        return events

    def _load_sqlite(self, source: TraceSource) -> list[AuditEvent]:
        path = _require_path(source)
        return SQLiteAuditSink(path).query(trace_id=source.trace_id)


def _require_path(source: TraceSource) -> Path:
    if not source.path:
        raise ValueError(f"Trace source kind={source.kind} requires path")
    return Path(source.path)


def _first_request_id(events: list[AuditEvent]) -> str:
    return events[0].request_id if events else ""


def _first_route(events: list[AuditEvent]) -> str:
    return events[0].route if events else ""


def _first_sse_value(events: list[dict[str, Any]], key: str) -> str:
    for event in events:
        value = event.get(key)
        if value:
            return str(value)
    return ""


def _ordered_unique(values) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _stage_for_event(event: AuditEvent) -> str:
    event_type = event.event_type
    if event_type == "auth_failed" or event.route == "auth":
        return "auth"
    if event_type == "permission_checked":
        return "permission"
    if event_type in {"tool_visible", "tool_blocked", "tool_call", "tool_failure"}:
        return "tool"
    if event_type in {"model_visible", "model_call"}:
        return "model"
    if event_type == "request_failed" and _looks_guardrail_block(event):
        return "guardrail"
    if event_type in {"request_started", "request_completed", "request_failed"}:
        return "gateway"
    if event_type in {"rag_retrieval", "upload_saved"} or event.route == "rag":
        return "retrieval"
    if event_type == "database_query" or event.route in {"database", "database_demo"}:
        return "database"
    if event_type == "admin_operation" or event.route == "admin":
        return "admin"
    metadata_stage = event.metadata.get("stage")
    if metadata_stage:
        return str(metadata_stage)
    return event.route or event_type


def _looks_guardrail_block(event: AuditEvent) -> bool:
    text = " ".join(
        str(part or "")
        for part in (event.decision, event.reason, event.error_class, event.metadata.get("reason"))
    ).lower()
    return "guardrail" in text or "blocked" in text


def _tools_for_event(event: AuditEvent):
    metadata = event.metadata
    candidates: list[str] = []
    for key in ("tool_id", "tool_name", "tool"):
        value = metadata.get(key)
        if isinstance(value, str):
            candidates.append(value)
    for key in ("tool_ids", "tools", "visible_tools", "blocked_tools"):
        value = metadata.get(key)
        if isinstance(value, list):
            candidates.extend(str(item) for item in value)
    return candidates


def _data_sources_for_event(event: AuditEvent):
    metadata = event.metadata
    candidates: list[str] = []
    for key in ("data_source", "data_source_id", "document_id", "table_name"):
        value = metadata.get(key)
        if isinstance(value, str):
            candidates.append(value)
    for key in ("data_sources", "document_ids", "table_names"):
        value = metadata.get(key)
        if isinstance(value, list):
            candidates.extend(str(item) for item in value)
    return candidates


def _task_contract_for_trace(
    source: TraceSource,
    events: list[AuditEvent],
) -> ObservedTaskContract | None:
    contract_id = _task_contract_id_for_trace(source, events)
    return (
        _task_contract_from_inline_records(source, contract_id)
        or _task_contract_from_sqlite_repository(source, contract_id)
        or _task_contract_from_audit(events, contract_id)
    )


def _task_contract_id_for_trace(source: TraceSource, events: list[AuditEvent]) -> str:
    for event in events:
        for key in ("task_contract_id", "task_id"):
            value = event.metadata.get(key)
            if value:
                return str(value)
    for event in source.sse_events:
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        value = event.get("task_contract_id") or data.get("task_contract_id")
        if value:
            return str(value)
    return ""


def _task_contract_from_inline_records(
    source: TraceSource,
    contract_id: str,
) -> ObservedTaskContract | None:
    for payload in source.task_contracts:
        observed = _observed_contract_from_payload(payload)
        if observed and _matches_contract_id(observed, contract_id):
            return observed
    return None


def _task_contract_from_sqlite_repository(
    source: TraceSource,
    contract_id: str,
) -> ObservedTaskContract | None:
    if not source.task_contract_path:
        return None
    from app.enterprise.tasks.repository import SQLiteTaskContractRepository

    contracts = SQLiteTaskContractRepository(source.task_contract_path).list_by_trace(source.trace_id)
    for contract in contracts:
        observed = _observed_contract_from_task_contract(contract)
        if _matches_contract_id(observed, contract_id):
            return observed
    return None


def _task_contract_from_audit(
    events: list[AuditEvent],
    contract_id: str,
) -> ObservedTaskContract | None:
    for event in reversed(events):
        if event.event_type not in {"task_contract_created", "task_contract_rejected"}:
            continue
        observed = _observed_contract_from_audit_event(event)
        if observed and _matches_contract_id(observed, contract_id):
            return observed
    return None


def _observed_contract_from_payload(payload: dict[str, Any]) -> ObservedTaskContract | None:
    if "task_contract_id" in payload:
        return ObservedTaskContract.model_validate(payload)
    if "task_id" in payload:
        try:
            from app.enterprise.tasks.models import TaskContract

            return _observed_contract_from_task_contract(TaskContract.model_validate(payload))
        except Exception:
            return _observed_contract_from_contract_like_payload(payload)
    return None


def _observed_contract_from_contract_like_payload(payload: dict[str, Any]) -> ObservedTaskContract:
    scope = payload.get("scope") or {}
    return ObservedTaskContract(
        task_contract_id=str(payload.get("task_id") or payload.get("task_contract_id") or ""),
        status=str(payload.get("status") or ""),
        risk_level=str(payload.get("risk_level") or ""),
        requires_human_approval=bool(payload.get("requires_human_approval")),
        allowed_data_sources=_as_str_list(scope.get("allowed_data_sources")),
        allowed_tools=_as_str_list(scope.get("allowed_tools")),
        forbidden_actions=_as_str_list(scope.get("forbidden_actions")),
        success_criteria=_as_str_list(payload.get("success_criteria")),
        expected_outputs=_as_str_list(payload.get("expected_outputs")),
    )


def _observed_contract_from_task_contract(contract) -> ObservedTaskContract:
    return ObservedTaskContract(
        task_contract_id=contract.task_id,
        status=contract.status.value if hasattr(contract.status, "value") else str(contract.status),
        risk_level=contract.risk_level.value if hasattr(contract.risk_level, "value") else str(contract.risk_level),
        requires_human_approval=contract.requires_human_approval,
        allowed_data_sources=list(contract.scope.allowed_data_sources),
        allowed_tools=list(contract.scope.allowed_tools),
        forbidden_actions=list(contract.scope.forbidden_actions),
        success_criteria=list(contract.success_criteria),
        expected_outputs=list(contract.expected_outputs),
    )


def _observed_contract_from_audit_event(event: AuditEvent) -> ObservedTaskContract | None:
    metadata = event.metadata
    task_id = metadata.get("task_id") or metadata.get("task_contract_id")
    if not task_id:
        return None
    return ObservedTaskContract(
        task_contract_id=str(task_id),
        status=str(metadata.get("status") or ""),
        risk_level=str(metadata.get("risk_level") or ""),
        requires_human_approval=bool(metadata.get("requires_human_approval")),
        allowed_data_sources=_as_str_list(metadata.get("allowed_data_sources")),
        allowed_tools=_as_str_list(metadata.get("allowed_tools")),
        forbidden_actions=_as_str_list(metadata.get("forbidden_actions")),
        success_criteria=_as_str_list(metadata.get("success_criteria")),
        expected_outputs=_as_str_list(metadata.get("expected_outputs")),
    )


def _matches_contract_id(contract: ObservedTaskContract, expected_id: str) -> bool:
    return not expected_id or contract.task_contract_id == expected_id


def _as_str_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple | set):
        return [str(item) for item in value]
    return [str(value)]


def _terminal_status(events: list[AuditEvent], sse_events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        if event.event_type == "request_completed":
            return "completed"
        if event.event_type == "request_failed":
            return "blocked" if event.decision in {"blocked", "denied"} or _looks_guardrail_block(event) else "failed"

    for event in reversed(sse_events):
        event_type = str(event.get("type") or "")
        status = str(event.get("status") or "")
        if event_type in {"done", "complete"} or status == "completed":
            return "completed"
        if event_type == "blocked" or status == "blocked":
            return "blocked"
        if event_type == "error" or status == "failed":
            return "failed"
    return "unknown"
