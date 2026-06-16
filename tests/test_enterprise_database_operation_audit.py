import tempfile
import unittest
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
from app.enterprise.observability.models import AuditEvent
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService


def build_database_operation_audit_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    app.include_router(database_routes.router, prefix="/api")
    return app


class EnterpriseDatabaseOperationAuditTests(unittest.TestCase):
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
        self.client = TestClient(build_database_operation_audit_app())

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

    def grant(
        self,
        resource_type: str,
        resource_id: str,
        action: str,
    ) -> ResourceGrant:
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
            database_operation_resource_id("sandbox_sales", "update"),
            DATABASE_OPERATION_EXECUTE_ACTION,
        )
        self.grant("database_table", "sandbox_sales.factory_access_events", "read")
        self.grant("database_column", "sandbox_sales.factory_access_events.event_id", "read")
        self.grant("database_column", "sandbox_sales.factory_access_events.direction", "read")
        return operation_grant

    def prepare_update(self, token: str):
        return self.client.post(
            "/api/database/operations/prepare",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "database_id": "sandbox_sales",
                "sql": (
                    "update factory_access_events set direction = 'manual_override' "
                    "where event_id = 1001"
                ),
                "reason": "audit test",
            },
        )

    def confirm(self, token: str, confirmation_id: str):
        return self.client.post(
            f"/api/database/confirmations/{confirmation_id}/confirm",
            headers={"Authorization": f"Bearer {token}"},
        )

    def event(self, event_type: str) -> AuditEvent:
        matches = [event for event in self.sink.events if event.event_type == event_type]
        self.assertTrue(matches, f"missing audit event {event_type}")
        return matches[-1]

    def test_prepare_confirm_and_execute_audit_include_stable_metadata(self):
        self.grant_orders_update_scope()
        token = self.login()

        prepare_response = self.prepare_update(token)
        confirmation_id = prepare_response.json()["data"]["confirmation_id"]
        confirm_response = self.confirm(token, confirmation_id)

        self.assertEqual(prepare_response.status_code, 200, prepare_response.text)
        self.assertEqual(confirm_response.status_code, 200, confirm_response.text)

        prepare_event = self.event("database_operation_prepare_created")
        confirmed_event = self.event("database_operation_confirmation_confirmed")
        executed_event = self.event("database_operation_executed")

        self.assertEqual(prepare_event.decision, "allowed")
        self.assertEqual(prepare_event.user_id, "user_demo_dept1")
        self.assertEqual(prepare_event.metadata["confirmation_id"], confirmation_id)
        self.assertEqual(prepare_event.metadata["database_id"], "sandbox_sales")
        self.assertEqual(prepare_event.metadata["operation_type"], "update")
        self.assertEqual(prepare_event.metadata["sql_hash_version"], "dbops-sql-hash-v1")
        self.assertEqual(prepare_event.metadata["normalization_version"], "sqlglot-normalize-v1")
        self.assertIn("sql_hash", prepare_event.metadata)
        self.assertIn("parameters_hash", prepare_event.metadata)
        self.assertIn("resource_ids", prepare_event.metadata)

        for event in (confirmed_event, executed_event):
            self.assertEqual(event.metadata["confirmation_id"], confirmation_id)
            self.assertEqual(event.metadata["database_id"], "sandbox_sales")
            self.assertEqual(event.metadata["operation_type"], "update")
            self.assertEqual(event.metadata["sql_hash_version"], "dbops-sql-hash-v1")
            self.assertIn("sql_hash", event.metadata)
            self.assertIn("parameters_hash", event.metadata)
            self.assertIn("resource_ids", event.metadata)

        self.assertEqual(executed_event.decision, "allowed")
        self.assertEqual(executed_event.metadata["rows_affected"], 1)

    def test_prepare_denied_and_cancel_audit_are_separate_from_admin_audit(self):
        token = self.login()
        denied_prepare = self.prepare_update(token)
        self.assertEqual(denied_prepare.status_code, 403, denied_prepare.text)
        denied_event = self.event("database_operation_prepare_rejected")

        self.assertEqual(denied_event.decision, "denied")
        self.assertEqual(denied_event.reason, "default_deny")
        self.assertEqual(denied_event.metadata["database_id"], "sandbox_sales")
        self.assertEqual(denied_event.metadata["operation_type"], "update")
        self.assertNotIn("permission_request_approved", [event.event_type for event in self.sink.events])

        self.grant_orders_update_scope()
        confirmation_id = self.prepare_update(token).json()["data"]["confirmation_id"]
        cancel_response = self.client.post(
            f"/api/database/confirmations/{confirmation_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(cancel_response.status_code, 200, cancel_response.text)
        cancel_event = self.event("database_operation_confirmation_cancelled")
        self.assertEqual(cancel_event.decision, "allowed")
        self.assertEqual(cancel_event.reason, "cancelled_by_owner")
        self.assertEqual(cancel_event.metadata["confirmation_id"], confirmation_id)
        self.assertIn("parameters_hash", cancel_event.metadata)
        self.assertIn("resource_ids", cancel_event.metadata)

    def test_expired_and_failed_confirm_audit_include_reason(self):
        operation_grant = self.grant_orders_update_scope()
        token = self.login()
        expired_confirmation_id = self.prepare_update(token).json()["data"]["confirmation_id"]
        repository = database_routes.get_database_operation_prepare_service().repository
        expired_confirmation = repository.get(expired_confirmation_id)
        self.assertIsNotNone(expired_confirmation)
        repository.update(
            expired_confirmation.model_copy(
                update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
            )
        )

        expired_response = self.confirm(token, expired_confirmation_id)

        self.assertEqual(expired_response.status_code, 409, expired_response.text)
        expired_event = self.event("database_operation_confirmation_expired")
        self.assertEqual(expired_event.decision, "denied")
        self.assertEqual(expired_event.reason, "confirmation_expired")
        self.assertEqual(expired_event.metadata["confirmation_id"], expired_confirmation_id)
        self.assertIn("parameters_hash", expired_event.metadata)

        failed_confirmation_id = self.prepare_update(token).json()["data"]["confirmation_id"]
        self.permission_service.revoke_grant(operation_grant.grant_id)

        failed_response = self.confirm(token, failed_confirmation_id)

        self.assertEqual(failed_response.status_code, 403, failed_response.text)
        failed_event = self.event("database_operation_execution_failed")
        self.assertEqual(failed_event.decision, "denied")
        self.assertEqual(failed_event.reason, "default_deny")
        self.assertEqual(failed_event.metadata["confirmation_id"], failed_confirmation_id)
        self.assertIn("parameters_hash", failed_event.metadata)


if __name__ == "__main__":
    unittest.main()
