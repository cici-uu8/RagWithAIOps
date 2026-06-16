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
from app.services.rerank_service import rerank_service
from app.services.retrieval_service import retrieval_service
from app.services.vector_search_service import SearchResult as RawSearchResult


def build_chunk(chunk_id: str, content: str, source_file: str) -> ChunkRecord:
    source_ref = SourceRef(
        kb_id="default",
        doc_id="doc_gate",
        chunk_id=chunk_id,
        source_file=source_file,
        page_start=None,
        page_end=None,
        heading_path=["P3 门禁"],
        content_type="markdown_section",
        parser_engine=ParserEngine.PLAIN_TEXT,
    )
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id="doc_gate",
        kb_id="default",
        content=content,
        chunk_index=0,
        start_index=0,
        end_index=len(content),
        heading_path=["P3 门禁"],
        page_start=None,
        page_end=None,
        content_type="markdown_section",
        source_ref=source_ref,
        quality_flags=[],
        metadata={
            "kb_id": "default",
            "doc_id": "doc_gate",
            "chunk_id": chunk_id,
            "_file_name": source_file,
            "heading_path": ["P3 门禁"],
            "content_type": "markdown_section",
            "parser_engine": "plain_text",
            "source_ref": source_ref.model_dump(mode="json"),
        },
    )


def build_hit(chunk_id: str, content: str, source_file: str, score: float) -> RawSearchResult:
    source_ref = SourceRef(
        kb_id="default",
        doc_id="doc_gate",
        chunk_id=chunk_id,
        source_file=source_file,
        page_start=None,
        page_end=None,
        heading_path=["P3 门禁"],
        content_type="markdown_section",
        parser_engine=ParserEngine.PLAIN_TEXT,
    )
    return RawSearchResult(
        id=chunk_id,
        content=content,
        score=score,
        metadata={
            "kb_id": "default",
            "doc_id": "doc_gate",
            "chunk_id": chunk_id,
            "_file_name": source_file,
            "heading_path": ["P3 门禁"],
            "content_type": "markdown_section",
            "parser_engine": "plain_text",
            "source_ref": source_ref.model_dump(mode="json"),
            "fusion_score": score,
        },
    )


class P3RetrievalGateTests(unittest.TestCase):
    def test_p3_modes_keep_citation_identity_and_rerank_boundary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_store = KnowledgeMetadataStore(Path(tmpdir) / "knowledge_metadata_store.json")
            sparse_chunk = build_chunk("doc_gate:c00001", "BM25 需要命中的 P3 门禁文本。", "gate_sparse.md")
            temp_store.replace_chunks("doc_gate", [sparse_chunk])

            dense_hit = build_hit(
                "doc_gate:c00002",
                "Dense 命中的 P3 门禁文本。",
                "gate_dense.md",
                0.2,
            )
            sparse_hit = build_hit(
                "doc_gate:c00001",
                "BM25 需要命中的 P3 门禁文本。",
                "gate_sparse.md",
                5.0,
            )

            with patch("app.services.retrieval_service.vector_search_service.search_similar_documents", return_value=[dense_hit]):
                dense_response = retrieval_service.retrieve(
                    RetrievalQuery(query="P3 门禁", top_k=3, retrieval_mode=RetrievalMode.DENSE_ONLY)
                )

            with patch("app.services.sparse_search_service.knowledge_metadata_store", temp_store):
                sparse_response = retrieval_service.retrieve(
                    RetrievalQuery(query="BM25 需要命中", top_k=3, retrieval_mode=RetrievalMode.SPARSE_ONLY)
                )

            with patch("app.services.hybrid_search_service.vector_search_service.search_similar_documents", return_value=[dense_hit]):
                with patch("app.services.hybrid_search_service.sparse_search_service.search", return_value=[sparse_hit]):
                    hybrid_response = retrieval_service.retrieve(
                        RetrievalQuery(query="P3 门禁", top_k=2, retrieval_mode=RetrievalMode.HYBRID)
                    )

            original_rerank_enabled = rerank_service.enabled
            try:
                rerank_service.enabled = True
                with patch("app.services.hybrid_search_service.vector_search_service.search_similar_documents", return_value=[dense_hit]):
                    with patch("app.services.hybrid_search_service.sparse_search_service.search", return_value=[sparse_hit]):
                        rerank_response = retrieval_service.retrieve(
                            RetrievalQuery(query="P3 门禁", top_k=2, retrieval_mode=RetrievalMode.HYBRID_RERANK)
                        )
            finally:
                rerank_service.enabled = original_rerank_enabled

        self.assertEqual(dense_response.results[0].source_ref.chunk_id, "doc_gate:c00002")
        self.assertEqual(dense_response.results[0].metadata["recall_score"], 0.2)
        self.assertEqual(sparse_response.results[0].source_ref.chunk_id, "doc_gate:c00001")
        self.assertIn("recall_score", sparse_response.results[0].metadata)
        self.assertIn("fusion_score", hybrid_response.results[0].metadata)
        self.assertEqual(hybrid_response.results[0].source_ref.chunk_id, hybrid_response.results[0].chunk_id)
        self.assertIn("rerank_score", rerank_response.results[0].metadata)
        self.assertEqual(rerank_response.results[0].metadata["retrieval_mode"], "hybrid_rerank")


if __name__ == "__main__":
    unittest.main()
