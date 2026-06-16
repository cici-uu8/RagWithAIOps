"""Resource catalog for Optimization 2 Stage 3-lite admin grants."""

from __future__ import annotations

from app.config import config
from app.enterprise.admin.models import AdminResourceDescriptor
from app.enterprise.database.mysql import build_mysql_registry_from_config
from app.enterprise.database.permissions import (
    DATABASE_OPERATION_EXECUTE_ACTION,
    DATABASE_OPERATION_RESOURCE_TYPE,
    database_column_resource_id,
    database_operation_resource_id,
    database_table_resource_id,
)
from app.enterprise.database.registry import DatabaseSchemaRegistry, build_default_sandbox_registry
from app.models import DocumentStatus
from app.services.knowledge_metadata_store import KnowledgeMetadataStore, knowledge_metadata_store
from app.tools import get_current_time, list_knowledge_documents, retrieve_knowledge

STAGE3_ACTIONS_BY_RESOURCE_TYPE: dict[str, list[str]] = {
    "knowledge_base": ["read"],
    "document": ["read"],
    "tool": ["use"],
    "database": ["read", "write", "admin"],
    "database_table": ["read"],
    "database_column": ["read"],
    DATABASE_OPERATION_RESOURCE_TYPE: [DATABASE_OPERATION_EXECUTE_ACTION],
}


