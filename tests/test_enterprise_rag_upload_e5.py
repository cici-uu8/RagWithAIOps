import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile

from app.enterprise.context import RequestContext
from app.enterprise.documents.service import DocumentAccessService
from app.enterprise.gateway.guardrail_providers import NoOpGuardrailProvider
from app.enterprise.gateway.guardrail_service import GuardrailService
from app.enterprise.gateway.request_gateway import RequestGateway
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService
from app.models import DocumentRecord, DocumentStatus, ParserEngine, RetrievalQuery, SourceRef
from app.services.knowledge_metadata_store import KnowledgeMetadataStore
from app.services.retrieval_service import RetrievalService
from app.services.vector_search_service import SearchResult as RawSearchResult


def _context() -> RequestContext:
    return RequestContext(
        request_id="request-e5",
        trace_id="trace-e5",
        user_id="user_demo_dept1",
        username="demo_user_dept1",
        department_id="dept_1",
        department_name="Department 1",
        roles=["user"],
    )


def _document(doc_id: str, kb_id: str, filename: str, root: Path) -> DocumentRecord:
    return DocumentRecord(
        doc_id=doc_id,
        kb_id=kb_id,
        file_name=filename,
        file_ext=filename.rsplit(".", 1)[-1],
        original_path=(root / filename).as_posix(),
        artifact_dir=(root / doc_id / "artifacts").as_posix(),
        parser_engine=ParserEngine.PLAIN_TEXT,
        status=DocumentStatus.INDEXED,
    )


def _raw_hit(
    *,
    kb_id: str,
    doc_id: str,
    chunk_id: str,
    source_file: str,
    heading_path: list[str],
    content: str,
) -> RawSearchResult:
    source_ref = SourceRef(
        kb_id=kb_id,
        doc_id=doc_id,
        chunk_id=chunk_id,
        source_file=source_file,
        heading_path=heading_path,
        parser_engine=ParserEngine.PLAIN_TEXT,
    )
    return RawSearchResult(
        id=chunk_id,
        content=content,
        score=0.3,
        metadata={
            "kb_id": kb_id,
            "doc_id": doc_id,
            "chunk_id": chunk_id,
            "_file_name": source_file,
            "heading_path": heading_path,
            "parser_engine": "plain_text",
            "source_ref": source_ref.model_dump(mode="json"),
        },
    )


