"""Schema registry for the E6 sandbox database."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ColumnPolicy:
    name: str
    data_type: str
    allowed: bool = True
    sensitive: bool = False
    mask: str | None = None
    description: str = ""

    def to_visible_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "data_type": self.data_type,
            "sensitive": self.sensitive,
            "mask": self.mask,
            "description": self.description,
        }


@dataclass(frozen=True)
class TablePolicy:
    name: str
    description: str
    columns: dict[str, ColumnPolicy]
    allowed: bool = True
    max_rows: int = 100
    metadata: dict[str, Any] = field(default_factory=dict)

    def visible_columns(self) -> list[ColumnPolicy]:
        return [column for column in self.columns.values() if column.allowed]


class DatabaseSchemaRegistry:
    """Local allowlist for database tables and columns.

    The registry is intentionally explicit. Unknown tables and unknown columns are
    denied by default, matching the E6 sandbox safety rule.
    """

    def __init__(self, *, database_id: str, tables: dict[str, TablePolicy]):
        self.database_id = database_id
        self._tables = {self._normalize(name): table for name, table in tables.items()}

    def list_tables(self) -> list[str]:
        return [table.name for table in self._tables.values() if table.allowed]

    def describe_table(self, table_name: str) -> dict[str, Any]:
        table = self.require_table(table_name)
        return {
            "database_id": self.database_id,
            "table_name": table.name,
            "description": table.description,
            "max_rows": table.max_rows,
            "columns": [column.to_visible_dict() for column in table.visible_columns()],
        }

    def require_table(self, table_name: str) -> TablePolicy:
        table = self._tables.get(self._normalize(table_name))
        if table is None or not table.allowed:
            raise KeyError(table_name)
        return table

    def require_column(self, table_name: str, column_name: str) -> ColumnPolicy:
        table = self.require_table(table_name)
        column = table.columns.get(self._normalize(column_name))
        if column is None or not column.allowed:
            raise KeyError(f"{table_name}.{column_name}")
        return column

    def allowed_column_names(self, table_name: str) -> set[str]:
        table = self.require_table(table_name)
        return {self._normalize(column.name) for column in table.visible_columns()}

    def column_policy(self, table_name: str, column_name: str) -> ColumnPolicy:
        return self.require_column(table_name, column_name)

    @staticmethod
    def _normalize(identifier: str) -> str:
        return identifier.strip().strip('"`[]').lower()


def build_default_sandbox_registry() -> DatabaseSchemaRegistry:
    return DatabaseSchemaRegistry(
        database_id="sandbox_sales",
        tables={
            "factory_access_events": TablePolicy(
                name="factory_access_events",
                description="Employee factory gate entry and exit access events.",
                max_rows=100,
                columns={
                    "event_id": ColumnPolicy("event_id", "INTEGER", description="Event id"),
                    "employee_id": ColumnPolicy("employee_id", "TEXT", description="Employee id"),
                    "employee_name": ColumnPolicy(
                        "employee_name",
                        "TEXT",
                        sensitive=True,
                        mask="name",
                        description="Employee name, masked in results",
                    ),
                    "department_name": ColumnPolicy(
                        "department_name", "TEXT", description="Department name"
                    ),
                    "direction": ColumnPolicy(
                        "direction", "TEXT", description="Access direction: entry or exit"
                    ),
                    "gate_name": ColumnPolicy("gate_name", "TEXT", description="Factory gate name"),
                    "event_time": ColumnPolicy("event_time", "TEXT", description="Event timestamp"),
                    "badge_id": ColumnPolicy(
                        "badge_id",
                        "TEXT",
                        sensitive=True,
                        mask="badge",
                        description="Badge id, masked in results",
                    ),
                    "raw_device_payload": ColumnPolicy(
                        "raw_device_payload",
                        "TEXT",
                        allowed=False,
                        sensitive=True,
                        mask="redact",
                        description="Raw device payload, not exposed to demo users",
                    ),
                },
            ),
            "building_access_events": TablePolicy(
                name="building_access_events",
                description="Employee building and floor access events.",
                max_rows=100,
                columns={
                    "event_id": ColumnPolicy("event_id", "INTEGER", description="Event id"),
                    "employee_id": ColumnPolicy("employee_id", "TEXT", description="Employee id"),
                    "employee_name": ColumnPolicy(
                        "employee_name",
                        "TEXT",
                        sensitive=True,
                        mask="name",
                        description="Employee name, masked in results",
                    ),
                    "department_name": ColumnPolicy(
                        "department_name", "TEXT", description="Department name"
                    ),
                    "building_name": ColumnPolicy("building_name", "TEXT", description="Building name"),
                    "floor_name": ColumnPolicy("floor_name", "TEXT", description="Floor name"),
                    "direction": ColumnPolicy(
                        "direction", "TEXT", description="Access direction: entry or exit"
                    ),
                    "access_point_name": ColumnPolicy(
                        "access_point_name", "TEXT", description="Access point name"
                    ),
                    "event_time": ColumnPolicy("event_time", "TEXT", description="Event timestamp"),
                    "device_id": ColumnPolicy(
                        "device_id",
                        "TEXT",
                        sensitive=True,
                        mask="redact",
                        description="Device id, masked in results",
                    ),
                    "raw_device_payload": ColumnPolicy(
                        "raw_device_payload",
                        "TEXT",
                        allowed=False,
                        sensitive=True,
                        mask="redact",
                        description="Raw device payload, not exposed to demo users",
                    ),
                },
            ),
        },
    )
