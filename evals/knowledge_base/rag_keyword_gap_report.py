"""Inspect expected-doc keyword gaps from an existing RAG eval report."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models import ChunkRecord
from app.services.knowledge_metadata_store import KnowledgeMetadataStore, knowledge_metadata_store


def build_keyword_gap_report(
    rag_report_path: str | Path,
    *,
    evalset_path: str | Path | None = None,
    metadata_store: KnowledgeMetadataStore = knowledge_metadata_store,
) -> dict[str, Any]:
    """Build a read-only report for answer_wrong rows whose expected doc was retrieved."""

    rag_report = json.loads(Path(rag_report_path).read_text(encoding="utf-8"))
    evalset_cases = _load_evalset(evalset_path or rag_report.get("evalset_path"))

    rows = []
    for result in rag_report.get("results") or []:
        if result.get("failure_category") != "answer_wrong":
            continue
        expected_doc_ids = list(result.get("expected_doc_ids") or [])
        actual_doc_ids = list(result.get("actual_doc_ids") or [])
        expected_doc_overlap = sorted(set(expected_doc_ids) & set(actual_doc_ids))
        if not expected_doc_overlap:
            continue

        case = evalset_cases.get(str(result.get("sample_id", "")), {})
        keywords = [str(keyword) for keyword in case.get("expected_answer_keywords") or [] if str(keyword)]
        rows.append(
            _analyze_result_row(
                result,
                expected_doc_overlap=expected_doc_overlap,
                expected_keywords=keywords,
                metadata_store=metadata_store,
            )
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rag_report_path": str(rag_report_path),
        "evalset_path": str(evalset_path or rag_report.get("evalset_path") or ""),
        "summary": {
            "total_keyword_gap_rows": len(rows),
            "verdict_counts": dict(Counter(row["verdict"] for row in rows)),
        },
        "rows": rows,
    }


def write_keyword_gap_report(
    rag_report_path: str | Path,
    *,
    output_json: str | Path,
    output_md: str | Path | None = None,
    evalset_path: str | Path | None = None,
    metadata_store: KnowledgeMetadataStore = knowledge_metadata_store,
) -> dict[str, Any]:
    report = build_keyword_gap_report(
        rag_report_path,
        evalset_path=evalset_path,
        metadata_store=metadata_store,
    )
    output_json_path = Path(output_json)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if output_md is not None:
        output_md_path = Path(output_md)
        output_md_path.parent.mkdir(parents=True, exist_ok=True)
        output_md_path.write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# RAG Keyword Gap Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- RAG report: `{report['rag_report_path']}`",
        f"- Total keyword-gap rows: {report['summary']['total_keyword_gap_rows']}",
        f"- Verdict counts: {report['summary']['verdict_counts']}",
        "",
        "| sample_id | verdict | answer_score | missing_in_all_retrieved_context | missing_in_retrieved_expected_doc_chunks | missing_in_expected_doc | expected_doc_overlap |",
        "|---|---|---:|---|---|---|---|",
    ]
    for row in report["rows"]:
        lines.append(
            "| {sample_id} | {verdict} | {answer_score} | {missing_all_context} | {missing_expected_context} | {missing_doc} | {overlap} |".format(
                sample_id=row["sample_id"],
                verdict=row["verdict"],
                answer_score=row["answer_score"],
                missing_all_context=", ".join(row["missing_in_all_retrieved_context"]) or "-",
                missing_expected_context=", ".join(row["missing_in_retrieved_expected_doc_chunks"]) or "-",
                missing_doc=", ".join(row["missing_in_expected_doc"]) or "-",
                overlap=", ".join(row["expected_doc_overlap"]) or "-",
            )
        )
    lines.append("")
    return "\n".join(lines)


def _analyze_result_row(
    result: dict[str, Any],
    *,
    expected_doc_overlap: list[str],
    expected_keywords: list[str],
    metadata_store: KnowledgeMetadataStore,
) -> dict[str, Any]:
    retrieved_refs = list(result.get("source_ref") or [])
    retrieved_chunk_ids = [str(ref.get("chunk_id", "")) for ref in retrieved_refs if ref.get("chunk_id")]
    retrieved_doc_ids = list(dict.fromkeys(str(ref.get("doc_id", "")) for ref in retrieved_refs if ref.get("doc_id")))
    expected_chunks = _load_expected_chunks(expected_doc_overlap, metadata_store)
    all_retrieved_chunks = _load_retrieved_chunks(retrieved_doc_ids, retrieved_chunk_ids, metadata_store)
    retrieved_expected_doc_chunks = [
        chunk for chunk in expected_chunks if chunk.chunk_id in set(retrieved_chunk_ids)
    ]

    all_retrieved_context = "\n\n".join(chunk.content for chunk in all_retrieved_chunks)
    retrieved_expected_doc_context = "\n\n".join(chunk.content for chunk in retrieved_expected_doc_chunks)
    expected_doc_context = "\n\n".join(chunk.content for chunk in expected_chunks)

    missing_in_all_retrieved_context = [
        keyword for keyword in expected_keywords if keyword not in all_retrieved_context
    ]
    missing_in_retrieved_expected_doc_chunks = [
        keyword for keyword in expected_keywords if keyword not in retrieved_expected_doc_context
    ]
    missing_in_expected_doc = [
        keyword for keyword in expected_keywords if keyword not in expected_doc_context
    ]
    available_outside_top_context = [
        keyword
        for keyword in missing_in_retrieved_expected_doc_chunks
        if keyword not in missing_in_expected_doc
    ]
    keywords_only_in_non_expected_retrieved_docs = [
        keyword
        for keyword in expected_keywords
        if keyword in all_retrieved_context and keyword not in retrieved_expected_doc_context
    ]

    return {
        "sample_id": result.get("sample_id", ""),
        "query": result.get("query", ""),
        "verdict": _verdict(
            expected_keywords=expected_keywords,
            missing_in_retrieved_expected_doc_chunks=missing_in_retrieved_expected_doc_chunks,
            missing_in_expected_doc=missing_in_expected_doc,
            available_outside_top_context=available_outside_top_context,
        ),
        "answer_score": result.get("answer_score", 0),
        "expected_answer_keywords": expected_keywords,
        "expected_doc_overlap": expected_doc_overlap,
        "retrieved_chunk_ids": retrieved_chunk_ids,
        "retrieved_expected_doc_chunk_ids": [chunk.chunk_id for chunk in retrieved_expected_doc_chunks],
        "missing_in_all_retrieved_context": missing_in_all_retrieved_context,
        "missing_in_retrieved_expected_doc_chunks": missing_in_retrieved_expected_doc_chunks,
        "missing_in_expected_doc": missing_in_expected_doc,
        "available_outside_top_context": available_outside_top_context,
        "keywords_only_in_non_expected_retrieved_docs": keywords_only_in_non_expected_retrieved_docs,
        "retrieved_chunks": [_chunk_summary(chunk, expected_keywords) for chunk in all_retrieved_chunks],
        "retrieved_expected_doc_chunks": [
            _chunk_summary(chunk, expected_keywords) for chunk in retrieved_expected_doc_chunks
        ],
        "candidate_chunks_by_keyword": {
            keyword: [
                _chunk_summary(chunk, expected_keywords)
                for chunk in expected_chunks
                if keyword in chunk.content and chunk.chunk_id not in set(retrieved_chunk_ids)
            ][:5]
            for keyword in available_outside_top_context
        },
    }


def _load_expected_chunks(
    doc_ids: list[str],
    metadata_store: KnowledgeMetadataStore,
) -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []
    for doc_id in doc_ids:
        for chunk in metadata_store.list_chunks_by_doc_id(doc_id):
            if chunk.metadata.get("chunk_role") == "parent":
                continue
            chunks.append(chunk)
    chunks.sort(key=lambda chunk: (chunk.doc_id, chunk.chunk_index, chunk.chunk_id))
    return chunks


def _load_retrieved_chunks(
    doc_ids: list[str],
    chunk_ids: list[str],
    metadata_store: KnowledgeMetadataStore,
) -> list[ChunkRecord]:
    wanted_chunk_ids = set(chunk_ids)
    chunks_by_id: dict[str, ChunkRecord] = {}
    for doc_id in doc_ids:
        for chunk in metadata_store.list_chunks_by_doc_id(doc_id):
            if chunk.chunk_id in wanted_chunk_ids:
                chunks_by_id[chunk.chunk_id] = chunk
    return [chunks_by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in chunks_by_id]


def _chunk_summary(chunk: ChunkRecord, keywords: list[str]) -> dict[str, Any]:
    return {
        "chunk_id": chunk.chunk_id,
        "heading_path": list(chunk.heading_path),
        "keyword_hits": [keyword for keyword in keywords if keyword in chunk.content],
        "content_preview": chunk.content[:240],
    }


def _verdict(
    *,
    expected_keywords: list[str],
    missing_in_retrieved_expected_doc_chunks: list[str],
    missing_in_expected_doc: list[str],
    available_outside_top_context: list[str],
) -> str:
    if not expected_keywords:
        return "no_expected_keywords"
    if not missing_in_retrieved_expected_doc_chunks:
        return "retrieved_expected_doc_chunks_contain_all_keywords"
    if missing_in_expected_doc and available_outside_top_context:
        return "mixed_expected_absent_and_context_gap"
    if missing_in_expected_doc:
        return "expected_keyword_absent_from_expected_doc"
    if available_outside_top_context:
        return "expected_keyword_available_outside_top_context"
    return "keyword_gap_unclassified"


def _load_evalset(path: str | Path | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    evalset_path = Path(path)
    if not evalset_path.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for line in evalset_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        rows[str(payload.get("sample_id", ""))] = payload
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect expected-doc keyword gaps from a RAG eval report.")
    parser.add_argument("--rag-report", required=True)
    parser.add_argument("--evalset", default="")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    write_keyword_gap_report(
        args.rag_report,
        evalset_path=args.evalset or None,
        output_json=args.output_json,
        output_md=args.output_md or None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
