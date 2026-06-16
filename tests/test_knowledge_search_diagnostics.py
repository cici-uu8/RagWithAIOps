import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.auth as auth_api
import app.api.knowledge_base as knowledge_base_api
from app.enterprise.auth.service import auth_service
from app.enterprise.context import RequestContext, reset_current_request_context, set_current_request_context
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.service import permission_service
from app.models import (
    ChunkRecord,
    DocumentRecord,
    DocumentStatus,
    ParserEngine,
    RetrievalQuery,
    RetrievalResponse,
    SourceRef,
)
from app.services.knowledge_metadata_store import KnowledgeMetadataStore


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    app.include_router(knowledge_base_api.router, prefix="/api")
    return app


def _document(
    doc_id: str,
    kb_id: str,
    file_name: str,
    root: Path,
    *,
    status: DocumentStatus = DocumentStatus.INDEXED,
) -> DocumentRecord:
    return DocumentRecord(
        doc_id=doc_id,
        kb_id=kb_id,
        file_name=file_name,
        file_ext=file_name.rsplit(".", 1)[-1],
        original_path=(root / file_name).as_posix(),
        artifact_dir=(root / doc_id / "artifacts").as_posix(),
        parser_engine=ParserEngine.PLAIN_TEXT,
        status=status,
    )


def _chunk(document: DocumentRecord, content: str) -> ChunkRecord:
    source_ref = SourceRef(
        kb_id=document.kb_id,
        doc_id=document.doc_id,
        chunk_id=f"{document.doc_id}:c0001",
        source_file=document.file_name,
        parser_engine=document.parser_engine,
    )
    return ChunkRecord(
        chunk_id=source_ref.chunk_id,
        doc_id=document.doc_id,
        kb_id=document.kb_id,
        content=content,
        chunk_index=0,
        start_index=0,
        end_index=len(content),
        source_ref=source_ref,
        metadata={
            "kb_id": document.kb_id,
            "doc_id": document.doc_id,
            "chunk_id": source_ref.chunk_id,
            "source_file": document.file_name,
            "parser_engine": document.parser_engine.value,
            "source_ref": source_ref.model_dump(mode="json"),
        },
    )


def _grant_document(doc_id: str, *, user_id: str = "user_demo_dept1") -> None:
    permission_service.grant_access(
        ResourceGrant(
            resource_type="document",
            resource_id=doc_id,
            action="read",
            principal_type=PrincipalType.USER,
            principal_id=user_id,
            effect=GrantEffect.ALLOW,
            reason="knowledge-search-diagnostics-test",
        )
    )


