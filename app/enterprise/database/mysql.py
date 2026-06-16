"""MySQL read-only database tools for DB-MySQL-1."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time
from decimal import Decimal
from queue import Empty, LifoQueue
from threading import Lock
from typing import Any, Protocol

import sqlglot
from sqlglot import exp

from app.enterprise.context import RequestContext
from app.enterprise.database.permissions import DatabasePermissionFilter
from app.enterprise.database.registry import ColumnPolicy, DatabaseSchemaRegistry, TablePolicy
from app.enterprise.database.safe_sql import DatabaseExecutionError, SafeSqlBlocked
from app.enterprise.database.service import DatabaseSandboxService
from app.enterprise.database.tool_schemas import (
    database_describe_table_input_schema,
    database_list_tables_input_schema,
    database_safe_select_input_schema,
)
from app.enterprise.errors.mapper import recovery_metadata
from app.enterprise.errors.models import ErrorClass, ErrorContext
from app.enterprise.errors.recovery import RecoveryStrategy
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.observability.models import AuditEvent
from app.enterprise.permissions.service import PermissionService
from app.enterprise.tools.models import ToolDefinition


class MySqlReadonlyConnector(Protocol):
    def execute_readonly(self, sql: str, *, timeout_seconds: float) -> list[dict[str, Any]]:
        ...


class MySqlWritableConnector(MySqlReadonlyConnector, Protocol):
    def execute_transaction(self, sql: str, *, timeout_seconds: float) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class MySqlConnectionSettings:
    host: str
    port: int
    database: str
    username: str
    password: str
    connect_timeout: float = 5.0
    read_timeout: float = 5.0


MySqlConnectionFactory = Callable[[MySqlConnectionSettings], Any]


class PooledMySqlReadonlyConnector:
    """Small lazy MySQL connector for explicit read-only database tools."""

    def __init__(
        self,
        *,
        settings: MySqlConnectionSettings,
        pool_size: int = 2,
        connection_factory: MySqlConnectionFactory | None = None,
    ):
        self.settings = settings
        self.pool_size = max(1, pool_size)
        self.connection_factory = connection_factory or _default_mysql_connection_factory
        self._pool: LifoQueue[Any] = LifoQueue(maxsize=self.pool_size)
        self._created_count = 0
        self._lock = Lock()

    def execute_readonly(self, sql: str, *, timeout_seconds: float) -> list[dict[str, Any]]:
        connection = self._acquire()
        try:
            with connection.cursor() as cursor:
                cursor.execute("START TRANSACTION READ ONLY")
                cursor.execute(sql)
                rows = cursor.fetchall()
                cursor.execute("COMMIT")
            return [dict(row) for row in rows]
        except Exception:
            rollback = getattr(connection, "rollback", None)
            if rollback is not None:
                rollback()
            raise
        finally:
            self._release(connection)

    def _acquire(self) -> Any:
        try:
            return self._pool.get_nowait()
        except Empty:
            pass

        with self._lock:
            if self._created_count < self.pool_size:
                self._created_count += 1
                return self.connection_factory(self.settings)

        try:
            return self._pool.get(timeout=max(0.1, self.settings.connect_timeout))
        except Empty as exc:
            raise RuntimeError("mysql_connection_pool_exhausted") from exc

    def _release(self, connection: Any) -> None:
        try:
            self._pool.put_nowait(connection)
        except Exception:
            close = getattr(connection, "close", None)
            if close is not None:
                close()


class PooledMySqlWritableConnector(PooledMySqlReadonlyConnector):
    """Small lazy MySQL connector for non-production confirmed write operations."""

    def execute_transaction(self, sql: str, *, timeout_seconds: float) -> dict[str, Any]:
        connection = self._acquire()
        try:
            with connection.cursor() as cursor:
                cursor.execute("START TRANSACTION")
                cursor.execute(sql)
                rowcount = getattr(cursor, "rowcount", -1)
                cursor.execute("COMMIT")
            return {
                "rows_affected": rowcount if rowcount >= 0 else None,
            }
        except Exception:
            rollback = getattr(connection, "rollback", None)
            if rollback is not None:
                rollback()
            raise
        finally:
            self._release(connection)


def _default_mysql_connection_factory(settings: MySqlConnectionSettings) -> Any:
    try:
        import pymysql
        from pymysql.cursors import DictCursor
    except ModuleNotFoundError as exc:
        raise RuntimeError("pymysql_not_installed") from exc

    return pymysql.connect(
        host=settings.host,
        port=settings.port,
        user=settings.username,
        password=settings.password,
        database=settings.database,
        connect_timeout=settings.connect_timeout,
        read_timeout=settings.read_timeout,
        write_timeout=settings.read_timeout,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
    )


class MySqlDatabaseOperationExecutor:
    dialect = "mysql"

    def __init__(
        self,
        *,
        registry: DatabaseSchemaRegistry,
        connector: MySqlWritableConnector,
        timeout_seconds: float = 5.0,
    ):
        self.registry = registry
        self.database_id = registry.database_id
        self.connector = connector
        self.timeout_seconds = max(0.0, timeout_seconds)

    def supports_operation(self, operation_type: str) -> bool:
        return operation_type in {
            "delete",
            "truncate",
            "drop_table",
            "alter_table_drop_column",
        }

    def supports_direct_operation(self, operation_type: str) -> bool:
        return operation_type in {
            "insert",
            "update",
            "create_table",
            "create_index",
            "drop_index",
            "alter_table",
            "rename_table",
        }

    def count_matching_rows(self, sql: str, table_name: str) -> int | None:
        try:
            statement = sqlglot.parse_one(sql.strip(), read=self.dialect)
        except Exception:
            return None
        if not isinstance(statement, (exp.Update, exp.Delete)):
            return None

        try:
            table = self.registry.require_table(table_name)
        except KeyError:
            return None

        where = statement.args.get("where")
        where_sql = ""
        if isinstance(where, exp.Where):
            where_sql = f" WHERE {where.this.sql(dialect=self.dialect, normalize=True)}"
        query = f"SELECT COUNT(*) AS affected_count FROM {_mysql_identifier(table.name)}{where_sql}"
        rows = self.connector.execute_readonly(query, timeout_seconds=self.timeout_seconds)
        if not rows:
            return None
        row = rows[0]
        if "affected_count" in row:
            return int(row["affected_count"])
        if "COUNT(*)" in row:
            return int(row["COUNT(*)"])
        try:
            return int(next(iter(row.values())))
        except StopIteration:
            return None

    def execute(self, confirmation) -> dict[str, Any]:
        if not self.supports_operation(confirmation.operation_type):
            raise RuntimeError("mysql_operation_not_supported")
        result = self.connector.execute_transaction(
            confirmation.normalized_sql,
            timeout_seconds=self.timeout_seconds,
        )
        return {
            "rows_affected": result.get("rows_affected"),
            "database_id": confirmation.database_id,
            "operation_type": confirmation.operation_type,
            "isolation_level": "mysql_transaction",
        }

    def execute_sql(
        self,
        sql: str,
        *,
        database_id: str,
        operation_type: str,
    ) -> dict[str, Any]:
        if database_id != self.database_id:
            raise RuntimeError("mysql_database_mismatch")
        if not self.supports_direct_operation(operation_type):
            raise RuntimeError("mysql_direct_operation_not_supported")
        result = self.connector.execute_transaction(
            sql,
            timeout_seconds=self.timeout_seconds,
        )
        return {
            "rows_affected": result.get("rows_affected"),
            "database_id": database_id,
            "operation_type": operation_type,
            "isolation_level": "mysql_transaction",
        }


class MySqlSafeSqlKernel:
    def __init__(
        self,
        *,
        registry: DatabaseSchemaRegistry,
        connector: MySqlReadonlyConnector,
        audit_service: AuditService | None = None,
        default_limit: int = 100,
        max_limit: int = 100,
        max_result_size_bytes: int = 64 * 1024,
        timeout_seconds: float = 5.0,
    ):
        self.registry = registry
        self.connector = connector
        self.audit_service = audit_service or AuditService()
        self.default_limit = min(max(1, default_limit), max(1, max_limit))
        self.max_limit = max(1, max_limit)
        self.max_result_size_bytes = max(1, max_result_size_bytes)
        self.timeout_seconds = max(0.0, timeout_seconds)

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
            rows = self.connector.execute_readonly(
                sanitized_sql,
                timeout_seconds=self.timeout_seconds,
            )
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
        except Exception as exc:
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
            statements = sqlglot.parse(sql, read="mysql")
        except Exception as exc:
            raise SafeSqlBlocked("parse_failed") from exc
        if len(statements) != 1:
            raise SafeSqlBlocked("multi_statement_not_allowed")
        return statements[0]

    def _validate_select(self, statement: exp.Expression) -> str:
        if not isinstance(statement, exp.Select):
            raise SafeSqlBlocked("non_select_statement_not_allowed")
        if statement.args.get("locks"):
            raise SafeSqlBlocked("locking_select_not_allowed")
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
        sql = statement.sql(dialect="mysql")
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

    def _mask_rows(self, table_name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        masked_rows: list[dict[str, Any]] = []
        for row in rows:
            masked = {}
            for column_name, value in row.items():
                policy = self.registry.column_policy(table_name, column_name)
                masked_value = _mask_value(value, policy.mask) if policy.sensitive else value
                masked[column_name] = _json_safe_value(masked_value)
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
            "dialect": "mysql",
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
                    stage="database_mysql",
                    reason=reason,
                )
            )
            metadata.update(recovery_metadata(recovery))
        self.audit_service.record(
            AuditEvent(
                event_type="database_query",
                route="database_mysql",
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


class DatabaseMySqlToolProvider:
    source = "database-mysql"

    def __init__(
        self,
        *,
        registry: DatabaseSchemaRegistry,
        kernel: MySqlSafeSqlKernel,
        service: DatabaseSandboxService | None = None,
        permission_service: PermissionService | None = None,
    ):
        self.registry = registry
        self.service = service or DatabaseSandboxService(registry=registry, kernel=kernel)
        self.permission_filter = (
            DatabasePermissionFilter(
                registry=registry,
                permission_service=permission_service,
                dialect="mysql",
            )
            if permission_service is not None
            else None
        )
        self._tools = [
            ToolDefinition(
                resource_id=f"database_mysql.{registry.database_id}.list_tables",
                name="list_tables",
                description="List database tables exposed by the MySQL read-only registry.",
                source=self.source,
                input_schema=database_list_tables_input_schema(),
                metadata={
                    "category": "database",
                    "database_id": registry.database_id,
                    "operation_type": "list_tables",
                    "read_only": True,
                },
            ),
            ToolDefinition(
                resource_id=f"database_mysql.{registry.database_id}.describe_table",
                name="describe_table",
                description="Describe one exposed MySQL database table.",
                source=self.source,
                input_schema=database_describe_table_input_schema(),
                metadata={
                    "category": "database",
                    "database_id": registry.database_id,
                    "operation_type": "describe_table",
                    "read_only": True,
                },
            ),
            ToolDefinition(
                resource_id=f"database_mysql.{registry.database_id}.safe_select",
                name="safe_select",
                description="Execute one allowlisted read-only SELECT against the MySQL database.",
                source=self.source,
                input_schema=database_safe_select_input_schema(),
                metadata={
                    "category": "database",
                    "database_id": registry.database_id,
                    "operation_type": "safe_select",
                    "read_only": True,
                },
            ),
        ]

    async def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools)

    async def execute_tool(self, resource_id: str, arguments: dict[str, Any]) -> Any:
        return await self.execute_tool_with_context(resource_id, arguments, _anonymous_context())

    async def execute_tool_with_context(
        self,
        resource_id: str,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> Any:
        if resource_id == f"database_mysql.{self.registry.database_id}.list_tables":
            if self.permission_filter is not None:
                return self._list_tables_with_permissions(context)
            return self.service.list_tables(context)
        if resource_id == f"database_mysql.{self.registry.database_id}.describe_table":
            if self.permission_filter is not None:
                return self._describe_table_with_permissions(
                    context,
                    str(arguments.get("table_name", "")),
                )
            return self.service.describe_table(context, str(arguments.get("table_name", "")))
        if resource_id == f"database_mysql.{self.registry.database_id}.safe_select":
            sql = str(arguments.get("sql", ""))
            if self.permission_filter is not None:
                self._enforce_safe_select_permissions(context, sql)
            result = self.service.safe_select(context, sql)
            self._verify_safe_select_result(context, sql, result)
            return result
        raise KeyError(resource_id)

    def _list_tables_with_permissions(self, context: RequestContext) -> dict[str, Any]:
        started = time.perf_counter()
        assert self.permission_filter is not None
        tables = self.permission_filter.allowed_table_names(context)
        self._record_database_audit(
            context,
            decision="allowed",
            status="success",
            operation_type="list_tables",
            target_tables=tables,
            rows_returned=len(tables),
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        return {
            "database_id": self.registry.database_id,
            "status": "success",
            "tables": tables,
        }

    def _describe_table_with_permissions(
        self,
        context: RequestContext,
        table_name: str,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        assert self.permission_filter is not None
        try:
            table = self.registry.require_table(table_name)
        except KeyError as exc:
            reason = "unauthorized_table"
            self._record_database_audit(
                context,
                decision="denied",
                status="blocked",
                operation_type="describe_table",
                target_tables=[table_name],
                reason=reason,
                latency_ms=(time.perf_counter() - started) * 1000,
                error_class=ErrorClass.SQL_BLOCKED.value,
            )
            raise SafeSqlBlocked(reason) from exc

        if not self.permission_filter.is_table_allowed(context, table.name):
            reason = "database_table_denied"
            self._record_database_audit(
                context,
                decision="denied",
                status="blocked",
                operation_type="describe_table",
                target_tables=[table.name],
                reason=reason,
                latency_ms=(time.perf_counter() - started) * 1000,
                error_class=ErrorClass.SQL_BLOCKED.value,
            )
            raise SafeSqlBlocked(reason)

        description = self.registry.describe_table(table.name)
        allowed_columns = self.permission_filter.allowed_column_names(context, table.name)
        description["columns"] = [
            column
            for column in description["columns"]
            if self.registry._normalize(column["name"]) in allowed_columns
        ]
        description["status"] = "success"
        self._record_database_audit(
            context,
            decision="allowed",
            status="success",
            operation_type="describe_table",
            target_tables=[table.name],
            rows_returned=len(description["columns"]),
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        return description

    def _enforce_safe_select_permissions(self, context: RequestContext, sql: str) -> None:
        started = time.perf_counter()
        assert self.permission_filter is not None
        target = self.permission_filter.select_target(sql)
        if target is None:
            return

        if not self.permission_filter.is_table_allowed(context, target.table_name):
            reason = "database_table_denied"
            self._record_database_audit(
                context,
                decision="denied",
                status="blocked",
                operation_type="safe_select",
                target_tables=[target.table_name],
                sql_text=sql,
                reason=reason,
                latency_ms=(time.perf_counter() - started) * 1000,
                error_class=ErrorClass.SQL_BLOCKED.value,
            )
            raise SafeSqlBlocked(reason)

        denied_columns = self.permission_filter.denied_columns(
            context,
            target.table_name,
            target.column_names,
        )
        if denied_columns:
            reason = "database_column_denied"
            self._record_database_audit(
                context,
                decision="denied",
                status="blocked",
                operation_type="safe_select",
                target_tables=[target.table_name],
                sql_text=sql,
                reason=reason,
                latency_ms=(time.perf_counter() - started) * 1000,
                metadata_extra={"denied_columns": denied_columns},
                error_class=ErrorClass.SQL_BLOCKED.value,
            )
            raise SafeSqlBlocked(reason)

    def _verify_safe_select_result(
        self,
        context: RequestContext,
        sql: str,
        result: dict[str, Any],
    ) -> None:
        authorized_columns = self._authorized_columns_for_sql(context, sql, result)
        if not authorized_columns and result.get("columns"):
            raise SafeSqlBlocked("sql_result_verification_failed")

    def _authorized_columns_for_sql(
        self,
        context: RequestContext,
        sql: str,
        result: dict[str, Any],
    ) -> list[str]:
        if self.permission_filter is not None:
            target = self.permission_filter.select_target(sql)
            if target is not None:
                return sorted(self.permission_filter.allowed_column_names(context, target.table_name))
        return [str(column) for column in result.get("columns", [])]

    def _record_database_audit(
        self,
        context: RequestContext,
        *,
        decision: str,
        status: str,
        operation_type: str,
        target_tables: list[str],
        sql_text: str = "",
        reason: str | None = None,
        rows_returned: int = 0,
        latency_ms: float | None = None,
        metadata_extra: dict[str, Any] | None = None,
        error_class: str | None = None,
    ) -> None:
        metadata = {
            "database_id": self.registry.database_id,
            "tool_name": operation_type,
            "operation_type": operation_type,
            "dialect": "mysql",
            "target_tables": target_tables,
            "sql_hash": _audit_hash(sql_text or operation_type),
            "sanitized_sql": "",
            "rows_returned": rows_returned,
            "result_size_bytes": 0,
            "status": status,
            "blocked_reason": reason,
        }
        if metadata_extra:
            metadata.update(metadata_extra)
        if error_class == ErrorClass.SQL_BLOCKED.value:
            recovery = RecoveryStrategy().decide(
                ErrorContext(
                    error_class=ErrorClass.SQL_BLOCKED,
                    stage="database_mysql",
                    reason=reason,
                )
            )
            metadata.update(recovery_metadata(recovery))
        self.service.audit_service.record(
            AuditEvent(
                event_type="database_query",
                route="database_mysql",
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


def build_mysql_provider_from_config(
    *,
    app_config: Any,
    permission_service: PermissionService,
    audit_service: AuditService | None = None,
    connection_factory: MySqlConnectionFactory | None = None,
) -> DatabaseMySqlToolProvider | None:
    registry = build_mysql_registry_from_config(app_config=app_config)
    if registry is None:
        return None

    host = str(getattr(app_config, "enterprise_mysql_host", "")).strip()
    database = str(getattr(app_config, "enterprise_mysql_database", "")).strip()
    username = str(getattr(app_config, "enterprise_mysql_username", "")).strip()
    settings = MySqlConnectionSettings(
        host=host,
        port=int(getattr(app_config, "enterprise_mysql_port", 3306)),
        database=database,
        username=username,
        password=str(getattr(app_config, "enterprise_mysql_password", "")),
        connect_timeout=float(
            getattr(app_config, "enterprise_mysql_connect_timeout_seconds", 5.0)
        ),
        read_timeout=float(getattr(app_config, "enterprise_mysql_read_timeout_seconds", 5.0)),
    )
    connector = PooledMySqlReadonlyConnector(
        settings=settings,
        pool_size=int(getattr(app_config, "enterprise_mysql_pool_size", 2)),
        connection_factory=connection_factory,
    )
    kernel = MySqlSafeSqlKernel(
        registry=registry,
        connector=connector,
        audit_service=audit_service,
        default_limit=int(getattr(app_config, "enterprise_mysql_default_limit", 100)),
        max_limit=int(getattr(app_config, "enterprise_mysql_max_limit", 100)),
    )
    return DatabaseMySqlToolProvider(
        registry=registry,
        kernel=kernel,
        permission_service=permission_service,
    )


def build_mysql_operation_executor_from_config(
    *,
    app_config: Any,
    connection_factory: MySqlConnectionFactory | None = None,
) -> tuple[DatabaseSchemaRegistry, MySqlDatabaseOperationExecutor] | None:
    registry = build_mysql_registry_from_config(app_config=app_config)
    if registry is None:
        return None

    host = str(getattr(app_config, "enterprise_mysql_host", "")).strip()
    database = str(getattr(app_config, "enterprise_mysql_database", "")).strip()
    username = str(getattr(app_config, "enterprise_mysql_username", "")).strip()
    settings = MySqlConnectionSettings(
        host=host,
        port=int(getattr(app_config, "enterprise_mysql_port", 3306)),
        database=database,
        username=username,
        password=str(getattr(app_config, "enterprise_mysql_password", "")),
        connect_timeout=float(
            getattr(app_config, "enterprise_mysql_connect_timeout_seconds", 5.0)
        ),
        read_timeout=float(getattr(app_config, "enterprise_mysql_read_timeout_seconds", 5.0)),
    )
    connector = PooledMySqlWritableConnector(
        settings=settings,
        pool_size=int(getattr(app_config, "enterprise_mysql_pool_size", 2)),
        connection_factory=connection_factory,
    )
    return (
        registry,
        MySqlDatabaseOperationExecutor(
            registry=registry,
            connector=connector,
            timeout_seconds=float(getattr(app_config, "enterprise_mysql_read_timeout_seconds", 5.0)),
        ),
    )


def build_mysql_registry_from_config(*, app_config: Any) -> DatabaseSchemaRegistry | None:
    if not bool(getattr(app_config, "enterprise_mysql_enabled", False)):
        return None

    database_id = str(getattr(app_config, "enterprise_mysql_database_id", "")).strip()
    host = str(getattr(app_config, "enterprise_mysql_host", "")).strip()
    database = str(getattr(app_config, "enterprise_mysql_database", "")).strip()
    username = str(getattr(app_config, "enterprise_mysql_username", "")).strip()
    allowlist_json = str(getattr(app_config, "enterprise_mysql_allowlist_json", "")).strip()
    if not database_id or not host or not database or not username or not allowlist_json:
        return None

    return build_mysql_registry_from_allowlist(
        database_id=database_id,
        allowlist=allowlist_json,
    )


def build_mysql_registry_from_allowlist(
    *,
    database_id: str,
    allowlist: str | dict[str, Any],
) -> DatabaseSchemaRegistry:
    if isinstance(allowlist, str):
        allowlist_data = json.loads(allowlist)
    else:
        allowlist_data = allowlist
    if not isinstance(allowlist_data, dict) or not allowlist_data:
        raise ValueError("mysql_allowlist_required")

    tables: dict[str, Any] = {}
    for table_name, table_config in allowlist_data.items():
        if not isinstance(table_config, dict):
            raise ValueError("mysql_table_allowlist_must_be_object")
        columns_config = table_config.get("columns")
        if not isinstance(columns_config, dict) or not columns_config:
            raise ValueError("mysql_table_columns_required")
        columns = {
            column_name: _column_policy_from_config(column_name, column_config)
            for column_name, column_config in columns_config.items()
        }
        tables[table_name] = TablePolicy(
            name=str(table_config.get("name") or table_name),
            description=str(table_config.get("description", "")),
            columns=columns,
            allowed=bool(table_config.get("allowed", True)),
            max_rows=int(table_config.get("max_rows", 100)),
            metadata=dict(table_config.get("metadata", {})),
        )
    return DatabaseSchemaRegistry(database_id=database_id, tables=tables)


def _column_policy_from_config(column_name: str, column_config: Any) -> ColumnPolicy:
    if isinstance(column_config, str):
        return ColumnPolicy(name=column_name, data_type=column_config)
    if not isinstance(column_config, dict):
        raise ValueError("mysql_column_allowlist_must_be_object_or_type")
    return ColumnPolicy(
        name=str(column_config.get("name") or column_name),
        data_type=str(column_config.get("data_type", "TEXT")),
        allowed=bool(column_config.get("allowed", True)),
        sensitive=bool(column_config.get("sensitive", False)),
        mask=column_config.get("mask"),
        description=str(column_config.get("description", "")),
    )


def _audit_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _mysql_identifier(identifier: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier) is None:
        raise RuntimeError("unsafe_mysql_identifier")
    return f"`{identifier}`"


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


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date | datetime_time):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _anonymous_context() -> RequestContext:
    return RequestContext(
        request_id="database-mysql-request",
        trace_id="database-mysql-trace",
        user_id="anonymous",
        username="anonymous",
        department_id="unknown",
        department_name="Unknown",
        roles=[],
    )
