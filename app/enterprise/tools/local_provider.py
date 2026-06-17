"""Local LangChain tools exposed as ToolGateway definitions."""

from __future__ import annotations

from app.enterprise.observability.audit_service import AuditService
from app.enterprise.permissions.service import PermissionService, permission_service
from app.enterprise.tools.facade import ToolExecutionFacade
from app.enterprise.tools.gateway import ToolGateway
from app.enterprise.tools.models import ToolDefinition
from app.enterprise.tools.pdf_document_provider import PDF_AGENT_TOOL_IDS, PdfDocumentToolProvider
from app.enterprise.tools.providers import StaticToolProvider
from app.tools import (
    describe_database_table,
    get_current_time,
    list_database_tables,
    list_knowledge_documents,
    retrieve_database_context,
    retrieve_knowledge,
    safe_select_database,
)

LOCAL_AGENT_DEFAULT_ALLOWED_TOOL_IDS = {
    "retrieve_knowledge",
    "list_knowledge_documents",
    "get_current_time",
    *PDF_AGENT_TOOL_IDS,
}


class LocalAgentToolProvider(StaticToolProvider):
    """Expose existing local Agent tools through the enterprise tool catalog."""

    def __init__(self):
        super().__init__(_local_agent_tool_definitions())


def build_local_agent_tool_gateway(
    *,
    permission_service: PermissionService | None = None,
    audit_service: AuditService | None = None,
) -> ToolGateway:
    """Build the local RAG agent tool gateway without broad MCP discovery."""

    return ToolGateway(
        providers=[LocalAgentToolProvider(), PdfDocumentToolProvider()],
        permission_service=permission_service or permission_service_default(),
        audit_service=audit_service,
        default_allowed_tool_ids=set(LOCAL_AGENT_DEFAULT_ALLOWED_TOOL_IDS),
    )


def build_local_agent_tool_execution_facade(
    *,
    permission_service: PermissionService | None = None,
    audit_service: AuditService | None = None,
) -> ToolExecutionFacade:
    return ToolExecutionFacade(
        gateway=build_local_agent_tool_gateway(
            permission_service=permission_service,
            audit_service=audit_service,
        )
    )


def list_local_agent_default_tool_ids() -> list[str]:
    return [
        tool.resource_id
        for tool in _local_agent_tool_definitions()
        if tool.resource_id in LOCAL_AGENT_DEFAULT_ALLOWED_TOOL_IDS
    ]


def _local_agent_tool_definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            resource_id="retrieve_knowledge",
            name="retrieve_knowledge",
            description=str(retrieve_knowledge.description),
            source="local",
            raw_tool=retrieve_knowledge,
            metadata={"category": "knowledge", "capability": "rag"},
        ),
        ToolDefinition(
            resource_id="list_knowledge_documents",
            name="list_knowledge_documents",
            description=str(list_knowledge_documents.description),
            source="local",
            raw_tool=list_knowledge_documents,
            metadata={"category": "knowledge", "capability": "rag"},
        ),
        ToolDefinition(
            resource_id="get_current_time",
            name="get_current_time",
            description=str(get_current_time.description),
            source="local",
            raw_tool=get_current_time,
            metadata={"category": "time", "capability": "common"},
        ),
        ToolDefinition(
            resource_id="database_demo.list_tables",
            name="list_database_tables",
            description=str(list_database_tables.description),
            source="local",
            raw_tool=list_database_tables,
            metadata={
                "category": "database",
                "capability": "rag",
                "database_id": "sandbox_sales",
                "operation_type": "list_tables",
                "read_only": True,
            },
        ),
        ToolDefinition(
            resource_id="database_demo.describe_table",
            name="describe_database_table",
            description=str(describe_database_table.description),
            source="local",
            raw_tool=describe_database_table,
            metadata={
                "category": "database",
                "capability": "rag",
                "database_id": "sandbox_sales",
                "operation_type": "describe_table",
                "read_only": True,
            },
        ),
        ToolDefinition(
            resource_id="database_demo.retrieve_context",
            name="retrieve_database_context",
            description=str(retrieve_database_context.description),
            source="local",
            raw_tool=retrieve_database_context,
            metadata={
                "category": "database",
                "capability": "rag",
                "database_id": "sandbox_sales",
                "operation_type": "context_retrieval",
                "read_only": True,
            },
        ),
        ToolDefinition(
            resource_id="database_demo.safe_select",
            name="safe_select_database",
            description=str(safe_select_database.description),
            source="local",
            raw_tool=safe_select_database,
            metadata={
                "category": "database",
                "capability": "rag",
                "database_id": "sandbox_sales",
                "operation_type": "safe_select",
                "read_only": True,
            },
        ),
    ]


def permission_service_default() -> PermissionService:
    return permission_service
