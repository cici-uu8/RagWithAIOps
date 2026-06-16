"""Document processing lifecycle workflow and health diagnostics."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.config import config
from app.models import DocumentRecord, DocumentStatus

PROCESSING_STATUSES = {
    DocumentStatus.PARSE_PENDING,
    DocumentStatus.PARSING,
    DocumentStatus.INDEX_PENDING,
    DocumentStatus.INDEXING,
}

PARSE_PROCESSING_STATUSES = {
    DocumentStatus.PARSE_PENDING,
    DocumentStatus.PARSING,
}

INDEX_PROCESSING_STATUSES = {
    DocumentStatus.INDEX_PENDING,
    DocumentStatus.INDEXING,
}


class DocumentProcessingWorkflow:
    """Coordinate document processing status transitions outside queue mechanics."""

    def __init__(
        self,
        *,
        metadata_store=None,
        processing_queue=None,
        stale_after_seconds: int | None = None,
    ):
        if metadata_store is None:
            from app.services.knowledge_metadata_store import knowledge_metadata_store

            metadata_store = knowledge_metadata_store
        if processing_queue is None:
            from app.services.document_processing_queue import document_processing_queue

            processing_queue = document_processing_queue

        self.metadata_store = metadata_store
        self.processing_queue = processing_queue
        self.stale_after_seconds = (
            stale_after_seconds or config.document_processing_job_timeout_seconds
        )

    def enqueue_deferred_processing(self, doc_id: str):
        return self.processing_queue.enqueue_deferred_document(doc_id)

    def process_deferred_document(self, doc_id: str) -> DocumentRecord:
        from app.services.document_ingestion_service import document_ingestion_service
        from app.services.vector_index_service import vector_index_service

        parsed_record = document_ingestion_service.process_deferred_document(doc_id)
        if parsed_record.status == DocumentStatus.INDEX_PENDING:
            vector_index_service.index_document_record(parsed_record)
        latest = self.metadata_store.get_document(doc_id)
        return latest or parsed_record

    def reindex_document(self, doc_id: str) -> DocumentRecord:
        from app.services.vector_index_service import vector_index_service

        document = self.metadata_store.get_document(doc_id)
        if document is None:
            raise ValueError(f"文档不存在: {doc_id}")
        vector_index_service.index_document_record(document)
        latest = self.metadata_store.get_document(doc_id)
        return latest or document

    def reconcile_stale_processing(self, *, now: datetime | None = None) -> dict[str, Any]:
        current_time = now or datetime.now()
        reconciled: list[dict[str, Any]] = []
        for document in self.metadata_store.list_documents():
            age_seconds = self._processing_age_seconds(document, current_time)
            if age_seconds is None or age_seconds < self.stale_after_seconds:
                continue

            target_status = self._stale_failure_status(document.status)
            if target_status is None:
                continue

            evidence = self._stale_evidence(document, age_seconds)
            updated = self.metadata_store.transition_document_status(
                document.doc_id,
                target_status,
                status_source="DocumentProcessingWorkflow.reconcile_stale_processing",
                status_detail=(
                    "document processing exceeded the stale threshold and was marked failed"
                ),
                status_evidence=evidence,
                error_message=evidence["error_message"],
                metadata_update={
                    "error_code": evidence["error_code"],
                    "last_processing_failure": evidence,
                },
            )
            if updated is None:
                continue
            reconciled.append(
                {
                    "doc_id": updated.doc_id,
                    "previous_status": evidence["previous_status"],
                    "status": updated.status.value,
                    "processing_age_seconds": age_seconds,
                }
            )

        return {
            "reconciled_count": len(reconciled),
            "reconciled_documents": reconciled,
            "stale_after_seconds": self.stale_after_seconds,
        }

    def status_batch(self, doc_ids: list[str]) -> dict[str, Any]:
        reconciliation = self.reconcile_stale_processing()
        documents: list[dict[str, Any]] = []
        missing_doc_ids: list[str] = []
        for doc_id in doc_ids:
            document = self.metadata_store.get_document(doc_id)
            if document is None:
                missing_doc_ids.append(doc_id)
                continue
            documents.append(self.document_status_payload(document))
        return {
            "documents": documents,
            "missing_doc_ids": missing_doc_ids,
            "reconciliation": reconciliation,
            "worker_health": self.worker_health(),
        }

    def worker_health(self, *, now: datetime | None = None) -> dict[str, Any]:
        current_time = now or datetime.now()
        processing_ages = [
            age
            for document in self.metadata_store.list_documents()
            if (age := self._processing_age_seconds(document, current_time)) is not None
        ]
        stale_count = sum(age >= self.stale_after_seconds for age in processing_ages)
        queue_health = self._queue_health()
        return {
            **queue_health,
            "stale_processing_count": stale_count,
            "oldest_processing_age_seconds": max(processing_ages) if processing_ages else 0,
            "stale_after_seconds": self.stale_after_seconds,
        }

    def document_status_payload(self, document: DocumentRecord) -> dict[str, Any]:
        confirmed_at = document.status_confirmed_at
        return {
            "doc_id": document.doc_id,
            "kb_id": document.kb_id,
            "filename": document.file_name,
            "file_name": document.file_name,
            "parser_engine": document.parser_engine.value,
            "status": document.status.value,
            "status_detail": document.status_detail,
            "status_source": document.status_source,
            "status_evidence": document.status_evidence,
            "status_confirmed_at": confirmed_at.isoformat() if confirmed_at else None,
            "error_message": document.error_message,
            "artifact_dir": document.artifact_dir,
            "updated_at": document.updated_at.isoformat() if document.updated_at else None,
        }

    def _queue_health(self) -> dict[str, Any]:
        health = getattr(self.processing_queue, "health", None)
        if not callable(health):
            return {
                "queue_enabled": False,
                "redis_connected": False,
                "worker_seen_recently": "unknown",
                "failed_job_count": "unknown",
            }
        return dict(health())

    def _processing_age_seconds(
        self,
        document: DocumentRecord,
        now: datetime,
    ) -> int | None:
        if document.status not in PROCESSING_STATUSES:
            return None
        started_at = document.status_confirmed_at or document.updated_at or document.created_at
        if started_at is None:
            return None
        return max(int((now - started_at).total_seconds()), 0)

    def _stale_failure_status(self, status: DocumentStatus) -> DocumentStatus | None:
        if status in PARSE_PROCESSING_STATUSES:
            return DocumentStatus.PARSE_FAILED
        if status in INDEX_PROCESSING_STATUSES:
            return DocumentStatus.INDEX_FAILED
        return None

    def _stale_evidence(
        self,
        document: DocumentRecord,
        age_seconds: int,
    ) -> dict[str, Any]:
        status_evidence = document.status_evidence or {}
        job_id = (
            status_evidence.get("processing_job_id")
            or status_evidence.get("job_id")
            or ""
        )
        error_message = (
            f"document_processing_stale: {document.status.value} exceeded "
            f"{self.stale_after_seconds}s"
        )
        return {
            "doc_id": document.doc_id,
            "previous_status": document.status.value,
            "processing_age_seconds": age_seconds,
            "stale_after_seconds": self.stale_after_seconds,
            "job_id": job_id,
            "processing_queue": status_evidence.get("processing_queue", ""),
            "error_code": "document_processing_stale",
            "error_message": error_message,
        }


def build_document_processing_workflow() -> DocumentProcessingWorkflow:
    return DocumentProcessingWorkflow()


document_processing_workflow = DocumentProcessingWorkflow()
