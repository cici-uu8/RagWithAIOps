"""Audit-aware verification service."""

from __future__ import annotations

from typing import Any

from app.enterprise.context import RequestContext
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.observability.models import AuditEvent
from app.enterprise.verifiers.base import BaseVerifier
from app.enterprise.verifiers.models import (
    VerificationFinding,
    VerificationResult,
    VerificationStatus,
)


class VerificationFailed(Exception):
    def __init__(
        self,
        result: VerificationResult,
        *,
        original_error: BaseException | None = None,
    ):
        self.result = result
        self.original_error = original_error
        super().__init__(f"Verification failed: {result.verifier} ({result.status.value})")


class VerificationService:
    def __init__(
        self,
        *,
        audit_service: AuditService | None = None,
    ):
        self.audit_service = audit_service or AuditService()

    def verify(
        self,
        context: RequestContext,
        verifier: BaseVerifier,
        payload: dict[str, Any],
        *,
        original_error: BaseException | None = None,
        revision_attempts: int = 0,
    ) -> VerificationResult:
        try:
            result = verifier.verify(context, payload)
        except Exception as exc:
            result = VerificationResult(
                verifier=verifier.name,
                status=VerificationStatus.FAILED,
                findings=[
                    VerificationFinding(
                        code="verifier_exception",
                        message="自检器执行异常。",
                        metadata={"error_class": type(exc).__name__},
                    )
                ],
                revision_required=False,
                max_revision_attempts=verifier.max_revision_attempts,
            )
            self._record_audit(
                context,
                result,
                original_error=original_error or exc,
                revision_attempts=revision_attempts,
            )
            raise

        self._record_audit(
            context,
            result,
            original_error=original_error,
            revision_attempts=revision_attempts,
        )
        return result

    def ensure_passed(
        self,
        context: RequestContext,
        verifier: BaseVerifier,
        payload: dict[str, Any],
        *,
        original_error: BaseException | None = None,
        revision_attempts: int = 0,
    ) -> VerificationResult:
        result = self.verify(
            context,
            verifier,
            payload,
            original_error=original_error,
            revision_attempts=revision_attempts,
        )
        if self.should_stop(result, revision_attempts=revision_attempts):
            raise VerificationFailed(result, original_error=original_error)
        return result

    def should_stop(self, result: VerificationResult, *, revision_attempts: int = 0) -> bool:
        if result.status == VerificationStatus.FAILED:
            return True
        return (
            result.status == VerificationStatus.NEEDS_REVISION
            and revision_attempts >= result.max_revision_attempts
        )

    def _record_audit(
        self,
        context: RequestContext,
        result: VerificationResult,
        *,
        original_error: BaseException | None = None,
        revision_attempts: int,
    ) -> None:
        self.audit_service.record(
            AuditEvent(
                event_type="verification_result",
                route="verifier",
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision=_decision(result),
                reason=_reason(result),
                error_class=type(original_error).__name__ if original_error is not None else None,
                error_message=str(original_error) if original_error is not None else None,
                metadata={
                    "verifier": result.verifier,
                    "status": result.status.value,
                    "revision_required": result.revision_required,
                    "revision_attempts": revision_attempts,
                    "max_revision_attempts": result.max_revision_attempts,
                    "finding_codes": [finding.code for finding in result.findings],
                    "findings": [
                        finding.model_dump(mode="json")
                        for finding in result.findings
                    ],
                    "result": result.model_dump(mode="json"),
                },
            )
        )


def _decision(result: VerificationResult) -> str:
    if result.status == VerificationStatus.PASSED:
        return "allowed"
    if result.status == VerificationStatus.NEEDS_REVISION:
        return "needs_revision"
    return "failed"


def _reason(result: VerificationResult) -> str | None:
    return ",".join(finding.code for finding in result.findings) or result.status.value
