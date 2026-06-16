"""Read-only query helpers for database audit events."""

from __future__ import annotations

from collections.abc import Iterable

from app.enterprise.observability.models import AuditEvent


class DatabaseAuditQueryService:
    def __init__(self, *, events: Iterable[AuditEvent]):
        self.events = events

    def query(
        self,
        *,
        trace_id: str | None = None,
        user_id: str | None = None,
        table_name: str | None = None,
    ) -> list[AuditEvent]:
        return [
            event
            for event in self.events
            if event.event_type == "database_query"
            and (trace_id is None or event.trace_id == trace_id)
            and (user_id is None or event.user_id == user_id)
            and _matches_table(event, table_name)
        ]


def _matches_table(event: AuditEvent, table_name: str | None) -> bool:
    if table_name is None:
        return True
    expected = _normalize_identifier(table_name)
    target_tables = event.metadata.get("target_tables") or []
    return expected in {_normalize_identifier(str(target)) for target in target_tables}


def _normalize_identifier(identifier: str) -> str:
    return identifier.strip().strip('"`[]').lower()
