import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models import (
    ChunkRecord,
    DocumentRecord,
    DocumentStatus,
    ParserEngine,
    RetrievalQuery,
    RetrievalResponse,
    RetrievalResult,
    SourceRef,
)
from app.services.document_health_check_service import (
    DocumentHealthCheckQueue,
    DocumentHealthCheckService,
    DocumentHealthCheckStore,
    DocumentHealthStatus,
)
from app.services.knowledge_metadata_store import KnowledgeMetadataStore
from app.services.vector_index_service import VectorIndexService


def _document(
    doc_id: str,
    kb_id: str,
    file_name: str,
    root: Path,
    *,
    parser_engine: ParserEngine = ParserEngine.PLAIN_TEXT,
) -> DocumentRecord:
    return DocumentRecord(
        doc_id=doc_id,
        kb_id=kb_id,
        file_name=file_name,
        file_ext=file_name.rsplit(".", 1)[-1],
        original_path=(root / file_name).as_posix(),
        artifact_dir=(root / doc_id / "artifacts").as_posix(),
        parser_engine=parser_engine,
        status=DocumentStatus.INDEXED,
    )


def _source_ref(
    *,
    doc_id: str = "doc-guide",
    kb_id: str = "guide",
    chunk_id: str = "doc-guide:c00001",
    file_name: str = "runbook.md",
    parser_engine: ParserEngine = ParserEngine.PLAIN_TEXT,
) -> SourceRef:
    return SourceRef(
        kb_id=kb_id,
        doc_id=doc_id,
        chunk_id=chunk_id,
        source_file=file_name,
        page_start=None,
        page_end=None,
        heading_path=["Runbook"],
        content_type="text",
        parser_engine=parser_engine,
    )


def _chunk(
    *,
    doc_id: str = "doc-guide",
    kb_id: str = "guide",
    chunk_id: str = "doc-guide:c00001",
    content: str = "CPU runbook explains high usage mitigation.",
    source_ref: SourceRef | None = None,
) -> ChunkRecord:
    ref = source_ref or _source_ref(doc_id=doc_id, kb_id=kb_id, chunk_id=chunk_id)
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id=doc_id,
        kb_id=kb_id,
        content=content,
        chunk_index=0,
        start_index=0,
        end_index=len(content),
        heading_path=["Runbook"],
        page_start=None,
        page_end=None,
        content_type="text",
        source_ref=ref,
        quality_flags=[],
        metadata={"source_ref": ref.model_dump(mode="json")},
    )


def _retrieval_hit(query: RetrievalQuery, doc_id: str = "doc-guide") -> RetrievalResult:
    source_ref = _source_ref(doc_id=doc_id, chunk_id=f"{doc_id}:c00001")
    return RetrievalResult(
        kb_id=source_ref.kb_id,
        doc_id=doc_id,
        chunk_id=source_ref.chunk_id,
        content="CPU runbook explains high usage mitigation.",
        score=0.1,
        source_ref=source_ref,
        citation_text=f"[来源: {source_ref.source_file}, chunk: {source_ref.chunk_id}]",
        metadata={"doc_id": doc_id},
    )


class FakeRetrievalService:
    def __init__(self, doc_ids_by_query: dict[str, list[str]] | None = None):
        self.doc_ids_by_query = doc_ids_by_query or {}
        self.calls: list[RetrievalQuery] = []

    def retrieve(self, query: RetrievalQuery) -> RetrievalResponse:
        self.calls.append(query)
        doc_ids = self.doc_ids_by_query.get(query.query, [])
        return RetrievalResponse(
            query=query,
            results=[_retrieval_hit(query, doc_id=doc_id) for doc_id in doc_ids],
            context_text="diagnostic",
        )


