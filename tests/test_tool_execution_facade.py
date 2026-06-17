import unittest

from langchain_core.tools import tool

from app.enterprise.context import (
    RequestContext,
    reset_current_request_context,
    set_current_request_context,
)
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService
from app.enterprise.tools.facade import ToolExecutionFacade
from app.enterprise.tools.gateway import ToolGateway
from app.enterprise.tools.local_provider import (
    LocalAgentToolProvider,
    build_local_agent_tool_execution_facade,
)
from app.enterprise.tools.models import ToolDefinition
from app.enterprise.tools.providers import StaticToolProvider


@tool
async def raw_echo(text: str) -> dict:
    """Echo text."""

    return {"echo": text}


@tool(response_format="content_and_artifact")
def raw_search(query: str) -> tuple[str, dict]:
    """Search with diagnostics artifact."""

    return "没有找到相关信息。", {
        "diagnostics": {
            "no_result_reason": "retrieval_no_hit",
            "selected_kb_ids": ["process_digital_dept"],
        }
    }


class ToolExecutionFacadeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sink = InMemoryAuditSink()
        self.audit_service = AuditService(sinks=[self.sink])
        self.permission_service = PermissionService(
            repository=InMemoryGovernanceRepository(),
            audit_service=self.audit_service,
        )
        self.context = RequestContext(
            request_id="request-facade",
            trace_id="trace-facade",
            user_id="user_demo_dept1",
            username="demo_user_dept1",
            department_id="dept_1",
            department_name="Department 1",
            roles=["user"],
        )

    def grant_tool(self, resource_id: str):
        self.permission_service.grant_access(
            ResourceGrant(
                resource_type="tool",
                resource_id=resource_id,
                action="use",
                principal_type=PrincipalType.USER,
                principal_id=self.context.user_id,
                effect=GrantEffect.ALLOW,
            )
        )

    def build_facade(self) -> ToolExecutionFacade:
        provider = StaticToolProvider(
            [
                ToolDefinition(
                    resource_id="local_echo",
                    name="raw_echo",
                    description="Echo text",
                    source="local",
                    raw_tool=raw_echo,
                ),
                ToolDefinition(
                    resource_id="hidden_tool",
                    name="hidden_tool",
                    description="Hidden",
                    source="local",
                    raw_tool=raw_echo,
                ),
            ]
        )
        gateway = ToolGateway(
            providers=[provider],
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )
        return ToolExecutionFacade(gateway=gateway)

    async def test_bindable_tools_are_permission_filtered_and_execute_through_gateway(self):
        self.grant_tool("local_echo")
        facade = self.build_facade()

        visible = await facade.list_visible_tools(self.context)
        bindable = await facade.get_bindable_tools(self.context)
        result = await bindable[0].ainvoke({"text": "hello"})

        self.assertEqual([tool.resource_id for tool in visible], ["local_echo"])
        self.assertEqual([tool.name for tool in bindable], ["raw_echo"])
        self.assertEqual(result, {"echo": "hello"})
        self.assertTrue(
            any(
                event.event_type == "tool_call"
                and event.metadata["tool_id"] == "local_echo"
                for event in self.sink.events
            )
        )
        self.assertTrue(
            any(
                event.event_type == "tool_visible"
                and "hidden_tool" in event.metadata["blocked_tool_ids"]
                for event in self.sink.events
            )
        )

    async def test_facade_execute_delegates_to_tool_gateway(self):
        self.grant_tool("local_echo")
        facade = self.build_facade()

        result = await facade.execute(self.context, "local_echo", {"text": "direct"})

        self.assertEqual(result, {"echo": "direct"})
        self.assertEqual(self.sink.events[-1].event_type, "tool_call")
        self.assertEqual(self.sink.events[-1].metadata["tool_id"], "local_echo")

    async def test_facade_execute_preserves_content_and_artifact_tool_result(self):
        provider = StaticToolProvider(
            [
                ToolDefinition(
                    resource_id="raw_search",
                    name="raw_search",
                    description="Search with diagnostics artifact",
                    source="local",
                    raw_tool=raw_search,
                )
            ]
        )
        gateway = ToolGateway(
            providers=[provider],
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )
        self.grant_tool("raw_search")
        facade = ToolExecutionFacade(gateway=gateway)

        content, artifact = await facade.execute(
            self.context,
            "raw_search",
            {"query": "中车长客数字化转型"},
        )

        self.assertEqual(content, "没有找到相关信息。")
        self.assertEqual(artifact["diagnostics"]["no_result_reason"], "retrieval_no_hit")

    async def test_facade_can_filter_visible_tools_by_tool_id(self):
        self.grant_tool("local_echo")
        self.grant_tool("hidden_tool")
        facade = self.build_facade()

        visible = await facade.list_visible_tools(
            self.context,
            tool_ids={"hidden_tool"},
        )
        bindable = await facade.get_bindable_tools(
            self.context,
            tool_ids={"hidden_tool"},
        )

        self.assertEqual([tool.resource_id for tool in visible], ["hidden_tool"])
        self.assertEqual([tool.name for tool in bindable], ["raw_echo"])

    async def test_local_agent_provider_keeps_resource_id_separate_from_bindable_name(self):
        provider = LocalAgentToolProvider()

        tools = {tool.resource_id: tool for tool in await provider.list_tools()}

        self.assertEqual(tools["retrieve_knowledge"].name, "retrieve_knowledge")
        self.assertEqual(tools["list_knowledge_documents"].name, "list_knowledge_documents")
        self.assertEqual(tools["get_current_time"].name, "get_current_time")
        self.assertEqual(tools["database_demo.retrieve_context"].name, "retrieve_database_context")
        self.assertEqual(tools["database_demo.safe_select"].name, "safe_select_database")
        self.assertEqual(tools["database_demo.list_tables"].name, "list_database_tables")

    async def test_local_agent_facade_default_allows_core_tools_and_filters_database(self):
        facade = build_local_agent_tool_execution_facade(
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )

        visible = await facade.list_visible_tools(self.context, capability="rag")
        bindable = await facade.get_bindable_tools(self.context, capability="rag")

        self.assertEqual(
            [tool.resource_id for tool in visible],
            ["retrieve_knowledge", "list_knowledge_documents"],
        )
        self.assertEqual(
            [tool.name for tool in bindable],
            ["retrieve_knowledge", "list_knowledge_documents"],
        )
        self.assertTrue(
            any(
                event.event_type == "tool_visible"
                and "database_demo.safe_select" in event.metadata["blocked_tool_ids"]
                and "database_demo.retrieve_context" in event.metadata["blocked_tool_ids"]
                and "retrieve_knowledge" in event.metadata["default_allowed_tool_ids"]
                for event in self.sink.events
            )
        )

        self.grant_tool("database_demo.retrieve_context")
        self.grant_tool("database_demo.safe_select")

        visible_after_grant = await facade.list_visible_tools(self.context, capability="rag")
        bindable_after_grant = await facade.get_bindable_tools(self.context, capability="rag")

        self.assertIn(
            "database_demo.retrieve_context",
            [tool.resource_id for tool in visible_after_grant],
        )
        self.assertIn(
            "database_demo.safe_select",
            [tool.resource_id for tool in visible_after_grant],
        )
        self.assertIn(
            "retrieve_database_context",
            [tool.name for tool in bindable_after_grant],
        )

    async def test_rag_agent_initializes_enterprise_bindable_tools_through_facade(self):
        import app.services.rag_agent_service as rag_agent_service_module

        class FakeFacade:
            def __init__(self):
                self.contexts: list[RequestContext] = []

            async def get_bindable_tools(self, context, *, capability=None):
                self.contexts.append(context)
                self.capability = capability
                return [raw_echo]

        facade = FakeFacade()
        service = rag_agent_service_module.RagAgentService(
            streaming=False,
            tool_execution_facade=facade,
        )
        token = set_current_request_context(self.context)
        self.addCleanup(reset_current_request_context, token)

        with unittest.mock.patch.object(
            rag_agent_service_module,
            "create_agent",
            return_value="agent-from-facade",
        ) as create_agent_mock, unittest.mock.patch.object(
            rag_agent_service_module,
            "get_mcp_client_with_retry",
            side_effect=AssertionError("direct MCP client should not be used"),
        ):
            agent = await service._build_request_agent()

        self.assertIs(agent, "agent-from-facade")
        self.assertEqual(facade.contexts, [self.context])
        self.assertEqual(facade.capability, "rag")
        self.assertEqual(create_agent_mock.call_args.kwargs["tools"], [raw_echo])


if __name__ == "__main__":
    unittest.main()
