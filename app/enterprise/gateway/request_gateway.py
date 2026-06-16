"""Enterprise RequestGateway MVP for E2."""

import time
from collections.abc import AsyncIterator, Awaitable, Callable

from app.enterprise.context import (
    RequestContext,
    clear_current_request_context,
    reset_current_request_context,
    set_current_request_context,
)
from app.enterprise.errors.mapper import map_exception_to_error_context, recovery_metadata
from app.enterprise.errors.models import ErrorClass, ErrorContext
from app.enterprise.errors.recovery import RecoveryStrategy
from app.enterprise.gateway.guardrail_service import GuardrailService
from app.enterprise.gateway.models import GatewayRequest
from app.enterprise.gateway.rate_limit_service import NoOpRateLimitService
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.observability.models import AuditEvent


class RequestBlocked(PermissionError):
    def __init__(self, reason: str, *, trace_id: str, request_id: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.trace_id = trace_id
        self.request_id = request_id


class RateLimitBlocked(PermissionError):
    def __init__(self, reason: str, *, trace_id: str, request_id: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.trace_id = trace_id
        self.request_id = request_id


class RequestGateway:
    def __init__(
        self,
        audit_service: AuditService | None = None,
        guardrail_service: GuardrailService | None = None,
        rate_limit_service: NoOpRateLimitService | None = None,
    ):
        self.audit_service = audit_service or AuditService()
        self.guardrail_service = guardrail_service or GuardrailService()
        self.rate_limit_service = rate_limit_service or NoOpRateLimitService()

    async def execute(
        self,
        request: GatewayRequest,
        handler: Callable[[RequestContext], Awaitable],
    ):
        request.ensure_trace_id()
        request.ensure_request_id()
        context = self._build_context(request)
        context_token = set_current_request_context(context)
        started_at = time.perf_counter()

        self._record_started(request)
        try:
            await self._enforce_rate_limit(request)
            await self._enforce_guardrail(request)
            result = await handler(context)
            self._record_completed(request, started_at)
            return result
        except (RequestBlocked, RateLimitBlocked) as exc:
            error_context = self._error_context_for_blocked(exc)
            recovery = RecoveryStrategy().decide(error_context)
            self._record_failed(
                request,
                started_at,
                error_class=recovery.error_class.value,
                reason=exc.reason,
                decision="blocked",
                metadata=recovery_metadata(
                    recovery,
                    source_error_class=type(exc).__name__,
                ),
            )
            raise
        except Exception as exc:
            error_context = map_exception_to_error_context(exc, stage=request.route)
            recovery = RecoveryStrategy().decide(error_context)
            self._record_failed(
                request,
                started_at,
                error_class=recovery.error_class.value,
                reason=error_context.reason,
                decision=recovery.status,
                metadata=recovery_metadata(
                    recovery,
                    source_error_class=error_context.source_error_class,
                ),
            )
            raise
        finally:
            try:
                reset_current_request_context(context_token)
            except ValueError:
                clear_current_request_context()

    async def execute_stream(
        self,
        request: GatewayRequest,
        handler: Callable[[RequestContext], AsyncIterator[dict]],
    ) -> AsyncIterator[dict]:
        request.ensure_trace_id()
        request.ensure_request_id()
        context = self._build_context(request)
        context_token = set_current_request_context(context)
        started_at = time.perf_counter()

        self._record_started(request)
        try:
            await self._enforce_rate_limit(request)
            await self._enforce_guardrail(request)
            async for item in handler(context):
                yield item
            self._record_completed(request, started_at)
        except (RequestBlocked, RateLimitBlocked) as exc:
            error_context = self._error_context_for_blocked(exc)
            recovery = RecoveryStrategy().decide(error_context)
            self._record_failed(
                request,
                started_at,
                error_class=recovery.error_class.value,
                reason=exc.reason,
                decision="blocked",
                metadata=recovery_metadata(
                    recovery,
                    source_error_class=type(exc).__name__,
                ),
            )
            raise
        except Exception as exc:
            error_context = map_exception_to_error_context(exc, stage=request.route)
            recovery = RecoveryStrategy().decide(error_context)
            self._record_failed(
                request,
                started_at,
                error_class=recovery.error_class.value,
                reason=error_context.reason,
                decision=recovery.status,
                metadata=recovery_metadata(
                    recovery,
                    source_error_class=error_context.source_error_class,
                ),
            )
            raise
        finally:
            try:
                reset_current_request_context(context_token)
            except ValueError:
                clear_current_request_context()

    def _build_context(self, request: GatewayRequest) -> RequestContext:
        return RequestContext(
            request_id=request.request_id or "",
            trace_id=request.trace_id or "",
            user_id=request.user_id,
            username=request.username,
            department_id=request.department_id,
            department_name=request.department_name,
            roles=request.roles,
        )

    async def _enforce_guardrail(self, request: GatewayRequest) -> None:
        decision = await self.guardrail_service.evaluate(request)
        if not decision.allowed:
            raise RequestBlocked(
                decision.reason or "blocked",
                trace_id=request.trace_id or "",
                request_id=request.request_id or "",
            )

    async def _enforce_rate_limit(self, request: GatewayRequest) -> None:
        decision = await self.rate_limit_service.check(request)
        if not decision.allowed:
            raise RateLimitBlocked(
                decision.reason or "rate limited",
                trace_id=request.trace_id or "",
                request_id=request.request_id or "",
            )

    def _error_context_for_blocked(
        self,
        exc: RequestBlocked | RateLimitBlocked,
    ) -> ErrorContext:
        if isinstance(exc, RequestBlocked):
            return ErrorContext(
                error_class=ErrorClass.GUARDRAIL_BLOCKED,
                stage="guardrail",
                reason=exc.reason,
            )
        return ErrorContext(
            error_class=ErrorClass.PERMISSION_DENIED,
            stage="rate_limit",
            reason=exc.reason,
        )

    def _record_started(self, request: GatewayRequest) -> None:
        self.audit_service.record(
            AuditEvent(
                event_type="request_started",
                route=request.route,
                trace_id=request.trace_id or "",
                request_id=request.request_id or "",
                user_id=request.user_id,
                decision="allowed",
            )
        )

    def _record_completed(self, request: GatewayRequest, started_at: float) -> None:
        self.audit_service.record(
            AuditEvent(
                event_type="request_completed",
                route=request.route,
                trace_id=request.trace_id or "",
                request_id=request.request_id or "",
                user_id=request.user_id,
                decision="allowed",
                latency_ms=self._latency_ms(started_at),
            )
        )

    def _record_failed(
        self,
        request: GatewayRequest,
        started_at: float,
        *,
        error_class: str,
        reason: str | None = None,
        decision: str = "failed",
        metadata: dict | None = None,
    ) -> None:
        self.audit_service.record(
            AuditEvent(
                event_type="request_failed",
                route=request.route,
                trace_id=request.trace_id or "",
                request_id=request.request_id or "",
                user_id=request.user_id,
                decision=decision,
                reason=reason,
                error_class=error_class,
                latency_ms=self._latency_ms(started_at),
                metadata=metadata or {},
            )
        )

    def _latency_ms(self, started_at: float) -> float:
        return round((time.perf_counter() - started_at) * 1000, 3)


request_gateway = RequestGateway()
