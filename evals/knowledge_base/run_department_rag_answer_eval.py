"""S5 answer-layer baseline runner for department RAG."""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import config
from app.enterprise.context import RequestContext
from app.models import RetrievalMode, RetrievalQuery, RetrievalResponse
from app.services.knowledge_metadata_store import KnowledgeMetadataStore, knowledge_metadata_store
from app.services.retrieval_service import retrieval_service
from evals.knowledge_base.answer_eval_helpers import check_answer_hard_gates
from evals.knowledge_base.run_department_rag_eval import verify_source_ref_integrity

ANSWER_REQUIRED_FIELDS = {
    "sample_id",
    "layer",
    "query",
    "allowed_kb_ids",
    "expected_doc_ids",
    "scope",
    "reference_answer",
    "must_include_facts",
    "must_not_include_claims",
    "required_citations",
    "context_policy",
}

DEFAULT_EVALSET = "evals/knowledge_base/evalsets/department_rag_answer_pilot_20q.jsonl"
DEFAULT_REPORT_NAME = "department_rag_answer_pilot_20q_baseline_20260611"
LLM_TEMPERATURE = 0.0
LLM_MAX_TOKENS = 900
LLM_TIMEOUT_SECONDS = 45
LLM_MAX_RETRIES = 1


@dataclass(frozen=True)
class GenerationResult:
    answer_text: str
    success: bool
    error_type: str = ""
    error_message: str = ""


class DashScopeContextAnswerGenerator:
    """Non-streaming eval generator that answers from retrieved context only."""

    generator_kind = "dashscope_context_llm"

    def __init__(self) -> None:
        self.model_name = config.rag_model
        self._llm = None

    def generate(
        self,
        *,
        query: str,
        context_text: str,
        sample: dict[str, Any],
    ) -> GenerationResult:
        if not config.dashscope_api_key:
            return GenerationResult(
                answer_text="",
                success=False,
                error_type="missing_api_key",
                error_message="DASHSCOPE_API_KEY is not configured",
            )
        prompt = build_answer_prompt(query=query, context_text=context_text, sample=sample)
        last_error = ""
        for attempt in range(LLM_MAX_RETRIES + 1):
            try:
                response = self._build_llm().invoke(prompt)
                text = response.content if hasattr(response, "content") else str(response)
                if not isinstance(text, str):
                    text = json.dumps(text, ensure_ascii=False)
                return GenerationResult(answer_text=text.strip(), success=True)
            except Exception as exc:  # noqa: BLE001 - eval report must capture external failures
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < LLM_MAX_RETRIES:
                    time.sleep(2**attempt)
        return GenerationResult(
            answer_text="",
            success=False,
            error_type="llm_generation_failed",
            error_message=last_error,
        )

    def _build_llm(self):
        if self._llm is None:
            from langchain_openai import ChatOpenAI

            self._llm = ChatOpenAI(
                model=self.model_name,
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_TOKENS,
                timeout=LLM_TIMEOUT_SECONDS,
                streaming=False,
                base_url=config.dashscope_api_base,
                api_key=config.dashscope_api_key,
            )
        return self._llm


def build_answer_prompt(
    *,
    query: str,
    context_text: str,
    sample: dict[str, Any],
) -> str:
    required_source_files = [
        str(citation.get("source_file") or citation.get("expected_in_answer") or "")
        for citation in sample.get("required_citations") or []
        if citation.get("source_file") or citation.get("expected_in_answer")
    ]
    source_hint = "、".join(required_source_files) if required_source_files else "检索上下文中的来源文件名"
    return (
        "你是企业知识库 Answer 层评测中的回答生成器。\n"
        "请只基于下面的检索上下文回答用户问题，不要使用外部知识，不要编造阈值、工具、流程或部门信息。\n"
        "如果上下文不足以回答，请明确说“参考资料不足以回答”。\n"
        "引用规则：每个关键事实后都要写来源文件名，格式为 [source: 文件名]。"
        f"本题至少应引用：{source_hint}。\n\n"
        f"检索上下文：\n{context_text}\n\n"
        f"用户问题：{query}\n\n"
        "请用中文回答，尽量简洁，但不要漏掉关键事实。"
    )


