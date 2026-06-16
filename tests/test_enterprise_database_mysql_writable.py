import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.auth as auth_api
import app.enterprise.database.routes as database_routes
from app.enterprise.auth.service import auth_service
from app.enterprise.database.mysql import MySqlDatabaseOperationExecutor
from app.enterprise.database.operation_permissions import (
    DATABASE_OPERATION_EXECUTE_ACTION,
    DATABASE_OPERATION_RESOURCE_TYPE,
    database_operation_resource_id,
)
from app.enterprise.database.registry import ColumnPolicy, DatabaseSchemaRegistry, TablePolicy
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService


def build_database_mysql_writable_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    app.include_router(database_routes.router, prefix="/api")
    return app


class FakeWritableMySqlConnector:
    def __init__(self):
        self.rows = {
            2001: {"order_id": 2001, "total_amount": 128.5},
            2002: {"order_id": 2002, "total_amount": 88.0},
        }
        self.readonly_sql: list[str] = []
        self.transaction_sql: list[str] = []

    def execute_readonly(self, sql: str, *, timeout_seconds: float) -> list[dict]:
        self.readonly_sql.append(sql)
        order_id = self._order_id(sql)
        count = 1 if order_id in self.rows else 0
        return [{"affected_count": count}]

    def execute_transaction(self, sql: str, *, timeout_seconds: float) -> dict:
        self.transaction_sql.append(sql)
        normalized = " ".join(sql.lower().split())
        order_id = self._order_id(sql)
        if normalized.startswith("insert into orders"):
            order_id, total_amount = self._insert_values(sql)
            self.rows[order_id] = {
                "order_id": order_id,
                "total_amount": total_amount,
            }
            return {"rows_affected": 1}
        if normalized.startswith("update orders set total_amount = 0"):
            if order_id in self.rows:
                self.rows[order_id]["total_amount"] = 0.0
                return {"rows_affected": 1}
            return {"rows_affected": 0}
        if normalized.startswith("delete from orders"):
            if order_id in self.rows:
                del self.rows[order_id]
                return {"rows_affected": 1}
            return {"rows_affected": 0}
        if normalized.startswith("create table archived_orders"):
            return {"rows_affected": 0}
        if normalized.startswith("alter table orders add column status"):
            return {"rows_affected": 0}
        if normalized.startswith("alter table orders rename column status to state"):
            return {"rows_affected": 0}
        if normalized.startswith("alter table orders modify column status"):
            return {"rows_affected": 0}
        if normalized.startswith("create index idx_orders_total on orders"):
            return {"rows_affected": 0}
        if normalized.startswith("drop index idx_orders_total on orders"):
            return {"rows_affected": 0}
        if normalized.startswith("rename table orders to archived_orders"):
            return {"rows_affected": 0}
        if normalized.startswith("drop table orders"):
            self.rows.clear()
            return {"rows_affected": 0}
        raise RuntimeError("unexpected_sql")

    def total_amount(self, order_id: int) -> float:
        return float(self.rows[order_id]["total_amount"])

    def exists(self, order_id: int) -> bool:
        return order_id in self.rows

    @staticmethod
    def _order_id(sql: str) -> int:
        normalized = " ".join(sql.lower().split())
        marker = "order_id = "
        if marker not in normalized:
            return -1
        value = normalized.split(marker, 1)[1].split()[0].strip(";")
        return int(value)

    @staticmethod
    def _insert_values(sql: str) -> tuple[int, float]:
        normalized = " ".join(sql.lower().split())
        values_text = normalized.split(" values ", 1)[1].strip().strip(";")
        values_text = values_text.strip("()")
        order_id, total_amount = [part.strip() for part in values_text.split(",", 1)]
        return int(order_id), float(total_amount)


