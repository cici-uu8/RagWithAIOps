"""Shadow-only context coverage probe for Answer eval samples."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.models import RetrievalMode, RetrievalQuery
from app.services.knowledge_metadata_store import KnowledgeMetadataStore, knowledge_metadata_store
from app.services.retrieval_service import retrieval_service
from evals.knowledge_base.answer_eval_helpers import contains_required_text
from evals.knowledge_base.run_department_rag_answer_eval import load_answer_evalset
from evals.knowledge_base.run_department_rag_eval import verify_source_ref_integrity

DEFAULT_EVALSET = "evals/knowledge_base/evalsets/department_rag_answer_30q_after_c6_triage_fix.jsonl"
DEFAULT_OUTPUT_JSON = "evals/knowledge_base/reports/answer_30q_context_shadow_c6a_md_004_005_20260612.json"
DEFAULT_SAMPLE_IDS = ("C6A-MD-004", "C6A-MD-005")
DEFAULT_TOP_KS = (3, 5, 8)
DEFAULT_TOP_K = 3
PROMOTION_TOP_K = 5


def build_answer_context_shadow_report(
    evalset_path: str | Path = DEFAULT_EVALSET,
    *,
    sample_ids: Iterable[str] = DEFAULT_SAMPLE_IDS,
    top_ks: Iterable[int] = DEFAULT_TOP_KS,
    retrieval_service=retrieval_service,
    metadata_store: KnowledgeMetadataStore | None = knowledge_metadata_store,
) -> dict[str, Any]:
    """Run retrieval-only context coverage probes for selected Answer samples."""

    selected_ids = [str(sample_id) for sample_id in sample_ids]
    selected_top_ks = _normalize_top_ks(top_ks)
    cases = _select_cases(load_answer_evalset(evalset_path), selected_ids)
    results = [
        _evaluate_context_shadow_case(
            case,
            top_ks=selected_top_ks,
            retrieval_service=retrieval_service,
            metadata_store=metadata_store,
        )
        for case in cases
    ]
    return _build_report(
        evalset_path=evalset_path,
        sample_ids=selected_ids,
        top_ks=selected_top_ks,
        results=results,
    )


def write_answer_context_shadow_report(
    evalset_path: str | Path = DEFAULT_EVALSET,
    *,
    sample_ids: Iterable[str] = DEFAULT_SAMPLE_IDS,
    top_ks: Iterable[int] = DEFAULT_TOP_KS,
    output_json: str | Path = DEFAULT_OUTPUT_JSON,
    retrieval_service=retrieval_service,
    metadata_store: KnowledgeMetadataStore | None = knowledge_metadata_store,
) -> dict[str, Any]:
    report = build_answer_context_shadow_report(
        evalset_path,
        sample_ids=sample_ids,
        top_ks=top_ks,
        retrieval_service=retrieval_service,
        metadata_store=metadata_store,
    )
    json_path = Path(output_json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path = json_path.with_suffix(".md")
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    report["report_json_path"] = str(json_path)
    report["report_markdown_path"] = str(md_path)
    return report


def _evaluate_context_shadow_case(
    case: dict[str, Any],
    *,
    top_ks: list[int],
    retrieval_service,
    metadata_store: KnowledgeMetadataStore | None,
) -> dict[str, Any]:
    top_k_results = {
        str(top_k): _run_context_probe(
            case,
            top_k=top_k,
            retrieval_service=retrieval_service,
            metadata_store=metadata_store,
        )
        for top_k in top_ks
    }
    default_result = top_k_results.get(str(DEFAULT_TOP_K), {})
    promotion_result = top_k_results.get(str(PROMOTION_TOP_K), {})
    default_missing = default_result.get("missing_context_facts") or []
    promotion_missing = promotion_result.get("missing_context_facts") or []
    return {
        "sample_id": case["sample_id"],
        "query": case["query"],
        "expected_doc_ids": list(case.get("expected_doc_ids") or []),
        "required_context_facts": list(case.get("must_include_facts") or []),
        "top_k_results": top_k_results,
        "context_lift": {
            "default_top_k": DEFAULT_TOP_K,
            "promotion_top_k": PROMOTION_TOP_K,
            "default_missing_context_fact_count": len(default_missing),
            "promotion_missing_context_fact_count": len(promotion_missing),
            "promotion_clears_default_context_missing": bool(default_missing) and not promotion_missing,
        },
    }


def _run_context_probe(
    case: dict[str, Any],
    *,
    top_k: int,
    retrieval_service,
    metadata_store: KnowledgeMetadataStore | None,
) -> dict[str, Any]:
    selected_kb_ids = list(case.get("allowed_kb_ids") or [])
    query = RetrievalQuery(
        query=str(case["query"]),
        top_k=top_k,
        retrieval_mode=_retrieval_mode(case.get("retrieval_mode")),
        knowledge_base_ids=selected_kb_ids,
    )
    response = retrieval_service.retrieve(query)
    context_text = response.context_text
    required_facts = [str(fact) for fact in case.get("must_include_facts") or []]
    missing_context_facts = [
        fact for fact in required_facts if not contains_required_text(context_text, fact)
    ]
    source_refs = [
        result.source_ref.model_dump(mode="json")
        for result in response.results
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
            "all_source_ref_complete": True,
            "all_resolvable": True,
            "citation_unresolvable_count": 0,
            "cross_scope_error_count": 0,
            "results": [],
        }
    )
    actual_doc_ids = [result.doc_id for result in response.results]
    expected_doc_ids = list(case.get("expected_doc_ids") or [])
    return {
        "top_k": top_k,
        "result_count": len(response.results),
        "expected_doc_ids": expected_doc_ids,
        "actual_doc_ids": actual_doc_ids,
        "expected_doc_hit": bool(set(expected_doc_ids) & set(actual_doc_ids)),
        "missing_context_fact_count": len(missing_context_facts),
        "missing_context_facts": missing_context_facts,
        "covered_context_facts": [fact for fact in required_facts if fact not in missing_context_facts],
        "context_text_chars": len(context_text),
        "source_ref": source_refs,
        "source_ref_integrity": integrity,
    }


def _build_report(
    *,
    evalset_path: str | Path,
    sample_ids: list[str],
    top_ks: list[int],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    promoted = [
        row["sample_id"]
        for row in results
        if row["context_lift"]["promotion_clears_default_context_missing"]
    ]
    return {
        "report_name": "answer_30q_context_shadow",
        "evalset_path": str(evalset_path),
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {
            "layer": "answer_context_shadow",
            "shadow_only": True,
            "calls_llm_answer_generator": False,
            "uses_llm_as_judge": False,
            "changes_main_gate": False,
            "writes_back_to_baseline": False,
            "changes_runtime_config": False,
            "changes_answer_prompt": False,
            "changes_default_top_k": False,
            "changes_default_retrieval_mode": False,
            "changes_query_rewrite_mode": False,
            "changes_rerank_enabled": False,
        },
        "summary": {
            "sample_count": len(results),
            "sample_ids": sample_ids,
            "top_k_values": top_ks,
            "default_top_k": DEFAULT_TOP_K,
            "promotion_top_k": PROMOTION_TOP_K,
            "promotion_clears_default_context_missing_count": len(promoted),
            "promotion_clears_default_context_missing_sample_ids": promoted,
            "candidate_for_answer_rerun": bool(promoted),
        },
        "results": results,
    }


def _select_cases(cases: list[dict[str, Any]], sample_ids: list[str]) -> list[dict[str, Any]]:
    by_id = {case["sample_id"]: case for case in cases}
    missing = [sample_id for sample_id in sample_ids if sample_id not in by_id]
    if missing:
        raise ValueError(f"sample ids not found in evalset: {missing}")
    return [by_id[sample_id] for sample_id in sample_ids]


def _normalize_top_ks(top_ks: Iterable[int]) -> list[int]:
    values = sorted({int(top_k) for top_k in top_ks})
    if DEFAULT_TOP_K not in values:
        values.insert(0, DEFAULT_TOP_K)
    if PROMOTION_TOP_K not in values:
        values.append(PROMOTION_TOP_K)
    return sorted(values)


def _retrieval_mode(value: Any) -> RetrievalMode:
    try:
        return RetrievalMode(str(value or RetrievalMode.DENSE_ONLY.value))
    except ValueError:
        return RetrievalMode.DENSE_ONLY


def _render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Answer Context Shadow Report",
        "",
        f"- Evalset: `{report['evalset_path']}`",
        f"- Generated at: `{report['generated_at']}`",
        f"- Sample count: {summary['sample_count']}",
        f"- Top-k values: {summary['top_k_values']}",
        f"- Shadow only: `{report['scope']['shadow_only']}`",
        f"- Calls LLM answer generator: `{report['scope']['calls_llm_answer_generator']}`",
        f"- Changes main gate: `{report['scope']['changes_main_gate']}`",
        f"- Promotion clears default context missing: {summary['promotion_clears_default_context_missing_sample_ids']}",
        "",
        "## Results",
        "",
        "| sample_id | top_k | expected_doc_hit | missing_context_facts | actual_doc_ids |",
        "|---|---:|---|---|---|",
    ]
    for row in report["results"]:
        for top_k, top_k_result in row["top_k_results"].items():
            lines.append(
                "| {sample_id} | {top_k} | {expected_doc_hit} | {missing} | {docs} |".format(
                    sample_id=row["sample_id"],
                    top_k=top_k,
                    expected_doc_hit=top_k_result["expected_doc_hit"],
                    missing=json.dumps(top_k_result["missing_context_facts"], ensure_ascii=False),
                    docs=", ".join(top_k_result["actual_doc_ids"]),
                )
            )
    lines.append("")
    return "\n".join(lines)


def _parse_top_ks(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evalset", default=DEFAULT_EVALSET)
    parser.add_argument("--sample-id", action="append", dest="sample_ids")
    parser.add_argument("--top-ks", default=",".join(str(value) for value in DEFAULT_TOP_KS))
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON)
    args = parser.parse_args()

    report = write_answer_context_shadow_report(
        args.evalset,
        sample_ids=args.sample_ids or DEFAULT_SAMPLE_IDS,
        top_ks=_parse_top_ks(args.top_ks),
        output_json=args.output_json,
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
