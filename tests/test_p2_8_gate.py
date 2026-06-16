import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.documents import Document

import app.api.file as file_api
import app.services.document_ingestion_service as ingestion_module
import app.services.vector_index_service as vector_index_module
from app.models import (
    DocumentRecord,
    DocumentStatus,
    ParserEngine,
    RetrievalQuery,
    RetrievalResponse,
    RetrievalResult,
    SourceRef,
)
from app.services.artifact_manifest_service import artifact_manifest_service
from app.services.knowledge_metadata_store import KnowledgeMetadataStore
from app.tools import knowledge_tool as knowledge_tool_module


class GateVectorStoreManager:
    def __init__(self):
        self.documents: list[Document] = []
        self.calls: list[tuple] = []

    def delete_by_doc_id(self, doc_id: str) -> int:
        before = len(self.documents)
        self.documents = [doc for doc in self.documents if doc.metadata.get("doc_id") != doc_id]
        deleted_count = before - len(self.documents)
        self.calls.append(("delete_by_doc_id", doc_id, deleted_count))
        return deleted_count

    def delete_by_source(self, file_path: str) -> int:
        before = len(self.documents)
        self.documents = [doc for doc in self.documents if doc.metadata.get("_source") != file_path]
        deleted_count = before - len(self.documents)
        self.calls.append(("delete_by_source", file_path, deleted_count))
        return deleted_count

    def add_documents(self, documents):
        self.documents.extend(documents)
        self.calls.append(("add_documents", len(documents)))
        return [f"fake-{index}" for index, _ in enumerate(documents)]

    def prepare_documents(self, documents):
        self.calls.append(("prepare_documents", len(documents)))
        return list(documents)

    def add_prepared_documents(self, prepared):
        documents = list(prepared)
        self.documents.extend(documents)
        self.calls.append(("add_prepared_documents", len(documents)))
        return [f"fake-{index}" for index, _ in enumerate(documents)]


class FakeRetrievalToolService:
    def __init__(self, response: RetrievalResponse):
        self.response = response

    def retrieve(self, query: RetrievalQuery) -> RetrievalResponse:
        return self.response


