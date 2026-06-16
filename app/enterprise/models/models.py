"""Models for enterprise model routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelEndpoint:
    endpoint_id: str
    model_name: str
    provider_name: str
    priority: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelRequest:
    messages: list[Any]
    endpoint_id: str | None = None
    temperature: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelResponse:
    content: Any
    usage: dict[str, Any] = field(default_factory=dict)
    raw_response: Any | None = None
    endpoint_id: str | None = None
    model_name: str | None = None
    provider_name: str | None = None
    fallback_used: bool = False
    status: str = "success"
    metadata: dict[str, Any] = field(default_factory=dict)
