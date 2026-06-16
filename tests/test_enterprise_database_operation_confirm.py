import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
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


class EnterpriseDatabaseOperationConfirmTests(unittest.TestCase):
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

    def login(self, username: str = "demo_user_dept1", password: str = "Demo123!") -> str:
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["access_token"]

    def grant(
        self,
        resource_type: str,
        resource_id: str,
        action: str,
        *,
        principal_id: str = "user_demo_dept1",
    ) -> ResourceGrant:
        grant = ResourceGrant(
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            principal_type=PrincipalType.USER,
            principal_id=principal_id,
            effect=GrantEffect.ALLOW,
        )
        return self.permission_service.grant_access(grant)

    def grant_orders_update_scope(self, *, principal_id: str = "user_demo_dept1") -> None:
        self.grant(
            DATABASE_OPERATION_RESOURCE_TYPE,
            database_operation_resource_id("sandbox_sales", "update"),
            DATABASE_OPERATION_EXECUTE_ACTION,
            principal_id=principal_id,
        )
        self.grant(
            "database_table",
            "sandbox_sales.factory_access_events",
            "read",
            principal_id=principal_id,
        )
        self.grant(
            "database_column",
            "sandbox_sales.factory_access_events.event_id",
            "read",
            principal_id=principal_id,
        )
        self.grant(
            "database_column",
            "sandbox_sales.factory_access_events.direction",
            "read",
            principal_id=principal_id,
        )

    def grant_orders_delete_scope(self, *, principal_id: str = "user_demo_dept1") -> None:
        self.grant(
            DATABASE_OPERATION_RESOURCE_TYPE,
            database_operation_resource_id("sandbox_sales", "delete"),
            DATABASE_OPERATION_EXECUTE_ACTION,
            principal_id=principal_id,
        )
        self.grant(
            "database_table",
            "sandbox_sales.factory_access_events",
            "read",
            principal_id=principal_id,
        )
        self.grant(
            "database_column",
            "sandbox_sales.factory_access_events.event_id",
            "read",
            principal_id=principal_id,
        )

    def prepare_update(self, token: str, *, event_id: int = 1001):
        return self.client.post(
            "/api/database/operations/prepare",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "database_id": "sandbox_sales",
                "sql": (
                    "update factory_access_events set direction = 'manual_override' "
                    f"where event_id = {event_id}"
                ),
                "reason": "confirm test",
            },
        )

    def post_prepare(self, token: str, sql: str):
        return self.client.post(
            "/api/database/operations/prepare",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "database_id": "sandbox_sales",
                "sql": sql,
                "reason": "confirm test",
            },
        )

    def post_confirm(self, token: str, confirmation_id: str):
        return self.client.post(
            f"/api/database/confirmations/{confirmation_id}/confirm",
            headers={"Authorization": f"Bearer {token}"},
        )

    def event_direction(self, event_id: int) -> str:
        with closing(sqlite3.connect(self.db_path)) as connection:
            row = connection.execute(
                "SELECT direction FROM factory_access_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return str(row[0])

    def order_exists(self, event_id: int) -> bool:
        with closing(sqlite3.connect(self.db_path)) as connection:
            row = connection.execute(
                "SELECT 1 FROM factory_access_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return row is not None

    def table_exists(self, table_name: str) -> bool:
        with closing(sqlite3.connect(self.db_path)) as connection:
            row = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).fetchone()
        return row is not None

    def test_user_lists_only_their_own_confirmations(self):
        self.grant_orders_update_scope()
        self.grant_orders_update_scope(principal_id="user_admin")
        user_token = self.login()
        admin_token = self.login("admin", "Admin123!")
        user_confirmation_id = self.prepare_update(user_token, event_id=1001).json()["data"][
            "confirmation_id"
        ]
        admin_confirmation_id = self.prepare_update(admin_token, event_id=1002).json()["data"][
            "confirmation_id"
        ]

        response = self.client.get(
            "/api/database/confirmations",
            headers={"Authorization": f"Bearer {user_token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        confirmations = response.json()["data"]["confirmations"]
        self.assertEqual([item["confirmation_id"] for item in confirmations], [user_confirmation_id])
        self.assertNotIn(admin_confirmation_id, [item["confirmation_id"] for item in confirmations])
        self.assertEqual(confirmations[0]["status"], "pending")
        self.assertEqual(confirmations[0]["operation_type"], "update")
        self.assertEqual(confirmations[0]["risk_level"], "medium")

    def test_cancel_pending_confirmation_prevents_confirm_execution(self):
        self.grant_orders_update_scope()
        token = self.login()
        confirmation_id = self.prepare_update(token).json()["data"]["confirmation_id"]

        cancel_response = self.client.post(
            f"/api/database/confirmations/{confirmation_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        confirm_response = self.client.post(
            f"/api/database/confirmations/{confirmation_id}/confirm",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(cancel_response.status_code, 200, cancel_response.text)
        self.assertEqual(cancel_response.json()["data"]["status"], "cancelled")
        self.assertEqual(confirm_response.status_code, 409, confirm_response.text)
        self.assertEqual(confirm_response.json()["detail"], "confirmation_not_pending")
        self.assertEqual(self.event_direction(1001), "entry")

    def test_confirm_update_executes_once_after_recheck(self):
        self.grant_orders_update_scope()
        token = self.login()
        confirmation_id = self.prepare_update(token).json()["data"]["confirmation_id"]

        response = self.post_confirm(token, confirmation_id)
        replay_response = self.post_confirm(token, confirmation_id)

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["status"], "executed")
        self.assertEqual(data["execution_result"]["rows_affected"], 1)
        self.assertEqual(self.event_direction(1001), "manual_override")
        self.assertEqual(replay_response.status_code, 409, replay_response.text)
        self.assertEqual(replay_response.json()["detail"], "confirmation_not_pending")
        self.assertTrue(
            any(
                event.event_type == "database_operation_executed"
                and event.metadata["confirmation_id"] == confirmation_id
                and event.metadata["rows_affected"] == 1
                for event in self.sink.events
            )
        )

    def test_confirm_delete_executes_after_recheck(self):
        self.grant_orders_delete_scope()
        token = self.login()
        confirmation_id = self.post_prepare(
            token,
            "delete from factory_access_events where event_id = 1002",
        ).json()["data"]["confirmation_id"]

        response = self.post_confirm(token, confirmation_id)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"]["status"], "executed")
        self.assertFalse(self.order_exists(1002))

    def test_confirm_drop_table_executes_in_sandbox(self):
        self.grant_orders_delete_scope()
        token = self.login()
        confirmation_id = self.post_prepare(token, "drop table factory_access_events").json()["data"][
            "confirmation_id"
        ]

        response = self.post_confirm(token, confirmation_id)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"]["status"], "executed")
        self.assertFalse(self.table_exists("factory_access_events"))

    def test_confirm_after_permission_revoked_fails_without_execution(self):
        operation_grant = self.grant(
            DATABASE_OPERATION_RESOURCE_TYPE,
            database_operation_resource_id("sandbox_sales", "update"),
            DATABASE_OPERATION_EXECUTE_ACTION,
        )
        self.grant("database_table", "sandbox_sales.factory_access_events", "read")
        self.grant("database_column", "sandbox_sales.factory_access_events.event_id", "read")
        self.grant("database_column", "sandbox_sales.factory_access_events.direction", "read")
        token = self.login()
        confirmation_id = self.prepare_update(token).json()["data"]["confirmation_id"]
        self.permission_service.revoke_grant(operation_grant.grant_id)

        response = self.post_confirm(token, confirmation_id)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], "default_deny")
        self.assertEqual(self.event_direction(1001), "entry")
        confirmation = database_routes.get_database_operation_prepare_service().repository.get(
            confirmation_id
        )
        self.assertEqual(confirmation.status, "failed")
        self.assertEqual(confirmation.failure_reason, "default_deny")

    def test_expired_confirmation_cannot_execute(self):
        self.grant_orders_update_scope()
        token = self.login()
        confirmation_id = self.prepare_update(token).json()["data"]["confirmation_id"]
        repository = database_routes.get_database_operation_prepare_service().repository
        confirmation = repository.get(confirmation_id)
        self.assertIsNotNone(confirmation)
        repository.update(
            confirmation.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
        )

        response = self.post_confirm(token, confirmation_id)

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"], "confirmation_expired")
        self.assertEqual(self.event_direction(1001), "entry")
        expired = repository.get(confirmation_id)
        self.assertEqual(expired.status, "expired")

    def test_confirm_rejects_tampered_confirmation_sql_hash(self):
        self.grant_orders_update_scope()
        token = self.login()
        confirmation_id = self.prepare_update(token).json()["data"]["confirmation_id"]
        repository = database_routes.get_database_operation_prepare_service().repository
        confirmation = repository.get(confirmation_id)
        self.assertIsNotNone(confirmation)
        repository.update(
            confirmation.model_copy(
                update={
                    "sql": (
                        "update factory_access_events set direction = 'tampered' "
                        "where event_id = 1001"
                    ),
                },
            )
        )

        response = self.post_confirm(token, confirmation_id)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], "sql_hash_mismatch")
        self.assertEqual(self.event_direction(1001), "entry")
        failed = repository.get(confirmation_id)
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.failure_reason, "sql_hash_mismatch")

    def test_user_cannot_read_another_users_confirmation_detail(self):
        self.grant_orders_update_scope(principal_id="user_admin")
        user_token = self.login()
        admin_token = self.login("admin", "Admin123!")
        confirmation_id = self.prepare_update(admin_token, event_id=1002).json()["data"][
            "confirmation_id"
        ]

        response = self.client.get(
            f"/api/database/confirmations/{confirmation_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )

        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["detail"], "confirmation_not_found")
