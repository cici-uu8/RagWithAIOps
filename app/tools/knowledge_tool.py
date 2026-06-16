"""知识检索工具 - 从向量数据库中检索相关信息"""

from typing import Any

from langchain_core.tools import tool
from loguru import logger

from app.config import config
from app.enterprise.adapters.rag_adapter import rag_adapter
from app.enterprise.context import get_current_request_context
from app.enterprise.documents import document_access_service
from app.models import DocumentRecord, DocumentStatus, RetrievalMode, RetrievalQuery
from app.services.chunk_evidence_mapper import ChunkEvidenceMapper
from app.services.retrieval_service import retrieval_service


@tool
def list_knowledge_documents(kb_id: str | None = None) -> dict[str, Any]:
    """列出当前用户可见的知识库文档。

    Args:
        kb_id: 可选，限定知识库 ID。不传则列出当前用户所有可见文档。

    Returns:
        结构化文档清单，只包含当前用户有权限查看且已索引的文档。
    """
    context = get_current_request_context()
    documents = document_access_service.list_visible_documents(context, kb_id=kb_id)
    visible_kb_ids = sorted({document.kb_id for document in documents if document.kb_id})
    message = ""
    if kb_id and not documents and not document_access_service.user_can_see_kb(context, kb_id):
        message = f"你没有权限查看知识库 '{kb_id}'"
    elif not documents:
        message = "当前用户可见文档为空"

    return {
        "documents": [_document_payload(document) for document in documents],
        "total": len(documents),
        "kb_ids": visible_kb_ids,
        "message": message,
    }


