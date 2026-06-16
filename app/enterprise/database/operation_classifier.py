"""SQL operation classification for database operation routing."""

from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp


@dataclass(frozen=True)
class DatabaseOperationClassification:
    operation_level: str
    operation_type: str
    database_id: str
    tables: list[str]
    columns: list[str]
    is_delete_like: bool
    requires_confirmation: bool
    denied_reason: str | None = None


def classify_sql_operation(
    sql: str,
    *,
    database_id: str,
    dialect: str = "sqlite",
) -> DatabaseOperationClassification:
    try:
        statements = sqlglot.parse(sql.strip(), read=dialect)
    except Exception:
        return _unknown(database_id, "parse_failed")

    if len(statements) != 1:
        return _unknown(database_id, "multi_statement_not_allowed")

    statement = statements[0]
    tables = _table_names(statement)
    columns = _column_names(statement)

    if isinstance(statement, exp.Select):
        return DatabaseOperationClassification(
            operation_level="L1",
            operation_type="select",
            database_id=database_id,
            tables=tables,
            columns=columns,
            is_delete_like=False,
            requires_confirmation=False,
        )
    if isinstance(statement, (exp.Describe, exp.Show)):
        return DatabaseOperationClassification(
            operation_level="L2",
            operation_type="metadata",
            database_id=database_id,
            tables=tables,
            columns=columns,
            is_delete_like=False,
            requires_confirmation=False,
        )
    if isinstance(statement, exp.Insert):
        return _confirmation_result(
            database_id,
            operation_level="L3",
            operation_type="insert",
            tables=tables,
            columns=columns,
        )
    if isinstance(statement, exp.Update):
        return _confirmation_result(
            database_id,
            operation_level="L3",
            operation_type="update",
            tables=tables,
            columns=columns,
        )
    if isinstance(statement, exp.Delete):
        return _confirmation_result(
            database_id,
            operation_level="L4",
            operation_type="delete",
            tables=tables,
            columns=columns,
            is_delete_like=True,
        )
    if isinstance(statement, exp.TruncateTable):
        return _confirmation_result(
            database_id,
            operation_level="L4",
            operation_type="truncate",
            tables=tables,
            columns=columns,
            is_delete_like=True,
        )
    if isinstance(statement, exp.Drop):
        return _classify_drop(statement, database_id, tables, columns)
    if isinstance(statement, exp.Alter):
        return _classify_alter(statement, database_id, tables, columns)
    if isinstance(statement, exp.Create):
        kind = _kind(statement)
        if kind == "index":
            operation_type = "create_index"
        elif kind == "table":
            operation_type = "create_table"
        else:
            operation_type = "create"
        return _confirmation_result(
            database_id,
            operation_level="L5",
            operation_type=operation_type,
            tables=tables,
            columns=columns,
        )
    if isinstance(statement, exp.Command):
        command_result = _classify_command(statement, database_id)
        if command_result is not None:
            return command_result
    if isinstance(statement, exp.Grant):
        return _permission_management(database_id, "grant", tables, columns)
    if isinstance(statement, exp.Revoke):
        return _permission_management(database_id, "revoke", tables, columns)

    return _unknown(database_id, "unsupported_operation")


def _classify_drop(
    statement: exp.Drop,
    database_id: str,
    tables: list[str],
    columns: list[str],
) -> DatabaseOperationClassification:
    kind = _kind(statement)
    operation_type = "drop_table" if kind == "table" else f"drop_{kind}" if kind else "drop"
    if kind == "index":
        index_table = _drop_index_table(statement)
        return _confirmation_result(
            database_id,
            operation_level="L5",
            operation_type=operation_type,
            tables=[index_table] if index_table else tables,
            columns=columns,
        )
    return _confirmation_result(
        database_id,
        operation_level="L4",
        operation_type=operation_type,
        tables=tables,
        columns=columns,
        is_delete_like=True,
    )


def _classify_alter(
    statement: exp.Alter,
    database_id: str,
    tables: list[str],
    columns: list[str],
) -> DatabaseOperationClassification:
    if _alter_drops_column(statement):
        return _confirmation_result(
            database_id,
            operation_level="L4",
            operation_type="alter_table_drop_column",
            tables=tables,
            columns=columns,
            is_delete_like=True,
        )
    return _confirmation_result(
        database_id,
        operation_level="L5",
        operation_type="alter_table",
        tables=tables,
        columns=columns,
    )