class EnterpriseRagAdapterE5Tests(unittest.TestCase):
    def test_retrieval_filters_unauthorized_documents_before_context_and_citation(self):
        from app.enterprise.adapters.rag_adapter import RagAdapter

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            metadata_store.upsert_document(_document("doc-visible", "kb-main", "visible.md", root))
            metadata_store.upsert_document(_document("doc-hidden", "kb-main", "secret.md", root))

            sink = InMemoryAuditSink()
            permission_service = PermissionService(
                repository=InMemoryGovernanceRepository(),
                audit_service=AuditService(sinks=[sink]),
            )
            permission_service.grant_access(
                ResourceGrant(
                    resource_type="document",
                    resource_id="doc-visible",
                    action="read",
                    principal_type=PrincipalType.USER,
                    principal_id="user_demo_dept1",
                    effect=GrantEffect.ALLOW,
                    reason="case-owner",
                )
            )

            adapter = RagAdapter(
                RetrievalService(),
                permission_service=permission_service,
                metadata_store=metadata_store,
                audit_service=AuditService(sinks=[sink]),
            )

            hidden = _raw_hit(
                kb_id="kb-main",
                doc_id="doc-hidden",
                chunk_id="doc-hidden:c00001",
                source_file="secret.md",
                heading_path=["Hidden Root Cause"],
                content="hidden remediation password rotation",
            )
            visible = _raw_hit(
                kb_id="kb-main",
                doc_id="doc-visible",
                chunk_id="doc-visible:c00001",
                source_file="visible.md",
                heading_path=["Visible SOP"],
                content="authorized restart procedure",
            )

            import app.services.retrieval_service as retrieval_module

            original_vector_search = retrieval_module.vector_search_service.search_similar_documents
            retrieval_module.vector_search_service.search_similar_documents = lambda *_args, **_kwargs: [
                hidden,
                visible,
            ]
            try:
                response = adapter.retrieve(_context(), RetrievalQuery(query="restart", top_k=3))
            finally:
                retrieval_module.vector_search_service.search_similar_documents = original_vector_search

        self.assertEqual([result.doc_id for result in response.results], ["doc-visible"])
        self.assertEqual(response.results[0].source_ref.source_file, "visible.md")
        self.assertIn("Visible SOP", response.context_text)
        self.assertIn("authorized restart procedure", response.context_text)
        self.assertNotIn("doc-hidden", response.context_text)
        self.assertNotIn("secret.md", response.context_text)
        self.assertNotIn("Hidden Root Cause", response.context_text)
        self.assertNotIn("hidden remediation", response.context_text)

        retrieval_events = [event for event in sink.events if event.event_type == "rag_retrieval"]
        self.assertEqual(len(retrieval_events), 1)
        self.assertEqual(retrieval_events[0].trace_id, "trace-e5")
        self.assertEqual(retrieval_events[0].metadata["allowed_doc_ids"], ["doc-visible"])
        self.assertEqual(retrieval_events[0].metadata["blocked_doc_ids"], ["doc-hidden"])

    def test_retrieval_allows_documents_via_knowledge_base_grant(self):
        from app.enterprise.adapters.rag_adapter import RagAdapter

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            metadata_store.upsert_document(_document("doc-kb", "kb-main", "runbook.md", root))

            sink = InMemoryAuditSink()
            permission_service = PermissionService(
                repository=InMemoryGovernanceRepository(),
                audit_service=AuditService(sinks=[sink]),
            )
            permission_service.grant_access(
                ResourceGrant(
                    resource_type="knowledge_base",
                    resource_id="kb-main",
                    action="read",
                    principal_type=PrincipalType.USER,
                    principal_id="user_demo_dept1",
                    effect=GrantEffect.ALLOW,
                    reason="department-kb",
                )
            )

            adapter = RagAdapter(
                RetrievalService(),
                permission_service=permission_service,
                metadata_store=metadata_store,
                audit_service=AuditService(sinks=[sink]),
            )

            hit = _raw_hit(
                kb_id="kb-main",
                doc_id="doc-kb",
                chunk_id="doc-kb:c00001",
                source_file="runbook.md",
                heading_path=["Runbook"],
                content="kb grant runbook content",
            )

            import app.services.retrieval_service as retrieval_module

            original_vector_search = retrieval_module.vector_search_service.search_similar_documents
            retrieval_module.vector_search_service.search_similar_documents = lambda *_args, **_kwargs: [hit]
            try:
                response = adapter.retrieve(
                    _context(),
                    RetrievalQuery(
                        query="runbook",
                        top_k=3,
                        knowledge_base_ids=["kb-main"],
                    ),
                )
            finally:
                retrieval_module.vector_search_service.search_similar_documents = original_vector_search

        self.assertEqual([result.doc_id for result in response.results], ["doc-kb"])
        self.assertIn("kb grant runbook content", response.context_text)

        retrieval_events = [event for event in sink.events if event.event_type == "rag_retrieval"]
        self.assertEqual(len(retrieval_events), 1)
        self.assertEqual(retrieval_events[0].metadata["allowed_doc_ids"], ["doc-kb"])
        self.assertEqual(retrieval_events[0].metadata["blocked_doc_ids"], [])


class EnterpriseStorageServiceE5Tests(unittest.TestCase):
    def test_local_storage_reads_provider_uri_and_legacy_path(self):
        from app.enterprise.storage.service import LocalStorageService

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = LocalStorageService(base_dir=tmpdir)
            stored = storage.save_bytes(
                relative_path="documents/default/doc-1/original/notes.md",
                content=b"# title",
            )
            legacy_path = Path(tmpdir) / "legacy.txt"
            legacy_path.write_bytes(b"legacy")

            self.assertEqual(stored.storage_uri, "local://documents/default/doc-1/original/notes.md")
            self.assertTrue(Path(stored.local_path).exists())
            self.assertEqual(storage.read_bytes(stored.storage_uri), b"# title")
            self.assertEqual(storage.read_bytes(legacy_path.as_posix()), b"legacy")


class RecordingStorageService:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.saved: list[tuple[str, bytes]] = []
        self.created_dirs: list[str] = []

    def save_bytes(self, *, relative_path: str, content: bytes):
        from app.enterprise.storage.models import StoredObject

        self.saved.append((relative_path, content))
        local_path = self.base_dir / relative_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(content)
        return StoredObject(
            storage_uri=f"local://{relative_path}",
            local_path=local_path.as_posix(),
            provider="local",
            relative_path=relative_path,
        )

    def ensure_directory(self, relative_path: str) -> str:
        self.created_dirs.append(relative_path)
        path = self.base_dir / relative_path
        path.mkdir(parents=True, exist_ok=True)
        return path.as_posix()


