"""Database resource permission helpers for E7."""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from app.enterprise.context import RequestContext
from app.enterprise.database.registry import DatabaseSchemaRegistry
from app.enterprise.permissions.service import PermissionService

DATABASE_TABLE_RESOURCE_TYPE = "database_table"
DATABASE_COLUMN_RESOURCE_TYPE = "database_column"
DATABASE_OPERATION_RESOURCE_TYPE = "database_operation"
DATABASE_READ_ACTION = "read"
DATABASE_OPERATION_EXECUTE_ACTION = "execute"


@dataclass(frozen=True)
class SelectPermissionTarget:
    table_name: str
    column_names: list[str]


class DatabasePermissionFilter:
    """Permission checks over the sandbox schema registry.

    SafeSqlKernel remains the SQL safety authority. This helper only decides
    whether a known table/column should be visible to the current request.
    """

    def __init__(
        self,
        *,
        registry: DatabaseSchemaRegistry,
        permission_service: PermissionService,
        dialect: str = "sqlite",
    ):
        self.registry = registry
        self.permission_service = permission_service
        self.dialect = dialect

    def table_resource_id(self, table_name: str) -> str:
        return database_table_resource_id(self.registry.database_id, table_name)

    def column_resource_id(self, table_name: str, column_name: str) -> str:
        return database_column_resource_id(self.registry.database_id, table_name, column_name)

    def is_table_allowed(self, context: RequestContext, table_name: str) -> bool:
        decision = self.permission_service.check(
            context,
            resource_type=DATABASE_TABLE_RESOURCE_TYPE,
            resource_id=self.table_resource_id(table_name),
            action=DATABASE_READ_ACTION,
        )
        return decision.allowed

    def is_column_allowed(
        self,
        context: RequestContext,
        table_name: str,
        column_name: str,
    ) -> bool:
        decision = self.permission_service.check(
            context,
            resource_type=DATABASE_COLUMN_RESOURCE_TYPE,
            resource_id=self.column_resource_id(table_name, column_name),
            action=DATABASE_READ_ACTION,
        )
        return decision.allowed

    def allowed_table_names(self, context: RequestContext) -> list[str]:
        return [
            table_name
            for table_name in self.registry.list_tables()
            if self.is_table_allowed(context, table_name)
        ]

    def allowed_column_names(self, context: RequestContext, table_name: str) -> set[str]:
        table = self.registry.require_table(table_name)
        return {
            self.registry._normalize(column.name)
            for column in table.visible_columns()
            if self.is_column_allowed(context, table.name, column.name)
        }

    def denied_columns(
        self,
        context: RequestContext,
        table_name: str,
        column_names: list[str],
    ) -> list[str]:
        denied: list[str] = []
        for column_name in column_names:
            if not self.is_column_allowed(context, table_name, column_name):
                denied.append(column_name)
        return denied

    def select_target(self, sql: str) -> SelectPermissionTarget | None:
        try:
            statements = sqlglot.parse(sql.strip(), read=self.dialect)
        except Exception:
            return None
        if len(statements) != 1:
            return None
        statement = statements[0]
        if not isinstance(statement, exp.Select):
            return None

        table_names = [self.registry._normalize(table.name) for table in statement.find_all(exp.Table)]
        if len(set(table_names)) != 1:
            return None
        table_name = table_names[0]

        try:
            table = self.registry.require_table(table_name)
        except KeyError:
            return None

        column_names: list[str] = []
        for column in statement.find_all(exp.Column):
            column_name = self.registry._normalize(column.name)
            try:
                self.registry.require_column(table.name, column_name)
            except KeyError:
                return None
            if column_name not in column_names:
                column_names.append(column_name)
        return SelectPermissionTarget(table_name=table.name, column_names=column_names)


def database_table_resource_id(database_id: str, table_name: str) -> str:
    return f"{database_id}.{_normalize_identifier(table_name)}"


def database_column_resource_id(database_id: str, table_name: str, column_name: str) -> str:
    return f"{database_id}.{_normalize_identifier(table_name)}.{_normalize_identifier(column_name)}"


def database_operation_resource_id(database_id: str, operation_type: str) -> str:
    return f"{_normalize_identifier(database_id)}.{_normalize_identifier(operation_type)}"


def _normalize_identifier(identifier: str) -> str:
    return identifier.strip().strip('"`[]').lower()
