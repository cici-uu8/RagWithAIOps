"""Permission-aware knowledge search with stable diagnostics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from app.enterprise.adapters.rag_adapter import RagAdapter, rag_adapter
from app.enterprise.context import RequestContext
from app.enterprise.documents.service import DocumentAccessService, document_access_service
from app.models import (
    DocumentRecord,
    DocumentStatus,
    RetrievalMode,
    RetrievalQuery,
    RetrievalResult,
)
from app.services.chunk_evidence_mapper import ChunkEvidenceMapper

DiagnosticsCount = int | Literal["not_available"]

PROCESS_DIGITAL_KB_ID = "process_digital_dept"
CRAFT_KB_ID = "craft_dept"

PROCESS_KEYWORDS = (
    "Kubernetes",
    "Pod",
    "Prometheus",
    "Alertmanager",
    "MCP",
    "数据库",
    "同步服务",
    "API",
    "数字化",
)
CRAFT_KEYWORDS = (
    "设备",
    "检修",
    "安全隔离",
    "LOTO",
    "压力系统",
    "土壤地下水",
    "监测",
    "环保",
)
BOTH_KEYWORDS = (
    "线上故障",
    "智能运维",
    "复盘",
    "事件响应",
)


@dataclass(frozen=True)
class RouteDecision:
    routing_mode: str
    selected_kb_ids: list[str]
    routing_reason: str
    requested_kb_ids: list[str]
    fallback_mode: str


@dataclass
class RagDiagnostics:
    requested_kb_ids: list[str]
    visible_kb_ids: list[str]
    selected_kb_ids: list[str]
    allowed_doc_count: int
    indexed_doc_count: int
    parse_pending_doc_count: int
    parse_failed_doc_count: int
    index_failed_doc_count: int
    sparse_hit_count: DiagnosticsCount
    dense_hit_count: DiagnosticsCount
    hybrid_result_count: DiagnosticsCount
    permission_filtered_count: int
    fallback_mode: str
    no_result_reason: str
    tool_called: bool
    tool_name: str
    trace_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KnowledgeSearchService:
    """Route knowledge search requests and explain empty results."""

    def __init__(
        self,
        *,
        rag_adapter: RagAdapter | None = None,
        document_access_service: DocumentAccessService | None = None,
    ):
        self.rag_adapter = rag_adapter or rag_adapter_default()
        self.document_access_service = document_access_service or document_access_service_default()

    def search_scoped(
        self,
        context: RequestContext,
        *,
        kb_id: str,
        query: str,
        top_k: int = 5,
        retrieval_mode: str | RetrievalMode = RetrievalMode.HYBRID,
    ) -> dict[str, Any]:
        normalized_query = self._normalize_query(query)
        requested_kb_ids = [kb_id]
        stats = self._scope_stats(context, requested_kb_ids)
        selected_kb_ids = [kb_id] if stats["indexed_doc_count"] > 0 else []
        if not selected_kb_ids:
            diagnostics = self._diagnostics(
                context,
                requested_kb_ids=requested_kb_ids,
                selected_kb_ids=[],
                stats=stats,
                retrieval_mode=retrieval_mode,
                result_count=0,
                fallback_mode="none",
                no_result_reason=self._no_document_reason(stats, requested_kb_ids),
            )
            return self._response(
                query=normalized_query,
                items=[],
                routing_mode="scoped",
                selected_kb_ids=[],
                routing_reason="指定知识库当前不可见或没有已索引文档，未执行检索。",
                diagnostics=diagnostics,
            )

        results = self._retrieve(
            context,
            query=normalized_query,
            kb_ids=selected_kb_ids,
            top_k=top_k,
            retrieval_mode=retrieval_mode,
        )
        diagnostics = self._diagnostics(
            context,
            requested_kb_ids=requested_kb_ids,
            selected_kb_ids=selected_kb_ids,
            stats=stats,
            retrieval_mode=retrieval_mode,
            result_count=len(results),
            fallback_mode="none",
            no_result_reason=self._result_reason(results, stats),
        )
        return self._response(
            query=normalized_query,
            items=results,
            routing_mode="scoped",
            selected_kb_ids=selected_kb_ids,
            routing_reason=f"指定知识库检索：{kb_id}。",
            diagnostics=diagnostics,
        )

    def search_unscoped(
        self,
        context: RequestContext,
        *,
        query: str,
        kb_scope: str = "auto",
        candidate_kb_ids: list[str] | None = None,
        top_k: int = 5,
        retrieval_mode: str | RetrievalMode = RetrievalMode.HYBRID,
        per_kb_top_k: int = 3,
    ) -> dict[str, Any]:
        normalized_query = self._normalize_query(query)
        visible_kb_ids = self.document_access_service.visible_kb_ids(context)
        decision = self.route_kb_scope(
            normalized_query,
            kb_scope=kb_scope,
            candidate_kb_ids=candidate_kb_ids,
            visible_kb_ids=visible_kb_ids,
        )
        stats = self._scope_stats(context, decision.requested_kb_ids)
        selected_kb_ids = [
            kb_id
            for kb_id in decision.selected_kb_ids
            if any(
                document.kb_id == kb_id and document.status == DocumentStatus.INDEXED
                for document in stats["allowed_documents"]
            )
        ]
        if not selected_kb_ids:
            diagnostics = self._diagnostics(
                context,
                requested_kb_ids=decision.requested_kb_ids,
                selected_kb_ids=[],
                stats=stats,
                retrieval_mode=retrieval_mode,
                result_count=0,
                fallback_mode=decision.fallback_mode,
                no_result_reason=self._no_document_reason(stats, decision.requested_kb_ids),
            )
            return self._response(
                query=normalized_query,
                items=[],
                routing_mode=decision.routing_mode,
                selected_kb_ids=[],
                routing_reason=decision.routing_reason,
                diagnostics=diagnostics,
            )

        if len(selected_kb_ids) == 1:
            results = self._retrieve(
                context,
                query=normalized_query,
                kb_ids=selected_kb_ids,
                top_k=top_k,
                retrieval_mode=retrieval_mode,
            )
        else:
            results = self._retrieve_across_kbs(
                context,
                query=normalized_query,
                kb_ids=selected_kb_ids,
                top_k=top_k,
                per_kb_top_k=per_kb_top_k,
                retrieval_mode=retrieval_mode,
            )
        diagnostics = self._diagnostics(
            context,
            requested_kb_ids=decision.requested_kb_ids,
            selected_kb_ids=selected_kb_ids,
            stats=stats,
            retrieval_mode=retrieval_mode,
            result_count=len(results),
            fallback_mode=decision.fallback_mode,
            no_result_reason=self._result_reason(results, stats),
        )
        return self._response(
            query=normalized_query,
            items=results,
            routing_mode=decision.routing_mode,
            selected_kb_ids=selected_kb_ids,
            routing_reason=decision.routing_reason,
            diagnostics=diagnostics,
        )

    def route_kb_scope(
        self,
        query: str,
        *,
        kb_scope: str,
        candidate_kb_ids: list[str] | None,
        visible_kb_ids: list[str],
    ) -> RouteDecision:
        visible = _dedupe_preserve_order(visible_kb_ids)
        candidates = self._candidate_kb_ids(candidate_kb_ids, visible)
        normalized_scope = (kb_scope or "auto").strip()
        if normalized_scope and normalized_scope not in {"auto", "all", "all_visible"}:
            selected = [normalized_scope] if normalized_scope in candidates else []
            reason = (
                f"显式指定知识库：{normalized_scope}。"
                if selected
                else "显式指定的知识库当前不可见或不在候选范围内。"
            )
            return RouteDecision(
                routing_mode="explicit",
                selected_kb_ids=selected,
                routing_reason=reason,
                requested_kb_ids=[normalized_scope],
                fallback_mode="none",
            )

        if normalized_scope in {"all", "all_visible"}:
            return RouteDecision(
                routing_mode="all_visible",
                selected_kb_ids=candidates,
                routing_reason="请求指定检索全部可见知识库。",
                requested_kb_ids=candidates,
                fallback_mode="all_visible",
            )

        selected, matched_keywords, fallback_mode = self._auto_route(query, candidates)
        if matched_keywords:
            reason = f"auto 命中关键词：{'、'.join(matched_keywords)}。"
        else:
            reason = "未命中明确部门关键词，降级检索可见候选知识库。"
        return RouteDecision(
            routing_mode="auto",
            selected_kb_ids=selected,
            routing_reason=reason,
            requested_kb_ids=list(candidate_kb_ids or selected),
            fallback_mode=fallback_mode,
        )

    def _scope_stats(self, context: RequestContext, requested_kb_ids: list[str]) -> dict[str, Any]:
        requested = set(requested_kb_ids)
        documents = [
            document
            for document in self.document_access_service.metadata_store.list_documents()
            if not requested or document.kb_id in requested
        ]
        allowed_documents: list[DocumentRecord] = []
        blocked_documents: list[DocumentRecord] = []
        for document in documents:
            if self.document_access_service.can_read_document(context, document):
                allowed_documents.append(document)
            else:
                blocked_documents.append(document)
        return {
            "allowed_documents": allowed_documents,
            "blocked_documents": blocked_documents,
            "visible_kb_ids": sorted({document.kb_id for document in allowed_documents if document.kb_id}),
            "allowed_doc_count": len(allowed_documents),
            "indexed_doc_count": _count_status(allowed_documents, DocumentStatus.INDEXED),
            "parse_pending_doc_count": _count_status(allowed_documents, DocumentStatus.PARSE_PENDING),
            "parse_failed_doc_count": _count_status(allowed_documents, DocumentStatus.PARSE_FAILED),
            "index_failed_doc_count": _count_status(allowed_documents, DocumentStatus.INDEX_FAILED),
            "permission_filtered_count": len(blocked_documents),
        }

    def _diagnostics(
        self,
        context: RequestContext,
        *,
        requested_kb_ids: list[str],
        selected_kb_ids: list[str],
        stats: dict[str, Any],
        retrieval_mode: str | RetrievalMode,
        result_count: int,
        fallback_mode: str,
        no_result_reason: str,
        tool_called: bool = False,
        tool_name: str = "",
    ) -> RagDiagnostics:
        mode = self._parse_retrieval_mode(retrieval_mode)
        sparse_hit_count: DiagnosticsCount = "not_available"
        dense_hit_count: DiagnosticsCount = "not_available"
        hybrid_result_count: DiagnosticsCount = "not_available"
        if mode == RetrievalMode.SPARSE_ONLY:
            sparse_hit_count = result_count
            hybrid_result_count = result_count
        elif mode == RetrievalMode.DENSE_ONLY:
            dense_hit_count = result_count
            hybrid_result_count = result_count
        elif mode in {RetrievalMode.HYBRID, RetrievalMode.HYBRID_RERANK}:
            hybrid_result_count = result_count
        return RagDiagnostics(
            requested_kb_ids=_dedupe_preserve_order(requested_kb_ids),
            visible_kb_ids=list(stats["visible_kb_ids"]),
            selected_kb_ids=_dedupe_preserve_order(selected_kb_ids),
            allowed_doc_count=stats["allowed_doc_count"],
            indexed_doc_count=stats["indexed_doc_count"],
            parse_pending_doc_count=stats["parse_pending_doc_count"],
            parse_failed_doc_count=stats["parse_failed_doc_count"],
            index_failed_doc_count=stats["index_failed_doc_count"],
            sparse_hit_count=sparse_hit_count,
            dense_hit_count=dense_hit_count,
            hybrid_result_count=hybrid_result_count,
            permission_filtered_count=stats["permission_filtered_count"],
            fallback_mode=fallback_mode,
            no_result_reason=no_result_reason,
            tool_called=tool_called,
            tool_name=tool_name,
            trace_id=context.trace_id,
        )

    def _retrieve(
        self,
        context: RequestContext,
        *,
        query: str,
        kb_ids: list[str],
        top_k: int,
        retrieval_mode: str | RetrievalMode,
    ) -> list[RetrievalResult]:
        retrieval_query = RetrievalQuery(
            query=query,
            top_k=max(1, top_k),
            retrieval_mode=self._parse_retrieval_mode(retrieval_mode),
            knowledge_base_ids=kb_ids,
        )
        return list(self.rag_adapter.retrieve(context, retrieval_query).results)

    def _retrieve_across_kbs(
        self,
        context: RequestContext,
        *,
        query: str,
        kb_ids: list[str],
        top_k: int,
        per_kb_top_k: int,
        retrieval_mode: str | RetrievalMode,
    ) -> list[RetrievalResult]:
        results: list[RetrievalResult] = []
        seen_chunk_ids: set[str] = set()
        for kb_id in kb_ids:
            for result in self._retrieve(
                context,
                query=query,
                kb_ids=[kb_id],
                top_k=max(1, per_kb_top_k),
                retrieval_mode=retrieval_mode,
            ):
                if result.chunk_id in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(result.chunk_id)
                results.append(result)
        return results[: max(1, top_k)]

    def _response(
        self,
        *,
        query: str,
        items: list[RetrievalResult],
        routing_mode: str,
        selected_kb_ids: list[str],
        routing_reason: str,
        diagnostics: RagDiagnostics,
    ) -> dict[str, Any]:
        return {
            "query": query,
            "items": [_result_payload(result) for result in items],
            "total": len(items),
            "routing_mode": routing_mode,
            "selected_kb_ids": list(selected_kb_ids),
            "routing_reason": routing_reason,
            "diagnostics": diagnostics.to_dict(),
        }

    def _candidate_kb_ids(self, candidate_kb_ids: list[str] | None, visible_kb_ids: list[str]) -> list[str]:
        visible = _dedupe_preserve_order(visible_kb_ids)
        if candidate_kb_ids:
            candidate_set = set(_dedupe_preserve_order(candidate_kb_ids))
            return [kb_id for kb_id in visible if kb_id in candidate_set]
        preferred = [kb_id for kb_id in (CRAFT_KB_ID, PROCESS_DIGITAL_KB_ID) if kb_id in visible]
        return preferred or visible

    def _auto_route(self, query: str, candidates: list[str]) -> tuple[list[str], list[str], str]:
        process_hits = _matched_keywords(query, PROCESS_KEYWORDS)
        craft_hits = _matched_keywords(query, CRAFT_KEYWORDS)
        both_hits = _matched_keywords(query, BOTH_KEYWORDS)
        selected: list[str] = []
        if both_hits or (process_hits and craft_hits):
            selected = [kb_id for kb_id in candidates if kb_id in {CRAFT_KB_ID, PROCESS_DIGITAL_KB_ID}]
        elif process_hits:
            selected = [kb_id for kb_id in candidates if kb_id == PROCESS_DIGITAL_KB_ID]
        elif craft_hits:
            selected = [kb_id for kb_id in candidates if kb_id == CRAFT_KB_ID]
        matched = [*both_hits, *process_hits, *craft_hits]
        if selected:
            return selected, matched, "keyword"
        if matched:
            return candidates, matched, "keyword_not_visible"
        return candidates, [], "all_visible"

    def _normalize_query(self, query: str) -> str:
        normalized = (query or "").strip()
        if not normalized:
            raise ValueError("query_required")
        return normalized

    def _parse_retrieval_mode(self, retrieval_mode: str | RetrievalMode) -> RetrievalMode:
        if isinstance(retrieval_mode, RetrievalMode):
            return retrieval_mode
        try:
            return RetrievalMode(str(retrieval_mode))
        except ValueError:
            return RetrievalMode.HYBRID

    def _no_document_reason(self, stats: dict[str, Any], requested_kb_ids: list[str]) -> str:
        if requested_kb_ids and stats["allowed_doc_count"] == 0 and stats["permission_filtered_count"] > 0:
            return "selected_kb_not_visible_or_no_indexed_documents"
        if stats["allowed_doc_count"] == 0:
            return "no_visible_documents"
        if stats["parse_pending_doc_count"] > 0 and stats["indexed_doc_count"] == 0:
            return "worker_pending"
        if stats["indexed_doc_count"] == 0:
            return "documents_not_indexed"
        return "unknown"

    def _result_reason(self, results: list[RetrievalResult], stats: dict[str, Any]) -> str:
        if results:
            return ""
        if stats["indexed_doc_count"] > 0:
            return "retrieval_no_hit"
        return self._no_document_reason(stats, [])


def _count_status(documents: list[DocumentRecord], status: DocumentStatus) -> int:
    return sum(1 for document in documents if document.status == status)


def _matched_keywords(query: str, keywords: tuple[str, ...]) -> list[str]:
    lowered = query.lower()
    return [keyword for keyword in keywords if keyword.lower() in lowered]


def _dedupe_preserve_order(values: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def _result_payload(result: RetrievalResult) -> dict[str, Any]:
    chunk_evidence = result.metadata.get("chunk_evidence")
    if not isinstance(chunk_evidence, dict):
        chunk_evidence = ChunkEvidenceMapper.from_retrieval_result(result).model_dump(mode="json")
    return {
        "kb_id": result.kb_id,
        "doc_id": result.doc_id,
        "chunk_id": result.chunk_id,
        "content": result.content,
        "score": result.score,
        "citation_text": result.citation_text,
        "source_ref": result.source_ref.model_dump(mode="json"),
        "chunk_evidence": chunk_evidence,
        "metadata": result.metadata,
    }


def rag_adapter_default() -> RagAdapter:
    return rag_adapter


def document_access_service_default() -> DocumentAccessService:
    return document_access_service


knowledge_search_service = KnowledgeSearchService()
