"""Service wrapper for E6 database sandbox operations."""

from __future__ import annotations

import hashlib
import time
from typing import Any

from app.enterprise.context import RequestContext
from app.enterprise.database.permissions import (
    DatabasePermissionFilter,
    database_column_resource_id,
    database_table_resource_id,
)
from app.enterprise.database.registry import DatabaseSchemaRegistry
from app.enterprise.database.safe_sql import SafeSqlBlocked, SafeSqlKernel
from app.enterprise.errors.mapper import recovery_metadata
from app.enterprise.errors.models import ErrorClass, ErrorContext
from app.enterprise.errors.recovery import RecoveryStrategy
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.observability.models import AuditEvent
from app.enterprise.permissions.service import PermissionService
from app.enterprise.tools.gateway import ToolGateway


class DatabaseSandboxService:
    def __init__(
        self,
        *,
        registry: DatabaseSchemaRegistry,
        kernel: SafeSqlKernel,
        audit_service: AuditService | None = None,
    ):
        self.registry = registry
        self.kernel = kernel
        self.audit_service = audit_service or kernel.audit_service

    def list_tables(self, context: RequestContext) -> dict[str, Any]:
        started = time.perf_counter()
        tables = self.registry.list_tables()
        self._record_audit(
            context,
            decision="allowed",
            status="success",
            operation_type="list_tables",
            target_tables=tables,
            sql_hash=_operation_hash("list_tables"),
            rows_returned=len(tables),
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        return {
            "database_id": self.registry.database_id,
            "status": "success",
            "tables": tables,
        }

    def describe_table(self, context: RequestContext, table_name: str) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            description = self.registry.describe_table(table_name)
        except KeyError as exc:
            reason = "unauthorized_table"
            self._record_audit(
                context,
                decision="denied",
                status="blocked",
                operation_type="describe_table",
                target_tables=[table_name],
                sql_hash=_operation_hash(f"describe_table:{table_name}"),
                reason=reason,
                latency_ms=(time.perf_counter() - started) * 1000,
                error_class=ErrorClass.SQL_BLOCKED.value,
            )
            raise SafeSqlBlocked(reason) from exc

        self._record_audit(
            context,
            decision="allowed",
            status="success",
            operation_type="describe_table",
            target_tables=[description["table_name"]],
            sql_hash=_operation_hash(f"describe_table:{description['table_name']}"),
            rows_returned=len(description["columns"]),
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        description["status"] = "success"
        return description

    def safe_select(self, context: RequestContext, sql: str) -> dict[str, Any]:
        return self.kernel.safe_select(context, sql)

    def _record_audit(
        self,
        context: RequestContext,
        *,
        decision: str,
        status: str,
        operation_type: str,
        target_tables: list[str],
        sql_hash: str,
        reason: str | None = None,
        rows_returned: int = 0,
        latency_ms: float | None = None,
        error_class: str | None = None,
    ) -> None:
        metadata = {
            "database_id": self.registry.database_id,
            "tool_name": operation_type,
            "operation_type": operation_type,
            "target_tables": target_tables,
            "sql_hash": sql_hash,
            "sanitized_sql": "",
            "rows_returned": rows_returned,
            "result_size_bytes": 0,
            "status": status,
            "blocked_reason": reason,
        }
        if error_class == ErrorClass.SQL_BLOCKED.value:
            recovery = RecoveryStrategy().decide(
                ErrorContext(
                    error_class=ErrorClass.SQL_BLOCKED,
                    stage="database_sandbox",
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


class DatabaseCapabilityCatalogService:
    """Build the user-visible database capability catalog from one source."""

    def __init__(
        self,
        *,
        registry: DatabaseSchemaRegistry,
        permission_service: PermissionService,
        tool_gateway: ToolGateway,
    ):
        self.registry = registry
        self.permission_service = permission_service
        self.tool_gateway = tool_gateway

    async def build_catalog(self, context: RequestContext) -> dict[str, Any]:
        visible_tools = await self._visible_database_tools(context)
        can_read_database = self._can_read_database(context)
        visible_tables = self._visible_tables(
            context,
            enabled=bool(visible_tools),
        )
        enabled = can_read_database or (bool(visible_tools) and bool(visible_tables))
        visible_databases = [self.registry.database_id] if enabled else []
        safe_sql_status = "ok"

        return {
            "database_id": self.registry.database_id,
            "enabled": enabled,
            "visible_databases": visible_databases,
            "visible_tools": visible_tools,
            "visible_tables": visible_tables,
            "safe_sql_kernel": {
                "status": safe_sql_status,
                "read_only": True,
                "blocked_operations": ["insert", "update", "delete", "ddl"],
            },
            "write_operations_enabled": False,
            "confirmation_required_for": ["update", "delete", "ddl"],
            "last_audit_status": self._last_audit_status(),
            "unavailable_reason": None if enabled else "permission_denied",
        }

    def get_authorized_columns(
        self,
        context: RequestContext,
        *,
        database_id: str,
        table_name: str,
    ) -> list[str]:
        if database_id not in {self.registry.database_id, "database_demo"}:
            raise SafeSqlBlocked("database_not_allowed")

        permission_filter = DatabasePermissionFilter(
            registry=self.registry,
            permission_service=self.permission_service,
        )
        try:
            table = self.registry.require_table(table_name)
        except KeyError as exc:
            raise SafeSqlBlocked("unauthorized_table") from exc

        if not permission_filter.is_table_allowed(context, table.name):
            raise SafeSqlBlocked("database_table_denied")

        return [
            column.name
            for column in table.visible_columns()
            if permission_filter.is_column_allowed(context, table.name, column.name)
        ]

    async def _visible_database_tools(self, context: RequestContext) -> list[str]:
        if "admin" in context.roles:
            return [
                tool.resource_id
                for tool in await self.tool_gateway.list_visible_tools(context)
                if self._is_database_tool(tool.metadata, tool.resource_id)
            ]

        return [
            tool.resource_id
            for tool in await self.tool_gateway.list_visible_tools(context)
            if self._is_database_tool(tool.metadata, tool.resource_id)
        ]

    def _can_read_database(self, context: RequestContext) -> bool:
        if "admin" in context.roles:
            return True
        return self.permission_service.check(
            context,
            resource_type="database",
            resource_id=self.registry.database_id,
            action="read",
        ).allowed

    def _visible_tables(self, context: RequestContext, *, enabled: bool) -> list[dict[str, Any]]:
        if not enabled:
            return []
        permission_filter = DatabasePermissionFilter(
            registry=self.registry,
            permission_service=self.permission_service,
        )
        visible_tables: list[dict[str, Any]] = []
        for table_name in self.registry.list_tables():
            table = self.registry.require_table(table_name)
            if not self._is_table_visible(context, permission_filter, table.name):
                continue
            visible_columns = [
                {
                    "column_name": column.name,
                    "resource_id": database_column_resource_id(
                        self.registry.database_id,
                        table.name,
                        column.name,
                    ),
                }
                for column in table.visible_columns()
                if self._is_column_visible(context, permission_filter, table.name, column.name)
            ]
            visible_tables.append(
                {
                    "table_name": table.name,
                    "resource_id": database_table_resource_id(
                        self.registry.database_id,
                        table.name,
                    ),
                    "visible_columns": visible_columns,
                }
            )
        return visible_tables

    def _is_table_visible(
        self,
        context: RequestContext,
        permission_filter: DatabasePermissionFilter,
        table_name: str,
    ) -> bool:
        return "admin" in context.roles or permission_filter.is_table_allowed(context, table_name)

    def _is_column_visible(
        self,
        context: RequestContext,
        permission_filter: DatabasePermissionFilter,
        table_name: str,
        column_name: str,
    ) -> bool:
        return "admin" in context.roles or permission_filter.is_column_allowed(
            context,
            table_name,
            column_name,
        )

    def _last_audit_status(self) -> dict[str, Any]:
        return {
            "status": "unknown",
            "reason": "not_queried",
        }

    def _is_database_tool(self, metadata: dict[str, Any], resource_id: str) -> bool:
        return metadata.get("category") == "database" and (
            metadata.get("database_id") == self.registry.database_id
            or resource_id.startswith("database_demo.")
        )


def _operation_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
