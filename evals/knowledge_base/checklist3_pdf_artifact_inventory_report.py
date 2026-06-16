"""Checklist 3 indexed PDF artifact inventory helpers."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_METADATA_STORE = "uploads/_metadata/knowledge_metadata_store.json"
DEFAULT_IMPORT_STATE = "data/knowledge_ingestion/current_import_state.json"
PAGE_COVERAGE_THRESHOLD = 0.95


def build_checklist3_pdf_artifact_inventory_report(
    *,
    metadata_store_path: str | Path = DEFAULT_METADATA_STORE,
    import_state_path: str | Path = DEFAULT_IMPORT_STATE,
    page_coverage_threshold: float = PAGE_COVERAGE_THRESHOLD,
) -> dict[str, Any]:
    metadata_store = Path(metadata_store_path)
    import_state = Path(import_state_path)
    current_state_docs = _load_current_import_state_docs(import_state)
    current_state_doc_ids = {doc["doc_id"] for doc in current_state_docs}
    pdf_docs = _load_indexed_pdf_documents(metadata_store)
    rows = [
        _inspect_pdf_document(
            doc,
            in_current_import_state=doc["doc_id"] in current_state_doc_ids,
            page_coverage_threshold=page_coverage_threshold,
        )
        for doc in pdf_docs
    ]
    summary = _build_summary(rows, current_state_docs)
    coverage_gaps = _coverage_gaps(summary)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": _inventory_status(summary, coverage_gaps),
        "metadata_store_path": metadata_store.as_posix(),
        "import_state_path": import_state.as_posix(),
        "page_coverage_threshold": page_coverage_threshold,
        "summary": summary,
        "documents": rows,
        "coverage_gaps": coverage_gaps,
    }


def write_checklist3_pdf_artifact_inventory_report(
    *,
    metadata_store_path: str | Path = DEFAULT_METADATA_STORE,
    import_state_path: str | Path = DEFAULT_IMPORT_STATE,
    page_coverage_threshold: float = PAGE_COVERAGE_THRESHOLD,
    output_json: str | Path,
    output_md: str | Path | None = None,
) -> dict[str, Any]:
    report = build_checklist3_pdf_artifact_inventory_report(
        metadata_store_path=metadata_store_path,
        import_state_path=import_state_path,
        page_coverage_threshold=page_coverage_threshold,
    )
    output_json_path = Path(output_json)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if output_md is not None:
        output_md_path = Path(output_md)
        output_md_path.parent.mkdir(parents=True, exist_ok=True)
        output_md_path.write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Checklist 3 PDF Artifact Inventory Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Status: `{report['status']}`",
        f"- Metadata store: `{report['metadata_store_path']}`",
        f"- Import state: `{report['import_state_path']}`",
        f"- Summary: {report['summary']}",
        f"- Coverage gaps: {report['coverage_gaps'] or []}",
        "",
        "| doc_id | kb_id | file | artifact | blocks | page coverage | tables | suitability | issues |",
        "|---|---|---|---|---:|---:|---:|---|---|",
    ]
    for row in report["documents"]:
        lines.append(
            "| {doc_id} | {kb_id} | {file_name} | {artifact_status} | {block_count} | {page_coverage_rate} | {table_count} | {suitability} | {issues} |".format(
                doc_id=row["doc_id"],
                kb_id=row["kb_id"],
                file_name=row["file_name"],
                artifact_status=row["artifact_status"],
                block_count=row["blocks"]["block_count"],
                page_coverage_rate=row["blocks"]["page_coverage_rate"],
                table_count=row["tables"]["table_count"],
                suitability=", ".join(row["suitability"]) or "-",
                issues=", ".join(row["issues"]) or "-",
            )
        )
    lines.append("")
    return "\n".join(lines)


def _load_indexed_pdf_documents(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    docs = payload.get("documents") or {}
    rows: list[dict[str, Any]] = []
    for doc_id, doc in docs.items():
        if str(doc.get("status")) != "indexed":
            continue
        if str(doc.get("file_ext") or "").lower() != "pdf":
            continue
        rows.append(
            {
                "doc_id": doc_id,
                "kb_id": str(doc.get("kb_id") or ""),
                "file_name": str(doc.get("file_name") or ""),
                "file_ext": str(doc.get("file_ext") or ""),
                "status": str(doc.get("status") or ""),
                "artifact_dir": str(doc.get("artifact_dir") or ""),
                "original_path": str(doc.get("original_path") or ""),
                "parser_engine": str(doc.get("parser_engine") or ""),
            }
        )
    return sorted(rows, key=lambda row: (row["kb_id"], row["file_name"], row["doc_id"]))


def _load_current_import_state_docs(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        dict(doc)
        for doc in payload.get("documents") or []
        if str(doc.get("status")) == "indexed" and str(doc.get("file_ext") or "").lower() == "pdf"
    ]


def _inspect_pdf_document(
    doc: dict[str, Any],
    *,
    in_current_import_state: bool,
    page_coverage_threshold: float,
) -> dict[str, Any]:
    artifact_dir = Path(doc["artifact_dir"])
    blocks_path = artifact_dir / "blocks.json"
    tables_path = artifact_dir / "tables.json"
    blocks = _inspect_blocks(blocks_path)
    tables = _inspect_tables(tables_path)
    issues = _document_issues(
        artifact_dir=artifact_dir,
        blocks=blocks,
        tables=tables,
        page_coverage_threshold=page_coverage_threshold,
    )
    suitability = _document_suitability(
        blocks=blocks,
        tables=tables,
        issues=issues,
        page_coverage_threshold=page_coverage_threshold,
    )
    return {
        **doc,
        "in_current_import_state": in_current_import_state,
        "artifact_status": "present" if artifact_dir.exists() else "missing",
        "blocks": blocks,
        "tables": tables,
        "suitability": suitability,
        "issues": issues,
    }


def _inspect_blocks(path: Path) -> dict[str, Any]:
    rows = _load_rows(path, "blocks")
    block_count = len(rows)
    with_page = sum(1 for row in rows if row.get("page") is not None)
    pages = sorted({int(row["page"]) for row in rows if isinstance(row.get("page"), int)})
    return {
        "path": path.as_posix(),
        "exists": path.exists(),
        "block_count": block_count,
        "blocks_with_page": with_page,
        "page_coverage_rate": round(with_page / block_count, 4) if block_count else 0.0,
        "page_count": len(pages),
        "pages": pages,
    }


def _inspect_tables(path: Path) -> dict[str, Any]:
    rows = _load_rows(path, "tables")
    usable_tables = [
        row
        for row in rows
        if row.get("table_id") and (row.get("rows") or row.get("markdown"))
    ]
    return {
        "path": path.as_posix(),
        "exists": path.exists(),
        "table_count": len(rows),
        "usable_table_count": len(usable_tables),
        "table_ids": [str(row.get("table_id")) for row in usable_tables],
        "table_pages": sorted(
            {
                int(row["page"])
                for row in usable_tables
                if isinstance(row.get("page"), int)
            }
        ),
    }


def _load_rows(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload if isinstance(payload, list) else payload.get(key) or []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _document_issues(
    *,
    artifact_dir: Path,
    blocks: dict[str, Any],
    tables: dict[str, Any],
    page_coverage_threshold: float,
) -> list[str]:
    issues: list[str] = []
    if not artifact_dir.exists():
        issues.append("artifact_dir_missing")
    if not blocks["exists"]:
        issues.append("blocks_json_missing")
    if blocks["block_count"] <= 0:
        issues.append("blocks_empty")
    if blocks["block_count"] > 0 and blocks["page_coverage_rate"] < page_coverage_threshold:
        issues.append("page_coverage_below_threshold")
    if not tables["exists"]:
        issues.append("tables_json_missing")
    if tables["exists"] and tables["usable_table_count"] <= 0:
        issues.append("no_usable_tables")
    return issues


def _document_suitability(
    *,
    blocks: dict[str, Any],
    tables: dict[str, Any],
    issues: list[str],
    page_coverage_threshold: float,
) -> list[str]:
    suitability: list[str] = []
    page_ready = (
        blocks["exists"]
        and blocks["block_count"] > 0
        and blocks["page_coverage_rate"] >= page_coverage_threshold
    )
    if page_ready:
        suitability.append("page_eval_candidate")
    if page_ready and tables["usable_table_count"] > 0:
        suitability.append("table_eval_candidate")
    if page_ready and tables["exists"] and tables["usable_table_count"] <= 0:
        suitability.append("page_only_candidate")
    if not suitability and issues:
        suitability.append("not_suitable")
    return suitability


def _build_summary(rows: list[dict[str, Any]], current_state_docs: list[dict[str, Any]]) -> dict[str, Any]:
    page_candidates = [row for row in rows if "page_eval_candidate" in row["suitability"]]
    table_candidates = [row for row in rows if "table_eval_candidate" in row["suitability"]]
    return {
        "indexed_pdf_count": len(rows),
        "current_import_state_indexed_pdf_count": len(current_state_docs),
        "artifact_present_count": sum(1 for row in rows if row["artifact_status"] == "present"),
        "page_sample_candidates": len(page_candidates),
        "table_sample_candidates": len(table_candidates),
        "page_candidate_doc_ids": [row["doc_id"] for row in page_candidates],
        "table_candidate_doc_ids": [row["doc_id"] for row in table_candidates],
        "kb_ids": sorted({row["kb_id"] for row in rows}),
    }


def _coverage_gaps(summary: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    if summary["indexed_pdf_count"] <= 1:
        gaps.append("indexed_pdf_corpus_single_doc")
    if summary["page_sample_candidates"] <= 1:
        gaps.append("pdf_page_eval_candidate_single_doc")
    if summary["table_sample_candidates"] <= 1:
        gaps.append("pdf_table_eval_candidate_single_doc")
    if summary["page_sample_candidates"] <= 0:
        gaps.append("no_pdf_page_eval_candidates")
    if summary["table_sample_candidates"] <= 0:
        gaps.append("no_pdf_table_eval_candidates")
    return gaps


def _inventory_status(summary: dict[str, Any], coverage_gaps: list[str]) -> str:
    if summary["page_sample_candidates"] <= 0 and summary["table_sample_candidates"] <= 0:
        return "corpus_gap"
    if any(gap.endswith("_single_doc") for gap in coverage_gaps):
        return "corpus_limited"
    return "ready_for_expansion"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Checklist 3 indexed PDF artifact inventory report.")
    parser.add_argument("--metadata-store", default=DEFAULT_METADATA_STORE)
    parser.add_argument("--import-state", default=DEFAULT_IMPORT_STATE)
    parser.add_argument("--page-coverage-threshold", type=float, default=PAGE_COVERAGE_THRESHOLD)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()
    write_checklist3_pdf_artifact_inventory_report(
        metadata_store_path=args.metadata_store,
        import_state_path=args.import_state,
        page_coverage_threshold=args.page_coverage_threshold,
        output_json=args.output_json,
        output_md=args.output_md or None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
