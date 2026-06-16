import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.models import DocumentRecord, DocumentStatus, ParserEngine
from app.services.document_processing_workflow import DocumentProcessingWorkflow
from app.services.knowledge_metadata_store import KnowledgeMetadataStore


class FakeDocumentProcessingQueue:
    def health(self):
        return {
            "queue_enabled": True,
            "redis_connected": False,
            "worker_seen_recently": "unknown",
            "failed_job_count": "unknown",
            "queue_name": "test_document_processing",
        }


def _document(
    doc_id: str,
    status: DocumentStatus,
    root: Path,
    *,
    seconds_old: int,
) -> DocumentRecord:
    now = datetime.now()
    stale_time = now - timedelta(seconds=seconds_old)
    return DocumentRecord(
        doc_id=doc_id,
        kb_id="default",
        file_name=f"{doc_id}.pdf",
        file_ext="pdf",
        original_path=(root / f"{doc_id}.pdf").as_posix(),
        artifact_dir=(root / doc_id / "artifacts").as_posix(),
        parser_engine=ParserEngine.MINERU,
        status=status,
        status_source="test",
        status_detail="test processing state",
        status_evidence={
            "processing_job_id": f"job-{doc_id}",
            "processing_queue": "test_document_processing",
        },
        status_confirmed_at=stale_time,
        created_at=stale_time,
        updated_at=stale_time,
    )


class DocumentProcessingWorkflowTests(unittest.TestCase):
    def test_reconcile_stale_parse_pending_marks_parse_failed_with_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = KnowledgeMetadataStore(root / "metadata.json")
            store.upsert_document(
                _document(
                    "doc-parse-stale",
                    DocumentStatus.PARSE_PENDING,
                    root,
                    seconds_old=7200,
                )
            )
            workflow = DocumentProcessingWorkflow(
                metadata_store=store,
                processing_queue=FakeDocumentProcessingQueue(),
                stale_after_seconds=60,
            )

            summary = workflow.reconcile_stale_processing()

            self.assertEqual(summary["reconciled_count"], 1)
            updated = store.get_document("doc-parse-stale")
            self.assertEqual(updated.status, DocumentStatus.PARSE_FAILED)
            self.assertEqual(
                updated.status_source,
                "DocumentProcessingWorkflow.reconcile_stale_processing",
            )
            self.assertEqual(updated.status_evidence["error_code"], "document_processing_stale")
            self.assertEqual(updated.status_evidence["previous_status"], "parse_pending")
            self.assertEqual(updated.status_evidence["job_id"], "job-doc-parse-stale")
            self.assertGreaterEqual(updated.status_evidence["processing_age_seconds"], 60)
            self.assertEqual(updated.metadata["error_code"], "document_processing_stale")
            self.assertIn("stale", updated.error_message)

    def test_reconcile_stale_indexing_marks_index_failed_and_worker_health_reports_stale_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = KnowledgeMetadataStore(root / "metadata.json")
            store.upsert_document(
                _document(
                    "doc-index-stale",
                    DocumentStatus.INDEXING,
                    root,
                    seconds_old=3600,
                )
            )
            workflow = DocumentProcessingWorkflow(
                metadata_store=store,
                processing_queue=FakeDocumentProcessingQueue(),
                stale_after_seconds=120,
            )

            health_before = workflow.worker_health()
            summary = workflow.reconcile_stale_processing()
            health_after = workflow.worker_health()

            self.assertEqual(health_before["stale_processing_count"], 1)
            self.assertGreaterEqual(health_before["oldest_processing_age_seconds"], 120)
            self.assertEqual(summary["reconciled_count"], 1)
            updated = store.get_document("doc-index-stale")
            self.assertEqual(updated.status, DocumentStatus.INDEX_FAILED)
            self.assertEqual(updated.status_evidence["previous_status"], "indexing")
            self.assertEqual(updated.status_evidence["job_id"], "job-doc-index-stale")
            self.assertEqual(health_after["stale_processing_count"], 0)
            self.assertEqual(health_after["worker_seen_recently"], "unknown")


if __name__ == "__main__":
    unittest.main()
