import unittest

from app.enterprise.context import RequestContext
from app.enterprise.database.context_builder import DatabaseContextBuilder
from app.enterprise.database.registry import build_default_sandbox_registry
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService


class DatabaseContextBuilderTests(unittest.TestCase):
    def setUp(self):
        self.audit_service = AuditService(sinks=[InMemoryAuditSink()])
        self.permission_service = PermissionService(
            repository=InMemoryGovernanceRepository(),
            audit_service=self.audit_service,
        )
        self.context = RequestContext(
            request_id="request-db-context",
            trace_id="trace-db-context",
            user_id="user_demo_dept1",
            username="demo_user_dept1",
            department_id="dept_1",
            department_name="Department 1",
            roles=["user"],
        )
        self.builder = DatabaseContextBuilder(
            registry=build_default_sandbox_registry(),
            permission_service=self.permission_service,
        )

    def grant(self, resource_type: str, resource_id: str, action: str = "read") -> None:
        self.permission_service.grant_access(
            ResourceGrant(
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                principal_type=PrincipalType.USER,
                principal_id=self.context.user_id,
                effect=GrantEffect.ALLOW,
            )
        )

    def test_context_includes_examples_and_only_authorized_columns(self):
        self.grant("database_table", "sandbox_sales.factory_access_events")
        self.grant("database_column", "sandbox_sales.factory_access_events.event_id")
        self.grant("database_column", "sandbox_sales.factory_access_events.direction")

        context = self.builder.build_context(
            self.context,
            question="查询最近进厂记录",
        )

        self.assertEqual(context["status"], "success")
        self.assertEqual(context["database_id"], "sandbox_sales")
        self.assertIn("F01", [example["example_id"] for example in context["relevant_examples"]])
        self.assertEqual(
            context["tables"],
            [
                {
                    "table_name": "factory_access_events",
                    "description": "Employee factory gate entry and exit access events.",
                    "authorized_columns": [
                        {
                            "name": "event_id",
                            "data_type": "INTEGER",
                            "sensitive": False,
                            "mask": None,
                            "description": "Event id",
                        },
                        {
                            "name": "direction",
                            "data_type": "TEXT",
                            "sensitive": False,
                            "mask": None,
                            "description": "Access direction: entry or exit",
                        },
                    ],
                }
            ],
        )
        self.assertIn("禁止 SELECT *", context["context_text"])
        self.assertIn("factory_access_events", context["context_text"])
        self.assertIn("event_id, direction", context["context_text"])
        self.assertNotIn("raw_device_payload", context["context_text"])

    def test_context_does_not_expose_ungranted_tables(self):
        context = self.builder.build_context(
            self.context,
            question="查询最近进厂记录",
        )

        self.assertEqual(context["status"], "success")
        self.assertEqual(context["relevant_examples"], [])
        self.assertEqual(context["tables"], [])
        self.assertIn("当前用户没有可见的相关数据库表", context["context_text"])


if __name__ == "__main__":
    unittest.main()
