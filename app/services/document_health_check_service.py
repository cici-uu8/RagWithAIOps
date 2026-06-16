"""Document-level post-index health diagnostics for the file manager."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

import app.services.retrieval_service as retrieval_module
from app.models import DocumentRecord, DocumentStatus, RetrievalQuery
from app.services.knowledge_metadata_store import KnowledgeMetadataStore, knowledge_metadata_store
from app.services.retrieval_service import RetrievalService


class DocumentHealthStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"
    SKIPPED = "skipped"


class DocumentHealthCheckResult(BaseModel):
    doc_id: str
    kb_id: str = ""
    status: DocumentHealthStatus
    summary: str
    retrieval: dict[str, Any] = Field(default_factory=dict)
    source_ref: dict[str, Any] = Field(default_factory=dict)
    pdf: dict[str, Any] = Field(default_factory=dict)
    checked_at: datetime | None = None
    marked_as_false_positive: bool = False
    false_positive_reason: str = ""

    def summary_payload(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "summary": self.summary,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
            "marked_as_false_positive": self.marked_as_false_positive,
            "false_positive_reason": self.false_positive_reason,
        }


class DocumentHealthCheckStore:
    """Persist document health results next to knowledge metadata."""

    def __init__(self, store_path: str | Path = "./uploads/_metadata/document_health_checks.json"):
        self.store_path = Path(store_path).resolve()
        self._lock = RLock()
        self._results: dict[str, DocumentHealthCheckResult] = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not self.store_path.exists():
                return
            raw = json.loads(self.store_path.read_text(encoding="utf-8"))
            self._results = {
                doc_id: DocumentHealthCheckResult.model_validate(payload)
                for doc_id, payload in raw.get("results", {}).items()
            }

    def _save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "results": {
                doc_id: result.model_dump(mode="json")
                for doc_id, result in self._results.items()
            }
        }
        self.store_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get(self, doc_id: str) -> DocumentHealthCheckResult | None:
        with self._lock:
            result = self._results.get(doc_id)
            return result.model_copy(deep=True) if result else None

    def upsert(self, result: DocumentHealthCheckResult) -> DocumentHealthCheckResult:
        with self._lock:
            self._results[result.doc_id] = result
            self._save()
            return result.model_copy(deep=True)

    def mark_pending(self, document: DocumentRecord) -> DocumentHealthCheckResult:
        return self.upsert(
            DocumentHealthCheckResult(
                doc_id=document.doc_id,
                kb_id=document.kb_id,
                status=DocumentHealthStatus.PENDING,
                summary="health_check_pending",
            )
        )

    def mark_skipped(
        self,
        doc_id: str,
        *,
        kb_id: str = "",
        reason: str,
    ) -> DocumentHealthCheckResult:
        existing = self.get(doc_id)
        return self.upsert(
            DocumentHealthCheckResult(
                doc_id=doc_id,
                kb_id=kb_id or existing.kb_id if existing else kb_id,
                status=DocumentHealthStatus.SKIPPED,
                summary=reason,
                retrieval={"passed": False, "skipped": reason, "queries": []},
                source_ref={"passed": False, "skipped": reason, "errors": []},
                pdf={"passed": False, "skipped": reason, "errors": []},
                checked_at=datetime.now(),
                marked_as_false_positive=existing.marked_as_false_positive if existing else False,
                false_positive_reason=existing.false_positive_reason if existing else "",
            )
        )

    def mark_false_positive(self, doc_id: str, reason: str) -> DocumentHealthCheckResult:
        existing = self.get(doc_id)
        if existing is None:
            existing = DocumentHealthCheckResult(
                doc_id=doc_id,
                status=DocumentHealthStatus.SKIPPED,
                summary="manual_false_positive_without_result",
                checked_at=datetime.now(),
            )
        updated = existing.model_copy(
            update={
                "marked_as_false_positive": True,
                "false_positive_reason": reason.strip(),
            }
        )
        return self.upsert(updated)

    def summary_for_document(self, document: DocumentRecord) -> dict[str, Any]:
        result = self.get(document.doc_id)
        if result is not None:
            return result.summary_payload()
        if document.status == DocumentStatus.INDEXED:
            return DocumentHealthCheckResult(
                doc_id=document.doc_id,
                kb_id=document.kb_id,
                status=DocumentHealthStatus.PENDING,
                summary="health_check_pending",
            ).summary_payload()
        return DocumentHealthCheckResult(
            doc_id=document.doc_id,
            kb_id=document.kb_id,
            status=DocumentHealthStatus.PENDING,
            summary="waiting_for_indexed_status",
        ).summary_payload()


class DocumentHealthCheckService:
    """Run deterministic post-index diagnostics for a single document."""

    def __init__(
        self,
        *,
        metadata_store: KnowledgeMetadataStore | None = None,
        health_store: DocumentHealthCheckStore | None = None,
        retrieval_service: RetrievalService | None = None,
    ):
        self.metadata_store = metadata_store or knowledge_metadata_store
        self.health_store = health_store or document_health_check_store
        self.retrieval_service = retrieval_service or retrieval_module.retrieval_service

    def run_check(self, doc_id: str) -> DocumentHealthCheckResult:
        document = self.metadata_store.get_document(doc_id)
        if document is None:
            return self.health_store.mark_skipped(
                doc_id,
                reason="document_not_found",
            )
        if document.status != DocumentStatus.INDEXED:
            return self.health_store.upsert(
                DocumentHealthCheckResult(
                    doc_id=document.doc_id,
                    kb_id=document.kb_id,
                    status=DocumentHealthStatus.PENDING,
                    summary="waiting_for_indexed_status",
                )
            )

        chunks = self.metadata_store.list_chunks_by_doc_id(doc_id)
        queries = self._generate_queries(document, chunks)
        retrieval_result = self._test_retrieval(document, queries)
        source_ref_result = self._test_source_ref(document, chunks)
        pdf_result = self._test_pdf(document)

        status, summary = self._summarize(
            retrieval_result=retrieval_result,
            source_ref_result=source_ref_result,
            pdf_result=pdf_result,
        )
        result = DocumentHealthCheckResult(
            doc_id=document.doc_id,
            kb_id=document.kb_id,
            status=status,
            summary=summary,
            retrieval=retrieval_result,
            source_ref=source_ref_result,
            pdf=pdf_result,
            checked_at=datetime.now(),
        )
        return self.health_store.upsert(result)

    def mark_false_positive(self, doc_id: str, reason: str) -> DocumentHealthCheckResult:
        return self.health_store.mark_false_positive(doc_id, reason)

    def _generate_queries(self, document: DocumentRecord, chunks: list[Any]) -> list[str]:
        queries: list[str] = []
        stem = Path(document.file_name).stem
        file_query = re.sub(r"[_\-.]+", " ", stem).strip()
        if file_query:
            queries.append(file_query)

        for chunk in chunks[:2]:
            words = re.findall(r"[\w\u4e00-\u9fff]+", chunk.content)
            if words:
                queries.append(" ".join(words[:5]))

        seen: set[str] = set()
        deduped: list[str] = []
        for query in queries:
            normalized = query.strip()
            if not normalized or normalized.lower() in seen:
                continue
            seen.add(normalized.lower())
            deduped.append(normalized)
        return deduped[:3]

    def _test_retrieval(self, document: DocumentRecord, queries: list[str]) -> dict[str, Any]:
        if not queries:
            return {
                "passed": False,
                "reason": "retrieval_no_queries",
                "queries": [],
            }

        query_results: list[dict[str, Any]] = []
        for query_text in queries:
            try:
                response = self.retrieval_service.retrieve(
                    RetrievalQuery(
                        query=query_text,
                        top_k=3,
                        knowledge_base_ids=[document.kb_id],
                    )
                )
            except Exception as exc:
                query_results.append(
                    {
                        "query": query_text,
                        "hit": False,
                        "rank": None,
                        "top_doc_ids": [],
                        "error": type(exc).__name__,
                    }
                )
                continue

            top_doc_ids = [result.doc_id for result in response.results[:3]]
            rank = next(
                (
                    index + 1
                    for index, result in enumerate(response.results[:3])
                    if result.doc_id == document.doc_id
                ),
                None,
            )
            query_results.append(
                {
                    "query": query_text,
                    "hit": rank is not None,
                    "rank": rank,
                    "top_doc_ids": top_doc_ids,
                }
            )

        return {
            "passed": any(item["hit"] for item in query_results),
            "queries": query_results,
        }

    def _test_source_ref(self, document: DocumentRecord, chunks: list[Any]) -> dict[str, Any]:
        errors: list[str] = []
        if not chunks:
            errors.append("source_ref_no_chunks")

        for chunk in chunks:
            source_ref = getattr(chunk, "source_ref", None)
            if source_ref is None:
                errors.append(f"source_ref_missing:{chunk.chunk_id}")
                continue
            if chunk.doc_id != document.doc_id:
                errors.append(f"chunk_doc_id_mismatch:{chunk.chunk_id}")
            if chunk.kb_id != document.kb_id:
                errors.append(f"chunk_kb_id_mismatch:{chunk.chunk_id}")
            if source_ref.doc_id != document.doc_id:
                errors.append(f"source_ref_doc_id_mismatch:{chunk.chunk_id}")
            if source_ref.kb_id != document.kb_id:
                errors.append(f"source_ref_kb_id_mismatch:{chunk.chunk_id}")
            if source_ref.chunk_id != chunk.chunk_id:
                errors.append(f"source_ref_chunk_id_mismatch:{chunk.chunk_id}")
            if not source_ref.source_file:
                errors.append(f"source_ref_missing_source_file:{chunk.chunk_id}")

        return {
            "passed": not errors,
            "errors": errors[:20],
            "checked_chunk_count": len(chunks),
        }

    def _test_pdf(self, document: DocumentRecord) -> dict[str, Any]:
        if document.file_ext.lower() != "pdf":
            return {
                "passed": True,
                "skipped": "not a PDF",
                "errors": [],
            }

        artifact_dir = Path(document.artifact_dir)
        manifest_path = artifact_dir / "artifact_manifest.json"
        errors: list[str] = []
        if not manifest_path.exists():
            return {
                "passed": False,
                "errors": ["pdf_artifact_missing_manifest"],
                "artifact_dir": artifact_dir.as_posix(),
            }

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return {
                "passed": False,
                "errors": ["pdf_artifact_invalid_manifest_json"],
                "artifact_dir": artifact_dir.as_posix(),
            }

        required_files = manifest.get("required_files") if isinstance(manifest, dict) else {}
        blocks_relative = required_files.get("blocks_json", "blocks.json") if isinstance(required_files, dict) else "blocks.json"
        blocks_path = artifact_dir / blocks_relative
        if not blocks_path.exists():
            errors.append("pdf_artifact_missing_blocks_json")
        else:
            try:
                blocks = json.loads(blocks_path.read_text(encoding="utf-8"))
                if not isinstance(blocks, list) or not blocks:
                    errors.append("pdf_artifact_empty_blocks_json")
            except Exception:
                errors.append("pdf_artifact_invalid_blocks_json")

        tables_relative = required_files.get("tables_json") if isinstance(required_files, dict) else None
        if tables_relative:
            tables_path = artifact_dir / tables_relative
            if tables_path.exists():
                try:
                    tables = json.loads(tables_path.read_text(encoding="utf-8"))
                    if not isinstance(tables, list):
                        errors.append("pdf_artifact_invalid_tables_json_shape")
                except Exception:
                    errors.append("pdf_artifact_invalid_tables_json")

        return {
            "passed": not errors,
            "errors": errors,
            "artifact_dir": artifact_dir.as_posix(),
        }

    def _summarize(
        self,
        *,
        retrieval_result: dict[str, Any],
        source_ref_result: dict[str, Any],
        pdf_result: dict[str, Any],
    ) -> tuple[DocumentHealthStatus, str]:
        reasons: list[str] = []
        if not retrieval_result.get("passed"):
            reasons.append("retrieval_no_hit")
        if not source_ref_result.get("passed"):
            reasons.append("source_ref_error")
        if not pdf_result.get("passed"):
            reasons.append("pdf_artifact_error")

        if not reasons:
            return DocumentHealthStatus.PASSED, "all diagnostics passed"
        return DocumentHealthStatus.FAILED, ",".join(reasons)


class DocumentHealthCheckQueue:
    """Bounded background queue for non-blocking post-index diagnostics."""

    def __init__(
        self,
        *,
        health_check_service: DocumentHealthCheckService | None = None,
        health_store: DocumentHealthCheckStore | None = None,
        max_queue_size: int = 100,
        max_concurrent: int = 10,
        run_inline: bool = False,
    ):
        self.health_check_service = health_check_service or document_health_check_service
        self.health_store = health_store or self.health_check_service.health_store
        self.max_queue_size = max_queue_size
        self.max_concurrent = max(max_concurrent, 1)
        self.run_inline = run_inline
        self._lock = RLock()
        self._pending_doc_ids: set[str] = set()
        self._running_doc_ids: set[str] = set()
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_concurrent,
            thread_name_prefix="document-health",
        )

    def enqueue(self, doc_id: str) -> bool:
        try:
            document = self.health_check_service.metadata_store.get_document(doc_id)
            kb_id = document.kb_id if document else ""
            with self._lock:
                outstanding = len(self._pending_doc_ids) + len(self._running_doc_ids)
                if outstanding >= self.max_queue_size:
                    self.health_store.mark_skipped(
                        doc_id,
                        kb_id=kb_id,
                        reason="queue_full",
                    )
                    return False
                if doc_id in self._pending_doc_ids or doc_id in self._running_doc_ids:
                    return True
                self._pending_doc_ids.add(doc_id)

            if document is not None:
                self.health_store.mark_pending(document)

            if self.run_inline:
                self._run(doc_id)
            else:
                self._executor.submit(self._run, doc_id)
            return True
        except Exception as exc:  # pragma: no cover - defensive non-blocking boundary
            logger.warning("文档健康检查入队失败: doc_id={}, 错误={}", doc_id, exc)
            return False

    def _run(self, doc_id: str) -> None:
        with self._lock:
            self._pending_doc_ids.discard(doc_id)
            self._running_doc_ids.add(doc_id)
        try:
            self.health_check_service.run_check(doc_id)
        except Exception as exc:
            logger.warning("文档健康检查执行失败: doc_id={}, 错误={}", doc_id, exc)
            document = self.health_check_service.metadata_store.get_document(doc_id)
            self.health_store.upsert(
                DocumentHealthCheckResult(
                    doc_id=doc_id,
                    kb_id=document.kb_id if document else "",
                    status=DocumentHealthStatus.FAILED,
                    summary=f"health_check_exception:{type(exc).__name__}",
                    retrieval={"passed": False, "queries": [], "error": str(exc)},
                    source_ref={"passed": False, "errors": []},
                    pdf={"passed": False, "errors": []},
                    checked_at=datetime.now(),
                )
            )
        finally:
            with self._lock:
                self._running_doc_ids.discard(doc_id)


document_health_check_store = DocumentHealthCheckStore()
document_health_check_service = DocumentHealthCheckService(
    health_store=document_health_check_store,
)
document_health_check_queue = DocumentHealthCheckQueue(
    health_check_service=document_health_check_service,
    health_store=document_health_check_store,
)
