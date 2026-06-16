"""Session-scoped memory store for prompt restoration.

This store is separate from user-visible chat history. It keeps only a
session summary and bounded live tail used by agent prompt construction.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from app.config import config
from app.models.session_memory import SessionMemoryMessage, SessionMemorySnapshot, utc_now


@dataclass(frozen=True)
class SessionMemoryArchive:
    archive_id: str
    session_id: str
    owner_id: str
    summary: str
    messages: list[SessionMemoryMessage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class ToolResultRef:
    result_ref: str
    session_id: str
    owner_id: str
    tool_name: str
    summary: str
    created_at: datetime = field(default_factory=utc_now)

    def prompt_stub(self) -> str:
        return f"[{self.tool_name}] {self.summary} (ref: {self.result_ref})"


@dataclass(frozen=True)
class ToolResultRecord:
    result_ref: str
    session_id: str
    owner_id: str
    tool_name: str
    content: str
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


class SessionMemoryStore(Protocol):
    def upsert_snapshot(self, snapshot: SessionMemorySnapshot) -> SessionMemorySnapshot:
        ...

    def get_snapshot(self, session_id: str, owner_id: str) -> SessionMemorySnapshot | None:
        ...

    def append_live_message(
        self,
        session_id: str,
        owner_id: str,
        *,
        role: str,
        content: str,
        metadata: dict | None = None,
        max_tail: int = 12,
    ) -> SessionMemorySnapshot:
        ...

    def clear(self) -> None:
        ...

    def cleanup_expired(
        self,
        *,
        ttl_seconds: int,
        owner_id: str | None = None,
    ) -> int:
        ...


class InMemorySessionMemoryStore:
    def __init__(self):
        self._snapshots: dict[tuple[str, str], SessionMemorySnapshot] = {}

    def upsert_snapshot(self, snapshot: SessionMemorySnapshot) -> SessionMemorySnapshot:
        normalized = _normalize_snapshot(snapshot)
        self._snapshots[(normalized.session_id, normalized.owner_id)] = normalized
        return normalized

    def get_snapshot(self, session_id: str, owner_id: str) -> SessionMemorySnapshot | None:
        return self._snapshots.get((_require_text(session_id, "session_id"), _require_text(owner_id, "owner_id")))

    def append_live_message(
        self,
        session_id: str,
        owner_id: str,
        *,
        role: str,
        content: str,
        metadata: dict | None = None,
        max_tail: int = 12,
    ) -> SessionMemorySnapshot:
        session_id = _require_text(session_id, "session_id")
        owner_id = _require_text(owner_id, "owner_id")
        existing = self.get_snapshot(session_id, owner_id)
        now = utc_now()
        message = SessionMemoryMessage(
            role=_require_text(role, "role"),
            content=_require_text(content, "content"),
            metadata=metadata or {},
            created_at=now,
        )
        snapshot = SessionMemorySnapshot(
            session_id=session_id,
            owner_id=owner_id,
            latest_summary=existing.latest_summary if existing else "",
            live_tail=_bounded_tail([*(existing.live_tail if existing else []), message], max_tail),
            metadata=existing.metadata if existing else {},
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        return self.upsert_snapshot(snapshot)

    def clear(self) -> None:
        self._snapshots.clear()

    def cleanup_expired(
        self,
        *,
        ttl_seconds: int,
        owner_id: str | None = None,
    ) -> int:
        ttl_seconds = _require_positive_int(ttl_seconds, "ttl_seconds")
        cutoff = utc_now() - timedelta(seconds=ttl_seconds)
        removed = 0
        for key, snapshot in list(self._snapshots.items()):
            if owner_id is not None and key[1] != _require_text(owner_id, "owner_id"):
                continue
            if snapshot.updated_at < cutoff:
                del self._snapshots[key]
                removed += 1
        return removed


class SQLiteSessionMemoryStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or config.enterprise_chat_session_sqlite_path)
        self._initialized = False

    def upsert_snapshot(self, snapshot: SessionMemorySnapshot) -> SessionMemorySnapshot:
        normalized = _normalize_snapshot(snapshot)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                self._init_schema(connection)
                connection.execute(
                    """
                    INSERT INTO session_memory_snapshots (
                        session_id,
                        owner_id,
                        latest_summary,
                        live_tail_json,
                        metadata_json,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id, owner_id) DO UPDATE SET
                        latest_summary = excluded.latest_summary,
                        live_tail_json = excluded.live_tail_json,
                        metadata_json = excluded.metadata_json,
                        updated_at = excluded.updated_at
                    """,
                    _snapshot_row(normalized),
                )
        return normalized

    def get_snapshot(self, session_id: str, owner_id: str) -> SessionMemorySnapshot | None:
        if not self.path.exists():
            return None
        session_id = _require_text(session_id, "session_id")
        owner_id = _require_text(owner_id, "owner_id")
        with closing(sqlite3.connect(self.path)) as connection:
            self._init_schema(connection)
            row = connection.execute(
                """
                SELECT
                    session_id,
                    owner_id,
                    latest_summary,
                    live_tail_json,
                    metadata_json,
                    created_at,
                    updated_at
                FROM session_memory_snapshots
                WHERE session_id = ? AND owner_id = ?
                """,
                (session_id, owner_id),
            ).fetchone()
        return _snapshot_from_row(row) if row else None

    def append_live_message(
        self,
        session_id: str,
        owner_id: str,
        *,
        role: str,
        content: str,
        metadata: dict | None = None,
        max_tail: int = 12,
    ) -> SessionMemorySnapshot:
        session_id = _require_text(session_id, "session_id")
        owner_id = _require_text(owner_id, "owner_id")
        existing = self.get_snapshot(session_id, owner_id)
        now = utc_now()
        message = SessionMemoryMessage(
            role=_require_text(role, "role"),
            content=_require_text(content, "content"),
            metadata=metadata or {},
            created_at=now,
        )
        snapshot = SessionMemorySnapshot(
            session_id=session_id,
            owner_id=owner_id,
            latest_summary=existing.latest_summary if existing else "",
            live_tail=_bounded_tail([*(existing.live_tail if existing else []), message], max_tail),
            metadata=existing.metadata if existing else {},
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        return self.upsert_snapshot(snapshot)

    def clear(self) -> None:
        if not self.path.exists():
            return
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                self._init_schema(connection)
                connection.execute("DELETE FROM session_memory_snapshots")
                connection.execute("DELETE FROM session_memory_archives")

    def cleanup_expired(
        self,
        *,
        ttl_seconds: int,
        owner_id: str | None = None,
    ) -> int:
        ttl_seconds = _require_positive_int(ttl_seconds, "ttl_seconds")
        if not self.path.exists():
            return 0
        cutoff = (utc_now() - timedelta(seconds=ttl_seconds)).isoformat()
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                self._init_schema(connection)
                if owner_id is None:
                    snapshots = connection.execute(
                        "DELETE FROM session_memory_snapshots WHERE updated_at < ?",
                        (cutoff,),
                    )
                    archives = connection.execute(
                        "DELETE FROM session_memory_archives WHERE created_at < ?",
                        (cutoff,),
                    )
                else:
                    owner_id = _require_text(owner_id, "owner_id")
                    snapshots = connection.execute(
                        """
                        DELETE FROM session_memory_snapshots
                        WHERE owner_id = ? AND updated_at < ?
                        """,
                        (owner_id, cutoff),
                    )
                    archives = connection.execute(
                        """
                        DELETE FROM session_memory_archives
                        WHERE owner_id = ? AND created_at < ?
                        """,
                        (owner_id, cutoff),
                    )
        return int(snapshots.rowcount or 0) + int(archives.rowcount or 0)

    def archive_live_tail(
        self,
        session_id: str,
        owner_id: str,
        *,
        keep_tail: int,
        archive_summary: str,
        archive_metadata: dict | None = None,
    ) -> SessionMemoryArchive:
        session_id = _require_text(session_id, "session_id")
        owner_id = _require_text(owner_id, "owner_id")
        summary = _require_text(archive_summary, "archive_summary")
        snapshot = self.get_snapshot(session_id, owner_id)
        now = utc_now()
        tail = list(snapshot.live_tail if snapshot else [])
        keep_tail = max(0, int(keep_tail))
        archived_messages = tail[:-keep_tail] if keep_tail else tail
        kept_messages = tail[-keep_tail:] if keep_tail else []
        archive = SessionMemoryArchive(
            archive_id=f"session_archive:{uuid4().hex}",
            session_id=session_id,
            owner_id=owner_id,
            summary=summary,
            messages=archived_messages,
            metadata=archive_metadata or {},
            created_at=now,
        )
        updated_snapshot = SessionMemorySnapshot(
            session_id=session_id,
            owner_id=owner_id,
            latest_summary=_merge_summary(snapshot.latest_summary if snapshot else "", summary),
            live_tail=kept_messages,
            metadata=snapshot.metadata if snapshot else {},
            created_at=snapshot.created_at if snapshot else now,
            updated_at=now,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                self._init_schema(connection)
                connection.execute(
                    """
                    INSERT INTO session_memory_archives (
                        archive_id,
                        session_id,
                        owner_id,
                        summary,
                        messages_json,
                        metadata_json,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    _archive_row(archive),
                )
                connection.execute(
                    """
                    INSERT INTO session_memory_snapshots (
                        session_id,
                        owner_id,
                        latest_summary,
                        live_tail_json,
                        metadata_json,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id, owner_id) DO UPDATE SET
                        latest_summary = excluded.latest_summary,
                        live_tail_json = excluded.live_tail_json,
                        metadata_json = excluded.metadata_json,
                        updated_at = excluded.updated_at
                    """,
                    _snapshot_row(updated_snapshot),
                )
        return archive

    def list_archives(self, session_id: str, owner_id: str) -> list[SessionMemoryArchive]:
        if not self.path.exists():
            return []
        session_id = _require_text(session_id, "session_id")
        owner_id = _require_text(owner_id, "owner_id")
        with closing(sqlite3.connect(self.path)) as connection:
            self._init_schema(connection)
            rows = connection.execute(
                """
                SELECT
                    archive_id,
                    session_id,
                    owner_id,
                    summary,
                    messages_json,
                    metadata_json,
                    created_at
                FROM session_memory_archives
                WHERE session_id = ? AND owner_id = ?
                ORDER BY created_at
                """,
                (session_id, owner_id),
            ).fetchall()
        return [_archive_from_row(row) for row in rows]

    def _init_schema(self, connection: sqlite3.Connection) -> None:
        if self._initialized:
            return
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS session_memory_snapshots (
                session_id TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                latest_summary TEXT NOT NULL,
                live_tail_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (session_id, owner_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_session_memory_owner_updated
            ON session_memory_snapshots(owner_id, updated_at)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS session_memory_archives (
                archive_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                messages_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_session_memory_archives_session
            ON session_memory_archives(session_id, owner_id, created_at)
            """
        )
        self._initialized = True


class SessionToolResultOffloadStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or config.enterprise_chat_session_sqlite_path)
        self._initialized = False

    def offload_result(
        self,
        *,
        session_id: str,
        owner_id: str,
        tool_name: str,
        content: str,
        summary: str,
        metadata: dict | None = None,
    ) -> ToolResultRef:
        record = ToolResultRecord(
            result_ref=f"tool_result:{uuid4().hex}",
            session_id=_require_text(session_id, "session_id"),
            owner_id=_require_text(owner_id, "owner_id"),
            tool_name=_require_text(tool_name, "tool_name"),
            content=_require_nonempty_text_preserving(content, "content"),
            summary=_require_text(summary, "summary"),
            metadata=metadata or {},
            created_at=utc_now(),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                self._init_schema(connection)
                connection.execute(
                    """
                    INSERT INTO session_tool_result_offloads (
                        result_ref,
                        session_id,
                        owner_id,
                        tool_name,
                        content,
                        summary,
                        metadata_json,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _tool_result_row(record),
                )
        return ToolResultRef(
            result_ref=record.result_ref,
            session_id=record.session_id,
            owner_id=record.owner_id,
            tool_name=record.tool_name,
            summary=record.summary,
            created_at=record.created_at,
        )

    def get_result(self, result_ref: str, *, owner_id: str) -> ToolResultRecord | None:
        if not self.path.exists():
            return None
        result_ref = _require_text(result_ref, "result_ref")
        owner_id = _require_text(owner_id, "owner_id")
        with closing(sqlite3.connect(self.path)) as connection:
            self._init_schema(connection)
            row = connection.execute(
                """
                SELECT
                    result_ref,
                    session_id,
                    owner_id,
                    tool_name,
                    content,
                    summary,
                    metadata_json,
                    created_at
                FROM session_tool_result_offloads
                WHERE result_ref = ? AND owner_id = ?
                """,
                (result_ref, owner_id),
            ).fetchone()
        return _tool_result_from_row(row) if row else None

    def cleanup_expired(
        self,
        *,
        ttl_seconds: int,
        owner_id: str | None = None,
    ) -> int:
        ttl_seconds = _require_positive_int(ttl_seconds, "ttl_seconds")
        if not self.path.exists():
            return 0
        cutoff = (utc_now() - timedelta(seconds=ttl_seconds)).isoformat()
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                self._init_schema(connection)
                if owner_id is None:
                    cursor = connection.execute(
                        "DELETE FROM session_tool_result_offloads WHERE created_at < ?",
                        (cutoff,),
                    )
                else:
                    owner_id = _require_text(owner_id, "owner_id")
                    cursor = connection.execute(
                        """
                        DELETE FROM session_tool_result_offloads
                        WHERE owner_id = ? AND created_at < ?
                        """,
                        (owner_id, cutoff),
                    )
        return int(cursor.rowcount or 0)

    def _init_schema(self, connection: sqlite3.Connection) -> None:
        if self._initialized:
            return
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS session_tool_result_offloads (
                result_ref TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                content TEXT NOT NULL,
                summary TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_session_tool_result_owner
            ON session_tool_result_offloads(owner_id, session_id, created_at)
            """
        )
        self._initialized = True


def _normalize_snapshot(snapshot: SessionMemorySnapshot) -> SessionMemorySnapshot:
    return SessionMemorySnapshot(
        session_id=_require_text(snapshot.session_id, "session_id"),
        owner_id=_require_text(snapshot.owner_id, "owner_id"),
        latest_summary=snapshot.latest_summary or "",
        live_tail=list(snapshot.live_tail),
        metadata=snapshot.metadata or {},
        created_at=snapshot.created_at,
        updated_at=snapshot.updated_at,
    )


def _bounded_tail(messages: list[SessionMemoryMessage], max_tail: int) -> list[SessionMemoryMessage]:
    max_tail = max(0, int(max_tail))
    if max_tail == 0:
        return []
    return messages[-max_tail:]


def _snapshot_row(snapshot: SessionMemorySnapshot) -> tuple:
    return (
        snapshot.session_id,
        snapshot.owner_id,
        snapshot.latest_summary,
        json.dumps([message.to_payload() for message in snapshot.live_tail], ensure_ascii=False),
        json.dumps(snapshot.metadata, ensure_ascii=False, sort_keys=True),
        snapshot.created_at.isoformat(),
        snapshot.updated_at.isoformat(),
    )


def _snapshot_from_row(row) -> SessionMemorySnapshot:
    live_tail = [
        SessionMemoryMessage(
            role=item["role"],
            content=item["content"],
            metadata=item.get("metadata") or {},
            created_at=datetime.fromisoformat(item["created_at"]),
        )
        for item in json.loads(row[3] or "[]")
    ]
    return SessionMemorySnapshot(
        session_id=row[0],
        owner_id=row[1],
        latest_summary=row[2],
        live_tail=live_tail,
        metadata=json.loads(row[4] or "{}"),
        created_at=datetime.fromisoformat(row[5]),
        updated_at=datetime.fromisoformat(row[6]),
    )


def _archive_row(archive: SessionMemoryArchive) -> tuple:
    return (
        archive.archive_id,
        archive.session_id,
        archive.owner_id,
        archive.summary,
        json.dumps([message.to_payload() for message in archive.messages], ensure_ascii=False),
        json.dumps(archive.metadata, ensure_ascii=False, sort_keys=True),
        archive.created_at.isoformat(),
    )


def _archive_from_row(row) -> SessionMemoryArchive:
    return SessionMemoryArchive(
        archive_id=row[0],
        session_id=row[1],
        owner_id=row[2],
        summary=row[3],
        messages=_messages_from_json(row[4]),
        metadata=json.loads(row[5] or "{}"),
        created_at=datetime.fromisoformat(row[6]),
    )


def _messages_from_json(payload: str) -> list[SessionMemoryMessage]:
    return [
        SessionMemoryMessage(
            role=item["role"],
            content=item["content"],
            metadata=item.get("metadata") or {},
            created_at=datetime.fromisoformat(item["created_at"]),
        )
        for item in json.loads(payload or "[]")
    ]


def _tool_result_row(record: ToolResultRecord) -> tuple:
    return (
        record.result_ref,
        record.session_id,
        record.owner_id,
        record.tool_name,
        record.content,
        record.summary,
        json.dumps(record.metadata, ensure_ascii=False, sort_keys=True),
        record.created_at.isoformat(),
    )


def _tool_result_from_row(row) -> ToolResultRecord:
    return ToolResultRecord(
        result_ref=row[0],
        session_id=row[1],
        owner_id=row[2],
        tool_name=row[3],
        content=row[4],
        summary=row[5],
        metadata=json.loads(row[6] or "{}"),
        created_at=datetime.fromisoformat(row[7]),
    )


def _merge_summary(existing: str, addition: str) -> str:
    existing = (existing or "").strip()
    addition = (addition or "").strip()
    if existing and addition:
        return f"{existing}\n\n{addition}"
    return existing or addition


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _require_nonempty_text_preserving(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value


def _require_positive_int(value: int, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return parsed
