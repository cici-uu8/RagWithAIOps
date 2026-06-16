import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.services.document_ingestion_service as ingestion_module
import app.services.mineru_parser_adapter as adapter_module
from app.models import DocumentRecord, DocumentStatus, ParserEngine
from app.services.artifact_manifest_service import artifact_manifest_service
from app.services.knowledge_metadata_store import KnowledgeMetadataStore


class MinerUParserAdapterTests(unittest.TestCase):
    def _build_document_record(self, root: Path) -> DocumentRecord:
        source_path = root / "uploads" / "documents" / "default" / "doc_pdf" / "original" / "sample.pdf"
        artifact_dir = root / "uploads" / "documents" / "default" / "doc_pdf" / "artifacts"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(b"%PDF-1.4 mock")
        return DocumentRecord(
            doc_id="doc_pdf",
            kb_id="default",
            file_name="sample.pdf",
            file_ext="pdf",
            original_path=source_path.as_posix(),
            artifact_dir=artifact_dir.as_posix(),
            parser_engine=ParserEngine.MINERU,
            status=DocumentStatus.PARSE_PENDING,
        )

    def test_parse_document_runs_cli_and_postprocess_then_marks_index_pending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            temp_store = KnowledgeMetadataStore(root / "uploads" / "_metadata" / "knowledge_metadata_store.json")
            adapter = adapter_module.MinerUParserAdapter()
            record = self._build_document_record(root)

            def fake_run_cli(source_path: Path, output_parent: Path) -> Path:
                raw_dir = output_parent / source_path.stem / "auto"
                raw_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / f"{source_path.stem}.md").write_text("# raw", encoding="utf-8")
                (raw_dir / f"{source_path.stem}_content_list.json").write_text("[]", encoding="utf-8")
                images_dir = raw_dir / "images"
                images_dir.mkdir(exist_ok=True)
                (images_dir / "page1.png").write_bytes(b"png")
                return raw_dir

            def fake_postprocess(source_dir: Path, artifact_dir: Path, source_path: Path) -> dict:
                (artifact_dir / "cleaned.md").write_text("# cleaned", encoding="utf-8")
                (artifact_dir / "blocks.json").write_text("[]", encoding="utf-8")
                (artifact_dir / "chunks.json").write_text("[]", encoding="utf-8")
                (artifact_dir / "tables.json").write_text("[]", encoding="utf-8")
                (artifact_dir / "quality_report.json").write_text('{"ok": true}', encoding="utf-8")
                return {"ok": True, "source_dir": source_dir.as_posix(), "source_file": source_path.as_posix()}

            with patch.object(adapter_module, "knowledge_metadata_store", temp_store):
                temp_store.upsert_document(record)
                with patch.object(adapter, "_run_mineru_cli", fake_run_cli):
                    with patch.object(adapter, "_run_postprocess", fake_postprocess):
                        result = adapter.parse_document(record)

            self.assertEqual(result.status, DocumentStatus.INDEX_PENDING)
            self.assertEqual(result.parser_version, "mineru_cli")
            self.assertIn("raw_output_dir", result.metadata)
            self.assertTrue(Path(result.metadata["raw_output_dir"]).exists())
            self.assertTrue(Path(result.metadata["markdown_path"]).exists())
            self.assertTrue(Path(record.artifact_dir, "cleaned.md").exists())
            manifest = artifact_manifest_service.load_manifest(record.artifact_dir)
            self.assertEqual(manifest.schema_version, "artifact_manifest_v1")
            self.assertEqual(manifest.parser_engine, ParserEngine.MINERU)
            self.assertEqual(manifest.required_files["cleaned_md"], "cleaned.md")
            stored = temp_store.get_document(record.doc_id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.status, DocumentStatus.INDEX_PENDING)
            self.assertEqual(stored.status_source, "MinerUParserAdapter.parse_document")
            self.assertIn("artifact_manifest_path", stored.status_evidence)
            self.assertIsNotNone(stored.status_confirmed_at)
            self.assertIn("artifact_manifest_path", stored.metadata)

    def test_parse_document_marks_parse_failed_on_adapter_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            temp_store = KnowledgeMetadataStore(root / "uploads" / "_metadata" / "knowledge_metadata_store.json")
            adapter = adapter_module.MinerUParserAdapter()
            record = self._build_document_record(root)

            with patch.object(adapter_module, "knowledge_metadata_store", temp_store):
                temp_store.upsert_document(record)
                with patch.object(adapter, "_run_mineru_cli", side_effect=RuntimeError("boom")):
                    with self.assertRaises(RuntimeError):
                        adapter.parse_document(record)

            stored = temp_store.get_document(record.doc_id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.status, DocumentStatus.PARSE_FAILED)
            self.assertEqual(stored.status_source, "MinerUParserAdapter.parse_document")
            self.assertEqual(stored.status_evidence["error_type"], "RuntimeError")
            self.assertIn("boom", stored.error_message)

    def test_run_mineru_cli_accepts_method_named_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "sample.pdf"
            output_parent = root / "raw"
            source_path.write_bytes(b"%PDF-1.4 mock")
            raw_dir = output_parent / "sample" / "txt"
            raw_dir.mkdir(parents=True)
            (raw_dir / "sample_content_list.json").write_text("[]", encoding="utf-8")
            adapter = adapter_module.MinerUParserAdapter()
            adapter.method = "txt"

            class FakeCompletedProcess:
                returncode = 0
                stdout = ""
                stderr = ""

            with patch.object(adapter_module.subprocess, "run", return_value=FakeCompletedProcess()):
                result = adapter._run_mineru_cli(source_path, output_parent)

            self.assertEqual(result, raw_dir)

    def test_parse_document_fails_when_required_artifact_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            temp_store = KnowledgeMetadataStore(root / "uploads" / "_metadata" / "knowledge_metadata_store.json")
            adapter = adapter_module.MinerUParserAdapter()
            record = self._build_document_record(root)

            def fake_run_cli(source_path: Path, output_parent: Path) -> Path:
                raw_dir = output_parent / source_path.stem / "auto"
                raw_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / f"{source_path.stem}.md").write_text("# raw", encoding="utf-8")
                (raw_dir / f"{source_path.stem}_content_list.json").write_text("[]", encoding="utf-8")
                return raw_dir

            def fake_postprocess(source_dir: Path, artifact_dir: Path, source_path: Path) -> dict:
                (artifact_dir / "cleaned.md").write_text("# cleaned", encoding="utf-8")
                (artifact_dir / "blocks.json").write_text("[]", encoding="utf-8")
                (artifact_dir / "chunks.json").write_text("[]", encoding="utf-8")
                (artifact_dir / "quality_report.json").write_text('{"ok": true}', encoding="utf-8")
                # tables.json intentionally missing
                return {"ok": True}

            with patch.object(adapter_module, "knowledge_metadata_store", temp_store):
                temp_store.upsert_document(record)
                with patch.object(adapter, "_run_mineru_cli", fake_run_cli):
                    with patch.object(adapter, "_run_postprocess", fake_postprocess):
                        with self.assertRaises(FileNotFoundError):
                            adapter.parse_document(record)

            stored = temp_store.get_document(record.doc_id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.status, DocumentStatus.PARSE_FAILED)
            self.assertEqual(stored.status_source, "MinerUParserAdapter.parse_document")
            self.assertEqual(stored.status_evidence["error_type"], "FileNotFoundError")
            self.assertIn("tables.json", stored.error_message)

    def test_document_ingestion_service_processes_parse_pending_mineru_document(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            temp_store = KnowledgeMetadataStore(root / "uploads" / "_metadata" / "knowledge_metadata_store.json")
            service = ingestion_module.DocumentIngestionService(upload_root=root / "uploads")
            record = self._build_document_record(root)

            with patch.object(ingestion_module, "knowledge_metadata_store", temp_store):
                temp_store.upsert_document(record)
                patched_result = record.model_copy(update={"status": DocumentStatus.INDEX_PENDING})
                with patch.object(ingestion_module.mineru_parser_adapter, "parse_document", return_value=patched_result) as parse_mock:
                    result = service.process_deferred_document(record.doc_id)

            self.assertEqual(result.status, DocumentStatus.INDEX_PENDING)
            parse_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
