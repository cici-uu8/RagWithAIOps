import unittest

from app.enterprise.context import RequestContext
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService
from app.enterprise.tools.gateway import ToolAccessDenied, ToolExecutionError, ToolGateway
from app.enterprise.tools.models import ToolDefinition
from app.enterprise.tools.providers import StaticToolProvider


async def echo_handler(arguments):
    return {"echo": arguments["text"]}


async def failing_handler(arguments):
    raise RuntimeError("tool exploded")


class EnterpriseToolGatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sink = InMemoryAuditSink()
        self.audit_service = AuditService(sinks=[self.sink])
        self.permission_service = PermissionService(
            repository=InMemoryGovernanceRepository(),
            audit_service=self.audit_service,
        )
        self.context = RequestContext(
            request_id="request-tool",
            trace_id="trace-tool",
            user_id="user_demo_dept1",
            username="demo_user_dept1",
            department_id="dept_1",
            department_name="Department 1",
            roles=["user"],
        )
        self.provider = StaticToolProvider(
            [
                ToolDefinition(
                    resource_id="local_echo",
                    name="echo",
                    description="Echo input text",
                    source="local",
                    handler=echo_handler,
                ),
                ToolDefinition(
                    resource_id="hidden_tool",
                    name="hidden",
                    description="Hidden tool",
                    source="local",
                    handler=echo_handler,
                ),
                ToolDefinition(
                    resource_id="db_safe_select",
                    name="safe_select",
                    description="Database demo select",
                    source="database-demo",
                    handler=echo_handler,
                    metadata={"category": "database"},
                ),
                ToolDefinition(
                    resource_id="failing_tool",
                    name="failing",
                    description="Failure fixture",
                    source="local",
                    handler=failing_handler,
                ),
            ]
        )
        self.gateway = ToolGateway(
            providers=[self.provider],
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )

    def grant_tool(self, resource_id: str):
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

    async def test_visible_tools_filter_permissions_including_database_tools(self):
        self.grant_tool("local_echo")
        self.grant_tool("db_safe_select")

        visible = await self.gateway.list_visible_tools(self.context)

        self.assertEqual([tool.resource_id for tool in visible], ["local_echo", "db_safe_select"])
        visible_audit = self.sink.events[-1]
        self.assertEqual(visible_audit.event_type, "tool_visible")
        self.assertEqual(
            visible_audit.metadata["visible_tool_ids"],
            ["local_echo", "db_safe_select"],
        )
        self.assertIn("hidden_tool", visible_audit.metadata["blocked_tool_ids"])
        self.assertEqual(visible_audit.metadata["filtered_tool_ids"], [])

    async def test_bindable_tools_do_not_include_unauthorized_tools(self):
        self.grant_tool("local_echo")

        bindable = await self.gateway.get_bindable_tools(self.context)

        self.assertEqual([tool.name for tool in bindable], ["echo"])

    async def test_authorized_tool_execution_writes_tool_call_audit(self):
        self.grant_tool("local_echo")

        result = await self.gateway.execute(self.context, "local_echo", {"text": "hello"})

        self.assertEqual(result, {"echo": "hello"})
        audit = self.sink.events[-1]
        self.assertEqual(audit.event_type, "tool_call")
        self.assertEqual(audit.decision, "allowed")
        self.assertEqual(audit.metadata["tool_id"], "local_echo")
        self.assertEqual(audit.metadata["status"], "success")
        self.assertIsNotNone(audit.latency_ms)

    async def test_unauthorized_tool_execution_is_blocked_and_audited(self):
        with self.assertRaises(ToolAccessDenied):
            await self.gateway.execute(self.context, "hidden_tool", {"text": "no"})

        audit = self.sink.events[-1]
        self.assertEqual(audit.event_type, "tool_blocked")
        self.assertEqual(audit.decision, "denied")
        self.assertEqual(audit.reason, "default_deny")
        self.assertEqual(audit.metadata["tool_id"], "hidden_tool")

    async def test_tool_failure_writes_failure_event(self):
        self.grant_tool("failing_tool")

        with self.assertRaises(ToolExecutionError):
            await self.gateway.execute(self.context, "failing_tool", {"text": "boom"})

        audit = self.sink.events[-1]
        self.assertEqual(audit.event_type, "tool_failure")
        self.assertEqual(audit.decision, "failed")
        self.assertEqual(audit.error_class, "tool_failed")
        self.assertEqual(audit.metadata["source_error_class"], "RuntimeError")
        self.assertEqual(audit.metadata["recovery_decision"], "abort")
        self.assertEqual(audit.metadata["tool_id"], "failing_tool")
        self.assertEqual(audit.metadata["status"], "failed")


if __name__ == "__main__":
    unittest.main()
