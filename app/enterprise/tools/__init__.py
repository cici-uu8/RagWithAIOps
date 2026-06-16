"""Enterprise tool gateway package."""

from app.enterprise.tools.facade import ToolExecutionFacade, tool_execution_facade
from app.enterprise.tools.gateway import ToolAccessDenied, ToolExecutionError, ToolGateway
from app.enterprise.tools.models import ToolDefinition
from app.enterprise.tools.providers import MCPToolProvider, StaticToolProvider, ToolProvider
from app.enterprise.tools.registry import ToolRegistry
from app.enterprise.tools.schema import (
    openai_function_name,
    to_openai_function_tool,
    to_openai_function_tools,
)

__all__ = [
    "MCPToolProvider",
    "LocalAgentToolProvider",
    "StaticToolProvider",
    "ToolAccessDenied",
    "ToolDefinition",
    "ToolExecutionError",
    "ToolExecutionFacade",
    "ToolGateway",
    "ToolProvider",
    "ToolRegistry",
    "openai_function_name",
    "to_openai_function_tool",
    "to_openai_function_tools",
    "tool_execution_facade",
]


def __getattr__(name: str):
    if name == "LocalAgentToolProvider":
        from app.enterprise.tools.local_provider import LocalAgentToolProvider

        return LocalAgentToolProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
