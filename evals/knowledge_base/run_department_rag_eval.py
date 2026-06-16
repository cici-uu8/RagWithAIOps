"""Department RAG eval runner with source_ref integrity checks."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.enterprise.context import RequestContext
from app.enterprise.rag.query_intent import infer_requested_kb_ids
from app.models import DocumentStatus, RetrievalMode, RetrievalQuery, RetrievalResponse
from app.services.chunk_evidence_mapper import ChunkEvidenceMapper
from app.services.knowledge_metadata_store import KnowledgeMetadataStore, knowledge_metadata_store
from app.services.retrieval_service import retrieval_service

REQUIRED_EVAL_FIELDS = {
    "sample_id",
    "query",
    "allowed_kb_ids",
    "expected_doc_ids",
    "expected_answer_keywords",
    "scope",
}


def verify_source_ref_integrity(
    response: RetrievalResponse | dict[str, Any] | Any,
    *,
    metadata_store: KnowledgeMetadataStore = knowledge_metadata_store,
    allowed_kb_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Check whether retrieval results can be resolved back to stored chunks."""

    allowed = set(allowed_kb_ids or [])
    rows: list[dict[str, Any]] = []

    for index, result in enumerate(_results(response)):
        evidence = ChunkEvidenceMapper.from_retrieval_result(result)
        missing_fields = ChunkEvidenceMapper.validate_required_fields(evidence)
        cross_scope_error = bool(allowed and evidence.kb_id not in allowed)
        matched_chunk = None
        if not missing_fields:
            for chunk in metadata_store.list_chunks_by_doc_id(evidence.doc_id):
                if chunk.chunk_id == evidence.chunk_id:
                    matched_chunk = chunk
                    break

        status = "resolved" if matched_chunk is not None and not cross_scope_error else "citation_unresolvable"
        rows.append(
            {
                "result_index": index,
                "status": status,
                "kb_id": evidence.kb_id,
                "doc_id": evidence.doc_id,
                "chunk_id": evidence.chunk_id,
                "source_uri": evidence.source_uri,
                "missing_fields": missing_fields,
                "cross_scope_error": cross_scope_error,
                "stored_chunk_found": matched_chunk is not None,
            }
        )

    return {
        "result_count": len(rows),
        "all_source_ref_complete": all(not row["missing_fields"] for row in rows),
        "all_resolvable": all(row["status"] == "resolved" for row in rows),
        "citation_unresolvable_count": sum(1 for row in rows if row["status"] == "citation_unresolvable"),
        "cross_scope_error_count": sum(1 for row in rows if row["cross_scope_error"]),
        "results": rows,
    }


def _results(response: RetrievalResponse | dict[str, Any] | Any) -> list[Any]:
    if response is None:
        return []
    if isinstance(response, dict):
        return list(response.get("results") or [])
    return list(getattr(response, "results", []) or [])


