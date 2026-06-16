import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.auth as auth_api
import app.enterprise.database.routes as database_routes
from app.enterprise.auth.service import auth_service
from app.enterprise.database.operation_permissions import (
    DATABASE_OPERATION_EXECUTE_ACTION,
    DATABASE_OPERATION_RESOURCE_TYPE,
    database_operation_resource_id,
)
from app.enterprise.database.registry import build_default_sandbox_registry
from app.enterprise.database.sandbox import create_sandbox_database
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService


def build_database_operation_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    app.include_router(database_routes.router, prefix="/api")
    return app


class EnterpriseDatabaseOperationPrepareTests(unittest.TestCase):
    def setUp(self):
        auth_service.reset_users()
        auth_service.clear_blacklist()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db_path = Path(self.tmpdir.name) / "sandbox.sqlite3"
        self.confirmation_path = Path(self.tmpdir.name) / "confirmations.sqlite3"
        create_sandbox_database(self.db_path)

        self.sink = InMemoryAuditSink()
        self.audit_service = AuditService(sinks=[self.sink])
        self.permission_service = PermissionService(
            repository=InMemoryGovernanceRepository(),
            audit_service=self.audit_service,
        )
        self.registry = build_default_sandbox_registry()
        self.original_prepare_service = database_routes.database_operation_prepare_service
        database_routes.database_operation_prepare_service = (
            database_routes.build_database_operation_prepare_service(
                database_path=self.db_path,
                confirmation_path=self.confirmation_path,
                registry=self.registry,
                permission_service=self.permission_service,
                audit_service=self.audit_service,
            )
        )
        self.addCleanup(self._restore_database_routes)
        self.client = TestClient(build_database_operation_app())

    def _restore_database_routes(self) -> None:
        database_routes.database_operation_prepare_service = self.original_prepare_service
        auth_service.reset_users()
        auth_service.clear_blacklist()

    def login(self) -> str:
        response = self.client.post(
            "/api/auth/login",
            json={"username": "demo_user_dept1", "password": "Demo123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["access_token"]

    def grant(self, resource_type: str, resource_id: str, action: str) -> None:
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

    def grant_orders_update_prepare_scope(self) -> None:
        self.grant(
            DATABASE_OPERATION_RESOURCE_TYPE,
            database_operation_resource_id("sandbox_sales", "update"),
            DATABASE_OPERATION_EXECUTE_ACTION,
        )
        self.grant("database_table", "sandbox_sales.factory_access_events", "read")
        self.grant("database_column", "sandbox_sales.factory_access_events.event_id", "read")
        self.grant("database_column", "sandbox_sales.factory_access_events.direction", "read")

    def grant_orders_delete_prepare_scope(self) -> None:
        self.grant(
            DATABASE_OPERATION_RESOURCE_TYPE,
            database_operation_resource_id("sandbox_sales", "delete"),
            DATABASE_OPERATION_EXECUTE_ACTION,
        )
        self.grant("database_table", "sandbox_sales.factory_access_events", "read")
        self.grant("database_column", "sandbox_sales.factory_access_events.event_id", "read")

    def post_prepare(self, token: str, sql: str):
        return self.client.post(
            "/api/database/operations/prepare",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "database_id": "sandbox_sales",
                "sql": sql,
                "reason": "prepare test",
            },
        )

    def event_direction(self, event_id: int) -> str:
        with closing(sqlite3.connect(self.db_path)) as connection:
            row = connection.execute(
                "SELECT direction FROM factory_access_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return str(row[0])

    def table_exists(self, table_name: str) -> bool:
        with closing(sqlite3.connect(self.db_path)) as connection:
            row = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).fetchone()
        return row is not None

    def test_prepare_update_creates_pending_confirmation_without_executing_sql(self):
        self.grant_orders_update_prepare_scope()
        token = self.login()

        response = self.post_prepare(
            token,
            "update factory_access_events set direction = 'manual_override' where event_id = 1001",
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertTrue(data["requires_confirmation"])
        self.assertEqual(data["operation_type"], "update")
        self.assertEqual(data["risk_level"], "medium")
        self.assertEqual(data["summary"]["estimated_affected_rows"], 1)
        self.assertTrue(data["summary"]["estimate_reliable"])
        self.assertEqual(self.event_direction(1001), "entry")

        confirmation = database_routes.get_database_operation_prepare_service().repository.get(
            data["confirmation_id"]
        )
        self.assertIsNotNone(confirmation)
        self.assertEqual(confirmation.status, "pending")
        self.assertEqual(confirmation.operation_type, "update")
        self.assertEqual(confirmation.sql_hash_version, "dbops-sql-hash-v1")
        self.assertEqual(confirmation.normalization_version, "sqlglot-normalize-v1")
        self.assertTrue(confirmation.sql_hash)
        self.assertTrue(confirmation.parameters_hash)
        self.assertGreater(confirmation.expires_at, confirmation.created_at)
        self.assertTrue(
            any(
                event.event_type == "database_operation_prepare_created"
                and event.metadata["confirmation_id"] == data["confirmation_id"]
                for event in self.sink.events
            )
        )

    def test_prepare_update_without_operation_permission_returns_403_without_confirmation(self):
        token = self.login()

        response = self.post_prepare(
            token,
            "update factory_access_events set direction = 'manual_override' where event_id = 1001",
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], "default_deny")
        repository = database_routes.get_database_operation_prepare_service().repository
        self.assertEqual(repository.list_pending(), [])
        self.assertEqual(self.event_direction(1001), "entry")
        self.assertTrue(
            any(
                event.event_type == "database_operation_prepare_rejected"
                and event.reason == "default_deny"
                for event in self.sink.events
            )
        )

    def test_prepare_update_without_column_permission_returns_403_without_confirmation(self):
        self.grant(
            DATABASE_OPERATION_RESOURCE_TYPE,
            database_operation_resource_id("sandbox_sales", "update"),
            DATABASE_OPERATION_EXECUTE_ACTION,
        )
        self.grant("database_table", "sandbox_sales.factory_access_events", "read")
        token = self.login()

        response = self.post_prepare(
            token,
            "update factory_access_events set direction = 'manual_override' where event_id = 1001",
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], "database_column_denied")
        repository = database_routes.get_database_operation_prepare_service().repository
        self.assertEqual(repository.list_pending(), [])
        self.assertEqual(self.event_direction(1001), "entry")

    def test_prepare_delete_creates_high_risk_confirmation_without_deleting_rows(self):
        self.grant_orders_delete_prepare_scope()
        token = self.login()

        response = self.post_prepare(
            token,
            "delete from factory_access_events where event_id = 1002",
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertTrue(data["requires_confirmation"])
        self.assertEqual(data["operation_type"], "delete")
        self.assertEqual(data["risk_level"], "high")
        self.assertEqual(data["summary"]["estimated_affected_rows"], 1)
        self.assertTrue(data["summary"]["estimate_reliable"])
        self.assertEqual(self.event_direction(1002), "exit")

        confirmation = database_routes.get_database_operation_prepare_service().repository.get(
            data["confirmation_id"]
        )
        self.assertIsNotNone(confirmation)
        self.assertEqual(confirmation.status, "pending")
        self.assertEqual(confirmation.operation_type, "delete")

    def test_prepare_drop_table_creates_confirmation_without_dropping_table(self):
        self.grant_orders_delete_prepare_scope()
        token = self.login()

        response = self.post_prepare(token, "drop table factory_access_events")

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["operation_type"], "drop_table")
        self.assertEqual(data["risk_level"], "high")
        self.assertIsNone(data["summary"]["estimated_affected_rows"])
        self.assertFalse(data["summary"]["estimate_reliable"])
        self.assertEqual(
            data["summary"]["estimate_reason"],
            "preview_not_supported_for_operation",
        )
        self.assertTrue(self.table_exists("factory_access_events"))

        confirmation = database_routes.get_database_operation_prepare_service().repository.get(
            data["confirmation_id"]
        )
        self.assertIsNotNone(confirmation)
        self.assertEqual(confirmation.status, "pending")
        self.assertEqual(confirmation.operation_type, "drop_table")


if __name__ == "__main__":
    unittest.main()
