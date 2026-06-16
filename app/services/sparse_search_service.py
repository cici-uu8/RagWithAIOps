"""BM25 sparse retrieval over persisted chunk metadata."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Sequence

from loguru import logger

from app.models import ChunkRecord
from app.services.chunk_text_helpers import build_search_text
from app.services.knowledge_metadata_store import knowledge_metadata_store
from app.services.vector_search_service import SearchResult


class SparseSearchService:
    """Small BM25 sidecar retriever for P3 hybrid recall."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        logger.info("BM25 稀疏检索服务初始化完成")

    def search(
        self,
        query: str,
        top_k: int = 3,
        knowledge_base_ids: Sequence[str] | None = None,
    ) -> list[SearchResult]:
        chunks = knowledge_metadata_store.list_chunks(list(knowledge_base_ids or []))
        # Section parents 含所有子块文本拼接，会污染 BM25 corpus 与召回结果，
        # 由 dense / sparse 路径都过滤掉；它们只用于检索后回溯父块上下文。
        chunks = [chunk for chunk in chunks if chunk.metadata.get("chunk_role") != "parent"]
        if not chunks:
            return []

        query_terms = self._tokenize(query)
        if not query_terms:
            return []

        corpus_terms = [self._tokenize(self._chunk_search_text(chunk)) for chunk in chunks]
        avgdl = sum(len(terms) for terms in corpus_terms) / len(corpus_terms)
        doc_freqs = self._document_frequencies(corpus_terms)

        scored: list[tuple[float, ChunkRecord]] = []
        for chunk, terms in zip(chunks, corpus_terms, strict=True):
            score = self._bm25_score(
                query_terms=query_terms,
                document_terms=terms,
                document_frequencies=doc_freqs,
                total_documents=len(chunks),
                avg_document_length=avgdl,
            )
            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
        results: list[SearchResult] = []
        for score, chunk in scored[:top_k]:
            metadata = dict(chunk.metadata)
            metadata["retrieval_mode"] = "sparse_only"
            metadata["recall_score"] = score
            metadata["sparse_score"] = score
            results.append(
                SearchResult(
                    id=chunk.chunk_id,
                    content=chunk.content,
                    score=score,
                    metadata=metadata,
                )
            )

        logger.info("BM25 稀疏检索完成, query='{}', hits={}", query, len(results))
        return results

    def _chunk_search_text(self, chunk: ChunkRecord) -> str:
        return build_search_text(chunk.heading_path, chunk.content)

    def _tokenize(self, text: str) -> list[str]:
        tokens: list[str] = []
        for part in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", text.lower()):
            if re.fullmatch(r"[\u4e00-\u9fff]+", part):
                tokens.extend(part)
                tokens.extend(part[index : index + 2] for index in range(max(0, len(part) - 1)))
            else:
                tokens.append(part)
        return [token for token in tokens if token.strip()]

    def _document_frequencies(self, corpus_terms: list[list[str]]) -> Counter[str]:
        document_frequencies: Counter[str] = Counter()
        for terms in corpus_terms:
            document_frequencies.update(set(terms))
        return document_frequencies

    def _bm25_score(
        self,
        query_terms: list[str],
        document_terms: list[str],
        document_frequencies: Counter[str],
        total_documents: int,
        avg_document_length: float,
    ) -> float:
        if not document_terms or avg_document_length <= 0:
            return 0.0

        term_counts = Counter(document_terms)
        document_length = len(document_terms)
        score = 0.0
        for term in query_terms:
            term_frequency = term_counts.get(term, 0)
            if term_frequency == 0:
                continue
            document_frequency = document_frequencies.get(term, 0)
            idf = math.log(1 + (total_documents - document_frequency + 0.5) / (document_frequency + 0.5))
            denominator = term_frequency + self.k1 * (
                1 - self.b + self.b * document_length / avg_document_length
            )
            score += idf * (term_frequency * (self.k1 + 1)) / denominator
        return score


sparse_search_service = SparseSearchService()
