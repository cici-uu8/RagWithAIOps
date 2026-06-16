import tempfile
import unittest
from pathlib import Path

from app.config import config
from app.enterprise.context import RequestContext
from app.enterprise.database.provider import DatabaseDemoToolProvider
from app.enterprise.database.registry import build_default_sandbox_registry
from app.enterprise.database.safe_sql import DatabaseExecutionError, SafeSqlBlocked, SafeSqlKernel
from app.enterprise.database.sandbox import create_sandbox_database
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService
from app.enterprise.tools.gateway import ToolGateway


class EnterpriseDatabaseE6Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
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
        self.context = RequestContext(
            request_id="request-e6",
            trace_id="trace-e6",
            user_id="user_demo_dept1",
            username="demo_user_dept1",
            department_id="dept_1",
            department_name="Department 1",
            roles=["user"],
        )

    def grant_database_tools(self):
        for resource_id in (
            "database_demo.list_tables",
            "database_demo.describe_table",
            "database_demo.safe_select",
        ):
            self.permission_service.grant_access(
                ResourceGrant(
                    resource_type="tool",
                    resource_id=resource_id,
                    action="use",
                    principal_type=PrincipalType.USER,
                    principal_id="user_demo_dept1",
                    effect=GrantEffect.ALLOW,
                )
            )

    async def test_default_tool_gateway_hides_ungranted_database_demo_tools(self):
        gateway = ToolGateway(
            providers=[self.provider],
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )

        visible = await gateway.list_visible_tools(self.context)

        self.assertEqual(visible, [])
        visible_audit = self.sink.events[-1]
        self.assertEqual(visible_audit.event_type, "tool_visible")
        self.assertEqual(visible_audit.metadata["filtered_tool_ids"], [])
        self.assertEqual(
            set(visible_audit.metadata["blocked_tool_ids"]),
            {
                "database_demo.list_tables",
                "database_demo.describe_table",
                "database_demo.safe_select",
            },
        )

    async def test_explicit_database_demo_session_can_list_describe_and_select(self):
        self.grant_database_tools()
        gateway = ToolGateway(
            providers=[self.provider],
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )

        visible = await gateway.list_visible_tools(self.context)
        self.assertEqual(
            [tool.resource_id for tool in visible],
            [
                "database_demo.list_tables",
                "database_demo.describe_table",
                "database_demo.safe_select",
            ],
        )

        tables = await gateway.execute(self.context, "database_demo.list_tables", {})
        self.assertEqual(tables["tables"], ["factory_access_events", "building_access_events"])

        description = await gateway.execute(
            self.context,
            "database_demo.describe_table",
            {"table_name": "factory_access_events"},
        )
        self.assertEqual([column["name"] for column in description["columns"]], [
            "event_id",
            "employee_id",
            "employee_name",
            "department_name",
            "direction",
            "gate_name",
            "event_time",
            "badge_id",
        ])

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
        self.assertEqual(result["status"], "success")
        self.assertTrue(any(event.event_type == "database_query" for event in self.sink.events))

    def test_safe_select_adds_limit_and_masks_sensitive_fields(self):
        result = self.kernel.safe_select(
            self.context,
            "select event_id, badge_id from factory_access_events order by event_id",
        )

        self.assertEqual(result["row_count"], 2)
        self.assertIn("LIMIT 2", result["sanitized_sql"].upper())
        self.assertEqual(result["rows"][0]["badge_id"], "BAD***001")
        audit = [event for event in self.sink.events if event.event_type == "database_query"][-1]
        self.assertEqual(audit.decision, "allowed")
        self.assertEqual(audit.metadata["status"], "success")
        self.assertEqual(audit.metadata["rows_returned"], 2)
        self.assertNotIn("BADGE001", audit.metadata["sanitized_sql"])

    def test_safe_select_blocks_oversized_results_and_audits(self):
        small_result_kernel = SafeSqlKernel(
            database_path=self.db_path,
            registry=self.registry,
            audit_service=self.audit_service,
            default_limit=2,
            max_limit=5,
            max_result_size_bytes=10,
        )

        with self.assertRaises(SafeSqlBlocked):
            small_result_kernel.safe_select(
                self.context,
                "select event_id, employee_name from factory_access_events order by event_id limit 2",
            )

        audit = [event for event in self.sink.events if event.event_type == "database_query"][-1]
        self.assertEqual(audit.decision, "denied")
        self.assertEqual(audit.reason, "result_size_exceeds_max")
        self.assertEqual(audit.metadata["status"], "blocked")

    def test_safe_select_timeout_is_audited_as_execution_failure(self):
        timeout_kernel = SafeSqlKernel(
            database_path=self.db_path,
            registry=self.registry,
            audit_service=self.audit_service,
            timeout_seconds=0,
            progress_check_steps=1,
        )

        with self.assertRaises(DatabaseExecutionError):
            timeout_kernel.safe_select(self.context, "select event_id from factory_access_events limit 1")

        audit = [event for event in self.sink.events if event.event_type == "database_query"][-1]
        self.assertEqual(audit.decision, "failed")
        self.assertEqual(audit.metadata["status"], "failed")
        self.assertEqual(audit.error_class, "OperationalError")

    def test_safe_select_blocks_dangerous_or_unauthorized_sql_and_audits(self):
        cases = [
            "update factory_access_events set direction = 0 where event_id = 1001",
            "drop table factory_access_events",
            "select event_id from factory_access_events; select event_id from building_access_events",
            "select name from sqlite_master",
            "select raw_device_payload from factory_access_events",
            "select badge_id as email from factory_access_events",
        ]

        for sql in cases:
            with self.subTest(sql=sql):
                with self.assertRaises(SafeSqlBlocked):
                    self.kernel.safe_select(self.context, sql)

        blocked_events = [
            event
            for event in self.sink.events
            if event.event_type == "database_query" and event.decision == "denied"
        ]
        self.assertEqual(len(blocked_events), len(cases))
        self.assertTrue(all(event.metadata["status"] == "blocked" for event in blocked_events))

    def test_database_execution_failure_is_audited_without_raw_exception_leakage(self):
        broken_kernel = SafeSqlKernel(
            database_path=Path(self.tmpdir.name) / "missing.sqlite3",
            registry=self.registry,
            audit_service=self.audit_service,
        )

        with self.assertRaises(DatabaseExecutionError):
            broken_kernel.safe_select(self.context, "select event_id from factory_access_events limit 1")

        audit = [event for event in self.sink.events if event.event_type == "database_query"][-1]
        self.assertEqual(audit.decision, "failed")
        self.assertEqual(audit.metadata["status"], "failed")
        self.assertEqual(audit.error_class, "OperationalError")
        self.assertIsNone(audit.error_message)

    def test_default_mcp_server_config_does_not_register_database_tools(self):
        self.assertEqual(set(config.mcp_servers), {"cls", "monitor"})
        self.assertNotIn("database", config.mcp_servers)
        self.assertNotIn("database-demo", config.mcp_servers)


if __name__ == "__main__":
    unittest.main()
