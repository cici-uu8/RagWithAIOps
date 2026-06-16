import json
import tempfile
import unittest
from pathlib import Path

from app.config import config
from app.enterprise.documents.service import DocumentAccessService
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService
from app.enterprise.tools.pdf_document_provider import PDF_AGENT_TOOL_IDS
from app.models import ChunkRecord, DocumentRecord, DocumentStatus, ParserEngine, SourceRef
from app.services.knowledge_metadata_store import KnowledgeMetadataStore
from evals.knowledge_base.pdf_agent_tool_smoke import (
    build_pdf_agent_tool_smoke_report,
    write_pdf_agent_tool_smoke_report,
)


class PdfAgentToolSmokeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        original_pdf_agent_tools_enabled = config.pdf_agent_tools_enabled
        config.pdf_agent_tools_enabled = False
        self.addCleanup(
            lambda: setattr(
                config,
                "pdf_agent_tools_enabled",
                original_pdf_agent_tools_enabled,
            )
        )
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
        self.artifact_dir = self.root / "doc-pdf" / "artifacts"
        self.artifact_dir.mkdir(parents=True)
        (self.artifact_dir / "blocks.json").write_text(
            json.dumps(
                {
                    "blocks": [
                        {
                            "id": "b00001",
                            "page": 1,
                            "text": "第 1 页真实 smoke 内容",
                        }
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
                            "table_id": "t00001",
                            "page": 1,
                            "rows": [["字段", "值"], ["部门", "工艺部"]],
                            "markdown": "| 字段 | 值 |\n| --- | --- |\n| 部门 | 工艺部 |",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.document = DocumentRecord(
            doc_id="doc-pdf",
            kb_id="craft_dept",
            file_name="manual.pdf",
            file_ext="pdf",
            original_path=(self.root / "manual.pdf").as_posix(),
            artifact_dir=self.artifact_dir.as_posix(),
            parser_engine=ParserEngine.MINERU,
            status=DocumentStatus.INDEXED,
        )
        self.metadata_store.upsert_document(self.document)

    def _replace_resolvable_chunk(self):
        self.metadata_store.replace_chunks(
            self.document.doc_id,
            [
                ChunkRecord(
                    chunk_id="doc-pdf:c00001",
                    doc_id=self.document.doc_id,
                    kb_id=self.document.kb_id,
                    content="第 1 页真实 smoke 内容",
                    chunk_index=0,
                    start_index=0,
                    end_index=14,
                    page_start=1,
                    page_end=1,
                    source_ref=SourceRef(
                        kb_id=self.document.kb_id,
                        doc_id=self.document.doc_id,
                        chunk_id="doc-pdf:c00001",
                        source_file=self.document.file_name,
                        page_start=1,
                        page_end=1,
                        parser_engine=ParserEngine.MINERU,
                    ),
                )
            ],
        )

    async def test_b4_g3_smoke_report_passes_page_and_table_no_leak(self):
        self._replace_resolvable_chunk()

        report = await build_pdf_agent_tool_smoke_report(
            doc_id=self.document.doc_id,
            valid_page=1,
            invalid_page=99,
            table_id="t00001",
            metadata_store=self.metadata_store,
            permission_service_=self.permission_service,
            access_service=self.access_service,
            audit_service=AuditService(sinks=[InMemoryAuditSink()]),
        )

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["stage"], "B4-G3")
        self.assertFalse(report["expected_default_enabled"])
        self.assertFalse(report["default_enabled"])
        self.assertEqual(report["default_tools_visible"], [])
        self.assertTrue(report["table_available"])
        self.assertEqual(report["selected_table_id"], "t00001")
        self.assertTrue(report["schema_has_no_context_or_owner"])
        self.assertEqual(report["authorized_page_read"]["status"], "success")
        self.assertTrue(report["authorized_page_read"]["content_non_empty"])
        self.assertTrue(report["authorized_page_read"]["source_refs_resolvable"])
        self.assertEqual(report["invalid_page"]["status"], "error")
        self.assertEqual(report["invalid_page"]["error"], "page_out_of_range")
        self.assertFalse(report["invalid_page"]["leak_detected"])
        self.assertEqual(report["invalid_page"]["matched_leak_terms"], [])
        self.assertEqual(report["invalid_page"]["response_keys"], ["error", "status"])
        self.assertEqual(report["denied_page_read"]["status"], "error")
        self.assertEqual(report["denied_page_read"]["error"], "permission_denied")
        self.assertFalse(report["denied_page_read"]["leak_detected"])
        self.assertEqual(report["denied_page_read"]["matched_leak_terms"], [])
        self.assertEqual(report["denied_page_read"]["response_keys"], ["error", "status"])
        self.assertEqual(report["authorized_table_extract"]["status"], "success")
        self.assertTrue(report["authorized_table_extract"]["rows_non_empty"])
        self.assertTrue(report["authorized_table_extract"]["source_refs_resolvable"])
        self.assertEqual(report["invalid_table"]["status"], "error")
        self.assertEqual(report["invalid_table"]["error"], "table_not_found")
        self.assertFalse(report["invalid_table"]["leak_detected"])
        self.assertEqual(report["denied_table_extract"]["status"], "error")
        self.assertEqual(report["denied_table_extract"]["error"], "permission_denied")
        self.assertFalse(report["denied_table_extract"]["leak_detected"])
        self.assertEqual(report["denied_table_extract"]["response_keys"], ["error", "status"])

    async def test_b4_g7_smoke_report_passes_when_default_enabled_is_expected(self):
        self._replace_resolvable_chunk()
        config.pdf_agent_tools_enabled = True

        report = await build_pdf_agent_tool_smoke_report(
            doc_id=self.document.doc_id,
            valid_page=1,
            expect_default_enabled=True,
            invalid_page=99,
            table_id="t00001",
            metadata_store=self.metadata_store,
            permission_service_=self.permission_service,
            access_service=self.access_service,
            audit_service=AuditService(sinks=[InMemoryAuditSink()]),
        )

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["stage"], "B4-G7")
        self.assertTrue(report["expected_default_enabled"])
        self.assertTrue(report["default_enabled"])
        self.assertTrue(set(PDF_AGENT_TOOL_IDS).issubset(report["default_tools_visible"]))
        self.assertEqual(report["authorized_page_read"]["status"], "success")
        self.assertEqual(report["denied_page_read"]["error"], "permission_denied")
        self.assertFalse(report["denied_page_read"]["leak_detected"])
        self.assertEqual(report["authorized_table_extract"]["status"], "success")
        self.assertEqual(report["denied_table_extract"]["error"], "permission_denied")
        self.assertFalse(report["denied_table_extract"]["leak_detected"])

    async def test_b4_g3_smoke_fails_when_source_ref_is_only_fallback(self):
        report = await build_pdf_agent_tool_smoke_report(
            doc_id=self.document.doc_id,
            valid_page=1,
            invalid_page=99,
            table_id="t00001",
            metadata_store=self.metadata_store,
            permission_service_=self.permission_service,
            access_service=self.access_service,
            audit_service=AuditService(sinks=[InMemoryAuditSink()]),
        )

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["authorized_page_read"]["status"], "success")
        self.assertTrue(report["authorized_page_read"]["content_non_empty"])
        self.assertFalse(report["authorized_page_read"]["source_refs_resolvable"])
        self.assertEqual(
            report["authorized_page_read"]["source_ref_missing_fields"][0]["missing"],
            ["chunk_id", "parser_engine"],
        )
        self.assertFalse(report["denied_page_read"]["leak_detected"])

    async def test_b4_g3_smoke_marks_authorized_table_not_applicable_when_no_tables(self):
        self._replace_resolvable_chunk()
        (self.artifact_dir / "tables.json").write_text(
            json.dumps({"tables": []}, ensure_ascii=False),
            encoding="utf-8",
        )

        report = await build_pdf_agent_tool_smoke_report(
            doc_id=self.document.doc_id,
            valid_page=1,
            invalid_page=99,
            metadata_store=self.metadata_store,
            permission_service_=self.permission_service,
            access_service=self.access_service,
            audit_service=AuditService(sinks=[InMemoryAuditSink()]),
        )

        self.assertEqual(report["status"], "passed")
        self.assertFalse(report["table_available"])
        self.assertEqual(report["authorized_table_extract"]["status"], "not_applicable")
        self.assertEqual(report["invalid_table"]["error"], "table_not_found")
        self.assertEqual(report["denied_table_extract"]["error"], "permission_denied")
        self.assertFalse(report["denied_table_extract"]["leak_detected"])

    async def test_write_smoke_report_writes_json_and_markdown(self):
        self._replace_resolvable_chunk()
        report = await build_pdf_agent_tool_smoke_report(
            doc_id=self.document.doc_id,
            valid_page=1,
            invalid_page=99,
            table_id="t00001",
            metadata_store=self.metadata_store,
            permission_service_=self.permission_service,
            access_service=self.access_service,
            audit_service=AuditService(sinks=[InMemoryAuditSink()]),
        )

        write_pdf_agent_tool_smoke_report(
            report,
            output_json=self.root / "report.json",
            output_md=self.root / "report.md",
        )

        self.assertTrue((self.root / "report.json").exists())
        self.assertTrue((self.root / "report.md").exists())
        self.assertIn("B4 PDF Agent Tool Smoke Report", (self.root / "report.md").read_text())


if __name__ == "__main__":
    unittest.main()
