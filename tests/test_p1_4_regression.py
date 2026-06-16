import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.file as file_api
import app.services.vector_index_service as vector_index_module
from app.models import DocumentRecord, DocumentStatus, ParserEngine
from app.services.knowledge_metadata_store import KnowledgeMetadataStore


class FakeVectorStoreManager:
    def __init__(self):
        self.deleted_sources: list[str] = []
        self.added_documents = []

    def delete_by_doc_id(self, doc_id: str) -> int:
        return 0

    def delete_by_source(self, file_path: str) -> int:
        self.deleted_sources.append(file_path)
        return 0

    def add_documents(self, documents):
        self.added_documents.extend(documents)
        return [f"fake-{index}" for index, _ in enumerate(documents)]


def build_file_app() -> FastAPI:
    app = FastAPI()
    app.include_router(file_api.router, prefix="/api")
    return app


class P14RegressionTests(unittest.TestCase):
    def test_index_single_file_enriches_chunk_metadata_with_stable_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            sample_path = tmp_path / "cpu_high_usage.md"
            sample_path.write_text(
                "# CPU 告警\n\n## 现象\n\nCPU 持续升高，需要排查业务线程和系统负载。\n",
                encoding="utf-8",
            )

            fake_manager = FakeVectorStoreManager()
            temp_store = KnowledgeMetadataStore(tmp_path / "knowledge_metadata_store.json")

            with patch.object(vector_index_module, "vector_store_manager", fake_manager):
                with patch.object(vector_index_module, "knowledge_metadata_store", temp_store):
                    service = vector_index_module.VectorIndexService()
                    service.index_single_file(str(sample_path), kb_id="default")

                    expected_doc_id = service._build_doc_id("default", sample_path)
                    document = temp_store.get_document(expected_doc_id)
                    self.assertIsNotNone(document)
                    self.assertEqual(document.status, DocumentStatus.INDEXED)
                    self.assertEqual(document.parser_engine, ParserEngine.PLAIN_TEXT)

                    chunks = temp_store.list_chunks_by_doc_id(expected_doc_id)
                    self.assertEqual(len(chunks), 1)
                    chunk = chunks[0]

                    self.assertEqual(chunk.doc_id, expected_doc_id)
                    self.assertTrue(chunk.chunk_id.startswith(f"{expected_doc_id}:c"))
                    self.assertEqual(chunk.source_ref.doc_id, expected_doc_id)
                    self.assertEqual(chunk.metadata["kb_id"], "default")
                    self.assertEqual(chunk.metadata["doc_id"], expected_doc_id)
                    self.assertEqual(chunk.metadata["chunk_id"], chunk.chunk_id)
                    self.assertEqual(chunk.metadata["_source"], sample_path.resolve().as_posix())
                    self.assertEqual(chunk.metadata["_file_name"], sample_path.name)
                    self.assertEqual(chunk.metadata["_extension"], ".md")
                    self.assertEqual(chunk.metadata["source_ref"]["source_file"], sample_path.name)

                    self.assertEqual(
                        fake_manager.deleted_sources,
                        [sample_path.resolve().as_posix()],
                    )
                    self.assertEqual(len(fake_manager.added_documents), len(chunks))

    def test_upload_keeps_success_response_shape_for_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            upload_dir = Path(tmpdir) / "uploads"
            saved_path = upload_dir / "documents" / "default" / "doc_test" / "original" / "notes.md"
            artifact_dir = upload_dir / "documents" / "default" / "doc_test" / "artifacts"

            def fake_ingest_upload(filename: str, content: bytes, kb_id: str = "default"):
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
                    client = TestClient(build_file_app())
                    response = client.post(
                        "/api/upload",
                        files={"file": ("notes.md", b"# Title\n\nBody", "text/markdown")},
                        data={"kb_id": "default"},
                    )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["code"], 200)
            self.assertEqual(payload["message"], "success")
            self.assertEqual(payload["data"]["filename"], "notes.md")

            self.assertTrue(saved_path.exists())
            self.assertEqual(payload["data"]["file_path"], str(saved_path))
            self.assertEqual(payload["data"]["size"], len(b"# Title\n\nBody"))
            self.assertEqual(payload["data"]["doc_id"], "doc_test")
            self.assertEqual(payload["data"]["parser_engine"], "plain_text")
            self.assertEqual(payload["data"]["status"], "indexed")
            self.assertEqual(payload["data"]["artifact_dir"], str(artifact_dir))

    def test_upload_still_returns_success_when_indexing_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            upload_dir = Path(tmpdir) / "uploads"
            saved_path = upload_dir / "documents" / "default" / "doc_fail" / "original" / "notes.txt"
            artifact_dir = upload_dir / "documents" / "default" / "doc_fail" / "artifacts"

            def fake_ingest_upload(filename: str, content: bytes, kb_id: str = "default"):
                saved_path.parent.mkdir(parents=True, exist_ok=True)
                artifact_dir.mkdir(parents=True, exist_ok=True)
                saved_path.write_bytes(content)
                return DocumentRecord(
                    doc_id="doc_fail",
                    kb_id=kb_id,
                    file_name=filename,
                    file_ext="txt",
                    original_path=str(saved_path),
                    artifact_dir=str(artifact_dir),
                    parser_engine=ParserEngine.PLAIN_TEXT,
                    status=DocumentStatus.INDEX_FAILED,
                    error_message="index boom",
                )

            with patch.object(file_api, "UPLOAD_DIR", upload_dir):
                with patch.object(
                    file_api.document_ingestion_service,
                    "ingest_upload",
                    fake_ingest_upload,
                ):
                    client = TestClient(build_file_app())
                    response = client.post(
                        "/api/upload",
                        files={"file": ("notes.txt", b"plain text body", "text/plain")},
                        data={"kb_id": "default"},
                    )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["code"], 200)
            self.assertEqual(payload["message"], "success")
            self.assertEqual(payload["data"]["filename"], "notes.txt")

            self.assertTrue(saved_path.exists())
            self.assertEqual(payload["data"]["file_path"], str(saved_path))
            self.assertEqual(payload["data"]["size"], len(b"plain text body"))
            self.assertEqual(payload["data"]["doc_id"], "doc_fail")
            self.assertEqual(payload["data"]["status"], "index_failed")


if __name__ == "__main__":
    unittest.main()
