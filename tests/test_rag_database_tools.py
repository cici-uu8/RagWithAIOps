import tempfile
import unittest
from pathlib import Path

import app.enterprise.database.routes as database_routes
from app.enterprise.context import (
    RequestContext,
    reset_current_request_context,
    set_current_request_context,
)
from app.enterprise.database.provider import DatabaseDemoToolProvider
from app.enterprise.database.registry import build_default_sandbox_registry
from app.enterprise.database.safe_sql import SafeSqlKernel
from app.enterprise.database.sandbox import create_sandbox_database
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService
from app.enterprise.tools.gateway import ToolGateway


class RagDatabaseToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db_path = Path(self.tmpdir.name) / "sandbox.sqlite3"
        create_sandbox_database(self.db_path)

        self.sink = InMemoryAuditSink()
        self.audit_service = AuditService(sinks=[self.sink])
        self.permission_service = PermissionService(
            repository=InMemoryGovernanceRepository(),
            audit_service=self.audit_service,
        )
        self.registry = build_default_sandbox_registry()
        self.kernel = SafeSqlKernel(
            database_path=self.db_path,
            registry=self.registry,
            audit_service=self.audit_service,
            default_limit=2,
            max_limit=5,
        )
        provider = DatabaseDemoToolProvider(
            registry=self.registry,
            kernel=self.kernel,
            permission_service=self.permission_service,
        )
        self.gateway = ToolGateway(
            providers=[provider],
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )
        self.original_database_tool_gateway = database_routes.database_tool_gateway
        database_routes.database_tool_gateway = self.gateway
        self.addCleanup(self._restore_database_routes)

        self.context = RequestContext(
            request_id="request-rag-db",
            trace_id="trace-rag-db",
            user_id="user_demo_dept1",
            username="demo_user_dept1",
            department_id="dept_1",
            department_name="Department 1",
            roles=["user"],
        )

    def _restore_database_routes(self) -> None:
        database_routes.database_tool_gateway = self.original_database_tool_gateway

    def grant(self, resource_type: str, resource_id: str, action: str = "read") -> None:
        self.permission_service.grant_access(
            ResourceGrant(
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                principal_type=PrincipalType.USER,
                principal_id="user_demo_dept1",
                effect=GrantEffect.ALLOW,
            )
        )

    def grant_read_only_database_access(self) -> None:
        for resource_id in (
            "database_demo.list_tables",
            "database_demo.describe_table",
            "database_demo.safe_select",
        ):
            self.grant("tool", resource_id, action="use")
        self.grant("database_table", "sandbox_sales.factory_access_events")
        self.grant("database_column", "sandbox_sales.factory_access_events.event_id")
        self.grant("database_column", "sandbox_sales.factory_access_events.direction")

    def test_rag_agent_binds_only_read_only_database_tools(self):
        import app.services.rag_agent_service as rag_agent_service_module

        tool_names = [tool.name for tool in rag_agent_service_module.RagAgentService().tools]

        self.assertIn("list_database_tables", tool_names)
        self.assertIn("describe_database_table", tool_names)
        self.assertIn("safe_select_database", tool_names)
        self.assertNotIn("prepare_database_operation", tool_names)
        self.assertNotIn("confirm_database_operation", tool_names)

    async def test_read_only_database_tools_execute_through_gateway(self):
        from app.tools.database_tool import (
            describe_database_table,
            list_database_tables,
            safe_select_database,
        )

        self.grant_read_only_database_access()
        token = set_current_request_context(self.context)
        self.addCleanup(reset_current_request_context, token)

        tables = await list_database_tables.ainvoke({"database_id": "sandbox_sales"})
        description = await describe_database_table.ainvoke(
            {"database_id": "sandbox_sales", "table_name": "factory_access_events"}
        )
        result = await safe_select_database.ainvoke(
            {
                "database_id": "sandbox_sales",
                "sql": "select event_id, direction from factory_access_events order by event_id limit 2",
            }
        )

        self.assertEqual(tables["status"], "success")
        self.assertEqual(tables["tables"], ["factory_access_events"])
        self.assertEqual(description["status"], "success")
        self.assertEqual(
            [column["name"] for column in description["columns"]],
            ["event_id", "direction"],
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["columns"], ["event_id", "direction"])
        self.assertEqual(
            result["rows"],
            [
                {"event_id": 1001, "direction": "entry"},
                {"event_id": 1002, "direction": "exit"},
            ],
        )
        self.assertTrue(
            any(
                event.event_type == "tool_call"
                and event.metadata["tool_id"] == "database_demo.safe_select"
                for event in self.sink.events
            )
        )

    async def test_database_tool_denies_without_tool_grant(self):
        from app.tools.database_tool import safe_select_database

        token = set_current_request_context(self.context)
        self.addCleanup(reset_current_request_context, token)

        result = await safe_select_database.ainvoke(
            {
                "database_id": "sandbox_sales",
                "sql": "select event_id from factory_access_events",
            }
        )

        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["reason"], "default_deny")
        self.assertTrue(
            any(
                event.event_type == "tool_blocked"
                and event.metadata["tool_id"] == "database_demo.safe_select"
                for event in self.sink.events
            )
        )


if __name__ == "__main__":
    unittest.main()