class ResourceCatalogService:
    def __init__(
        self,
        *,
        metadata_store: KnowledgeMetadataStore | None = None,
        database_registry: DatabaseSchemaRegistry | None = None,
        mysql_database_registries: list[DatabaseSchemaRegistry] | None = None,
    ):
        self.metadata_store = metadata_store or knowledge_metadata_store
        self.database_registry = database_registry or build_default_sandbox_registry()
        if mysql_database_registries is not None:
            self.mysql_database_registries = mysql_database_registries
        elif database_registry is None:
            mysql_registry = build_mysql_registry_from_config(app_config=config)
            self.mysql_database_registries = [mysql_registry] if mysql_registry is not None else []
        else:
            self.mysql_database_registries = []

    async def list_resources(self) -> list[AdminResourceDescriptor]:
        resources: list[AdminResourceDescriptor] = []
        resources.extend(self._knowledge_base_resources())
        resources.extend(self._document_resources())
        resources.extend(self._tool_resources())
        resources.extend(self._database_resources())
        resources.extend(self._database_table_resources())
        resources.extend(self._database_column_resources())
        resources.extend(self._database_operation_resources())
        return sorted(
            resources,
            key=lambda resource: (
                resource.resource_type,
                resource.metadata.get("kb_id", ""),
                resource.name,
                resource.resource_id,
            ),
        )

    async def get_resource(
        self,
        *,
        resource_type: str,
        resource_id: str,
    ) -> AdminResourceDescriptor | None:
        for resource in await self.list_resources():
            if resource.resource_type == resource_type and resource.resource_id == resource_id:
                return resource
        return None

    def _knowledge_base_resources(self) -> list[AdminResourceDescriptor]:
        indexed_documents = [
            document
            for document in self.metadata_store.list_documents()
            if document.status == DocumentStatus.INDEXED and not _is_public_document(document)
        ]
        documents_by_kb: dict[str, list] = {}
        for document in indexed_documents:
            documents_by_kb.setdefault(document.kb_id, []).append(document)

        resources: list[AdminResourceDescriptor] = []
        for kb_id, documents in sorted(documents_by_kb.items()):
            display_name = _knowledge_base_display_name(kb_id, documents)
            resources.append(
                AdminResourceDescriptor(
                    resource_type="knowledge_base",
                    resource_id=kb_id,
                    name=display_name,
                    description=f"Knowledge base {display_name}",
                    actions_supported=STAGE3_ACTIONS_BY_RESOURCE_TYPE["knowledge_base"],
                    metadata={
                        "kb_id": kb_id,
                        "display_name": display_name,
                        "document_count": len(documents),
                    },
                )
            )
        return resources

    def _document_resources(self) -> list[AdminResourceDescriptor]:
        return [
            AdminResourceDescriptor(
                resource_type="document",
                resource_id=document.doc_id,
                name=document.file_name,
                description=f"Indexed document in KB {document.kb_id}",
                actions_supported=STAGE3_ACTIONS_BY_RESOURCE_TYPE["document"],
                metadata={
                    "kb_id": document.kb_id,
                    "file_name": document.file_name,
                    "parser_engine": document.parser_engine.value,
                },
            )
            for document in self.metadata_store.list_documents()
            if document.status == DocumentStatus.INDEXED and not _is_public_document(document)
        ]

    def _tool_resources(self) -> list[AdminResourceDescriptor]:
        canonical_tools = {
            "get_current_time": {
                "tool": get_current_time,
                "description": "Current time tool",
                "category": "time",
            },
            "list_knowledge_documents": {
                "tool": list_knowledge_documents,
                "description": "Knowledge document listing tool",
                "category": "knowledge",
            },
            "retrieve_knowledge": {
                "tool": retrieve_knowledge,
                "description": "Knowledge retrieval tool",
                "category": "knowledge",
            },
        }
        resources = [
            AdminResourceDescriptor(
                resource_type="tool",
                resource_id=resource_id,
                name=resource_id,
                description=str(definition["description"]),
                actions_supported=STAGE3_ACTIONS_BY_RESOURCE_TYPE["tool"],
                metadata={"category": definition["category"]},
            )
            for resource_id, definition in sorted(canonical_tools.items())
        ]
        resources.extend(
            self._database_tool_resources(self.database_registry, "database_demo", "sqlite")
        )
        for registry in self.mysql_database_registries:
            resources.extend(
                self._database_tool_resources(
                    registry,
                    f"database_mysql.{registry.database_id}",
                    "mysql",
                )
            )
        return resources

    def _database_tool_resources(
        self,
        registry: DatabaseSchemaRegistry,
        prefix: str,
        dialect: str,
    ) -> list[AdminResourceDescriptor]:
        database_tools = {
            "database_demo.list_tables": {
                "tool": None,
                "description": "List tables exposed by the read-only database demo sandbox",
                "category": "database",
                "operation_type": "list_tables",
            },
            "database_demo.describe_table": {
                "tool": None,
                "description": "Describe an exposed table in the read-only database demo sandbox",
                "category": "database",
                "operation_type": "describe_table",
            },
            "database_demo.safe_select": {
                "tool": None,
                "description": "Run an allowlisted read-only SELECT in the database demo sandbox",
                "category": "database",
                "operation_type": "safe_select",
            },
        }
        database_tools = {
            f"{prefix}.{operation}": {
                **definition,
                "description": str(definition["description"]).replace(
                    "database demo sandbox", f"{dialect} database {registry.database_id}"
                ),
            }
            for operation, definition in {
                "list_tables": database_tools["database_demo.list_tables"],
                "describe_table": database_tools["database_demo.describe_table"],
                "safe_select": database_tools["database_demo.safe_select"],
            }.items()
        }
        return [
            AdminResourceDescriptor(
                resource_type="tool",
                resource_id=resource_id,
                name=resource_id,
                description=str(definition["description"]),
                actions_supported=STAGE3_ACTIONS_BY_RESOURCE_TYPE["tool"],
                metadata={
                    "category": definition["category"],
                    "database_id": registry.database_id,
                    "dialect": dialect,
                    "operation_type": definition["operation_type"],
                    "read_only": True,
                },
            )
            for resource_id, definition in sorted(database_tools.items())
        ]

    def _database_resources(self) -> list[AdminResourceDescriptor]:
        return [
            AdminResourceDescriptor(
                resource_type="database",
                resource_id=registry.database_id,
                name=registry.database_id,
                description=f"Database {registry.database_id}",
                actions_supported=STAGE3_ACTIONS_BY_RESOURCE_TYPE["database"],
                metadata={
                    "database_id": registry.database_id,
                    "table_count": len(registry.list_tables()),
                },
            )
            for registry in self._database_registries()
        ]

    def _database_table_resources(self) -> list[AdminResourceDescriptor]:
        resources: list[AdminResourceDescriptor] = []
        for registry in self._database_registries():
            for table_name in registry.list_tables():
                table = registry.require_table(table_name)
                resources.append(
                    AdminResourceDescriptor(
                        resource_type="database_table",
                        resource_id=database_table_resource_id(
                            registry.database_id,
                            table.name,
                        ),
                        name=table.name,
                        description=table.description,
                        actions_supported=STAGE3_ACTIONS_BY_RESOURCE_TYPE["database_table"],
                        metadata={
                            "database_id": registry.database_id,
                            "table_name": table.name,
                        },
                    )
                )
        return resources

    def _database_column_resources(self) -> list[AdminResourceDescriptor]:
        resources: list[AdminResourceDescriptor] = []
        for registry in self._database_registries():
            for table_name in registry.list_tables():
                table = registry.require_table(table_name)
                for column in table.visible_columns():
                    resources.append(
                        AdminResourceDescriptor(
                            resource_type="database_column",
                            resource_id=database_column_resource_id(
                                registry.database_id,
                                table.name,
                                column.name,
                            ),
                            name=f"{table.name}.{column.name}",
                            description=column.description,
                            actions_supported=STAGE3_ACTIONS_BY_RESOURCE_TYPE[
                                "database_column"
                            ],
                            metadata={
                                "database_id": registry.database_id,
                                "table_name": table.name,
                                "column_name": column.name,
                                "data_type": column.data_type,
                                "sensitive": column.sensitive,
                                "mask": column.mask,
                            },
                        )
                    )
        return resources

    def _database_operation_resources(self) -> list[AdminResourceDescriptor]:
        operation_definitions = {
            "update": {
                "description": "Execute non-delete write operations such as INSERT or UPDATE",
                "requires_confirmation": False,
            },
            "delete": {
                "description": "Prepare delete-like operations for user confirmation",
                "requires_confirmation": True,
            },
            "ddl": {
                "description": "Execute non-delete schema changes such as CREATE or ALTER",
                "requires_confirmation": False,
            },
        }
        resources: list[AdminResourceDescriptor] = []
        for registry in self._database_registries():
            for operation_type, definition in operation_definitions.items():
                resource_id = database_operation_resource_id(
                    registry.database_id,
                    operation_type,
                )
                resources.append(
                    AdminResourceDescriptor(
                        resource_type=DATABASE_OPERATION_RESOURCE_TYPE,
                        resource_id=resource_id,
                        name=resource_id,
                        description=str(definition["description"]),
                        actions_supported=STAGE3_ACTIONS_BY_RESOURCE_TYPE[
                            DATABASE_OPERATION_RESOURCE_TYPE
                        ],
                        metadata={
                            "database_id": registry.database_id,
                            "operation_type": operation_type,
                            "requires_confirmation": definition["requires_confirmation"],
                        },
                    )
                )
        return resources

    def _database_registries(self) -> list[DatabaseSchemaRegistry]:
        return [self.database_registry, *self.mysql_database_registries]


resource_catalog_service = ResourceCatalogService()


def _is_public_document(document) -> bool:
    visibility = str(document.metadata.get("visibility") or document.metadata.get("access") or "").lower()
    return visibility == "public" or bool(document.metadata.get("public_read"))


def _knowledge_base_display_name(kb_id: str, documents: list) -> str:
    for document in documents:
        value = document.metadata.get("kb_name") or document.metadata.get("knowledge_base_name")
        if value:
            return str(value)
    return kb_id
