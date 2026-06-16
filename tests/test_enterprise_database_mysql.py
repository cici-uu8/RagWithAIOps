import asyncio
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.auth as auth_api
import app.enterprise.database.routes as database_routes
from app.config import config
from app.enterprise.admin.resources import ResourceCatalogService
from app.enterprise.auth.service import auth_service
from app.enterprise.context import RequestContext
from app.enterprise.database.mysql import (
    DatabaseMySqlToolProvider,
    MySqlConnectionSettings,
    MySqlSafeSqlKernel,
    PooledMySqlReadonlyConnector,
    PooledMySqlWritableConnector,
    build_mysql_provider_from_config,
)
from app.enterprise.database.permissions import database_operation_resource_id
from app.enterprise.database.registry import ColumnPolicy, DatabaseSchemaRegistry, TablePolicy
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService
from app.enterprise.tools.gateway import ToolGateway


def build_database_mysql_http_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    app.include_router(database_routes.router, prefix="/api")
    return app


class FakeMySqlConnector:
    def __init__(self):
        self.executed_sql: list[str] = []
        self.rows = [
            {"order_id": 2001, "total_amount": 42.5},
            {"order_id": 2002, "total_amount": 63.0},
        ]

    def execute_readonly(self, sql: str, *, timeout_seconds: float) -> list[dict]:
        self.executed_sql.append(sql)
        return self.rows


class FakeMySqlCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql: str) -> None:
        self.connection.executed_sql.append(sql)
        self.rowcount = 1 if sql.strip().lower().startswith(("insert", "update", "delete")) else -1

    def fetchall(self) -> list[dict]:
        return [{"order_id": 2001, "total_amount": 42.5}]


class FakeMySqlConnection:
    def __init__(self):
        self.executed_sql: list[str] = []
        self.rollbacks = 0

    def cursor(self) -> FakeMySqlCursor:
        return FakeMySqlCursor(self)

    def rollback(self) -> None:
        self.rollbacks += 1


