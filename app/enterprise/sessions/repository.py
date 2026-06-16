"""Repositories for persistent chat sessions."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Protocol

from app.config import config
from app.enterprise.sessions.models import ChatMessageRecord, ChatSessionRecord, utc_now


class ChatSessionRepository(Protocol):
    def create_or_touch(
        self,
        session_id: str,
        user_id: str,
        *,
        kind: str = "chat",
        title: str | None = None,
    ) -> ChatSessionRecord:
        ...

    def get(self, session_id: str) -> ChatSessionRecord | None:
        ...

    def append_message(
        self,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> ChatMessageRecord:
        ...

    def list_by_user(self, user_id: str) -> list[ChatSessionRecord]:
        ...

    def get_messages(self, session_id: str, user_id: str) -> list[ChatMessageRecord]:
        ...

    def archive(self, session_id: str, user_id: str) -> bool:
        ...

    def clear(self) -> None:
        ...


class InMemoryChatSessionRepository:
    def __init__(self):
        self._sessions: dict[str, ChatSessionRecord] = {}
        self._messages: dict[str, list[ChatMessageRecord]] = {}

    def create_or_touch(
        self,
        session_id: str,
        user_id: str,
        *,
        kind: str = "chat",
        title: str | None = None,
    ) -> ChatSessionRecord:
        existing = self._sessions.get(session_id)
        now = utc_now()
        if existing is None:
            record = ChatSessionRecord(
                session_id=session_id,
                user_id=user_id,
                title=_title_or_default(title),
                kind=kind,
                created_at=now,
                updated_at=now,
            )
        else:
            record = ChatSessionRecord(
                session_id=existing.session_id,
                user_id=existing.user_id,
                title=existing.title,
                kind=existing.kind,
                created_at=existing.created_at,
                updated_at=now,
                archived_at=None,
            )
        self._sessions[session_id] = record
        return record

    def get(self, session_id: str) -> ChatSessionRecord | None:
        return self._sessions.get(session_id)

    def append_message(
        self,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> ChatMessageRecord:
        message = ChatMessageRecord(
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
            metadata=metadata or {},
        )
        self._messages.setdefault(session_id, []).append(message)
        session = self._sessions.get(session_id)
        if session is not None:
            self._sessions[session_id] = ChatSessionRecord(
                session_id=session.session_id,
                user_id=session.user_id,
                title=session.title,
                kind=session.kind,
                created_at=session.created_at,
                updated_at=message.created_at,
                archived_at=session.archived_at,
            )
        return message

    def list_by_user(self, user_id: str) -> list[ChatSessionRecord]:
        return sorted(
            [
                session
                for session in self._sessions.values()
                if session.user_id == user_id and session.archived_at is None
            ],
            key=lambda session: session.updated_at,
            reverse=True,
        )

    def get_messages(self, session_id: str, user_id: str) -> list[ChatMessageRecord]:
        session = self._sessions.get(session_id)
        if session is None or session.user_id != user_id or session.archived_at is not None:
            return []
        return list(self._messages.get(session_id, []))

    def archive(self, session_id: str, user_id: str) -> bool:
        session = self._sessions.get(session_id)
        if session is None or session.user_id != user_id:
            return False
        self._sessions[session_id] = ChatSessionRecord(
            session_id=session.session_id,
            user_id=session.user_id,
            title=session.title,
            kind=session.kind,
            created_at=session.created_at,
            updated_at=utc_now(),
            archived_at=utc_now(),
        )
        return True

    def clear(self) -> None:
        self._sessions.clear()
        self._messages.clear()


class SQLiteChatSessionRepository:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or config.enterprise_chat_session_sqlite_path)
        self._initialized = False

    def create_or_touch(
        self,
        session_id: str,
        user_id: str,
        *,
        kind: str = "chat",
        title: str | None = None,
    ) -> ChatSessionRecord:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        now = utc_now()
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                self._init_schema(connection)
                row = connection.execute(
                    """
                    SELECT session_id, user_id, title, kind, created_at, updated_at, archived_at
                    FROM chat_sessions
                    WHERE session_id = ?
                    """,
                    (session_id,),
                ).fetchone()
                if row is None:
                    record = ChatSessionRecord(
                        session_id=session_id,
                        user_id=user_id,
                        title=_title_or_default(title),
                        kind=kind,
                        created_at=now,
                        updated_at=now,
                    )
                    connection.execute(
                        """
                        INSERT INTO chat_sessions (
                            session_id, user_id, title, kind, created_at, updated_at, archived_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        _session_row(record),
                    )
                else:
                    existing = _session_from_row(row)
                    record = ChatSessionRecord(
                        session_id=existing.session_id,
                        user_id=existing.user_id,
                        title=existing.title,
                        kind=existing.kind,
                        created_at=existing.created_at,
                        updated_at=now,
                        archived_at=None,
                    )
                    connection.execute(
                        """
                        UPDATE chat_sessions
                        SET updated_at = ?, archived_at = ?
                        WHERE session_id = ?
                        """,
                        (
                            record.updated_at.isoformat(),
                            record.archived_at.isoformat() if record.archived_at else None,
                            record.session_id,
                        ),
                    )
        return record

    def get(self, session_id: str) -> ChatSessionRecord | None:
        if not self.path.exists():
            return None
        with closing(sqlite3.connect(self.path)) as connection:
            self._init_schema(connection)
            row = connection.execute(
                """
                SELECT session_id, user_id, title, kind, created_at, updated_at, archived_at
                FROM chat_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        return _session_from_row(row) if row else None

    def append_message(
        self,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> ChatMessageRecord:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        message = ChatMessageRecord(
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
            metadata=metadata or {},
        )
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                self._init_schema(connection)
                connection.execute(
                    """
                    INSERT INTO chat_messages (
                        message_id, session_id, user_id, role, content, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message.message_id,
                        message.session_id,
                        message.user_id,
                        message.role,
                        message.content,
                        json.dumps(message.metadata, ensure_ascii=False, sort_keys=True),
                        message.created_at.isoformat(),
                    ),
                )
                connection.execute(
                    """
                    UPDATE chat_sessions
                    SET updated_at = ?
                    WHERE session_id = ?
                    """,
                    (message.created_at.isoformat(), session_id),
                )
        return message

    def list_by_user(self, user_id: str) -> list[ChatSessionRecord]:
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(self.path)) as connection:
            self._init_schema(connection)
            rows = connection.execute(
                """
                SELECT session_id, user_id, title, kind, created_at, updated_at, archived_at
                FROM chat_sessions
                WHERE user_id = ? AND archived_at IS NULL
                ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [_session_from_row(row) for row in rows]

    def get_messages(self, session_id: str, user_id: str) -> list[ChatMessageRecord]:
        session = self.get(session_id)
        if session is None or session.user_id != user_id or session.archived_at is not None:
            return []
        with closing(sqlite3.connect(self.path)) as connection:
            self._init_schema(connection)
            rows = connection.execute(
                """
                SELECT message_id, session_id, user_id, role, content, metadata_json, created_at
                FROM chat_messages
                WHERE session_id = ? AND user_id = ?
                ORDER BY created_at ASC
                """,
                (session_id, user_id),
            ).fetchall()
        return [_message_from_row(row) for row in rows]

    def archive(self, session_id: str, user_id: str) -> bool:
        if self.get(session_id) is None:
            return False
        now = utc_now().isoformat()
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                self._init_schema(connection)
                cursor = connection.execute(
                    """
                    UPDATE chat_sessions
                    SET archived_at = ?, updated_at = ?
                    WHERE session_id = ? AND user_id = ?
                    """,
                    (now, now, session_id, user_id),
                )
        return cursor.rowcount > 0

    def clear(self) -> None:
        if not self.path.exists():
            return
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                self._init_schema(connection)
                connection.execute("DELETE FROM chat_messages")
                connection.execute("DELETE FROM chat_sessions")

    def _init_schema(self, connection: sqlite3.Connection) -> None:
        if self._initialized:
            return
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                kind TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                archived_at TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                message_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_updated
            ON chat_sessions(user_id, updated_at)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
            ON chat_messages(session_id, created_at)
            """
        )
        self._initialized = True


def _title_or_default(title: str | None) -> str:
    cleaned = (title or "新对话").strip()
    if not cleaned:
        return "新对话"
    return cleaned[:30] + ("..." if len(cleaned) > 30 else "")


def _session_row(record: ChatSessionRecord) -> tuple:
    return (
        record.session_id,
        record.user_id,
        record.title,
        record.kind,
        record.created_at.isoformat(),
        record.updated_at.isoformat(),
        record.archived_at.isoformat() if record.archived_at else None,
    )


def _session_from_row(row) -> ChatSessionRecord:
    return ChatSessionRecord(
        session_id=row[0],
        user_id=row[1],
        title=row[2],
        kind=row[3],
        created_at=datetime.fromisoformat(row[4]),
        updated_at=datetime.fromisoformat(row[5]),
        archived_at=datetime.fromisoformat(row[6]) if row[6] else None,
    )


def _message_from_row(row) -> ChatMessageRecord:
    return ChatMessageRecord(
        message_id=row[0],
        session_id=row[1],
        user_id=row[2],
        role=row[3],
        content=row[4],
        metadata=json.loads(row[5] or "{}"),
        created_at=datetime.fromisoformat(row[6]),
    )
