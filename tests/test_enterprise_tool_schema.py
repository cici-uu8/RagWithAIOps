import tempfile
import unittest
from pathlib import Path

from app.enterprise.database.mysql import DatabaseMySqlToolProvider
from app.enterprise.database.provider import DatabaseDemoToolProvider
from app.enterprise.database.registry import (
    ColumnPolicy,
    DatabaseSchemaRegistry,
    TablePolicy,
    build_default_sandbox_registry,
)
from app.enterprise.database.safe_sql import SafeSqlKernel
from app.enterprise.database.sandbox import create_sandbox_database
from app.enterprise.database.tool_schemas import database_prepare_operation_input_schema
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.tools.models import ToolDefinition
from app.enterprise.tools.providers import StaticToolProvider
from app.enterprise.tools.schema import openai_function_name, to_openai_function_tool


async def echo_handler(arguments):
    return {"echo": arguments}


class FakeKernel:
    audit_service = AuditService()


class EnterpriseToolSchemaTests(unittest.IsolatedAsyncioTestCase):
    def test_tool_definition_exports_strict_openai_function_schema(self):
        tool = ToolDefinition(
            resource_id="database_demo.safe_select",
            name="safe_select",
            description="Execute one SELECT",
            input_schema={
                "type": "object",
                "properties": {
                    "sql": {"type": "string"},
                },
                "required": ["sql"],
                "additionalProperties": False,
            },
        )

        schema = to_openai_function_tool(tool)

        self.assertEqual(schema["type"], "function")
        self.assertEqual(schema["function"]["name"], "database_demo_safe_select")
        self.assertEqual(schema["function"]["description"], "Execute one SELECT")
        self.assertTrue(schema["function"]["strict"])
        self.assertEqual(schema["function"]["parameters"]["required"], ["sql"])
        self.assertFalse(schema["function"]["parameters"]["additionalProperties"])

    async def test_tool_without_schema_still_executes_through_static_provider(self):
        provider = StaticToolProvider(
            [
                ToolDefinition(
                    resource_id="legacy_echo",
                    name="legacy_echo",
                    handler=echo_handler,
                )
            ]
        )

        result = await provider.execute_tool("legacy_echo", {"text": "hello"})

        self.assertEqual(result, {"echo": {"text": "hello"}})

    def test_raw_mcp_bindable_tool_is_preserved(self):
        raw_tool = object()
        tool = ToolDefinition(
            resource_id="mcp.search_logs",
            name="search_logs",
            raw_tool=raw_tool,
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        )

        self.assertIs(tool.bindable_tool, raw_tool)

    async def test_database_demo_tools_expose_strict_input_schemas(self):
        registry = build_default_sandbox_registry()
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = create_sandbox_database(Path(tmpdir) / "sandbox.sqlite3")
            kernel = SafeSqlKernel(
                database_path=db_path,
                registry=registry,
            )
            provider = DatabaseDemoToolProvider(registry=registry, kernel=kernel)

            tools = {tool.resource_id: tool for tool in await provider.list_tools()}

        self.assertEqual(
            tools["database_demo.list_tables"].input_schema,
            {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        )
        self.assertEqual(
            tools["database_demo.describe_table"].input_schema["required"],
            ["table_name"],
        )
        self.assertFalse(
            tools["database_demo.describe_table"].input_schema["additionalProperties"],
        )
        self.assertEqual(
            tools["database_demo.safe_select"].input_schema["required"],
            ["sql"],
        )
        self.assertFalse(tools["database_demo.safe_select"].input_schema["additionalProperties"])

    async def test_mysql_database_tools_reuse_strict_input_schemas(self):
        registry = DatabaseSchemaRegistry(
            database_id="mysql_sales_readonly",
            tables={
                "orders": TablePolicy(
                    name="orders",
                    description="orders",
                    columns={"order_id": ColumnPolicy("order_id", "INTEGER")},
                )
            },
        )
        provider = DatabaseMySqlToolProvider(registry=registry, kernel=FakeKernel())

        tools = {tool.resource_id: tool for tool in await provider.list_tools()}

        self.assertEqual(
            tools["database_mysql.mysql_sales_readonly.list_tables"].input_schema["required"],
            [],
        )
        self.assertEqual(
            tools["database_mysql.mysql_sales_readonly.describe_table"].input_schema["required"],
            ["table_name"],
        )
        self.assertEqual(
            tools["database_mysql.mysql_sales_readonly.safe_select"].input_schema["required"],
            ["sql"],
        )

    def test_prepare_operation_schema_rejects_extra_fields(self):
        schema = database_prepare_operation_input_schema()

        self.assertEqual(schema["required"], ["sql"])
        self.assertFalse(schema["additionalProperties"])

    def test_openai_function_name_uses_unique_resource_id_not_display_name(self):
        demo_tool = ToolDefinition(resource_id="database_demo.safe_select", name="safe_select")
        mysql_tool = ToolDefinition(
            resource_id="database_mysql.mysql_sales_readonly.safe_select",
            name="safe_select",
        )

        self.assertEqual(openai_function_name(demo_tool), "database_demo_safe_select")
        self.assertEqual(
            openai_function_name(mysql_tool),
            "database_mysql_mysql_sales_readonly_safe_select",
        )


if __name__ == "__main__":
    unittest.main()
