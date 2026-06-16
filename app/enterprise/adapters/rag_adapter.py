"""RAG adapter that applies enterprise document permissions before citations."""

from __future__ import annotations

from app.enterprise.context import RequestContext
from app.enterprise.documents.service import DocumentAccessService
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.observability.models import AuditEvent
from app.enterprise.permissions.models import ResourceDescriptor
from app.enterprise.permissions.service import PermissionService, permission_service
from app.enterprise.verifiers import CitationVerifier, VerificationService
from app.models import DocumentRecord, RetrievalQuery, RetrievalResponse
from app.services.knowledge_metadata_store import knowledge_metadata_store
from app.services.retrieval_service import RetrievalService, retrieval_service


class RagAdapter:
    def __init__(
        self,
        retrieval_service: RetrievalService | None = None,
        *,
        permission_service: PermissionService | None = None,
        metadata_store=None,
        audit_service: AuditService | None = None,
        verification_service: VerificationService | None = None,
        document_access_service: DocumentAccessService | None = None,
    ):
        self.retrieval_service = retrieval_service or retrieval_service_default()
        self.permission_service = permission_service or permission_service_default()
        self.metadata_store = metadata_store or knowledge_metadata_store
        self.audit_service = audit_service or AuditService()
        self.verification_service = verification_service or VerificationService(
            audit_service=self.audit_service
        )
        self.document_access_service = document_access_service or DocumentAccessService(
            metadata_store=self.metadata_store,
            permission_service=self.permission_service,
        )

    def retrieve(self, context: RequestContext, query: RetrievalQuery) -> RetrievalResponse:
        visible_documents, blocked_documents = self._partition_documents(context, query)
        allowed_doc_ids = [document.doc_id for document in visible_documents]

        if not allowed_doc_ids:
            response = RetrievalResponse(
                query=query,
                results=[],
                context_text=self.retrieval_service.EMPTY_MESSAGE,
                empty_message=self.retrieval_service.EMPTY_MESSAGE,
            )
        else:
            response = self.retrieval_service.retrieve(
                query,
                allowed_document_ids=allowed_doc_ids,
            )

        self._record_retrieval_audit(
            context,
            query=query,
            allowed_doc_ids=allowed_doc_ids,
            blocked_doc_ids=[document.doc_id for document in blocked_documents],
            result_doc_ids=[result.doc_id for result in response.results],
        )
        self.verification_service.ensure_passed(
            context,
            CitationVerifier(),
            {
                "response": response,
                "allowed_document_ids": allowed_doc_ids,
            },
        )
        return response

    def _partition_documents(
        self,
        context: RequestContext,
        query: RetrievalQuery,
    ) -> tuple[list[DocumentRecord], list[DocumentRecord]]:
        requested_kb_ids = set(query.knowledge_base_ids)
        requested_doc_ids = set(query.document_ids)
        documents = [
            document
            for document in self.metadata_store.list_documents()
            if not requested_kb_ids or document.kb_id in requested_kb_ids
            if not requested_doc_ids or document.doc_id in requested_doc_ids
        ]
        visible: list[DocumentRecord] = []
        blocked: list[DocumentRecord] = []
        for document in documents:
            if self.document_access_service.can_read_document(context, document):
                visible.append(document)
            else:
                blocked.append(document)
        return visible, blocked

    def _record_retrieval_audit(
        self,
        context: RequestContext,
        *,
        query: RetrievalQuery,
        allowed_doc_ids: list[str],
        blocked_doc_ids: list[str],
        result_doc_ids: list[str],
    ) -> None:
        self.audit_service.record(
            AuditEvent(
                event_type="rag_retrieval",
                route="rag",
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision="allowed",
                metadata={
                    "requested_kb_ids": list(query.knowledge_base_ids),
                    "allowed_doc_ids": allowed_doc_ids,
                    "blocked_doc_ids": blocked_doc_ids,
                    "result_doc_ids": result_doc_ids,
                    "result_count": len(result_doc_ids),
                },
            )
        )

    def list_visible_document_resources(
        self,
        context: RequestContext,
        query: RetrievalQuery | None = None,
    ) -> list[ResourceDescriptor]:
        requested_kb_ids = set(query.knowledge_base_ids if query else [])
        resources: list[ResourceDescriptor] = []
        for document in self.metadata_store.list_documents():
            if requested_kb_ids and document.kb_id not in requested_kb_ids:
                continue
            resources.append(
                ResourceDescriptor(
                    resource_type="document",
                    resource_id=document.doc_id,
                    name=document.file_name,
                    metadata={
                        "kb_id": document.kb_id,
                        "source_ref": document.original_path,
                    },
                )
            )
        return self.permission_service.filter_allowed(context, resources, action="read")


def retrieval_service_default() -> RetrievalService:
    return retrieval_service


def permission_service_default() -> PermissionService:
    return permission_service


rag_adapter = RagAdapter()
