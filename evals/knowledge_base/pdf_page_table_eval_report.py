"""PDF page/table/source_ref eval report helpers."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_pdf_page_table_eval_report(samples: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [_evaluate_sample(sample) for sample in samples]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(rows),
            "page_accuracy_passed": sum(1 for row in rows if row["page_accuracy"]),
            "table_presence_passed": sum(1 for row in rows if row["table_present"]),
            "source_ref_resolvable_passed": sum(1 for row in rows if row["source_ref_resolvable"]),
            "artifact_missing_count": sum(1 for row in rows if row["status"] == "artifact_missing"),
        },
        "samples": rows,
    }


def write_pdf_page_table_eval_report(
    samples: list[dict[str, Any]],
    *,
    output_json: str | Path,
    output_md: str | Path | None = None,
) -> dict[str, Any]:
    report = build_pdf_page_table_eval_report(samples)
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
        "# PDF Page/Table Eval Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Summary: {report['summary']}",
        "",
        "| sample_id | status | page_accuracy | table_present | source_ref_resolvable | page_sources | table_ids |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in report["samples"]:
        lines.append(
            "| {sample_id} | {status} | {page_accuracy} | {table_present} | {source_ref_resolvable} | {page_sources} | {table_ids} |".format(
                sample_id=row["sample_id"],
                status=row["status"],
                page_accuracy=row["page_accuracy"],
                table_present=row["table_present"],
                source_ref_resolvable=row["source_ref_resolvable"],
                page_sources=row["page_sources"],
                table_ids=row["table_ids"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def _evaluate_sample(sample: dict[str, Any]) -> dict[str, Any]:
    artifact_dir = Path(sample["artifact_dir"])
    chunks_path = artifact_dir / "chunks.json"
    tables_path = artifact_dir / "tables.json"
    if not chunks_path.exists() or not tables_path.exists():
        return _missing_row(sample, artifact_dir)

    chunks = _extract_items(_load_json(chunks_path), "chunks")
    tables = _extract_items(_load_json(tables_path), "tables")
    expected_page = sample.get("expected_page")
    expected_table_id = sample.get("expected_table_id")
    page_sources = sorted(
        {
            int(page)
            for chunk in chunks
            for page in _page_values(chunk)
            if page is not None
        }
    )
    source_ref_rows = [_source_ref_payload(chunk) for chunk in chunks]
    metadata_source_ref_rows = _metadata_source_ref_payloads(str(sample.get("doc_id") or ""))
    table_ids = {str(table.get("table_id") or table.get("id") or "") for table in tables}
    return {
        "sample_id": sample.get("sample_id") or artifact_dir.name,
        "artifact_dir": artifact_dir.as_posix(),
        "status": "evaluated",
        "page_sources": page_sources,
        "table_ids": sorted(table_id for table_id in table_ids if table_id),
        "page_accuracy": expected_page in page_sources if expected_page is not None else bool(page_sources),
        "table_present": str(expected_table_id) in table_ids if expected_table_id else bool(table_ids),
        "source_ref_resolvable": _source_refs_resolvable(source_ref_rows, metadata_source_ref_rows),
    }


def _missing_row(sample: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    return {
        "sample_id": sample.get("sample_id") or artifact_dir.name,
        "artifact_dir": artifact_dir.as_posix(),
        "status": "artifact_missing",
        "page_sources": [],
        "table_ids": [],
        "page_accuracy": False,
        "table_present": False,
        "source_ref_resolvable": False,
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_items(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        items = payload.get(key) or []
    else:
        items = payload or []
    return [item for item in items if isinstance(item, dict)]


def _source_ref_payload(chunk: dict[str, Any]) -> dict[str, Any]:
    payload = chunk.get("source_ref") or {}
    return payload if isinstance(payload, dict) else {}


def _page_values(chunk: dict[str, Any]) -> list[Any]:
    values = [chunk.get("page_start"), _source_ref_payload(chunk).get("page_start")]
    pages = chunk.get("pages") or []
    if isinstance(pages, list):
        values.extend(pages)
    return values


def _source_ref_complete(payload: dict[str, Any]) -> bool:
    return all(
        bool(payload.get(field))
        for field in ["kb_id", "doc_id", "chunk_id", "source_file", "parser_engine"]
    )


def _source_refs_resolvable(
    artifact_rows: list[dict[str, Any]],
    metadata_rows: list[dict[str, Any]],
) -> bool:
    rows = metadata_rows or artifact_rows
    return all(_source_ref_complete(row) for row in rows) if rows else False


def _metadata_source_ref_payloads(doc_id: str) -> list[dict[str, Any]]:
    if not doc_id:
        return []
    try:
        from app.services.knowledge_metadata_store import knowledge_metadata_store

        chunks = knowledge_metadata_store.list_chunks_by_doc_id(doc_id)
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for chunk in chunks:
        source_ref = getattr(chunk, "source_ref", None)
        if source_ref is None:
            rows.append({})
            continue
        rows.append(source_ref.model_dump(mode="json"))
    return rows


def _load_samples(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    return list(payload.get("samples") or [])


def main() -> int:
    parser = argparse.ArgumentParser(description="Build PDF page/table/source_ref eval report.")
    parser.add_argument("--samples", required=True, help="JSON file with sample list or {samples: [...]} payload.")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()
    write_pdf_page_table_eval_report(
        _load_samples(args.samples),
        output_json=args.output_json,
        output_md=args.output_md or None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
