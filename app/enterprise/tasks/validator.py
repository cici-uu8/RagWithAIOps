"""Task contract validation for Enterprise 2.0 F1."""

from __future__ import annotations

from app.enterprise.context import RequestContext
from app.enterprise.permissions.service import PermissionService, permission_service
from app.enterprise.tasks.models import (
    ContractValidationIssue,
    ContractValidationResult,
    RiskLevel,
    TaskContract,
)


class ContractValidator:
    def __init__(self, permissions: PermissionService | None = None):
        self.permissions = permissions or permission_service

    def validate(self, context: RequestContext, contract: TaskContract) -> ContractValidationResult:
        issues: list[ContractValidationIssue] = []
        issues.extend(self._validate_data_sources(context, contract))
        issues.extend(self._validate_tools(context, contract))
        issues.extend(self._validate_forbidden_action_conflicts(contract))
        issues.extend(self._validate_high_risk_policy(contract))

        hard_block = bool(issues)
        requires_approval = (
            contract.requires_human_approval
            or contract.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
        )
        return ContractValidationResult(
            allowed=not hard_block,
            requires_approval=requires_approval,
            issues=issues,
        )

    def _validate_data_sources(
        self,
        context: RequestContext,
        contract: TaskContract,
    ) -> list[ContractValidationIssue]:
        issues: list[ContractValidationIssue] = []
        for data_source in contract.scope.allowed_data_sources:
            decision = self.permissions.check(
                context,
                resource_type="document",
                resource_id=data_source,
                action="read",
            )
            if not decision.allowed:
                issues.append(
                    ContractValidationIssue(
                        code="data_source_permission_denied",
                        message=f"Data source is not authorized: {data_source}",
                        resource_type="document",
                        resource_id=data_source,
                        action="read",
                    )
                )
        return issues

    def _validate_tools(
        self,
        context: RequestContext,
        contract: TaskContract,
    ) -> list[ContractValidationIssue]:
        issues: list[ContractValidationIssue] = []
        for tool_id in contract.scope.allowed_tools:
            decision = self.permissions.check(
                context,
                resource_type="tool",
                resource_id=tool_id,
                action="use",
            )
            if not decision.allowed:
                issues.append(
                    ContractValidationIssue(
                        code="tool_permission_denied",
                        message=f"Tool is not authorized: {tool_id}",
                        resource_type="tool",
                        resource_id=tool_id,
                        action="use",
                    )
                )
        return issues

    def _validate_forbidden_action_conflicts(
        self,
        contract: TaskContract,
    ) -> list[ContractValidationIssue]:
        allowed_tools = {_normalize_item(tool_id) for tool_id in contract.scope.allowed_tools}
        issues: list[ContractValidationIssue] = []
        for action in contract.scope.forbidden_actions:
            normalized = _normalize_item(action)
            if normalized in allowed_tools:
                issues.append(
                    ContractValidationIssue(
                        code="forbidden_action_conflict",
                        message=f"Forbidden action conflicts with allowed tool: {action}",
                        resource_type="tool",
                        resource_id=action,
                        action="use",
                    )
                )
        return issues

    def _validate_high_risk_policy(self, contract: TaskContract) -> list[ContractValidationIssue]:
        if contract.risk_level not in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
            return []
        if contract.requires_human_approval:
            return []
        return [
            ContractValidationIssue(
                code="high_risk_requires_approval",
                message="High-risk task contracts must require human approval",
            )
        ]


def _normalize_item(value: str) -> str:
    return value.strip().lower().replace("_", "-")
