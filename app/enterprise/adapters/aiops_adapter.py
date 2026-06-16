"""Thin AIOps adapter for E2 RequestGateway."""

from collections.abc import AsyncIterator

from app.enterprise.aiops.failure_semantics import AIOpsFailureSemantics
from app.enterprise.errors.mapper import build_error_event, map_exception_to_error_context
from app.enterprise.errors.models import ErrorClass
from app.enterprise.gateway.models import GatewayRequest
from app.enterprise.gateway.request_gateway import RequestBlocked, RequestGateway, request_gateway
from app.enterprise.observability.models import AuditEvent
from app.enterprise.reviews.models import ReviewStatus
from app.enterprise.reviews.service import (
    HumanReviewService,
    human_review_service as default_human_review_service,
)
from app.enterprise.routing.router import StrategyRouter, strategy_router
from app.enterprise.tasks.models import TaskContractCreate, TaskStatus
from app.enterprise.tasks.service import TaskContractService, task_contract_service
from app.enterprise.verifiers import PlanVerifier, VerificationService
from app.models.aiops import AIOpsRequest


class AIOpsAdapter:
    def __init__(
        self,
        aiops_service,
        gateway: RequestGateway | None = None,
        contract_service: TaskContractService | None = None,
        human_review_service: HumanReviewService | None = None,
        verification_service: VerificationService | None = None,
        routing_service: StrategyRouter | None = None,
    ):
        self.aiops_service = aiops_service
        self.gateway = gateway or request_gateway
        self.contract_service = contract_service or task_contract_service
        self.human_review_service = human_review_service or default_human_review_service
        self.verification_service = verification_service or VerificationService()
        self.routing_service = routing_service or strategy_router

    async def diagnose_stream(
        self,
        request: AIOpsRequest,
        *,
        headers,
        session_id: str,
        memory_mode: str,
    ) -> AsyncIterator[dict]:
        gateway_request = GatewayRequest.from_headers(
            route="aiops",
            payload=request.model_dump(),
            headers=headers,
        )

        async def handler(context):
            self.routing_service.record_shadow_decision(
                audit_service=self.gateway.audit_service,
                context=context,
                actual_route="aiops",
                payload=request.model_dump(),
            )
            contract = None
            contract_id: str | None = None
            contract_result = None
            if request.task_contract is not None:
                resume_result = self._resolve_review_resume(context, request)
                if resume_result is not None:
                    if not resume_result["can_execute"]:
                        yield resume_result["event"]
                        return
                    contract = resume_result["contract"]
                    contract_id = contract.task_id
                else:
                    contract_create = _task_contract_create_from_request(request)
                    risk_detection = self.human_review_service.risk_detector.evaluate_contract(
                        contract_create,
                        query=request.query,
                    )
                    contract_create = self.human_review_service.risk_detector.force_review_contract(
                        contract_create,
                        risk_detection,
                    )
                    contract_result = self.contract_service.create_contract(
                        context,
                        contract_create,
                    )
                    contract = contract_result.contract
                    contract_id = contract_result.contract.task_id
                    if (
                        contract_result.decision == "pending_approval"
                        or risk_detection.requires_review
                    ):
                        review = self.human_review_service.register_pending_review(
                            context,
                            contract,
                            route="aiops",
                            reason=contract_result.reason
                            if contract_result.decision == "pending_approval"
                            else risk_detection.reason,
                            signals=risk_detection.signals,
                        )
                        yield _pending_approval_event(
                            trace_id=context.trace_id,
                            request_id=context.request_id,
                            review_id=review.review_id,
                            task_id=contract_id,
                            reason=review.reason,
                        )
                        return
                if contract_id is None:
                    raise ValueError("task contract id is required")
                if contract is None:
                    raise ValueError("task contract is required")
                if contract_result is not None and not contract_result.can_execute:
                    yield {
                        "type": "error",
                        "stage": "task_contract",
                        "status": "failed",
                        "message": contract_result.reason,
                        "error_class": ErrorClass.PERMISSION_DENIED.value,
                        "decision": "abort",
                        "task_contract_id": contract_id,
                        "reason": contract_result.reason,
                        "data": {
                            "error_class": ErrorClass.PERMISSION_DENIED.value,
                            "decision": "abort",
                            "recoverable": False,
                            "user_message": "任务合同未通过权限校验。",
                            "task_contract_id": contract_id,
                            "status": contract_result.contract.status.value,
                            "issue_codes": [
                                issue.code
                                for issue in contract_result.validation.issues
                            ],
                        },
                    }
                    return

            from app.services import aiops_service as aiops_service_module

            previous_aiops_audit_service = (
                aiops_service_module.aiops_tool_catalog.audit_service
            )
            aiops_service_module.aiops_tool_catalog.audit_service = self.gateway.audit_service
            try:
                async for event in self.aiops_service.diagnose(
                    session_id=session_id,
                    memory_mode=memory_mode,
                    enable_memory_guidance=request.enable_memory_guidance,
                    memory_owner_id=request.memory_owner_id,
                    query=request.query,
                    task_contract_id=contract_id,
                    context=context,
                ):
                    if isinstance(event, dict):
                        event = {
                            **event,
                            "trace_id": context.trace_id,
                            "request_id": context.request_id,
                        }
                        self._record_failure_semantics_event(context, event)
                        if contract_id is not None:
                            event.setdefault("task_contract_id", contract_id)
                        if contract is not None and event.get("type") == "plan":
                            verification = self.verification_service.verify(
                                context,
                                PlanVerifier(),
                                {
                                    "plan": event.get("plan", []),
                                    "task_contract": contract,
                                },
                            )
                            if not verification.passed:
                                yield _verifier_error_event(verification)
                                return
                    yield event
            finally:
                aiops_service_module.aiops_tool_catalog.audit_service = (
                    previous_aiops_audit_service
                )

        try:
            async for event in self.gateway.execute_stream(gateway_request, handler):
                yield event
        except RequestBlocked as exc:
            yield build_error_event(
                map_exception_to_error_context(exc, stage="guardrail"),
                trace_id=exc.trace_id,
                request_id=getattr(exc, "request_id", ""),
            )

    def _record_failure_semantics_event(self, context, event: dict) -> None:
        if not event.get("failure_semantics"):
            return
        metadata = {
            **AIOpsFailureSemantics.to_audit_metadata(event),
            "source_event_type": event.get("type"),
            "stage": event.get("stage"),
        }
        for key, value in event.items():
            if key.startswith("structured_output_") and value is not None:
                metadata[key] = value
        hard_failure = bool(metadata.get("failure_semantics_hard_failure"))
        self.gateway.audit_service.record(
            AuditEvent(
                event_type="aiops_failure" if hard_failure else "aiops_degradation",
                route="aiops",
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision="failed" if hard_failure else "degraded",
                reason=str(metadata["failure_semantics"]),
                metadata=metadata,
            )
        )

    def _resolve_review_resume(self, context, request: AIOpsRequest) -> dict | None:
        task_contract = request.task_contract
        if task_contract is None:
            return None
        review_id = task_contract.review_id
        task_id = task_contract.task_id
        if not review_id and not task_id:
            return None

        review = (
            self.human_review_service.get(review_id)
            if review_id
            else self.human_review_service.get_by_task(task_id or "")
        )
        if review is None and task_id:
            review = self.human_review_service.get_by_task(task_id)
        if review is None:
            return {
                "can_execute": False,
                "event": _review_error_event(
                    trace_id=context.trace_id,
                    request_id=context.request_id,
                    task_id=task_id or "",
                    review_id=review_id or "",
                    status="failed",
                    reason="human_review_not_found",
                    message="人工审批记录不存在。",
                ),
            }
        if task_id and review.task_id != task_id:
            return {
                "can_execute": False,
                "event": _review_error_event(
                    trace_id=context.trace_id,
                    request_id=context.request_id,
                    task_id=task_id,
                    review_id=review.review_id,
                    status="failed",
                    reason="human_review_task_mismatch",
                    message="审批记录与任务不匹配。",
                ),
            }
        if review.status == ReviewStatus.PENDING:
            return {
                "can_execute": False,
                "event": _pending_approval_event(
                    trace_id=context.trace_id,
                    request_id=context.request_id,
                    review_id=review.review_id,
                    task_id=review.task_id,
                    reason=review.reason,
                ),
            }
        if review.status == ReviewStatus.REJECTED:
            return {
                "can_execute": False,
                "event": _review_error_event(
                    trace_id=context.trace_id,
                    request_id=context.request_id,
                    task_id=review.task_id,
                    review_id=review.review_id,
                    status="rejected",
                    reason=review.approver_reason or "human_review_rejected",
                    message="人工审批已拒绝，任务不会继续执行。",
                ),
            }

        contract = self.contract_service.get_contract(review.task_id)
        if contract is None:
            return {
                "can_execute": False,
                "event": _review_error_event(
                    trace_id=context.trace_id,
                    request_id=context.request_id,
                    task_id=review.task_id,
                    review_id=review.review_id,
                    status="failed",
                    reason="task_contract_not_found",
                    message="审批对应的任务合同不存在。",
                ),
            }
        running_contract = self.contract_service.update_status(
            review.task_id,
            status=TaskStatus.RUNNING,
        ) or contract
        return {
            "can_execute": True,
            "contract": running_contract,
        }