class EnterpriseDatabaseMySqlTests(unittest.TestCase):
    def setUp(self):
        auth_service.reset_users()
        auth_service.clear_blacklist()
        self.sink = InMemoryAuditSink()
        self.audit_service = AuditService(sinks=[self.sink])
        self.permission_service = PermissionService(
            repository=InMemoryGovernanceRepository(),
            audit_service=self.audit_service,
        )
        self.registry = DatabaseSchemaRegistry(
            database_id="mysql_sales_readonly",
            tables={
                "orders": TablePolicy(
                    name="orders",
                    description="Read-only MySQL order records.",
                    columns={
                        "order_id": ColumnPolicy("order_id", "BIGINT"),
                        "total_amount": ColumnPolicy("total_amount", "DECIMAL"),
                    },
                )
            },
        )
        self.connector = FakeMySqlConnector()
        kernel = MySqlSafeSqlKernel(
            registry=self.registry,
            connector=self.connector,
            audit_service=self.audit_service,
            default_limit=2,
            max_limit=5,
        )
        provider = DatabaseMySqlToolProvider(
            registry=self.registry,
            kernel=kernel,
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
        self.client = TestClient(build_database_mysql_http_app())

    def _restore_database_routes(self) -> None:
        database_routes.database_tool_gateway = self.original_database_tool_gateway
        auth_service.reset_users()
        auth_service.clear_blacklist()

    def login(self) -> str:
        response = self.client.post(
            "/api/auth/login",
            json={"username": "demo_user_dept1", "password": "Demo123!"},
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

    def grant_mysql_safe_select_access(self) -> None:
        self.grant("tool", "database_mysql.mysql_sales_readonly.safe_select", action="use")
        self.grant("database_table", "mysql_sales_readonly.orders")
        self.grant("database_column", "mysql_sales_readonly.orders.order_id")
        self.grant("database_column", "mysql_sales_readonly.orders.total_amount")

    def grant_mysql_tool(self, operation: str) -> None:
        self.grant("tool", f"database_mysql.mysql_sales_readonly.{operation}", action="use")

    def request_context(self) -> RequestContext:
        return RequestContext(
            request_id="mysql-test-request",
            trace_id="mysql-test-trace",
            user_id="user_demo_dept1",
            username="demo_user_dept1",
            department_id="dept_1",
            department_name="Operations",
            roles=["user"],
        )

    def test_safe_select_routes_to_mysql_provider_by_database_id(self):
        self.grant_mysql_safe_select_access()
        token = self.login()

        response = self.client.post(
            "/api/database/safe-select",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "database_id": "mysql_sales_readonly",
                "sql": "select order_id, total_amount from orders order by order_id limit 2",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["data"]["result"]
        self.assertEqual(result["database_id"], "mysql_sales_readonly")
        self.assertEqual(result["columns"], ["order_id", "total_amount"])
        self.assertEqual(
            result["rows"],
            [
                {"order_id": 2001, "total_amount": 42.5},
                {"order_id": 2002, "total_amount": 63.0},
            ],
        )
        self.assertEqual(
            self.connector.executed_sql,
            ["SELECT order_id, total_amount FROM orders ORDER BY order_id LIMIT 2"],
        )
        self.assertTrue(
            any(
                event.event_type == "tool_call"
                and event.metadata["tool_id"]
                == "database_mysql.mysql_sales_readonly.safe_select"
                for event in self.sink.events
            )
        )

    def test_mysql_safe_select_blocks_dml_and_ddl_without_execution(self):
        self.grant_mysql_safe_select_access()
        token = self.login()

        update_response = self.client.post(
            "/api/database/safe-select",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "database_id": "mysql_sales_readonly",
                "sql": "update orders set total_amount = 0 where order_id = 2001",
            },
        )
        drop_response = self.client.post(
            "/api/database/safe-select",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "database_id": "mysql_sales_readonly",
                "sql": "drop table orders",
            },
        )

        self.assertEqual(update_response.status_code, 403, update_response.text)
        self.assertEqual(update_response.json()["detail"], "non_select_statement_not_allowed")
        self.assertEqual(drop_response.status_code, 403, drop_response.text)
        self.assertEqual(drop_response.json()["detail"], "non_select_statement_not_allowed")
        self.assertEqual(self.connector.executed_sql, [])
        self.assertGreaterEqual(
            sum(
                1
                for event in self.sink.events
                if event.event_type == "database_query"
                and event.decision == "denied"
                and event.metadata["database_id"] == "mysql_sales_readonly"
                and event.metadata["dialect"] == "mysql"
                and event.reason == "non_select_statement_not_allowed"
            ),
            2,
        )

    def test_mysql_safe_select_rejects_limit_above_max_without_execution(self):
        self.grant_mysql_safe_select_access()
        token = self.login()

        response = self.client.post(
            "/api/database/safe-select",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "database_id": "mysql_sales_readonly",
                "sql": "select order_id, total_amount from orders limit 999",
            },
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], "limit_exceeds_max")
        self.assertEqual(self.connector.executed_sql, [])
        self.assertTrue(
            any(
                event.event_type == "database_query"
                and event.decision == "denied"
                and event.metadata["database_id"] == "mysql_sales_readonly"
                and event.metadata["dialect"] == "mysql"
                and event.reason == "limit_exceeds_max"
                for event in self.sink.events
            )
        )

    def test_mysql_safe_select_blocks_locking_select_without_execution(self):
        self.grant_mysql_safe_select_access()
        token = self.login()

        response = self.client.post(
            "/api/database/safe-select",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "database_id": "mysql_sales_readonly",
                "sql": "select order_id, total_amount from orders for update",
            },
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], "locking_select_not_allowed")
        self.assertEqual(self.connector.executed_sql, [])

    def test_mysql_safe_select_serializes_decimal_values(self):
        self.grant_mysql_safe_select_access()
        self.connector.rows = [{"order_id": 2001, "total_amount": Decimal("42.50")}]
        token = self.login()

        response = self.client.post(
            "/api/database/safe-select",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "database_id": "mysql_sales_readonly",
                "sql": "select order_id, total_amount from orders limit 1",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["data"]["result"]
        self.assertEqual(result["rows"], [{"order_id": 2001, "total_amount": "42.50"}])
        self.assertGreater(result["result_size_bytes"], 0)

    def test_pooled_mysql_connector_executes_select_in_readonly_transaction(self):
        created_connections: list[FakeMySqlConnection] = []

        def connection_factory(_settings: MySqlConnectionSettings) -> FakeMySqlConnection:
            connection = FakeMySqlConnection()
            created_connections.append(connection)
            return connection

        connector = PooledMySqlReadonlyConnector(
            settings=MySqlConnectionSettings(
                host="127.0.0.1",
                port=3306,
                database="sales",
                username="readonly_user",
                password="secret",
            ),
            pool_size=1,
            connection_factory=connection_factory,
        )

        rows = connector.execute_readonly(
            "SELECT order_id, total_amount FROM orders LIMIT 1",
            timeout_seconds=3.0,
        )
        second_rows = connector.execute_readonly(
            "SELECT order_id, total_amount FROM orders LIMIT 1",
            timeout_seconds=3.0,
        )

        self.assertEqual(rows, [{"order_id": 2001, "total_amount": 42.5}])
        self.assertEqual(second_rows, [{"order_id": 2001, "total_amount": 42.5}])
        self.assertEqual(len(created_connections), 1)
        self.assertEqual(
            created_connections[0].executed_sql,
            [
                "START TRANSACTION READ ONLY",
                "SELECT order_id, total_amount FROM orders LIMIT 1",
                "COMMIT",
                "START TRANSACTION READ ONLY",
                "SELECT order_id, total_amount FROM orders LIMIT 1",
                "COMMIT",
            ],
        )
        self.assertEqual(created_connections[0].rollbacks, 0)

    def test_pooled_mysql_writable_connector_executes_write_in_transaction(self):
        created_connections: list[FakeMySqlConnection] = []

        def connection_factory(_settings: MySqlConnectionSettings) -> FakeMySqlConnection:
            connection = FakeMySqlConnection()
            created_connections.append(connection)
            return connection

        connector = PooledMySqlWritableConnector(
            settings=MySqlConnectionSettings(
                host="127.0.0.1",
                port=3306,
                database="sales",
                username="writable_user",
                password="secret",
            ),
            pool_size=1,
            connection_factory=connection_factory,
        )

        result = connector.execute_transaction(
            "UPDATE orders SET total_amount = 0 WHERE order_id = 2001",
            timeout_seconds=3.0,
        )

        self.assertEqual(result, {"rows_affected": 1})
        self.assertEqual(len(created_connections), 1)
        self.assertEqual(
            created_connections[0].executed_sql,
            [
                "START TRANSACTION",
                "UPDATE orders SET total_amount = 0 WHERE order_id = 2001",
                "COMMIT",
            ],
        )
        self.assertEqual(created_connections[0].rollbacks, 0)

    def test_mysql_config_builder_creates_distinct_provider_resource_ids(self):
        provider = build_mysql_provider_from_config(
            app_config=SimpleNamespace(
                enterprise_mysql_enabled=True,
                enterprise_mysql_database_id="mysql_sales_readonly",
                enterprise_mysql_host="127.0.0.1",
                enterprise_mysql_port=3306,
                enterprise_mysql_database="sales",
                enterprise_mysql_username="readonly_user",
                enterprise_mysql_password="secret",
                enterprise_mysql_connect_timeout_seconds=5.0,
                enterprise_mysql_read_timeout_seconds=5.0,
                enterprise_mysql_pool_size=1,
                enterprise_mysql_default_limit=2,
                enterprise_mysql_max_limit=5,
                enterprise_mysql_allowlist_json=json.dumps(
                    {
                        "orders": {
                            "description": "Read-only order records.",
                            "columns": {
                                "order_id": {"data_type": "BIGINT"},
                                "total_amount": {"data_type": "DECIMAL"},
                            },
                        }
                    }
                ),
            ),
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )

        self.assertIsNotNone(provider)
        tools = asyncio.run(provider.list_tools())

        self.assertEqual(
            [tool.resource_id for tool in tools],
            [
                "database_mysql.mysql_sales_readonly.list_tables",
                "database_mysql.mysql_sales_readonly.describe_table",
                "database_mysql.mysql_sales_readonly.safe_select",
            ],
        )
        self.assertTrue(all(tool.metadata["database_id"] == "mysql_sales_readonly" for tool in tools))

    def test_admin_resource_catalog_includes_mysql_resources_when_enabled(self):
        original_values = {
            name: getattr(config, name)
            for name in [
                "enterprise_mysql_enabled",
                "enterprise_mysql_database_id",
                "enterprise_mysql_host",
                "enterprise_mysql_port",
                "enterprise_mysql_database",
                "enterprise_mysql_username",
                "enterprise_mysql_password",
                "enterprise_mysql_connect_timeout_seconds",
                "enterprise_mysql_read_timeout_seconds",
                "enterprise_mysql_pool_size",
                "enterprise_mysql_default_limit",
                "enterprise_mysql_max_limit",
                "enterprise_mysql_allowlist_json",
            ]
        }
        self.addCleanup(
            lambda: [setattr(config, name, value) for name, value in original_values.items()]
        )
        config.enterprise_mysql_enabled = True
        config.enterprise_mysql_database_id = "mysql_sales_readonly"
        config.enterprise_mysql_host = "127.0.0.1"
        config.enterprise_mysql_port = 3306
        config.enterprise_mysql_database = "sales"
        config.enterprise_mysql_username = "readonly_user"
        config.enterprise_mysql_password = "secret"
        config.enterprise_mysql_connect_timeout_seconds = 5.0
        config.enterprise_mysql_read_timeout_seconds = 5.0
        config.enterprise_mysql_pool_size = 1
        config.enterprise_mysql_default_limit = 2
        config.enterprise_mysql_max_limit = 5
        config.enterprise_mysql_allowlist_json = json.dumps(
            {
                "orders": {
                    "description": "Read-only order records.",
                    "columns": {
                        "order_id": {"data_type": "BIGINT"},
                        "total_amount": {"data_type": "DECIMAL"},
                    },
                }
            }
        )

        resources = asyncio.run(ResourceCatalogService().list_resources())
        by_id = {resource.resource_id: resource for resource in resources}

        self.assertIn("database_mysql.mysql_sales_readonly.safe_select", by_id)
        self.assertIn("mysql_sales_readonly.orders", by_id)
        self.assertIn("mysql_sales_readonly.orders.order_id", by_id)
        mysql_update_operation = database_operation_resource_id(
            "mysql_sales_readonly",
            "update",
        )
        mysql_delete_operation = database_operation_resource_id(
            "mysql_sales_readonly",
            "delete",
        )
        mysql_ddl_operation = database_operation_resource_id(
            "mysql_sales_readonly",
            "ddl",
        )
        self.assertIn(mysql_update_operation, by_id)
        self.assertIn(mysql_delete_operation, by_id)
        self.assertIn(mysql_ddl_operation, by_id)
        self.assertFalse(by_id[mysql_update_operation].metadata["requires_confirmation"])
        self.assertEqual(by_id[mysql_delete_operation].resource_type, "database_operation")
        self.assertEqual(by_id[mysql_delete_operation].actions_supported, ["execute"])
        self.assertEqual(by_id[mysql_delete_operation].metadata["operation_type"], "delete")
        self.assertTrue(by_id[mysql_delete_operation].metadata["requires_confirmation"])
        self.assertFalse(by_id[mysql_ddl_operation].metadata["requires_confirmation"])
        self.assertEqual(
            by_id["database_mysql.mysql_sales_readonly.safe_select"].metadata["dialect"],
            "mysql",
        )
        self.assertEqual(
            by_id["mysql_sales_readonly.orders.order_id"].metadata["data_type"],
            "BIGINT",
        )

    def test_mysql_list_and_describe_use_tool_gateway_permissions(self):
        provider = build_mysql_provider_from_config(
            app_config=SimpleNamespace(
                enterprise_mysql_enabled=True,
                enterprise_mysql_database_id="mysql_sales_readonly",
                enterprise_mysql_host="127.0.0.1",
                enterprise_mysql_port=3306,
                enterprise_mysql_database="sales",
                enterprise_mysql_username="readonly_user",
                enterprise_mysql_password="secret",
                enterprise_mysql_connect_timeout_seconds=5.0,
                enterprise_mysql_read_timeout_seconds=5.0,
                enterprise_mysql_pool_size=1,
                enterprise_mysql_default_limit=2,
                enterprise_mysql_max_limit=5,
                enterprise_mysql_allowlist_json=json.dumps(
                    {
                        "orders": {
                            "description": "Read-only order records.",
                            "columns": {
                                "order_id": {"data_type": "BIGINT"},
                                "total_amount": {"data_type": "DECIMAL"},
                            },
                        },
                        "incidents": {
                            "description": "Not granted to this user.",
                            "columns": {"incident_id": {"data_type": "BIGINT"}},
                        },
                    }
                ),
            ),
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )
        self.assertIsNotNone(provider)
        gateway = ToolGateway(
            providers=[provider],
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )
        self.grant_mysql_tool("list_tables")
        self.grant_mysql_tool("describe_table")
        self.grant("database_table", "mysql_sales_readonly.orders")
        self.grant("database_column", "mysql_sales_readonly.orders.order_id")

        tables = asyncio.run(
            gateway.execute(
                self.request_context(),
                "database_mysql.mysql_sales_readonly.list_tables",
                {},
            )
        )
        description = asyncio.run(
            gateway.execute(
                self.request_context(),
                "database_mysql.mysql_sales_readonly.describe_table",
                {"table_name": "orders"},
            )
        )

        self.assertEqual(tables["tables"], ["orders"])
        self.assertEqual(
            [column["name"] for column in description["columns"]],
            ["order_id"],
        )

    def test_default_database_gateway_includes_mysql_provider_when_enabled(self):
        original_values = {
            name: getattr(config, name)
            for name in [
                "enterprise_mysql_enabled",
                "enterprise_mysql_database_id",
                "enterprise_mysql_host",
                "enterprise_mysql_port",
                "enterprise_mysql_database",
                "enterprise_mysql_username",
                "enterprise_mysql_password",
                "enterprise_mysql_connect_timeout_seconds",
                "enterprise_mysql_read_timeout_seconds",
                "enterprise_mysql_pool_size",
                "enterprise_mysql_default_limit",
                "enterprise_mysql_max_limit",
                "enterprise_mysql_allowlist_json",
            ]
        }
        self.addCleanup(
            lambda: [setattr(config, name, value) for name, value in original_values.items()]
        )
        config.enterprise_mysql_enabled = True
        config.enterprise_mysql_database_id = "mysql_sales_readonly"
        config.enterprise_mysql_host = "127.0.0.1"
        config.enterprise_mysql_port = 3306
        config.enterprise_mysql_database = "sales"
        config.enterprise_mysql_username = "readonly_user"
        config.enterprise_mysql_password = "secret"
        config.enterprise_mysql_connect_timeout_seconds = 5.0
        config.enterprise_mysql_read_timeout_seconds = 5.0
        config.enterprise_mysql_pool_size = 1
        config.enterprise_mysql_default_limit = 2
        config.enterprise_mysql_max_limit = 5
        config.enterprise_mysql_allowlist_json = json.dumps(
            {
                "orders": {
                    "description": "Read-only order records.",
                    "columns": {"order_id": {"data_type": "BIGINT"}},
                }
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            gateway = database_routes.build_database_tool_gateway(
                database_path=Path(tmpdir) / "sandbox.sqlite3"
            )
            tool_entries, _filtered = asyncio.run(gateway._collect_tools())

        self.assertIn("database_demo.safe_select", tool_entries)
        self.assertIn("database_mysql.mysql_sales_readonly.safe_select", tool_entries)

    def test_default_operation_services_bind_mysql_when_enabled(self):
        original_values = {
            name: getattr(config, name)
            for name in [
                "enterprise_mysql_enabled",
                "enterprise_mysql_database_id",
                "enterprise_mysql_host",
                "enterprise_mysql_port",
                "enterprise_mysql_database",
                "enterprise_mysql_username",
                "enterprise_mysql_password",
                "enterprise_mysql_connect_timeout_seconds",
                "enterprise_mysql_read_timeout_seconds",
                "enterprise_mysql_pool_size",
                "enterprise_mysql_default_limit",
                "enterprise_mysql_max_limit",
                "enterprise_mysql_allowlist_json",
            ]
        }
        original_prepare_service = database_routes.database_operation_prepare_service
        original_direct_service = database_routes.database_operation_direct_execute_service
        self.addCleanup(
            lambda: [setattr(config, name, value) for name, value in original_values.items()]
        )
        self.addCleanup(
            lambda: setattr(
                database_routes,
                "database_operation_prepare_service",
                original_prepare_service,
            )
        )
        self.addCleanup(
            lambda: setattr(
                database_routes,
                "database_operation_direct_execute_service",
                original_direct_service,
            )
        )
        config.enterprise_mysql_enabled = True
        config.enterprise_mysql_database_id = "mysql_sales_write"
        config.enterprise_mysql_host = "127.0.0.1"
        config.enterprise_mysql_port = 3307
        config.enterprise_mysql_database = "sales"
        config.enterprise_mysql_username = "root"
        config.enterprise_mysql_password = "secret"
        config.enterprise_mysql_connect_timeout_seconds = 5.0
        config.enterprise_mysql_read_timeout_seconds = 5.0
        config.enterprise_mysql_pool_size = 1
        config.enterprise_mysql_default_limit = 2
        config.enterprise_mysql_max_limit = 5
        config.enterprise_mysql_allowlist_json = json.dumps(
            {
                "orders": {
                    "description": "Writable smoke orders.",
                    "columns": {
                        "order_id": {"data_type": "BIGINT"},
                        "total_amount": {"data_type": "DECIMAL"},
                    },
                }
            }
        )
        database_routes.database_operation_prepare_service = None
        database_routes.database_operation_direct_execute_service = None

        prepare_service = database_routes.get_database_operation_prepare_service()
        direct_service = database_routes.get_database_operation_direct_execute_service()

        self.assertEqual(prepare_service.registry.database_id, "mysql_sales_write")
        self.assertEqual(direct_service.registry.database_id, "mysql_sales_write")
        self.assertEqual(prepare_service.operation_executor.dialect, "mysql")
        self.assertEqual(direct_service.operation_executor.dialect, "mysql")


if __name__ == "__main__":
    unittest.main()
