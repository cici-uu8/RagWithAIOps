"""Observable enterprise gateway for tools."""

from __future__ import annotations

import time
from typing import Any

from app.enterprise.context import RequestContext
from app.enterprise.errors.mapper import map_exception_to_error_context, recovery_metadata
from app.enterprise.errors.models import ErrorClass, ErrorContext
from app.enterprise.errors.recovery import RecoveryStrategy
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.observability.models import AuditEvent
from app.enterprise.permissions.service import PermissionService, permission_service
from app.enterprise.tools.models import ToolDefinition
from app.enterprise.tools.providers import MCPToolProvider, ToolProvider
from app.enterprise.tools.registry import ToolRegistry


class ToolAccessDenied(Exception):
    def __init__(self, tool_id: str, reason: str):
        self.tool_id = tool_id
        self.reason = reason
        super().__init__(f"Tool access denied: {tool_id} ({reason})")


class ToolExecutionError(Exception):
    def __init__(self, tool_id: str, cause: BaseException):
        self.tool_id = tool_id
        self.cause = cause
        super().__init__(f"Tool execution failed: {tool_id} ({type(cause).__name__})")


class ToolGateway:
    def __init__(
        self,
        *,
        providers: list[ToolProvider] | None = None,
        permission_service: PermissionService | None = None,
        audit_service: AuditService | None = None,
        include_database_tools: bool = False,
        registry: ToolRegistry | None = None,
        default_allowed_tool_ids: set[str] | None = None,
    ):
        self.providers = providers if providers is not None else [MCPToolProvider()]
        self.permission_service = permission_service or permission_service_default()
        self.audit_service = audit_service or AuditService()
        self.include_database_tools = include_database_tools
        self.registry = registry or ToolRegistry(include_database_tools=include_database_tools)
        self.default_allowed_tool_ids = set(default_allowed_tool_ids or set())

    async def list_visible_tools(self, context: RequestContext) -> list[ToolDefinition]:
        tool_entries, filtered = await self._collect_tools()
        visible: list[ToolDefinition] = []
        blocked_tool_ids: list[str] = []
        default_allowed_tool_ids: list[str] = []

        for tool_id, (tool, _provider) in tool_entries.items():
            if self._is_default_allowed_tool(tool_id):
                visible.append(tool)
                default_allowed_tool_ids.append(tool_id)
                continue

            decision = self.permission_service.check(
                context,
                resource_type="tool",
                resource_id=tool_id,
                action="use",
            )
            if decision.allowed:
                visible.append(tool)
            else:
                blocked_tool_ids.append(tool_id)

        self.audit_service.record(
            AuditEvent(
                event_type="tool_visible",
                route="tool_gateway",
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision="allowed",
                metadata={
                    "visible_tool_ids": [tool.resource_id for tool in visible],
                    "blocked_tool_ids": blocked_tool_ids,
                    "filtered_tool_ids": [tool.resource_id for tool in filtered],
                    "default_allowed_tool_ids": default_allowed_tool_ids,
                    "visible_count": len(visible),
                    "blocked_count": len(blocked_tool_ids),
                    "filtered_count": len(filtered),
                },
            )
        )
        return visible

    async def get_bindable_tools(self, context: RequestContext) -> list[Any]:
        return [tool.bindable_tool for tool in await self.list_visible_tools(context)]

    async def execute(
        self,
        context: RequestContext,
        tool_id: str,
        arguments: dict[str, Any],
    ) -> Any:
        tool_entries, filtered = await self._collect_tools()
        entry = tool_entries.get(tool_id)
        if entry is None:
            self._record_blocked(context, tool_id, "tool_not_found")
            raise ToolAccessDenied(tool_id, "tool_not_found")

        tool, provider = entry
        if not self._is_default_allowed_tool(tool_id):
            decision = self.permission_service.check(
                context,
                resource_type="tool",
                resource_id=tool_id,
                action="use",
            )
            if not decision.allowed:
                self._record_blocked(context, tool_id, decision.reason)
                raise ToolAccessDenied(tool_id, decision.reason)

        started = time.perf_counter()
        try:
            execute_with_context = getattr(provider, "execute_tool_with_context", None)
            if execute_with_context is not None:
                result = await execute_with_context(tool_id, arguments, context)
            else:
                result = await provider.execute_tool(tool_id, arguments)
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            error_context = map_exception_to_error_context(
                exc,
                stage="tool_execution",
                reason="tool_execution_failed",
                metadata={
                    "allow_partial": bool(tool.metadata.get("allow_partial")),
                    "retryable": bool(tool.metadata.get("retryable")),
                },
            )
            recovery = RecoveryStrategy().decide(error_context)
            self.audit_service.record(
                AuditEvent(
                    event_type="tool_failure",
                    route="tool_gateway",
                    trace_id=context.trace_id,
                    request_id=context.request_id,
                    user_id=context.user_id,
                    decision="blocked" if recovery.status == "blocked" else "failed",
                    reason="tool_execution_failed",
                    error_class=recovery.error_class.value,
                    latency_ms=latency_ms,
                    metadata={
                        "tool_id": tool_id,
                        "tool_name": tool.name,
                        "source": tool.source,
                        **recovery_metadata(
                            recovery,
                            source_error_class=error_context.source_error_class,
                            extra={"status": recovery.status},
                        ),
                    },
                )
            )
            raise ToolExecutionError(tool_id, exc) from exc

        latency_ms = (time.perf_counter() - started) * 1000
        self.audit_service.record(
            AuditEvent(
                event_type="tool_call",
                route="tool_gateway",
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision="allowed",
                latency_ms=latency_ms,
                metadata={
                    "tool_id": tool_id,
                    "tool_name": tool.name,
                    "source": tool.source,
                    "status": "success",
                    "default_allowed": self._is_default_allowed_tool(tool_id),
                },
            )
        )
        return result

    async def _collect_tools(
        self,
    ) -> tuple[dict[str, tuple[ToolDefinition, ToolProvider]], list[ToolDefinition]]:
        entries: dict[str, tuple[ToolDefinition, ToolProvider]] = {}
        filtered: list[ToolDefinition] = []
        for provider in self.providers:
            provider_tools = await provider.list_tools()
            self.registry.register_many(provider_tools)
            for tool in provider_tools:
                entries.setdefault(tool.resource_id, (tool, provider))
        return entries, filtered

    def _record_blocked(self, context: RequestContext, tool_id: str, reason: str) -> None:
        recovery = RecoveryStrategy().decide(
            ErrorContext(
                error_class=ErrorClass.PERMISSION_DENIED,
                stage="tool_permission",
                reason=reason,
            )
        )
        self.audit_service.record(
            AuditEvent(
                event_type="tool_blocked",
                route="tool_gateway",
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision="denied",
                reason=reason,
                error_class=recovery.error_class.value,
                metadata={
                    "tool_id": tool_id,
                    **recovery_metadata(recovery, extra={"status": "blocked"}),
                },
            )
        )

    def _is_default_allowed_tool(self, tool_id: str) -> bool:
        return tool_id in self.default_allowed_tool_ids

def permission_service_default() -> PermissionService:
    return permission_service


tool_gateway = ToolGateway()