class KnowledgeSearchDiagnosticsApiTests(unittest.TestCase):
    def setUp(self):
        auth_service.reset_users()
        auth_service.clear_blacklist()
        permission_service.repository.clear()
        permission_service.invalidate_cache()
        self.client = TestClient(_build_app())

    def tearDown(self):
        auth_service.reset_users()
        auth_service.clear_blacklist()
        permission_service.repository.clear()
        permission_service.invalidate_cache()

    def _login(self) -> str:
        response = self.client.post(
            "/api/auth/login",
            json={"username": "demo_user_dept1", "password": "Demo123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["access_token"]

    def test_scoped_search_explains_permission_filtered_scope(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            metadata_store.upsert_document(
                _document("doc-hidden", "craft_dept", "设备检修.md", root)
            )
            token = self._login()

            with (
                patch.object(
                    knowledge_base_api.knowledge_search_service.document_access_service,
                    "metadata_store",
                    metadata_store,
                ),
                patch.object(
                    knowledge_base_api.knowledge_search_service.rag_adapter,
                    "metadata_store",
                    metadata_store,
                ),
            ):
                response = self.client.get(
                    "/api/knowledge-bases/craft_dept/search",
                    params={"q": "设备检修", "top_k": 5, "retrieval_mode": "sparse_only"},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Trace-Id": "trace-diagnostics-permission",
                    },
                )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        diagnostics = data["diagnostics"]
        self.assertEqual(data["items"], [])
        self.assertEqual(diagnostics["requested_kb_ids"], ["craft_dept"])
        self.assertEqual(diagnostics["selected_kb_ids"], [])
        self.assertEqual(diagnostics["visible_kb_ids"], [])
        self.assertEqual(diagnostics["allowed_doc_count"], 0)
        self.assertEqual(diagnostics["permission_filtered_count"], 1)
        self.assertEqual(
            diagnostics["no_result_reason"],
            "selected_kb_not_visible_or_no_indexed_documents",
        )
        self.assertEqual(diagnostics["trace_id"], "trace-diagnostics-permission")

    def test_auto_search_counts_pending_documents_separately_from_retrieval_no_hit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            indexed = _document("doc-indexed", "process_digital_dept", "数字化.md", root)
            pending = _document(
                "doc-pending",
                "process_digital_dept",
                "待解析.pdf",
                root,
                status=DocumentStatus.PARSE_PENDING,
            )
            metadata_store.upsert_document(indexed)
            metadata_store.upsert_document(pending)
            metadata_store.replace_chunks(
                indexed.doc_id,
                [_chunk(indexed, "Prometheus 告警 API 监控")],
            )
            _grant_document(indexed.doc_id)
            _grant_document(pending.doc_id)
            token = self._login()

            with (
                patch.object(
                    knowledge_base_api.knowledge_search_service.document_access_service,
                    "metadata_store",
                    metadata_store,
                ),
                patch.object(
                    knowledge_base_api.knowledge_search_service.rag_adapter,
                    "metadata_store",
                    metadata_store,
                ),
                patch("app.services.sparse_search_service.knowledge_metadata_store", metadata_store),
            ):
                response = self.client.post(
                    "/api/knowledge-search",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Trace-Id": "trace-diagnostics-no-hit",
                    },
                    json={
                        "query": "完全不存在的词条",
                        "kb_scope": "process_digital_dept",
                        "candidate_kb_ids": ["process_digital_dept"],
                        "top_k": 5,
                        "retrieval_mode": "sparse_only",
                    },
                )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        diagnostics = data["diagnostics"]
        self.assertEqual(data["items"], [])
        self.assertEqual(diagnostics["requested_kb_ids"], ["process_digital_dept"])
        self.assertEqual(diagnostics["visible_kb_ids"], ["process_digital_dept"])
        self.assertEqual(diagnostics["selected_kb_ids"], ["process_digital_dept"])
        self.assertEqual(diagnostics["allowed_doc_count"], 2)
        self.assertEqual(diagnostics["indexed_doc_count"], 1)
        self.assertEqual(diagnostics["parse_pending_doc_count"], 1)
        self.assertEqual(diagnostics["sparse_hit_count"], 0)
        self.assertEqual(diagnostics["dense_hit_count"], "not_available")
        self.assertEqual(diagnostics["hybrid_result_count"], 0)
        self.assertEqual(diagnostics["no_result_reason"], "retrieval_no_hit")


class RetrieveKnowledgeToolDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        permission_service.repository.clear()
        permission_service.invalidate_cache()

    def tearDown(self):
        permission_service.repository.clear()
        permission_service.invalidate_cache()

    def test_tool_artifact_contains_diagnostics_when_no_results_are_returned(self):
        import app.tools.knowledge_tool as knowledge_tool

        context = RequestContext(
            request_id="request-tool-diagnostics",
            trace_id="trace-tool-diagnostics",
            user_id="user_demo_dept1",
            username="demo_user_dept1",
            department_id="dept_1",
            department_name="Department 1",
            roles=["user"],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            indexed = _document("doc-indexed", "process_digital_dept", "数字化.md", root)
            metadata_store.upsert_document(indexed)
            _grant_document(indexed.doc_id)

            class FakeRagAdapter:
                def retrieve(self, _context, query):
                    return RetrievalResponse(
                        query=query,
                        results=[],
                        context_text="没有找到相关信息。",
                        empty_message="没有找到相关信息。",
                    )

            fake_rag_adapter = FakeRagAdapter()
            fake_rag_adapter.metadata_store = metadata_store

            token = set_current_request_context(context)
            try:
                with (
                    patch.object(knowledge_tool, "rag_adapter", fake_rag_adapter),
                    patch.object(
                        knowledge_tool.document_access_service,
                        "metadata_store",
                        metadata_store,
                    ),
                ):
                    _content, artifact = knowledge_tool.retrieve_knowledge.func(
                        "不存在的内容",
                        knowledge_base_ids=["process_digital_dept"],
                    )
            finally:
                reset_current_request_context(token)

        diagnostics = artifact["diagnostics"]
        self.assertEqual(artifact["query"]["query"], "不存在的内容")
        self.assertEqual(diagnostics["requested_kb_ids"], ["process_digital_dept"])
        self.assertEqual(diagnostics["selected_kb_ids"], ["process_digital_dept"])
        self.assertEqual(diagnostics["visible_kb_ids"], ["process_digital_dept"])
        self.assertEqual(diagnostics["tool_called"], True)
        self.assertEqual(diagnostics["tool_name"], "retrieve_knowledge")
        self.assertEqual(diagnostics["no_result_reason"], "retrieval_no_hit")
        self.assertEqual(diagnostics["trace_id"], "trace-tool-diagnostics")


if __name__ == "__main__":
    unittest.main()
