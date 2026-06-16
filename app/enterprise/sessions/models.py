"""Persistent chat session models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ChatSessionRecord:
    session_id: str
    user_id: str
    title: str
    kind: str = "chat"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    archived_at: datetime | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "title": self.title,
            "kind": self.kind,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
        }


@dataclass(frozen=True)
class ChatMessageRecord:
    session_id: str
    user_id: str
    role: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    message_id: str = field(default_factory=lambda: f"msg_{uuid4().hex}")
    created_at: datetime = field(default_factory=utc_now)

    def to_payload(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "role": self.role,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }
