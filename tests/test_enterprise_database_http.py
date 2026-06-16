import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.auth as auth_api
import app.enterprise.database.routes as database_routes
from app.enterprise.auth.service import auth_service
from app.enterprise.context import RequestContext
from app.enterprise.database.provider import DatabaseDemoToolProvider
from app.enterprise.database.registry import build_default_sandbox_registry
from app.enterprise.database.safe_sql import SafeSqlKernel
from app.enterprise.database.sandbox import create_sandbox_database
from app.enterprise.gateway.guardrail_providers import NoOpGuardrailProvider
from app.enterprise.gateway.guardrail_service import GuardrailService
from app.enterprise.gateway.rate_limit_service import NoOpRateLimitService
from app.enterprise.gateway.request_gateway import RequestGateway
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService
from app.enterprise.profile import profile_service
from app.enterprise.tools.gateway import ToolGateway


def build_database_http_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    app.include_router(database_routes.router, prefix="/api")
    return app


class EnterpriseDatabaseHttpTests(unittest.TestCase):
    def setUp(self):
        auth_service.reset_users()
        auth_service.clear_blacklist()
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
        self.original_database_request_gateway = database_routes.gateway
        self.original_profile_permission_service = profile_service.permission_service
        self.original_profile_tool_gateway = profile_service.tool_gateway
        database_routes.database_tool_gateway = self.gateway
        database_routes.gateway = RequestGateway(
            audit_service=self.audit_service,
            guardrail_service=GuardrailService(providers=[NoOpGuardrailProvider()]),
            rate_limit_service=NoOpRateLimitService(),
        )
        profile_service.permission_service = self.permission_service
        profile_service.tool_gateway = self.gateway
        self.addCleanup(self._restore_database_routes)
        self.client = TestClient(build_database_http_app())
        self.context = RequestContext(
            request_id="request-db-http",
            trace_id="trace-db-http",
            user_id="user_demo_dept1",
            username="demo_user_dept1",
            department_id="dept_1",
            department_name="Department 1",
            roles=["user"],
        )

    def _restore_database_routes(self) -> None:
        database_routes.database_tool_gateway = self.original_database_tool_gateway
        database_routes.gateway = self.original_database_request_gateway
        profile_service.permission_service = self.original_profile_permission_service
        profile_service.tool_gateway = self.original_profile_tool_gateway
        auth_service.reset_users()
        auth_service.clear_blacklist()

    def login(self, username: str = "demo_user_dept1", password: str = "Demo123!") -> str:
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["access_token"]

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

    def grant_safe_select_access(self) -> None:
        self.grant("tool", "database_demo.safe_select", action="use")
        self.grant("database_table", "sandbox_sales.factory_access_events")
        self.grant("database_column", "sandbox_sales.factory_access_events.event_id")
        self.grant("database_column", "sandbox_sales.factory_access_events.direction")

    def post_safe_select(self, token: str | None, sql: str, database_id: str | None = None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        body = {"sql": sql}
        if database_id is not None:
            body["database_id"] = database_id
        return self.client.post(
            "/api/database/safe-select",
            headers=headers,
            json=body,
        )

    def get_sample_rows(
        self,
        token: str | None,
        *,
        database_id: str = "sandbox_sales",
        table_name: str = "factory_access_events",
        limit: int = 2,
    ):
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Trace-Id": "trace-db-sample",
            "X-Request-Id": "request-db-sample",
        } if token else {}
        return self.client.get(
            f"/api/database/{database_id}/tables/{table_name}/sample",
            headers=headers,
            params={"limit": limit},
        )

    def test_safe_select_http_returns_allowed_rows(self):
        self.grant_safe_select_access()
        token = self.login()

        response = self.post_safe_select(
            token,
            "select event_id, direction from factory_access_events order by event_id limit 2",
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["code"], 200)
        result = payload["data"]["result"]
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
        self.assertTrue(
            any(
                event.event_type == "database_query"
                and event.decision == "allowed"
                and event.metadata["operation_type"] == "safe_select"
                for event in self.sink.events
            )
        )

    def test_safe_select_http_requires_login(self):
        response = self.post_safe_select(None, "select event_id from factory_access_events limit 1")

        self.assertEqual(response.status_code, 401, response.text)

    def test_safe_select_http_requires_tool_permission(self):
        token = self.login()

        response = self.post_safe_select(token, "select event_id from factory_access_events limit 1")

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], "default_deny")
        self.assertTrue(
            any(
                event.event_type == "tool_blocked"
                and event.reason == "default_deny"
                and event.metadata["tool_id"] == "database_demo.safe_select"
                for event in self.sink.events
            )
        )

    def test_safe_select_http_requires_table_permission(self):
        self.grant("tool", "database_demo.safe_select", action="use")
        token = self.login()

        response = self.post_safe_select(token, "select event_id from factory_access_events limit 1")

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], "database_table_denied")
        self.assertTrue(
            any(
                event.event_type == "database_query"
                and event.decision == "denied"
                and event.reason == "database_table_denied"
                for event in self.sink.events
            )
        )

    def test_safe_select_http_requires_column_permission(self):
        self.grant("tool", "database_demo.safe_select", action="use")
        self.grant("database_table", "sandbox_sales.factory_access_events")
        self.grant("database_column", "sandbox_sales.factory_access_events.event_id")
        token = self.login()

        response = self.post_safe_select(
            token,
            "select event_id, direction from factory_access_events limit 1",
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], "database_column_denied")
        self.assertTrue(
            any(
                event.event_type == "database_query"
                and event.decision == "denied"
                and event.reason == "database_column_denied"
                and event.metadata["denied_columns"] == ["direction"]
                for event in self.sink.events
            )
        )

    def test_safe_select_http_blocks_dml_and_ddl(self):
        self.grant_safe_select_access()
        token = self.login()

        update_response = self.post_safe_select(
            token,
            "update factory_access_events set direction = 'exit' where event_id = 1001",
        )
        drop_response = self.post_safe_select(token, "drop table factory_access_events")

        self.assertEqual(update_response.status_code, 403, update_response.text)
        self.assertEqual(update_response.json()["detail"], "non_select_statement_not_allowed")
        self.assertEqual(drop_response.status_code, 403, drop_response.text)
        self.assertEqual(drop_response.json()["detail"], "non_select_statement_not_allowed")
        self.assertGreaterEqual(
            sum(
                1
                for event in self.sink.events
                if event.event_type == "database_query"
                and event.decision == "denied"
                and event.reason == "non_select_statement_not_allowed"
            ),
            2,
        )

    def test_safe_select_http_defaults_to_sandbox_database_id(self):
        self.grant_safe_select_access()
        token = self.login()

        response = self.post_safe_select(
            token,
            "select event_id, direction from factory_access_events order by event_id limit 1",
        )

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["data"]["result"]
        self.assertEqual(result["database_id"], "sandbox_sales")
        self.assertTrue(
            any(
                event.event_type == "tool_call"
                and event.metadata["tool_id"] == "database_demo.safe_select"
                for event in self.sink.events
            )
        )

    def test_safe_select_http_unknown_database_id_does_not_fall_back_to_sandbox(self):
        self.grant_safe_select_access()
        token = self.login()

        response = self.post_safe_select(
            token,
            "select event_id, direction from factory_access_events order by event_id limit 1",
            database_id="missing_database",
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], "tool_not_found")
        self.assertFalse(
            any(
                event.event_type == "database_query"
                and event.decision == "allowed"
                for event in self.sink.events
            )
        )

    def test_database_catalog_profile_and_gateway_visibility_are_consistent(self):
        self.grant("tool", "database_demo.list_tables", action="use")
        self.grant("tool", "database_demo.describe_table", action="use")
        self.grant("tool", "database_demo.safe_select", action="use")
        self.grant("database_table", "sandbox_sales.factory_access_events")
        self.grant("database_column", "sandbox_sales.factory_access_events.event_id")
        self.grant("database_column", "sandbox_sales.factory_access_events.direction")
        token = self.login()

        catalog_response = self.client.get(
            "/api/database/catalog",
            headers={"Authorization": f"Bearer {token}"},
        )
        profile_response = self.client.get(
            "/api/me/profile",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(catalog_response.status_code, 200, catalog_response.text)
        self.assertEqual(profile_response.status_code, 200, profile_response.text)

        catalog = catalog_response.json()["data"]["catalog"]
        profile = profile_response.json()["data"]
        gateway_tool_ids = [
            tool.resource_id
            for tool in asyncio.run(self.gateway.list_visible_tools(self.context))
            if tool.metadata.get("category") == "database"
        ]

        self.assertEqual(catalog["database_id"], "sandbox_sales")
        self.assertEqual(catalog["visible_tools"], gateway_tool_ids)
        self.assertEqual(catalog["visible_databases"], ["sandbox_sales"])
        self.assertEqual(catalog["safe_sql_kernel"]["status"], "ok")
        self.assertFalse(catalog["write_operations_enabled"])
        self.assertEqual(catalog["confirmation_required_for"], ["update", "delete", "ddl"])
        self.assertEqual(
            [table["table_name"] for table in catalog["visible_tables"]],
            ["factory_access_events"],
        )
        self.assertEqual(
            [column["column_name"] for column in catalog["visible_tables"][0]["visible_columns"]],
            ["event_id", "direction"],
        )
        self.assertEqual(
            profile["capabilities"]["database_catalog"]["details"]["visible_tools"],
            catalog["visible_tools"],
        )
        self.assertEqual(
            profile["capabilities"]["database_catalog"]["details"]["visible_databases"],
            catalog["visible_databases"],
        )
        self.assertEqual(
            profile["database_demo"]["visible_tables"],
            catalog["visible_tables"],
        )

    def test_database_sample_rows_use_gateway_and_only_authorized_columns(self):
        self.grant_safe_select_access()
        token = self.login()

        response = self.get_sample_rows(token)

        self.assertEqual(response.status_code, 200, response.text)
        sample = response.json()["data"]["sample"]
        self.assertEqual(sample["database_id"], "sandbox_sales")
        self.assertEqual(sample["table_name"], "factory_access_events")
        self.assertEqual(sample["columns"], ["event_id", "direction"])
        self.assertEqual(
            sample["rows"],
            [
                {"event_id": 1001, "direction": "entry"},
                {"event_id": 1002, "direction": "exit"},
            ],
        )
        self.assertTrue(sample["safe_sql_verified"])
        self.assertIsNone(sample["total_rows_estimate"])
        self.assertNotIn("raw_device_payload", sample["columns"])
        self.assertTrue(
            any(
                event.event_type == "request_started"
                and event.route == "database_catalog_sample_rows"
                and event.trace_id == "trace-db-sample"
                for event in self.sink.events
            )
        )
        self.assertTrue(
            any(
                event.event_type == "request_completed"
                and event.route == "database_catalog_sample_rows"
                and event.request_id == "request-db-sample"
                for event in self.sink.events
            )
        )
        self.assertTrue(
            any(
                event.event_type == "tool_call"
                and event.metadata["tool_id"] == "database_demo.safe_select"
                for event in self.sink.events
            )
        )
        self.assertTrue(
            any(
                event.event_type == "database_query"
                and event.decision == "allowed"
                and event.metadata["operation_type"] == "safe_select"
                for event in self.sink.events
            )
        )

    def test_database_sample_rows_require_table_permission(self):
        self.grant("tool", "database_demo.safe_select", action="use")
        self.grant("database_column", "sandbox_sales.factory_access_events.event_id")
        token = self.login()

        response = self.get_sample_rows(token)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], "database_table_denied")
        self.assertTrue(
            any(
                event.event_type == "request_failed"
                and event.route == "database_catalog_sample_rows"
                for event in self.sink.events
            )
        )

    def test_database_sample_rows_require_at_least_one_authorized_column(self):
        self.grant("tool", "database_demo.safe_select", action="use")
        self.grant("database_table", "sandbox_sales.factory_access_events")
        token = self.login()

        response = self.get_sample_rows(token)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], "database_column_denied")
        self.assertFalse(
            any(
                event.event_type == "tool_call"
                and event.metadata["tool_id"] == "database_demo.safe_select"
                for event in self.sink.events
            )
        )

    def test_database_tool_gateway_recreates_stale_sandbox_fixture(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            stale_db_path = Path(tmpdir) / "database_demo.sqlite3"
            with sqlite3.connect(stale_db_path) as connection:
                connection.execute("create table orders(order_id integer primary key)")

            database_routes.build_database_tool_gateway(stale_db_path)

            with sqlite3.connect(stale_db_path) as connection:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "select name from sqlite_master where type = 'table'"
                    )
                }
                rows = connection.execute(
                    "select event_id, direction from factory_access_events order by event_id limit 2"
                ).fetchall()

        self.assertIn("factory_access_events", table_names)
        self.assertIn("building_access_events", table_names)
        self.assertEqual(rows, [(1001, "entry"), (1002, "exit")])

    def test_database_catalog_accepts_database_read_grant_without_tool_execution_grant(self):
        self.grant("database", "sandbox_sales", action="read")
        token = self.login()

        catalog_response = self.client.get(
            "/api/database/catalog",
            headers={"Authorization": f"Bearer {token}"},
        )
        profile_response = self.client.get(
            "/api/me/profile",
            headers={"Authorization": f"Bearer {token}"},
        )
        safe_select_response = self.post_safe_select(
            token,
            "select event_id from factory_access_events limit 1",
        )

        self.assertEqual(catalog_response.status_code, 200, catalog_response.text)
        self.assertEqual(profile_response.status_code, 200, profile_response.text)
        catalog = catalog_response.json()["data"]["catalog"]
        profile = profile_response.json()["data"]

        self.assertTrue(catalog["enabled"])
        self.assertEqual(catalog["visible_databases"], ["sandbox_sales"])
        self.assertEqual(catalog["visible_tools"], [])
        self.assertEqual(catalog["visible_tables"], [])
        self.assertIsNone(catalog["unavailable_reason"])
        self.assertEqual(
            profile["capabilities"]["database_catalog"]["details"]["visible_databases"],
            ["sandbox_sales"],
        )
        self.assertTrue(profile["database_demo"]["enabled"])
        self.assertEqual(safe_select_response.status_code, 403, safe_select_response.text)
        self.assertEqual(safe_select_response.json()["detail"], "default_deny")


if __name__ == "__main__":
    unittest.main()
