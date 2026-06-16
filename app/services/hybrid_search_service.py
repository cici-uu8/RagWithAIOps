"""Hybrid dense/sparse retrieval and RRF fusion for P3."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from loguru import logger

from app.config import config
from app.models import RetrievalMode, RetrievalQuery
from app.services.rerank_service import rerank_service
from app.services.sparse_search_service import sparse_search_service
from app.services.vector_search_service import SearchResult, vector_search_service


class RrfFusionService:
    """Reciprocal Rank Fusion over already-ranked retrieval results."""

    def __init__(self, rank_constant: int = 60):
        self.rank_constant = rank_constant

    def fuse(
        self,
        ranked_lists: Iterable[tuple[str, list[SearchResult]]],
        top_k: int,
    ) -> list[SearchResult]:
        scores: dict[str, float] = defaultdict(float)
        representatives: dict[str, SearchResult] = {}
        rank_metadata: dict[str, dict[str, object]] = defaultdict(dict)

        for source_name, results in ranked_lists:
            for rank, result in enumerate(results, start=1):
                chunk_id = result.id
                scores[chunk_id] += 1 / (self.rank_constant + rank)
                representatives.setdefault(chunk_id, result)
                rank_metadata[chunk_id][f"{source_name}_rank"] = rank
                rank_metadata[chunk_id][f"{source_name}_score"] = result.score

        fused: list[SearchResult] = []
        for chunk_id, fusion_score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:top_k]:
            representative = representatives[chunk_id]
            metadata = dict(representative.metadata)
            metadata.update(rank_metadata[chunk_id])
            metadata["retrieval_mode"] = "hybrid"
            metadata.setdefault("recall_score", representative.score)
            metadata["fusion_score"] = fusion_score
            fused.append(
                SearchResult(
                    id=representative.id,
                    content=representative.content,
                    score=fusion_score,
                    metadata=metadata,
                )
            )
        return fused


class HybridSearchService:
    """Coordinate dense search, sparse search, and fusion."""

    def __init__(self):
        self.rrf_fusion_service = RrfFusionService()
        logger.info("混合检索服务初始化完成")

    def search(self, query: RetrievalQuery) -> list[SearchResult]:
        if query.retrieval_mode == RetrievalMode.DENSE_ONLY:
            return vector_search_service.search_similar_documents(query.query, top_k=query.top_k)

        if query.retrieval_mode == RetrievalMode.SPARSE_ONLY:
            return sparse_search_service.search(
                query.query,
                top_k=query.top_k,
                knowledge_base_ids=query.knowledge_base_ids,
            )

        if query.retrieval_mode != RetrievalMode.HYBRID:
            if query.retrieval_mode != RetrievalMode.HYBRID_RERANK:
                raise ValueError(f"Unsupported retrieval_mode: {query.retrieval_mode}")

        candidate_k = max(query.top_k * 4, query.top_k)
        dense_hits = vector_search_service.search_similar_documents(query.query, top_k=candidate_k)
        dense_hits = [self._annotate_recall(hit, source_name="dense") for hit in dense_hits]
        sparse_hits = sparse_search_service.search(
            query.query,
            top_k=candidate_k,
            knowledge_base_ids=query.knowledge_base_ids,
        )
        sparse_hits = [self._annotate_recall(hit, source_name="sparse") for hit in sparse_hits]
        fused = self.rrf_fusion_service.fuse(
            [("dense", dense_hits), ("sparse", sparse_hits)],
            top_k=max(query.top_k, config.rerank_top_k) if query.retrieval_mode == RetrievalMode.HYBRID_RERANK else query.top_k,
        )
        if query.retrieval_mode == RetrievalMode.HYBRID_RERANK:
            return rerank_service.rerank(query, fused)
        logger.info(
            "混合检索完成, query='{}', dense_hits={}, sparse_hits={}, fused_hits={}",
            query.query,
            len(dense_hits),
            len(sparse_hits),
            len(fused),
        )
        return fused

    def _annotate_recall(self, hit: SearchResult, source_name: str) -> SearchResult:
        metadata = dict(hit.metadata)
        metadata["recall_score"] = hit.score
        metadata[f"{source_name}_score"] = hit.score
        metadata["retrieval_mode"] = source_name
        return SearchResult(
            id=hit.id,
            content=hit.content,
            score=hit.score,
            metadata=metadata,
        )


hybrid_search_service = HybridSearchService()
