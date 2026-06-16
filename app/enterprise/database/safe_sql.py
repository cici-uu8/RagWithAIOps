"""Safe SQL kernel for the E6 database sandbox."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp

from app.enterprise.context import RequestContext
from app.enterprise.database.registry import DatabaseSchemaRegistry
from app.enterprise.errors.mapper import recovery_metadata
from app.enterprise.errors.models import ErrorClass, ErrorContext
from app.enterprise.errors.recovery import RecoveryStrategy
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.observability.models import AuditEvent


class SafeSqlBlocked(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Safe SQL blocked: {reason}")


class DatabaseExecutionError(Exception):
    def __init__(self, cause: BaseException):
        self.cause = cause
        super().__init__(f"Database execution failed: {type(cause).__name__}")


class SafeSqlKernel:
    def __init__(
        self,
        *,
        database_path: str | Path,
        registry: DatabaseSchemaRegistry,
        audit_service: AuditService | None = None,
        default_limit: int = 100,
        max_limit: int = 100,
        max_result_size_bytes: int = 64 * 1024,
        timeout_seconds: float = 5.0,
        progress_check_steps: int = 1000,
    ):
        self.database_path = Path(database_path)
        self.registry = registry
        self.audit_service = audit_service or AuditService()
        self.max_limit = max(1, max_limit)
        self.default_limit = min(max(1, default_limit), self.max_limit)
        self.max_result_size_bytes = max(1, max_result_size_bytes)
        self.timeout_seconds = max(0.0, timeout_seconds)
        self.progress_check_steps = max(1, progress_check_steps)

    def safe_select(self, context: RequestContext, sql: str) -> dict[str, Any]:
        started = time.perf_counter()
        sql_text = sql.strip()
        sql_hash = _hash_sql(sql_text)
        target_tables: list[str] = []
        sanitized_sql = ""

        try:
            parsed = self._parse_one(sql_text)
            table_name = self._validate_select(parsed)
            target_tables = [table_name]
            sanitized_sql = self._build_sql_with_limit(parsed)
            rows = self._execute_readonly(sanitized_sql)
            masked_rows = self._mask_rows(table_name, rows)
            columns = list(masked_rows[0]) if masked_rows else self._selected_columns(parsed, table_name)
            latency_ms = (time.perf_counter() - started) * 1000
            result_size_bytes = len(json.dumps(masked_rows, ensure_ascii=False).encode("utf-8"))
            if result_size_bytes > self.max_result_size_bytes:
                raise SafeSqlBlocked("result_size_exceeds_max")
            self._record_audit(
                context,
                decision="allowed",
                status="success",
                operation_type="safe_select",
                target_tables=target_tables,
                sql_hash=sql_hash,
                sanitized_sql=sanitized_sql,
                rows_returned=len(masked_rows),
                result_size_bytes=result_size_bytes,
                latency_ms=latency_ms,
            )
            return {
                "database_id": self.registry.database_id,
                "status": "success",
                "sql_hash": sql_hash,
                "safe_sql_verified": True,
                "sanitized_sql": sanitized_sql,
                "columns": columns,
                "rows": masked_rows,
                "row_count": len(masked_rows),
                "result_size_bytes": result_size_bytes,
                "latency_ms": latency_ms,
            }
        except SafeSqlBlocked as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            self._record_audit(
                context,
                decision="denied",
                status="blocked",
                operation_type="safe_select",
                target_tables=target_tables,
                sql_hash=sql_hash,
                sanitized_sql=sanitized_sql,
                reason=exc.reason,
                latency_ms=latency_ms,
                error_class=ErrorClass.SQL_BLOCKED.value,
            )
            raise
        except sqlite3.Error as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            self._record_audit(
                context,
                decision="failed",
                status="failed",
                operation_type="safe_select",
                target_tables=target_tables,
                sql_hash=sql_hash,
                sanitized_sql=sanitized_sql,
                latency_ms=latency_ms,
                error_class=type(exc).__name__,
            )
            raise DatabaseExecutionError(exc) from exc

    def _parse_one(self, sql: str) -> exp.Expression:
        try:
            statements = sqlglot.parse(sql, read="sqlite")
        except Exception as exc:
            raise SafeSqlBlocked("parse_failed") from exc
        if len(statements) != 1:
            raise SafeSqlBlocked("multi_statement_not_allowed")
        return statements[0]

    def _validate_select(self, statement: exp.Expression) -> str:
        if not isinstance(statement, exp.Select):
            raise SafeSqlBlocked("non_select_statement_not_allowed")
        if statement.find(exp.Join) is not None:
            raise SafeSqlBlocked("join_not_allowed")
        if statement.find(exp.Union) is not None or statement.find(exp.Subquery) is not None:
            raise SafeSqlBlocked("subquery_not_allowed")
        if any(isinstance(item, exp.Star) or item.find(exp.Star) for item in statement.expressions):
            raise SafeSqlBlocked("select_star_not_allowed")
        if any(isinstance(item, exp.Func) for item in statement.walk()):
            raise SafeSqlBlocked("function_not_allowed")

        table_names = {self.registry._normalize(table.name) for table in statement.find_all(exp.Table)}
        if len(table_names) != 1:
            raise SafeSqlBlocked("single_table_required")
        table_name = next(iter(table_names))

        try:
            self.registry.require_table(table_name)
        except KeyError as exc:
            raise SafeSqlBlocked("unauthorized_table") from exc

        selected_columns = self._selected_columns(statement, table_name)
        if not selected_columns:
            raise SafeSqlBlocked("columns_required")

        for column in statement.find_all(exp.Column):
            column_name = column.name
            try:
                self.registry.require_column(table_name, column_name)
            except KeyError as exc:
                raise SafeSqlBlocked("unauthorized_column") from exc

        return table_name

    def _build_sql_with_limit(self, statement: exp.Expression) -> str:
        sql = statement.sql(dialect="sqlite")
        limit_match = re.search(r"\bLIMIT\s+(\d+)\b", sql, flags=re.IGNORECASE)
        if limit_match is None:
            return f"{sql} LIMIT {self.default_limit}"
        limit_value = int(limit_match.group(1))
        if limit_value > self.max_limit:
            raise SafeSqlBlocked("limit_exceeds_max")
        return sql

    def _selected_columns(self, statement: exp.Expression, table_name: str) -> list[str]:
        selected: list[str] = []
        allowed = self.registry.allowed_column_names(table_name)
        for expression in statement.expressions:
            if isinstance(expression, exp.Alias) or expression.alias:
                raise SafeSqlBlocked("column_alias_not_allowed")
            columns = list(expression.find_all(exp.Column))
            if len(columns) != 1:
                raise SafeSqlBlocked("simple_column_select_required")
            column_name = self.registry._normalize(columns[0].name)
            if column_name not in allowed:
                raise SafeSqlBlocked("unauthorized_column")
            selected.append(columns[0].alias_or_name)
        return selected

    def _execute_readonly(self, sql: str) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.database_path)) as connection:
            deadline = time.perf_counter() + self.timeout_seconds

            def abort_after_deadline() -> int:
                return int(time.perf_counter() >= deadline)

            connection.set_progress_handler(abort_after_deadline, self.progress_check_steps)
            try:
                connection.execute("PRAGMA query_only = ON")
                connection.row_factory = sqlite3.Row
                rows = connection.execute(sql).fetchall()
                return [dict(row) for row in rows]
            finally:
                connection.set_progress_handler(None, 0)

    def _mask_rows(self, table_name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        masked_rows: list[dict[str, Any]] = []
        for row in rows:
            masked = {}
            for column_name, value in row.items():
                policy = self.registry.column_policy(table_name, column_name)
                masked[column_name] = _mask_value(value, policy.mask) if policy.sensitive else value
            masked_rows.append(masked)
        return masked_rows

    def _record_audit(
        self,
        context: RequestContext,
        *,
        decision: str,
        status: str,
        operation_type: str,
        target_tables: list[str],
        sql_hash: str,
        sanitized_sql: str,
        reason: str | None = None,
        rows_returned: int = 0,
        result_size_bytes: int = 0,
        latency_ms: float | None = None,
        error_class: str | None = None,
    ) -> None:
        metadata = {
            "database_id": self.registry.database_id,
            "tool_name": operation_type,
            "operation_type": operation_type,
            "target_tables": target_tables,
            "sql_hash": sql_hash,
            "sanitized_sql": sanitized_sql,
            "rows_returned": rows_returned,
            "result_size_bytes": result_size_bytes,
            "status": status,
            "blocked_reason": reason,
        }
        if error_class == ErrorClass.SQL_BLOCKED.value:
            recovery = RecoveryStrategy().decide(
                ErrorContext(
                    error_class=ErrorClass.SQL_BLOCKED,
                    stage="database_safe_sql",
                    reason=reason,
                )
            )
            metadata.update(recovery_metadata(recovery))
        self.audit_service.record(
            AuditEvent(
                event_type="database_query",
                route="database_demo",
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision=decision,
                reason=reason,
                error_class=error_class,
                latency_ms=latency_ms,
                metadata=metadata,
            )
        )


def _hash_sql(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def _mask_value(value: Any, mask: str | None) -> Any:
    if value is None:
        return None
    text = str(value)
    if mask == "email" and "@" in text:
        local, domain = text.split("@", 1)
        prefix = local[:1] if local else ""
        return f"{prefix}***@{domain}"
    if mask == "phone" and len(text) >= 5:
        return f"{text[:3]}****{text[-2:]}"
    if mask == "name":
        return f"{text[:1]}*" if text else "***"
    if mask == "badge" and len(text) >= 6:
        return f"{text[:3]}***{text[-3:]}"
    return "***"
