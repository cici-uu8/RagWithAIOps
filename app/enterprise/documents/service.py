"""Permission-aware document visibility for RAG product surfaces."""

from __future__ import annotations

import re
from pathlib import Path

from app.enterprise.context import RequestContext
from app.enterprise.permissions.service import PermissionService, permission_service
from app.models import DocumentRecord, DocumentStatus
from app.services.knowledge_metadata_store import KnowledgeMetadataStore, knowledge_metadata_store


class DocumentAccessService:
    def __init__(
        self,
        *,
        metadata_store: KnowledgeMetadataStore | None = None,
        permission_service: PermissionService | None = None,
    ):
        self.metadata_store = metadata_store or knowledge_metadata_store
        self.permission_service = permission_service or permission_service_default()

    def list_visible_documents(
        self,
        context: RequestContext | None,
        *,
        kb_id: str | None = None,
        status: DocumentStatus | None = DocumentStatus.INDEXED,
    ) -> list[DocumentRecord]:
        documents = self._filter_documents(kb_id=kb_id, status=status)
        if context is None or "admin" in context.roles:
            return documents
        return [
            document
            for document in documents
            if self.can_read_document(context, document)
        ]

    def can_read_document(
        self,
        context: RequestContext | None,
        document: DocumentRecord,
    ) -> bool:
        if context is None or "admin" in context.roles:
            return True
        if _is_public_document(document):
            return True
        document_decision = self.permission_service.check(
            context,
            resource_type="document",
            resource_id=document.doc_id,
            action="read",
        )
        if document_decision.allowed:
            return True
        return self.permission_service.check(
            context,
            resource_type="knowledge_base",
            resource_id=document.kb_id,
            action="read",
        ).allowed

    def visible_kb_ids(self, context: RequestContext | None) -> list[str]:
        return sorted(
            {
                document.kb_id
                for document in self.list_visible_documents(
                    context,
                    status=DocumentStatus.INDEXED,
                )
                if document.kb_id
            }
        )

    def find_visible_documents(
        self,
        context: RequestContext | None,
        *,
        doc_id: str | None = None,
        file_name: str | None = None,
        kb_ids: list[str] | None = None,
    ) -> list[DocumentRecord]:
        kb_filter = {kb_id for kb_id in kb_ids or [] if kb_id}
        candidates = self.list_visible_documents(context, status=DocumentStatus.INDEXED)
        matches: list[DocumentRecord] = []
        normalized_file_name = _normalize_document_name(file_name) if file_name else ""
        for document in candidates:
            if kb_filter and document.kb_id not in kb_filter:
                continue
            if doc_id and document.doc_id != doc_id:
                continue
            if normalized_file_name and normalized_file_name not in _document_name_keys(document):
                continue
            matches.append(document)
        return matches

    def user_can_see_kb(self, context: RequestContext | None, kb_id: str) -> bool:
        return any(
            document.kb_id == kb_id
            for document in self.list_visible_documents(
                context,
                kb_id=kb_id,
                status=DocumentStatus.INDEXED,
            )
        )

    def _filter_documents(
        self,
        *,
        kb_id: str | None,
        status: DocumentStatus | None,
    ) -> list[DocumentRecord]:
        documents = self.metadata_store.list_documents()
        filtered = [
            document
            for document in documents
            if (not kb_id or document.kb_id == kb_id)
            and (status is None or document.status == status)
        ]
        return sorted(filtered, key=lambda document: (document.kb_id, document.file_name, document.doc_id))


def _normalize_document_name(value: str | None) -> str:
    if not value:
        return ""
    normalized = Path(value.strip().lower()).name
    if "." in normalized:
        normalized = normalized.rsplit(".", 1)[0]
    return re.sub(r"[\s_.-]+", "", normalized)


def _document_name_keys(document: DocumentRecord) -> set[str]:
    return {
        _normalize_document_name(document.file_name),
        _normalize_document_name(Path(document.file_name).stem),
        _normalize_document_name(document.doc_id),
    }


def _is_public_document(document: DocumentRecord) -> bool:
    visibility = str(document.metadata.get("visibility") or document.metadata.get("access") or "").lower()
    return visibility == "public" or bool(document.metadata.get("public_read"))


def permission_service_default() -> PermissionService:
    return permission_service


document_access_service = DocumentAccessService()
