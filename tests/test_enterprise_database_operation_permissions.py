import unittest

from app.enterprise.context import RequestContext
from app.enterprise.database.operation_permissions import (
    DATABASE_OPERATION_EXECUTE_ACTION,
    DATABASE_OPERATION_RESOURCE_TYPE,
    DatabaseOperationPermissionChecker,
    database_operation_resource_id,
)
from app.enterprise.database.registry import (
    ColumnPolicy,
    DatabaseSchemaRegistry,
    TablePolicy,
    build_default_sandbox_registry,
)
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService


class EnterpriseDatabaseOperationPermissionTests(unittest.TestCase):
    def setUp(self):
        self.sink = InMemoryAuditSink()
        self.permission_service = PermissionService(
            repository=InMemoryGovernanceRepository(),
            audit_service=AuditService(sinks=[self.sink]),
        )
        self.registry = build_default_sandbox_registry()
        self.checker = DatabaseOperationPermissionChecker(
            registry=self.registry,
            permission_service=self.permission_service,
            dialect="mysql",
        )
        self.context = RequestContext(
            request_id="db-ops-4-request",
            trace_id="db-ops-4-trace",
            user_id="user_demo_dept1",
            username="demo_user_dept1",
            department_id="dept_1",
            department_name="Department 1",
            roles=["user"],
        )

    def grant(
        self,
        resource_type: str,
        resource_id: str,
        action: str,
        *,
        principal_type: PrincipalType = PrincipalType.USER,
        principal_id: str = "user_demo_dept1",
        effect: GrantEffect = GrantEffect.ALLOW,
        reason: str | None = None,
    ) -> None:
        self.permission_service.grant_access(
            ResourceGrant(
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                principal_type=principal_type,
                principal_id=principal_id,
                effect=effect,
                reason=reason,
            )
        )

    def grant_orders_delete_scope(self) -> None:
        self.grant(
            DATABASE_OPERATION_RESOURCE_TYPE,
            database_operation_resource_id("sandbox_sales", "delete"),
            DATABASE_OPERATION_EXECUTE_ACTION,
        )
        self.grant("database_table", "sandbox_sales.factory_access_events", "read")
        self.grant("database_column", "sandbox_sales.factory_access_events.event_id", "read")

    def grant_orders_update_scope(self) -> None:
        self.grant(
            DATABASE_OPERATION_RESOURCE_TYPE,
            database_operation_resource_id("sandbox_sales", "update"),
            DATABASE_OPERATION_EXECUTE_ACTION,
        )
        self.grant("database_table", "sandbox_sales.factory_access_events", "read")

    def grant_orders_ddl_scope(self) -> None:
        self.grant(
            DATABASE_OPERATION_RESOURCE_TYPE,
            database_operation_resource_id("sandbox_sales", "ddl"),
            DATABASE_OPERATION_EXECUTE_ACTION,
        )
        self.grant("database_table", "sandbox_sales.factory_access_events", "read")

    def test_allows_prepare_when_operation_table_and_column_permissions_exist(self):
        self.grant_orders_delete_scope()

        result = self.checker.check_sql(
            self.context,
            "delete from factory_access_events where event_id = 1001",
        )

        self.assertTrue(result.allowed)
        self.assertEqual(result.reason, "ready_for_confirmation")
        self.assertEqual(result.operation_type, "delete")
        self.assertEqual(result.operation_resource_id, "sandbox_sales.delete")
        self.assertEqual(result.denied_tables, [])
        self.assertEqual(result.denied_columns, [])

    def test_denies_prepare_without_operation_permission(self):
        self.grant("database_table", "sandbox_sales.factory_access_events", "read")
        self.grant("database_column", "sandbox_sales.factory_access_events.event_id", "read")

        result = self.checker.check_sql(
            self.context,
            "delete from factory_access_events where event_id = 1001",
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "default_deny")
        self.assertEqual(result.operation_resource_id, "sandbox_sales.delete")

    def test_denies_prepare_when_explicit_deny_overrides_allow(self):
        self.grant(
            DATABASE_OPERATION_RESOURCE_TYPE,
            database_operation_resource_id("sandbox_sales", "delete"),
            DATABASE_OPERATION_EXECUTE_ACTION,
            principal_type=PrincipalType.ROLE,
            principal_id="user",
        )
        self.grant(
            DATABASE_OPERATION_RESOURCE_TYPE,
            database_operation_resource_id("sandbox_sales", "delete"),
            DATABASE_OPERATION_EXECUTE_ACTION,
            effect=GrantEffect.DENY,
            reason="incident-freeze",
        )
        self.grant("database_table", "sandbox_sales.factory_access_events", "read")
        self.grant("database_column", "sandbox_sales.factory_access_events.event_id", "read")

        result = self.checker.check_sql(
            self.context,
            "delete from factory_access_events where event_id = 1001",
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "incident-freeze")

    def test_denies_prepare_without_table_permission(self):
        self.grant(
            DATABASE_OPERATION_RESOURCE_TYPE,
            database_operation_resource_id("sandbox_sales", "delete"),
            DATABASE_OPERATION_EXECUTE_ACTION,
        )
        self.grant("database_column", "sandbox_sales.factory_access_events.event_id", "read")

        result = self.checker.check_sql(
            self.context,
            "delete from factory_access_events where event_id = 1001",
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "database_table_denied")
        self.assertEqual(result.denied_tables, ["factory_access_events"])

    def test_denies_prepare_without_column_permission(self):
        self.grant(
            DATABASE_OPERATION_RESOURCE_TYPE,
            database_operation_resource_id("sandbox_sales", "delete"),
            DATABASE_OPERATION_EXECUTE_ACTION,
        )
        self.grant("database_table", "sandbox_sales.factory_access_events", "read")

        result = self.checker.check_sql(
            self.context,
            "delete from factory_access_events where event_id = 1001",
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "database_column_denied")
        self.assertEqual(result.denied_columns, ["factory_access_events.event_id"])

    def test_insert_prepare_checks_inserted_columns(self):
        self.grant_orders_update_scope()
        self.grant("database_column", "sandbox_sales.factory_access_events.event_id", "read")

        result = self.checker.check_sql(
            self.context,
            "insert into factory_access_events (event_id, direction) values (1001, 10)",
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "database_column_denied")
        self.assertEqual(result.operation_resource_id, "sandbox_sales.update")
        self.assertEqual(result.denied_columns, ["factory_access_events.direction"])

    def test_alter_table_add_column_checks_declared_column_scope(self):
        registry = DatabaseSchemaRegistry(
            database_id="sandbox_sales",
            tables={
                "factory_access_events": TablePolicy(
                    name="factory_access_events",
                    description="factory_access_events",
                    columns={
                        "event_id": ColumnPolicy("event_id", "INTEGER"),
                        "status": ColumnPolicy("status", "TEXT"),
                    },
                )
            },
        )
        checker = DatabaseOperationPermissionChecker(
            registry=registry,
            permission_service=self.permission_service,
            dialect="mysql",
        )
        self.grant_orders_ddl_scope()

        result = checker.check_sql(
            self.context,
            "alter table factory_access_events add column status varchar(20)",
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "database_column_denied")
        self.assertEqual(result.operation_resource_id, "sandbox_sales.ddl")
        self.assertEqual(result.denied_columns, ["factory_access_events.status"])

    def test_delete_prepare_checks_subquery_table_and_columns_by_owner_table(self):
        registry = DatabaseSchemaRegistry(
            database_id="sandbox_sales",
            tables={
                "factory_access_events": TablePolicy(
                    name="factory_access_events",
                    description="factory_access_events",
                    columns={
                        "event_id": ColumnPolicy("event_id", "INTEGER"),
                        "customer_id": ColumnPolicy("customer_id", "INTEGER"),
                    },
                ),
                "customers": TablePolicy(
                    name="customers",
                    description="customers",
                    columns={
                        "id": ColumnPolicy("id", "INTEGER"),
                        "status": ColumnPolicy("status", "TEXT"),
                    },
                ),
            },
        )
        checker = DatabaseOperationPermissionChecker(
            registry=registry,
            permission_service=self.permission_service,
            dialect="mysql",
        )
        self.grant(
            DATABASE_OPERATION_RESOURCE_TYPE,
            database_operation_resource_id("sandbox_sales", "delete"),
            DATABASE_OPERATION_EXECUTE_ACTION,
        )
        for resource_id in [
            "sandbox_sales.factory_access_events",
            "sandbox_sales.customers",
            "sandbox_sales.factory_access_events.customer_id",
            "sandbox_sales.customers.id",
            "sandbox_sales.customers.status",
        ]:
            resource_type = "database_column" if resource_id.count(".") == 2 else "database_table"
            self.grant(resource_type, resource_id, "read")

        result = checker.check_sql(
            self.context,
            "delete from factory_access_events where customer_id in "
            "(select id from customers where status = 1)",
        )

        self.assertTrue(result.allowed)
        self.assertEqual(result.denied_tables, [])
        self.assertEqual(result.denied_columns, [])


if __name__ == "__main__":
    unittest.main()
