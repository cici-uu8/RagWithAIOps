"""Deterministic human-review risk detection for Enterprise 2.0 F6."""

from __future__ import annotations

import re

from app.enterprise.reviews.models import RiskDetectionResult
from app.enterprise.tasks.models import RiskLevel, TaskContractCreate, TaskScope


class RiskDetector:
    """Small deterministic detector for approval-only F6 gates."""

    _DB_WRITE_PATTERN = re.compile(
        r"\b(insert|update|delete|drop|alter|truncate|create\s+table)\b",
        re.IGNORECASE,
    )
    _PII_PATTERN = re.compile(
        r"(\b\d{3}[- ]?\d{2}[- ]?\d{4}\b|\b1[3-9]\d{9}\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})"
    )

    def evaluate_contract(
        self,
        contract: TaskContractCreate,
        *,
        query: str | None = None,
    ) -> RiskDetectionResult:
        signals: list[str] = []
        text = " ".join(
            part
            for part in [
                contract.user_goal,
                query or "",
                " ".join(contract.scope.allowed_data_sources),
                " ".join(contract.scope.allowed_tools),
                " ".join(contract.scope.forbidden_actions),
                " ".join(contract.expected_outputs),
            ]
            if part
        )
        normalized = text.lower()

        if contract.requires_human_approval:
            signals.append("explicit_human_approval_required")
        if contract.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
            signals.append(f"risk_level_{contract.risk_level.value}")
        if self._DB_WRITE_PATTERN.search(text):
            signals.append("database_write_request")
        if any("sensitive" in source.lower() for source in contract.scope.allowed_data_sources):
            signals.append("sensitive_document_access")
        if (
            "grant all" in normalized
            or "all permissions" in normalized
            or "admin" in normalized
            and ("grant" in normalized or "授权" in normalized)
        ):
            signals.append("broad_authorization_change")
        if self._PII_PATTERN.search(text):
            signals.append("possible_pii")
        if (
            ("low confidence" in normalized or "低置信" in normalized)
            and any(action in normalized for action in ["restart", "deploy", "delete", "重启", "发布"])
        ):
            signals.append("low_confidence_production_impact")

        if not signals:
            return RiskDetectionResult()
        return RiskDetectionResult(
            requires_review=True,
            reason=",".join(signals),
            signals=signals,
        )

    def force_review_contract(
        self,
        contract: TaskContractCreate,
        detection: RiskDetectionResult,
    ) -> TaskContractCreate:
        if not detection.requires_review:
            return contract
        if contract.requires_human_approval:
            return contract
        return contract.model_copy(update={"requires_human_approval": True})


def scope_from_contract(contract: TaskContractCreate) -> TaskScope:
    return contract.scope