def load_answer_evalset(path: str | Path) -> list[dict[str, Any]]:
    evalset_path = Path(path)
    if not evalset_path.exists():
        raise FileNotFoundError(f"answer evalset not found: {evalset_path}")
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(evalset_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        missing = sorted(ANSWER_REQUIRED_FIELDS - set(payload))
        if missing:
            raise ValueError(f"{evalset_path}:{line_number} missing fields: {missing}")
        _validate_answer_case(evalset_path, line_number, payload)
        cases.append(payload)
    if not cases:
        raise ValueError(f"answer evalset empty: {evalset_path}")
    return cases


def run_department_rag_answer_eval(
    evalset_path: str | Path = DEFAULT_EVALSET,
    *,
    output_dir: str | Path = "evals/knowledge_base/reports",
    report_path: str | Path | None = None,
    write_report: bool = True,
    limit: int | None = None,
    retrieval_service=retrieval_service,
    metadata_store: KnowledgeMetadataStore | None = knowledge_metadata_store,
    answer_generator: Any | None = None,
) -> dict[str, Any]:
    cases = load_answer_evalset(evalset_path)
    if limit is not None:
        cases = cases[: max(0, limit)]
    generator = answer_generator or DashScopeContextAnswerGenerator()
    context = _eval_context()
    results: list[dict[str, Any]] = []
    for case in cases:
        results.append(
            _evaluate_answer_case(
                case,
                retrieval_service=retrieval_service,
                metadata_store=metadata_store,
                answer_generator=generator,
                context=context,
            )
        )
    report = _build_report(
        evalset_path=evalset_path,
        results=results,
        generator=generator,
    )
    if write_report:
        written = _write_reports(report, output_dir=output_dir, report_path=report_path)
        report.update(written)
    return report


def _evaluate_answer_case(
    case: dict[str, Any],
    *,
    retrieval_service,
    metadata_store: KnowledgeMetadataStore | None,
    answer_generator: Any,
    context: RequestContext,
) -> dict[str, Any]:
    retrieval_row, response = _run_retrieval(
        case,
        retrieval_service=retrieval_service,
        metadata_store=metadata_store,
        context=context,
    )
    if retrieval_row["status"] != "passed":
        gate = check_answer_hard_gates(
            sample=case,
            answer_text="",
            context_text=response.context_text if response is not None else "",
            retrieval_row=retrieval_row,
        )
        return _result_row(
            case=case,
            retrieval_row=retrieval_row,
            response=response,
            answer_text="",
            generation=GenerationResult("", success=False, error_type="retrieval_layer_failed"),
            gate=gate,
            status="failed",
        )

    generation = answer_generator.generate(
        query=str(case["query"]),
        context_text=response.context_text,
        sample=case,
    )
    if not generation.success:
        return _result_row(
            case=case,
            retrieval_row=retrieval_row,
            response=response,
            answer_text="",
            generation=generation,
            gate={},
            status="not_ready",
        )

    gate = check_answer_hard_gates(
        sample=case,
        answer_text=generation.answer_text,
        context_text=response.context_text,
        retrieval_row=retrieval_row,
    )
    return _result_row(
        case=case,
        retrieval_row=retrieval_row,
        response=response,
        answer_text=generation.answer_text,
        generation=generation,
        gate=gate,
        status="passed" if gate["hard_gate_passed"] else "failed",
    )


def _run_retrieval(
    case: dict[str, Any],
    *,
    retrieval_service,
    metadata_store: KnowledgeMetadataStore | None,
    context: RequestContext,
) -> tuple[dict[str, Any], RetrievalResponse | None]:
    selected_kb_ids = list(case.get("allowed_kb_ids") or [])
    query = RetrievalQuery(
        query=str(case["query"]),
        top_k=int(case.get("top_k") or 3),
        retrieval_mode=_retrieval_mode(case.get("retrieval_mode")),
        knowledge_base_ids=selected_kb_ids,
    )
    try:
        response = retrieval_service.retrieve(query)
    except Exception as exc:  # noqa: BLE001 - report external retrieval failures
        return _retrieval_not_ready_row(case, selected_kb_ids, context, exc), None

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
    expected_doc_hit = bool(set(expected_doc_ids) & set(actual_doc_ids))
    failure_category = _retrieval_failure_category(
        response=response,
        integrity=integrity,
        expected_doc_hit=expected_doc_hit,
    )
    status = "passed" if failure_category == "passed" else "failed"
    return (
        {
            "sample_id": case["sample_id"],
            "query": case["query"],
            "status": status,
            "failure_category": failure_category,
            "selected_kb_ids": selected_kb_ids,
            "expected_doc_ids": expected_doc_ids,
            "actual_doc_ids": actual_doc_ids,
            "expected_doc_hit": expected_doc_hit,
            "result_count": len(response.results),
            "source_ref": [
                result.source_ref.model_dump(mode="json")
                for result in response.results
                if getattr(result, "source_ref", None) is not None
            ],
            "source_ref_integrity": integrity,
            "trace_id": context.trace_id,
        },
        response,
    )


def _result_row(
    *,
    case: dict[str, Any],
    retrieval_row: dict[str, Any],
    response: RetrievalResponse | None,
    answer_text: str,
    generation: GenerationResult,
    gate: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    failure_category = gate.get("failure_category") or (
        "answer_generation_not_ready" if status == "not_ready" else retrieval_row["failure_category"]
    )
    return {
        "sample_id": case["sample_id"],
        "query": case["query"],
        "status": status,
        "failure_category": failure_category,
        "document_format": case.get("document_format", ""),
        "query_type": case.get("query_type", ""),
        "answer_risk_type": case.get("answer_risk_type", ""),
        "context_policy": case.get("context_policy", ""),
        "judge_policy": case.get("judge_policy", ""),
        "retrieval": retrieval_row,
        "answer_text": answer_text,
        "answer_text_chars": len(answer_text),
        "generation_success": generation.success,
        "generation_error_type": generation.error_type,
        "generation_error_message": generation.error_message,
        "gate": gate,
        "context_text_chars": len(response.context_text) if response is not None else 0,
    }


def _build_report(
    *,
    evalset_path: str | Path,
    results: list[dict[str, Any]],
    generator: Any,
) -> dict[str, Any]:
    status_counts = dict(Counter(row["status"] for row in results))
    failure_categories = dict(Counter(row["failure_category"] for row in results))
    gate_totals = _gate_totals(results)
    total = len(results)
    report = {
        "report_name": DEFAULT_REPORT_NAME,
        "evalset_path": str(evalset_path),
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {
            "layer": "answer",
            "retrieval_mode": "dense_only",
            "top_k": 3,
            "context_policy": "retrieved_context_only",
            "judge_policy": "deterministic_only",
            "calls_llm_answer_generator": True,
            "uses_ragas": False,
            "uses_llm_as_judge": False,
            "changes_runtime_config": False,
            "changes_default_retrieval_mode": False,
            "changes_query_rewrite_mode": False,
            "changes_rerank_enabled": False,
        },
        "generator": {
            "kind": getattr(generator, "generator_kind", type(generator).__name__),
            "model": getattr(generator, "model_name", ""),
            "temperature": LLM_TEMPERATURE,
            "max_tokens": LLM_MAX_TOKENS,
            "timeout_seconds": LLM_TIMEOUT_SECONDS,
            "max_retries": LLM_MAX_RETRIES,
        },
        "summary": {
            "total": total,
            "status_counts": status_counts,
            "failure_categories": failure_categories,
            "scored": sum(1 for row in results if row["status"] != "not_ready"),
            "not_ready": status_counts.get("not_ready", 0),
            "passed": status_counts.get("passed", 0),
            "failed": status_counts.get("failed", 0),
            "pass_rate": round(status_counts.get("passed", 0) / total, 4) if total else 0.0,
            "hard_gate_passed": total > 0 and status_counts.get("passed", 0) == total,
            "answer_baseline_run_complete": total > 0 and status_counts.get("not_ready", 0) == 0,
            **gate_totals,
        },
        "results": results,
    }
    return report


def _gate_totals(results: list[dict[str, Any]]) -> dict[str, int | bool]:
    fields = [
        "missing_required_fact_count",
        "context_missing_fact_count",
        "answer_missing_fact_count",
        "citation_required_but_missing",
        "unsupported_claim_count",
        "permission_leak_count",
        "source_ref_unresolvable_count",
    ]
    totals: dict[str, int | bool] = {
        field: sum(int((row.get("gate") or {}).get(field) or 0) for row in results)
        for field in fields
    }
    totals["retrieval_layer_failed_count"] = sum(
        1 for row in results if not (row.get("gate") or {}).get("retrieval_layer_passed", False)
    )
    totals["allow_active"] = (
        bool(results)
        and totals["citation_required_but_missing"] == 0
        and totals["unsupported_claim_count"] == 0
        and totals["permission_leak_count"] == 0
        and totals["source_ref_unresolvable_count"] == 0
        and totals["missing_required_fact_count"] == 0
        and totals["retrieval_layer_failed_count"] == 0
    )
    return totals


def _write_reports(
    report: dict[str, Any],
    *,
    output_dir: str | Path,
    report_path: str | Path | None,
) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    json_path = Path(report_path) if report_path else output / f"{DEFAULT_REPORT_NAME}.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path = json_path.with_suffix(".md")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown_report(report), encoding="utf-8")
    return {
        "report_json_path": str(json_path),
        "report_markdown_path": str(md_path),
    }


def _render_markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Department RAG Answer Baseline Report",
        "",
        f"- Evalset: `{report['evalset_path']}`",
        f"- Generated at: `{report['generated_at']}`",
        f"- Generator: `{report['generator']['kind']}` / `{report['generator']['model']}`",
        f"- Total: {summary['total']}",
        f"- Status counts: {summary['status_counts']}",
        f"- Failure categories: {summary['failure_categories']}",
        f"- Hard gate passed: {summary['hard_gate_passed']}",
        f"- Answer baseline run complete: {summary['answer_baseline_run_complete']}",
        "",
        "## Hard Gate Totals",
        "",
        f"- missing_required_fact_count: {summary['missing_required_fact_count']}",
        f"- citation_required_but_missing: {summary['citation_required_but_missing']}",
        f"- unsupported_claim_count: {summary['unsupported_claim_count']}",
        f"- permission_leak_count: {summary['permission_leak_count']}",
        f"- source_ref_unresolvable_count: {summary['source_ref_unresolvable_count']}",
        "",
        "## Results",
        "",
        "| sample_id | status | failure_category | format | query_type | missing_facts | missing_citations | unsupported |",
        "|---|---|---|---|---|---:|---:|---:|",
    ]
    for row in report["results"]:
        gate = row.get("gate") or {}
        lines.append(
            "| {sample_id} | {status} | {failure_category} | {fmt} | {query_type} | {missing} | {citation} | {unsupported} |".format(
                sample_id=row["sample_id"],
                status=row["status"],
                failure_category=row["failure_category"],
                fmt=row.get("document_format") or "-",
                query_type=row.get("query_type") or "-",
                missing=gate.get("missing_required_fact_count", "-"),
                citation=gate.get("citation_required_but_missing", "-"),
                unsupported=gate.get("unsupported_claim_count", "-"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _validate_answer_case(path: Path, line_number: int, payload: dict[str, Any]) -> None:
    for field in ("allowed_kb_ids", "expected_doc_ids", "must_include_facts", "must_not_include_claims", "required_citations"):
        if not isinstance(payload[field], list):
            raise ValueError(f"{path}:{line_number} {field} must be a list")
    if payload.get("layer") != "answer":
        raise ValueError(f"{path}:{line_number} layer must be answer")
    if payload.get("context_policy") != "retrieved_context_only":
        raise ValueError(f"{path}:{line_number} context_policy must be retrieved_context_only")


def _retrieval_mode(value: Any) -> RetrievalMode:
    try:
        return RetrievalMode(str(value or RetrievalMode.DENSE_ONLY.value))
    except ValueError:
        return RetrievalMode.DENSE_ONLY


def _retrieval_failure_category(
    *,
    response: RetrievalResponse,
    integrity: dict[str, Any],
    expected_doc_hit: bool,
) -> str:
    if not response.results:
        return "no_retrieval_hit"
    if integrity.get("cross_scope_error_count", 0) > 0:
        return "wrong_scope"
    if not integrity.get("all_source_ref_complete", False) or integrity.get("citation_unresolvable_count", 0) > 0:
        return "citation_unresolvable"
    if not expected_doc_hit:
        return "expected_doc_not_found"
    return "passed"


def _retrieval_not_ready_row(
    case: dict[str, Any],
    selected_kb_ids: list[str],
    context: RequestContext,
    exc: Exception,
) -> dict[str, Any]:
    return {
        "sample_id": case["sample_id"],
        "query": case["query"],
        "status": "not_ready",
        "failure_category": "retrieval_not_ready",
        "selected_kb_ids": selected_kb_ids,
        "expected_doc_ids": list(case.get("expected_doc_ids") or []),
        "actual_doc_ids": [],
        "expected_doc_hit": False,
        "result_count": 0,
        "source_ref": [],
        "source_ref_integrity": {
            "result_count": 0,
            "all_source_ref_complete": False,
            "all_resolvable": False,
            "citation_unresolvable_count": 0,
            "cross_scope_error_count": 0,
            "results": [],
        },
        "trace_id": context.trace_id,
        "blocked_module": "retrieval_service.retrieve",
        "blocked_error_type": type(exc).__name__,
        "blocked_error": str(exc),
    }


def _eval_context() -> RequestContext:
    return RequestContext(
        request_id="department-rag-answer-eval",
        trace_id="department-rag-answer-eval",
        user_id="department-rag-answer-eval",
        username="department-rag-answer-eval",
        department_id="eval",
        department_name="Eval",
        roles=["admin"],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run S5 department RAG answer eval.")
    parser.add_argument("--evalset", default=DEFAULT_EVALSET, help="Answer JSONL evalset path.")
    parser.add_argument("--output-dir", default="evals/knowledge_base/reports")
    parser.add_argument("--report", default="", help="Optional exact output report JSON path.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    report = run_department_rag_answer_eval(
        args.evalset,
        output_dir=args.output_dir,
        report_path=args.report or None,
        write_report=not args.no_write,
        limit=args.limit,
    )
    if args.no_write:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["summary"]["not_ready"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
