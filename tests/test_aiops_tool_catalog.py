import unittest

from langchain_core.tools import tool

from app.enterprise.aiops.failure_semantics import AIOpsFailureLabel, AIOpsFailureSemantics
from app.enterprise.aiops.tool_catalog import (
    AIOpsToolCatalog,
    get_aiops_bindable_tools,
    retrieve_aiops_experience_context,
)
from app.enterprise.context import RequestContext
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService
from app.services.aiops_service import AIOpsService


@tool
async def fake_mcp_tool(service: str) -> dict:
    """Return fake MCP data."""

    return {"service": service}


class AIOpsToolCatalogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sink = InMemoryAuditSink()
        self.audit_service = AuditService(sinks=[self.sink])
        self.permission_service = PermissionService(
            repository=InMemoryGovernanceRepository(),
            audit_service=self.audit_service,
        )
        self.context = RequestContext(
            request_id="request-aiops-catalog",
            trace_id="trace-aiops-catalog",
            user_id="user_demo_dept1",
            username="demo_user_dept1",
            department_id="dept_1",
            department_name="Department 1",
            roles=["user"],
        )

    async def test_no_context_preserves_legacy_local_aiops_tools_and_mcp_loader(self):
        catalog = AIOpsToolCatalog(mcp_tool_loader=lambda: _async_tools([fake_mcp_tool]))

        tools = await catalog.bindable_tools()

        self.assertEqual(
            [tool.name for tool in tools],
            ["get_current_time", "retrieve_knowledge", "fake_mcp_tool"],
        )

    async def test_context_filters_local_aiops_tools_through_facade(self):
        catalog = AIOpsToolCatalog(
            mcp_tool_loader=lambda: _async_tools([]),
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )

        tools = await catalog.bindable_tools(self.context)

        self.assertEqual(
            [tool.name for tool in tools],
            ["retrieve_knowledge", "get_current_time"],
        )
        self.assertTrue(
            any(
                event.event_type == "tool_visible"
                and "list_knowledge_documents" not in event.metadata["visible_tool_ids"]
                and "database_demo.safe_select" in event.metadata["blocked_tool_ids"]
                for event in self.sink.events
            )
        )

    async def test_context_bound_local_tool_executes_through_gateway(self):
        catalog = AIOpsToolCatalog(
            mcp_tool_loader=lambda: _async_tools([]),
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )

        tools = {tool.name: tool for tool in await catalog.bindable_tools(self.context)}
        result = await tools["get_current_time"].ainvoke({"timezone": "Asia/Shanghai"})

        self.assertIsInstance(result, str)
        self.assertTrue(
            any(
                event.event_type == "tool_call"
                and event.metadata["tool_id"] == "get_current_time"
                and event.metadata["default_allowed"] is True
                for event in self.sink.events
            )
        )

    def test_required_tool_validation_reports_missing_aiops_tools(self):
        catalog = AIOpsToolCatalog()

        result = catalog.validate_required_tools(
            "CPUHigh",
            available_tools=[fake_mcp_tool],
        )

        self.assertIn("query_active_alerts", result.required_tools)
        self.assertIn("query_metric_series", result.required_tools)
        self.assertIn("search_service_logs", result.required_tools)
        self.assertIn("query_active_alerts", result.missing_required_tools)
        self.assertNotIn("fake_mcp_tool", result.missing_required_tools)
        self.assertEqual(result.failure_semantics, AIOpsFailureLabel.MISSING_REQUIRED_TOOL)
        self.assertFalse(result.passed)

    def test_required_tool_validation_records_standard_audit_metadata(self):
        catalog = AIOpsToolCatalog(
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )

        result = catalog.validate_required_tools(
            "CPUHigh",
            available_tools=[fake_mcp_tool],
            context=self.context,
        )

        self.assertEqual(result.failure_semantics, "missing_required_tool")
        self.assertTrue(
            any(
                event.event_type == "aiops_tool_validation"
                and event.decision == "blocked"
                and event.reason == "missing_required_tool"
                and event.metadata["failure_semantics"] == "missing_required_tool"
                and "query_active_alerts" in event.metadata["missing_required_tools"]
                for event in self.sink.events
            )
        )

    def test_failure_semantics_classifies_exception_and_state_shapes(self):
        self.assertEqual(
            AIOpsFailureSemantics.classify_exception(
                TimeoutError("executor get_tools timed out after 25s")
            ),
            AIOpsFailureLabel.MCP_TIMEOUT,
        )
        self.assertEqual(
            AIOpsFailureSemantics.classify_exception(
                TimeoutError("executor final llm response timed out after 60s")
            ),
            AIOpsFailureLabel.LLM_TIMEOUT,
        )
        self.assertEqual(
            AIOpsFailureSemantics.classify_exception(
                RuntimeError("replanner structured output failed in primary and fallback")
            ),
            AIOpsFailureLabel.STRUCTURED_OUTPUT_FAILED,
        )
        self.assertEqual(
            AIOpsFailureSemantics.classify_event(
                {"structured_output_recovered": True, "structured_output_primary_stage": "replanner"}
            ),
            AIOpsFailureLabel.STRUCTURED_OUTPUT_RECOVERED,
        )

    def test_failure_semantics_builds_sse_and_audit_shapes(self):
        event = AIOpsFailureSemantics.to_degradation_event(
            {
                "structured_output_recovered": True,
                "structured_output_primary_stage": "replanner",
                "structured_output_primary_error": "TimeoutError: replanner timed out",
            }
        )
        audit = AIOpsFailureSemantics.to_audit_metadata(event)
        sse = AIOpsFailureSemantics.to_sse_error(event)

        self.assertEqual(event["failure_semantics"], "structured_output_recovered")
        self.assertFalse(event["hard_failure"])
        self.assertEqual(audit["failure_semantics"], "structured_output_recovered")
        self.assertEqual(sse["failure_semantics"], "structured_output_recovered")
        self.assertFalse(sse["failure_semantics_hard_failure"])

    def test_aiops_service_sse_fields_use_standard_failure_semantics(self):
        service = AIOpsService()

        infra_event = service._format_executor_event(
            {
                "plan": [],
                "past_steps": [("查询指标", "执行失败: TimeoutError: executor get_tools timed out")],
                "infra_error": True,
                "infra_error_stage": "executor",
                "infra_error_message": "TimeoutError: executor get_tools timed out",
            }
        )
        recovered_event = service._format_replanner_event(
            {
                "plan": ["继续排查"],
                "structured_output_recovered": True,
                "structured_output_primary_stage": "replanner",
                "structured_output_primary_error": "TimeoutError: replanner structured output timed out",
            }
        )

        self.assertEqual(infra_event["failure_semantics"], "mcp_timeout")
        self.assertTrue(infra_event["failure_semantics_hard_failure"])
        self.assertEqual(recovered_event["failure_semantics"], "structured_output_recovered")
        self.assertFalse(recovered_event["failure_semantics_hard_failure"])

    async def test_bindable_helper_uses_catalog_when_request_context_exists(self):
        class FakeCatalog:
            def __init__(self):
                self.contexts = []

            async def bindable_tools(self, context):
                self.contexts.append(context)
                return [fake_mcp_tool]

        catalog = FakeCatalog()

        tools = await get_aiops_bindable_tools(
            context=self.context,
            catalog=catalog,
            local_tools=[],
            mcp_tool_loader=lambda: _raise_if_called(),
        )

        self.assertEqual(tools, [fake_mcp_tool])
        self.assertEqual(catalog.contexts, [self.context])

    async def test_experience_helper_executes_through_catalog_when_context_exists(self):
        class FakeCatalog:
            def __init__(self):
                self.calls = []

            async def execute(self, context, tool_id, arguments):
                self.calls.append((context, tool_id, arguments))
                return "经验文档"

        catalog = FakeCatalog()

        result = await retrieve_aiops_experience_context(
            "CPUHigh",
            context=self.context,
            catalog=catalog,
            retrieve_tool=_NeverCalledTool(),
        )

        self.assertEqual(result, "经验文档")
        self.assertEqual(
            catalog.calls,
            [(self.context, "retrieve_knowledge", {"query": "CPUHigh"})],
        )


async def _async_tools(tools):
    return tools


async def _raise_if_called():
    raise AssertionError("legacy MCP loader should not be called with context")


class _NeverCalledTool:
    async def ainvoke(self, _arguments):
        raise AssertionError("legacy retrieve_knowledge should not be called with context")


if __name__ == "__main__":
    unittest.main()
