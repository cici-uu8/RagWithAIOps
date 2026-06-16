import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.enterprise.verifiers import CitationVerifier, VerificationStatus
from app.models import (
    ChunkRecord,
    ParserEngine,
    RetrievalQuery,
    RetrievalResponse,
    RetrievalResult,
    SourceRef,
)
from app.services.knowledge_metadata_store import KnowledgeMetadataStore
from app.services.vector_search_service import SearchResult as RawSearchResult
from evals.knowledge_base.run_department_rag_eval import verify_source_ref_integrity


def make_source_ref(
    *,
    kb_id: str = "kb-main",
    doc_id: str = "doc-1",
    chunk_id: str = "doc-1:c00001",
    source_file: str = "manual.md",
) -> SourceRef:
    return SourceRef(
        kb_id=kb_id,
        doc_id=doc_id,
        chunk_id=chunk_id,
        source_file=source_file,
        page_start=3,
        page_end=3,
        heading_path=["运行手册", "告警处理"],
        content_type="markdown_section",
        parser_engine=ParserEngine.PLAIN_TEXT,
    )


def make_chunk(
    *,
    kb_id: str = "kb-main",
    doc_id: str = "doc-1",
    chunk_id: str = "doc-1:c00001",
    source_file: str = "manual.md",
) -> ChunkRecord:
    source_ref = make_source_ref(
        kb_id=kb_id,
        doc_id=doc_id,
        chunk_id=chunk_id,
        source_file=source_file,
    )
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id=doc_id,
        kb_id=kb_id,
        content="CPU 告警处理步骤",
        chunk_index=0,
        start_index=0,
        end_index=10,
        heading_path=["运行手册", "告警处理"],
        page_start=3,
        page_end=3,
        content_type="markdown_section",
        source_ref=source_ref,
        quality_flags=[],
        metadata={
            "kb_id": kb_id,
            "doc_id": doc_id,
            "chunk_id": chunk_id,
            "_file_name": source_file,
            "_source": f"local://{source_file}",
            "title": "CPU 告警手册",
            "page_start": 3,
            "page_end": 3,
            "heading_path": ["运行手册", "告警处理"],
            "content_type": "markdown_section",
            "parser_engine": "plain_text",
            "source_ref": source_ref.model_dump(mode="json"),
        },
    )


class ChunkEvidenceMapperTests(unittest.TestCase):
    def test_from_index_metadata_builds_required_evidence_and_source_ref(self):
        from app.services.chunk_evidence_mapper import ChunkEvidenceMapper

        chunk = make_chunk()

        evidence = ChunkEvidenceMapper.from_index_metadata(
            chunk.metadata,
            score=0.42,
            retrieval_path="dense",
        )

        self.assertEqual(evidence.kb_id, "kb-main")
        self.assertEqual(evidence.doc_id, "doc-1")
        self.assertEqual(evidence.chunk_id, "doc-1:c00001")
        self.assertEqual(evidence.title, "CPU 告警手册")
        self.assertEqual(evidence.source_uri, "local://manual.md")
        self.assertEqual(evidence.score, 0.42)
        self.assertEqual(evidence.retrieval_path, "dense")
        self.assertEqual(evidence.page, 3)
        self.assertEqual(evidence.section, "运行手册 > 告警处理")
        self.assertEqual(evidence.source_ref.chunk_id, "doc-1:c00001")
        self.assertEqual(
            ChunkEvidenceMapper.validate_required_fields(evidence.model_dump(mode="json")),
            [],
        )

    def test_from_vector_hit_generates_legacy_chunk_id_fallback(self):
        from app.services.chunk_evidence_mapper import ChunkEvidenceMapper

        hit = RawSearchResult(
            id="",
            content="历史索引正文",
            score=0.7,
            metadata={
                "kb_id": "kb-legacy",
                "doc_id": "doc-legacy",
                "_file_name": "legacy.md",
                "parser_engine": "plain_text",
            },
        )

        evidence = ChunkEvidenceMapper.from_vector_hit(hit)

        self.assertTrue(evidence.chunk_id.startswith("doc-legacy:legacy:"))
        self.assertEqual(evidence.source_ref.chunk_id, evidence.chunk_id)
        self.assertTrue(evidence.metadata["evidence_diagnostics"]["legacy_chunk_id_fallback"])
        self.assertEqual(evidence.retrieval_path, "dense")

    def test_sparse_and_dense_hits_use_same_evidence_shape(self):
        from app.services.chunk_evidence_mapper import ChunkEvidenceMapper

        chunk = make_chunk()
        sparse_hit = RawSearchResult(
            id=chunk.chunk_id,
            content=chunk.content,
            score=2.5,
            metadata={**chunk.metadata, "retrieval_mode": "sparse_only"},
        )
        dense_hit = RawSearchResult(
            id=chunk.chunk_id,
            content=chunk.content,
            score=0.5,
            metadata={**chunk.metadata, "retrieval_mode": "dense"},
        )

        sparse_evidence = ChunkEvidenceMapper.from_sparse_hit(sparse_hit)
        dense_evidence = ChunkEvidenceMapper.from_vector_hit(dense_hit)

        for evidence in (sparse_evidence, dense_evidence):
            self.assertEqual(evidence.kb_id, "kb-main")
            self.assertEqual(evidence.doc_id, "doc-1")
            self.assertEqual(evidence.chunk_id, "doc-1:c00001")
            self.assertEqual(evidence.source_ref.chunk_id, "doc-1:c00001")
            self.assertEqual(evidence.title, "CPU 告警手册")
            self.assertEqual(evidence.source_uri, "local://manual.md")

    def test_from_retrieval_result_round_trips_result_identity(self):
        from app.services.chunk_evidence_mapper import ChunkEvidenceMapper

        source_ref = make_source_ref()
        result = RetrievalResult(
            kb_id="kb-main",
            doc_id="doc-1",
            chunk_id="doc-1:c00001",
            content="CPU 告警处理步骤",
            score=0.31,
            source_ref=source_ref,
            citation_text="[来源: manual.md, chunk: doc-1:c00001]",
            metadata={
                "title": "CPU 告警手册",
                "_source": "local://manual.md",
                "retrieval_mode": "hybrid_rerank",
                "rerank_score": 0.9,
            },
        )

        evidence = ChunkEvidenceMapper.from_retrieval_result(result)
        rebuilt_source_ref = ChunkEvidenceMapper.to_source_ref(evidence)

        self.assertEqual(evidence.retrieval_path, "hybrid_rerank")
        self.assertEqual(evidence.source_uri, "local://manual.md")
        self.assertEqual(evidence.metadata["rerank_score"], 0.9)
        self.assertEqual(rebuilt_source_ref.model_dump(mode="json"), source_ref.model_dump(mode="json"))


