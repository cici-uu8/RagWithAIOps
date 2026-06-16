import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.models import DocumentRecord, DocumentStatus, ParserEngine
from app.services.knowledge_metadata_store import KnowledgeMetadataStore


class KnowledgeMetadataStoreStatusTransitionTests(unittest.TestCase):
    def _build_record(self) -> DocumentRecord:
        return DocumentRecord(
            doc_id="doc_status",
            kb_id="default",
            file_name="notes.md",
            file_ext="md",
            original_path="/tmp/notes.md",
            artifact_dir="/tmp/artifacts",
            parser_engine=ParserEngine.PLAIN_TEXT,
            status=DocumentStatus.UPLOADED,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    def test_transition_document_status_persists_confirmed_status_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "knowledge_metadata_store.json"
            store = KnowledgeMetadataStore(store_path)
            store.upsert_document(self._build_record())

            updated = store.transition_document_status(
                "doc_status",
                DocumentStatus.INDEXING,
                status_source="VectorIndexService.index_document_record",
                status_detail="plain-text chunks are ready for vector write",
                status_evidence={"chunk_count": 2, "parser_engine": "plain_text"},
            )

            self.assertIsNotNone(updated)
            self.assertEqual(updated.status, DocumentStatus.INDEXING)
            self.assertEqual(updated.status_source, "VectorIndexService.index_document_record")
            self.assertEqual(updated.status_detail, "plain-text chunks are ready for vector write")
            self.assertEqual(updated.status_evidence["chunk_count"], 2)
            self.assertIsNotNone(updated.status_confirmed_at)

            reloaded = KnowledgeMetadataStore(store_path).get_document("doc_status")
            self.assertIsNotNone(reloaded)
            self.assertEqual(reloaded.status, DocumentStatus.INDEXING)
            self.assertEqual(reloaded.status_source, "VectorIndexService.index_document_record")
            self.assertEqual(reloaded.status_evidence["parser_engine"], "plain_text")
            self.assertIsNotNone(reloaded.status_confirmed_at)


if __name__ == "__main__":
    unittest.main()
