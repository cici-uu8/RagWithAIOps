"""Map chunk/search/result payloads into one retrieval evidence shape."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field

from app.models import ParserEngine, RetrievalResult, SourceRef


class ChunkEvidence(BaseModel):
    """Stable retrieval evidence shared by retrieval, citations, tools, and evals."""

    kb_id: str
    doc_id: str
    chunk_id: str
    source_ref: SourceRef
    title: str
    source_uri: str
    score: float | None = None
    retrieval_path: str
    chunk_role: str | None = None
    parent_chunk_id: str | None = None
    page: int | None = None
    section: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkEvidenceMapper:
    """Adapter layer for dense/sparse/rerank hit metadata and retrieval results."""

    REQUIRED_FIELDS = (
        "kb_id",
        "doc_id",
        "chunk_id",
        "source_ref",
        "title",
        "source_uri",
        "score",
        "retrieval_path",
    )
    REQUIRED_SOURCE_REF_FIELDS = ("kb_id", "doc_id", "chunk_id", "source_file")

    @classmethod
    def from_index_metadata(
        cls,
        metadata: dict[str, Any] | str | None,
        *,
        score: float | None = None,
        retrieval_path: str | None = None,
        hit_id: str | None = None,
        content: str = "",
    ) -> ChunkEvidence:
        normalized = cls._normalize_metadata(metadata)
        source_ref_payload = cls._source_ref_payload(normalized)
        kb_id = str(
            source_ref_payload.get("kb_id")
            or normalized.get("kb_id")
            or ""
        )
        doc_id = str(
            source_ref_payload.get("doc_id")
            or normalized.get("doc_id")
            or ""
        )
        raw_chunk_id = (
            source_ref_payload.get("chunk_id")
            or normalized.get("chunk_id")
            or hit_id
            or ""
        )
        diagnostics: dict[str, Any] = {}
        chunk_id = str(raw_chunk_id or "")
        if not chunk_id and doc_id:
            chunk_id = cls._legacy_chunk_id(doc_id, normalized, content)
            diagnostics["legacy_chunk_id_fallback"] = True

        source_file = str(
            source_ref_payload.get("source_file")
            or normalized.get("source_file")
            or normalized.get("_file_name")
            or normalized.get("file_name")
            or ""
        )
        heading_path = cls._heading_path(source_ref_payload.get("heading_path", normalized.get("heading_path")))
        page_start = cls._optional_int(source_ref_payload.get("page_start", normalized.get("page_start")))
        page_end = cls._optional_int(source_ref_payload.get("page_end", normalized.get("page_end")))
        content_type = str(source_ref_payload.get("content_type") or normalized.get("content_type") or "text")
        parser_engine = cls._parser_engine(
            source_ref_payload.get("parser_engine", normalized.get("parser_engine", ParserEngine.PLAIN_TEXT.value))
        )
        source_ref = SourceRef(
            kb_id=kb_id,
            doc_id=doc_id,
            chunk_id=chunk_id,
            source_file=source_file,
            page_start=page_start,
            page_end=page_end,
            heading_path=heading_path,
            content_type=content_type,
            parser_engine=parser_engine,
        )

        evidence_metadata = dict(normalized)
        if diagnostics:
            evidence_metadata["evidence_diagnostics"] = {
                **dict(evidence_metadata.get("evidence_diagnostics") or {}),
                **diagnostics,
            }

        path = retrieval_path or str(normalized.get("retrieval_path") or normalized.get("retrieval_mode") or "dense")
        source_uri = str(
            normalized.get("source_uri")
            or normalized.get("_source")
            or normalized.get("original_path")
            or source_file
        )
        title = str(
            normalized.get("title")
            or normalized.get("document_title")
            or normalized.get("file_name")
            or source_file
        )
        return ChunkEvidence(
            kb_id=kb_id,
            doc_id=doc_id,
            chunk_id=chunk_id,
            source_ref=source_ref,
            title=title,
            source_uri=source_uri,
            score=score,
            retrieval_path=path,
            chunk_role=cls._optional_str(normalized.get("chunk_role")),
            parent_chunk_id=cls._optional_str(normalized.get("parent_chunk_id")),
            page=page_start or cls._optional_int(normalized.get("page")),
            section=" > ".join(heading_path) if heading_path else None,
            metadata=evidence_metadata,
        )

    @classmethod
    def from_sparse_hit(cls, hit: Any) -> ChunkEvidence:
        return cls.from_index_metadata(
            getattr(hit, "metadata", {}),
            score=cls._optional_float(getattr(hit, "score", None)),
            retrieval_path=str(
                cls._normalize_metadata(getattr(hit, "metadata", {})).get("retrieval_mode")
                or "sparse_only"
            ),
            hit_id=getattr(hit, "id", None),
            content=str(getattr(hit, "content", "") or ""),
        )

    @classmethod
    def from_vector_hit(cls, hit: Any) -> ChunkEvidence:
        metadata = cls._normalize_metadata(getattr(hit, "metadata", {}))
        return cls.from_index_metadata(
            metadata,
            score=cls._optional_float(getattr(hit, "score", None)),
            retrieval_path=str(metadata.get("retrieval_mode") or "dense"),
            hit_id=getattr(hit, "id", None),
            content=str(getattr(hit, "content", "") or ""),
        )

    @classmethod
    def from_retrieval_result(cls, result: RetrievalResult | dict[str, Any] | Any) -> ChunkEvidence:
        metadata = cls._normalize_metadata(cls._value(result, "metadata") or {})
        source_ref = cls._value(result, "source_ref")
        if isinstance(source_ref, SourceRef):
            source_ref_payload = source_ref.model_dump(mode="json")
        elif isinstance(source_ref, dict):
            source_ref_payload = dict(source_ref)
        else:
            source_ref_payload = {}
        metadata = {
            **metadata,
            "kb_id": cls._value(result, "kb_id") or metadata.get("kb_id", ""),
            "doc_id": cls._value(result, "doc_id") or metadata.get("doc_id", ""),
            "chunk_id": cls._value(result, "chunk_id") or metadata.get("chunk_id", ""),
        }
        if source_ref_payload:
            source_ref_payload = {
                **source_ref_payload,
                "kb_id": metadata["kb_id"],
                "doc_id": metadata["doc_id"],
                "chunk_id": metadata["chunk_id"],
            }
            metadata["source_ref"] = source_ref_payload
        else:
            metadata.setdefault("source_ref", {})
        return cls.from_index_metadata(
            metadata,
            score=cls._optional_float(cls._value(result, "score")),
            retrieval_path=str(metadata.get("retrieval_mode") or metadata.get("retrieval_path") or "retrieval_result"),
            hit_id=cls._value(result, "chunk_id"),
            content=str(cls._value(result, "content") or ""),
        )

    @staticmethod
    def to_source_ref(evidence: ChunkEvidence | dict[str, Any]) -> SourceRef:
        if isinstance(evidence, ChunkEvidence):
            return evidence.source_ref
        source_ref = evidence.get("source_ref") if isinstance(evidence, dict) else None
        if isinstance(source_ref, SourceRef):
            return source_ref
        if isinstance(source_ref, dict):
            payload = dict(source_ref)
        else:
            payload = {}
        payload.setdefault("kb_id", evidence.get("kb_id", "") if isinstance(evidence, dict) else "")
        payload.setdefault("doc_id", evidence.get("doc_id", "") if isinstance(evidence, dict) else "")
        payload.setdefault("chunk_id", evidence.get("chunk_id", "") if isinstance(evidence, dict) else "")
        payload.setdefault("source_file", evidence.get("source_uri", "") if isinstance(evidence, dict) else "")
        payload.setdefault("parser_engine", ParserEngine.PLAIN_TEXT.value)
        payload["parser_engine"] = ChunkEvidenceMapper._parser_engine(payload.get("parser_engine"))
        return SourceRef.model_validate(payload)

    @classmethod
    def validate_required_fields(cls, evidence: ChunkEvidence | dict[str, Any] | Any) -> list[str]:
        payload = evidence.model_dump(mode="json") if isinstance(evidence, BaseModel) else evidence
        missing: list[str] = []
        for field in cls.REQUIRED_FIELDS:
            if not cls._has_value(cls._value(payload, field)):
                missing.append(field)
        source_ref = cls._value(payload, "source_ref")
        for field in cls.REQUIRED_SOURCE_REF_FIELDS:
            if not cls._has_value(cls._value(source_ref, field)):
                missing.append(f"source_ref.{field}")
        return missing

    @staticmethod
    def _normalize_metadata(metadata: dict[str, Any] | str | None | Any) -> dict[str, Any]:
        if isinstance(metadata, dict):
            return dict(metadata)
        if isinstance(metadata, str):
            try:
                parsed = json.loads(metadata)
            except json.JSONDecodeError:
                return {}
            return dict(parsed) if isinstance(parsed, dict) else {}
        return {}

    @classmethod
    def _source_ref_payload(cls, metadata: dict[str, Any]) -> dict[str, Any]:
        payload = metadata.get("source_ref")
        if isinstance(payload, SourceRef):
            return payload.model_dump(mode="json")
        if isinstance(payload, dict):
            return dict(payload)
        if isinstance(payload, str):
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                return {}
            return dict(parsed) if isinstance(parsed, dict) else {}
        return {}

    @staticmethod
    def _parser_engine(value: Any) -> ParserEngine:
        if isinstance(value, ParserEngine):
            return value
        try:
            return ParserEngine(str(value))
        except Exception:
            return ParserEngine.PLAIN_TEXT

    @staticmethod
    def _heading_path(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        if isinstance(value, tuple):
            return [str(item) for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [part.strip() for part in value.split(">") if part.strip()]
        return []

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_str(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text if text else None

    @staticmethod
    def _legacy_chunk_id(doc_id: str, metadata: dict[str, Any], content: str) -> str:
        stable_seed = json.dumps(
            {
                "doc_id": doc_id,
                "source_file": metadata.get("source_file") or metadata.get("_file_name") or "",
                "page_start": metadata.get("page_start"),
                "heading_path": metadata.get("heading_path"),
                "content": content,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.sha1(stable_seed.encode("utf-8")).hexdigest()[:12]
        return f"{doc_id}:legacy:{digest}"

    @staticmethod
    def _value(item: Any, key: str) -> Any:
        if item is None:
            return None
        if isinstance(item, dict):
            return item.get(key)
        return getattr(item, key, None)

    @staticmethod
    def _has_value(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        return True
