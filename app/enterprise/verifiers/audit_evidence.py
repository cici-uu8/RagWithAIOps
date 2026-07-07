"""Deterministic audit evidence verifier for P0 governance gates."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.enterprise.context import RequestContext
from app.enterprise.verifiers.base import BaseVerifier
from app.enterprise.verifiers.models import (
    VerificationFinding,
    VerificationResult,
    VerificationStatus,
)


class AuditEvidenceVerifier(BaseVerifier):
    name = "AuditEvidenceVerifier"

    required_event_fields = (
        "event_type",
        "route",
        "trace_id",
        "request_id",
        "user_id",
        "decision",
    )
    decisions_requiring_reason = {
        "denied",
        "blocked",
        "failed",
        "needs_revision",
        "degraded",
        "pending_approval",
    }
    required_metadata_by_event_type = {
        "permission_checked": ("resource_type", "resource_id", "action"),
        "tool_call": ("tool_id", "status"),
        "tool_blocked": ("tool_id", "status"),
        "tool_failure": ("tool_id", "status"),
        "database_operation_prepare_created": (
            "confirmation_id",
            "database_id",
            "operation_type",
            "resource_ids",
        ),
        "database_operation_prepare_rejected": ("database_id", "operation_type"),
        "database_operation_confirmation_confirmed": (
            "confirmation_id",
            "database_id",
            "operation_type",
        ),
        "database_operation_confirmation_cancelled": ("confirmation_id",),
        "database_operation_confirmation_expired": ("confirmation_id",),
        "database_operation_executed": (
            "confirmation_id",
            "database_id",
            "operation_type",
            "resource_ids",
        ),
        "database_operation_execution_failed": (
            "confirmation_id",
            "database_id",
            "operation_type",
        ),
        "human_review_requested": ("review_id", "task_id", "risk_level"),
        "human_review_approved": ("review_id", "task_id", "risk_level"),
        "human_review_rejected": ("review_id", "task_id", "risk_level"),
        "verification_result": ("verifier", "status", "result"),
    }

    def verify(self, context: RequestContext, payload: dict[str, Any]) -> VerificationResult:
        del context
        events = payload.get("audit_events") or []
        if not isinstance(events, list) or not events:
            return self._result(
                VerificationStatus.FAILED,
                [
                    self._finding(
                        "audit_events_missing",
                        "缺少可验证的审计事件列表。",
                    )
                ],
                metadata={"event_count": 0, "checked_event_count": 0},
            )

        findings: list[VerificationFinding] = []
        normalized_events = [_normalize_event(event) for event in events]

        for index, event in enumerate(normalized_events):
            if event is None:
                findings.append(
                    self._finding(
                        "audit_event_invalid",
                        "审计事件不是可解析的对象或字典。",
                        metadata={"event_index": index},
                    )
                )
                continue

            self._check_required_event_fields(index, event, findings)
            self._check_reason(index, event, findings)
            self._check_metadata(index, event, findings)

        status = VerificationStatus.FAILED if findings else VerificationStatus.PASSED
        return self._result(
            status,
            findings,
            metadata={
                "event_count": len(events),
                "checked_event_count": len(normalized_events),
            },
        )

    def _check_required_event_fields(
        self,
        index: int,
        event: dict[str, Any],
        findings: list[VerificationFinding],
    ) -> None:
        for field in self.required_event_fields:
            if _has_value(event.get(field)):
                continue
            findings.append(
                self._finding(
                    f"audit_{field}_missing",
                    "审计事件缺少 P0 门禁要求的基础追踪字段。",
                    metadata={
                        "event_index": index,
                        "event_type": event.get("event_type"),
                        "missing_field": field,
                    },
                )
            )

    def _check_reason(
        self,
        index: int,
        event: dict[str, Any],
        findings: list[VerificationFinding],
    ) -> None:
        decision = str(event.get("decision") or "")
        if decision not in self.decisions_requiring_reason or _has_value(event.get("reason")):
            return
        findings.append(
            self._finding(
                "audit_reason_missing",
                "拒绝、阻断、失败或降级类审计事件必须记录 reason。",
                metadata={
                    "event_index": index,
                    "event_type": event.get("event_type"),
                    "decision": decision,
                },
            )
        )

    def _check_metadata(
        self,
        index: int,
        event: dict[str, Any],
        findings: list[VerificationFinding],
    ) -> None:
        event_type = str(event.get("event_type") or "")
        required_fields = self.required_metadata_by_event_type.get(event_type, ())
        if not required_fields:
            return

        metadata = event.get("metadata") or {}
        if not isinstance(metadata, dict):
            missing_fields = [f"metadata.{field}" for field in required_fields]
        else:
            missing_fields = [
                f"metadata.{field}"
                for field in required_fields
                if not _has_value(metadata.get(field))
            ]

        if not missing_fields:
            return

        findings.append(
            self._finding(
                "audit_metadata_missing",
                "审计事件缺少 P0 决策所需的资源或决策 metadata。",
                metadata={
                    "event_index": index,
                    "event_type": event_type,
                    "missing_fields": missing_fields,
                },
            )
        )


def _normalize_event(event: Any) -> dict[str, Any] | None:
    if isinstance(event, dict):
        return event
    if isinstance(event, BaseModel):
        return event.model_dump(mode="json")
    model_dump = getattr(event, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return None


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True
