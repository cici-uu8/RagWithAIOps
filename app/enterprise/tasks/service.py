"""Task contract service for Enterprise 2.0 F1."""

from __future__ import annotations

from app.enterprise.context import RequestContext
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.observability.models import AuditEvent
from app.enterprise.tasks.models import (
    TaskContract,
    TaskContractCreate,
    TaskContractCreateResult,
    TaskStatus,
)
from app.enterprise.tasks.repository import SQLiteTaskContractRepository
from app.enterprise.tasks.validator import ContractValidator


class TaskContractService:
    def __init__(
        self,
        repository: SQLiteTaskContractRepository | None = None,
        validator: ContractValidator | None = None,
        audit_service: AuditService | None = None,
    ):
        self.repository = repository or SQLiteTaskContractRepository()
        self.validator = validator or ContractValidator()
        self.audit_service = audit_service or AuditService()

    def create_contract(
        self,
        context: RequestContext,
        create: TaskContractCreate,
    ) -> TaskContractCreateResult:
        contract = TaskContract(
            trace_id=context.trace_id,
            request_id=context.request_id,
            user_id=context.user_id,
            user_goal=create.user_goal,
            scope=create.scope,
            success_criteria=create.success_criteria,
            risk_level=create.risk_level,
            requires_human_approval=create.requires_human_approval,
            latency_budget_ms=create.latency_budget_ms,
            cost_budget=create.cost_budget,
            expected_outputs=create.expected_outputs,
        )
        validation = self.validator.validate(context, contract)

        if not validation.allowed:
            rejected = contract.with_status(TaskStatus.REJECTED)
            self.repository.create(rejected)
            reason = _issue_reason(validation)
            self._record_audit(
                context,
                rejected,
                event_type="task_contract_rejected",
                decision="denied",
                reason=reason,
                validation=validation,
            )
            return TaskContractCreateResult(
                can_execute=False,
                decision="denied",
                reason=reason,
                contract=rejected,
                validation=validation,
            )

        if validation.requires_approval:
            pending = contract.with_status(TaskStatus.PENDING)
            self.repository.create(pending)
            self._record_audit(
                context,
                pending,
                event_type="task_contract_created",
                decision="pending_approval",
                reason="approval_required",
                validation=validation,
            )
            return TaskContractCreateResult(
                can_execute=False,
                decision="pending_approval",
                reason="approval_required",
                contract=pending,
                validation=validation,
            )

        running = contract.with_status(TaskStatus.RUNNING)
        self.repository.create(running)
        self._record_audit(
            context,
            running,
            event_type="task_contract_created",
            decision="allowed",
            reason="contract_valid",
            validation=validation,
        )
        return TaskContractCreateResult(
            can_execute=True,
            decision="allowed",
            reason="contract_valid",
            contract=running,
            validation=validation,
        )

    def get_contract(self, task_id: str) -> TaskContract | None:
        return self.repository.get(task_id)

    def list_by_trace(self, trace_id: str) -> list[TaskContract]:
        return self.repository.list_by_trace(trace_id)

    def update_status(self, task_id: str, status: TaskStatus) -> TaskContract | None:
        return self.repository.update_status(task_id, status)

    def _record_audit(
        self,
        context: RequestContext,
        contract: TaskContract,
        *,
        event_type: str,
        decision: str,
        reason: str,
        validation,
    ) -> None:
        self.audit_service.record(
            AuditEvent(
                event_type=event_type,
                route="task_contract",
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision=decision,
                reason=reason,
                metadata={
                    "task_id": contract.task_id,
                    "status": contract.status.value,
                    "risk_level": contract.risk_level.value,
                    "requires_human_approval": contract.requires_human_approval,
                    "allowed_data_sources": contract.scope.allowed_data_sources,
                    "allowed_tools": contract.scope.allowed_tools,
                    "forbidden_actions": contract.scope.forbidden_actions,
                    "success_criteria": contract.success_criteria,
                    "expected_outputs": contract.expected_outputs,
                    "issue_codes": [issue.code for issue in validation.issues],
                },
            )
        )


def _issue_reason(validation) -> str:
    return ",".join(issue.code for issue in validation.issues) or "contract_invalid"


task_contract_service = TaskContractService()
