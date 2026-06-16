"""RQ-backed queue for deferred document parsing and indexing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger

from app.config import config


@dataclass(frozen=True)
class DocumentProcessingJobRef:
    """Small public reference returned after a document processing job is queued."""

    job_id: str
    queue_name: str
    doc_id: str


@dataclass(frozen=True)
class DirectoryIndexBatchJobRef:
    """Reference returned after a directory indexing batch is queued."""

    job_id: str
    queue_name: str
    directory_path: str
    kb_id: str


def process_deferred_document_job(doc_id: str) -> dict[str, str]:
    """Worker entrypoint: parse a deferred document, then index it when ready."""

    from app.services.document_processing_workflow import build_document_processing_workflow

    logger.info("开始处理异步文档任务: doc_id={}", doc_id)
    latest = build_document_processing_workflow().process_deferred_document(doc_id)
    logger.info("异步文档任务完成: doc_id={}, status={}", doc_id, latest.status.value)
    return {
        "doc_id": latest.doc_id,
        "status": latest.status.value,
        "parser_engine": latest.parser_engine.value,
    }


def process_directory_index_batch_job(directory_path: str, kb_id: str) -> dict[str, Any]:
    """Worker entrypoint: delegate directory submission to the ingestion layer."""

    from app.services.document_ingestion_service import document_ingestion_service

    logger.info("开始处理目录批量索引任务: directory={}, kb_id={}", directory_path, kb_id)
    result = document_ingestion_service.ingest_directory(directory_path, kb_id=kb_id)
    payload = result.to_dict()
    logger.info(
        "目录批量索引任务完成: directory={}, kb_id={}, success={}, total={}",
        directory_path,
        kb_id,
        payload["success"],
        payload["total_files"],
    )
    return payload


QueueFactory = Callable[[], Any]


class DocumentProcessingQueue:
    """Thin RQ adapter kept outside ingestion so queue mechanics stay contained."""

    def __init__(
        self,
        redis_url: str | None = None,
        queue_name: str | None = None,
        job_timeout_seconds: int | None = None,
        result_ttl_seconds: int | None = None,
        failure_ttl_seconds: int | None = None,
        queue_factory: QueueFactory | None = None,
    ):
        self.redis_url = redis_url or config.document_processing_redis_url
        self.queue_name = queue_name or config.document_processing_queue_name
        self.job_timeout_seconds = (
            job_timeout_seconds or config.document_processing_job_timeout_seconds
        )
        self.result_ttl_seconds = (
            result_ttl_seconds or config.document_processing_result_ttl_seconds
        )
        self.failure_ttl_seconds = (
            failure_ttl_seconds or config.document_processing_failure_ttl_seconds
        )
        self._queue_factory = queue_factory or self._build_rq_queue

    def enqueue_deferred_document(self, doc_id: str) -> DocumentProcessingJobRef:
        if not doc_id or not doc_id.strip():
            raise ValueError("doc_id 不能为空")

        queue = self._queue_factory()
        job = queue.enqueue(
            process_deferred_document_job,
            doc_id,
            job_timeout=self.job_timeout_seconds,
            result_ttl=self.result_ttl_seconds,
            failure_ttl=self.failure_ttl_seconds,
            meta={"doc_id": doc_id},
        )
        logger.info(
            "已投递异步文档处理任务: doc_id={}, queue={}, job_id={}",
            doc_id,
            self.queue_name,
            job.id,
        )
        return DocumentProcessingJobRef(
            job_id=str(job.id),
            queue_name=self.queue_name,
            doc_id=doc_id,
        )

    def enqueue_directory_index_batch(
        self,
        directory_path: str,
        kb_id: str,
    ) -> DirectoryIndexBatchJobRef:
        if not directory_path or not str(directory_path).strip():
            raise ValueError("directory_path 不能为空")
        if kb_id is None or not str(kb_id).strip():
            raise ValueError("kb_id 不能为空")

        queue = self._queue_factory()
        job = queue.enqueue(
            process_directory_index_batch_job,
            str(directory_path),
            str(kb_id).strip(),
            job_timeout=self.job_timeout_seconds,
            result_ttl=self.result_ttl_seconds,
            failure_ttl=self.failure_ttl_seconds,
            meta={
                "job_type": "directory_index_batch",
                "directory_path": str(directory_path),
                "kb_id": str(kb_id).strip(),
            },
        )
        logger.info(
            "已投递目录批量索引任务: directory={}, kb_id={}, queue={}, job_id={}",
            directory_path,
            kb_id,
            self.queue_name,
            job.id,
        )
        return DirectoryIndexBatchJobRef(
            job_id=str(job.id),
            queue_name=self.queue_name,
            directory_path=str(directory_path),
            kb_id=str(kb_id).strip(),
        )

    def _build_rq_queue(self):
        try:
            from redis import Redis
            from rq import Queue
        except ImportError as exc:
            raise RuntimeError(
                "缺少 RQ/Redis 依赖，请先安装项目依赖后再启用异步文档队列"
            ) from exc

        redis_conn = Redis.from_url(self.redis_url)
        return Queue(self.queue_name, connection=redis_conn)

    def health(self) -> dict[str, Any]:
        try:
            from redis import Redis
            from rq.registry import FailedJobRegistry
        except ImportError as exc:
            return {
                "queue_enabled": False,
                "redis_connected": False,
                "worker_seen_recently": "unknown",
                "failed_job_count": "unknown",
                "queue_name": self.queue_name,
                "error": str(exc),
            }

        redis_conn = Redis.from_url(self.redis_url)
        try:
            redis_conn.ping()
        except Exception as exc:
            return {
                "queue_enabled": True,
                "redis_connected": False,
                "worker_seen_recently": "unknown",
                "failed_job_count": "unknown",
                "queue_name": self.queue_name,
                "error": str(exc),
            }

        failed_count: int | str = "unknown"
        try:
            failed_count = FailedJobRegistry(
                self.queue_name,
                connection=redis_conn,
            ).count
        except Exception:
            failed_count = "unknown"

        return {
            "queue_enabled": True,
            "redis_connected": True,
            "worker_seen_recently": "unknown",
            "failed_job_count": failed_count,
            "queue_name": self.queue_name,
        }


document_processing_queue = DocumentProcessingQueue()
