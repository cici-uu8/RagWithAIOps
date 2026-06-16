"""Models for enterprise tool governance."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

ToolHandler = Callable[[dict[str, Any]], Any | Awaitable[Any]]


@dataclass(frozen=True)
class ToolDefinition:
    resource_id: str
    name: str
    description: str = ""
    source: str = "local"
    handler: ToolHandler | None = None
    raw_tool: Any | None = None
    input_schema: dict[str, Any] | None = None
    strict: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def bindable_tool(self) -> Any:
        return self.raw_tool if self.raw_tool is not None else self

    @property
    def is_database_tool(self) -> bool:
        category = self.metadata.get("category")
        return category == "database" or self.source.startswith("database")
