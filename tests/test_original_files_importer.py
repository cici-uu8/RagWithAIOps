import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class OriginalFilesImporterTests(unittest.TestCase):
    def test_dry_run_does_not_call_ingestion_service(self):
        from scripts.knowledge_assets.import_original_files import import_reviewed_files

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_root = root / "原始文件"
            source_root.mkdir()
            file_path = source_root / "runbook.md"
            file_path.write_text("runbook", encoding="utf-8")
            review_path = root / "review.tsv"
            review_path.write_text(
                "asset_id\trelative_path\tkb_id\treview_status\timport_enabled\tnotes\n"
                "orig_a4ed67fc67de\trunbook.md\tprocess_digital_dept\tapproved\ttrue\tseed\n",
                encoding="utf-8",
            )

            with patch("scripts.knowledge_assets.import_original_files.DocumentIngestionService") as svc:
                report = import_reviewed_files(
                    source_root=source_root,
                    review_path=review_path,
                    apply=False,
                    limit=10,
                )

            self.assertEqual(report["mode"], "dry_run")
            self.assertEqual(report["summary"]["eligible"], 1)
            self.assertEqual(report["summary"]["imported"], 0)
            svc.assert_not_called()

    def test_apply_imports_only_approved_enabled_rows_with_limit(self):
        from scripts.knowledge_assets.import_original_files import import_reviewed_files

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_root = root / "原始文件"
            source_root.mkdir()
            (source_root / "a.md").write_text("a", encoding="utf-8")
            (source_root / "b.md").write_text("b", encoding="utf-8")
            (source_root / "c.md").write_text("c", encoding="utf-8")
            review_path = root / "review.tsv"
            review_path.write_text(
                "asset_id\trelative_path\tkb_id\treview_status\timport_enabled\tnotes\n"
                "orig_a\ta.md\tprocess_digital_dept\tapproved\ttrue\tseed\n"
                "orig_b\tb.md\tcraft_dept\tapproved\ttrue\tseed\n"
                "orig_c\tc.md\tcraft_dept\tpending\ttrue\tseed\n",
                encoding="utf-8",
            )

            class FakeDocument:
                def __init__(self, doc_id, kb_id, status):
                    self.doc_id = doc_id
                    self.kb_id = kb_id
                    self.status = status
                    self.status_evidence = {"processing_job_id": f"job-{doc_id}"}

            class FakeIngestionService:
                calls = []

                def ingest_upload(self, filename, content, kb_id):
                    self.calls.append((filename, content, kb_id))
                    return FakeDocument(f"doc-{filename}", kb_id, "indexed")

            with patch(
                "scripts.knowledge_assets.import_original_files.DocumentIngestionService",
                return_value=FakeIngestionService(),
            ):
                report = import_reviewed_files(
                    source_root=source_root,
                    review_path=review_path,
                    apply=True,
                    limit=1,
                )

            self.assertEqual(report["mode"], "apply")
            self.assertEqual(report["summary"]["eligible"], 2)
            self.assertEqual(report["summary"]["imported"], 1)
            self.assertEqual(report["summary"]["skipped_pending_review"], 1)
            self.assertEqual(report["imported"][0]["doc_id"], "doc-a.md")
            self.assertEqual(report["imported"][0]["job_id"], "job-doc-a.md")

    def test_freeze_import_state_records_doc_source_ref_and_pdf_job_id(self):
        from app.models import DocumentRecord, DocumentStatus, ParserEngine
        from app.services.knowledge_metadata_store import KnowledgeMetadataStore
        from scripts.knowledge_assets.import_original_files import freeze_import_state

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = KnowledgeMetadataStore(root / "metadata.json")
            store.upsert_document(
                DocumentRecord(
                    doc_id="doc-pdf",
                    kb_id="craft_dept",
                    file_name="现场设备工艺版.pdf",
                    file_ext="pdf",
                    original_path=(root / "现场设备工艺版.pdf").as_posix(),
                    artifact_dir=(root / "artifacts").as_posix(),
                    parser_engine=ParserEngine.MINERU,
                    status=DocumentStatus.PARSE_PENDING,
                    status_evidence={"processing_job_id": "rq-job-1"},
                )
            )
            output_path = root / "current_import_state.json"

            state = freeze_import_state(
                metadata_store=store,
                kb_ids=["craft_dept"],
                output_path=output_path,
            )

            self.assertEqual(state["summary"]["total_documents"], 1)
            self.assertEqual(state["summary"]["status_counts"], {"parse_pending": 1})
            self.assertEqual(state["documents"][0]["doc_id"], "doc-pdf")
            self.assertEqual(state["documents"][0]["kb_id"], "craft_dept")
            self.assertEqual(state["documents"][0]["source_ref"]["source_file"], "现场设备工艺版.pdf")
            self.assertEqual(state["documents"][0]["job_id"], "rq-job-1")
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()
