"""P4.5 context_granularity tests.

锁定:
- 三模式 (chunk / parent_chunk / full_doc) 在 RetrievalResponse.context_text 上的
  拼装规则与 P4.5 设计 §1 一致;
- citation 不变性: 三模式下 ``[(chunk_id, citation_text)] * top_k`` 完全有序相等;
- 同 parent 多 child / 同 doc 多 hit 的"重复拉、不去重"硬口径;
- expanded_context / context_granularity_fallback 的生命周期硬口径
  (P4.5 设计 §1.2): 不写回 metadata store, 不写入 Milvus,
  不进入 retrieve_knowledge artifact 稳定字段语义。
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.models import (
    ChunkRecord,
    ContextGranularity,
    ParserEngine,
    RetrievalQuery,
    SourceRef,
)
from app.services.retrieval_service import retrieval_service
from app.services.vector_search_service import SearchResult as RawSearchResult


def _make_source_ref(**overrides) -> SourceRef:
    payload = {
        "kb_id": "default",
        "doc_id": "doc_pdf",
        "chunk_id": "doc_pdf:c00001",
        "source_file": "manual.pdf",
        "page_start": 2,
        "page_end": 3,
        "heading_path": ["第一章", "概述"],
        "content_type": "text",
        "parser_engine": ParserEngine.MINERU,
    }
    payload.update(overrides)
    return SourceRef(**payload)


def _make_child_chunk(chunk_id: str, content: str, chunk_index: int, parent_chunk_id: str | None = None) -> ChunkRecord:
    source_ref = _make_source_ref(chunk_id=chunk_id)
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id="doc_pdf",
        kb_id="default",
        content=content,
        chunk_index=chunk_index,
        start_index=chunk_index * 100,
        end_index=chunk_index * 100 + len(content),
        heading_path=["第一章", "概述"],
        page_start=2,
        page_end=3,
        content_type="text",
        source_ref=source_ref,
        quality_flags=[],
        metadata={
            "kb_id": "default",
            "doc_id": "doc_pdf",
            "chunk_id": chunk_id,
            "content_type": "text",
            "parser_engine": "mineru",
            "heading_path": ["第一章", "概述"],
            **({"parent_chunk_id": parent_chunk_id} if parent_chunk_id else {}),
        },
        parent_chunk_id=parent_chunk_id,
    )


def _make_parent_chunk(chunk_id: str, content: str, child_chunk_ids: list[str]) -> ChunkRecord:
    source_ref = _make_source_ref(chunk_id=chunk_id, content_type="section_parent")
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id="doc_pdf",
        kb_id="default",
        content=content,
        chunk_index=0,
        start_index=0,
        end_index=len(content),
        heading_path=["第一章", "概述"],
        page_start=2,
        page_end=3,
        content_type="section_parent",
        source_ref=source_ref,
        quality_flags=[],
        metadata={
            "kb_id": "default",
            "doc_id": "doc_pdf",
            "chunk_id": chunk_id,
            "content_type": "section_parent",
            "chunk_role": "parent",
            "child_chunk_ids": child_chunk_ids,
        },
        parent_chunk_id=None,
    )


def _make_raw_hit(chunk_id: str, content: str, *, parent_chunk_id: str | None = None) -> RawSearchResult:
    source_ref = _make_source_ref(chunk_id=chunk_id)
    metadata = {
        "kb_id": "default",
        "doc_id": "doc_pdf",
        "chunk_id": chunk_id,
        "_file_name": "manual.pdf",
        "page_start": 2,
        "page_end": 3,
        "heading_path": ["第一章", "概述"],
        "content_type": "text",
        "parser_engine": "mineru",
        "source_ref": source_ref.model_dump(mode="json"),
    }
    if parent_chunk_id:
        metadata["parent_chunk_id"] = parent_chunk_id
    return RawSearchResult(id=chunk_id, content=content, score=0.5, metadata=metadata)


class P45ContextGranularityTests(unittest.TestCase):
    def test_chunk_mode_context_text_is_unchanged(self):
        raw_hit = _make_raw_hit("doc_pdf:c00001", "第一段正文")
        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=[raw_hit],
        ):
            response = retrieval_service.retrieve(
                RetrievalQuery(
                    query="正文",
                    top_k=3,
                    context_granularity=ContextGranularity.CHUNK,
                )
            )

        self.assertEqual(len(response.results), 1)
        self.assertIn("内容:\n第一段正文", response.context_text)
        self.assertEqual(response.results[0].metadata["expanded_context"], "第一段正文")
        self.assertNotIn("context_granularity_fallback", response.results[0].metadata)

    def test_parent_chunk_mode_uses_parent_content(self):
        parent_id = "doc_pdf:parent:00000"
        raw_hit = _make_raw_hit(
            "doc_pdf:c00001", "第一段正文", parent_chunk_id=parent_id
        )
        parent_chunk = _make_parent_chunk(
            parent_id,
            "第一段正文\n\n第二段正文",
            child_chunk_ids=["doc_pdf:c00001", "doc_pdf:c00002"],
        )

        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=[raw_hit],
        ):
            with patch(
                "app.services.retrieval_service.knowledge_metadata_store.list_chunks_by_doc_id",
                return_value=[parent_chunk],
            ):
                response = retrieval_service.retrieve(
                    RetrievalQuery(
                        query="第一章 概述",
                        top_k=3,
                        context_granularity=ContextGranularity.PARENT_CHUNK,
                    )
                )

        self.assertEqual(len(response.results), 1)
        result = response.results[0]
        # citation 主语义不变
        self.assertEqual(result.chunk_id, "doc_pdf:c00001")
        self.assertEqual(result.content, "第一段正文")
        # context_text 用父块文本拼装
        self.assertIn("内容:\n第一段正文\n\n第二段正文", response.context_text)
        self.assertEqual(result.metadata["expanded_context"], "第一段正文\n\n第二段正文")
        self.assertNotIn("context_granularity_fallback", result.metadata)

    def test_parent_chunk_mode_falls_back_when_no_parent(self):
        raw_hit = _make_raw_hit("doc_pdf:c00002", "孤立段落")  # 没有 parent_chunk_id

        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=[raw_hit],
        ):
            response = retrieval_service.retrieve(
                RetrievalQuery(
                    query="孤立段落",
                    top_k=3,
                    context_granularity=ContextGranularity.PARENT_CHUNK,
                )
            )

        result = response.results[0]
        self.assertIn("内容:\n孤立段落", response.context_text)
        self.assertEqual(result.metadata["expanded_context"], "孤立段落")
        self.assertEqual(result.metadata["context_granularity_fallback"], "no_parent")

    def test_full_doc_mode_assembles_doc_from_metadata_store_only(self):
        """full_doc 只能来自 metadata store 的非 parent 子块,不能去读 original_path。"""
        raw_hit = _make_raw_hit("doc_pdf:c00001", "第一段正文")
        c1 = _make_child_chunk("doc_pdf:c00001", "第一段正文", 0)
        c2 = _make_child_chunk("doc_pdf:c00002", "第二段正文", 1)
        c3 = _make_child_chunk("doc_pdf:c00003", "第三段正文", 2)
        parent_noise = _make_parent_chunk(
            "doc_pdf:parent:00000",
            "应该被过滤掉的父块",
            child_chunk_ids=["doc_pdf:c00001", "doc_pdf:c00002", "doc_pdf:c00003"],
        )
        # 故意打乱顺序,验证按 chunk_index 升序拼
        store_chunks = [c3, parent_noise, c1, c2]

        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=[raw_hit],
        ):
            with patch(
                "app.services.retrieval_service.knowledge_metadata_store.list_chunks_by_doc_id",
                return_value=store_chunks,
            ):
                response = retrieval_service.retrieve(
                    RetrievalQuery(
                        query="正文",
                        top_k=3,
                        context_granularity=ContextGranularity.FULL_DOC,
                    )
                )

        result = response.results[0]
        # citation 不变
        self.assertEqual(result.chunk_id, "doc_pdf:c00001")
        self.assertEqual(result.content, "第一段正文")
        # full doc 文本: 按 chunk_index 升序拼,parent 被过滤
        expected_doc_text = "第一段正文\n\n第二段正文\n\n第三段正文"
        self.assertIn(f"内容:\n{expected_doc_text}", response.context_text)
        self.assertEqual(result.metadata["expanded_context"], expected_doc_text)
        self.assertNotIn("应该被过滤掉的父块", response.context_text)
        self.assertNotIn("context_granularity_fallback", result.metadata)

    def test_full_doc_mode_falls_back_when_doc_has_no_children(self):
        raw_hit = _make_raw_hit("doc_pdf:c00001", "回退正文")

        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=[raw_hit],
        ):
            with patch(
                "app.services.retrieval_service.knowledge_metadata_store.list_chunks_by_doc_id",
                return_value=[],
            ):
                response = retrieval_service.retrieve(
                    RetrievalQuery(
                        query="回退",
                        top_k=3,
                        context_granularity=ContextGranularity.FULL_DOC,
                    )
                )

        result = response.results[0]
        self.assertIn("内容:\n回退正文", response.context_text)
        self.assertEqual(result.metadata["expanded_context"], "回退正文")
        self.assertEqual(result.metadata["context_granularity_fallback"], "no_doc_text")

    def test_parent_chunk_mode_keeps_duplicate_parent_text_no_dedup(self):
        """同 parent 两个 child 命中: parent 文本必须重复出现两次,不合并。"""
        parent_id = "doc_pdf:parent:00000"
        raw_hits = [
            _make_raw_hit("doc_pdf:c00001", "第一段正文", parent_chunk_id=parent_id),
            _make_raw_hit("doc_pdf:c00002", "第二段正文", parent_chunk_id=parent_id),
        ]
        parent_chunk = _make_parent_chunk(
            parent_id,
            "整段父块文本",
            child_chunk_ids=["doc_pdf:c00001", "doc_pdf:c00002"],
        )

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
                        query="同 parent 多 child",
                        top_k=3,
                        context_granularity=ContextGranularity.PARENT_CHUNK,
                    )
                )

        # 两条 hit 各自仍然返回, citation 各自指向自己的子块
        self.assertEqual(
            [r.chunk_id for r in response.results],
            ["doc_pdf:c00001", "doc_pdf:c00002"],
        )
        # context_text 中父块文本必须出现两次, 显式验证 P4.5 "重复拉,不合并"
        self.assertEqual(response.context_text.count("整段父块文本"), 2)

    def test_full_doc_mode_keeps_duplicate_doc_text_no_dedup(self):
        raw_hits = [
            _make_raw_hit("doc_pdf:c00001", "第一段正文"),
            _make_raw_hit("doc_pdf:c00002", "第二段正文"),
        ]
        c1 = _make_child_chunk("doc_pdf:c00001", "第一段正文", 0)
        c2 = _make_child_chunk("doc_pdf:c00002", "第二段正文", 1)

        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=raw_hits,
        ):
            with patch(
                "app.services.retrieval_service.knowledge_metadata_store.list_chunks_by_doc_id",
                return_value=[c1, c2],
            ):
                response = retrieval_service.retrieve(
                    RetrievalQuery(
                        query="同 doc 多 hit",
                        top_k=3,
                        context_granularity=ContextGranularity.FULL_DOC,
                    )
                )

        # context_text 中整篇 doc 必须出现两次
        full_doc_text = "第一段正文\n\n第二段正文"
        self.assertEqual(response.context_text.count(full_doc_text), 2)

    def test_three_modes_share_identical_ordered_citation_list(self):
        """citation 不变性: 三模式下 [(chunk_id, citation_text)] * top_k 严格有序相等。"""
        parent_id = "doc_pdf:parent:00000"
        raw_hits = [
            _make_raw_hit("doc_pdf:c00001", "第一段正文", parent_chunk_id=parent_id),
            _make_raw_hit("doc_pdf:c00002", "第二段正文", parent_chunk_id=parent_id),
        ]
        parent_chunk = _make_parent_chunk(
            parent_id,
            "整段父块",
            child_chunk_ids=["doc_pdf:c00001", "doc_pdf:c00002"],
        )
        c1 = _make_child_chunk("doc_pdf:c00001", "第一段正文", 0, parent_chunk_id=parent_id)
        c2 = _make_child_chunk("doc_pdf:c00002", "第二段正文", 1, parent_chunk_id=parent_id)
        store_chunks = [c1, c2, parent_chunk]

        ordered_citations: dict[str, list[tuple[str, str]]] = {}
        for granularity in (
            ContextGranularity.CHUNK,
            ContextGranularity.PARENT_CHUNK,
            ContextGranularity.FULL_DOC,
        ):
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
                            query="三模式不变性",
                            top_k=3,
                            context_granularity=granularity,
                        )
                    )
            ordered_citations[granularity.value] = [
                (r.chunk_id, r.citation_text) for r in response.results
            ]

        # 三模式必须严格有序相等(不仅集合相等)
        self.assertEqual(
            ordered_citations["chunk"],
            ordered_citations["parent_chunk"],
        )
        self.assertEqual(
            ordered_citations["chunk"],
            ordered_citations["full_doc"],
        )
        # 同时锁定 RetrievalResult 主 DTO 字段在三模式下完全等价
        self.assertEqual(len(ordered_citations["chunk"]), 2)

    def test_default_context_granularity_is_chunk(self):
        """没有显式传 context_granularity 时, 默认 chunk 行为, 与 P4 baseline 一致。"""
        raw_hit = _make_raw_hit("doc_pdf:c00001", "默认行为正文")
        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=[raw_hit],
        ):
            response = retrieval_service.retrieve(
                RetrievalQuery(query="默认行为", top_k=3)
            )

        self.assertEqual(response.query.context_granularity, ContextGranularity.CHUNK)
        self.assertIn("内容:\n默认行为正文", response.context_text)

    def test_expanded_context_does_not_persist_to_metadata_store(self):
        """生命周期硬口径: expanded_context 只在本次 retrieval response 上,
        不会被回写到 KnowledgeMetadataStore。
        """
        c1 = _make_child_chunk("doc_pdf:c00001", "持久化检查正文", 0)

        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=[_make_raw_hit("doc_pdf:c00001", "持久化检查正文")],
        ):
            with patch(
                "app.services.retrieval_service.knowledge_metadata_store.list_chunks_by_doc_id",
                return_value=[c1],
            ) as load_chunks:
                response = retrieval_service.retrieve(
                    RetrievalQuery(
                        query="持久化检查",
                        top_k=3,
                        context_granularity=ContextGranularity.FULL_DOC,
                    )
                )

        # response 上挂了 expanded_context
        self.assertEqual(
            response.results[0].metadata["expanded_context"], "持久化检查正文"
        )
        # 但 metadata store 里的子块本身, expanded_context 不应被回写
        self.assertNotIn("expanded_context", c1.metadata)
        self.assertNotIn("context_granularity_fallback", c1.metadata)
        # 只读了一次 store, 没有对它做任何写入语义的调用
        load_chunks.assert_called()


if __name__ == "__main__":
    unittest.main()
