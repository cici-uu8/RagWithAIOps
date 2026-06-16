"""B4 PDF Agent tool smoke runner for real indexed PDF artifacts."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import config
from app.enterprise.context import RequestContext
from app.enterprise.documents.service import DocumentAccessService
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.permissions.service import PermissionService, permission_service
from app.enterprise.tools.facade import ToolExecutionFacade
from app.enterprise.tools.gateway import ToolGateway
from app.enterprise.tools.pdf_document_provider import (
    EXTRACT_DOCUMENT_TABLE_TOOL_ID,
    PDF_AGENT_TOOL_IDS,
    READ_DOCUMENT_PAGE_TOOL_ID,
    PdfDocumentToolProvider,
)
from app.models import DocumentRecord
from app.services.knowledge_metadata_store import KnowledgeMetadataStore, knowledge_metadata_store

REQUIRED_SOURCE_REF_FIELDS = ("kb_id", "doc_id", "chunk_id", "source_file", "parser_engine")
FORBIDDEN_SCHEMA_TERMS = (
    "RequestContext",
    "owner_id",
    "artifact",
    "permission",
    "department_id",
)


async def build_pdf_agent_tool_smoke_report(
    *,
    doc_id: str,
    valid_page: int,
    expect_default_enabled: bool = False,
    invalid_page: int | None = None,
    table_id: str = "",
    invalid_table_id: str = "__missing_table__",
    authorized_user: str = "admin",
    authorized_roles: list[str] | None = None,
    denied_user: str = "user-denied",
    denied_roles: list[str] | None = None,
    metadata_store: KnowledgeMetadataStore | None = None,
    permission_service_: PermissionService | None = None,
    audit_service: AuditService | None = None,
    access_service: DocumentAccessService | None = None,
) -> dict[str, Any]:
    """Run B4-G1 smoke checks through the real ToolGateway path."""

    metadata_store = metadata_store or knowledge_metadata_store
    permission_service_ = permission_service_ or permission_service
    audit_service = audit_service or AuditService()
    access_service = access_service or DocumentAccessService(
        metadata_store=metadata_store,
        permission_service=permission_service_,
    )
    context = _request_context(authorized_user, roles=authorized_roles or ["admin"])
    denied_context = _request_context(denied_user, roles=denied_roles or ["user"])
    document = metadata_store.get_document(doc_id)
    tables = _load_document_tables(document)
    selected_table = _select_smoke_table(tables, table_id)
    selected_table_id = _table_id(selected_table)
    selected_table_page = _table_page(selected_table)

    default_provider = PdfDocumentToolProvider(
        metadata_store=metadata_store,
        access_service=access_service,
        enabled=None,
    )
    default_tools = await default_provider.list_tools()

    smoke_provider = PdfDocumentToolProvider(
        metadata_store=metadata_store,
        access_service=access_service,
        enabled=True,
    )
    gateway = ToolGateway(
        providers=[smoke_provider],
        permission_service=permission_service_,
        audit_service=audit_service,
        default_allowed_tool_ids=set(PDF_AGENT_TOOL_IDS),
    )
    facade = ToolExecutionFacade(gateway=gateway)

    visible_tools = await facade.list_visible_tools(context, capability="rag")
    schema_check = _schema_has_no_forbidden_terms(visible_tools)
    authorized_result = await _execute_read_page(
        facade=facade,
        context=context,
        doc_id=doc_id,
        page=valid_page,
    )
    authorized_page_read = _authorized_page_summary(authorized_result)
    leak_terms = _leak_terms(document, authorized_result)
    invalid_page_check = await _read_invalid_page(
        facade=facade,
        context=context,
        doc_id=doc_id,
        page=invalid_page,
        leak_terms=leak_terms,
    )
    denied_page_read = await _read_denied_page(
        facade=facade,
        context=denied_context,
        doc_id=doc_id,
        page=valid_page,
        leak_terms=leak_terms,
    )
    table_leak_terms = _table_leak_terms(document, selected_table)
    authorized_table_extract = await _extract_authorized_table(
        facade=facade,
        context=context,
        doc_id=doc_id,
        table_id=selected_table_id,
        page=selected_table_page,
        table_available=selected_table is not None,
    )
    invalid_table = await _extract_invalid_table(
        facade=facade,
        context=context,
        doc_id=doc_id,
        invalid_table_id=invalid_table_id,
        leak_terms=table_leak_terms,
    )
    denied_table_extract = await _extract_denied_table(
        facade=facade,
        context=denied_context,
        doc_id=doc_id,
        table_id=selected_table_id or invalid_table_id,
        page=selected_table_page,
        leak_terms=table_leak_terms,
    )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stage": "B4-G7" if expect_default_enabled else "B4-G3",
        "status": "failed",
        "doc_id": doc_id,
        "valid_page": valid_page,
        "invalid_page_number": invalid_page,
        "requested_table_id": table_id,
        "selected_table_id": selected_table_id,
        "selected_table_page": selected_table_page,
        "table_available": selected_table is not None,
        "table_count": len(tables),
        "invalid_table_id": invalid_table_id,
        "authorized_user": authorized_user,
        "denied_user": denied_user,
        "expected_default_enabled": expect_default_enabled,
        "default_enabled": bool(getattr(config, "pdf_agent_tools_enabled", False)),
        "default_tools_visible": [tool.resource_id for tool in default_tools],
        "temporary_smoke_enabled": True,
        "visible_pdf_tool_ids": sorted(
            tool.resource_id
            for tool in visible_tools
            if tool.resource_id in PDF_AGENT_TOOL_IDS
        ),
        "schema_has_no_context_or_owner": schema_check["passed"],
        "schema_check": schema_check,
        "authorized_page_read": authorized_page_read,
        "authorized_table_extract": authorized_table_extract,
        "invalid_page": invalid_page_check,
        "invalid_table": invalid_table,
        "denied_page_read": denied_page_read,
        "denied_table_extract": denied_table_extract,
    }
    report["status"] = "passed" if _g3_passed(report) else "failed"
    return report


def write_pdf_agent_tool_smoke_report(
    report: dict[str, Any],
    *,
    output_json: str | Path | None = None,
    output_md: str | Path | None = None,
) -> None:
    if output_json:
        output_json_path = Path(output_json)
        output_json_path.parent.mkdir(parents=True, exist_ok=True)
        output_json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if output_md:
        output_md_path = Path(output_md)
        output_md_path.parent.mkdir(parents=True, exist_ok=True)
        output_md_path.write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    read = report["authorized_page_read"]
    lines = [
        "# B4 PDF Agent Tool Smoke Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Stage: `{report['stage']}`",
        f"- Status: `{report['status']}`",
        f"- Doc ID: `{report['doc_id']}`",
        f"- Valid page: `{report['valid_page']}`",
        f"- Expected default enabled: `{report['expected_default_enabled']}`",
        f"- Default enabled: `{report['default_enabled']}`",
        f"- Temporary smoke enabled: `{report['temporary_smoke_enabled']}`",
        "",
        "| check | status | detail |",
        "|---|---|---|",
        f"| default config expectation | {'passed' if _default_enabled_check_passed(report) else 'failed'} | expected={report['expected_default_enabled']}, actual={report['default_enabled']}, default tools: `{report['default_tools_visible']}` |",
        f"| schema no forbidden params | {'passed' if report['schema_has_no_context_or_owner'] else 'failed'} | forbidden hits: `{report['schema_check']['forbidden_hits']}` |",
        f"| authorized page read | {read.get('status')} | content_non_empty={read.get('content_non_empty')}, source_refs_resolvable={read.get('source_refs_resolvable')} |",
        "",
    ]
    denied = report["denied_page_read"]
    invalid = report["invalid_page"]
    table = report["authorized_table_extract"]
    invalid_table = report["invalid_table"]
    denied_table = report["denied_table_extract"]
    lines.append(
        f"| invalid page | {invalid.get('status')} | error={invalid.get('error')}, leak_detected={invalid.get('leak_detected')} |"
    )
    lines.append(
        f"| denied page read | {denied.get('status')} | error={denied.get('error')}, leak_detected={denied.get('leak_detected')} |"
    )
    lines.append(
        f"| authorized table extract | {table.get('status')} | rows_non_empty={table.get('rows_non_empty')}, source_refs_resolvable={table.get('source_refs_resolvable')} |"
    )
    lines.append(
        f"| invalid table | {invalid_table.get('status')} | error={invalid_table.get('error')}, leak_detected={invalid_table.get('leak_detected')} |"
    )
    lines.append(
        f"| denied table extract | {denied_table.get('status')} | error={denied_table.get('error')}, leak_detected={denied_table.get('leak_detected')} |"
    )
    lines.append("")
    return "\n".join(lines)


async def _execute_read_page(
    *,
    facade: ToolExecutionFacade,
    context: RequestContext,
    doc_id: str,
    page: int,
) -> dict[str, Any]:
    try:
        return await facade.execute(
            context,
            READ_DOCUMENT_PAGE_TOOL_ID,
            {"doc_id": doc_id, "page": page},
        )
    except Exception as exc:
        return {
            "status": "exception",
            "error": type(exc).__name__,
            "message": str(exc),
        }


def _authorized_page_summary(result: dict[str, Any]) -> dict[str, Any]:
    source_refs = result.get("source_refs") if isinstance(result, dict) else []
    content = str(result.get("content") or "") if isinstance(result, dict) else ""
    return {
        "status": result.get("status") if isinstance(result, dict) else "invalid_result",
        "error": result.get("error") if isinstance(result, dict) else "invalid_result",
        "content_non_empty": bool(content.strip()),
        "content_chars": len(content),
        "source_ref_count": len(source_refs) if isinstance(source_refs, list) else 0,
        "source_refs_resolvable": _source_refs_resolvable(source_refs),
        "source_ref_missing_fields": _source_ref_missing_fields(source_refs),
    }


async def _read_denied_page(
    *,
    facade: ToolExecutionFacade,
    context: RequestContext,
    doc_id: str,
    page: int,
    leak_terms: list[str],
) -> dict[str, Any]:
    result = await _execute_read_page(
        facade=facade,
        context=context,
        doc_id=doc_id,
        page=page,
    )
    result_text = json.dumps(result, ensure_ascii=False, sort_keys=True)
    matched_terms = [term for term in leak_terms if term and term in result_text]
    return {
        "status": result.get("status") if isinstance(result, dict) else "invalid_result",
        "error": result.get("error") if isinstance(result, dict) else "invalid_result",
        "leak_detected": bool(matched_terms),
        "matched_leak_terms": matched_terms,
        "response_keys": sorted(result) if isinstance(result, dict) else [],
    }


async def _read_invalid_page(
    *,
    facade: ToolExecutionFacade,
    context: RequestContext,
    doc_id: str,
    page: int | None,
    leak_terms: list[str],
) -> dict[str, Any]:
    if page is None:
        return _not_run("B4-G2", requested={"page": None})
    result = await _execute_read_page(
        facade=facade,
        context=context,
        doc_id=doc_id,
        page=page,
    )
    result_text = json.dumps(result, ensure_ascii=False, sort_keys=True)
    matched_terms = [term for term in leak_terms if term and term in result_text]
    return {
        "status": result.get("status") if isinstance(result, dict) else "invalid_result",
        "error": result.get("error") if isinstance(result, dict) else "invalid_result",
        "page": page,
        "leak_detected": bool(matched_terms),
        "matched_leak_terms": matched_terms,
        "response_keys": sorted(result) if isinstance(result, dict) else [],
    }


async def _execute_extract_table(
    *,
    facade: ToolExecutionFacade,
    context: RequestContext,
    doc_id: str,
    table_id: str = "",
    page: int | None = None,
) -> dict[str, Any]:
    arguments: dict[str, Any] = {"doc_id": doc_id}
    if table_id:
        arguments["table_id"] = table_id
    if page is not None:
        arguments["page"] = page
    try:
        return await facade.execute(
            context,
            EXTRACT_DOCUMENT_TABLE_TOOL_ID,
            arguments,
        )
    except Exception as exc:
        return {
            "status": "exception",
            "error": type(exc).__name__,
            "message": str(exc),
        }


async def _extract_authorized_table(
    *,
    facade: ToolExecutionFacade,
    context: RequestContext,
    doc_id: str,
    table_id: str,
    page: int | None,
    table_available: bool,
) -> dict[str, Any]:
    if not table_available:
        return {
            "status": "not_applicable",
            "reason": "no_tables_found",
        }
    result = await _execute_extract_table(
        facade=facade,
        context=context,
        doc_id=doc_id,
        table_id=table_id,
        page=page,
    )
    rows = result.get("rows") if isinstance(result, dict) else []
    markdown = str(result.get("markdown") or "") if isinstance(result, dict) else ""
    source_refs = result.get("source_refs") if isinstance(result, dict) else []
    return {
        "status": result.get("status") if isinstance(result, dict) else "invalid_result",
        "error": result.get("error") if isinstance(result, dict) else "invalid_result",
        "table_id": result.get("table_id") if isinstance(result, dict) else "",
        "page": result.get("page") if isinstance(result, dict) else None,
        "rows_non_empty": bool(rows),
        "row_count": len(rows) if isinstance(rows, list) else 0,
        "markdown_non_empty": bool(markdown.strip()),
        "source_ref_count": len(source_refs) if isinstance(source_refs, list) else 0,
        "source_refs_resolvable": _source_refs_resolvable(source_refs),
        "source_ref_missing_fields": _source_ref_missing_fields(source_refs),
    }


async def _extract_invalid_table(
    *,
    facade: ToolExecutionFacade,
    context: RequestContext,
    doc_id: str,
    invalid_table_id: str,
    leak_terms: list[str],
) -> dict[str, Any]:
    result = await _execute_extract_table(
        facade=facade,
        context=context,
        doc_id=doc_id,
        table_id=invalid_table_id,
    )
    matched_terms = _matched_leak_terms(result, leak_terms)
    return {
        "status": result.get("status") if isinstance(result, dict) else "invalid_result",
        "error": result.get("error") if isinstance(result, dict) else "invalid_result",
        "table_id": invalid_table_id,
        "leak_detected": bool(matched_terms),
        "matched_leak_terms": matched_terms,
        "response_keys": sorted(result) if isinstance(result, dict) else [],
    }


async def _extract_denied_table(
    *,
    facade: ToolExecutionFacade,
    context: RequestContext,
    doc_id: str,
    table_id: str,
    page: int | None,
    leak_terms: list[str],
) -> dict[str, Any]:
    result = await _execute_extract_table(
        facade=facade,
        context=context,
        doc_id=doc_id,
        table_id=table_id,
        page=page,
    )
    matched_terms = _matched_leak_terms(result, leak_terms)
    return {
        "status": result.get("status") if isinstance(result, dict) else "invalid_result",
        "error": result.get("error") if isinstance(result, dict) else "invalid_result",
        "leak_detected": bool(matched_terms),
        "matched_leak_terms": matched_terms,
        "response_keys": sorted(result) if isinstance(result, dict) else [],
    }


def _leak_terms(document: DocumentRecord | None, authorized_result: dict[str, Any]) -> list[str]:
    terms: set[str] = {
        "artifact",
        "artifact_dir",
        "blocks.json",
        "tables.json",
        "source_refs",
        "source_ref",
        "chunk_id",
        "parser_engine",
    }
    if document is not None:
        for value in [document.file_name, document.original_path, document.artifact_dir]:
            if value:
                terms.add(str(value))
                name = Path(str(value)).name
                if name:
                    terms.add(name)
    content = str(authorized_result.get("content") or "") if isinstance(authorized_result, dict) else ""
    for snippet in _content_snippets(content):
        terms.add(snippet)
    return sorted(term for term in terms if len(term) >= 3)


def _table_leak_terms(document: DocumentRecord | None, table: dict[str, Any] | None) -> list[str]:
    terms = set(_leak_terms(document, {}))
    if table:
        for key in ("table_id", "id", "markdown"):
            value = table.get(key)
            if value:
                terms.add(str(value))
        rows = table.get("rows")
        if isinstance(rows, list):
            for row in rows[:5]:
                if isinstance(row, list):
                    for cell in row[:5]:
                        text = str(cell).strip()
                        if text:
                            terms.add(text)
    return sorted(term for term in terms if len(term) >= 2)


def _matched_leak_terms(result: dict[str, Any], leak_terms: list[str]) -> list[str]:
    result_text = json.dumps(result, ensure_ascii=False, sort_keys=True)
    return [term for term in leak_terms if term and term in result_text]


def _content_snippets(content: str) -> list[str]:
    stripped = content.strip()
    if not stripped:
        return []
    snippets = [stripped[:80]]
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    snippets.extend(line[:80] for line in lines[:3])
    return [snippet for snippet in snippets if len(snippet) >= 6]


def _schema_has_no_forbidden_terms(tools: list[Any]) -> dict[str, Any]:
    schema_payload = [
        {
            "tool_id": tool.resource_id,
            "input_schema": tool.input_schema,
        }
        for tool in tools
        if tool.resource_id in PDF_AGENT_TOOL_IDS
    ]
    schema_text = json.dumps(schema_payload, ensure_ascii=False)
    forbidden_hits = [term for term in FORBIDDEN_SCHEMA_TERMS if term in schema_text]
    return {
        "passed": not forbidden_hits and len(schema_payload) == len(PDF_AGENT_TOOL_IDS),
        "forbidden_hits": forbidden_hits,
        "tool_count": len(schema_payload),
    }


def _source_refs_resolvable(source_refs: Any) -> bool:
    if not isinstance(source_refs, list) or not source_refs:
        return False
    return not _source_ref_missing_fields(source_refs)


def _source_ref_missing_fields(source_refs: Any) -> list[dict[str, Any]]:
    if not isinstance(source_refs, list):
        return [{"index": -1, "missing": list(REQUIRED_SOURCE_REF_FIELDS)}]
    missing_rows: list[dict[str, Any]] = []
    for index, source_ref in enumerate(source_refs):
        if not isinstance(source_ref, dict):
            missing_rows.append({"index": index, "missing": list(REQUIRED_SOURCE_REF_FIELDS)})
            continue
        missing = [field for field in REQUIRED_SOURCE_REF_FIELDS if not source_ref.get(field)]
        if missing:
            missing_rows.append({"index": index, "missing": missing})
    return missing_rows


def _g1_passed(report: dict[str, Any]) -> bool:
    read = report["authorized_page_read"]
    return (
        _default_enabled_check_passed(report)
        and report["schema_has_no_context_or_owner"] is True
        and read.get("status") == "success"
        and read.get("content_non_empty") is True
        and read.get("source_refs_resolvable") is True
    )


def _default_enabled_check_passed(report: dict[str, Any]) -> bool:
    expected = bool(report.get("expected_default_enabled", False))
    actual = bool(report.get("default_enabled", False))
    visible_tools = set(report.get("default_tools_visible") or [])
    if actual is not expected:
        return False
    if expected:
        return set(PDF_AGENT_TOOL_IDS).issubset(visible_tools)
    return not visible_tools


def _g2_passed(report: dict[str, Any]) -> bool:
    denied = report["denied_page_read"]
    invalid = report["invalid_page"]
    return (
        _g1_passed(report)
        and invalid.get("status") == "error"
        and invalid.get("error") == "page_out_of_range"
        and invalid.get("leak_detected") is False
        and denied.get("status") == "error"
        and denied.get("error") == "permission_denied"
        and denied.get("leak_detected") is False
    )


def _g3_passed(report: dict[str, Any]) -> bool:
    invalid_table = report["invalid_table"]
    denied_table = report["denied_table_extract"]
    return (
        _g2_passed(report)
        and _authorized_table_passed(report)
        and invalid_table.get("status") == "error"
        and invalid_table.get("error") == "table_not_found"
        and invalid_table.get("leak_detected") is False
        and denied_table.get("status") == "error"
        and denied_table.get("error") == "permission_denied"
        and denied_table.get("leak_detected") is False
    )


def _authorized_table_passed(report: dict[str, Any]) -> bool:
    table = report["authorized_table_extract"]
    if report.get("table_available") is False:
        return table.get("status") == "not_applicable"
    return (
        table.get("status") == "success"
        and (table.get("rows_non_empty") is True or table.get("markdown_non_empty") is True)
        and table.get("source_refs_resolvable") is True
    )


def _load_document_tables(document: DocumentRecord | None) -> list[dict[str, Any]]:
    if document is None or not document.artifact_dir:
        return []
    path = Path(document.artifact_dir) / "tables.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_tables = payload.get("tables", []) if isinstance(payload, dict) else payload
    if not isinstance(raw_tables, list):
        return []
    return [table for table in raw_tables if isinstance(table, dict)]


def _select_smoke_table(tables: list[dict[str, Any]], requested_table_id: str) -> dict[str, Any] | None:
    requested = requested_table_id.strip()
    if requested and requested != "t_expected_if_known":
        for table in tables:
            if _table_id(table) == requested:
                return table
    return tables[0] if tables else None


def _table_id(table: dict[str, Any] | None) -> str:
    if not table:
        return ""
    return str(table.get("table_id") or table.get("id") or "")


def _table_page(table: dict[str, Any] | None) -> int | None:
    if not table:
        return None
    for key in ("page", "page_start", "page_no"):
        value = table.get(key)
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.isdigit() and int(value) > 0:
            return int(value)
    return None


def _request_context(user_id: str, *, roles: list[str]) -> RequestContext:
    return RequestContext(
        request_id=f"b4-smoke-{user_id}",
        trace_id=f"b4-smoke-{user_id}",
        user_id=user_id,
        username=user_id,
        department_id="smoke",
        department_name="Smoke",
        roles=roles,
    )


def _not_run(stage: str, *, requested: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "not_run",
        "reason": f"reserved_for_{stage}",
    }
    if requested is not None:
        payload["requested"] = requested
    return payload


def _parse_roles(raw: str) -> list[str]:
    roles = [item.strip() for item in raw.split(",") if item.strip()]
    return roles or ["admin"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run B4 PDF Agent tool smoke checks.")
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--valid-page", type=int, required=True)
    parser.add_argument(
        "--expect-default-enabled",
        action="store_true",
        help="Expect the process config to expose PDF tools, for approved local G7 enablement.",
    )
    parser.add_argument("--invalid-page", type=int, default=None)
    parser.add_argument("--table-id", default="")
    parser.add_argument("--invalid-table-id", default="__missing_table__")
    parser.add_argument("--authorized-user", default="admin")
    parser.add_argument("--authorized-roles", default="admin")
    parser.add_argument("--denied-user", default="user-denied")
    parser.add_argument("--denied-roles", default="user")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    report = asyncio.run(
        build_pdf_agent_tool_smoke_report(
            doc_id=args.doc_id,
            valid_page=args.valid_page,
            expect_default_enabled=args.expect_default_enabled,
            invalid_page=args.invalid_page,
            table_id=args.table_id,
            invalid_table_id=args.invalid_table_id,
            authorized_user=args.authorized_user,
            authorized_roles=_parse_roles(args.authorized_roles),
            denied_user=args.denied_user,
            denied_roles=_parse_roles(args.denied_roles),
        )
    )
    write_pdf_agent_tool_smoke_report(
        report,
        output_json=args.output_json or None,
        output_md=args.output_md or None,
    )
    if not args.output_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
