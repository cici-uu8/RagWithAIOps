"""Session-scoped memory models for prompt restoration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class SessionMemoryMessage:
    role: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def to_payload(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class SessionMemorySnapshot:
    session_id: str
    owner_id: str
    latest_summary: str = ""
    live_tail: list[SessionMemoryMessage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def to_prompt_context(self) -> str:
        parts: list[str] = []
        if self.latest_summary.strip():
            parts.append(f"会话摘要:\n{self.latest_summary.strip()}")
        if self.live_tail:
            tail = "\n".join(
                f"{message.role}: {message.content}"
                for message in self.live_tail
                if message.content.strip()
            )
            if tail:
                parts.append(f"最近会话:\n{tail}")
        return "\n\n".join(parts)