class EnterpriseUploadStorageAuditE5Tests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_uses_storage_service_and_records_storage_audit(self):
        from app.enterprise.adapters.upload_adapter import UploadAdapter
        from app.services import document_ingestion_service as ingestion_module

        with tempfile.TemporaryDirectory() as tmpdir:
            upload_root = Path(tmpdir) / "uploads"
            metadata_store = KnowledgeMetadataStore(upload_root / "_metadata" / "store.json")
            fake_indexer = type(
                "FakeIndexer",
                (),
                {
                    "index_document_record": lambda _self, record: ingestion_module.knowledge_metadata_store.transition_document_status(
                        record.doc_id,
                        DocumentStatus.INDEXED,
                        status_source="FakeIndexer.index_document_record",
                        status_detail="fake index complete",
                        status_evidence={"doc_id": record.doc_id},
                    )
                },
            )()
            storage = RecordingStorageService(upload_root)
            ingestion_service = ingestion_module.DocumentIngestionService(
                upload_root=upload_root,
                storage_service=storage,
            )
            sink = InMemoryAuditSink()
            audit_service = AuditService(sinks=[sink])
            permission_service = PermissionService(
                repository=InMemoryGovernanceRepository(),
                audit_service=audit_service,
            )
            gateway = RequestGateway(
                audit_service=audit_service,
                guardrail_service=GuardrailService(providers=[NoOpGuardrailProvider()]),
            )
            adapter = UploadAdapter(
                ingestion_service,
                max_file_size=1024,
                gateway=gateway,
                permission_service=permission_service,
            )
            metadata_store.upsert_document(_document("doc-hidden", "default", "hidden.md", upload_root))

            original_store = ingestion_module.knowledge_metadata_store
            original_indexer = ingestion_module.vector_index_service
            ingestion_module.knowledge_metadata_store = metadata_store
            ingestion_module.vector_index_service = fake_indexer
            try:
                response = await adapter.upload(
                    UploadFile(filename="notes.md", file=BytesIO(b"# Title\n\nBody")),
                    "default",
                    {
                        "X-Trace-Id": "trace-upload-e5",
                        "X-Request-Id": "request-upload-e5",
                        "X-User-Id": "user_demo_dept1",
                        "X-Department-Id": "dept_1",
                        "X-Roles": "user",
                    },
                )
            finally:
                ingestion_module.knowledge_metadata_store = original_store
                ingestion_module.vector_index_service = original_indexer

            file_exists = Path(response["file_path"]).exists()
            access_service = DocumentAccessService(
                metadata_store=metadata_store,
                permission_service=permission_service,
            )
            visible_docs = access_service.list_visible_documents(
                _context(),
                kb_id="default",
                status=DocumentStatus.INDEXED,
            )
            document_grants = permission_service.repository.list_all_grants(
                resource_type="document",
                resource_id=response["doc_id"],
                action="read",
                principal_type=PrincipalType.USER,
                principal_id="user_demo_dept1",
            )
            kb_grants = permission_service.repository.list_all_grants(
                resource_type="knowledge_base",
                resource_id="default",
                action="read",
                principal_type=PrincipalType.USER,
                principal_id="user_demo_dept1",
            )

            self.assertEqual(len(storage.saved), 1)
            self.assertEqual(storage.saved[0][1], b"# Title\n\nBody")
            self.assertEqual(
                response["storage_uri"],
                f"local://documents/default/{response['doc_id']}/original/notes.md",
            )
            self.assertTrue(file_exists)
            self.assertEqual([document.doc_id for document in visible_docs], [response["doc_id"]])
            self.assertEqual(len(document_grants), 1)
            self.assertEqual(document_grants[0].effect, GrantEffect.ALLOW)
            self.assertEqual(document_grants[0].reason, "document_uploader_auto_read")
            self.assertEqual(kb_grants, [])

        upload_events = [event for event in sink.events if event.event_type == "upload_saved"]
        self.assertEqual(len(upload_events), 1)
        event = upload_events[0]
        self.assertEqual(event.trace_id, "trace-upload-e5")
        self.assertEqual(event.request_id, "request-upload-e5")
        self.assertEqual(event.user_id, "user_demo_dept1")
        self.assertEqual(event.metadata["department_id"], "dept_1")
        self.assertEqual(event.metadata["kb_id"], "default")
        self.assertEqual(event.metadata["doc_id"], response["doc_id"])
        self.assertEqual(event.metadata["storage_uri"], response["storage_uri"])
        self.assertEqual(event.metadata["uploader_read_grant_id"], document_grants[0].grant_id)


if __name__ == "__main__":
    unittest.main()
