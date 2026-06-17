"""Build permission-scoped database context for RAG tools."""

from __future__ import annotations

import re
from typing import Any

from app.enterprise.context import RequestContext
from app.enterprise.database.permissions import DatabasePermissionFilter
from app.enterprise.database.qsql_examples import QSqlExample, QSqlExampleRegistry
from app.enterprise.database.registry import (
    ColumnPolicy,
    DatabaseSchemaRegistry,
    build_default_sandbox_registry,
)
from app.enterprise.permissions.service import (
    PermissionService,
    permission_service as global_permission_service,
)

SELECT_COLUMNS_RE = re.compile(r"select\s+(?P<columns>.*?)\s+from\s+", re.IGNORECASE | re.DOTALL)


class DatabaseContextBuilder:
    def __init__(
        self,
        *,
        registry: DatabaseSchemaRegistry | None = None,
        permission_service: PermissionService | None = None,
        example_registry: QSqlExampleRegistry | None = None,
    ):
        self.registry = registry or build_default_sandbox_registry()
        self.permission_service = permission_service or global_permission_service
        self.example_registry = example_registry or QSqlExampleRegistry()

    def build_context(
        self,
        context: RequestContext,
        *,
        question: str,
        database_id: str = "sandbox_sales",
        limit: int = 3,
    ) -> dict[str, Any]:
        normalized_database_id = (database_id or self.registry.database_id).strip()
        if normalized_database_id not in {self.registry.database_id, "database_demo"}:
            return {
                "status": "denied",
                "reason": "database_not_allowed",
                "database_id": normalized_database_id,
                "question": question,
                "relevant_examples": [],
                "tables": [],
                "context_text": "当前数据库不在 allowlist 中。",
            }

        relevant_examples = self.example_registry.search(question, limit=limit)
        table_names = _ordered_table_names(relevant_examples, self.registry)
        tables: list[dict[str, Any]] = []
        for table_name in table_names:
            table_context = self._table_context(context, table_name)
            if table_context is not None:
                tables.append(table_context)
        visible_columns_by_table = {
            table["table_name"]: {column["name"] for column in table["authorized_columns"]}
            for table in tables
        }
        visible_table_names = set(visible_columns_by_table)
        relevant_examples = [
            example
            for example in relevant_examples
            if example.table_name in visible_table_names
        ]
        example_payloads = [
            self._example_payload(example, visible_columns_by_table)
            for example in relevant_examples
        ]
        context_text = self._context_text(
            question=question,
            tables=tables,
            examples=example_payloads,
        )
        return {
            "status": "success",
            "database_id": self.registry.database_id,
            "question": question,
            "relevant_examples": example_payloads,
            "tables": tables,
            "context_text": context_text,
        }

    def _table_context(self, context: RequestContext, table_name: str) -> dict[str, Any] | None:
        try:
            table = self.registry.require_table(table_name)
        except KeyError:
            return None
        columns = table.visible_columns() if "admin" in context.roles else self._authorized_columns(context, table.name)
        if not columns:
            return None
        return {
            "table_name": table.name,
            "description": table.description,
            "authorized_columns": [
                {
                    "name": column.name,
                    "data_type": column.data_type,
                    "sensitive": column.sensitive,
                    "mask": column.mask,
                    "description": column.description,
                }
                for column in columns
            ],
        }

    def _authorized_columns(self, context: RequestContext, table_name: str) -> list[ColumnPolicy]:
        permission_filter = DatabasePermissionFilter(
            registry=self.registry,
            permission_service=self.permission_service,
        )
        if not permission_filter.is_table_allowed(context, table_name):
            return []
        table = self.registry.require_table(table_name)
        return [
            column
            for column in table.visible_columns()
            if permission_filter.is_column_allowed(context, table.name, column.name)
        ]

    def _example_payload(
        self,
        example: QSqlExample,
        visible_columns_by_table: dict[str, set[str]],
    ) -> dict[str, Any]:
        selected_columns = _selected_columns(example.sql)
        visible_columns = visible_columns_by_table.get(example.table_name, set())
        sql_allowed = bool(selected_columns) and set(selected_columns).issubset(visible_columns)
        payload: dict[str, Any] = {
            "example_id": example.example_id,
            "question": example.question,
            "table_name": example.table_name,
            "explanation": example.explanation,
            "tags": list(example.tags),
        }
        if sql_allowed:
            payload["sql"] = example.sql
        else:
            payload["sql"] = None
            payload["sql_unavailable_reason"] = "requires_ungranted_columns"
        return payload

    def _context_text(
        self,
        *,
        question: str,
        tables: list[dict[str, Any]],
        examples: list[dict[str, Any]],
    ) -> str:
        lines = [
            f"用户问题: {question}",
            "",
            "可用数据库表:",
        ]
        if not tables:
            lines.append("- 当前用户没有可见的相关数据库表。")
        for table in tables:
            column_names = ", ".join(column["name"] for column in table["authorized_columns"])
            lines.append(f"- {table['table_name']}: {table['description']}")
            lines.append(f"  可查询字段: {column_names}")
        visible_table_names = {table["table_name"] for table in tables}
        visible_examples = [example for example in examples if example["table_name"] in visible_table_names]
        if visible_examples:
            lines.extend(["", "相关 Q-SQL 示例:"])
            for example in visible_examples:
                lines.append(f"- {example['example_id']}: {example['question']}")
                if example.get("sql"):
                    lines.append(f"  SQL: {example['sql']}")
                else:
                    lines.append("  SQL: 当前授权列不足，不能直接复用该示例 SQL。")
        lines.extend(
            [
                "",
                "安全限制:",
                "- 必须显式列出列名，禁止 SELECT *。",
                "- 禁止 JOIN、子查询、函数和聚合函数。",
                "- 查询仍必须通过 database_demo.safe_select 执行。",
            ]
        )
        return "\n".join(lines)


def _ordered_table_names(
    examples: list[QSqlExample],
    registry: DatabaseSchemaRegistry,
) -> list[str]:
    table_names: list[str] = []
    for example in examples:
        if example.table_name not in table_names:
            table_names.append(example.table_name)
    return table_names or registry.list_tables()


def _selected_columns(sql: str) -> list[str]:
    match = SELECT_COLUMNS_RE.search(sql)
    if match is None:
        return []
    raw_columns = match.group("columns")
    columns: list[str] = []
    for raw_column in raw_columns.split(","):
        column_name = raw_column.strip().split()[-1].strip('"`[]')
        if "." in column_name:
            column_name = column_name.rsplit(".", 1)[-1]
        columns.append(column_name.lower())
    return columns