class P28EndToEndGateTests(unittest.TestCase):
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
        artifact_manifest_service.write_manifest(record)
        return record

    def _build_file_app(self) -> FastAPI:
        app = FastAPI()
        app.include_router(file_api.router, prefix="/api")
        return app

    def test_md_txt_regression_gate_preserves_stable_ids_and_source_ref(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sample_path = root / "cpu_high_usage.md"
            sample_path.write_text(
                "# CPU 告警\n\n## 现象\n\nCPU 持续升高，需要排查业务线程和系统负载。\n",
                encoding="utf-8",
            )

            temp_store = KnowledgeMetadataStore(root / "knowledge_metadata_store.json")
            fake_vector_store = GateVectorStoreManager()

            with patch.object(vector_index_module, "knowledge_metadata_store", temp_store):
                with patch.object(vector_index_module, "vector_store_manager", fake_vector_store):
                    service = vector_index_module.VectorIndexService()
                    service.index_single_file(str(sample_path), kb_id="default")

            expected_doc_id = service._build_doc_id("default", sample_path)
            document = temp_store.get_document(expected_doc_id)
            self.assertIsNotNone(document)
            self.assertEqual(document.status, DocumentStatus.INDEXED)
            self.assertEqual(document.status_source, "VectorIndexService.index_document_record")
            self.assertEqual(document.status_evidence["vector_document_count"], 1)
            self.assertIsNotNone(document.status_confirmed_at)
            self.assertEqual(document.parser_engine, ParserEngine.PLAIN_TEXT)

            chunks = temp_store.list_chunks_by_doc_id(expected_doc_id)
            self.assertEqual(len(chunks), 1)
            chunk = chunks[0]
            self.assertEqual(chunk.doc_id, expected_doc_id)
            self.assertTrue(chunk.chunk_id.startswith(f"{expected_doc_id}:c"))
            self.assertEqual(chunk.source_ref.doc_id, expected_doc_id)
            self.assertEqual(chunk.metadata["source_ref"]["chunk_id"], chunk.chunk_id)
            self.assertEqual(chunk.metadata["_source"], sample_path.resolve().as_posix())
            self.assertEqual(len(fake_vector_store.documents), 1)

    def test_artifact_completeness_gate_accepts_full_mineru_bundle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            temp_store = KnowledgeMetadataStore(root / "knowledge_metadata_store.json")
            record = self._build_mineru_record(root)

            temp_store.upsert_document(record)
            with patch.object(ingestion_module, "knowledge_metadata_store", temp_store):
                service = ingestion_module.DocumentIngestionService()
                manifest = service.validate_artifacts_for_index(record.doc_id)
                prepared = service.prepare_artifacts_for_index(record.doc_id)

            self.assertEqual(manifest.doc_id, record.doc_id)
            self.assertEqual(manifest.status, "parsed")
            self.assertEqual(len(prepared.chunk_records), 2)
            self.assertEqual(sorted(manifest.required_files.values()), [
                "blocks.json",
                "chunks.json",
                "cleaned.md",
                "quality_report.json",
                "tables.json",
            ])

    def test_mineru_reference_gate_preserves_source_ref_through_indexing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            temp_store = KnowledgeMetadataStore(root / "knowledge_metadata_store.json")
            fake_vector_store = GateVectorStoreManager()
            record = self._build_mineru_record(root)

            temp_store.upsert_document(record)
            with patch.object(vector_index_module, "knowledge_metadata_store", temp_store):
                with patch.object(vector_index_module, "vector_store_manager", fake_vector_store):
                    with patch.object(ingestion_module, "knowledge_metadata_store", temp_store):
                        service = vector_index_module.VectorIndexService()
                        service.index_document_record(record)

            indexed = temp_store.get_document(record.doc_id)
            self.assertIsNotNone(indexed)
            self.assertEqual(indexed.status, DocumentStatus.INDEXED)
            self.assertEqual(indexed.status_source, "VectorIndexService._index_mineru_document_record")
            self.assertEqual(indexed.status_evidence["vector_document_count"], 2)

            chunks = temp_store.list_chunks_by_doc_id(record.doc_id)
            self.assertEqual(len(chunks), 2)
            for chunk in chunks:
                self.assertEqual(chunk.doc_id, record.doc_id)
                self.assertEqual(chunk.source_ref.doc_id, record.doc_id)
                self.assertEqual(chunk.source_ref.kb_id, "default")
                self.assertEqual(chunk.source_ref.parser_engine, ParserEngine.MINERU)
                self.assertEqual(chunk.metadata["source_ref"]["chunk_id"], chunk.chunk_id)
                self.assertEqual(chunk.metadata["doc_id"], record.doc_id)

            self.assertEqual(len(fake_vector_store.documents), 2)
            for document, chunk in zip(fake_vector_store.documents, chunks, strict=True):
                self.assertEqual(document.metadata["doc_id"], record.doc_id)
                self.assertEqual(document.metadata["chunk_id"], chunk.chunk_id)
                self.assertEqual(document.metadata["source_ref"]["chunk_id"], chunk.chunk_id)

    def test_non_degradation_gate_keeps_upload_api_envelope(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            upload_dir = Path(tmpdir) / "uploads"
            saved_path = upload_dir / "documents" / "default" / "doc_test" / "original" / "notes.md"
            artifact_dir = upload_dir / "documents" / "default" / "doc_test" / "artifacts"

            def fake_ingest_upload(filename: str, content: bytes, kb_id: str = "default"):
                saved_path.parent.mkdir(parents=True, exist_ok=True)
                artifact_dir.mkdir(parents=True, exist_ok=True)
                saved_path.write_bytes(content)
                return DocumentRecord(
                    doc_id="doc_test",
                    kb_id=kb_id,
                    file_name=filename,
                    file_ext="md",
                    original_path=str(saved_path),
                    artifact_dir=str(artifact_dir),
                    parser_engine=ParserEngine.PLAIN_TEXT,
                    status=DocumentStatus.INDEXED,
                )

            with patch.object(file_api, "UPLOAD_DIR", upload_dir):
                with patch.object(
                    file_api.document_ingestion_service,
                    "ingest_upload",
                    fake_ingest_upload,
                ):
                    client = TestClient(self._build_file_app())
                    response = client.post(
                        "/api/upload",
                        files={"file": ("notes.md", b"# Title\n\nBody", "text/markdown")},
                        data={"kb_id": "default"},
                    )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["code"], 200)
            self.assertEqual(payload["message"], "success")
            self.assertEqual(payload["data"]["filename"], "notes.md")
            self.assertEqual(payload["data"]["doc_id"], "doc_test")
            self.assertEqual(payload["data"]["parser_engine"], "plain_text")
            self.assertEqual(payload["data"]["status"], "indexed")
            self.assertEqual(payload["data"]["artifact_dir"], str(artifact_dir))
            self.assertEqual(payload["data"]["file_path"], str(saved_path))

    def test_citation_gate_returns_structured_evidence_artifact(self):
        source_ref = SourceRef(
            kb_id="default",
            doc_id="doc_pdf",
            chunk_id="doc_pdf:table:t00001",
            source_file="manual.pdf",
            page_start=4,
            page_end=4,
            heading_path=["第一章", "参数"],
            content_type="manual_table",
            parser_engine=ParserEngine.MINERU,
        )
        response = RetrievalResponse(
            query=RetrievalQuery(query="参数表在哪里", top_k=3),
            results=[
                RetrievalResult(
                    kb_id="default",
                    doc_id="doc_pdf",
                    chunk_id="doc_pdf:table:t00001",
                    content="| 名称 | 值 |",
                    score=0.2,
                    source_ref=source_ref,
                    citation_text="[来源: manual.pdf, 页码: 4, 章节: 第一章 > 参数, chunk: doc_pdf:table:t00001]",
                    metadata={"kb_id": "default", "doc_id": "doc_pdf"},
                )
            ],
            context_text="【参考资料 1】\n来源: manual.pdf\n定位: [来源: manual.pdf, 页码: 4, 章节: 第一章 > 参数, chunk: doc_pdf:table:t00001]\n内容:\n| 名称 | 值 |\n",
        )
        fake_service = FakeRetrievalToolService(response)

        with patch.object(knowledge_tool_module, "retrieval_service", fake_service):
            content, artifact = knowledge_tool_module.retrieve_knowledge.func("参数表在哪里")

        self.assertEqual(content, response.context_text)
        self.assertEqual(artifact["query"]["query"], "参数表在哪里")
        self.assertEqual(artifact["results"][0]["citation_text"], response.results[0].citation_text)
        self.assertEqual(artifact["results"][0]["source_ref"]["chunk_id"], "doc_pdf:table:t00001")
        self.assertEqual(artifact["results"][0]["source_ref"]["doc_id"], "doc_pdf")
        self.assertEqual(artifact["results"][0]["source_ref"]["kb_id"], "default")


if __name__ == "__main__":
    unittest.main()
