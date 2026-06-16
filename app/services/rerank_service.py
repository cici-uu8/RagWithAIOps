"""Explicit rerank boundary for P3 retrieval experiments."""

from __future__ import annotations

import re
import time
from collections import Counter
from typing import Protocol

from loguru import logger

from app.config import config
from app.models import RetrievalQuery
from app.services.chunk_text_helpers import build_search_text
from app.services.vector_search_service import SearchResult


class RerankScorer(Protocol):
    """Score fused candidates for a query without mutating candidate identity."""

    def score(self, query: str, candidates: list[SearchResult]) -> list[float]:
        ...


class LexicalRerankScorer:
    """Dependency-free local rerank baseline used until an external model is wired."""

    def score(self, query: str, candidates: list[SearchResult]) -> list[float]:
        query_terms = self._tokenize(query)
        if not query_terms:
            return [0.0 for _ in candidates]

        query_term_set = set(query_terms)
        scores: list[float] = []
        for candidate in candidates:
            candidate_terms = self._tokenize(self._candidate_text(candidate))
            if not candidate_terms:
                scores.append(0.0)
                continue

            term_counts = Counter(candidate_terms)
            overlap = sum(1 for term in query_term_set if term_counts.get(term, 0) > 0)
            coverage = overlap / len(query_term_set)
            density = overlap / len(set(candidate_terms))
            phrase_bonus = 0.1 if query.lower() in candidate.content.lower() else 0.0
            scores.append(coverage + density + phrase_bonus)
        return scores

    def _candidate_text(self, candidate: SearchResult) -> str:
        return build_search_text(candidate.metadata.get("heading_path"), candidate.content)

    def _tokenize(self, text: str) -> list[str]:
        tokens: list[str] = []
        for part in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", text.lower()):
            if re.fullmatch(r"[\u4e00-\u9fff]+", part):
                tokens.extend(part)
                tokens.extend(part[index : index + 2] for index in range(max(0, len(part) - 1)))
            else:
                tokens.append(part)
        return [token for token in tokens if token.strip()]


class RerankService:
    """Reorder fused candidates while preserving citation identity."""

    def __init__(
        self,
        enabled: bool | None = None,
        scorer: RerankScorer | None = None,
        timeout_ms: int | None = None,
        max_candidates: int | None = None,
        fallback_on_error: bool | None = None,
    ):
        self.enabled = config.rerank_enabled if enabled is None else enabled
        self.scorer = scorer or LexicalRerankScorer()
        self.timeout_ms = config.rerank_timeout_ms if timeout_ms is None else timeout_ms
        self.max_candidates = config.rerank_top_k if max_candidates is None else max_candidates
        self.fallback_on_error = (
            config.rerank_fallback_on_error if fallback_on_error is None else fallback_on_error
        )
        self.model_id = config.rerank_model
        logger.info(
            "Rerank 服务初始化完成, enabled={}, model={}, timeout_ms={}",
            self.enabled,
            self.model_id,
            self.timeout_ms,
        )

    def rerank(self, query: RetrievalQuery, candidates: list[SearchResult]) -> list[SearchResult]:
        if not candidates:
            return []

        candidates = candidates[: max(query.top_k, self.max_candidates)]
        if not self.enabled:
            return self._annotate(candidates[: query.top_k], status="disabled")

        started_at = time.perf_counter()
        try:
            scores = self.scorer.score(query.query, candidates)
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            if duration_ms > self.timeout_ms:
                raise TimeoutError(f"rerank timeout after {duration_ms}ms")
            if len(scores) != len(candidates):
                raise ValueError("rerank scorer returned an invalid score count")

            ranked_pairs = sorted(
                enumerate(zip(candidates, scores, strict=True)),
                key=lambda item: (-item[1][1], item[0]),
            )
            ranked = [
                self._copy_with_metadata(
                    candidate,
                    retrieval_mode="hybrid_rerank",
                    rerank_score=score,
                    rerank_status="applied",
                    rerank_model=self.model_id,
                    rerank_latency_ms=duration_ms,
                )
                for _, (candidate, score) in ranked_pairs
            ]
            logger.info(
                "Rerank 完成, query='{}', input={}, output={}, latency_ms={}",
                query.query,
                len(candidates),
                len(ranked[: query.top_k]),
                duration_ms,
            )
            return ranked[: query.top_k]
        except Exception as exc:
            if not self.fallback_on_error:
                raise
            logger.warning("Rerank 失败，回退 fused candidates: {}", exc)
            return self._annotate(candidates[: query.top_k], status="fallback", error=str(exc))

    def _annotate(
        self,
        candidates: list[SearchResult],
        status: str,
        error: str = "",
    ) -> list[SearchResult]:
        return [
            self._copy_with_metadata(
                candidate,
                retrieval_mode="hybrid_rerank",
                rerank_score=None,
                rerank_status=status,
                rerank_model=self.model_id,
                rerank_error=error,
            )
            for candidate in candidates
        ]

    def _copy_with_metadata(self, result: SearchResult, **metadata_updates: object) -> SearchResult:
        metadata = dict(result.metadata)
        metadata.update(metadata_updates)
        return SearchResult(
            id=result.id,
            content=result.content,
            score=result.score,
            metadata=metadata,
        )


rerank_service = RerankService()