class DocumentHealthCheckServiceTests(unittest.TestCase):
    def _build_service(
        self,
        root: Path,
        *,
        retrieval_doc_ids_by_query: dict[str, list[str]] | None = None,
    ) -> tuple[
        KnowledgeMetadataStore,
        DocumentHealthCheckStore,
        DocumentHealthCheckService,
        FakeRetrievalService,
    ]:
        metadata_store = KnowledgeMetadataStore(root / "metadata.json")
        health_store = DocumentHealthCheckStore(root / "health.json")
        fake_retrieval = FakeRetrievalService(retrieval_doc_ids_by_query)
        service = DocumentHealthCheckService(
            metadata_store=metadata_store,
            health_store=health_store,
            retrieval_service=fake_retrieval,
        )
        return metadata_store, health_store, service, fake_retrieval

    def test_indexed_document_health_passes_when_retrieval_and_source_ref_are_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata_store, health_store, service, fake_retrieval = self._build_service(
                root,
                retrieval_doc_ids_by_query={
                    "cpu runbook": ["doc-guide"],
                    "CPU runbook explains high usage": ["doc-guide"],
                },
            )
            document = _document("doc-guide", "guide", "cpu_runbook.md", root)
            metadata_store.upsert_document(document)
            metadata_store.replace_chunks(document.doc_id, [_chunk()])

            result = service.run_check(document.doc_id)

        self.assertEqual(result.status, DocumentHealthStatus.PASSED)
        self.assertTrue(result.retrieval["passed"])
        self.assertEqual(result.retrieval["queries"][0]["rank"], 1)
        self.assertTrue(result.source_ref["passed"])
        self.assertTrue(result.pdf["passed"])
        self.assertEqual(result.pdf["skipped"], "not a PDF")
        self.assertEqual(health_store.get(document.doc_id).status, DocumentHealthStatus.PASSED)
        self.assertEqual(fake_retrieval.calls[0].knowledge_base_ids, ["guide"])
        self.assertEqual(fake_retrieval.calls[0].top_k, 3)

    def test_retrieval_no_hit_is_failed_without_changing_document_indexed_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata_store, _health_store, service, _fake_retrieval = self._build_service(root)
            document = _document("doc-guide", "guide", "cpu_runbook.md", root)
            metadata_store.upsert_document(document)
            metadata_store.replace_chunks(document.doc_id, [_chunk()])

            result = service.run_check(document.doc_id)

            stored_document = metadata_store.get_document(document.doc_id)

        self.assertEqual(result.status, DocumentHealthStatus.FAILED)
        self.assertFalse(result.retrieval["passed"])
        self.assertIn("retrieval_no_hit", result.summary)
        self.assertEqual(stored_document.status, DocumentStatus.INDEXED)

    def test_source_ref_mismatch_is_reported_separately(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata_store, _health_store, service, _fake_retrieval = self._build_service(
                root,
                retrieval_doc_ids_by_query={"cpu runbook": ["doc-guide"]},
            )
            document = _document("doc-guide", "guide", "cpu_runbook.md", root)
            wrong_ref = _source_ref(
                doc_id="other-doc",
                kb_id="guide",
                chunk_id="doc-guide:c00001",
            )
            metadata_store.upsert_document(document)
            metadata_store.replace_chunks(document.doc_id, [_chunk(source_ref=wrong_ref)])

            result = service.run_check(document.doc_id)

        self.assertEqual(result.status, DocumentHealthStatus.FAILED)
        self.assertTrue(result.retrieval["passed"])
        self.assertFalse(result.source_ref["passed"])
        self.assertIn("source_ref_doc_id_mismatch", result.source_ref["errors"][0])

    def test_pdf_artifact_problem_is_reported_separately(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata_store, _health_store, service, _fake_retrieval = self._build_service(
                root,
                retrieval_doc_ids_by_query={"manual": ["doc-pdf"]},
            )
            document = _document(
                "doc-pdf",
                "guide",
                "manual.pdf",
                root,
                parser_engine=ParserEngine.MINERU,
            )
            metadata_store.upsert_document(document)
            metadata_store.replace_chunks(
                document.doc_id,
                [
                    _chunk(
                        doc_id="doc-pdf",
                        chunk_id="doc-pdf:c00001",
                        content="Manual content",
                        source_ref=_source_ref(
                            doc_id="doc-pdf",
                            chunk_id="doc-pdf:c00001",
                            file_name="manual.pdf",
                            parser_engine=ParserEngine.MINERU,
                        ),
                    )
                ],
            )

            result = service.run_check(document.doc_id)

        self.assertEqual(result.status, DocumentHealthStatus.FAILED)
        self.assertTrue(result.retrieval["passed"])
        self.assertFalse(result.pdf["passed"])
        self.assertIn("pdf_artifact_missing_manifest", result.pdf["errors"][0])

    def test_queue_full_marks_skipped_and_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata_store, health_store, service, _fake_retrieval = self._build_service(root)
            document = _document("doc-guide", "guide", "cpu_runbook.md", root)
            metadata_store.upsert_document(document)

            queue = DocumentHealthCheckQueue(
                health_check_service=service,
                health_store=health_store,
                max_queue_size=0,
                max_concurrent=1,
                run_inline=True,
            )
            accepted = queue.enqueue(document.doc_id)

            result = health_store.get(document.doc_id)

        self.assertFalse(accepted)
        self.assertEqual(result.status, DocumentHealthStatus.SKIPPED)
        self.assertIn("queue_full", result.summary)

    def test_false_positive_mark_only_updates_health_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata_store, health_store, service, _fake_retrieval = self._build_service(root)
            document = _document("doc-guide", "guide", "cpu_runbook.md", root)
            metadata_store.upsert_document(document)
            metadata_store.replace_chunks(document.doc_id, [_chunk()])
            service.run_check(document.doc_id)

            updated = service.mark_false_positive(document.doc_id, "diagnostic query too narrow")
            stored_document = metadata_store.get_document(document.doc_id)

        self.assertTrue(updated.marked_as_false_positive)
        self.assertEqual(updated.false_positive_reason, "diagnostic query too narrow")
        self.assertEqual(health_store.get(document.doc_id).false_positive_reason, "diagnostic query too narrow")
        self.assertEqual(stored_document.status, DocumentStatus.INDEXED)

    def test_vector_index_health_hook_is_non_blocking(self):
        class RecordingQueue:
            def __init__(self):
                self.doc_ids: list[str] = []

            def enqueue(self, doc_id: str) -> bool:
                self.doc_ids.append(doc_id)
                raise RuntimeError("queue down")

        queue = RecordingQueue()
        service = VectorIndexService()

        with patch("app.services.document_health_check_service.document_health_check_queue", queue):
            service._enqueue_document_health_check("doc-guide")

        self.assertEqual(queue.doc_ids, ["doc-guide"])


if __name__ == "__main__":
    unittest.main()
