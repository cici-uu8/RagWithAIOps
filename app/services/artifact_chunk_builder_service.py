"""Adapt parsed artifacts into index-ready chunk records for P2-5."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from app.models import ArtifactManifest, ChunkRecord, DocumentRecord, SourceRef


@dataclass
class PreparedIndexArtifacts:
    """Contract-normalized artifacts ready for the index write path."""

    document_record: DocumentRecord
    manifest: ArtifactManifest
    documents: list[Document]
    chunk_records: list[ChunkRecord]
    quality_report: dict[str, Any]


class ArtifactChunkBuilderService:
    """Build index-ready chunks strictly from `chunks.json` and `tables.json`."""

    def prepare(
        self,
        document_record: DocumentRecord,
        manifest: ArtifactManifest,
    ) -> PreparedIndexArtifacts:
        artifact_dir = Path(document_record.artifact_dir)
        chunks_payload = self._load_json_list(artifact_dir / manifest.required_files["chunks_json"])
        tables_payload = self._load_json_list(artifact_dir / manifest.required_files["tables_json"])
        quality_report = self._load_json_object(
            artifact_dir / manifest.required_files["quality_report_json"]
        )
        self._raise_for_fatal_quality_errors(quality_report)

        chunk_records: list[ChunkRecord] = []
        documents: list[Document] = []
        cursor = 0

        for raw_chunk in chunks_payload:
            chunk_record = self._build_text_chunk_record(
                document_record=document_record,
                raw_chunk=raw_chunk,
                chunk_index=len(chunk_records),
                start_index=cursor,
            )
            cursor = max(cursor, chunk_record.end_index)
            chunk_records.append(chunk_record)
            documents.append(Document(page_content=chunk_record.content, metadata=dict(chunk_record.metadata)))

        for raw_table in tables_payload:
            chunk_record = self._build_table_chunk_record(
                document_record=document_record,
                raw_table=raw_table,
                chunk_index=len(chunk_records),
                start_index=cursor,
            )
            cursor = max(cursor, chunk_record.end_index)
            chunk_records.append(chunk_record)
            documents.append(Document(page_content=chunk_record.content, metadata=dict(chunk_record.metadata)))

        return PreparedIndexArtifacts(
            document_record=document_record,
            manifest=manifest,
            documents=documents,
            chunk_records=chunk_records,
            quality_report=quality_report,
        )

    def _build_text_chunk_record(
        self,
        document_record: DocumentRecord,
        raw_chunk: dict[str, Any],
        chunk_index: int,
        start_index: int,
    ) -> ChunkRecord:
        local_id = self._required_str(raw_chunk, ["chunk_id", "id"], "chunk_id")
        content = self._required_str(raw_chunk, ["content", "text"], "content")
        chunk_id = self._normalize_chunk_id(document_record.doc_id, local_id)
        pages = raw_chunk.get("pages") if isinstance(raw_chunk.get("pages"), list) else []
        page_start = raw_chunk.get("page_start", min(pages) if pages else None)
        page_end = raw_chunk.get("page_end", max(pages) if pages else None)
        heading_path = self._list_or_empty(raw_chunk.get("heading_path"))
        content_type = raw_chunk.get("content_type") or "text"
        quality_flags = self._list_or_empty(raw_chunk.get("quality_flags"))
        source_ref = self._build_source_ref(
            document_record=document_record,
            chunk_id=chunk_id,
            page_start=page_start,
            page_end=page_end,
            heading_path=heading_path,
            content_type=content_type,
        )
        metadata = self._base_metadata(
            document_record=document_record,
            chunk_id=chunk_id,
            content_type=content_type,
            page_start=page_start,
            page_end=page_end,
            heading_path=heading_path,
            source_ref=source_ref,
            quality_flags=quality_flags,
        )
        metadata.update(
            {
                "artifact_source": "chunks_json",
                "raw_chunk_id": local_id,
                "block_ids": self._list_or_empty(raw_chunk.get("block_ids")),
                "block_types": self._list_or_empty(raw_chunk.get("block_types")),
            }
        )
        return ChunkRecord(
            chunk_id=chunk_id,
            doc_id=document_record.doc_id,
            kb_id=document_record.kb_id,
            content=content,
            chunk_index=chunk_index,
            start_index=start_index,
            end_index=start_index + len(content),
            heading_path=heading_path,
            page_start=page_start,
            page_end=page_end,
            content_type=content_type,
            source_ref=source_ref,
            quality_flags=quality_flags,
            metadata=metadata,
        )

    def _build_table_chunk_record(
        self,
        document_record: DocumentRecord,
        raw_table: dict[str, Any],
        chunk_index: int,
        start_index: int,
    ) -> ChunkRecord:
        table_id = self._required_str(raw_table, ["table_id", "id"], "table_id")
        content = self._required_str(raw_table, ["display_text", "markdown"], "markdown")
        chunk_id = self._normalize_table_chunk_id(document_record.doc_id, table_id)
        page_start = raw_table.get("page_start", raw_table.get("page"))
        page_end = raw_table.get("page_end", raw_table.get("page"))
        heading_path = self._list_or_empty(raw_table.get("heading_path"))
        content_type = raw_table.get("content_type") or "table"
        quality_flags = self._list_or_empty(raw_table.get("quality_flags"))
        source_ref = self._build_source_ref(
            document_record=document_record,
            chunk_id=chunk_id,
            page_start=page_start,
            page_end=page_end,
            heading_path=heading_path,
            content_type=content_type,
        )
        metadata = self._base_metadata(
            document_record=document_record,
            chunk_id=chunk_id,
            content_type=content_type,
            page_start=page_start,
            page_end=page_end,
            heading_path=heading_path,
            source_ref=source_ref,
            quality_flags=quality_flags,
        )
        metadata.update(
            {
                "artifact_source": "tables_json",
                "table_id": table_id,
                "classification": raw_table.get("classification", ""),
                "structured_payload": {
                    "rows": raw_table.get("rows", []),
                    "caption": raw_table.get("caption", []),
                    "quality_flags": quality_flags,
                },
            }
        )
        return ChunkRecord(
            chunk_id=chunk_id,
            doc_id=document_record.doc_id,
            kb_id=document_record.kb_id,
            content=content,
            chunk_index=chunk_index,
            start_index=start_index,
            end_index=start_index + len(content),
            heading_path=heading_path,
            page_start=page_start,
            page_end=page_end,
            content_type=content_type,
            source_ref=source_ref,
            quality_flags=quality_flags,
            metadata=metadata,
        )

    def _base_metadata(
        self,
        document_record: DocumentRecord,
        chunk_id: str,
        content_type: str,
        page_start: int | None,
        page_end: int | None,
        heading_path: list[str],
        source_ref: SourceRef,
        quality_flags: list[str],
    ) -> dict[str, Any]:
        return {
            "kb_id": document_record.kb_id,
            "doc_id": document_record.doc_id,
            "chunk_id": chunk_id,
            "_source": document_record.original_path,
            "_file_name": document_record.file_name,
            "_extension": f".{document_record.file_ext}",
            "content_type": content_type,
            "page_start": page_start,
            "page_end": page_end,
            "heading_path": heading_path,
            "parser_engine": document_record.parser_engine.value,
            "source_ref": source_ref.model_dump(mode="json"),
            "quality_flags": quality_flags,
        }

    def _build_source_ref(
        self,
        document_record: DocumentRecord,
        chunk_id: str,
        page_start: int | None,
        page_end: int | None,
        heading_path: list[str],
        content_type: str,
    ) -> SourceRef:
        return SourceRef(
            kb_id=document_record.kb_id,
            doc_id=document_record.doc_id,
            chunk_id=chunk_id,
            source_file=document_record.file_name,
            page_start=page_start,
            page_end=page_end,
            heading_path=heading_path,
            content_type=content_type,
            parser_engine=document_record.parser_engine,
        )

    def _load_json_list(self, path: Path) -> list[dict[str, Any]]:
        payload = self._load_json(path)
        if not isinstance(payload, list):
            raise ValueError(f"{path.name} must be a JSON list")
        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                raise ValueError(f"{path.name}[{index}] must be an object")
        return payload

    def _load_json_object(self, path: Path) -> dict[str, Any]:
        payload = self._load_json(path)
        if not isinstance(payload, dict):
            raise ValueError(f"{path.name} must be a JSON object")
        return payload

    def _load_json(self, path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name} is not valid JSON: {exc}") from exc

    def _raise_for_fatal_quality_errors(self, quality_report: dict[str, Any]) -> None:
        fatal_errors = quality_report.get("fatal_errors") or []
        if fatal_errors:
            raise ValueError(f"quality_report.fatal_errors is not empty: {fatal_errors}")

    def _required_str(self, payload: dict[str, Any], keys: list[str], contract_name: str) -> str:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        raise ValueError(f"{contract_name} is required")

    def _normalize_chunk_id(self, doc_id: str, local_id: str) -> str:
        if local_id.startswith(f"{doc_id}:"):
            return local_id
        return f"{doc_id}:{local_id}"

    def _normalize_table_chunk_id(self, doc_id: str, table_id: str) -> str:
        prefix = f"{doc_id}:table:"
        if table_id.startswith(prefix):
            return table_id
        if table_id.startswith(f"{doc_id}:"):
            return table_id
        return f"{prefix}{table_id}"

    def _list_or_empty(self, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []


artifact_chunk_builder_service = ArtifactChunkBuilderService()
