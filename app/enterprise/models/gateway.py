"""Observable enterprise gateway for model calls."""

from __future__ import annotations

import time
from dataclasses import replace

from app.config import config
from app.enterprise.context import RequestContext
from app.enterprise.errors.mapper import recovery_metadata
from app.enterprise.errors.models import ErrorClass, ErrorContext
from app.enterprise.errors.recovery import RecoveryStrategy
from app.enterprise.models.models import ModelEndpoint, ModelRequest, ModelResponse
from app.enterprise.models.providers import DashScopeModelProvider, ModelProvider
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.observability.models import AuditEvent
from app.enterprise.permissions.models import ResourceDescriptor
from app.enterprise.permissions.service import PermissionService, permission_service


class ModelAccessDenied(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Model access denied: {reason}")


class ModelGatewayError(Exception):
    def __init__(self, message: str, *, failed_endpoint_ids: list[str]):
        self.failed_endpoint_ids = failed_endpoint_ids
        super().__init__(message)


class ModelGateway:
    def __init__(
        self,
        *,
        endpoints: list[ModelEndpoint] | None = None,
        providers: dict[str, ModelProvider] | None = None,
        permission_service: PermissionService | None = None,
        audit_service: AuditService | None = None,
    ):
        self.endpoints = endpoints if endpoints is not None else default_model_endpoints()
        self.providers = providers if providers is not None else {"dashscope": DashScopeModelProvider()}
        self.permission_service = permission_service or permission_service_default()
        self.audit_service = audit_service or AuditService()

    def list_visible_endpoints(self, context: RequestContext) -> list[ResourceDescriptor]:
        descriptors = [self._resource_descriptor(endpoint) for endpoint in self.endpoints]
        visible = self.permission_service.filter_allowed(context, descriptors, action="use")
        self.audit_service.record(
            AuditEvent(
                event_type="model_visible",
                route="model_gateway",
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision="allowed",
                metadata={
                    "visible_endpoint_ids": [endpoint.resource_id for endpoint in visible],
                    "visible_count": len(visible),
                },
            )
        )
        return visible

    async def generate(self, context: RequestContext, request: ModelRequest) -> ModelResponse:
        candidates = self._candidate_endpoints(request)
        allowed = self._allowed_endpoints(context, candidates)
        if not allowed:
            recovery = RecoveryStrategy().decide(
                ErrorContext(
                    error_class=ErrorClass.PERMISSION_DENIED,
                    stage="model_permission",
                    reason="no_allowed_model_endpoint",
                )
            )
            self.audit_service.record(
                AuditEvent(
                    event_type="model_call",
                    route="model_gateway",
                    trace_id=context.trace_id,
                    request_id=context.request_id,
                    user_id=context.user_id,
                    decision="denied",
                    reason="no_allowed_model_endpoint",
                    error_class=recovery.error_class.value,
                    metadata={
                        "status": "blocked",
                        "requested_endpoint_id": request.endpoint_id,
                        **recovery_metadata(recovery),
                    },
                )
            )
            raise ModelAccessDenied("no_allowed_model_endpoint")

        started = time.perf_counter()
        failed_endpoint_ids: list[str] = []
        source_error_classes: list[str] = []
        last_error: BaseException | None = None
        for endpoint in allowed:
            provider = self.providers.get(endpoint.provider_name)
            try:
                if provider is None:
                    raise RuntimeError(f"Model provider not configured: {endpoint.provider_name}")

                response = await provider.generate(request, endpoint)
                latency_ms = (time.perf_counter() - started) * 1000
                fallback_used = bool(failed_endpoint_ids)
                enriched = replace(
                    response,
                    endpoint_id=endpoint.endpoint_id,
                    model_name=endpoint.model_name,
                    provider_name=endpoint.provider_name,
                    fallback_used=fallback_used,
                    status="success",
                )
                self._record_model_call(
                    context,
                    endpoint=endpoint,
                    response=enriched,
                    latency_ms=latency_ms,
                    failed_endpoint_ids=failed_endpoint_ids,
                    source_error_classes=source_error_classes,
                )
                return enriched
            except Exception as exc:
                failed_endpoint_ids.append(endpoint.endpoint_id)
                source_error_classes.append(type(exc).__name__)
                last_error = exc

        latency_ms = (time.perf_counter() - started) * 1000
        recovery = RecoveryStrategy().decide(
            ErrorContext(
                error_class=ErrorClass.MODEL_UNAVAILABLE,
                stage="model_call",
                reason="model_provider_failed",
                metadata={"fallback_available": False},
            )
        )
        self.audit_service.record(
            AuditEvent(
                event_type="model_call",
                route="model_gateway",
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision="failed",
                reason="model_provider_failed",
                error_class=recovery.error_class.value,
                latency_ms=latency_ms,
                metadata={
                    "status": "failed",
                    "fallback_used": len(failed_endpoint_ids) > 1,
                    "failed_endpoint_ids": failed_endpoint_ids,
                    "requested_endpoint_id": request.endpoint_id,
                    **recovery_metadata(
                        recovery,
                        source_error_class=type(last_error).__name__ if last_error is not None else None,
                        source_error_classes=source_error_classes,
                    ),
                },
            )
        )
        raise ModelGatewayError(
            "All model endpoints failed",
            failed_endpoint_ids=failed_endpoint_ids,
        )

    def _candidate_endpoints(self, request: ModelRequest) -> list[ModelEndpoint]:
        endpoints = self.endpoints
        if request.endpoint_id is not None:
            endpoints = [endpoint for endpoint in endpoints if endpoint.endpoint_id == request.endpoint_id]
        return sorted(endpoints, key=lambda endpoint: endpoint.priority)

    def _allowed_endpoints(
        self,
        context: RequestContext,
        endpoints: list[ModelEndpoint],
    ) -> list[ModelEndpoint]:
        allowed: list[ModelEndpoint] = []
        for endpoint in endpoints:
            decision = self.permission_service.check(
                context,
                resource_type="model_endpoint",
                resource_id=endpoint.endpoint_id,
                action="use",
            )
            if decision.allowed:
                allowed.append(endpoint)
        return allowed

    def _record_model_call(
        self,
        context: RequestContext,
        *,
        endpoint: ModelEndpoint,
        response: ModelResponse,
        latency_ms: float,
        failed_endpoint_ids: list[str],
        source_error_classes: list[str],
    ) -> None:
        fallback_used = bool(failed_endpoint_ids)
        if fallback_used:
            recovery = RecoveryStrategy().decide(
                ErrorContext(
                    error_class=ErrorClass.MODEL_UNAVAILABLE,
                    stage="model_call",
                    reason="fallback_used",
                    metadata={"fallback_available": True},
                )
            )
            decision = "degraded"
            error_class = recovery.error_class.value
        else:
            recovery = None
            decision = "allowed"
            error_class = None
        self.audit_service.record(
            AuditEvent(
                event_type="model_call",
                route="model_gateway",
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision=decision,
                latency_ms=latency_ms,
                metadata={
                    "endpoint_id": endpoint.endpoint_id,
                    "model_name": endpoint.model_name,
                    "provider_name": endpoint.provider_name,
                    "fallback_used": response.fallback_used,
                    "failed_endpoint_ids": failed_endpoint_ids,
                    "usage": response.usage,
                    **(
                        recovery_metadata(
                            recovery,
                            source_error_classes=source_error_classes,
                            extra={"recovery_status": recovery.status},
                        )
                        if recovery is not None
                        else {}
                    ),
                    "status": response.status,
                },
                error_class=error_class,
            )
        )

    def _resource_descriptor(self, endpoint: ModelEndpoint) -> ResourceDescriptor:
        return ResourceDescriptor(
            resource_type="model_endpoint",
            resource_id=endpoint.endpoint_id,
            name=endpoint.model_name,
            metadata={"provider": endpoint.provider_name, **endpoint.metadata},
        )


def default_model_endpoints() -> list[ModelEndpoint]:
    return [
        ModelEndpoint(
            endpoint_id=config.rag_model,
            model_name=config.rag_model,
            provider_name="dashscope",
        )
    ]


def permission_service_default() -> PermissionService:
    return permission_service


model_gateway = ModelGateway()
