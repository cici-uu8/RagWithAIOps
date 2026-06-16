"""Explicit database-demo tool provider for E6."""

from __future__ import annotations

import hashlib
import time
from typing import Any

from app.enterprise.context import RequestContext
from app.enterprise.database.permissions import DatabasePermissionFilter
from app.enterprise.database.registry import DatabaseSchemaRegistry
from app.enterprise.database.safe_sql import SafeSqlBlocked, SafeSqlKernel
from app.enterprise.database.service import DatabaseSandboxService
from app.enterprise.database.tool_schemas import (
    database_describe_table_input_schema,
    database_list_tables_input_schema,
    database_safe_select_input_schema,
)
from app.enterprise.errors.mapper import recovery_metadata
from app.enterprise.errors.models import ErrorClass, ErrorContext
from app.enterprise.errors.recovery import RecoveryStrategy
from app.enterprise.observability.models import AuditEvent
from app.enterprise.permissions.service import PermissionService
from app.enterprise.tools.models import ToolDefinition
from app.enterprise.verifiers import SqlResultVerifier, VerificationService


class DatabaseDemoToolProvider:
    """Expose read-only sandbox DB tools only when a gateway opts in."""

    source = "database-demo"

    def __init__(
        self,
        *,
        registry: DatabaseSchemaRegistry,
        kernel: SafeSqlKernel,
        service: DatabaseSandboxService | None = None,
        permission_service: PermissionService | None = None,
        verification_service: VerificationService | None = None,
    ):
        self.registry = registry
        self.service = service or DatabaseSandboxService(registry=registry, kernel=kernel)
        self.verification_service = verification_service or VerificationService(
            audit_service=self.service.audit_service
        )
        self.permission_filter = (
            DatabasePermissionFilter(registry=registry, permission_service=permission_service)
            if permission_service is not None
            else None
        )
        self._tools = [
            ToolDefinition(
                resource_id="database_demo.list_tables",
                name="list_tables",
                description="List database tables exposed by the sandbox schema registry.",
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
                resource_id="database_demo.describe_table",
                name="describe_table",
                description="Describe one exposed sandbox database table.",
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
                resource_id="database_demo.safe_select",
                name="safe_select",
                description="Execute one allowlisted read-only SELECT against the sandbox database.",
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
        if resource_id == "database_demo.list_tables":
            if self.permission_filter is not None:
                return self._list_tables_with_permissions(context)
            return self.service.list_tables(context)
        if resource_id == "database_demo.describe_table":
            if self.permission_filter is not None:
                return self._describe_table_with_permissions(
                    context,
                    str(arguments.get("table_name", "")),
                )
            return self.service.describe_table(context, str(arguments.get("table_name", "")))
        if resource_id == "database_demo.safe_select":
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
        verification = self.verification_service.verify(
            context,
            SqlResultVerifier(),
            {
                "result": result,
                "authorized_columns": authorized_columns,
            },
        )
        if not verification.passed:
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
                    stage="database_demo",
                    reason=reason,
                )
            )
            metadata.update(recovery_metadata(recovery))
        self.service.audit_service.record(
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


def _audit_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _anonymous_context() -> RequestContext:
    return RequestContext(
        request_id="database-demo-request",
        trace_id="database-demo-trace",
        user_id="anonymous",
        username="anonymous",
        department_id="unknown",
        department_name="Unknown",
        roles=[],
    )
