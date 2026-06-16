import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.file as file_api
import app.services.document_ingestion_service as ingestion_module
from app.models import DocumentRecord, DocumentStatus, ParserEngine
from app.services.document_processing_queue import DocumentProcessingJobRef
from app.services.knowledge_metadata_store import KnowledgeMetadataStore


class FakeVectorIndexService:
    def __init__(self):
        self.indexed_doc_ids: list[str] = []

    def index_document_record(self, document_record):
        self.indexed_doc_ids.append(document_record.doc_id)
        ingestion_module.knowledge_metadata_store.transition_document_status(
            document_record.doc_id,
            DocumentStatus.INDEXED,
            status_source="FakeVectorIndexService.index_document_record",
            status_detail="fake indexer accepted the plain-text document",
            status_evidence={"doc_id": document_record.doc_id},
        )


class FakeDocumentProcessingQueue:
    def __init__(self, failure: Exception | None = None):
        self.queue_name = "test_document_processing"
        self.failure = failure
        self.enqueued_doc_ids: list[str] = []

    def enqueue_deferred_document(self, doc_id: str) -> DocumentProcessingJobRef:
        self.enqueued_doc_ids.append(doc_id)
        if self.failure is not None:
            raise self.failure
        return DocumentProcessingJobRef(
            job_id=f"job-{doc_id}",
            queue_name=self.queue_name,
            doc_id=doc_id,
        )

    def health(self):
        return {
            "queue_enabled": True,
            "redis_connected": False,
            "worker_seen_recently": "unknown",
            "failed_job_count": "unknown",
            "queue_name": self.queue_name,
        }


class FakePdfProfileService:
    def __init__(self, failure: Exception | None = None):
        self.failure = failure
        self.profiled_paths: list[str] = []

    def profile_pdf(self, original_path, *, file_size: int):
        self.profiled_paths.append(Path(original_path).name)
        if self.failure is not None:
            raise self.failure
        return {
            "profile_status": "ok",
            "profile_version": "test",
            "page_count": 1,
            "is_encrypted": False,
            "text_layer_sample_chars": 128,
            "risk_flags": ["native_text"],
            "file_size": file_size,
        }


class RecordingKnowledgeMetadataStore(KnowledgeMetadataStore):
    def __init__(self, store_path):
        super().__init__(store_path)
        self.transitions = []

    def transition_document_status(self, doc_id, status, **kwargs):
        self.transitions.append(
            {
                "doc_id": doc_id,
                "status": status,
                "status_evidence": kwargs.get("status_evidence", {}),
            }
        )
        return super().transition_document_status(doc_id, status, **kwargs)


def build_file_app() -> FastAPI:
    app = FastAPI()
    app.include_router(file_api.router, prefix="/api")
    return app


