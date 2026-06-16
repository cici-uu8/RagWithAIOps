import unittest
from unittest.mock import patch

from app.models import ParserEngine, RetrievalMode, RetrievalQuery, SourceRef
from app.services.rerank_service import RerankService
from app.services.vector_search_service import SearchResult as RawSearchResult


def build_hit(chunk_id: str, content: str, score: float = 0.1) -> RawSearchResult:
    source_ref = SourceRef(
        kb_id="default",
        doc_id="doc_cpu",
        chunk_id=chunk_id,
        source_file="cpu_high_usage.md",
        heading_path=["CPU使用率过高告警处理方案"],
        content_type="markdown_section",
        parser_engine=ParserEngine.PLAIN_TEXT,
    )
    return RawSearchResult(
        id=chunk_id,
        content=content,
        score=score,
        metadata={
            "kb_id": "default",
            "doc_id": "doc_cpu",
            "chunk_id": chunk_id,
            "_file_name": "cpu_high_usage.md",
            "heading_path": ["CPU使用率过高告警处理方案"],
            "content_type": "markdown_section",
            "parser_engine": "plain_text",
            "source_ref": source_ref.model_dump(mode="json"),
            "fusion_score": score,
        },
    )


class BrokenScorer:
    def score(self, query: str, candidates: list[RawSearchResult]) -> list[float]:
        raise TimeoutError("rerank timeout")


class P3RerankServiceTests(unittest.TestCase):
    def test_enabled_rerank_reorders_candidates_without_changing_identity(self):
        weak_hit = build_hit("doc_cpu:c00002", "CPU 告警可能来自流量突增。", 0.4)
        strong_hit = build_hit(
            "doc_cpu:c00001",
            "HighCPUUsage 告警需要查询 system-metrics 日志并检查 CPU 使用率。",
            0.3,
        )

        reranker = RerankService(enabled=True)
        ranked = reranker.rerank(
            query=RetrievalQuery(
                query="HighCPUUsage system-metrics",
                top_k=2,
                retrieval_mode=RetrievalMode.HYBRID_RERANK,
            ),
            candidates=[weak_hit, strong_hit],
        )

        self.assertEqual([hit.id for hit in ranked], ["doc_cpu:c00001", "doc_cpu:c00002"])
        self.assertEqual(ranked[0].metadata["chunk_id"], "doc_cpu:c00001")
        self.assertEqual(ranked[0].metadata["source_ref"]["chunk_id"], "doc_cpu:c00001")
        self.assertIn("rerank_score", ranked[0].metadata)
        self.assertEqual(ranked[0].metadata["retrieval_mode"], "hybrid_rerank")

    def test_rerank_failure_falls_back_to_fused_candidates(self):
        candidates = [
            build_hit("doc_cpu:c00002", "CPU 告警可能来自流量突增。", 0.4),
            build_hit("doc_cpu:c00001", "HighCPUUsage 告警需要查询 system-metrics 日志。", 0.3),
        ]

        reranker = RerankService(enabled=True, scorer=BrokenScorer())
        ranked = reranker.rerank(
            query=RetrievalQuery(
                query="HighCPUUsage system-metrics",
                top_k=2,
                retrieval_mode=RetrievalMode.HYBRID_RERANK,
            ),
            candidates=candidates,
        )

        self.assertEqual([hit.id for hit in ranked], ["doc_cpu:c00002", "doc_cpu:c00001"])
        self.assertEqual(ranked[0].metadata["rerank_status"], "fallback")
        self.assertIn("rerank timeout", ranked[0].metadata["rerank_error"])

    def test_disabled_rerank_is_explicit_and_stable(self):
        candidates = [
            build_hit("doc_cpu:c00002", "CPU 告警可能来自流量突增。", 0.4),
            build_hit("doc_cpu:c00001", "HighCPUUsage 告警需要查询 system-metrics 日志。", 0.3),
            build_hit("doc_cpu:c00003", "CPU 历史曲线可以辅助排查。", 0.2),
        ]

        reranker = RerankService(enabled=False)
        ranked = reranker.rerank(
            query=RetrievalQuery(
                query="HighCPUUsage system-metrics",
                top_k=2,
                retrieval_mode=RetrievalMode.HYBRID_RERANK,
            ),
            candidates=candidates,
        )

        self.assertEqual([hit.id for hit in ranked], ["doc_cpu:c00002", "doc_cpu:c00001"])
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0].metadata["rerank_status"], "disabled")

    def test_retrieval_service_routes_hybrid_rerank_mode(self):
        from app.services.retrieval_service import retrieval_service

        candidates = [
            build_hit("doc_cpu:c00002", "CPU 告警可能来自流量突增。", 0.4),
            build_hit("doc_cpu:c00001", "HighCPUUsage 告警需要查询 system-metrics 日志。", 0.3),
        ]

        with patch(
            "app.services.retrieval_service.hybrid_search_service.search",
            return_value=candidates,
        ) as mocked_search:
            response = retrieval_service.retrieve(
                RetrievalQuery(
                    query="HighCPUUsage system-metrics",
                    top_k=2,
                    retrieval_mode=RetrievalMode.HYBRID_RERANK,
                )
            )

        mocked_search.assert_called_once()
        called_query = mocked_search.call_args.args[0]
        self.assertEqual(called_query.retrieval_mode, RetrievalMode.HYBRID_RERANK)
        self.assertEqual([result.chunk_id for result in response.results], ["doc_cpu:c00002", "doc_cpu:c00001"])


if __name__ == "__main__":
    unittest.main()