class EnterpriseDatabaseMySqlWritableTests(unittest.TestCase):
    def setUp(self):
        auth_service.reset_users()
        auth_service.clear_blacklist()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.confirmation_path = Path(self.tmpdir.name) / "confirmations.sqlite3"
        self.sink = InMemoryAuditSink()
        self.audit_service = AuditService(sinks=[self.sink])
        self.permission_service = PermissionService(
            repository=InMemoryGovernanceRepository(),
            audit_service=self.audit_service,
        )
        self.registry = DatabaseSchemaRegistry(
            database_id="mysql_sales_write",
            tables={
                "orders": TablePolicy(
                    name="orders",
                    description="Non-production writable MySQL orders.",
                    columns={
                        "order_id": ColumnPolicy("order_id", "BIGINT"),
                        "total_amount": ColumnPolicy("total_amount", "DECIMAL"),
                        "status": ColumnPolicy("status", "VARCHAR"),
                        "state": ColumnPolicy("state", "VARCHAR"),
                    },
                ),
                "archived_orders": TablePolicy(
                    name="archived_orders",
                    description="DDL target table.",
                    columns={
                        "order_id": ColumnPolicy("order_id", "BIGINT"),
                    },
                ),
            },
        )
        self.connector = FakeWritableMySqlConnector()
        self.original_prepare_service = database_routes.database_operation_prepare_service
        self.original_direct_execute_service = (
            database_routes.database_operation_direct_execute_service
        )
        operation_executor = MySqlDatabaseOperationExecutor(
            registry=self.registry,
            connector=self.connector,
            timeout_seconds=2.0,
        )
        database_routes.database_operation_prepare_service = (
            database_routes.build_database_operation_prepare_service(
                database_path=Path(self.tmpdir.name) / "unused.sqlite3",
                confirmation_path=self.confirmation_path,
                registry=self.registry,
                permission_service=self.permission_service,
                audit_service=self.audit_service,
                dialect="mysql",
                operation_executor=operation_executor,
            )
        )
        database_routes.database_operation_direct_execute_service = (
            database_routes.build_database_operation_direct_execute_service(
                registry=self.registry,
                permission_service=self.permission_service,
                audit_service=self.audit_service,
                dialect="mysql",
                operation_executor=operation_executor,
            )
        )
        self.addCleanup(self._restore_database_routes)
        self.client = TestClient(build_database_mysql_writable_app())

    def _restore_database_routes(self) -> None:
        database_routes.database_operation_prepare_service = self.original_prepare_service
        database_routes.database_operation_direct_execute_service = (
            self.original_direct_execute_service
        )
        auth_service.reset_users()
        auth_service.clear_blacklist()

    def login(self) -> str:
        response = self.client.post(
            "/api/auth/login",
            json={"username": "demo_user_dept1", "password": "Demo123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["access_token"]

    def grant(self, resource_type: str, resource_id: str, action: str = "read") -> ResourceGrant:
        return self.permission_service.grant_access(
            ResourceGrant(
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                principal_type=PrincipalType.USER,
                principal_id="user_demo_dept1",
                effect=GrantEffect.ALLOW,
            )
        )

    def grant_orders_update_scope(self) -> ResourceGrant:
        operation_grant = self.grant(
            DATABASE_OPERATION_RESOURCE_TYPE,
            database_operation_resource_id("mysql_sales_write", "update"),
            DATABASE_OPERATION_EXECUTE_ACTION,
        )
        self.grant("database_table", "mysql_sales_write.orders")
        self.grant("database_column", "mysql_sales_write.orders.order_id")
        self.grant("database_column", "mysql_sales_write.orders.total_amount")
        return operation_grant

    def grant_orders_delete_scope(self) -> ResourceGrant:
        operation_grant = self.grant(
            DATABASE_OPERATION_RESOURCE_TYPE,
            database_operation_resource_id("mysql_sales_write", "delete"),
            DATABASE_OPERATION_EXECUTE_ACTION,
        )
        self.grant("database_table", "mysql_sales_write.orders")
        self.grant("database_column", "mysql_sales_write.orders.order_id")
        return operation_grant

    def grant_orders_insert_scope(self) -> ResourceGrant:
        operation_grant = self.grant(
            DATABASE_OPERATION_RESOURCE_TYPE,
            database_operation_resource_id("mysql_sales_write", "update"),
            DATABASE_OPERATION_EXECUTE_ACTION,
        )
        self.grant("database_table", "mysql_sales_write.orders")
        self.grant("database_column", "mysql_sales_write.orders.order_id")
        self.grant("database_column", "mysql_sales_write.orders.total_amount")
        return operation_grant

    def grant_orders_ddl_scope(self) -> ResourceGrant:
        operation_grant = self.grant(
            DATABASE_OPERATION_RESOURCE_TYPE,
            database_operation_resource_id("mysql_sales_write", "ddl"),
            DATABASE_OPERATION_EXECUTE_ACTION,
        )
        self.grant("database_table", "mysql_sales_write.orders")
        self.grant("database_column", "mysql_sales_write.orders.total_amount")
        self.grant("database_column", "mysql_sales_write.orders.status")
        self.grant("database_column", "mysql_sales_write.orders.state")
        self.grant("database_table", "mysql_sales_write.archived_orders")
        self.grant("database_column", "mysql_sales_write.archived_orders.order_id")
        return operation_grant

    def post_prepare(self, token: str, sql: str):
        return self.client.post(
            "/api/database/operations/prepare",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "database_id": "mysql_sales_write",
                "sql": sql,
                "reason": "mysql writable test",
            },
        )

    def post_execute(self, token: str, sql: str):
        return self.client.post(
            "/api/database/operations/execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "database_id": "mysql_sales_write",
                "sql": sql,
            },
        )

    def post_confirm(self, token: str, confirmation_id: str):
        return self.client.post(
            f"/api/database/confirmations/{confirmation_id}/confirm",
            headers={"Authorization": f"Bearer {token}"},
        )

    def test_mysql_update_direct_execute_does_not_create_confirmation(self):
        self.grant_orders_update_scope()
        token = self.login()

        execute_response = self.post_execute(
            token,
            "update orders set total_amount = 0 where order_id = 2001",
        )

        self.assertEqual(execute_response.status_code, 200, execute_response.text)
        data = execute_response.json()["data"]
        self.assertEqual(data["database_id"], "mysql_sales_write")
        self.assertEqual(data["operation_type"], "update")
        self.assertFalse(data["requires_confirmation"])
        self.assertEqual(data["execution_result"]["rows_affected"], 1)
        self.assertEqual(self.connector.total_amount(2001), 0.0)
        repository = database_routes.get_database_operation_prepare_service().repository
        self.assertEqual(repository.list_pending(), [])
        self.assertTrue(
            any(
                event.event_type == "database_operation_direct_executed"
                and event.metadata["database_id"] == "mysql_sales_write"
                and event.metadata["rows_affected"] == 1
                and "confirmation_id" not in event.metadata
                for event in self.sink.events
            )
        )

    def test_mysql_update_prepare_is_rejected_because_confirmation_is_not_required(self):
        self.grant_orders_update_scope()
        token = self.login()

        response = self.post_prepare(
            token,
            "update orders set total_amount = 0 where order_id = 2001",
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], "database_operation_does_not_require_confirmation")
        self.assertEqual(self.connector.total_amount(2001), 128.5)

    def test_mysql_delete_without_operation_permission_does_not_create_confirmation(self):
        self.grant("database_table", "mysql_sales_write.orders")
        self.grant("database_column", "mysql_sales_write.orders.order_id")
        token = self.login()

        response = self.post_prepare(token, "delete from orders where order_id = 2002")

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], "default_deny")
        repository = database_routes.get_database_operation_prepare_service().repository
        self.assertEqual(repository.list_pending(), [])
        self.assertTrue(self.connector.exists(2002))
        self.assertEqual(self.connector.transaction_sql, [])

    def test_mysql_insert_direct_execute_does_not_create_confirmation(self):
        self.grant_orders_insert_scope()
        token = self.login()

        response = self.post_execute(
            token,
            "insert into orders (order_id, total_amount) values (2003, 16.5)",
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["operation_type"], "insert")
        self.assertFalse(data["requires_confirmation"])
        self.assertEqual(data["execution_result"]["rows_affected"], 1)
        self.assertTrue(self.connector.exists(2003))
        self.assertEqual(self.connector.total_amount(2003), 16.5)
        repository = database_routes.get_database_operation_prepare_service().repository
        self.assertEqual(repository.list_pending(), [])

    def test_mysql_create_table_direct_execute_does_not_create_confirmation(self):
        self.grant_orders_ddl_scope()
        token = self.login()

        response = self.post_execute(
            token,
            "create table archived_orders (order_id bigint)",
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["operation_type"], "create_table")
        self.assertEqual(data["operation_level"], "L5")
        self.assertFalse(data["requires_confirmation"])
        self.assertEqual(data["execution_result"]["rows_affected"], 0)
        self.assertIn("CREATE TABLE archived_orders", self.connector.transaction_sql[-1])
        repository = database_routes.get_database_operation_prepare_service().repository
        self.assertEqual(repository.list_pending(), [])
        self.assertTrue(
            any(
                event.event_type == "database_operation_direct_executed"
                and event.metadata["operation_type"] == "create_table"
                and event.metadata["operation_resource_id"] == "mysql_sales_write.ddl"
                for event in self.sink.events
            )
        )

    def test_mysql_alter_add_column_direct_execute_does_not_create_confirmation(self):
        self.grant_orders_ddl_scope()
        token = self.login()

        response = self.post_execute(
            token,
            "alter table orders add column status varchar(20)",
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["operation_type"], "alter_table")
        self.assertEqual(data["operation_level"], "L5")
        self.assertFalse(data["requires_confirmation"])
        self.assertEqual(data["execution_result"]["rows_affected"], 0)
        self.assertIn("ALTER TABLE orders ADD COLUMN", self.connector.transaction_sql[-1])
        repository = database_routes.get_database_operation_prepare_service().repository
        self.assertEqual(repository.list_pending(), [])

    def test_mysql_index_ddl_direct_execute_does_not_create_confirmation(self):
        self.grant_orders_ddl_scope()
        token = self.login()

        create_response = self.post_execute(
            token,
            "create index idx_orders_total on orders (total_amount)",
        )
        drop_response = self.post_execute(
            token,
            "drop index idx_orders_total on orders",
        )

        self.assertEqual(create_response.status_code, 200, create_response.text)
        self.assertEqual(drop_response.status_code, 200, drop_response.text)
        self.assertEqual(create_response.json()["data"]["operation_type"], "create_index")
        self.assertEqual(drop_response.json()["data"]["operation_type"], "drop_index")
        self.assertFalse(create_response.json()["data"]["requires_confirmation"])
        self.assertFalse(drop_response.json()["data"]["requires_confirmation"])
        repository = database_routes.get_database_operation_prepare_service().repository
        self.assertEqual(repository.list_pending(), [])

    def test_mysql_rename_and_modify_ddl_direct_execute_does_not_create_confirmation(self):
        self.grant_orders_ddl_scope()
        token = self.login()

        rename_column_response = self.post_execute(
            token,
            "alter table orders rename column status to state",
        )
        modify_response = self.post_execute(
            token,
            "alter table orders modify column status varchar(40)",
        )
        rename_table_response = self.post_execute(
            token,
            "rename table orders to archived_orders",
        )

        self.assertEqual(rename_column_response.status_code, 200, rename_column_response.text)
        self.assertEqual(modify_response.status_code, 200, modify_response.text)
        self.assertEqual(rename_table_response.status_code, 200, rename_table_response.text)
        self.assertEqual(rename_column_response.json()["data"]["operation_type"], "alter_table")
        self.assertEqual(modify_response.json()["data"]["operation_type"], "alter_table")
        self.assertEqual(rename_table_response.json()["data"]["operation_type"], "rename_table")
        repository = database_routes.get_database_operation_prepare_service().repository
        self.assertEqual(repository.list_pending(), [])

    def test_mysql_delete_direct_execute_requires_confirmation(self):
        self.grant_orders_delete_scope()
        token = self.login()

        response = self.post_execute(token, "delete from orders where order_id = 2002")

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], "database_operation_requires_confirmation")
        self.assertTrue(self.connector.exists(2002))
        self.assertEqual(self.connector.transaction_sql, [])
        repository = database_routes.get_database_operation_prepare_service().repository
        self.assertEqual(repository.list_pending(), [])

    def test_mysql_drop_table_direct_execute_requires_confirmation_and_prepare_creates_confirmation(
        self,
    ):
        self.grant_orders_delete_scope()
        token = self.login()

        direct_response = self.post_execute(token, "drop table orders")
        prepare_response = self.post_prepare(token, "drop table orders")

        self.assertEqual(direct_response.status_code, 403, direct_response.text)
        self.assertEqual(
            direct_response.json()["detail"],
            "database_operation_requires_confirmation",
        )
        self.assertEqual(prepare_response.status_code, 200, prepare_response.text)
        data = prepare_response.json()["data"]
        self.assertEqual(data["operation_type"], "drop_table")
        self.assertTrue(data["requires_confirmation"])
        self.assertFalse(data["summary"]["estimate_reliable"])
        self.assertTrue(self.connector.exists(2001))
        self.assertEqual(self.connector.transaction_sql, [])

    def test_mysql_delete_confirm_rechecks_revoked_permission_without_execution(self):
        operation_grant = self.grant_orders_delete_scope()
        token = self.login()
        prepare_response = self.post_prepare(token, "delete from orders where order_id = 2002")
        confirmation_id = prepare_response.json()["data"]["confirmation_id"]
        self.permission_service.revoke_grant(operation_grant.grant_id)

        response = self.post_confirm(token, confirmation_id)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], "default_deny")
        self.assertTrue(self.connector.exists(2002))
        self.assertEqual(self.connector.transaction_sql, [])
        confirmation = database_routes.get_database_operation_prepare_service().repository.get(
            confirmation_id
        )
        self.assertEqual(confirmation.status, "failed")
        self.assertEqual(confirmation.failure_reason, "default_deny")


if __name__ == "__main__":
    unittest.main()
