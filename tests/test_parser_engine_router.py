import tempfile
import unittest
from pathlib import Path

import app.services.vector_index_service as vector_index_module
from app.models import ChunkingConfig, DocumentStatus, ParserEngine, ParserEngineRule
from app.services.knowledge_metadata_store import KnowledgeMetadataStore
from app.services.parser_engine_router import ParserEngineRouter, parser_engine_router


class FakeVectorStoreManager:
    def delete_by_doc_id(self, doc_id: str) -> int:
        return 0

    def delete_by_source(self, file_path: str) -> int:
        return 0

    def add_documents(self, documents):
        return [f"fake-{index}" for index, _ in enumerate(documents)]


class ParserEngineRouterTests(unittest.TestCase):
    def test_default_routes_match_p2_contract(self):
        self.assertEqual(parser_engine_router.resolve(".md"), ParserEngine.PLAIN_TEXT)
        self.assertEqual(parser_engine_router.resolve("txt"), ParserEngine.PLAIN_TEXT)
        self.assertEqual(parser_engine_router.resolve("pdf"), ParserEngine.MINERU)
        self.assertEqual(parser_engine_router.resolve("docx"), ParserEngine.MINERU)
        self.assertEqual(parser_engine_router.resolve("xlsx"), ParserEngine.MINERU)

    def test_supported_file_types_are_predictable(self):
        self.assertEqual(
            parser_engine_router.supported_file_types(),
            ["md", "txt", "pdf", "docx", "xlsx"],
        )

    def test_support_checks_reuse_router_rules_without_raising(self):
        self.assertTrue(parser_engine_router.supports_file_type("md"))
        self.assertTrue(parser_engine_router.supports_file_type(".PDF"))
        self.assertTrue(parser_engine_router.supports_path(Path("manual.docx")))
        self.assertFalse(parser_engine_router.supports_file_type("csv"))
        self.assertFalse(parser_engine_router.supports_file_type(""))
        self.assertFalse(parser_engine_router.supports_path(Path("README")))

    def test_custom_chunking_rules_can_override_default_route(self):
        router = ParserEngineRouter()
        config = ChunkingConfig(
            parser_engine_rules=[
                ParserEngineRule(file_types=["pdf"], engine=ParserEngine.PLAIN_TEXT),
            ]
        )
        self.assertEqual(router.resolve("pdf", chunking_config=config), ParserEngine.PLAIN_TEXT)
        self.assertTrue(router.supports_file_type("pdf", chunking_config=config))

    def test_engine_info_reserves_availability_shape(self):
        engine_info = {item.name: item for item in parser_engine_router.list_engine_info()}

        self.assertEqual(engine_info["plain_text"].file_types, ["md", "txt"])
        self.assertTrue(engine_info["plain_text"].available)
        self.assertEqual(engine_info["mineru"].file_types, ["pdf", "docx", "xlsx"])
        self.assertIsNone(engine_info["mineru"].available)

    def test_unsupported_file_type_raises_clear_error(self):
        with self.assertRaises(ValueError):
            parser_engine_router.resolve("csv")

    def test_vector_index_service_consumes_router_for_plain_text_legacy_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            sample_path = tmp_path / "notes.txt"
            sample_path.write_text("plain text route check", encoding="utf-8")

            fake_manager = FakeVectorStoreManager()
            temp_store = KnowledgeMetadataStore(tmp_path / "knowledge_metadata_store.json")

            original_store = vector_index_module.knowledge_metadata_store
            original_manager = vector_index_module.vector_store_manager
            try:
                vector_index_module.knowledge_metadata_store = temp_store
                vector_index_module.vector_store_manager = fake_manager

                service = vector_index_module.VectorIndexService()
                service.index_single_file(str(sample_path), kb_id="default")

                doc_id = service._build_doc_id("default", sample_path)
                document = temp_store.get_document(doc_id)
                self.assertIsNotNone(document)
                self.assertEqual(document.status, DocumentStatus.INDEXED)
                self.assertEqual(document.parser_engine, ParserEngine.PLAIN_TEXT)
            finally:
                vector_index_module.knowledge_metadata_store = original_store
                vector_index_module.vector_store_manager = original_manager


if __name__ == "__main__":
    unittest.main()
