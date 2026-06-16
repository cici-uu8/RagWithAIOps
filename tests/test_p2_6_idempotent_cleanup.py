import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from langchain_core.documents import Document

import app.services.document_ingestion_service as ingestion_module
import app.services.vector_index_service as vector_index_module
from app.models import DocumentRecord, DocumentStatus, ParserEngine
from app.services.artifact_manifest_service import artifact_manifest_service
from app.services.knowledge_metadata_store import KnowledgeMetadataStore


class TrackingVectorStoreManager:
    def __init__(self, call_log):
        self.call_log = call_log
        self.documents: list[Document] = []

    def delete_by_doc_id(self, doc_id: str) -> int:
        before = len(self.documents)
        self.documents = [doc for doc in self.documents if doc.metadata.get("doc_id") != doc_id]
        deleted_count = before - len(self.documents)
        self.call_log.append(("delete_by_doc_id", doc_id, deleted_count))
        return deleted_count

    def delete_by_source(self, file_path: str) -> int:
        before = len(self.documents)
        self.documents = [doc for doc in self.documents if doc.metadata.get("_source") != file_path]
        deleted_count = before - len(self.documents)
        self.call_log.append(("delete_by_source", file_path, deleted_count))
        return deleted_count

    def add_documents(self, documents):
        self.documents.extend(documents)
        self.call_log.append(("add_documents", len(documents)))
        return [f"fake-{index}" for index, _ in enumerate(documents)]

    def prepare_documents(self, documents):
        self.call_log.append(("prepare_documents", len(documents)))
        return list(documents)

    def add_prepared_documents(self, prepared):
        documents = list(prepared)
        self.documents.extend(documents)
        self.call_log.append(("add_prepared_documents", len(documents)))
        return [f"fake-{index}" for index, _ in enumerate(documents)]


class P26IdempotentCleanupTests(unittest.TestCase):
    def _write_json(self, path: Path, payload):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _build_mineru_record(self, root: Path) -> DocumentRecord:
        original_path = (root / "uploads" / "documents" / "default" / "doc_pdf" / "original" / "manual.pdf").resolve()
        artifact_dir = (root / "uploads" / "documents" / "default" / "doc_pdf" / "artifacts").resolve()
        original_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        original_path.write_bytes(b"%PDF-1.4 mock")
        (artifact_dir / "cleaned.md").write_text("# cleaned fallback only", encoding="utf-8")
        self._write_json(artifact_dir / "blocks.json", [])
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
        record = DocumentRecord(
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
        self._write_manifest(record)
        return record

    def _write_manifest(self, record: DocumentRecord):
        artifact_manifest_service.write_manifest(record)

    def test_mineru_reindex_same_doc_id_clears_old_vector_and_chunk_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            temp_store = KnowledgeMetadataStore(root / "uploads" / "_metadata" / "knowledge_metadata_store.json")
            call_log = []
            fake_vector_store = TrackingVectorStoreManager(call_log)
            original_delete_chunks = temp_store.delete_chunks_by_doc_id

            def tracked_delete_chunks(doc_id: str) -> int:
                deleted_count = original_delete_chunks(doc_id)
                call_log.append(("delete_chunks_by_doc_id", doc_id, deleted_count))
                return deleted_count

            record = self._build_mineru_record(root)

            with patch.object(vector_index_module, "knowledge_metadata_store", temp_store):
                with patch.object(vector_index_module, "vector_store_manager", fake_vector_store):
                    with patch.object(ingestion_module, "knowledge_metadata_store", temp_store):
                        with patch.object(
                            temp_store,
                            "delete_chunks_by_doc_id",
                            side_effect=tracked_delete_chunks,
                        ):
                            temp_store.upsert_document(record)
                            service = vector_index_module.VectorIndexService()
                            service.index_document_record(record)

                            self.assertEqual(len(temp_store.list_chunks_by_doc_id(record.doc_id)), 2)
                            self.assertEqual(len(fake_vector_store.documents), 2)

                            # Seed a legacy row that only relies on _source cleanup to make sure the
                            # second pass still removes old data even if doc_id cleanup misses it.
                            fake_vector_store.documents.append(
                                Document(
                                    page_content="legacy stale chunk",
                                    metadata={
                                        "_source": record.original_path,
                                        "_file_name": "manual.pdf",
                                        "_extension": ".pdf",
                                    },
                                )
                            )
                            call_log.clear()

                            service.index_document_record(record)

            self.assertEqual(len(temp_store.list_chunks_by_doc_id(record.doc_id)), 2)
            self.assertEqual(len(fake_vector_store.documents), 2)
            self.assertEqual(
                [entry[0] for entry in call_log],
                [
                    "prepare_documents",
                    "delete_chunks_by_doc_id",
                    "delete_by_doc_id",
                    "delete_by_source",
                    "add_prepared_documents",
                ],
            )
            self.assertEqual(call_log[1][2], 2)
            self.assertEqual(call_log[2][2], 2)
            self.assertEqual(call_log[3][2], 1)

    def test_plain_text_reindex_same_doc_id_clears_old_vector_and_chunk_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            upload_root = root / "uploads"
            sample_path = upload_root / "cpu_high_usage.md"
            sample_path.parent.mkdir(parents=True, exist_ok=True)
            sample_path.write_text(
                "# CPU 告警\n\n## 现象\n\nCPU 持续升高，需要排查业务线程和系统负载。\n",
                encoding="utf-8",
            )

            temp_store = KnowledgeMetadataStore(root / "uploads" / "_metadata" / "knowledge_metadata_store.json")
            call_log = []
            fake_vector_store = TrackingVectorStoreManager(call_log)
            service = vector_index_module.VectorIndexService()
            original_delete_chunks = temp_store.delete_chunks_by_doc_id

            def tracked_delete_chunks(doc_id: str) -> int:
                deleted_count = original_delete_chunks(doc_id)
                call_log.append(("delete_chunks_by_doc_id", doc_id, deleted_count))
                return deleted_count

            with patch.object(vector_index_module, "knowledge_metadata_store", temp_store):
                with patch.object(vector_index_module, "vector_store_manager", fake_vector_store):
                    with patch.object(
                        temp_store,
                        "delete_chunks_by_doc_id",
                        side_effect=tracked_delete_chunks,
                    ):
                        service.index_single_file(str(sample_path), kb_id="default")
                        expected_doc_id = service._build_doc_id("default", sample_path)
                        self.assertEqual(len(temp_store.list_chunks_by_doc_id(expected_doc_id)), 1)
                        self.assertEqual(len(fake_vector_store.documents), 1)

                        fake_vector_store.documents.append(
                            Document(
                                page_content="legacy stale plain text chunk",
                                metadata={
                                    "_source": sample_path.resolve().as_posix(),
                                    "_file_name": sample_path.name,
                                    "_extension": ".md",
                                },
                            )
                        )
                        call_log.clear()

                        service.index_single_file(str(sample_path), kb_id="default")

            self.assertEqual(len(temp_store.list_chunks_by_doc_id(expected_doc_id)), 1)
            self.assertEqual(len(fake_vector_store.documents), 1)
            self.assertEqual(
                [entry[0] for entry in call_log],
                [
                    "prepare_documents",
                    "delete_chunks_by_doc_id",
                    "delete_by_doc_id",
                    "delete_by_source",
                    "add_prepared_documents",
                ],
            )
            self.assertEqual(call_log[1][2], 1)
            self.assertEqual(call_log[2][2], 1)
            self.assertEqual(call_log[3][2], 1)


if __name__ == "__main__":
    unittest.main()
