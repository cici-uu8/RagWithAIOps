"""Permission-aware PDF artifact tools for local RAG agents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.config import config
from app.enterprise.context import RequestContext
from app.enterprise.documents.service import DocumentAccessService, document_access_service
from app.enterprise.tools.models import ToolDefinition
from app.models import DocumentRecord
from app.services.knowledge_metadata_store import KnowledgeMetadataStore, knowledge_metadata_store

READ_DOCUMENT_PAGE_TOOL_ID = "pdf.read_document_page"
EXTRACT_DOCUMENT_TABLE_TOOL_ID = "pdf.extract_document_table"
PDF_AGENT_TOOL_IDS = {
    READ_DOCUMENT_PAGE_TOOL_ID,
    EXTRACT_DOCUMENT_TABLE_TOOL_ID,
}


class ReadDocumentPageInput(BaseModel):
    doc_id: str = Field(..., min_length=1, description="Document id to read.")
    page: int = Field(..., ge=1, description="One-based page number to read.")


class ExtractDocumentTableInput(BaseModel):
    doc_id: str = Field(..., min_length=1, description="Document id to read.")
    table_id: str | None = Field(None, description="Optional table id to extract.")
    page: int | None = Field(None, ge=1, description="Optional one-based page number.")


class PdfDocumentToolProvider:
    """Expose PDF page/table artifact reads behind document access checks."""

    source = "pdf-artifact"

    def __init__(
        self,
        *,
        metadata_store: KnowledgeMetadataStore | None = None,
        access_service: DocumentAccessService | None = None,
        enabled: bool | None = None,
    ):
        self.metadata_store = metadata_store or knowledge_metadata_store
        self.access_service = access_service or document_access_service
        self.enabled = enabled
        self._tools = [
            ToolDefinition(
                resource_id=READ_DOCUMENT_PAGE_TOOL_ID,
                name="read_document_page",
                description="Read one page from a visible PDF document artifact.",
                source=self.source,
                raw_tool=_read_document_page_bindable_tool(),
                input_schema=read_document_page_input_schema(),
                metadata={"category": "pdf", "capability": "rag", "requires_context": True},
            ),
            ToolDefinition(
                resource_id=EXTRACT_DOCUMENT_TABLE_TOOL_ID,
                name="extract_document_table",
                description="Extract one visible PDF table by table id or page.",
                source=self.source,
                raw_tool=_extract_document_table_bindable_tool(),
                input_schema=extract_document_table_input_schema(),
                metadata={"category": "pdf", "capability": "rag", "requires_context": True},
            ),
        ]

    async def list_tools(self) -> list[ToolDefinition]:
        if not self._is_enabled():
            return []
        return list(self._tools)

    async def execute_tool(self, resource_id: str, arguments: dict[str, Any]) -> Any:
        raise RuntimeError("pdf_document_tools_require_request_context")

    async def execute_tool_with_context(
        self,
        resource_id: str,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        if resource_id == READ_DOCUMENT_PAGE_TOOL_ID:
            request = ReadDocumentPageInput.model_validate(arguments)
            return self._read_document_page(
                doc_id=request.doc_id,
                page=request.page,
                context=context,
            )
        if resource_id == EXTRACT_DOCUMENT_TABLE_TOOL_ID:
            request = ExtractDocumentTableInput.model_validate(arguments)
            return self._extract_document_table(
                doc_id=request.doc_id,
                table_id=request.table_id,
                page=request.page,
                context=context,
            )
        raise KeyError(resource_id)

    def _is_enabled(self) -> bool:
        if self.enabled is not None:
            return self.enabled
        return bool(getattr(config, "pdf_agent_tools_enabled", False))

    def _read_document_page(
        self,
        *,
        doc_id: str,
        page: int,
        context: RequestContext,
    ) -> dict[str, Any]:
        document = self.metadata_store.get_document(doc_id)
        if document is None:
            return _error("document_not_found")
        if not self.access_service.can_read_document(context, document):
            return _error("permission_denied")

        blocks = _load_artifact_items(document.artifact_dir, "blocks.json", "blocks")
        if blocks is None:
            return _error("artifact_missing")

        page_blocks = [block for block in blocks if _item_matches_page(block, page)]
        if not page_blocks:
            return _error("page_out_of_range")

        content = "\n\n".join(
            text
            for text in (_block_text(block) for block in page_blocks)
            if text
        ).strip()
        return {
            "status": "success",
            "doc_id": document.doc_id,
            "kb_id": document.kb_id,
            "page": page,
            "content": content,
            "source_refs": self._source_refs_for_page(document, page),
        }

    def _extract_document_table(
        self,
        *,
        doc_id: str,
        table_id: str | None,
        page: int | None,
        context: RequestContext,
    ) -> dict[str, Any]:
        document = self.metadata_store.get_document(doc_id)
        if document is None:
            return _error("document_not_found")
        if not self.access_service.can_read_document(context, document):
            return _error("permission_denied")

        tables = _load_artifact_items(document.artifact_dir, "tables.json", "tables")
        if tables is None:
            return _error("artifact_missing")

        table = _select_table(tables, table_id=table_id, page=page)
        if table is None:
            return _error("table_not_found")

        table_page = _first_page(table)
        return {
            "status": "success",
            "doc_id": document.doc_id,
            "kb_id": document.kb_id,
            "table_id": str(table.get("table_id") or ""),
            "page": table_page,
            "page_start": table.get("page_start", table_page),
            "page_end": table.get("page_end", table_page),
            "rows": table.get("rows") or [],
            "markdown": str(table.get("markdown") or ""),
            "quality_flags": _list_or_empty(table.get("quality_flags")),
            "source_refs": (
                self._source_refs_for_page(document, int(table_page))
                if isinstance(table_page, int)
                else []
            ),
        }

    def _source_refs_for_page(self, document: DocumentRecord, page: int) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for chunk in self.metadata_store.list_chunks_by_doc_id(document.doc_id):
            if _page_in_range(page, chunk.page_start, chunk.page_end):
                refs.append(chunk.source_ref.model_dump(mode="json"))
        if refs:
            return refs
        return [
            {
                "kb_id": document.kb_id,
                "doc_id": document.doc_id,
                "page_start": page,
                "page_end": page,
                "source_file": document.file_name,
                "artifact_source": "blocks_json",
            }
        ]


def read_document_page_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "doc_id": {
                "type": "string",
                "minLength": 1,
                "description": "Document id to read.",
            },
            "page": {
                "type": "integer",
                "minimum": 1,
                "description": "One-based page number to read.",
            },
        },
        "required": ["doc_id", "page"],
        "additionalProperties": False,
    }


def extract_document_table_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "doc_id": {
                "type": "string",
                "minLength": 1,
                "description": "Document id to read.",
            },
            "table_id": {
                "type": "string",
                "description": "Optional table id to extract.",
            },
            "page": {
                "type": "integer",
                "minimum": 1,
                "description": "Optional one-based page number.",
            },
        },
        "required": ["doc_id"],
        "additionalProperties": False,
    }


async def _read_document_page_schema_only(doc_id: str, page: int) -> dict[str, Any]:
    raise RuntimeError("read_document_page must execute through ToolGateway")


async def _extract_document_table_schema_only(
    doc_id: str,
    table_id: str | None = None,
    page: int | None = None,
) -> dict[str, Any]:
    raise RuntimeError("extract_document_table must execute through ToolGateway")


def _read_document_page_bindable_tool() -> StructuredTool:
    return StructuredTool.from_function(
        coroutine=_read_document_page_schema_only,
        name="read_document_page",
        description="Read one page from a visible PDF document artifact.",
        args_schema=ReadDocumentPageInput,
    )


def _extract_document_table_bindable_tool() -> StructuredTool:
    return StructuredTool.from_function(
        coroutine=_extract_document_table_schema_only,
        name="extract_document_table",
        description="Extract one visible PDF table by table id or page.",
        args_schema=ExtractDocumentTableInput,
    )


def _load_artifact_items(
    artifact_dir: str,
    file_name: str,
    collection_key: str,
) -> list[dict[str, Any]] | None:
    path = Path(artifact_dir) / file_name
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        raw_items = payload.get(collection_key, [])
    else:
        raw_items = payload
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, dict)]


def _select_table(
    tables: list[dict[str, Any]],
    *,
    table_id: str | None,
    page: int | None,
) -> dict[str, Any] | None:
    normalized_table_id = (table_id or "").strip()
    if normalized_table_id:
        return next(
            (
                table
                for table in tables
                if str(table.get("table_id") or "") == normalized_table_id
            ),
            None,
        )
    if page is not None:
        return next((table for table in tables if _item_matches_page(table, page)), None)
    return tables[0] if tables else None


def _item_matches_page(item: dict[str, Any], page: int) -> bool:
    pages = _pages(item)
    if pages:
        return page in pages
    first_page = _first_page(item)
    if isinstance(first_page, int):
        return first_page == page
    return False


def _pages(item: dict[str, Any]) -> set[int]:
    value = item.get("pages")
    if not isinstance(value, list):
        return set()
    pages: set[int] = set()
    for raw_page in value:
        coerced = _coerce_positive_int(raw_page)
        if coerced is not None:
            pages.add(coerced)
    return pages


def _first_page(item: dict[str, Any]) -> int | None:
    for key in ("page", "page_start", "page_no"):
        coerced = _coerce_positive_int(item.get(key))
        if coerced is not None:
            return coerced
    return None


def _page_in_range(
    page: int,
    page_start: int | None,
    page_end: int | None,
) -> bool:
    if page_start is None:
        return False
    effective_end = page_end if page_end is not None else page_start
    return page_start <= page <= effective_end


def _block_text(block: dict[str, Any]) -> str:
    for key in ("text", "content", "markdown"):
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _coerce_positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return None
    return coerced if coerced >= 1 else None


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _error(reason: str) -> dict[str, str]:
    return {"status": "error", "error": reason}
