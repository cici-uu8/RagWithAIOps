"""P5 doc-level result aggregation tests.

锁定 (设计文档 docs/p5_doc_level_dedup_design.md):
- §1.1 硬口径: ``NONE`` 模式下 ``top_chunks_per_doc`` / ``doc_oversample_factor``
  必须绝对 no-op; ``DOC_LEVEL`` 是用户显式选择的另一条结果组织策略。
- §1.2 长度语义: ``DOC_LEVEL`` 下 ``len(results) ≤ top_k * top_chunks_per_doc``;
  每个 ``doc_id`` 出现次数 ≤ ``top_chunks_per_doc``。
- §2.3 doc 间排序: ``doc_hit_count`` 降 → ``doc_max_score`` 降 → ``doc_id`` 升。
- §2.4 三个观测位: ``aggregation_doc_hit_count`` / ``aggregation_doc_max_score`` /
  ``aggregation_dropped_chunk_ids``; 生命周期硬口径——不持久化, 不入 Milvus,
  不进 ``retrieve_knowledge`` artifact 稳定契约。
- §4 citation 不变性: 返回 result 的 ``chunk_id`` / ``content`` / ``source_ref`` /
  ``citation_text`` 与候选池内同 ``chunk_id`` 的那条 hit 逐字段相等。
- §3 与 P4.5 三 granularity 交互: ``DOC_LEVEL + chunk|parent_chunk|full_doc`` 都跑通。
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.models import (
    ChunkRecord,
    ContextGranularity,
    ParserEngine,
    ResultAggregation,
    RetrievalQuery,
    SourceRef,
)
from app.services.retrieval_service import retrieval_service
from app.services.vector_search_service import SearchResult as RawSearchResult


def _make_source_ref(chunk_id: str, doc_id: str = "doc_a") -> SourceRef:
    return SourceRef(
        kb_id="default",
        doc_id=doc_id,
        chunk_id=chunk_id,
        source_file=f"{doc_id}.md",
        page_start=None,
        page_end=None,
        heading_path=["第一章"],
        content_type="text",
        parser_engine=ParserEngine.PLAIN_TEXT,
    )


def _make_raw_hit(
    chunk_id: str,
    doc_id: str,
    *,
    score: float,
    content: str | None = None,
    parent_chunk_id: str | None = None,
) -> RawSearchResult:
    source_ref = _make_source_ref(chunk_id, doc_id=doc_id)
    metadata = {
        "kb_id": "default",
        "doc_id": doc_id,
        "chunk_id": chunk_id,
        "_file_name": f"{doc_id}.md",
        "heading_path": ["第一章"],
        "content_type": "text",
        "parser_engine": "plain_text",
        "source_ref": source_ref.model_dump(mode="json"),
    }
    if parent_chunk_id:
        metadata["parent_chunk_id"] = parent_chunk_id
    return RawSearchResult(
        id=chunk_id,
        content=content if content is not None else f"{chunk_id}-content",
        score=score,
        metadata=metadata,
    )


def _make_child_chunk(
    chunk_id: str,
    doc_id: str,
    chunk_index: int,
    content: str,
    parent_chunk_id: str | None = None,
) -> ChunkRecord:
    source_ref = _make_source_ref(chunk_id, doc_id=doc_id)
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id=doc_id,
        kb_id="default",
        content=content,
        chunk_index=chunk_index,
        start_index=chunk_index * 100,
        end_index=chunk_index * 100 + len(content),
        heading_path=["第一章"],
        page_start=None,
        page_end=None,
        content_type="text",
        source_ref=source_ref,
        quality_flags=[],
        metadata={
            "kb_id": "default",
            "doc_id": doc_id,
            "chunk_id": chunk_id,
            "content_type": "text",
            "parser_engine": "plain_text",
            "heading_path": ["第一章"],
            **({"parent_chunk_id": parent_chunk_id} if parent_chunk_id else {}),
        },
        parent_chunk_id=parent_chunk_id,
    )


def _make_parent_chunk(parent_id: str, doc_id: str, child_chunk_ids: list[str]) -> ChunkRecord:
    source_ref = _make_source_ref(parent_id, doc_id=doc_id)
    return ChunkRecord(
        chunk_id=parent_id,
        doc_id=doc_id,
        kb_id="default",
        content="parent-stitched-content",
        chunk_index=0,
        start_index=0,
        end_index=10,
        heading_path=["第一章"],
        page_start=None,
        page_end=None,
        content_type="section_parent",
        source_ref=source_ref,
        quality_flags=[],
        metadata={
            "kb_id": "default",
            "doc_id": doc_id,
            "chunk_id": parent_id,
            "content_type": "section_parent",
            "chunk_role": "parent",
            "child_chunk_ids": list(child_chunk_ids),
        },
        parent_chunk_id=None,
    )


class P5DocLevelAggregationTests(unittest.TestCase):
    # --- §1.1 默认与边界 ---

    def test_default_result_aggregation_is_none(self):
        """默认 RetrievalQuery 的 result_aggregation 是 NONE, 且高级字段有默认值。"""
        query = RetrievalQuery(query="default", top_k=3)
        self.assertEqual(query.result_aggregation, ResultAggregation.NONE)
        self.assertEqual(query.top_chunks_per_doc, 1)
        self.assertEqual(query.doc_oversample_factor, 4)

    def test_none_path_byteforbyte_equivalent_to_p45_baseline(self):
        """NONE 路径与 P4.5 baseline 字节级等价: results / chunk_ids / context_text 一致。"""
        raw_hits = [
            _make_raw_hit("c1", "doc_a", score=0.9),
            _make_raw_hit("c2", "doc_a", score=0.8),
            _make_raw_hit("c3", "doc_b", score=0.7),
        ]

        # baseline: P4.5 默认 query (无 P5 字段)
        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=raw_hits,
        ) as mock_search:
            response_baseline = retrieval_service.retrieve(
                RetrievalQuery(query="baseline", top_k=3)
            )
        self.assertEqual(mock_search.call_args.kwargs["top_k"], 3)

        # P5 显式 NONE
        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=raw_hits,
        ) as mock_search:
            response_none = retrieval_service.retrieve(
                RetrievalQuery(
                    query="baseline",
                    top_k=3,
                    result_aggregation=ResultAggregation.NONE,
                )
            )
        self.assertEqual(mock_search.call_args.kwargs["top_k"], 3)

        self.assertEqual(
            [(r.chunk_id, r.citation_text) for r in response_baseline.results],
            [(r.chunk_id, r.citation_text) for r in response_none.results],
        )
        self.assertEqual(response_baseline.context_text, response_none.context_text)

    def test_none_path_ignores_top_chunks_per_doc_and_oversample_factor(self):
        """硬口径 §1.1: NONE 模式下两个高级字段必须绝对 no-op。

        即使显式调大 top_chunks_per_doc / doc_oversample_factor 任何值,
        NONE 模式下:
        - 候选池不放大 (search 仍用 top_k)
        - 不挂 aggregation_* 观测位
        - 结果与 P4.5 baseline 完全等价
        """
        raw_hits = [
            _make_raw_hit("c1", "doc_a", score=0.9),
            _make_raw_hit("c2", "doc_a", score=0.8),
        ]

        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=raw_hits,
        ) as mock_search:
            response = retrieval_service.retrieve(
                RetrievalQuery(
                    query="absolute-noop",
                    top_k=2,
                    result_aggregation=ResultAggregation.NONE,
                    top_chunks_per_doc=99,
                    doc_oversample_factor=99,
                )
            )

        # 没有放大候选池
        self.assertEqual(mock_search.call_args.kwargs["top_k"], 2)
        # 没有挂任何 P5 观测位
        for result in response.results:
            self.assertNotIn("aggregation_doc_hit_count", result.metadata)
            self.assertNotIn("aggregation_doc_max_score", result.metadata)
            self.assertNotIn("aggregation_dropped_chunk_ids", result.metadata)

    # --- §2 算法核心 ---

    def test_doc_level_oversamples_candidate_pool(self):
        """§2.1 候选池放大: pool_k = max(top_k * doc_oversample_factor, top_k)。"""
        raw_hits = [_make_raw_hit(f"c{i}", "doc_a", score=1.0 - i * 0.01) for i in range(10)]

        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=raw_hits,
        ) as mock_search:
            retrieval_service.retrieve(
                RetrievalQuery(
                    query="oversample",
                    top_k=2,
                    result_aggregation=ResultAggregation.DOC_LEVEL,
                    doc_oversample_factor=4,
                )
            )

        # pool_k = max(2 * 4, 2) = 8
        self.assertEqual(mock_search.call_args.kwargs["top_k"], 8)

    def test_doc_level_groups_and_caps_per_doc(self):
        """每个 doc_id 在 results 中最多出现 top_chunks_per_doc 次。"""
        raw_hits = [
            _make_raw_hit("a1", "doc_a", score=0.9),
            _make_raw_hit("a2", "doc_a", score=0.85),
            _make_raw_hit("a3", "doc_a", score=0.8),
            _make_raw_hit("b1", "doc_b", score=0.7),
            _make_raw_hit("b2", "doc_b", score=0.65),
            _make_raw_hit("c1", "doc_c", score=0.6),
        ]

        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=raw_hits,
        ):
            response = retrieval_service.retrieve(
                RetrievalQuery(
                    query="cap-per-doc",
                    top_k=2,
                    result_aggregation=ResultAggregation.DOC_LEVEL,
                    top_chunks_per_doc=1,
                )
            )

        self.assertEqual(len(response.results), 2)
        doc_ids = [r.doc_id for r in response.results]
        self.assertEqual(doc_ids, ["doc_a", "doc_b"])  # hit_count 排序: A=3, B=2, C=1
        # top_chunks_per_doc=1 时每 doc 一条
        self.assertEqual(len(set(doc_ids)), 2)

    def test_doc_level_ranks_docs_by_hit_count_then_max_score_then_doc_id(self):
        """§2.3 doc 间排序三键: hit_count 降 → max_score 降 → doc_id 升。"""
        # 设计一个 hit_count 全部相等 (=2) 但 max_score / doc_id 不同的场景,
        # 验证次键 max_score 与稳定键 doc_id 都被使用。
        raw_hits = [
            # doc_z: hit=2, max=0.5
            _make_raw_hit("z1", "doc_z", score=0.5),
            _make_raw_hit("z2", "doc_z", score=0.4),
            # doc_x: hit=2, max=0.9 (应排在 doc_z 之前, 同 hit_count 下 max_score 更高)
            _make_raw_hit("x1", "doc_x", score=0.9),
            _make_raw_hit("x2", "doc_x", score=0.3),
            # doc_y: hit=2, max=0.9 (与 doc_x 平 → 走 doc_id 升序: x < y)
            _make_raw_hit("y1", "doc_y", score=0.9),
            _make_raw_hit("y2", "doc_y", score=0.2),
        ]

        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=raw_hits,
        ):
            response = retrieval_service.retrieve(
                RetrievalQuery(
                    query="ranking",
                    top_k=3,
                    result_aggregation=ResultAggregation.DOC_LEVEL,
                    top_chunks_per_doc=1,
                )
            )

        # 期望: doc_x (max=0.9, doc_id < doc_y), doc_y (max=0.9), doc_z (max=0.5)
        self.assertEqual([r.doc_id for r in response.results], ["doc_x", "doc_y", "doc_z"])

    def test_doc_level_attaches_aggregation_metadata(self):
        """§2.4 每条 result 挂三个观测位; dropped_chunk_ids 反映 cap 后被丢的 chunk。"""
        raw_hits = [
            _make_raw_hit("a1", "doc_a", score=0.9),
            _make_raw_hit("a2", "doc_a", score=0.85),
            _make_raw_hit("a3", "doc_a", score=0.8),
            _make_raw_hit("b1", "doc_b", score=0.7),
        ]

        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=raw_hits,
        ):
            response = retrieval_service.retrieve(
                RetrievalQuery(
                    query="metadata",
                    top_k=2,
                    result_aggregation=ResultAggregation.DOC_LEVEL,
                    top_chunks_per_doc=1,
                )
            )

        a_result = next(r for r in response.results if r.doc_id == "doc_a")
        b_result = next(r for r in response.results if r.doc_id == "doc_b")
        self.assertEqual(a_result.metadata["aggregation_doc_hit_count"], 3)
        self.assertEqual(a_result.metadata["aggregation_doc_max_score"], 0.9)
        self.assertEqual(
            sorted(a_result.metadata["aggregation_dropped_chunk_ids"]),
            ["a2", "a3"],
        )
        self.assertEqual(b_result.metadata["aggregation_doc_hit_count"], 1)
        self.assertEqual(b_result.metadata["aggregation_doc_max_score"], 0.7)
        self.assertEqual(b_result.metadata["aggregation_dropped_chunk_ids"], [])

    def test_doc_level_preserves_citation_identity_per_chunk(self):
        """§4 citation 不变性: 返回 result 的 chunk_id / content / source_ref /
        citation_text 与候选池内同 chunk_id 那条 hit 逐字段相等。"""
        raw_hits = [
            _make_raw_hit("a1", "doc_a", score=0.9, content="a1 content"),
            _make_raw_hit("b1", "doc_b", score=0.7, content="b1 content"),
        ]

        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=raw_hits,
        ):
            response_pool = retrieval_service.retrieve(
                RetrievalQuery(
                    query="identity-pool",
                    top_k=2,
                    result_aggregation=ResultAggregation.NONE,
                )
            )

        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=raw_hits,
        ):
            response_dedup = retrieval_service.retrieve(
                RetrievalQuery(
                    query="identity-dedup",
                    top_k=2,
                    result_aggregation=ResultAggregation.DOC_LEVEL,
                    top_chunks_per_doc=1,
                )
            )

        pool_by_id = {r.chunk_id: r for r in response_pool.results}
        # dedup 不发明新 chunk_id
        for r in response_dedup.results:
            self.assertIn(r.chunk_id, pool_by_id)
        # citation 四字段逐条相等
        for r in response_dedup.results:
            ref = pool_by_id[r.chunk_id]
            self.assertEqual(r.chunk_id, ref.chunk_id)
            self.assertEqual(r.content, ref.content)
            self.assertEqual(
                r.source_ref.model_dump(mode="json"),
                ref.source_ref.model_dump(mode="json"),
            )
            self.assertEqual(r.citation_text, ref.citation_text)

    def test_doc_level_length_caps(self):
        """§1.2 长度上限: len(results) ≤ top_k * top_chunks_per_doc;
        每个 doc_id 出现次数 ≤ top_chunks_per_doc。"""
        raw_hits = [
            _make_raw_hit("a1", "doc_a", score=0.9),
            _make_raw_hit("a2", "doc_a", score=0.85),
            _make_raw_hit("a3", "doc_a", score=0.8),
            _make_raw_hit("b1", "doc_b", score=0.7),
            _make_raw_hit("b2", "doc_b", score=0.65),
            _make_raw_hit("c1", "doc_c", score=0.6),
        ]
        top_k = 2
        cap = 2

        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=raw_hits,
        ):
            response = retrieval_service.retrieve(
                RetrievalQuery(
                    query="length-cap",
                    top_k=top_k,
                    result_aggregation=ResultAggregation.DOC_LEVEL,
                    top_chunks_per_doc=cap,
                )
            )

        # len(results) 上限
        self.assertLessEqual(len(response.results), top_k * cap)
        # 每个 doc 出现次数 ≤ cap
        from collections import Counter
        for doc_id, count in Counter(r.doc_id for r in response.results).items():
            self.assertLessEqual(count, cap, f"doc {doc_id} 出现 {count} 次, 超过 cap {cap}")
        # 在本数据下应是 [a1, a2, b1, b2] (doc_a + doc_b 各取 2 条)
        self.assertEqual(
            [r.chunk_id for r in response.results],
            ["a1", "a2", "b1", "b2"],
        )

    # --- §3 与 P4.5 三 granularity 交互 ---

    def test_doc_level_with_chunk_granularity(self):
        raw_hits = [
            _make_raw_hit("a1", "doc_a", score=0.9, content="a1 body"),
            _make_raw_hit("a2", "doc_a", score=0.85, content="a2 body"),
            _make_raw_hit("b1", "doc_b", score=0.7, content="b1 body"),
        ]
        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=raw_hits,
        ):
            response = retrieval_service.retrieve(
                RetrievalQuery(
                    query="dl-chunk",
                    top_k=2,
                    result_aggregation=ResultAggregation.DOC_LEVEL,
                    context_granularity=ContextGranularity.CHUNK,
                )
            )

        # 每条 result 的 expanded_context 是其自己的 content
        for r in response.results:
            self.assertEqual(r.metadata["expanded_context"], r.content)
        # context_text 仍按 P4.5 chunk 模式拼装
        self.assertIn("内容:\na1 body", response.context_text)
        self.assertIn("内容:\nb1 body", response.context_text)

    def test_doc_level_with_parent_chunk_granularity(self):
        parent_id = "doc_a:parent:00000"
        raw_hits = [
            _make_raw_hit("a1", "doc_a", score=0.9, parent_chunk_id=parent_id),
            _make_raw_hit("a2", "doc_a", score=0.85, parent_chunk_id=parent_id),
            _make_raw_hit("b1", "doc_b", score=0.7),
        ]
        parent_chunk = _make_parent_chunk(parent_id, "doc_a", ["a1", "a2"])

        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=raw_hits,
        ):
            with patch(
                "app.services.retrieval_service.knowledge_metadata_store.list_chunks_by_doc_id",
                return_value=[parent_chunk],
            ):
                response = retrieval_service.retrieve(
                    RetrievalQuery(
                        query="dl-parent",
                        top_k=2,
                        result_aggregation=ResultAggregation.DOC_LEVEL,
                        top_chunks_per_doc=1,
                        context_granularity=ContextGranularity.PARENT_CHUNK,
                    )
                )

        # dedup 后 doc_a 只剩一条 (a1), doc_b 剩 b1
        self.assertEqual([r.doc_id for r in response.results], ["doc_a", "doc_b"])
        a_result = next(r for r in response.results if r.doc_id == "doc_a")
        # parent_chunk 模式: doc_a 的 result expanded_context 是 parent 文本
        self.assertEqual(a_result.metadata["expanded_context"], "parent-stitched-content")
        # citation 仍指向子块 a1
        self.assertEqual(a_result.chunk_id, "a1")

    def test_doc_level_with_full_doc_granularity(self):
        raw_hits = [
            _make_raw_hit("a1", "doc_a", score=0.9, content="a1 body"),
            _make_raw_hit("a2", "doc_a", score=0.85, content="a2 body"),
            _make_raw_hit("b1", "doc_b", score=0.7, content="b1 body"),
        ]
        # full_doc 用的 metadata store 数据按 doc 分组
        store_by_doc = {
            "doc_a": [
                _make_child_chunk("a1", "doc_a", 0, "a1 full"),
                _make_child_chunk("a2", "doc_a", 1, "a2 full"),
            ],
            "doc_b": [_make_child_chunk("b1", "doc_b", 0, "b1 full")],
        }

        def fake_list_chunks(doc_id: str) -> list[ChunkRecord]:
            return store_by_doc.get(doc_id, [])

        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=raw_hits,
        ):
            with patch(
                "app.services.retrieval_service.knowledge_metadata_store.list_chunks_by_doc_id",
                side_effect=fake_list_chunks,
            ):
                response = retrieval_service.retrieve(
                    RetrievalQuery(
                        query="dl-fulldoc",
                        top_k=2,
                        result_aggregation=ResultAggregation.DOC_LEVEL,
                        top_chunks_per_doc=1,
                        context_granularity=ContextGranularity.FULL_DOC,
                    )
                )

        # dedup 后 doc_a 一条 + doc_b 一条
        a_result = next(r for r in response.results if r.doc_id == "doc_a")
        b_result = next(r for r in response.results if r.doc_id == "doc_b")
        # full_doc 模式拼整篇 doc 文本
        self.assertEqual(a_result.metadata["expanded_context"], "a1 full\n\na2 full")
        self.assertEqual(b_result.metadata["expanded_context"], "b1 full")
        # full_doc 模式下同 doc 重复拉问题被 dedup 顺带消除 (这是 §3 显式语义)
        self.assertEqual(response.context_text.count("a1 full\n\na2 full"), 1)

    # --- §2.4 观测位生命周期 ---

    def test_aggregation_observability_not_persisted_to_metadata_store(self):
        """三个观测位只挂在本次 retrieval response 上, 不回写到 metadata store。"""
        store_chunks = [
            _make_child_chunk("a1", "doc_a", 0, "a1 body"),
            _make_child_chunk("a2", "doc_a", 1, "a2 body"),
            _make_child_chunk("b1", "doc_b", 0, "b1 body"),
        ]

        raw_hits = [
            _make_raw_hit("a1", "doc_a", score=0.9, content="a1 body"),
            _make_raw_hit("a2", "doc_a", score=0.85, content="a2 body"),
            _make_raw_hit("b1", "doc_b", score=0.7, content="b1 body"),
        ]

        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=raw_hits,
        ):
            with patch(
                "app.services.retrieval_service.knowledge_metadata_store.list_chunks_by_doc_id",
                return_value=store_chunks,
            ):
                response = retrieval_service.retrieve(
                    RetrievalQuery(
                        query="lifecycle",
                        top_k=2,
                        result_aggregation=ResultAggregation.DOC_LEVEL,
                        top_chunks_per_doc=1,
                    )
                )

        # response 上挂了三个观测位
        for r in response.results:
            self.assertIn("aggregation_doc_hit_count", r.metadata)
            self.assertIn("aggregation_doc_max_score", r.metadata)
            self.assertIn("aggregation_dropped_chunk_ids", r.metadata)
        # metadata store 里的子块没有被回写
        for chunk in store_chunks:
            self.assertNotIn("aggregation_doc_hit_count", chunk.metadata)
            self.assertNotIn("aggregation_doc_max_score", chunk.metadata)
            self.assertNotIn("aggregation_dropped_chunk_ids", chunk.metadata)


if __name__ == "__main__":
    unittest.main()
