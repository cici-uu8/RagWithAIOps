import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.auth as auth_api
import app.enterprise.admin.routes as admin_routes
from app.enterprise.admin.departments import department_service
from app.enterprise.admin.service import admin_service
from app.enterprise.auth.service import auth_service
from app.enterprise.context import RequestContext
from app.enterprise.database.audit import DatabaseAuditQueryService
from app.enterprise.database.provider import DatabaseDemoToolProvider
from app.enterprise.database.registry import build_default_sandbox_registry
from app.enterprise.database.safe_sql import SafeSqlBlocked, SafeSqlKernel
from app.enterprise.database.sandbox import create_sandbox_database
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService
from app.enterprise.profile import profile_service
from app.enterprise.tools.gateway import ToolExecutionError, ToolGateway


def build_database_permission_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    app.include_router(admin_routes.router, prefix="/api")
    return app


class EnterpriseDatabaseE7Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        auth_service.reset_users()
        auth_service.clear_blacklist()
        department_service.reset_departments()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db_path = Path(self.tmpdir.name) / "sandbox.sqlite3"
        create_sandbox_database(self.db_path)

        self.sink = InMemoryAuditSink()
        self.audit_service = AuditService(sinks=[self.sink])
        self.registry = build_default_sandbox_registry()
        self.kernel = SafeSqlKernel(
            database_path=self.db_path,
            registry=self.registry,
            audit_service=self.audit_service,
            default_limit=2,
            max_limit=5,
        )
        self.provider = DatabaseDemoToolProvider(
            registry=self.registry,
            kernel=self.kernel,
        )
        self.permission_service = PermissionService(
            repository=InMemoryGovernanceRepository(),
            audit_service=self.audit_service,
        )
        self.original_admin_permission_service = admin_service.permission_service
        self.original_profile_permission_service = profile_service.permission_service
        admin_service.permission_service = self.permission_service
        profile_service.permission_service = self.permission_service
        self.addCleanup(self._restore_global_services)
        self.client = TestClient(build_database_permission_app())
        self.context = RequestContext(
            request_id="request-e7",
            trace_id="trace-e7",
            user_id="user_demo_dept1",
            username="demo_user_dept1",
            department_id="dept_1",
            department_name="Department 1",
            roles=["user"],
        )

    def _restore_global_services(self) -> None:
        admin_service.permission_service = self.original_admin_permission_service
        profile_service.permission_service = self.original_profile_permission_service
        auth_service.reset_users()
        auth_service.clear_blacklist()
        department_service.reset_departments()

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

    def login(self, username: str = "admin", password: str = "Admin123!") -> str:
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["access_token"]

    def grant_via_admin_api(
        self,
        token: str,
        *,
        resource_type: str,
        resource_id: str,
        action: str,
    ) -> str:
        response = self.client.post(
            "/api/admin/grants",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "resource_type": resource_type,
                "resource_id": resource_id,
                "action": action,
                "principal_type": "user",
                "principal_id": "user_demo_dept1",
                "effect": "allow",
                "reason": "Stage 6.3 database permission e2e",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["grant"]["grant_id"]

    def grant_database_demo_access(self, token: str) -> str:
        for tool_id in (
            "database_demo.list_tables",
            "database_demo.describe_table",
            "database_demo.safe_select",
        ):
            self.grant_via_admin_api(
                token,
                resource_type="tool",
                resource_id=tool_id,
                action="use",
            )
        self.grant_via_admin_api(
            token,
            resource_type="database_table",
            resource_id="sandbox_sales.factory_access_events",
            action="read",
        )
        for column_id in (
            "sandbox_sales.factory_access_events.event_id",
            "sandbox_sales.factory_access_events.direction",
        ):
            self.grant_via_admin_api(
                token,
                resource_type="database_column",
                resource_id=column_id,
                action="read",
            )
        list_response = self.client.get(
            "/api/admin/grants?resource_type=database_table&resource_id=sandbox_sales.factory_access_events",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(list_response.status_code, 200, list_response.text)
        return list_response.json()["data"]["grants"][0]["grant_id"]

    def get_profile(self, token: str) -> dict:
        response = self.client.get(
            "/api/me/profile",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def permissioned_database_gateway(self) -> ToolGateway:
        provider = DatabaseDemoToolProvider(
            registry=self.registry,
            kernel=self.kernel,
            permission_service=self.permission_service,
        )
        return ToolGateway(
            providers=[provider],
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )

    async def test_admin_granted_database_permissions_enable_profile_and_safe_select(self):
        admin_token = self.login()
        user_token = self.login(username="demo_user_dept1", password="Demo123!")

        before_profile = self.get_profile(user_token)
        self.assertFalse(before_profile["database_demo"]["enabled"])

        self.grant_database_demo_access(admin_token)

        profile = self.get_profile(user_token)
        self.assertTrue(profile["database_demo"]["enabled"])
        self.assertEqual(
            profile["database_demo"]["visible_tables"],
            [
                {
                    "table_name": "factory_access_events",
                    "resource_id": "sandbox_sales.factory_access_events",
                    "visible_columns": [
                        {
                            "column_name": "event_id",
                            "resource_id": "sandbox_sales.factory_access_events.event_id",
                        },
                        {
                            "column_name": "direction",
                            "resource_id": "sandbox_sales.factory_access_events.direction",
                        },
                    ],
                }
            ],
        )

        gateway = self.permissioned_database_gateway()
        result = await gateway.execute(
            self.context,
            "database_demo.safe_select",
            {"sql": "select event_id, direction from factory_access_events order by event_id limit 2"},
        )

        self.assertEqual(result["columns"], ["event_id", "direction"])
        self.assertEqual(
            result["rows"],
            [
                {"event_id": 1001, "direction": "entry"},
                {"event_id": 1002, "direction": "exit"},
            ],
        )

    async def test_admin_granted_database_permissions_still_block_dml_and_ddl(self):
        admin_token = self.login()
        self.grant_database_demo_access(admin_token)
        gateway = self.permissioned_database_gateway()

        with self.assertRaises(ToolExecutionError) as blocked_update:
            await gateway.execute(
                self.context,
                "database_demo.safe_select",
                {"sql": "update factory_access_events set direction = 'exit' where event_id = 1001"},
            )

        self.assertIsInstance(blocked_update.exception.cause, SafeSqlBlocked)
        self.assertEqual(
            blocked_update.exception.cause.reason,
            "non_select_statement_not_allowed",
        )

        with self.assertRaises(ToolExecutionError) as blocked_create:
            await gateway.execute(
                self.context,
                "database_demo.safe_select",
                {"sql": "create table shadow_orders(id integer)"},
            )

        self.assertIsInstance(blocked_create.exception.cause, SafeSqlBlocked)
        self.assertEqual(
            blocked_create.exception.cause.reason,
            "non_select_statement_not_allowed",
        )

    async def test_revoking_database_table_grant_disables_database_demo_profile(self):
        admin_token = self.login()
        user_token = self.login(username="demo_user_dept1", password="Demo123!")

        table_grant_id = self.grant_database_demo_access(admin_token)
        profile = self.get_profile(user_token)
        self.assertTrue(profile["database_demo"]["enabled"])

        revoke_response = self.client.delete(
            f"/api/admin/grants/{table_grant_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        self.assertEqual(revoke_response.status_code, 200, revoke_response.text)
        self.assertTrue(revoke_response.json()["data"]["revoked"])

        profile_after_revoke = self.get_profile(user_token)
        self.assertFalse(profile_after_revoke["database_demo"]["enabled"])
        self.assertEqual(profile_after_revoke["database_demo"]["visible_tables"], [])
        self.assertEqual(
            profile_after_revoke["database_demo"]["unavailable_reason"],
            "permission_denied",
        )

        gateway = self.permissioned_database_gateway()
        with self.assertRaises(ToolExecutionError) as denied_after_revoke:
            await gateway.execute(
                self.context,
                "database_demo.safe_select",
                {"sql": "select event_id, direction from factory_access_events order by event_id limit 1"},
            )

        self.assertIsInstance(denied_after_revoke.exception.cause, SafeSqlBlocked)
        self.assertEqual(denied_after_revoke.exception.cause.reason, "database_table_denied")

    async def test_database_tools_are_visible_by_tool_permission_without_include_flag(self):
        self.grant("tool", "database_demo.safe_select", action="use")
        gateway = ToolGateway(
            providers=[self.provider],
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )

        visible = await gateway.list_visible_tools(self.context)

        self.assertEqual([tool.resource_id for tool in visible], ["database_demo.safe_select"])
        visible_audit = self.sink.events[-1]
        self.assertEqual(visible_audit.event_type, "tool_visible")
        self.assertEqual(visible_audit.metadata["visible_tool_ids"], ["database_demo.safe_select"])
        self.assertEqual(visible_audit.metadata["filtered_tool_ids"], [])
        self.assertIn(
            "database_demo.safe_select",
            [tool.resource_id for tool in gateway.registry.list_exposable()],
        )

    async def test_safe_select_requires_table_and_column_permissions(self):
        provider = DatabaseDemoToolProvider(
            registry=self.registry,
            kernel=self.kernel,
            permission_service=self.permission_service,
        )
        gateway = ToolGateway(
            providers=[provider],
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )
        self.grant("tool", "database_demo.safe_select", action="use")
        query = "select event_id, direction from factory_access_events order by event_id limit 2"

        with self.assertRaises(ToolExecutionError) as denied_table:
            await gateway.execute(self.context, "database_demo.safe_select", {"sql": query})

        self.assertIsInstance(denied_table.exception.cause, SafeSqlBlocked)
        self.assertEqual(denied_table.exception.cause.reason, "database_table_denied")
        self.assertTrue(
            any(
                event.event_type == "database_query"
                and event.decision == "denied"
                and event.reason == "database_table_denied"
                for event in self.sink.events
            )
        )

        self.grant("database_table", "sandbox_sales.factory_access_events")
        self.grant("database_column", "sandbox_sales.factory_access_events.event_id")
        self.grant("database_column", "sandbox_sales.factory_access_events.direction")

        result = await gateway.execute(self.context, "database_demo.safe_select", {"sql": query})

        self.assertEqual(result["columns"], ["event_id", "direction"])
        self.assertEqual(
            result["rows"],
            [
                {"event_id": 1001, "direction": "entry"},
                {"event_id": 1002, "direction": "exit"},
            ],
        )

        with self.assertRaises(ToolExecutionError) as denied_column:
            await gateway.execute(
                self.context,
                "database_demo.safe_select",
                {"sql": "select event_id, badge_id from factory_access_events limit 1"},
            )

        self.assertIsInstance(denied_column.exception.cause, SafeSqlBlocked)
        self.assertEqual(denied_column.exception.cause.reason, "database_column_denied")
        self.assertTrue(
            any(
                event.event_type == "database_query"
                and event.decision == "denied"
                and event.reason == "database_column_denied"
                and event.metadata["target_tables"] == ["factory_access_events"]
                for event in self.sink.events
            )
        )

    async def test_list_and_describe_filter_database_schema_by_permissions(self):
        provider = DatabaseDemoToolProvider(
            registry=self.registry,
            kernel=self.kernel,
            permission_service=self.permission_service,
        )
        gateway = ToolGateway(
            providers=[provider],
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )
        self.grant("tool", "database_demo.list_tables", action="use")
        self.grant("tool", "database_demo.describe_table", action="use")
        self.grant("database_table", "sandbox_sales.factory_access_events")
        self.grant("database_column", "sandbox_sales.factory_access_events.event_id")
        self.grant("database_column", "sandbox_sales.factory_access_events.direction")

        tables = await gateway.execute(self.context, "database_demo.list_tables", {})
        description = await gateway.execute(
            self.context,
            "database_demo.describe_table",
            {"table_name": "factory_access_events"},
        )

        self.assertEqual(tables["tables"], ["factory_access_events"])
        self.assertEqual(
            [column["name"] for column in description["columns"]],
            ["event_id", "direction"],
        )

        with self.assertRaises(ToolExecutionError) as denied_table:
            await gateway.execute(
                self.context,
                "database_demo.describe_table",
                {"table_name": "building_access_events"},
            )

        self.assertIsInstance(denied_table.exception.cause, SafeSqlBlocked)
        self.assertEqual(denied_table.exception.cause.reason, "database_table_denied")

    async def test_database_audit_queries_filter_by_trace_user_and_table(self):
        self.grant("tool", "database_demo.list_tables", action="use")
        self.grant("tool", "database_demo.describe_table", action="use")
        self.grant("tool", "database_demo.safe_select", action="use")
        self.grant("database_table", "sandbox_sales.factory_access_events")
        self.grant("database_column", "sandbox_sales.factory_access_events.event_id")
        self.grant("database_column", "sandbox_sales.factory_access_events.direction")
        provider = DatabaseDemoToolProvider(
            registry=self.registry,
            kernel=self.kernel,
            permission_service=self.permission_service,
        )
        gateway = ToolGateway(
            providers=[provider],
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )

        await gateway.execute(self.context, "database_demo.list_tables", {})
        await gateway.execute(
            self.context,
            "database_demo.describe_table",
            {"table_name": "factory_access_events"},
        )
        await gateway.execute(
            self.context,
            "database_demo.safe_select",
            {"sql": "select event_id, direction from factory_access_events order by event_id limit 1"},
        )
        with self.assertRaises(ToolExecutionError):
            await gateway.execute(
                self.context,
                "database_demo.safe_select",
                {"sql": "select event_id, badge_id from factory_access_events limit 1"},
            )

        query_service = DatabaseAuditQueryService(events=self.sink.events)
        events = query_service.query(
            trace_id="trace-e7",
            user_id="user_demo_dept1",
            table_name="factory_access_events",
        )

        self.assertGreaterEqual(len(events), 4)
        self.assertTrue(all(event.event_type == "database_query" for event in events))
        self.assertTrue(any(event.decision == "allowed" for event in events))
        self.assertTrue(any(event.reason == "database_column_denied" for event in events))
        self.assertEqual(
            query_service.query(trace_id="trace-missing", user_id="user_demo_dept1"),
            [],
        )

    async def test_write_operations_still_blocked_by_safe_sql_kernel_after_permissions(self):
        self.grant("tool", "database_demo.safe_select", action="use")
        self.grant("database_table", "sandbox_sales.factory_access_events")
        for column_name in ("event_id", "employee_name", "badge_id", "direction", "event_time"):
            self.grant("database_column", f"sandbox_sales.factory_access_events.{column_name}")
        provider = DatabaseDemoToolProvider(
            registry=self.registry,
            kernel=self.kernel,
            permission_service=self.permission_service,
        )
        gateway = ToolGateway(
            providers=[provider],
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )

        with self.assertRaises(ToolExecutionError) as blocked:
            await gateway.execute(
                self.context,
                "database_demo.safe_select",
                {"sql": "update factory_access_events set direction = 'exit' where event_id = 1001"},
            )

        self.assertIsInstance(blocked.exception.cause, SafeSqlBlocked)
        self.assertEqual(blocked.exception.cause.reason, "non_select_statement_not_allowed")
        audit = [
            event
            for event in self.sink.events
            if event.event_type == "database_query" and event.decision == "denied"
        ][-1]
        self.assertEqual(audit.reason, "non_select_statement_not_allowed")
        self.assertEqual(audit.metadata["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
