"""Local audit service shell for E2."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Protocol

from loguru import logger

from app.config import config
from app.enterprise.observability.models import AuditEvent


class AuditSink(Protocol):
    def emit(self, event: AuditEvent) -> None:
        ...


class InMemoryAuditSink:
    def __init__(self):
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        self.events.append(event)

    def query(
        self,
        *,
        trace_id: str | None = None,
        request_id: str | None = None,
        user_id: str | None = None,
        event_type: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int | None = None,
    ) -> list[AuditEvent]:
        events = [
            event
            for event in self.events
            if (trace_id is None or event.trace_id == trace_id)
            and (request_id is None or event.request_id == request_id)
            and (user_id is None or event.user_id == user_id)
            and (event_type is None or event.event_type == event_type)
            and (start_time is None or event.timestamp >= start_time)
            and (end_time is None or event.timestamp <= end_time)
        ]
        return events[-limit:] if limit is not None else events


class JsonlAuditSink:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def emit(self, event: AuditEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False))
            file.write("\n")


class SQLiteAuditSink:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._initialized = False

    def emit(self, event: AuditEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                if not self._initialized:
                    self._init_schema(connection)
                    self._initialized = True
                connection.execute(
                    """
                    INSERT INTO enterprise_audit_events (
                        event_id, event_type, route, trace_id, request_id, user_id,
                        timestamp, decision, reason, error_class, error_message,
                        latency_ms, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.event_type,
                        event.route,
                        event.trace_id,
                        event.request_id,
                        event.user_id,
                        event.timestamp.isoformat(),
                        event.decision,
                        event.reason,
                        event.error_class,
                        event.error_message,
                        event.latency_ms,
                        json.dumps(event.metadata, ensure_ascii=False, sort_keys=True),
                    ),
                )

    def query(
        self,
        *,
        trace_id: str | None = None,
        request_id: str | None = None,
        user_id: str | None = None,
        event_type: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int | None = None,
    ) -> list[AuditEvent]:
        if not self.path.exists():
            return []

        clauses: list[str] = []
        params: list[str] = []
        if trace_id is not None:
            clauses.append("trace_id = ?")
            params.append(trace_id)
        if request_id is not None:
            clauses.append("request_id = ?")
            params.append(request_id)
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        if start_time is not None:
            clauses.append("timestamp >= ?")
            params.append(start_time.isoformat())
        if end_time is not None:
            clauses.append("timestamp <= ?")
            params.append(end_time.isoformat())

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT
                event_id, event_type, route, trace_id, request_id, user_id,
                timestamp, decision, reason, error_class, error_message,
                latency_ms, metadata_json
            FROM enterprise_audit_events
            {where_sql}
            ORDER BY timestamp ASC
        """
        with closing(sqlite3.connect(self.path)) as connection:
            self._init_schema(connection)
            rows = connection.execute(query, params).fetchall()
        if limit is not None:
            rows = rows[-limit:]
        return [self._row_to_event(row) for row in rows]

    def _init_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS enterprise_audit_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                route TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                decision TEXT,
                reason TEXT,
                error_class TEXT,
                error_message TEXT,
                latency_ms REAL,
                metadata_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_enterprise_audit_events_trace_id
            ON enterprise_audit_events (trace_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_enterprise_audit_events_trace_timestamp
            ON enterprise_audit_events (trace_id, timestamp)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_enterprise_audit_events_request_id
            ON enterprise_audit_events (request_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_enterprise_audit_events_request_timestamp
            ON enterprise_audit_events (request_id, timestamp)
            """
        )

    def _row_to_event(self, row: sqlite3.Row | tuple) -> AuditEvent:
        return AuditEvent(
            event_id=row[0],
            event_type=row[1],
            route=row[2],
            trace_id=row[3],
            request_id=row[4],
            user_id=row[5],
            timestamp=datetime.fromisoformat(row[6]),
            decision=row[7],
            reason=row[8],
            error_class=row[9],
            error_message=row[10],
            latency_ms=row[11],
            metadata=json.loads(row[12] or "{}"),
        )


class AuditService:
    def __init__(self, sinks: Iterable[AuditSink] | None = None):
        self.sinks = list(sinks) if sinks is not None else self._default_sinks()

    def record(self, event: AuditEvent) -> None:
        for sink in self.sinks:
            try:
                sink.emit(event)
            except Exception as exc:
                logger.warning("Audit sink write failed: {}", exc)

    def query(
        self,
        *,
        trace_id: str | None = None,
        request_id: str | None = None,
        user_id: str | None = None,
        event_type: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int | None = None,
    ) -> list[AuditEvent]:
        for sink in self.sinks:
            query = getattr(sink, "query", None)
            if callable(query):
                return list(
                    query(
                        trace_id=trace_id,
                        request_id=request_id,
                        user_id=user_id,
                        event_type=event_type,
                        start_time=start_time,
                        end_time=end_time,
                        limit=limit,
                    )
                )
        return []

    def _default_sinks(self) -> list[AuditSink]:
        return [
            SQLiteAuditSink(config.enterprise_audit_sqlite_path),
            JsonlAuditSink(config.enterprise_audit_jsonl_path),
        ]
