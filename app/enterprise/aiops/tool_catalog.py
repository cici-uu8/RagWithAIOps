"""AIOps tool catalog adapter for planner/executor/replanner."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from app.enterprise.aiops.failure_semantics import AIOpsFailureLabel, AIOpsFailureSemantics
from app.enterprise.context import RequestContext, get_current_request_context
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.observability.models import AuditEvent
from app.enterprise.permissions.service import (
    PermissionService,
    permission_service as default_permission_service,
)
from app.enterprise.tools.facade import ToolExecutionFacade
from app.enterprise.tools.gateway import ToolGateway
from app.enterprise.tools.local_provider import LocalAgentToolProvider
from app.enterprise.tools.models import ToolDefinition
from app.enterprise.tools.providers import StaticToolProvider
from app.tools import get_current_time, retrieve_knowledge

McpToolLoader = Callable[[], Awaitable[list[Any]]]

AIOPS_LOCAL_TOOL_IDS = {"get_current_time", "retrieve_knowledge"}

DEFAULT_AIOPS_REQUIRED_TOOLS: dict[str, set[str]] = {
    "cpuhigh": {
        "query_active_alerts",
        "query_metric_series",
        "search_service_logs",
        "analyze_log_pattern",
        "get_service_info",
        "get_recent_deployments",
        "search_historical_tickets",
        "list_service_dependencies",
    },
    "dbslowquery": {
        "query_active_alerts",
        "query_metric_series",
        "search_service_logs",
        "analyze_log_pattern",
        "get_service_info",
        "get_recent_deployments",
        "search_historical_tickets",
        "list_service_dependencies",
    },
    "redisqueuebacklog": {
        "query_active_alerts",
        "query_metric_series",
        "search_service_logs",
        "analyze_log_pattern",
        "get_service_info",
        "get_recent_deployments",
        "search_historical_tickets",
        "list_service_dependencies",
    },
}


@dataclass
class AIOpsToolCatalogResult:
    visible_tools: list[str]
    bindable_tools: list[Any]
    required_tools: list[str]
    missing_required_tools: list[str] = field(default_factory=list)
    failure_semantics: AIOpsFailureLabel | None = None
    hard_failure: bool = False

    @property
    def passed(self) -> bool:
        return not self.hard_failure and not self.missing_required_tools


class AIOpsToolCatalog:
    def __init__(
        self,
        *,
        local_tools: list[Any] | None = None,
        mcp_tool_loader: McpToolLoader | None = None,
        permission_service: PermissionService | None = None,
        audit_service: AuditService | None = None,
    ):
        self.local_tools = local_tools or [get_current_time, retrieve_knowledge]
        self.mcp_tool_loader = mcp_tool_loader
        self.permission_service = permission_service or default_permission_service
        self.audit_service = audit_service or AuditService()

    async def visible_tools(
        self,
        context: RequestContext | None = None,
    ) -> list[str]:
        bindable_tools = await self.bindable_tools(context)
        return [tool.name if hasattr(tool, "name") else str(tool) for tool in bindable_tools]

    async def bindable_tools(
        self,
        context: RequestContext | None = None,
    ) -> list[Any]:
        if context is None:
            local_tools = list(self.local_tools)
            mcp_tools = await self._load_mcp_tools()
            return [*local_tools, *mcp_tools]

        return await self._context_bindable_tools(context)

    async def execute(
        self,
        context: RequestContext | None,
        tool_id: str,
        arguments: dict[str, Any],
    ) -> Any:
        if context is None:
            raise ValueError("AIOps tool execution requires a request context")

        mcp_tools = await self._load_mcp_tools()
        mcp_definitions = [self._to_tool_definition(tool) for tool in mcp_tools]
        gateway = self._build_gateway(mcp_definitions)
        return await gateway.execute(context, tool_id, arguments)

    def required_tools_for_scenario(self, scenario: str | None) -> list[str]:
        normalized = self._normalize_scenario(scenario)
        if normalized is None:
            return []
        return sorted(DEFAULT_AIOPS_REQUIRED_TOOLS.get(normalized, set()))

    def validate_required_tools(
        self,
        scenario: str | None,
        available_tools: Iterable[Any] | None = None,
        *,
        context: RequestContext | None = None,
    ) -> AIOpsToolCatalogResult:
        required_tools = self.required_tools_for_scenario(scenario)
        visible_tools = self._tool_names(list(available_tools or []))
        missing = [tool for tool in required_tools if tool not in set(visible_tools)]
        failure_semantics = (
            AIOpsFailureLabel.MISSING_REQUIRED_TOOL if missing else None
        )
        failure_metadata = (
            AIOpsFailureSemantics.to_audit_metadata(
                {"failure_semantics": failure_semantics.value}
            )
            if failure_semantics
            else {}
        )
        result = AIOpsToolCatalogResult(
            visible_tools=visible_tools,
            bindable_tools=list(available_tools or []),
            required_tools=required_tools,
            missing_required_tools=missing,
            failure_semantics=failure_semantics,
            hard_failure=bool(failure_metadata.get("failure_semantics_hard_failure")),
        )
        if context is not None:
            self._record_required_tool_validation(context, scenario, result, failure_metadata)
        return result

    def _record_required_tool_validation(
        self,
        context: RequestContext,
        scenario: str | None,
        result: AIOpsToolCatalogResult,
        failure_metadata: dict[str, Any],
    ) -> None:
        self.audit_service.record(
            AuditEvent(
                event_type="aiops_tool_validation",
                route="aiops",
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision="blocked" if result.missing_required_tools else "allowed",
                reason=(
                    result.failure_semantics.value
                    if result.failure_semantics is not None
                    else None
                ),
                metadata={
                    "scenario": scenario,
                    "visible_tools": result.visible_tools,
                    "required_tools": result.required_tools,
                    "missing_required_tools": result.missing_required_tools,
                    **failure_metadata,
                },
            )
        )

    async def _load_mcp_tools(self) -> list[Any]:
        if self.mcp_tool_loader is None:
            from app.agent.mcp_client import get_mcp_tools_with_retry

            return await get_mcp_tools_with_retry()
        return await self.mcp_tool_loader()

    async def _context_bindable_tools(self, context: RequestContext) -> list[Any]:
        mcp_tools = await self._load_mcp_tools()
        mcp_definitions = [self._to_tool_definition(tool) for tool in mcp_tools]
        tool_ids = set(AIOPS_LOCAL_TOOL_IDS)
        tool_ids.update(tool.resource_id for tool in mcp_definitions)
        gateway = self._build_gateway(mcp_definitions)
        facade = ToolExecutionFacade(gateway=gateway)
        return await facade.get_bindable_tools(context, tool_ids=tool_ids)

    def _build_gateway(self, mcp_definitions: list[ToolDefinition]) -> ToolGateway:
        default_allowed_tool_ids = set(AIOPS_LOCAL_TOOL_IDS)
        default_allowed_tool_ids.update(tool.resource_id for tool in mcp_definitions)
        return ToolGateway(
            providers=[
                LocalAgentToolProvider(),
                StaticToolProvider(mcp_definitions),
            ],
            permission_service=self.permission_service,
            audit_service=self.audit_service,
            default_allowed_tool_ids=default_allowed_tool_ids,
        )

    def _to_tool_definition(self, raw_tool: Any) -> ToolDefinition:
        name = str(getattr(raw_tool, "name", raw_tool))
        description = str(getattr(raw_tool, "description", ""))
        return ToolDefinition(
            resource_id=name,
            name=name,
            description=description,
            source="mcp",
            raw_tool=raw_tool,
            metadata={"provider": "mcp", "capability": "aiops"},
        )

    def _tool_names(self, tools: list[Any]) -> list[str]:
        names: list[str] = []
        for tool in tools:
            name = getattr(tool, "name", None)
            if name:
                names.append(str(name))
                continue
            resource_id = getattr(tool, "resource_id", None)
            if resource_id:
                names.append(str(resource_id))
                continue
            names.append(str(tool))
        return names

    def _normalize_scenario(self, scenario: str | None) -> str | None:
        if scenario is None:
            return None
        normalized = "".join(ch for ch in scenario.lower() if ch.isalnum())
        return normalized or None


aiops_tool_catalog = AIOpsToolCatalog()


async def get_aiops_bindable_tools(
    *,
    local_tools: list[Any] | None = None,
    mcp_tool_loader: McpToolLoader | None = None,
    context: RequestContext | None = None,
    catalog: AIOpsToolCatalog | None = None,
) -> list[Any]:
    """Return AIOps bindable tools with a legacy no-context fallback."""

    current_context = context if context is not None else get_current_request_context()
    if current_context is None:
        tools = local_tools or [get_current_time, retrieve_knowledge]
        if mcp_tool_loader is None:
            from app.agent.mcp_client import get_mcp_tools_with_retry

            mcp_tools = await get_mcp_tools_with_retry()
        else:
            mcp_tools = await mcp_tool_loader()
        return [*tools, *mcp_tools]

    active_catalog = catalog or aiops_tool_catalog
    return await active_catalog.bindable_tools(current_context)


async def retrieve_aiops_experience_context(
    query: str,
    *,
    retrieve_tool: Any | None = None,
    context: RequestContext | None = None,
    catalog: AIOpsToolCatalog | None = None,
) -> Any:
    """Retrieve AIOps experience docs through ToolGateway when context exists."""

    current_context = context if context is not None else get_current_request_context()
    if current_context is None:
        tool = retrieve_tool or retrieve_knowledge
        return await tool.ainvoke({"query": query})

    active_catalog = catalog or aiops_tool_catalog
    return await active_catalog.execute(
        current_context,
        "retrieve_knowledge",
        {"query": query},
    )
