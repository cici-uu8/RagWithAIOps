"""C1 §10(b) enforcement tests: kb_id is required at production boundaries.

Locks the 2026-05-20 §10(b) decision (P6 permanently closed; aiops + manuals
must go to different kb_ids in production) into code via two enforcement points:

1. **API boundary**: `/api/upload` requires `kb_id` form param. No default.
   This is where production users actually exist; forcing the choice here
   means anyone uploading documents must declare which KB they belong to.

2. **Service boundary**: `DocumentIngestionService.ingest_upload(kb_id)`
   requires the kb_id parameter. Removing the implicit None→"default"
   fallback means internal callers (the API itself) must pass it.

Eval scripts continue to pass `kb_id="default"` explicitly to
`index_single_file(...)` for isolated temp Milvus collections. That explicit
eval convention does NOT contradict production §10(b) enforcement because eval
collections are isolated; they never share state with production.

Also locks the tool surface change: `retrieve_knowledge` now accepts an
optional `knowledge_base_ids` parameter so agents/planners can opt into
KB filtering, while `None` preserves the original "no filter" behavior.
"""

import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile

from fastapi.testclient import TestClient

from app.api import file as file_api
from app.models import DocumentRecord, DocumentStatus, ParserEngine
from app.services.document_ingestion_service import DocumentIngestionService


def _build_file_app():
    """Mirror the wiring used by other API tests."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(file_api.router, prefix="/api")
    return app


class IngestUploadRequiresKbIdTests(unittest.TestCase):
    """ingest_upload must require kb_id explicitly (no None→default fallback)."""

    def test_ingest_upload_with_none_kb_id_raises(self):
        service = DocumentIngestionService()
        with self.assertRaises((TypeError, ValueError)):
            service.ingest_upload(filename="x.md", content=b"hi", kb_id=None)  # type: ignore[arg-type]

    def test_ingest_upload_with_empty_string_kb_id_raises(self):
        service = DocumentIngestionService()
        with self.assertRaises(ValueError):
            service.ingest_upload(filename="x.md", content=b"hi", kb_id="")

    def test_ingest_upload_with_whitespace_kb_id_raises(self):
        service = DocumentIngestionService()
        with self.assertRaises(ValueError):
            service.ingest_upload(filename="x.md", content=b"hi", kb_id="   ")

    def test_ingest_upload_without_kb_id_kwarg_raises(self):
        """No positional/default fallback — caller must name kb_id."""
        service = DocumentIngestionService()
        with self.assertRaises(TypeError):
            service.ingest_upload(filename="x.md", content=b"hi")  # type: ignore[call-arg]


class UploadApiRequiresKbIdFormParamTests(unittest.TestCase):
    """POST /api/upload must require kb_id form param (HTTP 422 / 400 if missing)."""

    def test_upload_without_kb_id_form_param_returns_4xx(self):
        client = TestClient(_build_file_app())
        response = client.post(
            "/api/upload",
            files={"file": ("x.md", b"# hi\n\nbody", "text/markdown")},
        )
        # FastAPI's missing-required-form returns 422; either is fine
        # so long as the request is rejected before any ingestion happens.
        self.assertIn(response.status_code, (400, 422))

    def test_upload_with_empty_kb_id_returns_4xx(self):
        client = TestClient(_build_file_app())
        response = client.post(
            "/api/upload",
            files={"file": ("x.md", b"# hi\n\nbody", "text/markdown")},
            data={"kb_id": ""},
        )
        self.assertIn(response.status_code, (400, 422))

    def test_upload_with_kb_id_form_param_passes_through(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            upload_dir = Path(tmpdir) / "uploads"
            saved_path = upload_dir / "documents" / "aiops" / "doc_test" / "original" / "x.md"
            artifact_dir = upload_dir / "documents" / "aiops" / "doc_test" / "artifacts"
            captured: dict = {}

            def fake_ingest_upload(filename: str, content: bytes, kb_id: str):
                captured["kb_id"] = kb_id
                captured["filename"] = filename
                saved_path.parent.mkdir(parents=True, exist_ok=True)
                artifact_dir.mkdir(parents=True, exist_ok=True)
                saved_path.write_bytes(content)
                return DocumentRecord(
                    doc_id="doc_test",
                    kb_id=kb_id,
                    file_name=filename,
                    file_ext="md",
                    original_path=str(saved_path),
                    artifact_dir=str(artifact_dir),
                    parser_engine=ParserEngine.PLAIN_TEXT,
                    status=DocumentStatus.INDEXED,
                )

            with patch.object(file_api, "UPLOAD_DIR", upload_dir):
                with patch.object(
                    file_api.document_ingestion_service,
                    "ingest_upload",
                    fake_ingest_upload,
                ):
                    client = TestClient(_build_file_app())
                    response = client.post(
                        "/api/upload",
                        files={"file": ("x.md", b"# hi\n\nbody", "text/markdown")},
                        data={"kb_id": "aiops"},
                    )

            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(captured["kb_id"], "aiops")


class RetrieveKnowledgeKbFilterTests(unittest.TestCase):
    """retrieve_knowledge tool exposes optional knowledge_base_ids filter."""

    def test_tool_default_no_kb_filter_passes_empty_list(self):
        from app.tools import knowledge_tool as kt

        captured = {}

        class FakeService:
            def retrieve(self, query):
                captured["kb_ids"] = list(query.knowledge_base_ids)
                from app.models import RetrievalResponse
                return RetrievalResponse(
                    query=query,
                    results=[],
                    context_text="",
                    empty_message="no results",
                )

        with patch.object(kt, "retrieval_service", FakeService()):
            kt.retrieve_knowledge.invoke({"query": "x"})
        self.assertEqual(captured["kb_ids"], [])

    def test_tool_with_kb_ids_passes_filter(self):
        from app.tools import knowledge_tool as kt

        captured = {}

        class FakeService:
            def retrieve(self, query):
                captured["kb_ids"] = list(query.knowledge_base_ids)
                from app.models import RetrievalResponse
                return RetrievalResponse(
                    query=query,
                    results=[],
                    context_text="",
                    empty_message="no results",
                )

        with patch.object(kt, "retrieval_service", FakeService()):
            kt.retrieve_knowledge.invoke({"query": "x", "knowledge_base_ids": ["aiops", "manuals"]})
        self.assertEqual(captured["kb_ids"], ["aiops", "manuals"])


if __name__ == "__main__":
    unittest.main()
