import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models import (
    ChunkRecord,
    ParserEngine,
    RetrievalMode,
    RetrievalQuery,
    SourceRef,
)
from app.services.knowledge_metadata_store import KnowledgeMetadataStore
from app.services.retrieval_service import retrieval_service
from app.services.vector_search_service import SearchResult as RawSearchResult


def build_chunk(
    chunk_id: str,
    content: str,
    source_file: str = "cpu_high_usage.md",
    heading_path: list[str] | None = None,
) -> ChunkRecord:
    heading_path = heading_path or ["CPU使用率过高告警处理方案", "排查步骤"]
    source_ref = SourceRef(
        kb_id="default",
        doc_id="doc_cpu",
        chunk_id=chunk_id,
        source_file=source_file,
        page_start=None,
        page_end=None,
        heading_path=heading_path,
        content_type="markdown_section",
        parser_engine=ParserEngine.PLAIN_TEXT,
    )
    metadata = {
        "kb_id": "default",
        "doc_id": "doc_cpu",
        "chunk_id": chunk_id,
        "_file_name": source_file,
        "heading_path": heading_path,
        "content_type": "markdown_section",
        "parser_engine": "plain_text",
        "source_ref": source_ref.model_dump(mode="json"),
    }
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id="doc_cpu",
        kb_id="default",
        content=content,
        chunk_index=0,
        start_index=0,
        end_index=len(content),
        heading_path=heading_path,
        page_start=None,
        page_end=None,
        content_type="markdown_section",
        source_ref=source_ref,
        quality_flags=[],
        metadata=metadata,
    )


def build_parent_chunk(
    chunk_id: str,
    content: str,
    source_file: str = "cpu_high_usage.md",
    heading_path: list[str] | None = None,
) -> ChunkRecord:
    heading_path = heading_path or ["CPU使用率过高告警处理方案", "排查步骤"]
    source_ref = SourceRef(
        kb_id="default",
        doc_id="doc_cpu",
        chunk_id=chunk_id,
        source_file=source_file,
        page_start=None,
        page_end=None,
        heading_path=heading_path,
        content_type="section_parent",
        parser_engine=ParserEngine.PLAIN_TEXT,
    )
    metadata = {
        "kb_id": "default",
        "doc_id": "doc_cpu",
        "chunk_id": chunk_id,
        "_file_name": source_file,
        "heading_path": heading_path,
        "content_type": "section_parent",
        "parser_engine": "plain_text",
        "source_ref": source_ref.model_dump(mode="json"),
        "chunk_role": "parent",
    }
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id="doc_cpu",
        kb_id="default",
        content=content,
        chunk_index=0,
        start_index=0,
        end_index=len(content),
        heading_path=heading_path,
        page_start=None,
        page_end=None,
        content_type="section_parent",
        source_ref=source_ref,
        quality_flags=[],
        metadata=metadata,
    )


class P3HybridRetrievalTests(unittest.TestCase):
    def test_sparse_only_retrieval_returns_citation_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_store = KnowledgeMetadataStore(Path(tmpdir) / "knowledge_metadata_store.json")
            chunk = build_chunk(
                "doc_cpu:c00001",
                "HighCPUUsage 告警需要查询 system-metrics 日志并检查 CPU 使用率。",
            )
            temp_store.replace_chunks("doc_cpu", [chunk])

            with patch("app.services.sparse_search_service.knowledge_metadata_store", temp_store):
                response = retrieval_service.retrieve(
                    RetrievalQuery(
                        query="HighCPUUsage system-metrics",
                        top_k=3,
                        retrieval_mode=RetrievalMode.SPARSE_ONLY,
                    )
                )

        self.assertEqual(len(response.results), 1)
        result = response.results[0]
        self.assertEqual(result.doc_id, "doc_cpu")
        self.assertEqual(result.chunk_id, "doc_cpu:c00001")
        self.assertEqual(result.source_ref.source_file, "cpu_high_usage.md")
        self.assertIn("chunk: doc_cpu:c00001", result.citation_text)

    def test_sparse_search_filters_out_section_parents(self):
        """Section parents must not enter BM25 corpus — they would dominate
        every query because their content is the concatenation of all child
        chunks under the same heading path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_store = KnowledgeMetadataStore(Path(tmpdir) / "knowledge_metadata_store.json")
            child = build_chunk(
                "doc_cpu:c00001",
                "HighCPUUsage 告警需要查询 system-metrics 日志。",
            )
            parent = build_parent_chunk(
                "doc_cpu:parent:00000",
                "HighCPUUsage 告警需要查询 system-metrics 日志。\n\n其他正文段。",
            )
            temp_store.replace_chunks("doc_cpu", [child, parent])

            with patch("app.services.sparse_search_service.knowledge_metadata_store", temp_store):
                response = retrieval_service.retrieve(
                    RetrievalQuery(
                        query="HighCPUUsage system-metrics",
                        top_k=3,
                        retrieval_mode=RetrievalMode.SPARSE_ONLY,
                    )
                )

        chunk_ids = [r.chunk_id for r in response.results]
        self.assertIn("doc_cpu:c00001", chunk_ids)
        self.assertNotIn("doc_cpu:parent:00000", chunk_ids)

    def test_hybrid_retrieval_uses_rrf_and_preserves_identity(self):
        dense_hit = RawSearchResult(
            id="doc_cpu:c00002",
            content="CPU 告警可能来自流量突增。",
            score=0.4,
            metadata=build_chunk("doc_cpu:c00002", "CPU 告警可能来自流量突增。").metadata,
        )
        sparse_hit = RawSearchResult(
            id="doc_cpu:c00001",
            content="HighCPUUsage 告警需要查询 system-metrics 日志。",
            score=5.0,
            metadata=build_chunk("doc_cpu:c00001", "HighCPUUsage 告警需要查询 system-metrics 日志。").metadata,
        )

        with patch(
            "app.services.hybrid_search_service.vector_search_service.search_similar_documents",
            return_value=[dense_hit],
        ):
            with patch(
                "app.services.hybrid_search_service.sparse_search_service.search",
                return_value=[sparse_hit],
            ):
                response = retrieval_service.retrieve(
                    RetrievalQuery(
                        query="HighCPUUsage system-metrics",
                        top_k=2,
                        retrieval_mode=RetrievalMode.HYBRID,
                    )
                )

        self.assertCountEqual(
            [result.chunk_id for result in response.results],
            ["doc_cpu:c00002", "doc_cpu:c00001"],
        )
        for result in response.results:
            self.assertEqual(result.doc_id, "doc_cpu")
            self.assertIn("fusion_score", result.metadata)
            self.assertIn("source_ref", result.metadata)
            self.assertEqual(result.source_ref.chunk_id, result.chunk_id)


if __name__ == "__main__":
    unittest.main()
