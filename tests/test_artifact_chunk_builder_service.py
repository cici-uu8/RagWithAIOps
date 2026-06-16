import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import app.services.document_ingestion_service as ingestion_module
import app.services.vector_index_service as vector_index_module
from app.models import DocumentRecord, DocumentStatus, ParserEngine
from app.services.artifact_manifest_service import artifact_manifest_service
from app.services.knowledge_metadata_store import KnowledgeMetadataStore


class FakeVectorStoreManager:
    def __init__(self):
        self.added_documents = []
        self.fail_on_add = False

    def delete_by_doc_id(self, doc_id: str) -> int:
        return 0

    def delete_by_source(self, file_path: str) -> int:
        return 0

    def add_documents(self, documents):
        if self.fail_on_add:
            raise RuntimeError("vector boom")
        self.added_documents.extend(documents)
        return [f"fake-{index}" for index, _ in enumerate(documents)]


class ArtifactChunkBuilderServiceTests(unittest.TestCase):
    def _write_json(self, path: Path, payload):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _build_record_with_artifacts(self, root: Path) -> DocumentRecord:
        original_path = root / "uploads" / "documents" / "default" / "doc_pdf" / "original" / "manual.pdf"
        artifact_dir = root / "uploads" / "documents" / "default" / "doc_pdf" / "artifacts"
        original_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        original_path.write_bytes(b"%PDF-1.4 mock")
        (artifact_dir / "cleaned.md").write_text("# cleaned fallback only", encoding="utf-8")
        self._write_json(artifact_dir / "blocks.json", [])
        return DocumentRecord(
            doc_id="doc_pdf",
            kb_id="default",
            file_name="manual.pdf",
            file_ext="pdf",
            original_path=original_path.as_posix(),
            artifact_dir=artifact_dir.as_posix(),
            parser_engine=ParserEngine.MINERU,
            status=DocumentStatus.INDEX_PENDING,
            parser_version="mineru-3.1.11",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    def _write_manifest(self, record: DocumentRecord):
        artifact_manifest_service.write_manifest(record)

    def test_prepare_artifacts_for_index_normalizes_chunks_and_tables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            temp_store = KnowledgeMetadataStore(root / "uploads" / "_metadata" / "knowledge_metadata_store.json")
            record = self._build_record_with_artifacts(root)
            artifact_dir = Path(record.artifact_dir)
            self._write_json(
                artifact_dir / "chunks.json",
                [
                    {
                        "id": "c00001",
                        "doc_type": "manual",
                        "text": "第一段正文",
                        "pages": [2, 3],
                        "heading_path": ["第一章", "概述"],
                        "block_ids": ["b00001", "b00002"],
                        "block_types": ["heading", "text"],
                        "char_count": 5,
                    }
                ],
            )
            self._write_json(
                artifact_dir / "tables.json",
                [
                    {
                        "schema_version": "table_v1",
                        "table_id": "t00001",
                        "page": 4,
                        "page_start": 4,
                        "page_end": 4,
                        "heading_path": ["第一章", "参数"],
                        "content_type": "manual_table",
                        "classification": "parameter_table",
                        "caption": ["表1 参数"],
                        "rows": [["名称", "值"], ["A", "1"]],
                        "markdown": "| 名称 | 值 |\n| --- | --- |\n| A | 1 |",
                        "raw_html": "<table></table>",
                        "quality_flags": ["no_caption"],
                    }
                ],
            )
            self._write_json(
                artifact_dir / "quality_report.json",
                {
                    "doc_type": "manual",
                    "block_count": 2,
                    "chunk_count": 1,
                    "table_count": 1,
                    "fatal_errors": [],
                    "warnings": [],
                },
            )
            self._write_manifest(record)

            service = ingestion_module.DocumentIngestionService(upload_root=root / "uploads")
            with patch.object(ingestion_module, "knowledge_metadata_store", temp_store):
                temp_store.upsert_document(record)
                prepared = service.prepare_artifacts_for_index(record.doc_id)

            self.assertEqual(len(prepared.chunk_records), 2)
            self.assertEqual(len(prepared.documents), 2)

            text_chunk = prepared.chunk_records[0]
            self.assertEqual(text_chunk.chunk_id, "doc_pdf:c00001")
            self.assertEqual(text_chunk.content, "第一段正文")
            self.assertEqual(text_chunk.page_start, 2)
            self.assertEqual(text_chunk.page_end, 3)
            self.assertEqual(text_chunk.content_type, "text")
            self.assertEqual(text_chunk.source_ref.doc_id, "doc_pdf")
            self.assertEqual(text_chunk.source_ref.source_file, "manual.pdf")
            self.assertEqual(text_chunk.metadata["_source"], record.original_path)
            self.assertEqual(text_chunk.metadata["_file_name"], "manual.pdf")
            self.assertEqual(text_chunk.metadata["_extension"], ".pdf")
            self.assertEqual(text_chunk.metadata["source_ref"]["chunk_id"], "doc_pdf:c00001")

            table_chunk = prepared.chunk_records[1]
            self.assertEqual(table_chunk.chunk_id, "doc_pdf:table:t00001")
            self.assertEqual(table_chunk.content_type, "manual_table")
            self.assertEqual(table_chunk.page_start, 4)
            self.assertEqual(table_chunk.metadata["structured_payload"]["rows"], [["名称", "值"], ["A", "1"]])
            self.assertEqual(prepared.documents[1].metadata["chunk_id"], table_chunk.chunk_id)

    def test_prepare_artifacts_for_index_marks_index_failed_and_reraises_on_bad_chunk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            temp_store = KnowledgeMetadataStore(root / "uploads" / "_metadata" / "knowledge_metadata_store.json")
            record = self._build_record_with_artifacts(root)
            artifact_dir = Path(record.artifact_dir)
            self._write_json(artifact_dir / "chunks.json", [{"id": "c00001", "pages": [1]}])
            self._write_json(artifact_dir / "tables.json", [])
            self._write_json(artifact_dir / "quality_report.json", {"fatal_errors": [], "warnings": []})
            self._write_manifest(record)

            service = ingestion_module.DocumentIngestionService(upload_root=root / "uploads")
            with patch.object(ingestion_module, "knowledge_metadata_store", temp_store):
                temp_store.upsert_document(record)
                with self.assertRaises(ValueError):
                    service.prepare_artifacts_for_index(record.doc_id)

            stored = temp_store.get_document(record.doc_id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.status, DocumentStatus.INDEX_FAILED)
            self.assertEqual(stored.status_source, "DocumentIngestionService.prepare_artifacts_for_index")
            self.assertEqual(stored.status_evidence["error_type"], "ValueError")
            self.assertIn("content", stored.error_message)

    def test_prepare_artifacts_for_index_rejects_quality_report_fatal_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            temp_store = KnowledgeMetadataStore(root / "uploads" / "_metadata" / "knowledge_metadata_store.json")
            record = self._build_record_with_artifacts(root)
            artifact_dir = Path(record.artifact_dir)
            self._write_json(
                artifact_dir / "chunks.json",
                [{"id": "c00001", "text": "正文", "pages": [1], "heading_path": []}],
            )
            self._write_json(artifact_dir / "tables.json", [])
            self._write_json(
                artifact_dir / "quality_report.json",
                {"fatal_errors": ["ocr_failed"], "warnings": []},
            )
            self._write_manifest(record)

            service = ingestion_module.DocumentIngestionService(upload_root=root / "uploads")
            with patch.object(ingestion_module, "knowledge_metadata_store", temp_store):
                temp_store.upsert_document(record)
                with self.assertRaises(ValueError):
                    service.prepare_artifacts_for_index(record.doc_id)

            stored = temp_store.get_document(record.doc_id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.status, DocumentStatus.INDEX_FAILED)
            self.assertEqual(stored.status_source, "DocumentIngestionService.prepare_artifacts_for_index")
            self.assertEqual(stored.status_evidence["error_type"], "ValueError")
            self.assertIn("fatal_errors", stored.error_message)

    def test_vector_index_service_indexes_prepared_mineru_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            temp_store = KnowledgeMetadataStore(root / "uploads" / "_metadata" / "knowledge_metadata_store.json")
            fake_vector_store = FakeVectorStoreManager()
            record = self._build_record_with_artifacts(root)
            artifact_dir = Path(record.artifact_dir)
            self._write_json(
                artifact_dir / "chunks.json",
                [{"id": "c00001", "text": "第一段正文", "pages": [2], "heading_path": ["概述"]}],
            )
            self._write_json(
                artifact_dir / "tables.json",
                [
                    {
                        "schema_version": "table_v1",
                        "table_id": "t00001",
                        "page": 3,
                        "page_start": 3,
                        "page_end": 3,
                        "heading_path": ["参数"],
                        "content_type": "manual_table",
                        "caption": [],
                        "rows": [["名称", "值"]],
                        "markdown": "| 名称 | 值 |\n| --- | --- |",
                        "quality_flags": [],
                    }
                ],
            )
            self._write_json(
                artifact_dir / "quality_report.json",
                {"fatal_errors": [], "warnings": [], "chunk_count": 1, "table_count": 1},
            )
            self._write_manifest(record)

            with patch.object(vector_index_module, "knowledge_metadata_store", temp_store):
                with patch.object(vector_index_module, "vector_store_manager", fake_vector_store):
                    with patch.object(ingestion_module, "knowledge_metadata_store", temp_store):
                        temp_store.upsert_document(record)
                        service = vector_index_module.VectorIndexService()
                        service.index_document_record(record)

            stored = temp_store.get_document(record.doc_id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.status, DocumentStatus.INDEXED)
            self.assertEqual(stored.status_source, "VectorIndexService._index_mineru_document_record")
            self.assertEqual(stored.status_evidence["vector_document_count"], 2)
            chunks = temp_store.list_chunks_by_doc_id(record.doc_id)
            self.assertEqual(len(chunks), 2)
            self.assertEqual(len(fake_vector_store.added_documents), 2)
            self.assertEqual(fake_vector_store.added_documents[0].metadata["chunk_id"], "doc_pdf:c00001")
            self.assertEqual(fake_vector_store.added_documents[1].metadata["chunk_id"], "doc_pdf:table:t00001")
            self.assertEqual(chunks[0].metadata["source_ref"]["doc_id"], "doc_pdf")
            self.assertEqual(chunks[1].metadata["content_type"], "manual_table")

    def test_vector_index_service_marks_index_failed_when_mineru_vector_write_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            temp_store = KnowledgeMetadataStore(root / "uploads" / "_metadata" / "knowledge_metadata_store.json")
            fake_vector_store = FakeVectorStoreManager()
            fake_vector_store.fail_on_add = True
            record = self._build_record_with_artifacts(root)
            artifact_dir = Path(record.artifact_dir)
            self._write_json(
                artifact_dir / "chunks.json",
                [{"id": "c00001", "text": "第一段正文", "pages": [2], "heading_path": []}],
            )
            self._write_json(artifact_dir / "tables.json", [])
            self._write_json(artifact_dir / "quality_report.json", {"fatal_errors": [], "warnings": []})
            self._write_manifest(record)

            with patch.object(vector_index_module, "knowledge_metadata_store", temp_store):
                with patch.object(vector_index_module, "vector_store_manager", fake_vector_store):
                    with patch.object(ingestion_module, "knowledge_metadata_store", temp_store):
                        temp_store.upsert_document(record)
                        service = vector_index_module.VectorIndexService()
                        with self.assertRaises(RuntimeError):
                            service.index_document_record(record)

            stored = temp_store.get_document(record.doc_id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.status, DocumentStatus.INDEX_FAILED)
            self.assertEqual(stored.status_source, "VectorIndexService.index_document_record")
            self.assertEqual(stored.status_evidence["error_type"], "RuntimeError")
            self.assertIn("vector boom", stored.error_message)


if __name__ == "__main__":
    unittest.main()
