"""Minimal metadata store for document and chunk lifecycle tracking."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional

from loguru import logger

from app.models import ChunkRecord, DocumentRecord, DocumentStatus


class KnowledgeMetadataStore:
    """Persist minimal document/chunk metadata outside the vector store."""

    def __init__(self, store_path: str | Path = "./uploads/_metadata/knowledge_metadata_store.json"):
        self.store_path = Path(store_path).resolve()
        self._lock = RLock()
        self._documents: Dict[str, DocumentRecord] = {}
        self._chunks_by_doc: Dict[str, Dict[str, ChunkRecord]] = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not self.store_path.exists():
                return

            raw = json.loads(self.store_path.read_text(encoding="utf-8"))
            self._documents = {
                doc_id: DocumentRecord.model_validate(payload)
                for doc_id, payload in raw.get("documents", {}).items()
            }
            self._chunks_by_doc = {
                doc_id: {
                    chunk_id: ChunkRecord.model_validate(chunk_payload)
                    for chunk_id, chunk_payload in chunk_map.items()
                }
                for doc_id, chunk_map in raw.get("chunks_by_doc", {}).items()
            }

    def _save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "documents": {
                doc_id: document.model_dump(mode="json")
                for doc_id, document in self._documents.items()
            },
            "chunks_by_doc": {
                doc_id: {
                    chunk_id: chunk.model_dump(mode="json")
                    for chunk_id, chunk in chunk_map.items()
                }
                for doc_id, chunk_map in self._chunks_by_doc.items()
            },
        }
        self.store_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def upsert_document(self, document: DocumentRecord) -> DocumentRecord:
        with self._lock:
            self._documents[document.doc_id] = document
            self._save()
            logger.debug(
                "MetadataStore upserted document doc_id={} status={}",
                document.doc_id,
                document.status,
            )
            return document

    def get_document(self, doc_id: str) -> Optional[DocumentRecord]:
        with self._lock:
            document = self._documents.get(doc_id)
            return document.model_copy(deep=True) if document else None

    def transition_document_status(
        self,
        doc_id: str,
        status: DocumentStatus,
        *,
        status_source: str,
        status_detail: str,
        status_evidence: Dict[str, Any],
        error_message: str = "",
        parser_version: str | None = None,
        metadata_update: Dict[str, Any] | None = None,
    ) -> Optional[DocumentRecord]:
        if not status_source.strip():
            raise ValueError("status_source 不能为空")
        if not status_detail.strip():
            raise ValueError("status_detail 不能为空")
        if not status_evidence:
            raise ValueError("status_evidence 不能为空")

        with self._lock:
            document = self._documents.get(doc_id)
            if document is None:
                return None

            now = datetime.now()
            update_payload: Dict[str, Any] = {
                "status": status,
                "status_detail": status_detail,
                "status_source": status_source,
                "status_evidence": status_evidence,
                "status_confirmed_at": now,
                "error_message": error_message,
                "updated_at": now,
            }
            if parser_version is not None:
                update_payload["parser_version"] = parser_version
            if metadata_update:
                update_payload["metadata"] = {
                    **document.metadata,
                    **metadata_update,
                }

            updated = document.model_copy(
                update=update_payload,
            )
            self._documents[doc_id] = updated
            self._save()
            logger.debug(
                "MetadataStore transitioned status doc_id={} -> {} source={}",
                doc_id,
                status,
                status_source,
            )
            return updated

    def replace_chunks(self, doc_id: str, chunks: List[ChunkRecord]) -> int:
        with self._lock:
            self._chunks_by_doc[doc_id] = {chunk.chunk_id: chunk for chunk in chunks}
            self._save()
            logger.debug("MetadataStore replaced chunks doc_id={} count={}", doc_id, len(chunks))
            return len(chunks)

    def list_chunks_by_doc_id(self, doc_id: str) -> List[ChunkRecord]:
        with self._lock:
            chunks = self._chunks_by_doc.get(doc_id, {})
            return [chunk.model_copy(deep=True) for chunk in chunks.values()]

    def list_chunks(self, knowledge_base_ids: List[str] | None = None) -> List[ChunkRecord]:
        """List chunks across documents, optionally scoped to knowledge-base IDs."""
        allowed_kb_ids = set(knowledge_base_ids or [])
        with self._lock:
            chunks: List[ChunkRecord] = []
            for chunk_map in self._chunks_by_doc.values():
                for chunk in chunk_map.values():
                    if allowed_kb_ids and chunk.kb_id not in allowed_kb_ids:
                        continue
                    chunks.append(chunk.model_copy(deep=True))
            return chunks

    def delete_chunks_by_doc_id(self, doc_id: str) -> int:
        with self._lock:
            chunk_map = self._chunks_by_doc.pop(doc_id, {})
            deleted_count = len(chunk_map)
            if deleted_count:
                self._save()
            logger.debug("MetadataStore deleted chunks doc_id={} count={}", doc_id, deleted_count)
            return deleted_count

    def list_documents(self) -> List[DocumentRecord]:
        with self._lock:
            return [document.model_copy(deep=True) for document in self._documents.values()]


knowledge_metadata_store = KnowledgeMetadataStore()