def load_evalset(path: str | Path) -> list[dict[str, Any]]:
    evalset_path = Path(path)
    if not evalset_path.exists():
        raise FileNotFoundError(f"evalset not found: {evalset_path}")
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(evalset_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        missing = sorted(REQUIRED_EVAL_FIELDS - set(payload))
        if missing:
            raise ValueError(f"{evalset_path}:{line_number} missing fields: {missing}")
        if not isinstance(payload["allowed_kb_ids"], list):
            raise ValueError(f"{evalset_path}:{line_number} allowed_kb_ids must be a list")
        if not isinstance(payload["expected_doc_ids"], list):
            raise ValueError(f"{evalset_path}:{line_number} expected_doc_ids must be a list")
        if not isinstance(payload["expected_answer_keywords"], list):
            raise ValueError(f"{evalset_path}:{line_number} expected_answer_keywords must be a list")
        cases.append(payload)
    if not cases:
        raise ValueError(f"evalset empty: {evalset_path}")
    return cases


def evaluate_case(
    case: dict[str, Any],
    *,
    retrieval_service=retrieval_service,
    metadata_store: KnowledgeMetadataStore | None = knowledge_metadata_store,
    context: RequestContext | None = None,
) -> dict[str, Any]:
    selected_kb_ids = list(case.get("allowed_kb_ids") or [])
    if _should_short_circuit_permission_filtered(case, selected_kb_ids):
        return _permission_filtered_row(case, selected_kb_ids, context)
    query = RetrievalQuery(
        query=str(case["query"]),
        top_k=int(case.get("top_k") or 3),
        retrieval_mode=_retrieval_mode(case.get("retrieval_mode")),
        knowledge_base_ids=selected_kb_ids,
    )
    try:
        response = retrieval_service.retrieve(query)
    except Exception as exc:
        return _not_ready_row(case, selected_kb_ids, exc)

    results = list(response.results)
    source_refs = [
        result.source_ref.model_dump(mode="json")
        for result in results
        if getattr(result, "source_ref", None) is not None
    ]
    integrity = (
        verify_source_ref_integrity(
            response,
            metadata_store=metadata_store,
            allowed_kb_ids=selected_kb_ids,
        )
        if metadata_store is not None
        else {
            "all_source_ref_complete": bool(source_refs) or not results,
            "all_resolvable": True,
            "citation_unresolvable_count": 0,
            "cross_scope_error_count": 0,
            "results": [],
        }
    )
    answer_score = _answer_score(response.context_text, case.get("expected_answer_keywords") or [])
    if not results and case.get("expected_failure") == "permission_filtered":
        answer_score = 1.0
    failure_category = _failure_category(case, response, integrity, metadata_store)
    status = "passed" if failure_category == "passed" else "failed"
    no_result_reason = (
        ""
        if results
        else "permission_filtered"
        if case.get("expected_failure") == "permission_filtered"
        else _no_result_reason(selected_kb_ids, metadata_store)
    )
    return {
        "sample_id": case["sample_id"],
        "query": case["query"],
        "status": status,
        "no_result_reason": no_result_reason,
        "selected_kb_ids": selected_kb_ids,
        "source_ref": source_refs,
        "answer_score": answer_score,
        "failure_category": failure_category,
        "result_count": len(results),
        "expected_doc_ids": list(case.get("expected_doc_ids") or []),
        "actual_doc_ids": [result.doc_id for result in results],
        "source_ref_integrity": integrity,
        "trace_id": context.trace_id if context else "",
    }


def run_department_rag_eval(
    evalset_path: str | Path,
    *,
    output_dir: str | Path = "evals/knowledge_base/reports",
    write_report: bool = True,
    metadata_store: KnowledgeMetadataStore = knowledge_metadata_store,
) -> dict[str, Any]:
    cases = load_evalset(evalset_path)
    context = RequestContext(
        request_id="department-rag-eval",
        trace_id="department-rag-eval",
        user_id="department-rag-eval",
        username="department-rag-eval",
        department_id="eval",
        department_name="Eval",
        roles=["admin"],
    )
    results = [
        evaluate_case(
            case,
            retrieval_service=retrieval_service,
            metadata_store=metadata_store,
            context=context,
        )
        for case in cases
    ]
    status_counts = dict(Counter(row["status"] for row in results))
    failure_categories = dict(Counter(row["failure_category"] for row in results))
    wrong_scope_count = failure_categories.get("wrong_scope", 0)
    citation_unresolvable_count = failure_categories.get("citation_unresolvable", 0)
    permission_filtered_passed = sum(
        1
        for row in results
        if row["status"] == "passed" and row["no_result_reason"] == "permission_filtered"
    )
    report = {
        "evalset_path": str(evalset_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(results),
            "status_counts": status_counts,
            "failure_categories": failure_categories,
            "scored": sum(1 for row in results if row["status"] != "not_ready"),
            "not_ready": status_counts.get("not_ready", 0),
            "asset_blocked": failure_categories.get("data_not_indexed", 0),
            "wrong_scope_count": wrong_scope_count,
            "wrong_scope_rate": round(wrong_scope_count / len(results), 4) if results else 0.0,
            "citation_unresolvable_count": citation_unresolvable_count,
            "citation_unresolvable_rate": round(citation_unresolvable_count / len(results), 4)
            if results
            else 0.0,
            "permission_filtered_passed": permission_filtered_passed,
            "all_source_ref_resolvable": all(
                row["source_ref_integrity"].get("all_resolvable", False)
                for row in results
                if row["source_ref"]
            ),
        },
        "results": results,
    }
    if write_report:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        stem = f"department_rag_eval_{Path(evalset_path).stem}_{stamp}"
        json_path = output / f"{stem}.json"
        md_path = output / f"{stem}.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_path.write_text(_render_markdown_report(report), encoding="utf-8")
        report["report_json_path"] = json_path.name
        report["report_markdown_path"] = md_path.name
    return report


def _not_ready_row(case: dict[str, Any], selected_kb_ids: list[str], exc: Exception) -> dict[str, Any]:
    return {
        "sample_id": case["sample_id"],
        "query": case["query"],
        "status": "not_ready",
        "no_result_reason": "eval_framework_blocked",
        "selected_kb_ids": selected_kb_ids,
        "source_ref": [],
        "answer_score": 0.0,
        "failure_category": "eval_framework_blocked",
        "result_count": 0,
        "expected_doc_ids": list(case.get("expected_doc_ids") or []),
        "actual_doc_ids": [],
        "source_ref_integrity": {
            "result_count": 0,
            "all_source_ref_complete": False,
            "all_resolvable": False,
            "citation_unresolvable_count": 0,
            "cross_scope_error_count": 0,
            "results": [],
        },
        "blocked_module": "retrieval_service.retrieve",
        "blocked_error_type": type(exc).__name__,
        "blocked_error": str(exc),
    }


def _permission_filtered_row(
    case: dict[str, Any],
    selected_kb_ids: list[str],
    context: RequestContext | None,
) -> dict[str, Any]:
    return {
        "sample_id": case["sample_id"],
        "query": case["query"],
        "status": "passed",
        "no_result_reason": "permission_filtered",
        "selected_kb_ids": selected_kb_ids,
        "source_ref": [],
        "answer_score": 1.0,
        "failure_category": "passed",
        "result_count": 0,
        "expected_doc_ids": list(case.get("expected_doc_ids") or []),
        "actual_doc_ids": [],
        "source_ref_integrity": {
            "result_count": 0,
            "all_source_ref_complete": True,
            "all_resolvable": True,
            "citation_unresolvable_count": 0,
            "cross_scope_error_count": 0,
            "results": [],
        },
        "trace_id": context.trace_id if context else "",
    }


def _retrieval_mode(value: Any) -> RetrievalMode:
    try:
        return RetrievalMode(str(value or RetrievalMode.SPARSE_ONLY.value))
    except ValueError:
        return RetrievalMode.SPARSE_ONLY


def _answer_score(context_text: str, keywords: list[str]) -> float:
    if not keywords:
        return 1.0 if context_text.strip() else 0.0
    if not context_text.strip():
        return 0.0
    hits = sum(1 for keyword in keywords if str(keyword) and str(keyword) in context_text)
    return round(hits / len(keywords), 4)


def _failure_category(
    case: dict[str, Any],
    response: RetrievalResponse,
    integrity: dict[str, Any],
    metadata_store: KnowledgeMetadataStore | None,
) -> str:
    if case.get("expected_failure") == "permission_filtered":
        return "passed" if not response.results else "wrong_scope"
    if not response.results:
        return _no_result_failure_category(case.get("allowed_kb_ids") or [], metadata_store)
    if _contains_forbidden_kb(response, case.get("retrieved_must_not_contain_kb") or []):
        return "wrong_scope"
    if integrity.get("cross_scope_error_count", 0) > 0:
        return "wrong_scope"
    if not integrity.get("all_source_ref_complete", False) or integrity.get("citation_unresolvable_count", 0) > 0:
        return "citation_unresolvable"
    expected_doc_ids = set(case.get("expected_doc_ids") or [])
    actual_doc_ids = {result.doc_id for result in response.results}
    if expected_doc_ids and not (expected_doc_ids & actual_doc_ids):
        return "answer_wrong"
    if _answer_score(response.context_text, case.get("expected_answer_keywords") or []) < 1.0:
        return "answer_wrong"
    return "passed"


def _should_short_circuit_permission_filtered(
    case: dict[str, Any],
    selected_kb_ids: list[str],
) -> bool:
    if case.get("expected_failure") != "permission_filtered":
        return False
    selected = set(selected_kb_ids)
    explicit_target = str(case.get("target_kb_id") or "")
    requested = [explicit_target] if explicit_target else infer_requested_kb_ids(str(case.get("query") or ""))
    return bool(requested and selected and not (set(requested) & selected))


def _contains_forbidden_kb(response: RetrievalResponse, forbidden_kb_ids: list[str]) -> bool:
    forbidden = {str(kb_id) for kb_id in forbidden_kb_ids if str(kb_id)}
    if not forbidden:
        return False
    return any(result.kb_id in forbidden for result in response.results)


def _no_result_failure_category(
    selected_kb_ids: list[str],
    metadata_store: KnowledgeMetadataStore | None,
) -> str:
    if metadata_store is None:
        return "no_retrieval_hit"
    documents = [
        document
        for document in metadata_store.list_documents()
        if not selected_kb_ids or document.kb_id in selected_kb_ids
    ]
    if not documents or not any(document.status == DocumentStatus.INDEXED for document in documents):
        return "data_not_indexed"
    return "no_retrieval_hit"


def _no_result_reason(
    selected_kb_ids: list[str],
    metadata_store: KnowledgeMetadataStore | None,
) -> str:
    failure_category = _no_result_failure_category(selected_kb_ids, metadata_store)
    if failure_category == "data_not_indexed":
        return "data_not_indexed"
    return "retrieval_no_hit"


def _render_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Department RAG Eval Report",
        "",
        f"- Evalset: `{report['evalset_path']}`",
        f"- Generated at: `{report['generated_at']}`",
        f"- Total: {report['summary']['total']}",
        f"- Status counts: {report['summary']['status_counts']}",
        f"- Failure categories: {report['summary']['failure_categories']}",
        f"- Wrong scope rate: {report['summary'].get('wrong_scope_rate', 0.0)}",
        f"- Citation unresolvable rate: {report['summary'].get('citation_unresolvable_rate', 0.0)}",
        f"- Permission filtered passed: {report['summary'].get('permission_filtered_passed', 0)}",
        "",
        "## Results",
        "",
        "| sample_id | status | no_result_reason | answer_score | failure_category | selected_kb_ids |",
        "|---|---|---|---:|---|---|",
    ]
    for row in report["results"]:
        lines.append(
            "| {sample_id} | {status} | {no_result_reason} | {answer_score} | {failure_category} | {selected} |".format(
                sample_id=row["sample_id"],
                status=row["status"],
                no_result_reason=row["no_result_reason"] or "-",
                answer_score=row["answer_score"],
                failure_category=row["failure_category"],
                selected=", ".join(row["selected_kb_ids"]) or "-",
            )
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run department RAG eval.")
    parser.add_argument("--evalset", required=True, help="JSONL evalset path.")
    parser.add_argument("--output-dir", default="evals/knowledge_base/reports")
    parser.add_argument("--report", default="", help="Optional exact output report JSON path.")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    report = run_department_rag_eval(
        args.evalset,
        output_dir=args.output_dir,
        write_report=not args.no_write,
    )
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif args.no_write:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["summary"]["not_ready"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
