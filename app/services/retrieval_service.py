"""Citation-aware retrieval service built on the existing Milvus search path."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from loguru import logger

from app.models import (
    ChunkRecord,
    ContextGranularity,
    ResultAggregation,
    RetrievalMode,
    RetrievalQuery,
    RetrievalResponse,
    RetrievalResult,
    SourceRef,
)
from app.services.chunk_evidence_mapper import ChunkEvidenceMapper
from app.services.hybrid_search_service import hybrid_search_service
from app.services.knowledge_metadata_store import knowledge_metadata_store
from app.services.vector_search_service import (
    SearchResult as RawSearchResult,
    vector_search_service,
)


class RetrievalService:
    """Turn raw vector hits into structured retrieval artifacts."""

    EMPTY_MESSAGE = "没有找到相关信息。"

    def retrieve(
        self,
        query: RetrievalQuery,
        *,
        allowed_document_ids: Iterable[str] | None = None,
    ) -> RetrievalResponse:
        logger.info("开始结构化检索: query='{}', top_k={}", query.query, query.top_k)
        allowed_doc_ids = set(allowed_document_ids) if allowed_document_ids is not None else None

        if query.result_aggregation == ResultAggregation.DOC_LEVEL:
            results = self._retrieve_with_doc_aggregation(query, allowed_document_ids=allowed_doc_ids)
        else:
            # NONE 路径必须与 P4.5 baseline 字节级等价 (P5 设计 §1.1):
            # ``top_chunks_per_doc`` / ``doc_oversample_factor`` 在此分支
            # 完全 no-op, 走原始召回路径不放大候选池, 不动排序。
            results = self._retrieve_candidates(query, allowed_document_ids=allowed_doc_ids)

        context_text = self._format_context(results, query.context_granularity)
        if not results:
            context_text = self.EMPTY_MESSAGE

        return RetrievalResponse(
            query=query,
            results=results,
            context_text=context_text,
            empty_message=self.EMPTY_MESSAGE,
        )

    def _retrieve_candidates(
        self,
        query: RetrievalQuery,
        *,
        allowed_document_ids: set[str] | None = None,
    ) -> list[RetrievalResult]:
        """Run the underlying recall path and build ``RetrievalResult`` objects.

        Identical to the pre-P5 ``retrieve()`` body up to (but not including)
        context-text formatting. ``_format_context`` is intentionally not called
        here because P5 ``DOC_LEVEL`` mode needs to dedup before formatting.
        """
        if query.retrieval_mode == RetrievalMode.DENSE_ONLY:
            raw_hits = vector_search_service.search_similar_documents(
                query.query, top_k=query.top_k
            )
        else:
            raw_hits = hybrid_search_service.search(query)
        return self._build_results(raw_hits, query, allowed_document_ids=allowed_document_ids)

    def _retrieve_with_doc_aggregation(
        self,
        query: RetrievalQuery,
        *,
        allowed_document_ids: set[str] | None = None,
    ) -> list[RetrievalResult]:
        """P5 ``DOC_LEVEL`` strategy: oversample → group by ``doc_id`` → rank docs.

        Per design §2: pool_k = ``max(top_k * doc_oversample_factor, top_k)``.
        The pool query is forced to ``ResultAggregation.NONE`` to avoid
        recursion / double dedup.
        """
        pool_k = max(query.top_k * query.doc_oversample_factor, query.top_k)
        pool_query = query.model_copy(
            update={
                "top_k": pool_k,
                "result_aggregation": ResultAggregation.NONE,
            }
        )
        candidates = self._retrieve_candidates(
            pool_query,
            allowed_document_ids=allowed_document_ids,
        )
        return self._aggregate_by_doc(candidates, query)

    def _aggregate_by_doc(
        self,
        candidates: list[RetrievalResult],
        query: RetrievalQuery,
    ) -> list[RetrievalResult]:
        """Group candidates by ``doc_id``, keep ``top_chunks_per_doc`` per doc.

        Doc ranking (design §2.3): ``doc_hit_count`` desc → ``doc_max_score``
        desc (``None`` treated as worst) → ``doc_id`` ascending (stable
        tie-breaker). Within each doc, candidates keep the underlying recall
        order (which already reflects rank).

        Each kept result gets three observability fields on ``metadata``:
        ``aggregation_doc_hit_count`` / ``aggregation_doc_max_score`` /
        ``aggregation_dropped_chunk_ids``. Lifecycle (design §2.4): construction-
        time only — not persisted to ``KnowledgeMetadataStore``, not written to
        Milvus, not part of the ``retrieve_knowledge`` artifact stable contract.
        """
        if not candidates:
            return []

        groups: dict[str, list[RetrievalResult]] = {}
        for result in candidates:
            groups.setdefault(result.doc_id, []).append(result)

        doc_hit_count: dict[str, int] = {
            doc_id: len(items) for doc_id, items in groups.items()
        }
        doc_max_score: dict[str, float | None] = {}
        for doc_id, items in groups.items():
            scores = [item.score for item in items if item.score is not None]
            doc_max_score[doc_id] = max(scores) if scores else None

        def sort_key(doc_id: str) -> tuple[int, float, str]:
            max_score = doc_max_score[doc_id]
            score_key = -(max_score if max_score is not None else float("-inf"))
            return (-doc_hit_count[doc_id], score_key, doc_id)

        ranked_doc_ids = sorted(groups.keys(), key=sort_key)[: query.top_k]

        per_doc_cap = max(query.top_chunks_per_doc, 1)
        final_results: list[RetrievalResult] = []
        for doc_id in ranked_doc_ids:
            items = groups[doc_id]
            kept = items[:per_doc_cap]
            dropped_chunk_ids = [item.chunk_id for item in items[per_doc_cap:]]
            for item in kept:
                item.metadata["aggregation_doc_hit_count"] = doc_hit_count[doc_id]
                item.metadata["aggregation_doc_max_score"] = doc_max_score[doc_id]
                item.metadata["aggregation_dropped_chunk_ids"] = list(dropped_chunk_ids)
                final_results.append(item)

        return final_results

    def _build_results(
        self,
        raw_hits: Iterable[RawSearchResult],
        query: RetrievalQuery,
        *,
        allowed_document_ids: set[str] | None = None,
    ) -> list[RetrievalResult]:
        results: list[RetrievalResult] = []
        allowed_kb_ids = set(query.knowledge_base_ids)
        requested_doc_ids = set(query.document_ids)
        for hit in raw_hits:
            evidence = ChunkEvidenceMapper.from_vector_hit(hit)
            metadata = dict(evidence.metadata)
            source_ref = ChunkEvidenceMapper.to_source_ref(evidence)
            kb_id = evidence.kb_id

            if allowed_kb_ids and kb_id not in allowed_kb_ids:
                continue

            doc_id = evidence.doc_id
            if requested_doc_ids and doc_id not in requested_doc_ids:
                continue
            if allowed_document_ids is not None and doc_id not in allowed_document_ids:
                continue

            chunk_id = evidence.chunk_id
            content = hit.content or metadata.get("content", "")
            if not kb_id or not doc_id or not chunk_id or not source_ref.source_file:
                logger.warning(
                    "跳过缺少稳定引用字段的检索命中: kb_id={}, doc_id={}, chunk_id={}, source_file={}",
                    kb_id,
                    doc_id,
                    chunk_id,
                    source_ref.source_file,
                )
                continue

            score = evidence.score
            if score is not None and "recall_score" not in metadata:
                metadata["recall_score"] = score
            metadata["chunk_evidence"] = evidence.model_dump(mode="json")
            citation_text = self._build_citation_text(source_ref, chunk_id)

            self._attach_parent_context(metadata, doc_id)

            results.append(
                RetrievalResult(
                    kb_id=kb_id,
                    doc_id=doc_id,
                    chunk_id=chunk_id,
                    content=content,
                    score=score,
                    source_ref=source_ref,
                    citation_text=citation_text,
                    metadata=metadata,
                )
            )

        return results

    def _attach_parent_context(self, metadata: dict[str, Any], doc_id: str) -> None:
        """命中子块带 ``parent_chunk_id`` 时，把父块文本挂到 metadata 上。

        - 不修改 ``RetrievalResult.content`` / ``citation_text``，保证引用稳定。
        - 父块缺失或加载失败时，静默跳过（不阻断检索）。
        """
        parent_chunk_id = metadata.get("parent_chunk_id")
        if not parent_chunk_id or not doc_id:
            return
        parent = self._load_parent_chunk(doc_id, parent_chunk_id)
        if parent is None:
            return
        metadata["parent_content"] = parent.content
        metadata["parent_chunk_id"] = parent_chunk_id
        metadata["parent_heading_path"] = list(parent.heading_path)

    def _load_parent_chunk(self, doc_id: str, parent_chunk_id: str) -> ChunkRecord | None:
        try:
            chunks = knowledge_metadata_store.list_chunks_by_doc_id(doc_id)
        except Exception as exc:  # pragma: no cover - 防御性兜底
            logger.warning("加载父块所属文档失败: doc_id={}, 错误={}", doc_id, exc)
            return None
        for chunk in chunks:
            if chunk.chunk_id == parent_chunk_id:
                return chunk
        return None

    def _build_citation_text(self, source_ref: SourceRef, chunk_id: str) -> str:
        parts: list[str] = []
        if source_ref.source_file:
            parts.append(f"来源: {source_ref.source_file}")

        if source_ref.page_start is not None:
            if source_ref.page_end is not None and source_ref.page_end != source_ref.page_start:
                parts.append(f"页码: {source_ref.page_start}-{source_ref.page_end}")
            else:
                parts.append(f"页码: {source_ref.page_start}")

        if source_ref.heading_path:
            parts.append(f"章节: {' > '.join(source_ref.heading_path)}")

        if chunk_id:
            parts.append(f"chunk: {chunk_id}")

        return "[" + ", ".join(parts) + "]" if parts else ""

    def _format_context(
        self,
        results: list[RetrievalResult],
        granularity: ContextGranularity,
    ) -> str:
        if not results:
            return self.EMPTY_MESSAGE

        formatted_parts: list[str] = []
        for index, result in enumerate(results, start=1):
            body_text, fallback = self._resolve_context_body(result, granularity)
            # P4.5 §1.2 生命周期: ``expanded_context`` / ``context_granularity_fallback``
            # 仅存在于本次 retrieval response 构造期，不写回 metadata store / Milvus，
            # 不进入 retrieve_knowledge artifact 稳定契约字段。
            result.metadata["expanded_context"] = body_text
            if fallback:
                result.metadata["context_granularity_fallback"] = fallback
            else:
                result.metadata.pop("context_granularity_fallback", None)

            headers = " > ".join(result.source_ref.heading_path) if result.source_ref.heading_path else ""
            formatted = f"【参考资料 {index}】"
            if headers:
                formatted += f"\n标题: {headers}"
            if result.source_ref.source_file:
                formatted += f"\n来源: {result.source_ref.source_file}"
            if result.citation_text:
                formatted += f"\n定位: {result.citation_text}"
            formatted += f"\n内容:\n{body_text}\n"
            formatted_parts.append(formatted)

        return "\n".join(formatted_parts)

    def _resolve_context_body(
        self,
        result: RetrievalResult,
        granularity: ContextGranularity,
    ) -> tuple[str, str | None]:
        """Pick the per-hit context body for the given granularity.

        Returns ``(body_text, fallback_reason)`` where ``fallback_reason`` is
        ``None`` on the happy path. Same parent / same doc duplicates are kept
        verbatim per P4.5 design (no dedup).
        """
        if granularity == ContextGranularity.PARENT_CHUNK:
            parent_content = result.metadata.get("parent_content")
            if parent_content:
                return str(parent_content), None
            return result.content, "no_parent"
        if granularity == ContextGranularity.FULL_DOC:
            doc_text = self._assemble_full_doc_context(result.doc_id)
            if doc_text:
                return doc_text, None
            return result.content, "no_doc_text"
        # CHUNK 与未知值均退回到子块原文，保持 P4 行为不变。
        return result.content, None

    def _assemble_full_doc_context(self, doc_id: str) -> str:
        """组装 ``full_doc`` 模式下的整篇可展示文本。

        硬口径 (P4.5 设计 §1.1): 只从 ``KnowledgeMetadataStore`` 的非 parent
        子块组装；不读 ``original_path`` / ``cleaned.md`` / 任何原始文件。
        子块按 ``chunk_index`` 升序，用 ``\n\n`` 拼接。
        """
        if not doc_id:
            return ""
        try:
            chunks = knowledge_metadata_store.list_chunks_by_doc_id(doc_id)
        except Exception as exc:  # pragma: no cover - 防御性兜底
            logger.warning("加载 doc 子块失败: doc_id={}, 错误={}", doc_id, exc)
            return ""
        children = [c for c in chunks if c.metadata.get("chunk_role") != "parent"]
        if not children:
            return ""
        children.sort(key=lambda c: c.chunk_index)
        return "\n\n".join(c.content for c in children)


retrieval_service = RetrievalService()
