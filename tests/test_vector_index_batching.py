import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from langchain_core.documents import Document
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.file as file_api
import app.services.vector_index_service as vector_index_module
from app.models import ChunkRecord, DocumentRecord, DocumentStatus, ParserEngine, SourceRef
from app.services.document_processing_queue import DocumentProcessingQueue
from app.services.knowledge_metadata_store import KnowledgeMetadataStore


class FakeBatchQueue:
    def __init__(self):
        self.calls = []

    def enqueue_directory_index_batch(self, directory_path: str, kb_id: str):
        self.calls.append((directory_path, kb_id))
        return type(
            "JobRef",
            (),
            {
                "job_id": "batch-job-1",
                "queue_name": "doc-queue",
                "directory_path": directory_path,
                "kb_id": kb_id,
            },
        )()


class FakeVectorStoreManager:
    def __init__(self):
        self.documents: list[Document] = []
        self.calls: list[tuple] = []

    def delete_by_doc_id(self, doc_id: str) -> int:
        before = len(self.documents)
        self.documents = [doc for doc in self.documents if doc.metadata.get("doc_id") != doc_id]
        deleted = before - len(self.documents)
        self.calls.append(("delete_by_doc_id", doc_id, deleted))
        return deleted

    def delete_by_source(self, file_path: str) -> int:
        before = len(self.documents)
        self.documents = [doc for doc in self.documents if doc.metadata.get("_source") != file_path]
        deleted = before - len(self.documents)
        self.calls.append(("delete_by_source", file_path, deleted))
        return deleted

    def prepare_documents(self, documents):
        self.calls.append(("prepare_documents", len(documents)))
        return {
            "documents": documents,
            "prepared": True,
        }

    def add_prepared_documents(self, prepared):
        documents = prepared["documents"]
        self.documents.extend(documents)
        self.calls.append(("add_prepared_documents", len(documents)))
        return [f"fake-{index}" for index, _ in enumerate(documents)]


class FakeFailingPrepareVectorStore(FakeVectorStoreManager):
    def prepare_documents(self, documents):
        self.calls.append(("prepare_documents", len(documents)))
        raise RuntimeError("prepare boom")


class VectorIndexBatchingTests(unittest.TestCase):
    def _build_app(self):
        app = FastAPI()
        app.include_router(file_api.router, prefix="/api")
        return app

    def test_upload_api_directory_index_returns_batch_job_reference(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "index-me"
            source_dir.mkdir(parents=True, exist_ok=True)
            fake_queue = FakeBatchQueue()

            with patch.object(file_api, "document_processing_queue", fake_queue, create=True):
                client = TestClient(self._build_app())
                response = client.post(
                    "/api/index_directory",
                    data={"directory_path": str(source_dir), "kb_id": "aiops"},
                )

            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            self.assertEqual(payload["code"], 200)
            self.assertEqual(payload["data"]["async_processing"], True)
            self.assertEqual(payload["data"]["batch_job_id"], "batch-job-1")
            self.assertEqual(fake_queue.calls, [(str(source_dir), "aiops")])

    def test_upload_api_directory_index_maps_queue_validation_to_400(self):
        fake_rq_queue = FakeBatchQueue()
        validating_queue = DocumentProcessingQueue(
            redis_url="redis://test",
            queue_name="test_queue",
            job_timeout_seconds=60,
            result_ttl_seconds=120,
            failure_ttl_seconds=180,
            queue_factory=lambda: fake_rq_queue,
        )

        with patch.object(file_api, "document_processing_queue", validating_queue, create=True):
            client = TestClient(self._build_app())
            response = client.post(
                "/api/index_directory",
                data={"directory_path": "/tmp/docs", "kb_id": "   "},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("kb_id", response.json()["detail"])
        self.assertEqual(fake_rq_queue.calls, [])

    def test_prepare_failure_keeps_old_vector_data_intact(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sample_path = root / "cpu_high_usage.md"
            sample_path.write_text("# CPU\n\nbody", encoding="utf-8")
            temp_store = KnowledgeMetadataStore(root / "uploads" / "_metadata" / "knowledge_metadata_store.json")
            fake_vector_store = FakeFailingPrepareVectorStore()
            service = vector_index_module.VectorIndexService()
            expected_doc_id = service._build_doc_id("default", sample_path)

            temp_store.upsert_document(
                DocumentRecord(
                    doc_id=expected_doc_id,
                    kb_id="default",
                    file_name=sample_path.name,
                    file_ext="md",
                    original_path=sample_path.resolve().as_posix(),
                    artifact_dir=str(root / "uploads" / "documents" / "default" / expected_doc_id / "artifacts"),
                    parser_engine=ParserEngine.PLAIN_TEXT,
                    status=DocumentStatus.INDEXED,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
            )
            temp_store.replace_chunks(
                expected_doc_id,
                [
                    ChunkRecord(
                        chunk_id=f"{expected_doc_id}:c00000",
                        doc_id=expected_doc_id,
                        kb_id="default",
                        content="old chunk",
                        chunk_index=0,
                        start_index=0,
                        end_index=9,
                        heading_path=[],
                        page_start=None,
                        page_end=None,
                        content_type="text",
                        source_ref=SourceRef(
                            kb_id="default",
                            doc_id=expected_doc_id,
                            chunk_id=f"{expected_doc_id}:c00000",
                            source_file=sample_path.name,
                            page_start=None,
                            page_end=None,
                            heading_path=[],
                            content_type="text",
                            parser_engine=ParserEngine.PLAIN_TEXT,
                        ),
                        quality_flags=[],
                        metadata={
                            "kb_id": "default",
                            "doc_id": expected_doc_id,
                            "chunk_id": f"{expected_doc_id}:c00000",
                            "_source": sample_path.resolve().as_posix(),
                            "_file_name": sample_path.name,
                            "_extension": ".md",
                        },
                    )
                ],
            )
            fake_vector_store.documents.append(
                Document(
                    page_content="old chunk",
                    metadata={
                        "doc_id": expected_doc_id,
                        "_source": sample_path.resolve().as_posix(),
                        "_file_name": sample_path.name,
                        "_extension": ".md",
                    },
                )
            )

            with patch.object(vector_index_module, "knowledge_metadata_store", temp_store):
                with patch.object(vector_index_module, "vector_store_manager", fake_vector_store):
                    with self.assertRaises(RuntimeError):
                        service.index_single_file(str(sample_path), kb_id="default")

            self.assertEqual(len(temp_store.list_chunks_by_doc_id(expected_doc_id)), 1)
            self.assertEqual(len(fake_vector_store.documents), 1)
            self.assertEqual([item[0] for item in fake_vector_store.calls], ["prepare_documents"])


if __name__ == "__main__":
    unittest.main()