def _task_contract_create_from_request(request: AIOpsRequest) -> TaskContractCreate:
    task_contract = request.task_contract
    if task_contract is None:
        raise ValueError("task_contract is required")
    return TaskContractCreate(
        user_goal=task_contract.user_goal or request.query or "AIOps diagnosis task",
        scope=task_contract.scope.model_dump(),
        success_criteria=task_contract.success_criteria,
        risk_level=task_contract.risk_level,
        requires_human_approval=task_contract.requires_human_approval,
        latency_budget_ms=task_contract.latency_budget_ms,
        cost_budget=task_contract.cost_budget,
        expected_outputs=task_contract.expected_outputs,
    )


def _pending_approval_event(
    *,
    trace_id: str,
    request_id: str,
    review_id: str,
    task_id: str,
    reason: str,
) -> dict:
    return {
        "type": "pending_approval",
        "stage": "human_review",
        "status": "pending",
        "message": "任务需要人工审批，已进入待审批队列。",
        "decision": "pending_approval",
        "reason": reason,
        "trace_id": trace_id,
        "request_id": request_id,
        "review_id": review_id,
        "task_contract_id": task_id,
        "data": {
            "review_id": review_id,
            "task_contract_id": task_id,
            "reason": reason,
        },
    }


def _review_error_event(
    *,
    trace_id: str,
    request_id: str,
    task_id: str,
    review_id: str,
    status: str,
    reason: str,
    message: str,
) -> dict:
    return {
        "type": "error",
        "stage": "human_review",
        "status": status,
        "message": message,
        "error_class": ErrorClass.PERMISSION_DENIED.value,
        "decision": "abort",
        "reason": reason,
        "trace_id": trace_id,
        "request_id": request_id,
        "review_id": review_id,
        "task_contract_id": task_id,
        "data": {
            "error_class": ErrorClass.PERMISSION_DENIED.value,
            "decision": "abort",
            "recoverable": False,
            "user_message": message,
            "review_id": review_id,
            "task_contract_id": task_id,
            "status": status,
        },
    }


def _verifier_error_event(verification) -> dict:
    return {
        "type": "error",
        "stage": "verifier",
        "status": verification.status.value,
        "message": "structured verifier blocked task execution",
        "error_class": ErrorClass.GUARDRAIL_BLOCKED.value,
        "decision": "abort",
        "reason": ",".join(finding.code for finding in verification.findings),
        "data": {
            "error_class": ErrorClass.GUARDRAIL_BLOCKED.value,
            "decision": "abort",
            "recoverable": False,
            "user_message": "结构化校验未通过，任务已停止。",
            "verifier": verification.verifier,
            "status": verification.status.value,
            "finding_codes": [finding.code for finding in verification.findings],
            "findings": [
                finding.model_dump(mode="json")
                for finding in verification.findings
            ],
            "revision_required": verification.revision_required,
            "max_revision_attempts": verification.max_revision_attempts,
        },
    }
