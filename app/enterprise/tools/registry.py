"""Registry for enterprise tool definitions."""

from __future__ import annotations

from app.enterprise.tools.models import ToolDefinition


class ToolRegistry:
    def __init__(self, *, include_database_tools: bool = False):
        self.include_database_tools = include_database_tools
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> ToolDefinition:
        self._tools[tool.resource_id] = tool
        return tool

    def register_many(self, tools: list[ToolDefinition]) -> list[ToolDefinition]:
        for tool in tools:
            self.register(tool)
        return self.list_all()

    def list_all(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def list_exposable(self) -> list[ToolDefinition]:
        return self.list_all()