@tool(response_format="content_and_artifact")
def retrieve_knowledge(
    query: str,
    knowledge_base_ids: list[str] | None = None,
    file_name: str | None = None,
    doc_id: str | None = None,
    top_k: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """从知识库中检索相关信息来回答问题

    当用户的问题涉及专业知识、文档内容或需要参考资料时，使用此工具。

    Args:
        query: 用户的问题或查询
        knowledge_base_ids: Optional list of knowledge base IDs to scope the
            retrieval. When None or empty, searches across all KBs (default
            behavior). Per §10(b) decision (2026-05-20), production KBs are
            split by knowledge type (e.g. "aiops" vs "manuals"); pass the
            relevant kb_id list when the question is scoped to a particular
            domain.
        file_name: Optional file name or stem to restrict retrieval to one
            visible document.
        doc_id: Optional document ID to restrict retrieval to one visible
            document.
        top_k: Optional number of chunks to return. Defaults to config.rag_top_k.

    Returns:
        Tuple[str, Dict[str, Any]]: (格式化的上下文文本, 结构化检索 artifact)
    """
    try:
        kb_ids = list(knowledge_base_ids) if knowledge_base_ids else []
        effective_top_k = _coerce_top_k(top_k)
        context = get_current_request_context()
        target_documents = document_access_service.find_visible_documents(
            context,
            doc_id=doc_id,
            file_name=file_name,
            kb_ids=kb_ids,
        ) if (doc_id or file_name) else []
        target_doc_ids = [document.doc_id for document in target_documents]
        if (doc_id or file_name) and not target_doc_ids:
            target_label = doc_id or file_name or ""
            error_message = f"没有找到当前用户可见的文档: {target_label}"
            retrieval_query = RetrievalQuery(
                query=query,
                top_k=effective_top_k,
                retrieval_mode=_default_retrieval_mode(),
                knowledge_base_ids=kb_ids,
                document_ids=[],
            )
            return error_message, {
                "query": retrieval_query.model_dump(mode="json"),
                "results": [],
                "context_text": error_message,
                "empty_message": error_message,
                "matched_documents": [],
                "diagnostics": _build_tool_diagnostics(
                    context=context,
                    query=retrieval_query,
                    result_count=0,
                ),
            }
        logger.info(
            "知识检索工具被调用: query='{}', kb_ids={}, doc_ids={}",
            query,
            kb_ids if kb_ids else "<all>",
            target_doc_ids if target_doc_ids else "<all>",
        )
        retrieval_query = RetrievalQuery(
            query=query,
            top_k=effective_top_k,
            retrieval_mode=_default_retrieval_mode(),
            knowledge_base_ids=kb_ids,
            document_ids=target_doc_ids,
        )
        if context is not None:
            response = rag_adapter.retrieve(context, retrieval_query)
        elif target_doc_ids:
            response = retrieval_service.retrieve(
                retrieval_query,
                allowed_document_ids=target_doc_ids,
            )
        else:
            response = retrieval_service.retrieve(retrieval_query)
        logger.info("检索到 {} 个相关文档", len(response.results))
        artifact = response.model_dump(mode="json")
        artifact["query"] = RetrievalQuery(
            query=query,
            top_k=response.query.top_k,
            retrieval_mode=response.query.retrieval_mode,
            knowledge_base_ids=list(response.query.knowledge_base_ids),
            document_ids=list(response.query.document_ids),
        ).model_dump(mode="json")
        artifact["matched_documents"] = [_document_payload(document) for document in target_documents]
        artifact["diagnostics"] = _build_tool_diagnostics(
            context=context,
            query=response.query,
            result_count=len(response.results),
        )
        for result in artifact.get("results", []):
            chunk_evidence = result.get("chunk_evidence")
            if not isinstance(chunk_evidence, dict):
                chunk_evidence = ChunkEvidenceMapper.from_retrieval_result(result).model_dump(mode="json")
                result["chunk_evidence"] = chunk_evidence
            source_ref = result.get("source_ref")
            if isinstance(source_ref, dict):
                source_ref["kb_id"] = result.get("kb_id", source_ref.get("kb_id", ""))
                source_ref["doc_id"] = result.get("doc_id", source_ref.get("doc_id", ""))
                source_ref["chunk_id"] = result.get("chunk_id", source_ref.get("chunk_id", ""))
            chunk_source_ref = chunk_evidence.get("source_ref") if isinstance(chunk_evidence, dict) else None
            if isinstance(chunk_source_ref, dict):
                chunk_source_ref["kb_id"] = result.get("kb_id", chunk_source_ref.get("kb_id", ""))
                chunk_source_ref["doc_id"] = result.get("doc_id", chunk_source_ref.get("doc_id", ""))
                chunk_source_ref["chunk_id"] = result.get("chunk_id", chunk_source_ref.get("chunk_id", ""))
        return response.context_text, artifact
    except Exception as e:
        logger.error("知识检索工具调用失败: {}", e)
        error_message = f"检索知识时发生错误: {str(e)}"
        retrieval_query = RetrievalQuery(
            query=query,
            top_k=_coerce_top_k(top_k),
            retrieval_mode=_default_retrieval_mode(),
            knowledge_base_ids=list(knowledge_base_ids) if knowledge_base_ids else [],
        )
        return error_message, {
            "query": retrieval_query.model_dump(mode="json"),
            "results": [],
            "context_text": error_message,
            "empty_message": error_message,
            "diagnostics": _build_tool_diagnostics(
                context=get_current_request_context(),
                query=retrieval_query,
                result_count=0,
                no_result_reason="unknown",
            ),
        }


def _document_payload(document) -> dict[str, Any]:
    return {
        "doc_id": document.doc_id,
        "file_name": document.file_name,
        "kb_id": document.kb_id,
        "created_at": document.created_at.isoformat() if document.created_at else None,
    }


def _build_tool_diagnostics(
    *,
    context,
    query: RetrievalQuery,
    result_count: int,
    no_result_reason: str | None = None,
) -> dict[str, Any]:
    stats = _document_scope_stats(
        context=context,
        kb_ids=list(query.knowledge_base_ids),
        doc_ids=list(query.document_ids),
    )
    reason = no_result_reason
    if reason is None:
        reason = _diagnose_no_result(result_count, stats)
    dense_hit_count: int | str = "not_available"
    sparse_hit_count: int | str = "not_available"
    hybrid_result_count: int | str = "not_available"
    mode = str(query.retrieval_mode)
    if mode == "dense_only":
        dense_hit_count = result_count
        hybrid_result_count = result_count
    elif mode == "sparse_only":
        sparse_hit_count = result_count
        hybrid_result_count = result_count
    elif mode in {"hybrid", "hybrid_rerank"}:
        hybrid_result_count = result_count

    return {
        "requested_kb_ids": list(query.knowledge_base_ids),
        "visible_kb_ids": stats["visible_kb_ids"],
        "selected_kb_ids": stats["selected_kb_ids"],
        "allowed_doc_count": stats["allowed_doc_count"],
        "indexed_doc_count": stats["indexed_doc_count"],
        "parse_pending_doc_count": stats["parse_pending_doc_count"],
        "parse_failed_doc_count": stats["parse_failed_doc_count"],
        "index_failed_doc_count": stats["index_failed_doc_count"],
        "sparse_hit_count": sparse_hit_count,
        "dense_hit_count": dense_hit_count,
        "hybrid_result_count": hybrid_result_count,
        "permission_filtered_count": stats["permission_filtered_count"],
        "fallback_mode": "none",
        "no_result_reason": reason,
        "tool_called": True,
        "tool_name": "retrieve_knowledge",
        "trace_id": context.trace_id if context else "",
    }


def _document_scope_stats(
    *,
    context,
    kb_ids: list[str],
    doc_ids: list[str],
) -> dict[str, Any]:
    requested_kb_ids = set(kb_ids)
    requested_doc_ids = set(doc_ids)
    documents = [
        document
        for document in document_access_service.metadata_store.list_documents()
        if (not requested_kb_ids or document.kb_id in requested_kb_ids)
        and (not requested_doc_ids or document.doc_id in requested_doc_ids)
    ]
    allowed_documents: list[DocumentRecord] = []
    blocked_documents: list[DocumentRecord] = []
    for document in documents:
        if document_access_service.can_read_document(context, document):
            allowed_documents.append(document)
        else:
            blocked_documents.append(document)

    indexed_documents = [
        document for document in allowed_documents if document.status == DocumentStatus.INDEXED
    ]
    return {
        "visible_kb_ids": sorted({document.kb_id for document in indexed_documents if document.kb_id}),
        "selected_kb_ids": sorted({document.kb_id for document in indexed_documents if document.kb_id}),
        "allowed_doc_count": len(allowed_documents),
        "indexed_doc_count": len(indexed_documents),
        "parse_pending_doc_count": _count_documents_with_status(
            allowed_documents,
            DocumentStatus.PARSE_PENDING,
        ),
        "parse_failed_doc_count": _count_documents_with_status(
            allowed_documents,
            DocumentStatus.PARSE_FAILED,
        ),
        "index_failed_doc_count": _count_documents_with_status(
            allowed_documents,
            DocumentStatus.INDEX_FAILED,
        ),
        "permission_filtered_count": len(blocked_documents),
    }


def _count_documents_with_status(
    documents: list[DocumentRecord],
    status: DocumentStatus,
) -> int:
    return sum(1 for document in documents if document.status == status)


def _diagnose_no_result(result_count: int, stats: dict[str, Any]) -> str:
    if result_count > 0:
        return ""
    if stats["allowed_doc_count"] == 0 and stats["permission_filtered_count"] > 0:
        return "selected_kb_not_visible_or_no_indexed_documents"
    if stats["allowed_doc_count"] == 0:
        return "no_visible_documents"
    if stats["parse_pending_doc_count"] > 0 and stats["indexed_doc_count"] == 0:
        return "worker_pending"
    if stats["indexed_doc_count"] == 0:
        return "documents_not_indexed"
    return "retrieval_no_hit"


def _coerce_top_k(top_k: int | None) -> int:
    if top_k is None:
        return config.rag_top_k
    try:
        return max(int(top_k), 1)
    except (TypeError, ValueError):
        return config.rag_top_k


def _default_retrieval_mode() -> RetrievalMode:
    try:
        return RetrievalMode(str(config.rag_default_retrieval_mode))
    except ValueError:
        return RetrievalMode.DENSE_ONLY
