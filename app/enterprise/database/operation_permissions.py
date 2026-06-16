"""Permission checks for high-risk database operation preparation."""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from app.enterprise.context import RequestContext
from app.enterprise.database.operation_classifier import (
    DatabaseOperationClassification,
    classify_sql_operation,
)
from app.enterprise.database.permissions import (
    DATABASE_COLUMN_RESOURCE_TYPE,
    DATABASE_OPERATION_EXECUTE_ACTION,
    DATABASE_OPERATION_RESOURCE_TYPE,
    DATABASE_READ_ACTION,
    DATABASE_TABLE_RESOURCE_TYPE,
    database_column_resource_id,
    database_operation_resource_id,
    database_table_resource_id,
)
from app.enterprise.database.registry import DatabaseSchemaRegistry
from app.enterprise.permissions.service import PermissionService


@dataclass(frozen=True)
class DatabaseOperationPermissionResult:
    allowed: bool
    reason: str
    classification: DatabaseOperationClassification
    operation_type: str | None
    operation_resource_id: str | None
    denied_tables: list[str]
    denied_columns: list[str]


@dataclass(frozen=True)
class _ColumnRef:
    table_name: str
    column_name: str


class DatabaseOperationPermissionChecker:
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

    def check_sql(self, context: RequestContext, sql: str) -> DatabaseOperationPermissionResult:
        classification = classify_sql_operation(
            sql,
            database_id=self.registry.database_id,
            dialect=self.dialect,
        )
        operation_type = operation_permission_type(classification)
        operation_resource_id = (
            database_operation_resource_id(self.registry.database_id, operation_type)
            if operation_type is not None
            else None
        )

        if classification.denied_reason is not None:
            return _result(
                classification,
                allowed=False,
                reason=classification.denied_reason,
                operation_type=operation_type,
                operation_resource_id=operation_resource_id,
            )
        if operation_type is None or operation_resource_id is None:
            return _result(
                classification,
                allowed=False,
                reason="operation_not_confirmable",
                operation_type=operation_type,
                operation_resource_id=operation_resource_id,
            )

        operation_decision = self.permission_service.check(
            context,
            resource_type=DATABASE_OPERATION_RESOURCE_TYPE,
            resource_id=operation_resource_id,
            action=DATABASE_OPERATION_EXECUTE_ACTION,
        )
        if not operation_decision.allowed:
            return _result(
                classification,
                allowed=False,
                reason=operation_decision.reason,
                operation_type=operation_type,
                operation_resource_id=operation_resource_id,
            )

        denied_tables = self._denied_tables(context, classification.tables)
        if denied_tables:
            return _result(
                classification,
                allowed=False,
                reason="database_table_denied",
                operation_type=operation_type,
                operation_resource_id=operation_resource_id,
                denied_tables=denied_tables,
            )

        denied_columns = self._denied_columns(
            context,
            self._column_refs(sql, classification.tables),
        )
        if denied_columns:
            return _result(
                classification,
                allowed=False,
                reason="database_column_denied",
                operation_type=operation_type,
                operation_resource_id=operation_resource_id,
                denied_columns=denied_columns,
            )

        return _result(
            classification,
            allowed=True,
            reason="ready_for_confirmation",
            operation_type=operation_type,
            operation_resource_id=operation_resource_id,
        )

    def _denied_tables(self, context: RequestContext, table_names: list[str]) -> list[str]:
        denied: list[str] = []
        for table_name in table_names:
            try:
                table = self.registry.require_table(table_name)
            except KeyError:
                if table_name not in denied:
                    denied.append(table_name)
                continue
            decision = self.permission_service.check(
                context,
                resource_type=DATABASE_TABLE_RESOURCE_TYPE,
                resource_id=database_table_resource_id(self.registry.database_id, table.name),
                action=DATABASE_READ_ACTION,
            )
            if not decision.allowed and table.name not in denied:
                denied.append(table.name)
        return denied

    def _denied_columns(self, context: RequestContext, column_refs: list[_ColumnRef]) -> list[str]:
        if not column_refs:
            return []
        denied: list[str] = []
        for column_ref in column_refs:
            if not self._column_allowed(context, column_ref.table_name, column_ref.column_name):
                denied_key = f"{column_ref.table_name}.{column_ref.column_name}"
                if denied_key not in denied:
                    denied.append(denied_key)
        return denied

    def _column_refs(self, sql: str, table_names: list[str]) -> list[_ColumnRef]:
        try:
            statement = sqlglot.parse_one(sql.strip(), read=self.dialect)
        except Exception:
            return []

        refs: list[_ColumnRef] = []
        target_table = self._first_known_table_name(table_names)
        if isinstance(statement, exp.Insert) and isinstance(statement.this, exp.Schema):
            if target_table is not None:
                for expression in statement.this.expressions:
                    if isinstance(expression, exp.Identifier):
                        self._append_column_ref(refs, target_table, expression.name)
        if target_table is not None and isinstance(statement, (exp.Alter, exp.Create)):
            for column_def in statement.find_all(exp.ColumnDef):
                column_name = self._column_def_name(column_def)
                if column_name:
                    self._append_column_ref(refs, target_table, column_name)

        for column in statement.find_all(exp.Column):
            column_name = column.name
            table_name = self._resolve_column_table(column.table, column_name, table_names)
            if table_name is None:
                table_name = self._first_known_table_name(table_names)
            if table_name is not None:
                self._append_column_ref(refs, table_name, column_name)
        return refs

    def _first_known_table_name(self, table_names: list[str]) -> str | None:
        known_tables = self._known_tables(table_names)
        return known_tables[0].name if known_tables else None

    def _resolve_column_table(
        self,
        table_name: str,
        column_name: str,
        statement_table_names: list[str],
    ) -> str | None:
        if table_name:
            return self.registry._normalize(table_name)

        normalized_column = self.registry._normalize(column_name)
        matching_tables = []
        for statement_table_name in statement_table_names:
            try:
                table = self.registry.require_table(statement_table_name)
            except KeyError:
                continue
            if normalized_column in table.columns:
                matching_tables.append(table.name)
        if len(matching_tables) == 1:
            return matching_tables[0]
        if len(statement_table_names) == 1:
            return statement_table_names[0]
        return None

    def _append_column_ref(
        self,
        refs: list[_ColumnRef],
        table_name: str,
        column_name: str,
    ) -> None:
        ref = _ColumnRef(
            table_name=self.registry._normalize(table_name),
            column_name=self.registry._normalize(column_name),
        )
        if ref not in refs:
            refs.append(ref)

    @staticmethod
    def _column_def_name(column_def: exp.ColumnDef) -> str:
        target = column_def.this
        if isinstance(target, exp.Identifier):
            return target.name
        return str(getattr(target, "name", "") or "")

    def _known_tables(self, table_names: list[str]):
        tables = []
        for table_name in table_names:
            try:
                tables.append(self.registry.require_table(table_name))
            except KeyError:
                continue
        return tables

    def _column_allowed(self, context: RequestContext, table_name: str, column_name: str) -> bool:
        try:
            column = self.registry.require_column(table_name, column_name)
        except KeyError:
            return False
        decision = self.permission_service.check(
            context,
            resource_type=DATABASE_COLUMN_RESOURCE_TYPE,
            resource_id=database_column_resource_id(
                self.registry.database_id,
                table_name,
                column.name,
            ),
            action=DATABASE_READ_ACTION,
        )
        return decision.allowed


def operation_permission_type(
    classification: DatabaseOperationClassification,
) -> str | None:
    if classification.operation_level == "L3":
        return "update"
    if classification.operation_level == "L4":
        return "delete"
    if classification.operation_level == "L5":
        return "ddl"
    return None


def _result(
    classification: DatabaseOperationClassification,
    *,
    allowed: bool,
    reason: str,
    operation_type: str | None,
    operation_resource_id: str | None,
    denied_tables: list[str] | None = None,
    denied_columns: list[str] | None = None,
) -> DatabaseOperationPermissionResult:
    return DatabaseOperationPermissionResult(
        allowed=allowed,
        reason=reason,
        classification=classification,
        operation_type=operation_type,
        operation_resource_id=operation_resource_id,
        denied_tables=denied_tables or [],
        denied_columns=denied_columns or [],
    )
