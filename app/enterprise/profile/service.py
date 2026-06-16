"""Aggregate current-user profile data for front-end consumption."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.enterprise.context import RequestContext
from app.enterprise.database.permissions import (
    DatabasePermissionFilter,
    database_column_resource_id,
    database_table_resource_id,
)
from app.enterprise.database.registry import build_default_sandbox_registry
from app.enterprise.database.service import DatabaseCapabilityCatalogService
from app.enterprise.documents.service import DocumentAccessService, document_access_service
from app.enterprise.permissions.service import PermissionService, permission_service
from app.enterprise.tools.gateway import ToolGateway
from app.enterprise.tools.local_provider import (
    build_local_agent_tool_gateway,
    list_local_agent_default_tool_ids,
)

DATABASE_DEMO_TOOL_IDS = [
    "database_demo.list_tables",
    "database_demo.describe_table",
    "database_demo.safe_select",
]


@dataclass
class ProfilePayload:
    user: dict
    visible_tools: list[str]
    visible_kb_ids: list[str]
    feature_flags: dict[str, bool]
    unavailable_reasons: dict[str, str]
    database_demo: dict
    capabilities: dict


class ProfileService:
    def __init__(
        self,
        *,
        document_access: DocumentAccessService | None = None,
        permission_service: PermissionService | None = None,
        tool_gateway: ToolGateway | None = None,
    ):
        self.document_access_service = document_access or document_access_service
        self.permission_service = permission_service or permission_service_default()
        self.tool_gateway = tool_gateway or build_local_agent_tool_gateway(
            permission_service=self.permission_service,
        )

    async def build_profile(
        self,
        context: RequestContext,
        *,
        include_gateway_tools: bool = True,
    ) -> dict:
        visible_tools = self._base_tools()
        unavailable_reasons: dict[str, str] = {}
        tool_gateway = self._tool_gateway_for_profile()

        if include_gateway_tools:
            try:
                gateway_tools = await tool_gateway.list_visible_tools(context)
                visible_tools.extend(tool.resource_id for tool in gateway_tools)
            except Exception as exc:  # pragma: no cover - best effort for UI profile
                unavailable_reasons["tool_gateway"] = type(exc).__name__

        visible_kb_ids = self.document_access_service.visible_kb_ids(context)
        database_catalog = await self._database_catalog(context)
        database_demo = self._database_demo_from_catalog(database_catalog)
        visible_tools.extend(database_catalog.get("visible_tools", []))

        feature_flags = {
            "rag_chat": True,
            "file_upload": True,
            "aiops": True,
            "admin": "admin" in context.roles or "department_admin" in context.roles,
            "database_demo": bool(database_demo["enabled"]),
            "execution_dashboard": True,
        }

        if not feature_flags["admin"]:
            unavailable_reasons["admin"] = "requires_admin_role"
        if not feature_flags["database_demo"]:
            unavailable_reasons.setdefault("database_demo", "permission_denied")

        payload = ProfilePayload(
            user={
                "user_id": context.user_id,
                "username": context.username,
                "department_id": context.department_id,
                "department_name": context.department_name,
                "roles": list(context.roles),
            },
            visible_tools=sorted(set(visible_tools)),
            visible_kb_ids=visible_kb_ids,
            feature_flags=feature_flags,
            unavailable_reasons=unavailable_reasons,
            database_demo=database_demo,
            capabilities=self._capability_health(
                visible_kb_ids=visible_kb_ids,
                database_demo=database_demo,
                database_catalog=database_catalog,
                unavailable_reasons=unavailable_reasons,
            ),
        )
        return asdict(payload)

    def _base_tools(self) -> list[str]:
        return list_local_agent_default_tool_ids()

    def _visible_database_tools(self, context: RequestContext) -> list[str]:
        if "admin" in context.roles:
            return list(DATABASE_DEMO_TOOL_IDS)
        return [
            tool_id
            for tool_id in DATABASE_DEMO_TOOL_IDS
            if self.permission_service.check(
                context,
                resource_type="tool",
                resource_id=tool_id,
                action="use",
            ).allowed
        ]

    def _database_demo_profile(
        self,
        context: RequestContext,
        database_tools: list[str],
    ) -> dict:
        registry = build_default_sandbox_registry()
        visible_tables: list[dict] = []

        if database_tools:
            permission_filter = DatabasePermissionFilter(
                registry=registry,
                permission_service=self.permission_service,
            )
            for table_name in registry.list_tables():
                table = registry.require_table(table_name)
                if not self._is_database_table_visible(context, permission_filter, table.name):
                    continue
                visible_columns = [
                    {
                        "column_name": column.name,
                        "resource_id": database_column_resource_id(
                            registry.database_id,
                            table.name,
                            column.name,
                        ),
                    }
                    for column in table.visible_columns()
                    if self._is_database_column_visible(
                        context,
                        permission_filter,
                        table.name,
                        column.name,
                    )
                ]
                visible_tables.append(
                    {
                        "table_name": table.name,
                        "resource_id": database_table_resource_id(
                            registry.database_id,
                            table.name,
                        ),
                        "visible_columns": visible_columns,
                    }
                )

        enabled = bool(database_tools) and bool(visible_tables)
        return {
            "enabled": enabled,
            "database_id": registry.database_id,
            "visible_tables": visible_tables,
            "readonly": True,
            "unavailable_reason": None if enabled else "permission_denied",
        }

    async def _database_catalog(self, context: RequestContext) -> dict:
        registry = build_default_sandbox_registry()
        return await DatabaseCapabilityCatalogService(
            registry=registry,
            permission_service=self.permission_service,
            tool_gateway=self._tool_gateway_for_profile(),
        ).build_catalog(context)

    def _database_demo_from_catalog(self, catalog: dict) -> dict:
        return {
            "enabled": bool(catalog.get("enabled")),
            "database_id": catalog.get("database_id"),
            "visible_tables": catalog.get("visible_tables") or [],
            "readonly": True,
            "unavailable_reason": catalog.get("unavailable_reason"),
        }

    def _capability_health(
        self,
        *,
        visible_kb_ids: list[str],
        database_demo: dict,
        database_catalog: dict,
        unavailable_reasons: dict[str, str],
    ) -> dict:
        document_worker = self._document_worker_health()
        tool_gateway_reason = unavailable_reasons.get("tool_gateway")
        return {
            "profile": {
                "status": "ok",
            },
            "knowledge_base_api": {
                "status": "ok",
                "details": {
                    "visible_kb_count": len(visible_kb_ids),
                },
            },
            "document_worker": document_worker,
            "database_catalog": {
                "status": "ok",
                "details": {
                    "database_id": database_demo.get("database_id"),
                    "enabled": bool(database_demo.get("enabled")),
                    "visible_table_count": len(database_demo.get("visible_tables") or []),
                    "visible_databases": database_catalog.get("visible_databases") or [],
                    "visible_tools": database_catalog.get("visible_tools") or [],
                    "safe_sql_kernel": database_catalog.get("safe_sql_kernel") or {},
                    "write_operations_enabled": bool(
                        database_catalog.get("write_operations_enabled")
                    ),
                    "confirmation_required_for": database_catalog.get(
                        "confirmation_required_for"
                    )
                    or [],
                    "last_audit_status": database_catalog.get("last_audit_status") or {},
                },
            },
            "tool_gateway": {
                "status": "degraded" if tool_gateway_reason else "ok",
                "reason": tool_gateway_reason,
            },
        }

    def _document_worker_health(self) -> dict:
        try:
            from app.services.document_processing_workflow import document_processing_workflow

            health = document_processing_workflow.worker_health()
        except Exception as exc:  # pragma: no cover - defensive profile health fallback
            return {
                "status": "unknown",
                "reason": type(exc).__name__,
                "details": {},
            }

        queue_enabled = bool(health.get("queue_enabled"))
        redis_connected = bool(health.get("redis_connected"))
        stale_count = int(health.get("stale_processing_count") or 0)
        worker_seen = health.get("worker_seen_recently")
        if stale_count > 0 or (queue_enabled and not redis_connected):
            status = "degraded"
        elif worker_seen == "unknown":
            status = "unknown"
        else:
            status = "ok"
        reason = None
        if stale_count > 0:
            reason = "stale_processing_documents"
        elif queue_enabled and not redis_connected:
            reason = "queue_unavailable"
        elif status == "unknown":
            reason = "worker_state_unknown"
        return {
            "status": status,
            "reason": reason,
            "details": health,
        }

    def _is_database_table_visible(
        self,
        context: RequestContext,
        permission_filter: DatabasePermissionFilter,
        table_name: str,
    ) -> bool:
        return "admin" in context.roles or permission_filter.is_table_allowed(context, table_name)

    def _is_database_column_visible(
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

    def _tool_gateway_for_profile(self) -> ToolGateway:
        if self.tool_gateway.permission_service is not self.permission_service:
            self.tool_gateway.permission_service = self.permission_service
        return self.tool_gateway


def permission_service_default() -> PermissionService:
    return permission_service


profile_service = ProfileService()
