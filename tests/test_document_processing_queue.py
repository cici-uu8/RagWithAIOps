import unittest
from datetime import datetime
from unittest.mock import patch

from app.models import DocumentRecord, DocumentStatus, ParserEngine
from app.services.document_processing_queue import (
    DocumentProcessingQueue,
    process_directory_index_batch_job,
    process_deferred_document_job,
)


class FakeJob:
    id = "job-123"


class FakeRqQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, func, *args, **kwargs):
        self.calls.append((func, args, kwargs))
        return FakeJob()


class FakeDocumentIngestionService:
    def __init__(self, returned_record):
        self.returned_record = returned_record
        self.processed_doc_ids = []

    def process_deferred_document(self, doc_id: str):
        self.processed_doc_ids.append(doc_id)
        return self.returned_record


class FakeVectorIndexService:
    def __init__(self, indexed_record):
        self.indexed_record = indexed_record
        self.indexed_doc_ids = []

    def index_document_record(self, document_record):
        self.indexed_doc_ids.append(document_record.doc_id)


class FakeDirectoryIngestionService:
    def __init__(self):
        self.calls = []

    def ingest_directory(self, directory_path: str, *, kb_id: str, recursive: bool = True):
        self.calls.append((directory_path, kb_id, recursive))
        return type(
            "DirectoryIngestionResult",
            (),
            {
                "to_dict": lambda self: {
                    "success": True,
                    "directory_path": directory_path,
                    "kb_id": kb_id,
                    "recursive": recursive,
                    "total_files": 2,
                    "success_count": 2,
                    "fail_count": 0,
                }
            },
        )()


class FakeMetadataStore:
    def __init__(self, latest_record):
        self.latest_record = latest_record

    def get_document(self, doc_id: str):
        if self.latest_record.doc_id == doc_id:
            return self.latest_record
        return None


def _record(status: DocumentStatus) -> DocumentRecord:
    now = datetime.now()
    return DocumentRecord(
        doc_id="doc_pdf",
        kb_id="default",
        file_name="manual.pdf",
        file_ext="pdf",
        original_path="/tmp/manual.pdf",
        artifact_dir="/tmp/artifacts",
        parser_engine=ParserEngine.MINERU,
        status=status,
        created_at=now,
        updated_at=now,
    )


class DocumentProcessingQueueTests(unittest.TestCase):
    def test_enqueue_deferred_document_submits_rq_job(self):
        fake_queue = FakeRqQueue()
        queue = DocumentProcessingQueue(
            redis_url="redis://test",
            queue_name="test_queue",
            job_timeout_seconds=60,
            result_ttl_seconds=120,
            failure_ttl_seconds=180,
            queue_factory=lambda: fake_queue,
        )

        job_ref = queue.enqueue_deferred_document("doc_pdf")

        self.assertEqual(job_ref.job_id, "job-123")
        self.assertEqual(job_ref.queue_name, "test_queue")
        self.assertEqual(job_ref.doc_id, "doc_pdf")
        self.assertEqual(len(fake_queue.calls), 1)
        func, args, kwargs = fake_queue.calls[0]
        self.assertIs(func, process_deferred_document_job)
        self.assertEqual(args, ("doc_pdf",))
        self.assertEqual(kwargs["job_timeout"], 60)
        self.assertEqual(kwargs["result_ttl"], 120)
        self.assertEqual(kwargs["failure_ttl"], 180)
        self.assertEqual(kwargs["meta"], {"doc_id": "doc_pdf"})

    def test_enqueue_directory_index_batch_submits_rq_job(self):
        fake_queue = FakeRqQueue()
        queue = DocumentProcessingQueue(
            redis_url="redis://test",
            queue_name="test_queue",
            job_timeout_seconds=60,
            result_ttl_seconds=120,
            failure_ttl_seconds=180,
            queue_factory=lambda: fake_queue,
        )

        job_ref = queue.enqueue_directory_index_batch("/tmp/docs", kb_id="aiops")

        self.assertEqual(job_ref.job_id, "job-123")
        self.assertEqual(job_ref.queue_name, "test_queue")
        self.assertEqual(job_ref.directory_path, "/tmp/docs")
        self.assertEqual(job_ref.kb_id, "aiops")
        self.assertEqual(len(fake_queue.calls), 1)
        func, args, kwargs = fake_queue.calls[0]
        self.assertIs(func, process_directory_index_batch_job)
        self.assertEqual(args, ("/tmp/docs", "aiops"))
        self.assertEqual(kwargs["job_timeout"], 60)
        self.assertEqual(kwargs["result_ttl"], 120)
        self.assertEqual(kwargs["failure_ttl"], 180)
        self.assertEqual(
            kwargs["meta"],
            {
                "job_type": "directory_index_batch",
                "directory_path": "/tmp/docs",
                "kb_id": "aiops",
            },
        )

    def test_process_deferred_document_job_indexes_index_pending_document(self):
        parsed = _record(DocumentStatus.INDEX_PENDING)
        indexed = _record(DocumentStatus.INDEXED)
        fake_ingestion = FakeDocumentIngestionService(parsed)
        fake_indexer = FakeVectorIndexService(indexed)
        fake_store = FakeMetadataStore(indexed)

        with patch(
            "app.services.document_ingestion_service.document_ingestion_service",
            fake_ingestion,
        ):
            with patch(
                "app.services.vector_index_service.vector_index_service",
                fake_indexer,
            ):
                with patch(
                    "app.services.knowledge_metadata_store.knowledge_metadata_store",
                    fake_store,
                ):
                    result = process_deferred_document_job("doc_pdf")

        self.assertEqual(fake_ingestion.processed_doc_ids, ["doc_pdf"])
        self.assertEqual(fake_indexer.indexed_doc_ids, ["doc_pdf"])
        self.assertEqual(result["doc_id"], "doc_pdf")
        self.assertEqual(result["status"], "indexed")

    def test_process_deferred_document_job_returns_parse_failed_without_index(self):
        failed = _record(DocumentStatus.PARSE_FAILED)
        fake_ingestion = FakeDocumentIngestionService(failed)
        fake_indexer = FakeVectorIndexService(failed)
        fake_store = FakeMetadataStore(failed)

        with patch(
            "app.services.document_ingestion_service.document_ingestion_service",
            fake_ingestion,
        ):
            with patch(
                "app.services.vector_index_service.vector_index_service",
                fake_indexer,
            ):
                with patch(
                    "app.services.knowledge_metadata_store.knowledge_metadata_store",
                    fake_store,
                ):
                    result = process_deferred_document_job("doc_pdf")

        self.assertEqual(fake_ingestion.processed_doc_ids, ["doc_pdf"])
        self.assertEqual(fake_indexer.indexed_doc_ids, [])
        self.assertEqual(result["status"], "parse_failed")

    def test_process_directory_index_batch_job_returns_indexing_result(self):
        fake_ingestion = FakeDirectoryIngestionService()

        with patch(
            "app.services.document_ingestion_service.document_ingestion_service",
            fake_ingestion,
        ):
            result = process_directory_index_batch_job("/tmp/docs", "aiops")

        self.assertEqual(fake_ingestion.calls, [("/tmp/docs", "aiops", True)])
        self.assertEqual(result["success"], True)
        self.assertEqual(result["total_files"], 2)
        self.assertEqual(result["kb_id"], "aiops")


if __name__ == "__main__":
    unittest.main()
