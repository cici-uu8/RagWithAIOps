"""向量索引服务模块"""

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from langchain_core.documents import Document
from loguru import logger

from app.models import (
    ChunkRecord,
    DocumentRecord,
    DocumentStatus,
    ParserEngine,
    SourceRef,
)
from app.services.chunk_policy_service import chunk_policy_service
from app.services.document_splitter_service import document_splitter_service
from app.services.knowledge_metadata_store import knowledge_metadata_store
from app.services.parser_engine_router import parser_engine_router
from app.services.vector_store_manager import vector_store_manager


class VectorIndexService:
    """向量索引服务 - 负责读取文件、生成向量、存储到 Milvus"""

    def __init__(self):
        """初始化向量索引服务"""
        logger.info("向量索引服务初始化完成")

    def index_single_file(self, file_path: str, kb_id: str):
        """
        索引单个文件 (使用新的 LangChain 分割器)

        Args:
            file_path: 文件路径
            kb_id: 目标知识库 id，必须显式传入

        Raises:
            ValueError: 文件不存在时抛出
            RuntimeError: 索引失败时抛出
        """
        self._validate_kb_id(kb_id)
        kb_id = kb_id.strip()
        path = Path(file_path).resolve()

        if not path.exists() or not path.is_file():
            raise ValueError(f"文件不存在: {file_path}")

        logger.info(f"开始索引文件: {path}")

        try:
            doc_id = self._build_doc_id(kb_id, path)
            parser_engine = parser_engine_router.resolve_path(path)
            document_record = self._build_document_record(
                kb_id=kb_id,
                doc_id=doc_id,
                path=path,
                status=DocumentStatus.UPLOADED,
                parser_engine=parser_engine,
            )
            self.index_document_record(document_record)

        except Exception as e:
            if 'doc_id' in locals():
                knowledge_metadata_store.transition_document_status(
                    doc_id,
                    DocumentStatus.INDEX_FAILED,
                    status_source="VectorIndexService.index_single_file",
                    status_detail="legacy single-file indexing failed",
                    status_evidence={
                        "file_path": str(path),
                        "kb_id": kb_id,
                        "error_type": type(e).__name__,
                    },
                    error_message=str(e),
                )
            logger.error(f"索引文件失败: {file_path}, 错误: {e}")
            raise RuntimeError(f"索引文件失败: {e}") from e

    def index_document_record(self, document_record: DocumentRecord):
        """Index a document that has already entered the formal document lifecycle."""
        path = Path(document_record.original_path).resolve()

        try:
            if not path.exists() or not path.is_file():
                raise ValueError(f"文件不存在: {document_record.original_path}")

            if document_record.parser_engine == ParserEngine.MINERU:
                self._index_mineru_document_record(document_record)
                return

            if document_record.parser_engine != ParserEngine.PLAIN_TEXT:
                raise ValueError(f"不支持的 parser_engine: {document_record.parser_engine.value}")

            doc_id = document_record.doc_id
            knowledge_metadata_store.upsert_document(document_record)
            self._transition_document_status(
                doc_id,
                DocumentStatus.INDEX_PENDING,
                status_source="VectorIndexService.index_document_record",
                status_detail="plain-text document is confirmed for chunking before index write",
                status_evidence={
                    "parser_engine": document_record.parser_engine.value,
                    "original_path": path.as_posix(),
                },
            )

            # 1. 读取文件内容
            content = path.read_text(encoding="utf-8")
            logger.info(f"读取文件: {path}, 内容长度: {len(content)} 字符")

            # 3. 使用新的文档分割器
            normalized_path = path.as_posix()
            documents = document_splitter_service.split_document(content, normalized_path)
            logger.info(f"文档分割完成: {path} -> {len(documents)} 个分片")

            chunk_records = self._build_chunk_records(
                kb_id=document_record.kb_id,
                doc_id=doc_id,
                path=path,
                content=content,
                documents=documents,
                parser_engine=document_record.parser_engine,
            )

            # 统一 ChunkPolicy: 同 heading 合并、超长再拆、表格/公式不并入正文，
            # 同时聚合同一节内的多个文本子块为 section parent。
            policy_result = chunk_policy_service.apply_with_parents(chunk_records)
            chunk_records = policy_result.chunks
            parents = policy_result.parents
            documents = self._documents_from_chunk_records(chunk_records)

            self._transition_document_status(
                doc_id,
                DocumentStatus.INDEXING,
                status_source="VectorIndexService.index_document_record",
                status_detail="plain-text chunks were prepared and vector write is starting",
                status_evidence={
                    "child_chunk_count": len(chunk_records),
                    "parent_chunk_count": len(parents),
                    "vector_document_count": len(documents),
                    "original_path": path.as_posix(),
                },
            )
            # 4. 添加文档到向量存储
            if documents:
                self._write_vector_documents(document_record, documents)
                # parents 与 children 一同落 metadata store，
                # 但 parents 不写入 Milvus，避免 dense 召回稀释 top_k。
                knowledge_metadata_store.replace_chunks(doc_id, chunk_records + parents)
                self._transition_document_status(
                    doc_id,
                    DocumentStatus.INDEXED,
                    status_source="VectorIndexService.index_document_record",
                    status_detail="plain-text chunks and vector rows were written successfully",
                    status_evidence={
                        "child_chunk_count": len(chunk_records),
                        "parent_chunk_count": len(parents),
                        "vector_document_count": len(documents),
                        "original_path": path.as_posix(),
                    },
                )
                logger.info(
                    f"文件索引完成: {path}, 共 {len(documents)} 个子块, {len(parents)} 个父块"
                )
            else:
                self._cleanup_existing_document_data(document_record)
                self._transition_document_status(
                    doc_id,
                    DocumentStatus.INDEXED,
                    status_source="VectorIndexService.index_document_record",
                    status_detail="plain-text document produced no vector rows but indexing completed",
                    status_evidence={
                        "child_chunk_count": 0,
                        "parent_chunk_count": len(parents),
                        "vector_document_count": 0,
                        "original_path": path.as_posix(),
                    },
                )
                logger.warning(f"文件内容为空或无法分割: {path}")
        except Exception as e:
            knowledge_metadata_store.transition_document_status(
                document_record.doc_id,
                DocumentStatus.INDEX_FAILED,
                status_source="VectorIndexService.index_document_record",
                status_detail="document indexing failed before completion",
                status_evidence={
                    "parser_engine": document_record.parser_engine.value,
                    "original_path": document_record.original_path,
                    "error_type": type(e).__name__,
                },
                error_message=str(e),
            )
            logger.error(f"索引文档记录失败: doc_id={document_record.doc_id}, 错误: {e}")
            raise

    def _index_mineru_document_record(self, document_record: DocumentRecord) -> None:
        """Index a MinerU document from validated parsed artifacts."""
        from app.services.document_ingestion_service import DocumentIngestionService

        doc_id = document_record.doc_id
        knowledge_metadata_store.upsert_document(document_record)
        self._transition_document_status(
            doc_id,
            DocumentStatus.INDEXING,
            status_source="VectorIndexService._index_mineru_document_record",
            status_detail="MinerU document artifacts are entering validation before vector write",
            status_evidence={
                "parser_engine": document_record.parser_engine.value,
                "artifact_dir": document_record.artifact_dir,
                "original_path": document_record.original_path,
            },
        )

        prepared = DocumentIngestionService().prepare_artifacts_for_index(doc_id)
        # 统一 ChunkPolicy: 与 plain_text 路径共用最终边界规则。
        policy_result = chunk_policy_service.apply_with_parents(prepared.chunk_records)
        chunk_records = policy_result.chunks
        parents = policy_result.parents
        documents = self._documents_from_chunk_records(chunk_records)

        self._transition_document_status(
            doc_id,
            DocumentStatus.INDEXING,
            status_source="VectorIndexService._index_mineru_document_record",
            status_detail="MinerU chunks were prepared and vector write is starting",
            status_evidence={
                "child_chunk_count": len(chunk_records),
                "parent_chunk_count": len(parents),
                "vector_document_count": len(documents),
                "artifact_dir": document_record.artifact_dir,
            },
        )

        if documents:
            self._write_vector_documents(document_record, documents)
            # parents 一同落 metadata store，但不写入 Milvus。
            knowledge_metadata_store.replace_chunks(doc_id, chunk_records + parents)
        else:
            self._cleanup_existing_document_data(document_record)

        self._transition_document_status(
            doc_id,
            DocumentStatus.INDEXED,
            status_source="VectorIndexService._index_mineru_document_record",
            status_detail="MinerU artifact chunks and vector rows were written successfully",
            status_evidence={
                "child_chunk_count": len(chunk_records),
                "parent_chunk_count": len(parents),
                "vector_document_count": len(documents),
                "artifact_dir": document_record.artifact_dir,
            },
        )
        logger.info(
            "MinerU artifact 索引完成: doc_id={}, children={}, parents={}",
            doc_id,
            len(chunk_records),
            len(parents),
        )

    def _cleanup_existing_document_data(self, document_record: DocumentRecord) -> None:
        """Remove old chunk/index data before writing a fresh version."""
        doc_id = document_record.doc_id
        normalized_source = Path(document_record.original_path).resolve().as_posix()

        deleted_chunk_count = knowledge_metadata_store.delete_chunks_by_doc_id(doc_id)
        if deleted_chunk_count:
            logger.info(f"删除文档旧 chunk 记录: doc_id={doc_id}, 删除数量: {deleted_chunk_count}")

        _ = vector_store_manager.delete_by_doc_id(doc_id)
        _ = vector_store_manager.delete_by_source(normalized_source)

    def _transition_document_status(
        self,
        doc_id: str,
        status: DocumentStatus,
        *,
        status_source: str,
        status_detail: str,
        status_evidence: dict[str, Any],
        error_message: str = "",
    ) -> DocumentRecord:
        updated = knowledge_metadata_store.transition_document_status(
            doc_id,
            status,
            status_source=status_source,
            status_detail=status_detail,
            status_evidence=status_evidence,
            error_message=error_message,
        )
        if updated is None:
            raise ValueError(f"文档不存在: {doc_id}")
        if status == DocumentStatus.INDEXED:
            self._enqueue_document_health_check(doc_id)
        return updated

    def _enqueue_document_health_check(self, doc_id: str) -> None:
        """Schedule post-index diagnostics without making indexing depend on it."""
        try:
            from app.services.document_health_check_service import document_health_check_queue

            document_health_check_queue.enqueue(doc_id)
        except Exception as exc:  # pragma: no cover - deliberately non-blocking
            logger.warning("文档健康检查触发失败: doc_id={}, 错误={}", doc_id, exc)

    def _build_doc_id(self, kb_id: str, path: Path) -> str:
        """Build a stable document ID for legacy md/txt compatibility indexing."""
        normalized_path = path.resolve().as_posix()
        return str(uuid5(NAMESPACE_URL, f"{kb_id}:{normalized_path}"))

    def _build_artifact_dir(self, kb_id: str, doc_id: str) -> str:
        return str((Path("./uploads") / "documents" / kb_id / doc_id / "artifacts").resolve())

    def _build_document_record(
        self,
        kb_id: str,
        doc_id: str,
        path: Path,
        status: DocumentStatus,
        parser_engine: ParserEngine,
        error_message: str = "",
    ) -> DocumentRecord:
        now = datetime.now()
        return DocumentRecord(
            doc_id=doc_id,
            kb_id=kb_id,
            file_name=path.name,
            file_ext=path.suffix.lower().lstrip("."),
            original_path=path.resolve().as_posix(),
            artifact_dir=self._build_artifact_dir(kb_id, doc_id),
            parser_engine=parser_engine,
            status=status,
            status_detail="legacy single-file record created before index pipeline continues",
            status_source="VectorIndexService.index_single_file",
            status_evidence={
                "file_path": path.resolve().as_posix(),
                "kb_id": kb_id,
                "parser_engine": parser_engine.value,
            },
            status_confirmed_at=now,
            error_message=error_message,
            metadata={
                "legacy_path": True,
                "source_hash": hashlib.sha1(path.resolve().as_posix().encode("utf-8")).hexdigest(),
            },
            created_at=now,
            updated_at=now,
        )

    def _build_chunk_records(
        self,
        kb_id: str,
        doc_id: str,
        path: Path,
        content: str,
        documents: list[Document],
        parser_engine: ParserEngine,
    ) -> list[ChunkRecord]:
        offsets = self._locate_chunk_offsets(content, documents)
        file_ext = path.suffix.lower()
        chunk_records: list[ChunkRecord] = []

        for chunk_index, (document, (start_index, end_index)) in enumerate(zip(documents, offsets, strict=True)):
            heading_path = self._extract_heading_path(document.metadata)
            chunk_id = f"{doc_id}:c{chunk_index:05d}"
            content_type = "markdown_section" if file_ext == ".md" else "text"
            source_ref = SourceRef(
                kb_id=kb_id,
                doc_id=doc_id,
                chunk_id=chunk_id,
                source_file=path.name,
                page_start=None,
                page_end=None,
                heading_path=heading_path,
                content_type=content_type,
                parser_engine=parser_engine,
            )

            document.metadata.update(
                {
                    "kb_id": kb_id,
                    "doc_id": doc_id,
                    "chunk_id": chunk_id,
                    "content_type": content_type,
                    "parser_engine": parser_engine.value,
                    "heading_path": heading_path,
                    "page_start": None,
                    "page_end": None,
                    "quality_flags": [],
                    "source_ref": source_ref.model_dump(mode="json"),
                }
            )

            chunk_records.append(
                ChunkRecord(
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    kb_id=kb_id,
                    content=document.page_content,
                    chunk_index=chunk_index,
                    start_index=start_index,
                    end_index=end_index,
                    heading_path=heading_path,
                    page_start=None,
                    page_end=None,
                    content_type=content_type,
                    source_ref=source_ref,
                    quality_flags=[],
                    metadata=dict(document.metadata),
                )
            )

        return chunk_records

    def _extract_heading_path(self, metadata: dict[str, Any]) -> list[str]:
        return [metadata[key] for key in ("h1", "h2", "h3") if metadata.get(key)]

    def _documents_from_chunk_records(self, chunk_records: list[ChunkRecord]) -> list[Document]:
        """从最终 ChunkRecord 重建 Document，确保 documents 与 chunk_records 1:1 且 metadata 同步。"""
        return [
            Document(page_content=record.content, metadata=dict(record.metadata))
            for record in chunk_records
        ]

    def _write_vector_documents(
        self,
        document_record: DocumentRecord,
        documents: list[Document],
    ) -> list[str]:
        """Prepare embeddings before deleting old vector/chunk data."""
        prepare = getattr(vector_store_manager, "prepare_documents", None)
        add_prepared = getattr(vector_store_manager, "add_prepared_documents", None)
        if callable(prepare) and callable(add_prepared):
            prepared = prepare(documents)
            self._cleanup_existing_document_data(document_record)
            return add_prepared(prepared)

        self._cleanup_existing_document_data(document_record)
        return vector_store_manager.add_documents(documents)

    def _validate_kb_id(self, kb_id: str) -> None:
        if kb_id is None or not str(kb_id).strip():
            raise ValueError("kb_id 不能为空，索引入口必须显式声明目标知识库")

    def _locate_chunk_offsets(self, content: str, documents: list[Document]) -> list[tuple[int, int]]:
        offsets: list[tuple[int, int]] = []
        cursor = 0

        for document in documents:
            chunk_text = document.page_content
            start_index = content.find(chunk_text, cursor)

            if start_index < 0:
                trimmed_text = chunk_text.strip()
                if trimmed_text:
                    start_index = content.find(trimmed_text, cursor)
                    if start_index >= 0:
                        end_index = start_index + len(trimmed_text)
                        offsets.append((start_index, end_index))
                        cursor = end_index
                        continue

                start_index = cursor

            end_index = start_index + len(chunk_text)
            offsets.append((start_index, end_index))
            cursor = max(cursor, end_index)

        return offsets


# 全局单例
vector_index_service = VectorIndexService()
