import unittest
from unittest.mock import patch

from app.config import config
from app.models import (
    ChunkRecord,
    ParserEngine,
    RetrievalQuery,
    RetrievalResponse,
    RetrievalResult,
    SourceRef,
)
from app.services.retrieval_service import retrieval_service
from app.services.vector_search_service import SearchResult as RawSearchResult


class FakeRetrievalToolService:
    def __init__(self, response: RetrievalResponse):
        self.response = response
        self.calls = []

    def retrieve(self, query: RetrievalQuery) -> RetrievalResponse:
        self.calls.append(query)
        return self.response


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


class RetrievalServiceTests(unittest.TestCase):
    def test_retrieval_service_builds_structured_citation_artifact(self):
        source_ref = _make_source_ref()
        raw_hit = RawSearchResult(
            id="doc_pdf:c00001",
            content="第一段正文",
            score=0.125,
            metadata={
                "kb_id": "default",
                "doc_id": "doc_pdf",
                "chunk_id": "doc_pdf:c00001",
                "_file_name": "manual.pdf",
                "_source": "/tmp/manual.pdf",
                "page_start": 2,
                "page_end": 3,
                "heading_path": ["第一章", "概述"],
                "content_type": "text",
                "parser_engine": "mineru",
                "source_ref": source_ref.model_dump(mode="json"),
            },
        )

        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=[raw_hit],
        ):
            response = retrieval_service.retrieve(RetrievalQuery(query="正文内容是什么", top_k=3))

        self.assertEqual(response.query.query, "正文内容是什么")
        self.assertEqual(response.query.top_k, 3)
        self.assertEqual(len(response.results), 1)

        result = response.results[0]
        self.assertEqual(result.kb_id, "default")
        self.assertEqual(result.doc_id, "doc_pdf")
        self.assertEqual(result.chunk_id, "doc_pdf:c00001")
        self.assertEqual(result.score, 0.125)
        self.assertEqual(result.source_ref.doc_id, "doc_pdf")
        self.assertEqual(
            result.citation_text,
            "[来源: manual.pdf, 页码: 2-3, 章节: 第一章 > 概述, chunk: doc_pdf:c00001]",
        )
        self.assertIn(
            "定位: [来源: manual.pdf, 页码: 2-3, 章节: 第一章 > 概述, chunk: doc_pdf:c00001]",
            response.context_text,
        )
        self.assertIn("第一段正文", response.context_text)

    def test_retrieval_service_returns_empty_citation_response_when_no_hits(self):
        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=[],
        ):
            response = retrieval_service.retrieve(RetrievalQuery(query="找不到的内容", top_k=3))

        self.assertEqual(response.results, [])
        self.assertEqual(response.context_text, "没有找到相关信息。")
        self.assertEqual(response.empty_message, "没有找到相关信息。")

    def test_retrieval_service_attaches_parent_content_when_child_hit_has_parent(self):
        source_ref = _make_source_ref(chunk_id="doc_pdf:c00001")
        raw_hit = RawSearchResult(
            id="doc_pdf:c00001",
            content="第一段正文",
            score=0.5,
            metadata={
                "kb_id": "default",
                "doc_id": "doc_pdf",
                "chunk_id": "doc_pdf:c00001",
                "_file_name": "manual.pdf",
                "page_start": 2,
                "page_end": 3,
                "heading_path": ["第一章", "概述"],
                "content_type": "text",
                "parser_engine": "mineru",
                "parent_chunk_id": "doc_pdf:parent:00000",
                "source_ref": source_ref.model_dump(mode="json"),
            },
        )
        parent_source_ref = _make_source_ref(
            chunk_id="doc_pdf:parent:00000",
            content_type="section_parent",
        )
        parent_chunk = ChunkRecord(
            chunk_id="doc_pdf:parent:00000",
            doc_id="doc_pdf",
            kb_id="default",
            content="第一段正文\n\n第二段正文",
            chunk_index=0,
            start_index=0,
            end_index=20,
            heading_path=["第一章", "概述"],
            page_start=2,
            page_end=3,
            content_type="section_parent",
            source_ref=parent_source_ref,
            quality_flags=[],
            metadata={"chunk_role": "parent"},
            parent_chunk_id=None,
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
                    RetrievalQuery(query="第一章 概述", top_k=3)
                )

        self.assertEqual(len(response.results), 1)
        result = response.results[0]
        # citation/content 仍然指向子块
        self.assertEqual(result.chunk_id, "doc_pdf:c00001")
        self.assertEqual(result.content, "第一段正文")
        self.assertIn("chunk: doc_pdf:c00001", result.citation_text)
        # parent 文本通过 metadata 暴露
        self.assertEqual(result.metadata["parent_chunk_id"], "doc_pdf:parent:00000")
        self.assertEqual(result.metadata["parent_content"], "第一段正文\n\n第二段正文")
        self.assertEqual(result.metadata["parent_heading_path"], ["第一章", "概述"])

    def test_retrieval_service_skips_parent_lookup_when_child_has_no_parent(self):
        source_ref = _make_source_ref(chunk_id="doc_pdf:c00002")
        raw_hit = RawSearchResult(
            id="doc_pdf:c00002",
            content="孤立段落",
            score=0.5,
            metadata={
                "kb_id": "default",
                "doc_id": "doc_pdf",
                "chunk_id": "doc_pdf:c00002",
                "_file_name": "manual.pdf",
                "heading_path": ["第一章"],
                "content_type": "text",
                "parser_engine": "mineru",
                "source_ref": source_ref.model_dump(mode="json"),
            },
        )

        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=[raw_hit],
        ):
            with patch(
                "app.services.retrieval_service.knowledge_metadata_store.list_chunks_by_doc_id",
            ) as load_chunks:
                response = retrieval_service.retrieve(
                    RetrievalQuery(query="孤立段落", top_k=3)
                )

        load_chunks.assert_not_called()
        self.assertEqual(len(response.results), 1)
        self.assertNotIn("parent_content", response.results[0].metadata)

    def test_retrieve_knowledge_tool_returns_structured_artifact(self):
        source_ref = SourceRef(
            kb_id="default",
            doc_id="doc_pdf",
            chunk_id="doc_pdf:c00001",
            source_file="manual.pdf",
            page_start=4,
            page_end=4,
            heading_path=["第二章", "参数"],
            content_type="manual_table",
            parser_engine=ParserEngine.MINERU,
        )
        response = RetrievalResponse(
            query=RetrievalQuery(query="参数表", top_k=config.rag_top_k),
            results=[
                RetrievalResult(
                    kb_id="default",
                    doc_id="doc_pdf",
                    chunk_id="doc_pdf:table:t00001",
                    content="| 名称 | 值 |",
                    score=0.2,
                    source_ref=source_ref,
                    citation_text="[来源: manual.pdf, 页码: 4, 章节: 第二章 > 参数, chunk: doc_pdf:table:t00001]",
                    metadata={"kb_id": "default", "doc_id": "doc_pdf"},
                )
            ],
            context_text="【参考资料 1】\n来源: manual.pdf\n定位: [来源: manual.pdf, 页码: 4, 章节: 第二章 > 参数, chunk: doc_pdf:table:t00001]\n内容:\n| 名称 | 值 |\n",
        )
        fake_service = FakeRetrievalToolService(response)

        import app.tools.knowledge_tool as knowledge_tool_module

        with patch.object(knowledge_tool_module, "retrieval_service", fake_service):
            content, artifact = knowledge_tool_module.retrieve_knowledge.func("参数表在哪里")

        self.assertEqual(content, response.context_text)
        self.assertEqual(len(fake_service.calls), 1)
        self.assertEqual(fake_service.calls[0].query, "参数表在哪里")
        self.assertEqual(fake_service.calls[0].top_k, config.rag_top_k)
        self.assertEqual(artifact["query"]["query"], "参数表在哪里")
        self.assertEqual(artifact["results"][0]["citation_text"], response.results[0].citation_text)
        self.assertEqual(artifact["results"][0]["source_ref"]["chunk_id"], "doc_pdf:table:t00001")

    def test_retrieve_knowledge_tool_default_retrieval_mode_stays_dense_only(self):
        response = RetrievalResponse(
            query=RetrievalQuery(query="默认模式"),
            results=[],
            context_text="没有找到相关信息。",
        )
        fake_service = FakeRetrievalToolService(response)

        import app.tools.knowledge_tool as knowledge_tool_module

        with patch.object(knowledge_tool_module, "retrieval_service", fake_service):
            with patch.object(knowledge_tool_module.config, "rag_default_retrieval_mode", "dense_only"):
                _, artifact = knowledge_tool_module.retrieve_knowledge.func("默认模式")

        self.assertEqual(fake_service.calls[0].retrieval_mode.value, "dense_only")
        self.assertEqual(artifact["query"]["retrieval_mode"], "dense_only")

    def test_retrieve_knowledge_tool_uses_configured_hybrid_mode_without_tool_parameter(self):
        response = RetrievalResponse(
            query=RetrievalQuery(query="hybrid 模式", retrieval_mode="hybrid"),
            results=[],
            context_text="没有找到相关信息。",
        )
        fake_service = FakeRetrievalToolService(response)

        import app.tools.knowledge_tool as knowledge_tool_module

        with patch.object(knowledge_tool_module, "retrieval_service", fake_service):
            with patch.object(knowledge_tool_module.config, "rag_default_retrieval_mode", "hybrid"):
                _, artifact = knowledge_tool_module.retrieve_knowledge.func("hybrid 模式")

        self.assertEqual(fake_service.calls[0].retrieval_mode.value, "hybrid")
        self.assertEqual(artifact["query"]["retrieval_mode"], "hybrid")
        self.assertNotIn("retrieval_mode", knowledge_tool_module.retrieve_knowledge.args)


if __name__ == "__main__":
    unittest.main()