class ChunkEvidenceIntegrationTests(unittest.TestCase):
    def test_retrieval_service_attaches_mapper_evidence_for_dense_hits(self):
        from app.services.retrieval_service import retrieval_service

        chunk = make_chunk()
        raw_hit = RawSearchResult(
            id=chunk.chunk_id,
            content=chunk.content,
            score=0.19,
            metadata={**chunk.metadata, "retrieval_mode": "dense"},
        )

        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=[raw_hit],
        ):
            response = retrieval_service.retrieve(RetrievalQuery(query="CPU 告警", top_k=1))

        self.assertEqual(len(response.results), 1)
        result = response.results[0]
        evidence = result.metadata["chunk_evidence"]
        self.assertEqual(evidence["kb_id"], result.kb_id)
        self.assertEqual(evidence["doc_id"], result.doc_id)
        self.assertEqual(evidence["chunk_id"], result.chunk_id)
        self.assertEqual(evidence["source_ref"]["chunk_id"], result.chunk_id)
        self.assertEqual(evidence["retrieval_path"], "dense")

    def test_source_ref_integrity_helper_resolves_original_chunk(self):
        chunk = make_chunk()
        response = RetrievalResponse(
            query=RetrievalQuery(query="CPU 告警"),
            results=[
                RetrievalResult(
                    kb_id=chunk.kb_id,
                    doc_id=chunk.doc_id,
                    chunk_id=chunk.chunk_id,
                    content=chunk.content,
                    score=0.5,
                    source_ref=chunk.source_ref,
                    citation_text="[来源: manual.md, chunk: doc-1:c00001]",
                    metadata={**chunk.metadata, "chunk_evidence": chunk.metadata},
                )
            ],
            context_text=chunk.content,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            store = KnowledgeMetadataStore(Path(tmpdir) / "metadata.json")
            store.replace_chunks(chunk.doc_id, [chunk])

            report = verify_source_ref_integrity(
                response,
                metadata_store=store,
                allowed_kb_ids=["kb-main"],
            )

        self.assertTrue(report["all_resolvable"])
        self.assertEqual(report["results"][0]["status"], "resolved")
        self.assertEqual(report["results"][0]["source_uri"], "local://manual.md")

    def test_source_ref_integrity_helper_marks_unresolvable_and_cross_kb(self):
        source_ref = make_source_ref(kb_id="kb-hidden", doc_id="doc-hidden", chunk_id="doc-hidden:c00001")
        response = RetrievalResponse(
            query=RetrievalQuery(query="CPU 告警"),
            results=[
                RetrievalResult(
                    kb_id="kb-hidden",
                    doc_id="doc-hidden",
                    chunk_id="doc-hidden:c00001",
                    content="hidden",
                    score=0.5,
                    source_ref=source_ref,
                    citation_text="[来源: manual.md, chunk: doc-hidden:c00001]",
                    metadata={"source_ref": source_ref.model_dump(mode="json")},
                )
            ],
            context_text="hidden",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            store = KnowledgeMetadataStore(Path(tmpdir) / "metadata.json")

            report = verify_source_ref_integrity(
                response,
                metadata_store=store,
                allowed_kb_ids=["kb-main"],
            )

        self.assertFalse(report["all_resolvable"])
        self.assertEqual(report["results"][0]["status"], "citation_unresolvable")
        self.assertEqual(report["results"][0]["cross_scope_error"], True)

    def test_citation_verifier_fails_when_source_ref_required_fields_are_missing(self):
        result = CitationVerifier().verify(
            context=None,
            payload={
                "retrieval_response": {
                    "results": [
                        {
                            "kb_id": "kb-main",
                            "doc_id": "doc-1",
                            "chunk_id": "doc-1:c00001",
                            "source_ref": {
                                "doc_id": "doc-1",
                                "source_file": "manual.md",
                            },
                            "score": 0.4,
                        }
                    ]
                },
                "allowed_document_ids": ["doc-1"],
            },
        )

        self.assertEqual(result.status, VerificationStatus.FAILED)
        self.assertEqual(result.findings[0].code, "citation_source_ref_incomplete")
        self.assertIn("source_ref.kb_id", result.findings[0].metadata["missing_fields"])
        self.assertIn("source_ref.chunk_id", result.findings[0].metadata["missing_fields"])

    def test_knowledge_search_payload_exposes_top_level_chunk_evidence(self):
        from app.services.knowledge_search_service import _result_payload

        source_ref = make_source_ref()
        result = RetrievalResult(
            kb_id="kb-main",
            doc_id="doc-1",
            chunk_id="doc-1:c00001",
            content="CPU 告警处理步骤",
            score=0.31,
            source_ref=source_ref,
            citation_text="[来源: manual.md, chunk: doc-1:c00001]",
            metadata={
                "title": "CPU 告警手册",
                "_source": "local://manual.md",
                "retrieval_mode": "hybrid",
            },
        )

        payload = _result_payload(result)

        self.assertEqual(payload["chunk_evidence"]["kb_id"], "kb-main")
        self.assertEqual(payload["chunk_evidence"]["doc_id"], "doc-1")
        self.assertEqual(payload["chunk_evidence"]["chunk_id"], "doc-1:c00001")
        self.assertEqual(payload["chunk_evidence"]["source_ref"]["chunk_id"], "doc-1:c00001")
        self.assertEqual(payload["chunk_evidence"]["retrieval_path"], "hybrid")

    def test_retrieve_knowledge_artifact_exposes_top_level_chunk_evidence(self):
        import app.tools.knowledge_tool as knowledge_tool

        source_ref = make_source_ref()
        response = RetrievalResponse(
            query=RetrievalQuery(query="CPU 告警", top_k=1),
            results=[
                RetrievalResult(
                    kb_id="kb-main",
                    doc_id="doc-1",
                    chunk_id="doc-1:c00001",
                    content="CPU 告警处理步骤",
                    score=0.31,
                    source_ref=source_ref,
                    citation_text="[来源: manual.md, chunk: doc-1:c00001]",
                    metadata={
                        "title": "CPU 告警手册",
                        "_source": "local://manual.md",
                        "retrieval_mode": "dense",
                    },
                )
            ],
            context_text="CPU 告警处理步骤",
        )

        class FakeRetrievalService:
            def retrieve(self, query):
                return response

        with patch.object(knowledge_tool, "retrieval_service", FakeRetrievalService()):
            _content, artifact = knowledge_tool.retrieve_knowledge.func("CPU 告警")

        self.assertEqual(artifact["results"][0]["chunk_evidence"]["kb_id"], "kb-main")
        self.assertEqual(artifact["results"][0]["chunk_evidence"]["doc_id"], "doc-1")
        self.assertEqual(artifact["results"][0]["chunk_evidence"]["chunk_id"], "doc-1:c00001")
        self.assertEqual(
            artifact["results"][0]["chunk_evidence"]["source_ref"]["chunk_id"],
            "doc-1:c00001",
        )


if __name__ == "__main__":
    unittest.main()
