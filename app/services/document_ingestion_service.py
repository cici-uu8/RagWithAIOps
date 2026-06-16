"""正式文档接入流程"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from loguru import logger

from app.enterprise.storage.service import LocalStorageService
from app.models import DirectoryIngestionResult, DocumentRecord, DocumentStatus, ParserEngine
from app.services.artifact_chunk_builder_service import artifact_chunk_builder_service
from app.services.artifact_manifest_service import artifact_manifest_service
from app.services.document_processing_queue import document_processing_queue
from app.services.knowledge_metadata_store import knowledge_metadata_store
from app.services.mineru_parser_adapter import mineru_parser_adapter
from app.services.parser_engine_router import parser_engine_router
from app.services.pdf_profile_service import pdf_profile_service
from app.services.vector_index_service import vector_index_service


class DocumentIngestionService:
    """保存原始文件，创建文档记录，路由解析器，并触发索引."""

    def __init__(self, upload_root: str | Path = "./uploads", storage_service=None):
        self.upload_root = Path(upload_root)
        self.storage_service = storage_service or LocalStorageService(self.upload_root)

    def ingest_upload(self, filename: str, content: bytes, kb_id: str) -> DocumentRecord:
        """上传文件的处理逻辑"""
        kb = self._validate_kb_id(kb_id)
        safe_filename = self._sanitize_filename(filename)
        file_ext = self._get_file_extension(safe_filename)
        parser_engine = parser_engine_router.resolve(file_ext)
        doc_id = self._build_uploaded_doc_id(kb, safe_filename, content)

        original_relative_path = self._build_original_relative_path(kb, doc_id, safe_filename)
        artifact_relative_dir = self._build_artifact_relative_dir(kb, doc_id)
        stored_original = self.storage_service.save_bytes(
            relative_path=original_relative_path,
            content=content,
        )
        artifact_dir = Path(self.storage_service.ensure_directory(artifact_relative_dir))
        original_path = Path(stored_original.local_path)
        document_record = self._build_document_record(
            kb_id=kb,
            doc_id=doc_id,
            file_name=safe_filename,
            original_path=original_path,
            artifact_dir=artifact_dir,
            parser_engine=parser_engine,
            file_size=len(content),
            storage_uri=stored_original.storage_uri,
            storage_provider=stored_original.provider,
        )
        document_record = self._attach_pdf_profile(document_record, file_size=len(content))

        knowledge_metadata_store.upsert_document(document_record)

        logger.info(
            "文档已进入正式接入链路: doc_id={}, parser_engine={}, original_path={}",
            doc_id,
            parser_engine,
            original_path,
        )

        if parser_engine == ParserEngine.PLAIN_TEXT:
            return self._ingest_plain_text_document(document_record)

        try:
            processing_job = document_processing_queue.enqueue_deferred_document(doc_id)
        except Exception as exc:
            knowledge_metadata_store.transition_document_status(
                doc_id,
                DocumentStatus.ENQUEUE_FAILED,
                status_source="DocumentIngestionService.ingest_upload",
                status_detail="无法加入异步解析任务",
                status_evidence={
                    "doc_id": doc_id,
                    "parser_engine": parser_engine.value,
                    "original_path": original_path.as_posix(),
                    "artifact_dir": artifact_dir.as_posix(),
                    "storage_uri": stored_original.storage_uri,
                    "queue_name": getattr(document_processing_queue, "queue_name", ""),
                    "error_type": type(exc).__name__,
                },
                error_message=str(exc),
            )
            logger.error("文档异步任务投递失败: doc_id={}, 错误={}", doc_id, exc)
            raise

        queued_record = knowledge_metadata_store.transition_document_status(
            doc_id,
            DocumentStatus.PARSE_PENDING,
            status_source="DocumentIngestionService.ingest_upload",
            status_detail="非纯文本文件已上传，等待异步解析任务执行",
            status_evidence={
                "doc_id": doc_id,
                "parser_engine": parser_engine.value,
                "original_path": original_path.as_posix(),
                "artifact_dir": artifact_dir.as_posix(),
                "storage_uri": stored_original.storage_uri,
                "processing_job_id": processing_job.job_id,
                "processing_queue": processing_job.queue_name,
                "enqueued_at": datetime.now().isoformat(),
            },
        )
        if queued_record is None:
            raise ValueError(f"文档不存在: {doc_id}")
        return queued_record

    def ingest_directory(
        self,
        directory_path: str | Path | None = None,
        *,
        kb_id: str,
        recursive: bool = True,
    ) -> DirectoryIngestionResult:
        """Scan a directory and submit every supported file through ingest_upload()."""
        result = DirectoryIngestionResult()
        result.start_time = datetime.now()
        result.recursive = recursive

        try:
            result.kb_id = self._validate_kb_id(kb_id)
            target_path = Path(directory_path) if directory_path else self.upload_root
            dir_path = target_path.resolve()

            if not dir_path.exists() or not dir_path.is_dir():
                raise ValueError(f"目录不存在或不是有效目录: {target_path}")

            result.directory_path = str(dir_path)
            iterator = dir_path.rglob("*") if recursive else dir_path.iterdir()
            files = sorted(
                path
                for path in iterator
                if path.is_file() and parser_engine_router.supports_path(path)
            )

            if not files:
                logger.warning("目录中没有找到支持的文件: {}", target_path)
                result.success = True
                result.end_time = datetime.now()
                return result

            result.total_files = len(files)
            logger.info("开始接入目录: {}, 找到 {} 个文件", target_path, len(files))

            for file_path in files:
                try:
                    document_record = self.ingest_upload(
                        filename=file_path.name,
                        content=file_path.read_bytes(),
                        kb_id=result.kb_id,
                    )
                    result.increment_success_count()
                    result.document_ids.append(document_record.doc_id)
                    if document_record.status == DocumentStatus.PARSE_PENDING:
                        result.queued_count += 1
                    logger.info(
                        "文件已进入统一接入链路: {}, doc_id={}, status={}",
                        file_path.name,
                        document_record.doc_id,
                        document_record.status.value,
                    )
                except Exception as exc:
                    result.increment_fail_count()
                    result.add_failed_file(str(file_path), str(exc))
                    logger.error("文件接入失败: {}, 错误={}", file_path, exc)

            result.success = result.fail_count == 0
            result.end_time = datetime.now()
            logger.info(
                "目录接入完成: total={}, success={}, queued={}, failed={}",
                result.total_files,
                result.success_count,
                result.queued_count,
                result.fail_count,
            )
            return result
        except Exception as exc:
            logger.error("目录接入失败: {}", exc)
            result.success = False
            result.error_message = str(exc)
            result.end_time = datetime.now()
            return result

    def _ingest_plain_text_document(self, document_record: DocumentRecord) -> DocumentRecord:
        try:
            knowledge_metadata_store.upsert_document(document_record)
            parse_pending_record = knowledge_metadata_store.transition_document_status(
                document_record.doc_id,
                DocumentStatus.PARSE_PENDING,
                status_source="DocumentIngestionService._ingest_plain_text_document",
                status_detail="纯文本文档已准备就绪，可直接进入索引流程",
                status_evidence={
                    "parser_engine": document_record.parser_engine.value,
                    "original_path": document_record.original_path,
                    "artifact_dir": document_record.artifact_dir,
                    "storage_uri": document_record.metadata.get("storage_uri", ""),
                },
            )
            if parse_pending_record is None:
                raise ValueError(f"文档不存在: {document_record.doc_id}")

            # plain_text 没有独立 parser 阶段，这里直接交给索引服务推进
            # INDEX_PENDING -> INDEXING -> INDEXED，避免把“未实际发生的解析完成”写成状态。
            vector_index_service.index_document_record(parse_pending_record)
            latest = knowledge_metadata_store.get_document(parse_pending_record.doc_id)
            return latest or parse_pending_record
        except Exception as exc:
            logger.error("Plain-text 文档接入失败: doc_id={}, 错误={}", document_record.doc_id, exc)
            latest = knowledge_metadata_store.get_document(document_record.doc_id)
            if latest is not None:
                return latest
            now = datetime.now()
            return document_record.model_copy(
                update={
                    "status": DocumentStatus.PARSE_FAILED,
                    "status_source": "DocumentIngestionService._ingest_plain_text_document",
                    "status_detail": "纯文本文档接入失败，元数据存储无法确认持久化状态",
                    "status_evidence": {
                        "doc_id": document_record.doc_id,
                        "error_type": type(exc).__name__,
                    },
                    "status_confirmed_at": now,
                    "error_message": str(exc),
                    "updated_at": now,
                }
            )

    def process_deferred_document(self, doc_id: str) -> DocumentRecord:
        document_record = knowledge_metadata_store.get_document(doc_id)
        if document_record is None:
            raise ValueError(f"文档不存在: {doc_id}")

        if document_record.parser_engine == ParserEngine.PLAIN_TEXT:
            return self._ingest_plain_text_document(document_record)

        if document_record.parser_engine == ParserEngine.MINERU:
            return mineru_parser_adapter.parse_document(document_record)

        raise ValueError(f"不支持的 parser_engine: {document_record.parser_engine.value}")

    def validate_artifacts_for_index(self, doc_id: str):
        document_record = knowledge_metadata_store.get_document(doc_id)
        if document_record is None:
            raise ValueError(f"文档不存在: {doc_id}")

        if document_record.status not in {DocumentStatus.PARSED, DocumentStatus.INDEX_PENDING, DocumentStatus.INDEXING, DocumentStatus.INDEXED}:
            raise ValueError(f"文档状态不允许进入索引校验: {document_record.status.value}")

        return artifact_manifest_service.validate_manifest(document_record.artifact_dir)

    def prepare_artifacts_for_index(self, doc_id: str):
        """验证解析后的产物，并将其转换为可直接用于索引的分片数据。

        失败会被记录为 index_failed 状态，并重新抛出异常，
        以便调用方决定是否重试、上报或终止索引工作流。
        """
        try:
            document_record = knowledge_metadata_store.get_document(doc_id)
            if document_record is None:
                raise ValueError(f"文档不存在: {doc_id}")

            manifest = self.validate_artifacts_for_index(doc_id)
            return artifact_chunk_builder_service.prepare(document_record, manifest)
        except Exception as exc:
            knowledge_metadata_store.transition_document_status(
                doc_id,
                DocumentStatus.INDEX_FAILED,
                error_message=str(exc),
                status_source="DocumentIngestionService.prepare_artifacts_for_index",
                status_detail="解析后的产物验证或分片适配失败",
                status_evidence={
                    "doc_id": doc_id,
                    "operation": "prepare_artifacts_for_index",
                    "error_type": type(exc).__name__,
                },
            )
            logger.error("artifact 索引准备失败: doc_id={}, 错误={}", doc_id, exc)
            raise

    def _build_uploaded_doc_id(self, kb_id: str, safe_filename: str, content: bytes) -> str:
        content_hash = hashlib.sha1(content).hexdigest()
        stable_seed = f"{kb_id}:{safe_filename}:{content_hash}"
        return f"doc_{uuid5(NAMESPACE_URL, stable_seed)}"

    def _validate_kb_id(self, kb_id: str) -> str:
        if kb_id is None or not str(kb_id).strip():
            raise ValueError("知识库 ID 为必填项，不能为空、空值或空白字符")
        return str(kb_id).strip()

    def _build_original_path(self, kb_id: str, doc_id: str, safe_filename: str) -> Path:
        return (self.upload_root / "documents" / kb_id / doc_id / "original" / safe_filename).resolve()

    def _build_artifact_dir(self, kb_id: str, doc_id: str) -> Path:
        return (self.upload_root / "documents" / kb_id / doc_id / "artifacts").resolve()

    def _build_original_relative_path(self, kb_id: str, doc_id: str, safe_filename: str) -> str:
        return f"documents/{kb_id}/{doc_id}/original/{safe_filename}"

    def _build_artifact_relative_dir(self, kb_id: str, doc_id: str) -> str:
        return f"documents/{kb_id}/{doc_id}/artifacts"

    def _build_document_record(
        self,
        kb_id: str,
        doc_id: str,
        file_name: str,
        original_path: Path,
        artifact_dir: Path,
        parser_engine: ParserEngine,
        file_size: int,
        storage_uri: str,
        storage_provider: str,
    ) -> DocumentRecord:
        now = datetime.now()
        return DocumentRecord(
            doc_id=doc_id,
            kb_id=kb_id,
            file_name=file_name,
            file_ext=self._get_file_extension(file_name),
            original_path=original_path.as_posix(),
            artifact_dir=artifact_dir.as_posix(),
            parser_engine=parser_engine,
            status=DocumentStatus.UPLOADED,
            status_detail="在解析器路由继续执行前，已创建上传记录",
            status_source="DocumentIngestionService.ingest_upload",
            status_evidence={
                "file_name": file_name,
                "file_size": file_size,
                "parser_engine": parser_engine.value,
                "original_path": original_path.as_posix(),
                "artifact_dir": artifact_dir.as_posix(),
                "storage_uri": storage_uri,
                "storage_provider": storage_provider,
            },
            status_confirmed_at=now,
            error_message="",
            metadata={
                "legacy_path": False,
                "upload_origin": "api",
                "file_size": file_size,
                "storage_uri": storage_uri,
                "storage_provider": storage_provider,
            },
            created_at=now,
            updated_at=now,
        )

    def _attach_pdf_profile(self, document_record: DocumentRecord, *, file_size: int) -> DocumentRecord:
        if document_record.file_ext != "pdf":
            return document_record
        try:
            profile = pdf_profile_service.profile_pdf(document_record.original_path, file_size=file_size)
        except Exception as exc:
            logger.warning(
                "PDF profile 生成失败，继续上传流程: doc_id={}, error_type={}, error={}",
                document_record.doc_id,
                type(exc).__name__,
                exc,
            )
            profile = {
                "profile_status": "failed",
                "profile_version": "pdf_profile_v1",
                "risk_flags": ["profile_failed"],
                "file_size": file_size,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "generated_at": datetime.now().isoformat(),
            }
        metadata = {**document_record.metadata, "pdf_profile": profile}
        return document_record.model_copy(update={"metadata": metadata, "updated_at": datetime.now()})

    def _get_file_extension(self, filename: str) -> str:
        parts = filename.rsplit(".", 1)
        if len(parts) == 2:
            return parts[1].lower()
        return ""

    def _sanitize_filename(self, filename: str) -> str:
        sanitized = filename.replace(" ", "_")
        for char in ['\\', '/', ':', '*', '?', '"', '<', '>', '|']:
            sanitized = sanitized.replace(char, "_")
        return sanitized


document_ingestion_service = DocumentIngestionService()