class DocumentIngestionServiceTests(unittest.TestCase):
    def test_ingest_directory_scans_supported_types_through_unified_ingestion_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "source"
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "a.md").write_text("# A", encoding="utf-8")
            (source_dir / "b.pdf").write_bytes(b"%PDF-1.4 mock")
            nested_dir = source_dir / "nested"
            nested_dir.mkdir()
            (nested_dir / "c.xlsx").write_bytes(b"mock xlsx")
            (source_dir / "ignore.csv").write_text("skip", encoding="utf-8")

            upload_root = root / "uploads"
            temp_store = KnowledgeMetadataStore(upload_root / "_metadata" / "knowledge_metadata_store.json")
            fake_indexer = FakeVectorIndexService()
            fake_queue = FakeDocumentProcessingQueue()
            service = ingestion_module.DocumentIngestionService(upload_root=upload_root)

            with patch.object(ingestion_module, "knowledge_metadata_store", temp_store):
                with patch.object(ingestion_module, "vector_index_service", fake_indexer):
                    with patch.object(ingestion_module, "document_processing_queue", fake_queue):
                        result = service.ingest_directory(source_dir, kb_id="aiops")

            self.assertTrue(result.success)
            self.assertEqual(result.total_files, 3)
            self.assertEqual(result.success_count, 3)
            self.assertEqual(result.queued_count, 2)
            self.assertEqual(result.fail_count, 0)
            self.assertEqual(result.kb_id, "aiops")
            self.assertEqual(len(result.document_ids), 3)
            stored_file_names = [
                temp_store.get_document(doc_id).file_name
                for doc_id in result.document_ids
            ]
            self.assertEqual(stored_file_names, ["a.md", "b.pdf", "c.xlsx"])
            self.assertEqual(len(fake_indexer.indexed_doc_ids), 1)
            self.assertEqual(len(fake_queue.enqueued_doc_ids), 2)

    def test_plain_text_upload_enters_formal_workflow_and_indexes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            upload_root = Path(tmpdir) / "uploads"
            temp_store = KnowledgeMetadataStore(upload_root / "_metadata" / "knowledge_metadata_store.json")
            fake_indexer = FakeVectorIndexService()
            service = ingestion_module.DocumentIngestionService(upload_root=upload_root)

            with patch.object(ingestion_module, "knowledge_metadata_store", temp_store):
                with patch.object(ingestion_module, "vector_index_service", fake_indexer):
                    record = service.ingest_upload("notes.md", b"# Title\n\nBody", kb_id="default")

            self.assertEqual(record.parser_engine, ParserEngine.PLAIN_TEXT)
            self.assertEqual(record.status, DocumentStatus.INDEXED)
            self.assertEqual(fake_indexer.indexed_doc_ids, [record.doc_id])
            self.assertTrue(Path(record.original_path).exists())
            self.assertTrue(Path(record.artifact_dir).exists())
            self.assertIn(f"/documents/default/{record.doc_id}/original/notes.md", record.original_path)
            stored = temp_store.get_document(record.doc_id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.status, DocumentStatus.INDEXED)
            self.assertEqual(stored.status_source, "FakeVectorIndexService.index_document_record")
            self.assertEqual(stored.status_evidence["doc_id"], record.doc_id)
            self.assertIsNotNone(stored.status_confirmed_at)

    def test_mineru_upload_stops_at_parse_pending_without_indexing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            upload_root = Path(tmpdir) / "uploads"
            temp_store = RecordingKnowledgeMetadataStore(
                upload_root / "_metadata" / "knowledge_metadata_store.json"
            )
            fake_indexer = FakeVectorIndexService()
            fake_queue = FakeDocumentProcessingQueue()
            service = ingestion_module.DocumentIngestionService(upload_root=upload_root)

            with patch.object(ingestion_module, "knowledge_metadata_store", temp_store):
                with patch.object(ingestion_module, "vector_index_service", fake_indexer):
                    with patch.object(ingestion_module, "document_processing_queue", fake_queue):
                        record = service.ingest_upload("manual.pdf", b"%PDF-1.4 mock", kb_id="default")

            self.assertEqual(record.parser_engine, ParserEngine.MINERU)
            self.assertEqual(record.status, DocumentStatus.PARSE_PENDING)
            self.assertEqual(fake_queue.enqueued_doc_ids, [record.doc_id])
            self.assertEqual(fake_indexer.indexed_doc_ids, [])
            self.assertTrue(Path(record.original_path).exists())
            self.assertTrue(Path(record.artifact_dir).exists())
            self.assertIn(f"/documents/default/{record.doc_id}/original/manual.pdf", record.original_path)
            stored = temp_store.get_document(record.doc_id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.status, DocumentStatus.PARSE_PENDING)
            self.assertEqual(stored.status_source, "DocumentIngestionService.ingest_upload")
            self.assertEqual(stored.status_evidence["parser_engine"], "mineru")
            self.assertEqual(stored.status_evidence["processing_job_id"], f"job-{record.doc_id}")
            self.assertEqual(stored.status_evidence["processing_queue"], "test_document_processing")
            self.assertIn("enqueued_at", stored.status_evidence)
            self.assertIsNotNone(stored.status_confirmed_at)
            parse_pending_transitions = [
                transition
                for transition in temp_store.transitions
                if transition["status"] == DocumentStatus.PARSE_PENDING
            ]
            self.assertEqual(len(parse_pending_transitions), 1)
            self.assertEqual(
                parse_pending_transitions[0]["status_evidence"]["processing_job_id"],
                f"job-{record.doc_id}",
            )

    def test_pdf_upload_writes_profile_metadata_without_changing_queue_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            upload_root = Path(tmpdir) / "uploads"
            temp_store = KnowledgeMetadataStore(upload_root / "_metadata" / "knowledge_metadata_store.json")
            fake_indexer = FakeVectorIndexService()
            fake_queue = FakeDocumentProcessingQueue()
            fake_profile = FakePdfProfileService()
            service = ingestion_module.DocumentIngestionService(upload_root=upload_root)

            with patch.object(ingestion_module, "knowledge_metadata_store", temp_store):
                with patch.object(ingestion_module, "vector_index_service", fake_indexer):
                    with patch.object(ingestion_module, "document_processing_queue", fake_queue):
                        with patch.object(ingestion_module, "pdf_profile_service", fake_profile):
                            record = service.ingest_upload("manual.pdf", b"%PDF-1.4 mock", kb_id="default")

            stored = temp_store.get_document(record.doc_id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.status, DocumentStatus.PARSE_PENDING)
            self.assertEqual(fake_queue.enqueued_doc_ids, [record.doc_id])
            self.assertEqual(fake_indexer.indexed_doc_ids, [])
            self.assertEqual(fake_profile.profiled_paths, ["manual.pdf"])
            self.assertEqual(stored.metadata["pdf_profile"]["profile_status"], "ok")
            self.assertEqual(stored.metadata["pdf_profile"]["page_count"], 1)
            self.assertEqual(stored.metadata["pdf_profile"]["risk_flags"], ["native_text"])

    def test_non_pdf_upload_does_not_write_pdf_profile_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            upload_root = Path(tmpdir) / "uploads"
            temp_store = KnowledgeMetadataStore(upload_root / "_metadata" / "knowledge_metadata_store.json")
            fake_indexer = FakeVectorIndexService()
            fake_profile = FakePdfProfileService()
            service = ingestion_module.DocumentIngestionService(upload_root=upload_root)

            with patch.object(ingestion_module, "knowledge_metadata_store", temp_store):
                with patch.object(ingestion_module, "vector_index_service", fake_indexer):
                    with patch.object(ingestion_module, "pdf_profile_service", fake_profile):
                        record = service.ingest_upload("notes.md", b"# Title", kb_id="default")

            stored = temp_store.get_document(record.doc_id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.status, DocumentStatus.INDEXED)
            self.assertNotIn("pdf_profile", stored.metadata)
            self.assertEqual(fake_profile.profiled_paths, [])

    def test_pdf_profile_failure_degrades_without_blocking_upload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            upload_root = Path(tmpdir) / "uploads"
            temp_store = KnowledgeMetadataStore(upload_root / "_metadata" / "knowledge_metadata_store.json")
            fake_queue = FakeDocumentProcessingQueue()
            fake_profile = FakePdfProfileService(failure=RuntimeError("profile unavailable"))
            service = ingestion_module.DocumentIngestionService(upload_root=upload_root)

            with patch.object(ingestion_module, "knowledge_metadata_store", temp_store):
                with patch.object(ingestion_module, "document_processing_queue", fake_queue):
                    with patch.object(ingestion_module, "pdf_profile_service", fake_profile):
                        record = service.ingest_upload("manual.pdf", b"%PDF-1.4 mock", kb_id="default")

            stored = temp_store.get_document(record.doc_id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.status, DocumentStatus.PARSE_PENDING)
            self.assertEqual(fake_queue.enqueued_doc_ids, [record.doc_id])
            self.assertEqual(stored.metadata["pdf_profile"]["profile_status"], "failed")
            self.assertEqual(stored.metadata["pdf_profile"]["risk_flags"], ["profile_failed"])
            self.assertEqual(stored.metadata["pdf_profile"]["error_type"], "RuntimeError")

    def test_upload_write_failure_does_not_create_document_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            upload_root = Path(tmpdir) / "uploads"
            store_path = upload_root / "_metadata" / "knowledge_metadata_store.json"
            temp_store = KnowledgeMetadataStore(store_path)
            service = ingestion_module.DocumentIngestionService(upload_root=upload_root)

            with patch.object(ingestion_module, "knowledge_metadata_store", temp_store):
                with patch.object(Path, "write_bytes", side_effect=OSError("disk full")):
                    with self.assertRaises(OSError):
                        service.ingest_upload("manual.pdf", b"%PDF-1.4 mock", kb_id="default")

            self.assertFalse(store_path.exists())

    def test_mineru_upload_records_enqueue_failed_status_when_queue_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            upload_root = Path(tmpdir) / "uploads"
            temp_store = KnowledgeMetadataStore(upload_root / "_metadata" / "knowledge_metadata_store.json")
            fake_queue = FakeDocumentProcessingQueue(failure=RuntimeError("redis unavailable"))
            service = ingestion_module.DocumentIngestionService(upload_root=upload_root)
            content = b"%PDF-1.4 mock"
            expected_doc_id = service._build_uploaded_doc_id("default", "manual.pdf", content)

            with patch.object(ingestion_module, "knowledge_metadata_store", temp_store):
                with patch.object(ingestion_module, "document_processing_queue", fake_queue):
                    with self.assertRaises(RuntimeError):
                        service.ingest_upload("manual.pdf", content, kb_id="default")

            stored = temp_store.get_document(expected_doc_id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.status, DocumentStatus.ENQUEUE_FAILED)
            self.assertEqual(stored.status_source, "DocumentIngestionService.ingest_upload")
            self.assertEqual(stored.status_evidence["parser_engine"], "mineru")
            self.assertEqual(stored.status_evidence["queue_name"], "test_document_processing")
            self.assertEqual(stored.status_evidence["error_type"], "RuntimeError")
            self.assertEqual(stored.error_message, "redis unavailable")
            self.assertTrue(Path(stored.original_path).exists())

    def test_upload_api_accepts_pdf_and_returns_parse_pending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            upload_root = Path(tmpdir) / "uploads"
            temp_store = KnowledgeMetadataStore(upload_root / "_metadata" / "knowledge_metadata_store.json")
            fake_indexer = FakeVectorIndexService()
            fake_queue = FakeDocumentProcessingQueue()
            service = ingestion_module.DocumentIngestionService(upload_root=upload_root)

            with patch.object(ingestion_module, "knowledge_metadata_store", temp_store):
                with patch.object(ingestion_module, "vector_index_service", fake_indexer):
                    with patch.object(file_api, "UPLOAD_DIR", upload_root):
                        with patch.object(file_api, "document_ingestion_service", service):
                            with patch.object(ingestion_module, "document_processing_queue", fake_queue):
                                client = TestClient(build_file_app())
                                response = client.post(
                                    "/api/upload",
                                    files={"file": ("manual.pdf", b"%PDF-1.4 mock", "application/pdf")},
                                    data={"kb_id": "default"},
                                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["code"], 200)
            self.assertEqual(payload["message"], "success")
            self.assertEqual(payload["data"]["filename"], "manual.pdf")
            self.assertEqual(payload["data"]["parser_engine"], "mineru")
            self.assertEqual(payload["data"]["status"], "parse_pending")
            self.assertTrue(payload["data"]["doc_id"].startswith("doc_"))
            self.assertTrue(payload["data"]["async_processing"])
            self.assertEqual(payload["data"]["processing_queue"], "test_document_processing")
            self.assertEqual(fake_queue.enqueued_doc_ids, [payload["data"]["doc_id"]])
            self.assertTrue(Path(payload["data"]["file_path"]).exists())
            self.assertTrue(Path(payload["data"]["artifact_dir"]).exists())
            self.assertEqual(fake_indexer.indexed_doc_ids, [])

    def test_upload_api_rejects_unsupported_type_from_ingestion_layer(self):
        client = TestClient(build_file_app())
        response = client.post(
            "/api/upload",
            files={"file": ("data.csv", b"a,b\n1,2", "text/csv")},
            data={"kb_id": "default"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("不支持该文件类型", response.json()["detail"])

    def test_document_status_api_returns_confirmed_status_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            upload_root = Path(tmpdir) / "uploads"
            temp_store = KnowledgeMetadataStore(upload_root / "_metadata" / "knowledge_metadata_store.json")
            fake_queue = FakeDocumentProcessingQueue()
            service = ingestion_module.DocumentIngestionService(upload_root=upload_root)

            with patch.object(ingestion_module, "knowledge_metadata_store", temp_store):
                with patch.object(ingestion_module, "document_processing_queue", fake_queue):
                    record = service.ingest_upload("manual.pdf", b"%PDF-1.4 mock", kb_id="default")

            with patch.object(file_api, "knowledge_metadata_store", temp_store):
                client = TestClient(build_file_app())
                response = client.get(f"/api/documents/{record.doc_id}")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["data"]["doc_id"], record.doc_id)
            self.assertEqual(payload["data"]["status"], "parse_pending")
            self.assertEqual(payload["data"]["status_source"], "DocumentIngestionService.ingest_upload")
            self.assertEqual(payload["data"]["status_evidence"]["parser_engine"], "mineru")
            self.assertIsNotNone(payload["data"]["status_confirmed_at"])

    def test_document_status_batch_reconciles_stale_processing_before_returning_status(self):
        from app.services.document_processing_workflow import DocumentProcessingWorkflow

        with tempfile.TemporaryDirectory() as tmpdir:
            upload_root = Path(tmpdir) / "uploads"
            temp_store = KnowledgeMetadataStore(upload_root / "_metadata" / "knowledge_metadata_store.json")
            stale_time = datetime.now() - timedelta(seconds=7200)
            temp_store.upsert_document(
                DocumentRecord(
                    doc_id="doc-stale-batch",
                    kb_id="default",
                    file_name="manual.pdf",
                    file_ext="pdf",
                    original_path=(upload_root / "manual.pdf").as_posix(),
                    artifact_dir=(upload_root / "doc-stale-batch" / "artifacts").as_posix(),
                    parser_engine=ParserEngine.MINERU,
                    status=DocumentStatus.PARSE_PENDING,
                    status_source="test",
                    status_detail="waiting for worker",
                    status_evidence={
                        "processing_job_id": "job-doc-stale-batch",
                        "processing_queue": "test_document_processing",
                    },
                    status_confirmed_at=stale_time,
                    created_at=stale_time,
                    updated_at=stale_time,
                )
            )
            workflow = DocumentProcessingWorkflow(
                metadata_store=temp_store,
                processing_queue=FakeDocumentProcessingQueue(),
                stale_after_seconds=60,
            )
            client = TestClient(build_file_app())

            with (
                patch.object(file_api, "knowledge_metadata_store", temp_store),
                patch.object(file_api, "document_processing_workflow", workflow),
            ):
                response = client.post(
                    "/api/documents/status-batch",
                    json={"doc_ids": ["doc-stale-batch"]},
                )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()["data"]
        self.assertEqual(payload["reconciliation"]["reconciled_count"], 1)
        self.assertEqual(payload["worker_health"]["worker_seen_recently"], "unknown")
        self.assertEqual(payload["documents"][0]["doc_id"], "doc-stale-batch")
        self.assertEqual(payload["documents"][0]["status"], "parse_failed")
        self.assertEqual(
            payload["documents"][0]["status_evidence"]["error_code"],
            "document_processing_stale",
        )


if __name__ == "__main__":
    unittest.main()