def _alter_drops_column(statement: exp.Alter) -> bool:
    for action in statement.args.get("actions") or []:
        if isinstance(action, exp.Drop) and _kind(action) == "column":
            return True
    return False


def _drop_index_table(statement: exp.Drop) -> str | None:
    cluster = statement.args.get("cluster")
    target = getattr(cluster, "this", None)
    if isinstance(target, exp.Identifier):
        return _normalize_identifier(target.name)
    if isinstance(target, str):
        return _normalize_identifier(target)
    return None


def _classify_command(
    statement: exp.Command,
    database_id: str,
) -> DatabaseOperationClassification | None:
    command = str(statement.args.get("this") or "").strip().lower()
    expression = statement.args.get("expression")
    expression_text = expression.this if isinstance(expression, exp.Literal) else ""
    if command != "rename" or not isinstance(expression_text, str):
        return None

    match = re.fullmatch(
        r"\s*table\s+([`\"\[\]\w]+)\s+to\s+([`\"\[\]\w]+)\s*",
        expression_text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    source_table = _normalize_identifier(match.group(1))
    target_table = _normalize_identifier(match.group(2))
    tables = [table for table in [source_table, target_table] if table]
    return _confirmation_result(
        database_id,
        operation_level="L5",
        operation_type="rename_table",
        tables=tables,
        columns=[],
    )


def _confirmation_result(
    database_id: str,
    *,
    operation_level: str,
    operation_type: str,
    tables: list[str],
    columns: list[str],
    is_delete_like: bool = False,
    requires_confirmation: bool = False,
) -> DatabaseOperationClassification:
    return DatabaseOperationClassification(
        operation_level=operation_level,
        operation_type=operation_type,
        database_id=database_id,
        tables=tables,
        columns=columns,
        is_delete_like=is_delete_like,
        requires_confirmation=requires_confirmation or is_delete_like,
    )


def _permission_management(
    database_id: str,
    operation_type: str,
    tables: list[str],
    columns: list[str],
) -> DatabaseOperationClassification:
    return DatabaseOperationClassification(
        operation_level="M1",
        operation_type=operation_type,
        database_id=database_id,
        tables=tables,
        columns=columns,
        is_delete_like=False,
        requires_confirmation=False,
        denied_reason="permission_management_not_database_operation",
    )


def _unknown(database_id: str, denied_reason: str) -> DatabaseOperationClassification:
    return DatabaseOperationClassification(
        operation_level="unknown",
        operation_type="unknown",
        database_id=database_id,
        tables=[],
        columns=[],
        is_delete_like=False,
        requires_confirmation=False,
        denied_reason=denied_reason,
    )


def _table_names(statement: exp.Expression) -> list[str]:
    names: list[str] = []
    for table in statement.find_all(exp.Table):
        table_name = _normalize_identifier(table.name)
        if table_name and table_name not in names:
            names.append(table_name)
    if isinstance(statement, exp.Show):
        target = statement.args.get("target")
        if isinstance(target, exp.Identifier):
            table_name = _normalize_identifier(target.name)
            if table_name and table_name not in names:
                names.append(table_name)
    return names


def _column_names(statement: exp.Expression) -> list[str]:
    names: list[str] = []
    for column in statement.find_all(exp.Column):
        column_name = _normalize_identifier(column.name)
        if column_name and column_name not in names:
            names.append(column_name)
    if isinstance(statement, (exp.Alter, exp.Create)):
        for column_def in statement.find_all(exp.ColumnDef):
            column_name = _column_def_name(column_def)
            if column_name and column_name not in names:
                names.append(column_name)
    if isinstance(statement, exp.Insert) and isinstance(statement.this, exp.Schema):
        for expression in statement.this.expressions:
            if isinstance(expression, exp.Identifier):
                column_name = _normalize_identifier(expression.name)
                if column_name and column_name not in names:
                    names.append(column_name)
    return names


def _kind(statement: exp.Expression) -> str:
    return str(statement.args.get("kind") or "").strip().lower()


def _normalize_identifier(identifier: str) -> str:
    return identifier.strip().strip('"`[]').lower()


def _column_def_name(column_def: exp.ColumnDef) -> str:
    target = column_def.this
    if isinstance(target, exp.Identifier):
        return _normalize_identifier(target.name)
    return _normalize_identifier(str(getattr(target, "name", "") or ""))
