"""Thin execution facade for model-bindable enterprise tools."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from app.enterprise.context import RequestContext
from app.enterprise.tools.gateway import ToolGateway, tool_gateway
from app.enterprise.tools.models import ToolDefinition


class ToolExecutionFacade:
    """Expose visible, bindable, and executable tools through one gateway seam."""

    def __init__(self, *, gateway: ToolGateway | None = None):
        self.gateway = gateway or tool_gateway

    async def list_visible_tools(
        self,
        context: RequestContext,
        *,
        capability: str | None = None,
        tool_ids: set[str] | None = None,
    ) -> list[ToolDefinition]:
        tools = await self.gateway.list_visible_tools(context)
        if capability is not None:
            tools = [
                tool
                for tool in tools
                if tool.metadata.get("capability") == capability
                or capability in tool.metadata.get("capabilities", [])
            ]
        if tool_ids is not None:
            tools = [tool for tool in tools if tool.resource_id in tool_ids]
        return tools

    async def get_bindable_tools(
        self,
        context: RequestContext,
        *,
        capability: str | None = None,
        tool_ids: set[str] | None = None,
    ) -> list[Any]:
        return [
            self._to_gateway_bound_tool(context, tool)
            for tool in await self.list_visible_tools(
                context,
                capability=capability,
                tool_ids=tool_ids,
            )
        ]

    async def execute(
        self,
        context: RequestContext,
        tool_id: str,
        arguments: dict[str, Any],
    ) -> Any:
        return await self.gateway.execute(context, tool_id, arguments)

    def _to_gateway_bound_tool(
        self,
        context: RequestContext,
        tool: ToolDefinition,
    ) -> Any:
        raw_tool = tool.raw_tool
        name = str(getattr(raw_tool, "name", tool.name))
        description = str(getattr(raw_tool, "description", tool.description))
        args_schema = getattr(raw_tool, "args_schema", None)
        response_format = getattr(raw_tool, "response_format", "content")
        return_direct = bool(getattr(raw_tool, "return_direct", False))

        async def _call_gateway(**arguments):
            return await self.execute(context, tool.resource_id, dict(arguments))

        return StructuredTool.from_function(
            coroutine=_call_gateway,
            name=name,
            description=description,
            args_schema=args_schema,
            infer_schema=args_schema is None,
            response_format=response_format,
            return_direct=return_direct,
        )


tool_execution_facade = ToolExecutionFacade()
