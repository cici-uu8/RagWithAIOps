"""Classify remaining RAG answer_wrong rows from an existing eval report."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_answer_failure_triage_report(
    rag_report_path: str | Path,
    *,
    evalset_path: str | Path | None = None,
    original_manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a read-only triage report for answer_wrong rows."""

    rag_report = json.loads(Path(rag_report_path).read_text(encoding="utf-8"))
    evalset_cases = _load_evalset(evalset_path or rag_report.get("evalset_path"))
    manifest_assets = _load_manifest_assets(original_manifest_path)

    rows = []
    for result in rag_report.get("results") or []:
        if result.get("failure_category") != "answer_wrong":
            continue
        case = evalset_cases.get(result.get("sample_id"), {})
        classification, next_action, evidence = _classify_row(result, case, manifest_assets)
        rows.append(
            {
                "sample_id": result.get("sample_id", ""),
                "query": result.get("query", ""),
                "classification": classification,
                "next_action": next_action,
                "answer_score": result.get("answer_score", 0),
                "expected_doc_ids": list(result.get("expected_doc_ids") or []),
                "actual_doc_ids": list(dict.fromkeys(result.get("actual_doc_ids") or [])),
                "expected_answer_keywords": list(case.get("expected_answer_keywords") or []),
                "retrieved_source_files": _unique_source_files(result),
                "evidence": evidence,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rag_report_path": str(rag_report_path),
        "evalset_path": str(evalset_path or rag_report.get("evalset_path") or ""),
        "original_manifest_path": str(original_manifest_path or ""),
        "summary": {
            "total_answer_wrong": len(rows),
            "classification_counts": dict(Counter(row["classification"] for row in rows)),
        },
        "rows": rows,
    }


def write_answer_failure_triage_report(
    rag_report_path: str | Path,
    *,
    output_json: str | Path,
    output_md: str | Path | None = None,
    evalset_path: str | Path | None = None,
    original_manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    report = build_answer_failure_triage_report(
        rag_report_path,
        evalset_path=evalset_path,
        original_manifest_path=original_manifest_path,
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
        "# RAG Answer Failure Triage Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- RAG report: `{report['rag_report_path']}`",
        f"- Total answer_wrong: {report['summary']['total_answer_wrong']}",
        f"- Classification counts: {report['summary']['classification_counts']}",
        "",
        "| sample_id | classification | next_action | answer_score | expected_docs | actual_docs | retrieved_sources |",
        "|---|---|---|---:|---|---|---|",
    ]
    for row in report["rows"]:
        lines.append(
            "| {sample_id} | {classification} | {next_action} | {answer_score} | {expected_docs} | {actual_docs} | {sources} |".format(
                sample_id=row["sample_id"],
                classification=row["classification"],
                next_action=row["next_action"],
                answer_score=row["answer_score"],
                expected_docs=", ".join(row["expected_doc_ids"]) or "-",
                actual_docs=", ".join(row["actual_doc_ids"]) or "-",
                sources=", ".join(row["retrieved_source_files"]) or "-",
            )
        )
    lines.append("")
    return "\n".join(lines)


def _classify_row(
    result: dict[str, Any],
    case: dict[str, Any],
    manifest_assets: list[dict[str, Any]],
) -> tuple[str, str, dict[str, Any]]:
    expected_doc_ids = set(result.get("expected_doc_ids") or [])
    actual_doc_ids = set(result.get("actual_doc_ids") or [])
    expected_keywords = [str(keyword) for keyword in case.get("expected_answer_keywords") or []]
    source_files = _unique_source_files(result)
    matched_pending_assets = _find_pending_assets(expected_keywords, manifest_assets)

    if not result.get("source_ref"):
        return (
            "retrieval_empty_or_missing_context",
            "inspect retrieval no-hit before rewrite or ranking work",
            {"reason": "answer_wrong row has no source_ref rows"},
        )

    if expected_doc_ids and expected_doc_ids & actual_doc_ids:
        return (
            "expected_doc_retrieved_keyword_gap",
            "inspect chunk content and expected keywords before changing retrieval strategy",
            {
                "reason": "expected document is present, but answer_score is below 1.0",
                "expected_doc_overlap": sorted(expected_doc_ids & actual_doc_ids),
                "retrieved_source_files": source_files,
            },
        )

    if not expected_doc_ids and matched_pending_assets:
        return (
            "eval_asset_pending_review_import",
            "review and import the matching original assets before judging retrieval quality",
            {
                "reason": "eval case has no expected_doc_ids, but matching source assets are still pending review/import",
                "matched_assets": matched_pending_assets,
            },
        )

    if expected_doc_ids:
        return (
            "expected_doc_not_retrieved",
            "compare dense/sparse/hybrid ranking for this case before query rewrite",
            {
                "reason": "expected document is absent from retrieved docs",
                "missing_expected_doc_ids": sorted(expected_doc_ids - actual_doc_ids),
                "retrieved_source_files": source_files,
            },
        )

    return (
        "eval_expectation_incomplete",
        "bind expected_doc_ids or expected assets before using this row as retrieval evidence",
        {
            "reason": "eval case has answer keywords but no expected_doc_ids or matching pending assets",
            "expected_answer_keywords": expected_keywords,
            "retrieved_source_files": source_files,
        },
    )


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


def _load_manifest_assets(path: str | Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    manifest_path = Path(path)
    if not manifest_path.exists():
        return []
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return list(payload.get("assets") or [])


def _unique_source_files(result: dict[str, Any]) -> list[str]:
    source_files = [
        str(ref.get("source_file", ""))
        for ref in result.get("source_ref") or []
        if ref.get("source_file")
    ]
    return list(dict.fromkeys(source_files))


def _find_pending_assets(
    expected_keywords: list[str],
    manifest_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not expected_keywords:
        return []
    matches = []
    for asset in manifest_assets:
        haystack = f"{asset.get('file_name', '')} {asset.get('relative_path', '')}"
        if any(keyword and keyword in haystack for keyword in expected_keywords):
            matches.append(
                {
                    "asset_id": asset.get("asset_id", ""),
                    "file_name": asset.get("file_name", ""),
                    "kb_id": asset.get("kb_id", ""),
                    "review_status": asset.get("review_status", ""),
                    "import_enabled": bool(asset.get("import_enabled", False)),
                }
            )
    return [
        match
        for match in matches
        if match["review_status"] != "approved" or not match["import_enabled"]
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify answer_wrong rows from an existing RAG eval report.")
    parser.add_argument("--rag-report", required=True)
    parser.add_argument("--evalset", default="")
    parser.add_argument("--original-manifest", default="")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    write_answer_failure_triage_report(
        args.rag_report,
        evalset_path=args.evalset or None,
        original_manifest_path=args.original_manifest or None,
        output_json=args.output_json,
        output_md=args.output_md or None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
