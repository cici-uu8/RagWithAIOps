import json
import tempfile
import unittest
from pathlib import Path

from app.enterprise.context import RequestContext
from app.enterprise.documents.service import DocumentAccessService
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService
from app.enterprise.tools.facade import ToolExecutionFacade
from app.enterprise.tools.gateway import ToolGateway
from app.enterprise.tools.local_provider import build_local_agent_tool_execution_facade
from app.enterprise.tools.pdf_document_provider import (
    EXTRACT_DOCUMENT_TABLE_TOOL_ID,
    PDF_AGENT_TOOL_IDS,
    READ_DOCUMENT_PAGE_TOOL_ID,
    PdfDocumentToolProvider,
)
from app.models import ChunkRecord, DocumentRecord, DocumentStatus, ParserEngine, SourceRef
from app.services.knowledge_metadata_store import KnowledgeMetadataStore


class PdfDocumentToolProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = Path(self.tmpdir.name)
        self.metadata_store = KnowledgeMetadataStore(self.root / "metadata.json")
        self.permission_service = PermissionService(
            repository=InMemoryGovernanceRepository(),
            audit_service=AuditService(sinks=[InMemoryAuditSink()]),
        )
        self.access_service = DocumentAccessService(
            metadata_store=self.metadata_store,
            permission_service=self.permission_service,
        )
        self.artifact_dir = self.root / "doc-secret" / "artifacts"
        self.artifact_dir.mkdir(parents=True)
        self._write_artifacts()
        self.document = DocumentRecord(
            doc_id="doc-secret",
            kb_id="craft_dept",
            file_name="秘密工艺手册.pdf",
            file_ext="pdf",
            original_path=(self.root / "秘密工艺手册.pdf").as_posix(),
            artifact_dir=self.artifact_dir.as_posix(),
            parser_engine=ParserEngine.MINERU,
            status=DocumentStatus.INDEXED,
        )
        self.metadata_store.upsert_document(self.document)
        self.metadata_store.replace_chunks(
            self.document.doc_id,
            [
                ChunkRecord(
                    chunk_id="doc-secret:c00001",
                    doc_id=self.document.doc_id,
                    kb_id=self.document.kb_id,
                    content="第 1 页泄露正文",
                    chunk_index=0,
                    start_index=0,
                    end_index=8,
                    page_start=1,
                    page_end=1,
                    source_ref=SourceRef(
                        kb_id=self.document.kb_id,
                        doc_id=self.document.doc_id,
                        chunk_id="doc-secret:c00001",
                        source_file=self.document.file_name,
                        page_start=1,
                        page_end=1,
                        parser_engine=ParserEngine.MINERU,
                    ),
                )
            ],
        )

    def _write_artifacts(self) -> None:
        (self.artifact_dir / "blocks.json").write_text(
            json.dumps(
                {
                    "blocks": [
                        {
                            "id": "b00001",
                            "page": 1,
                            "text": "第 1 页泄露正文",
                        },
                        {
                            "id": "b00002",
                            "page": 2,
                            "text": "第 2 页公开正文",
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (self.artifact_dir / "tables.json").write_text(
            json.dumps(
                {
                    "tables": [
                        {
                            "table_id": "t-secret",
                            "page_start": 1,
                            "page_end": 1,
                            "rows": [["设备", "处理"], ["泵", "停机"]],
                            "markdown": "| 设备 | 处理 |\n| --- | --- |\n| 泵 | 停机 |",
                            "quality_flags": ["checked"],
                        },
                        {
                            "table_id": "t-page-2",
                            "page": 2,
                            "rows": [["项", "值"]],
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def admin_context(self) -> RequestContext:
        return RequestContext(
            request_id="request-admin",
            trace_id="trace-admin",
            user_id="admin",
            username="admin",
            department_id="ops",
            department_name="Ops",
            roles=["admin"],
        )

    def denied_context(self) -> RequestContext:
        return RequestContext(
            request_id="request-denied",
            trace_id="trace-denied",
            user_id="user-denied",
            username="user-denied",
            department_id="other",
            department_name="Other",
            roles=["user"],
        )

    def provider(self, *, enabled: bool = True) -> PdfDocumentToolProvider:
        return PdfDocumentToolProvider(
            metadata_store=self.metadata_store,
            access_service=self.access_service,
            enabled=enabled,
        )

    def facade(self, provider: PdfDocumentToolProvider) -> ToolExecutionFacade:
        gateway = ToolGateway(
            providers=[provider],
            permission_service=self.permission_service,
            audit_service=AuditService(sinks=[InMemoryAuditSink()]),
            default_allowed_tool_ids=set(PDF_AGENT_TOOL_IDS),
        )
        return ToolExecutionFacade(gateway=gateway)

    async def test_pdf_tools_are_default_off(self):
        self.assertEqual(await self.provider(enabled=False).list_tools(), [])

    async def test_tool_schema_has_no_context_owner_or_artifact_path(self):
        tools = {tool.resource_id: tool for tool in await self.provider(enabled=True).list_tools()}

        read_schema = tools[READ_DOCUMENT_PAGE_TOOL_ID].input_schema
        table_schema = tools[EXTRACT_DOCUMENT_TABLE_TOOL_ID].input_schema
        schema_text = json.dumps([read_schema, table_schema], ensure_ascii=False)

        self.assertIn("doc_id", read_schema["properties"])
        self.assertIn("page", read_schema["properties"])
        self.assertIn("table_id", table_schema["properties"])
        self.assertNotIn("RequestContext", schema_text)
        self.assertNotIn("owner_id", schema_text)
        self.assertNotIn("artifact", schema_text)

    async def test_bindable_tools_expose_business_parameters_not_generic_arguments(self):
        facade = self.facade(self.provider(enabled=True))

        bindable = await facade.get_bindable_tools(self.admin_context())
        args_by_name = {tool.name: tool.args for tool in bindable}

        self.assertEqual(
            set(args_by_name["read_document_page"]),
            {"doc_id", "page"},
        )
        self.assertEqual(
            set(args_by_name["extract_document_table"]),
            {"doc_id", "table_id", "page"},
        )
        self.assertNotIn("arguments", args_by_name["read_document_page"])

    async def test_read_page_success_uses_gateway_context(self):
        facade = self.facade(self.provider(enabled=True))

        result = await facade.execute(
            self.admin_context(),
            READ_DOCUMENT_PAGE_TOOL_ID,
            {"doc_id": self.document.doc_id, "page": 1},
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["content"], "第 1 页泄露正文")
        self.assertEqual(result["source_refs"][0]["chunk_id"], "doc-secret:c00001")

    async def test_read_page_permission_denied_no_content_leak(self):
        facade = self.facade(self.provider(enabled=True))

        result = await facade.execute(
            self.denied_context(),
            READ_DOCUMENT_PAGE_TOOL_ID,
            {"doc_id": self.document.doc_id, "page": 1},
        )

        self.assertEqual(result, {"status": "error", "error": "permission_denied"})
        result_text = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("秘密工艺手册", result_text)
        self.assertNotIn("泄露正文", result_text)
        self.assertNotIn(str(self.artifact_dir), result_text)

    async def test_read_page_out_of_range(self):
        facade = self.facade(self.provider(enabled=True))

        result = await facade.execute(
            self.admin_context(),
            READ_DOCUMENT_PAGE_TOOL_ID,
            {"doc_id": self.document.doc_id, "page": 99},
        )

        self.assertEqual(result, {"status": "error", "error": "page_out_of_range"})

    async def test_extract_table_by_id_and_page(self):
        facade = self.facade(self.provider(enabled=True))

        by_id = await facade.execute(
            self.admin_context(),
            EXTRACT_DOCUMENT_TABLE_TOOL_ID,
            {"doc_id": self.document.doc_id, "table_id": "t-secret"},
        )
        by_page = await facade.execute(
            self.admin_context(),
            EXTRACT_DOCUMENT_TABLE_TOOL_ID,
            {"doc_id": self.document.doc_id, "page": 2},
        )

        self.assertEqual(by_id["status"], "success")
        self.assertEqual(by_id["rows"][1], ["泵", "停机"])
        self.assertEqual(by_id["quality_flags"], ["checked"])
        self.assertEqual(by_page["table_id"], "t-page-2")

    async def test_extract_table_permission_denied_no_table_leak(self):
        facade = self.facade(self.provider(enabled=True))

        result = await facade.execute(
            self.denied_context(),
            EXTRACT_DOCUMENT_TABLE_TOOL_ID,
            {"doc_id": self.document.doc_id, "table_id": "t-secret"},
        )

        self.assertEqual(result, {"status": "error", "error": "permission_denied"})
        result_text = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("秘密工艺手册", result_text)
        self.assertNotIn("泵", result_text)
        self.assertNotIn("停机", result_text)
        self.assertNotIn(str(self.artifact_dir), result_text)

    async def test_local_agent_gateway_lists_pdf_tools_only_when_config_enabled(self):
        from app.config import config

        original = config.pdf_agent_tools_enabled
        try:
            config.pdf_agent_tools_enabled = True
            facade = build_local_agent_tool_execution_facade(
                permission_service=self.permission_service,
                audit_service=AuditService(sinks=[InMemoryAuditSink()]),
            )

            visible = await facade.list_visible_tools(self.admin_context(), capability="rag")

            self.assertIn(
                READ_DOCUMENT_PAGE_TOOL_ID,
                [tool.resource_id for tool in visible],
            )
            self.assertIn(
                EXTRACT_DOCUMENT_TABLE_TOOL_ID,
                [tool.resource_id for tool in visible],
            )
        finally:
            config.pdf_agent_tools_enabled = original


if __name__ == "__main__":
    unittest.main()
