"""Schema helpers for model-callable enterprise tools."""

from __future__ import annotations

import copy
import hashlib
import re
from typing import Any

from app.enterprise.tools.models import ToolDefinition

_OPENAI_FUNCTION_NAME_MAX_LENGTH = 64
_OPENAI_FUNCTION_NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")


def openai_function_name(tool: ToolDefinition) -> str:
    """Return a stable OpenAI-compatible function name for a tool resource."""

    configured_name = tool.metadata.get("openai_function_name")
    raw_name = str(configured_name or tool.resource_id)
    name = _OPENAI_FUNCTION_NAME_RE.sub("_", raw_name).strip("_")
    name = re.sub(r"_+", "_", name) or "tool"
    if len(name) <= _OPENAI_FUNCTION_NAME_MAX_LENGTH:
        return name

    digest = hashlib.sha256(raw_name.encode("utf-8")).hexdigest()[:8]
    prefix_length = _OPENAI_FUNCTION_NAME_MAX_LENGTH - len(digest) - 1
    return f"{name[:prefix_length]}_{digest}"


def to_openai_function_tool(tool: ToolDefinition) -> dict[str, Any]:
    """Convert a ToolDefinition into OpenAI chat-completions function tool shape."""

    parameters = _normalized_parameters(tool.input_schema, strict=tool.strict)
    return {
        "type": "function",
        "function": {
            "name": openai_function_name(tool),
            "description": tool.description,
            "parameters": parameters,
            "strict": tool.strict,
        },
    }


def to_openai_function_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [to_openai_function_tool(tool) for tool in tools]


def _normalized_parameters(
    input_schema: dict[str, Any] | None,
    *,
    strict: bool,
) -> dict[str, Any]:
    parameters = copy.deepcopy(input_schema) if input_schema is not None else {}
    parameters.setdefault("type", "object")
    parameters.setdefault("properties", {})
    parameters.setdefault("required", [])
    if strict and parameters.get("type") == "object":
        parameters.setdefault("additionalProperties", False)
    return parameters
