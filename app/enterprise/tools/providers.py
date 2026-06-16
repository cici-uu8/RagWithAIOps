"""Tool providers used by ToolGateway."""

from __future__ import annotations

import inspect
from typing import Any, Protocol

from app.agent.mcp_client import get_mcp_tools_with_retry
from app.enterprise.tools.models import ToolDefinition


class ToolProvider(Protocol):
    async def list_tools(self) -> list[ToolDefinition]:
        ...

    async def execute_tool(self, resource_id: str, arguments: dict[str, Any]) -> Any:
        ...


class StaticToolProvider:
    """Small provider for local tools and tests."""

    def __init__(self, tools: list[ToolDefinition]):
        self._tools = {tool.resource_id: tool for tool in tools}

    async def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    async def execute_tool(self, resource_id: str, arguments: dict[str, Any]) -> Any:
        tool = self._tools[resource_id]
        return await _invoke_tool(tool, arguments)


class MCPToolProvider:
    """Provider that exposes LangChain MCP tools through the gateway boundary."""

    def __init__(self, *, source: str = "mcp"):
        self.source = source
        self._tools_by_id: dict[str, Any] = {}

    async def list_tools(self) -> list[ToolDefinition]:
        raw_tools = await get_mcp_tools_with_retry()
        definitions: list[ToolDefinition] = []
        self._tools_by_id = {}
        for raw_tool in raw_tools:
            name = str(getattr(raw_tool, "name", raw_tool))
            description = str(getattr(raw_tool, "description", ""))
            resource_id = name
            self._tools_by_id[resource_id] = raw_tool
            definitions.append(
                ToolDefinition(
                    resource_id=resource_id,
                    name=name,
                    description=description,
                    source=self.source,
                    raw_tool=raw_tool,
                    metadata={"provider": self.source},
                )
            )
        return definitions

    async def execute_tool(self, resource_id: str, arguments: dict[str, Any]) -> Any:
        return await _invoke_raw_tool(self._tools_by_id[resource_id], arguments)


async def _invoke_tool(tool: ToolDefinition, arguments: dict[str, Any]) -> Any:
    if tool.handler is not None:
        result = tool.handler(arguments)
        if inspect.isawaitable(result):
            return await result
        return result

    if tool.raw_tool is not None:
        return await _invoke_raw_tool(tool.raw_tool, arguments)

    raise RuntimeError(f"Tool {tool.resource_id} has no executable handler")


async def _invoke_raw_tool(raw_tool: Any, arguments: dict[str, Any]) -> Any:
    if getattr(raw_tool, "response_format", "") == "content_and_artifact":
        raw_callable = getattr(raw_tool, "coroutine", None) or getattr(raw_tool, "func", None)
        if raw_callable is not None:
            result = raw_callable(**arguments)
            if inspect.isawaitable(result):
                return await result
            return result
    if hasattr(raw_tool, "ainvoke"):
        return await raw_tool.ainvoke(arguments)
    if hasattr(raw_tool, "invoke"):
        result = raw_tool.invoke(arguments)
        if inspect.isawaitable(result):
            return await result
        return result
    if callable(raw_tool):
        result = raw_tool(arguments)
        if inspect.isawaitable(result):
            return await result
        return result
    raise RuntimeError(f"Tool {getattr(raw_tool, 'name', raw_tool)} is not callable")
