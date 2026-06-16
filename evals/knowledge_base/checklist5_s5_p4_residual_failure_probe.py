"""Checklist 5 S5-P4 observation-only residual answer-failure probes.

This script probes the seven residual failures from the repaired S5-P3.1
Answer Pilot baseline. It does not change production prompt, top_k, retrieval
mode, rerank, query rewrite, RAGAS, or agent behavior gates.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import config
from app.models import (
    ContextGranularity,
    ResultAggregation,
    RetrievalQuery,
    RetrievalResponse,
)
from app.services.knowledge_metadata_store import KnowledgeMetadataStore, knowledge_metadata_store
from app.services.retrieval_service import retrieval_service
from evals.knowledge_base.answer_eval_helpers import check_answer_hard_gates, contains_required_text
from evals.knowledge_base.run_department_rag_answer_eval import (
    DEFAULT_EVALSET,
    LLM_MAX_RETRIES,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    LLM_TIMEOUT_SECONDS,
    DashScopeContextAnswerGenerator,
    GenerationResult,
    _eval_context,
    _retrieval_mode,
    load_answer_evalset,
)
from evals.knowledge_base.run_department_rag_eval import verify_source_ref_integrity

DEFAULT_BASELINE_REPORT = (
    "evals/knowledge_base/reports/"
    "department_rag_answer_pilot_20q_baseline_after_s5_p31_repair_20260611.json"
)
DEFAULT_OUTPUT_JSON = (
    "evals/knowledge_base/reports/"
    "checklist5_s5_p4_residual_failure_probe_20260611.json"
)

PROMPT_POLICY_SAMPLE_IDS = ["S5P1-MD-001", "S5P1-MD-007"]
TOP_K_CONTEXT_SAMPLE_ID = "S5P1-MD-002"
PDF_SOURCE_SUPPORT_SAMPLE_IDS = ["S5P1-PDF-004", "S5P1-PDF-009"]
GENERATION_VARIANCE_SAMPLE_IDS = ["S5P1-PDF-001", "S5P1-PDF-002"]
RESIDUAL_SAMPLE_IDS = (
    PROMPT_POLICY_SAMPLE_IDS
    + [TOP_K_CONTEXT_SAMPLE_ID]
    + PDF_SOURCE_SUPPORT_SAMPLE_IDS
    + GENERATION_VARIANCE_SAMPLE_IDS
)


def build_s5_p4_residual_failure_probe_report(
    *,
    evalset_path: str | Path = DEFAULT_EVALSET,
    baseline_report_path: str | Path = DEFAULT_BASELINE_REPORT,
    retrieval_service=retrieval_service,
    metadata_store: KnowledgeMetadataStore | None = knowledge_metadata_store,
    generator_factory: Any | None = None,
    variance_runs: int = 5,
) -> dict[str, Any]:
    cases = load_answer_evalset(evalset_path)
    sample_by_id = {str(case["sample_id"]): case for case in cases}
    missing = [sample_id for sample_id in RESIDUAL_SAMPLE_IDS if sample_id not in sample_by_id]
    if missing:
        raise ValueError(f"S5-P4 residual samples missing from evalset: {missing}")

    baseline = _load_baseline_report(baseline_report_path)
    baseline_by_id = _baseline_results_by_id(baseline)
    factory = generator_factory or _default_generator_factory

    prompt_rows = _run_prompt_policy_probe(
        [sample_by_id[sample_id] for sample_id in PROMPT_POLICY_SAMPLE_IDS],
        baseline_by_id=baseline_by_id,
        retrieval_service=retrieval_service,
        metadata_store=metadata_store,
        generator=factory("prompt_enhanced"),
    )
    top_k_row = _run_top_k_context_probe(
        sample_by_id[TOP_K_CONTEXT_SAMPLE_ID],
        baseline_by_id=baseline_by_id,
        retrieval_service=retrieval_service,
        metadata_store=metadata_store,
        generator=factory("context_shadow"),
    )
    pdf_rows = _run_pdf_source_support_probe(
        [sample_by_id[sample_id] for sample_id in PDF_SOURCE_SUPPORT_SAMPLE_IDS],
        baseline_by_id=baseline_by_id,
        retrieval_service=retrieval_service,
        metadata_store=metadata_store,
    )
    variance_rows = _run_generation_variance_probe(
        [sample_by_id[sample_id] for sample_id in GENERATION_VARIANCE_SAMPLE_IDS],
        baseline_by_id=baseline_by_id,
        retrieval_service=retrieval_service,
        metadata_store=metadata_store,
        generator=factory("generation_variance"),
        variance_runs=variance_runs,
    )

    summary = _build_summary(
        baseline=baseline,
        prompt_rows=prompt_rows,
        top_k_row=top_k_row,
        pdf_rows=pdf_rows,
        variance_rows=variance_rows,
    )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "probe_name": "checklist5_s5_p4_residual_failure_probe",
        "status": "observation_only",
        "scope": {
            "phase": "S5-P4",
            "report_kind": "residual_answer_failure_probe",
            "evalset_path": Path(evalset_path).as_posix(),
            "baseline_report_path": Path(baseline_report_path).as_posix(),
            "sample_ids": list(RESIDUAL_SAMPLE_IDS),
            "sample_count": len(RESIDUAL_SAMPLE_IDS),
            "calls_llm_answer_generator": True,
            "uses_ragas": False,
            "uses_llm_as_judge": False,
            "changes_runtime_config": False,
            "changes_app_config": False,
            "changes_answer_prompt": False,
            "changes_default_top_k": False,
            "changes_default_retrieval_mode": False,
            "changes_query_rewrite_mode": False,
            "changes_rerank_enabled": False,
            "creates_formal_evalset": False,
            "runs_formal_20q_rerun": False,
        },
        "generator": {
            "baseline_model": getattr(config, "rag_model", ""),
            "temperature": LLM_TEMPERATURE,
            "max_tokens": LLM_MAX_TOKENS,
            "timeout_seconds": LLM_TIMEOUT_SECONDS,
            "max_retries": LLM_MAX_RETRIES,
        },
        "summary": summary,
        "probes": {
            "prompt_policy_shadow": prompt_rows,
            "top_k_context_shadow": top_k_row,
            "pdf_chunk_source_support": pdf_rows,
            "generation_variance": variance_rows,
        },
        "decisions": {
            "eligible_for_answer_50q": False,
            "requires_formal_20q_rerun_before_expansion": True,
            "change_production_prompt": False,
            "change_default_top_k": False,
            "change_default_retrieval_mode": False,
            "enable_rerank": False,
            "enable_query_rewrite": False,
            "use_ragas_as_gate": False,
            "enter_agent_behavior_layer": False,
        },
    }


def write_s5_p4_residual_failure_probe_report(
    *,
    output_json: str | Path = DEFAULT_OUTPUT_JSON,
    output_md: str | Path | None = None,
    evalset_path: str | Path = DEFAULT_EVALSET,
    baseline_report_path: str | Path = DEFAULT_BASELINE_REPORT,
    retrieval_service=retrieval_service,
    metadata_store: KnowledgeMetadataStore | None = knowledge_metadata_store,
    generator_factory: Any | None = None,
    variance_runs: int = 5,
) -> dict[str, Any]:
    report = build_s5_p4_residual_failure_probe_report(
        evalset_path=evalset_path,
        baseline_report_path=baseline_report_path,
        retrieval_service=retrieval_service,
        metadata_store=metadata_store,
        generator_factory=generator_factory,
        variance_runs=variance_runs,
    )
    output_json_path = Path(output_json)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    output_md_path = Path(output_md) if output_md is not None else output_json_path.with_suffix(".md")
    output_md_path.parent.mkdir(parents=True, exist_ok=True)
    output_md_path.write_text(render_markdown(report), encoding="utf-8")
    report["report_json_path"] = output_json_path.as_posix()
    report["report_markdown_path"] = output_md_path.as_posix()
    return report


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Checklist 5 S5-P4 Residual Failure Probe Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Status: `{report['status']}`",
        f"- Baseline passed: `{summary['baseline_passed']}/20`",
        f"- Sample count: `{summary['sample_count']}`",
        f"- Eligible for Answer 50q: `{report['decisions']['eligible_for_answer_50q']}`",
        f"- Requires formal 20q rerun: `{report['decisions']['requires_formal_20q_rerun_before_expansion']}`",
        "",
        "## Scope",
        "",
        f"- changes_answer_prompt: `{report['scope']['changes_answer_prompt']}`",
        f"- changes_default_top_k: `{report['scope']['changes_default_top_k']}`",
        f"- changes_default_retrieval_mode: `{report['scope']['changes_default_retrieval_mode']}`",
        f"- changes_query_rewrite_mode: `{report['scope']['changes_query_rewrite_mode']}`",
        f"- changes_rerank_enabled: `{report['scope']['changes_rerank_enabled']}`",
        f"- uses_ragas: `{report['scope']['uses_ragas']}`",
        f"- uses_llm_as_judge: `{report['scope']['uses_llm_as_judge']}`",
        "",
        "## Summary",
        "",
        f"- Prompt enhanced passed: `{summary['prompt_policy_probe']['enhanced_passed_count']}/2`",
        f"- Top-k=5 passed: `{summary['top_k_context_probe']['top_k_5_passed']}`",
        f"- Doc-level passed: `{summary['top_k_context_probe']['doc_level_passed']}`",
        f"- PDF source-support verdicts: `{summary['pdf_chunk_source_support_probe']['verdict_counts']}`",
        f"- Generation variance verdicts: `{summary['generation_variance_probe']['verdict_counts']}`",
        "",
        "## Prompt / Policy Shadow",
        "",
        "| sample_id | baseline_failure | enhanced_status | enhanced_failure | verdict |",
        "|---|---|---|---|---|",
    ]
    for row in report["probes"]["prompt_policy_shadow"]:
        lines.append(
            f"| {row['sample_id']} | {row['baseline_failure_category']} | "
            f"{row['enhanced_status']} | {row['enhanced_failure_category']} | {row['verdict']} |"
        )

    lines.extend(
        [
            "",
            "## Top-k / Context Shadow",
            "",
            "| variant | status | failure | context_missing_facts | context_facts_present | result_count |",
            "|---|---|---|---:|---:|---:|",
        ]
    )
    for variant in report["probes"]["top_k_context_shadow"]["variants"]:
        lines.append(
            f"| {variant['variant']} | {variant['status']} | {variant['failure_category']} | "
            f"{variant['context_missing_fact_count']} | {variant['context_fact_present_count']} | "
            f"{variant['retrieval_result_count']} |"
        )

    lines.extend(
        [
            "",
            "## PDF Chunk / Source-Support",
            "",
            "| sample_id | verdict | artifact_all_facts_supported | top3_fact_present | top10_fact_present | top3_rank | top10_rank | matching_artifact_chunks |",
            "|---|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in report["probes"]["pdf_chunk_source_support"]:
        lines.append(
            f"| {row['sample_id']} | {row['verdict']} | {row['artifact_all_facts_supported']} | "
            f"{row['top3_context_fact_present_count']} | {row['top10_context_fact_present_count']} | "
            f"{_display_rank(row['top3_first_matching_rank'])} | {_display_rank(row['top10_first_matching_rank'])} | "
            f"{_summarize_chunk_ids(row['matching_artifact_chunk_ids'])} |"
        )

    lines.extend(
        [
            "",
            "## Generation Variance",
            "",
            "| sample_id | passed_runs | total_runs | verdict | failure_counts |",
            "|---|---:|---:|---|---|",
        ]
    )
    for row in report["probes"]["generation_variance"]:
        lines.append(
            f"| {row['sample_id']} | {row['passed_runs']} | {row['total_runs']} | "
            f"{row['verdict']} | {row['failure_category_counts']} |"
        )
    lines.append("")
    return "\n".join(lines)


class EnhancedPromptAnswerGenerator:
    """Temporary S5-P4 prompt-shadow generator; does not change production prompt."""

    generator_kind = "dashscope_context_llm_s5_p4_enhanced_prompt_shadow"

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
        prompt = build_enhanced_prompt(query=query, context_text=context_text, sample=sample)
        last_error = ""
        for attempt in range(LLM_MAX_RETRIES + 1):
            try:
                response = self._build_llm().invoke(prompt)
                text = response.content if hasattr(response, "content") else str(response)
                if not isinstance(text, str):
                    text = json.dumps(text, ensure_ascii=False)
                return GenerationResult(answer_text=text.strip(), success=True)
            except Exception as exc:  # noqa: BLE001 - eval report captures external failures
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


def build_enhanced_prompt(
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
        "你是企业知识库 Answer 层评测中的临时 shadow 回答生成器。\n"
        "只基于给定检索上下文回答，不要使用外部知识，不要编造阈值、工具、流程或部门信息。\n"
        "重要：必须覆盖与问题直接相关的关键事实点；如果上下文中列出步骤、指标、对象、平台、结果或数值，不要只做笼统总结。\n"
        "如果上下文不足以回答，请明确说“参考资料不足以回答”。\n"
        "引用规则：每个关键事实后都要写来源文件名，格式为 [source: 文件名]。"
        f"本题至少应引用：{source_hint}。\n\n"
        f"检索上下文：\n{context_text}\n\n"
        f"用户问题：{query}\n\n"
        "请用中文回答，保持简洁，但不要漏掉上下文中能直接支持的关键事实。"
    )


def _default_generator_factory(kind: str):
    if kind == "prompt_enhanced":
        return EnhancedPromptAnswerGenerator()
    return DashScopeContextAnswerGenerator()


def _run_prompt_policy_probe(
    samples: list[dict[str, Any]],
    *,
    baseline_by_id: dict[str, dict[str, Any]],
    retrieval_service,
    metadata_store: KnowledgeMetadataStore | None,
    generator: Any,
) -> list[dict[str, Any]]:
    rows = []
    for sample in samples:
        retrieval_row, response = _run_retrieval_variant(
            sample,
            retrieval_service=retrieval_service,
            metadata_store=metadata_store,
        )
        if retrieval_row["status"] != "passed" or response is None:
            gate = check_answer_hard_gates(
                sample=sample,
                answer_text="",
                context_text=response.context_text if response else "",
                retrieval_row=retrieval_row,
            )
            generation = GenerationResult("", success=False, error_type="retrieval_layer_failed")
        else:
            generation = generator.generate(
                query=str(sample["query"]),
                context_text=response.context_text,
                sample=sample,
            )
            gate = (
                check_answer_hard_gates(
                    sample=sample,
                    answer_text=generation.answer_text,
                    context_text=response.context_text,
                    retrieval_row=retrieval_row,
                )
                if generation.success
                else {}
            )
        passed = bool(gate.get("hard_gate_passed"))
        rows.append(
            {
                "sample_id": sample["sample_id"],
                "query": sample["query"],
                "baseline_failure_category": _baseline_failure(baseline_by_id, sample["sample_id"]),
                "retrieval_status": retrieval_row["status"],
                "enhanced_status": "passed" if passed else "failed",
                "enhanced_failure_category": gate.get("failure_category") or generation.error_type or "not_ready",
                "missing_required_facts": gate.get("missing_required_facts", []),
                "answer_missing_facts": gate.get("answer_missing_facts", []),
                "context_missing_facts": gate.get("context_missing_facts", []),
                "generation_success": generation.success,
                "generation_error_type": generation.error_type,
                "verdict": "prompt_policy_repaired" if passed else "no_prompt_policy_lift",
            }
        )
    return rows


def _run_top_k_context_probe(
    sample: dict[str, Any],
    *,
    baseline_by_id: dict[str, dict[str, Any]],
    retrieval_service,
    metadata_store: KnowledgeMetadataStore | None,
    generator: Any,
) -> dict[str, Any]:
    variants = [
        {
            "variant": "current_top_k_3",
            "top_k": 3,
            "result_aggregation": ResultAggregation.NONE,
            "context_granularity": ContextGranularity.CHUNK,
        },
        {
            "variant": "shadow_top_k_5",
            "top_k": 5,
            "result_aggregation": ResultAggregation.NONE,
            "context_granularity": ContextGranularity.CHUNK,
        },
        {
            "variant": "shadow_doc_level",
            "top_k": 3,
            "result_aggregation": ResultAggregation.DOC_LEVEL,
            "context_granularity": ContextGranularity.CHUNK,
            "top_chunks_per_doc": 3,
        },
    ]
    rows = [
        _run_context_variant(
            sample,
            baseline_by_id=baseline_by_id,
            retrieval_service=retrieval_service,
            metadata_store=metadata_store,
            generator=generator,
            **variant,
        )
        for variant in variants
    ]
    by_variant = {row["variant"]: row for row in rows}
    top_k_5_passed = by_variant["shadow_top_k_5"]["status"] == "passed"
    doc_level_passed = by_variant["shadow_doc_level"]["status"] == "passed"
    if top_k_5_passed:
        verdict = "top_k_5_lift_observed"
    elif doc_level_passed:
        verdict = "doc_level_lift_observed"
    else:
        verdict = "no_context_lift_observed"
    return {
        "sample_id": sample["sample_id"],
        "query": sample["query"],
        "baseline_failure_category": _baseline_failure(baseline_by_id, sample["sample_id"]),
        "verdict": verdict,
        "top_k_5_passed": top_k_5_passed,
        "doc_level_passed": doc_level_passed,
        "variants": rows,
    }


def _run_context_variant(
    sample: dict[str, Any],
    *,
    baseline_by_id: dict[str, dict[str, Any]],
    retrieval_service,
    metadata_store: KnowledgeMetadataStore | None,
    generator: Any,
    variant: str,
    top_k: int,
    result_aggregation: ResultAggregation,
    context_granularity: ContextGranularity,
    top_chunks_per_doc: int = 1,
) -> dict[str, Any]:
    retrieval_row, response = _run_retrieval_variant(
        sample,
        retrieval_service=retrieval_service,
        metadata_store=metadata_store,
        top_k=top_k,
        result_aggregation=result_aggregation,
        context_granularity=context_granularity,
        top_chunks_per_doc=top_chunks_per_doc,
    )
    context_text = response.context_text if response else ""
    coverage = _required_fact_coverage(sample, context_text)
    if retrieval_row["status"] != "passed" or response is None:
        gate: dict[str, Any] = check_answer_hard_gates(
            sample=sample,
            answer_text="",
            context_text=context_text,
            retrieval_row=retrieval_row,
        )
        generation = GenerationResult("", success=False, error_type="retrieval_layer_failed")
    else:
        generation = generator.generate(
            query=str(sample["query"]),
            context_text=context_text,
            sample=sample,
        )
        gate = (
            check_answer_hard_gates(
                sample=sample,
                answer_text=generation.answer_text,
                context_text=context_text,
                retrieval_row=retrieval_row,
            )
            if generation.success
            else {}
        )
    return {
        "variant": variant,
        "baseline_failure_category": _baseline_failure(baseline_by_id, sample["sample_id"]),
        "top_k": top_k,
        "result_aggregation": result_aggregation.value,
        "context_granularity": context_granularity.value,
        "top_chunks_per_doc": top_chunks_per_doc,
        "retrieval_status": retrieval_row["status"],
        "retrieval_result_count": retrieval_row["result_count"],
        "actual_doc_ids": retrieval_row["actual_doc_ids"],
        "context_text_chars": len(context_text),
        "context_fact_present_count": len(coverage["present_facts"]),
        "context_missing_fact_count": len(coverage["missing_facts"]),
        "context_missing_facts": coverage["missing_facts"],
        "generation_success": generation.success,
        "generation_error_type": generation.error_type,
        "status": "passed" if gate.get("hard_gate_passed") else "failed",
        "failure_category": gate.get("failure_category") or generation.error_type or "not_ready",
        "missing_required_facts": gate.get("missing_required_facts", []),
    }


def _run_pdf_source_support_probe(
    samples: list[dict[str, Any]],
    *,
    baseline_by_id: dict[str, dict[str, Any]],
    retrieval_service,
    metadata_store: KnowledgeMetadataStore | None,
) -> list[dict[str, Any]]:
    rows = []
    for sample in samples:
        artifact = _load_artifact_chunks(sample, metadata_store)
        fact_support = _artifact_fact_support(sample, artifact["chunks"])
        matching_chunks = sorted(
            {
                chunk_id
                for chunk_ids in fact_support["fact_to_chunk_ids"].values()
                for chunk_id in chunk_ids
            }
        )
        top3_row, top3_response = _run_retrieval_variant(
            sample,
            retrieval_service=retrieval_service,
            metadata_store=metadata_store,
            top_k=3,
        )
        top10_row, top10_response = _run_retrieval_variant(
            sample,
            retrieval_service=retrieval_service,
            metadata_store=metadata_store,
            top_k=10,
        )
        top3_context_coverage = _required_fact_coverage(sample, top3_response.context_text if top3_response else "")
        top10_context_coverage = _required_fact_coverage(sample, top10_response.context_text if top10_response else "")
        top3_rank = _first_matching_chunk_rank(top3_response, matching_chunks)
        top10_rank = _first_matching_chunk_rank(top10_response, matching_chunks)
        if artifact["status"] != "loaded":
            verdict = "artifact_unavailable"
        elif not fact_support["all_facts_supported"]:
            verdict = "source_support_issue"
        elif not top3_context_coverage["missing_facts"]:
            verdict = "top3_contains_source_support"
        elif not top10_context_coverage["missing_facts"]:
            verdict = "chunk_indexed_but_ranked_low"
        else:
            verdict = "chunk_supported_but_not_retrieved_top10"
        rows.append(
            {
                "sample_id": sample["sample_id"],
                "query": sample["query"],
                "baseline_failure_category": _baseline_failure(baseline_by_id, sample["sample_id"]),
                "expected_doc_ids": list(sample.get("expected_doc_ids") or []),
                "artifact_status": artifact["status"],
                "artifact_dir": artifact["artifact_dir"],
                "artifact_chunk_count": len(artifact["chunks"]),
                "artifact_all_facts_supported": fact_support["all_facts_supported"],
                "artifact_missing_facts": fact_support["missing_facts"],
                "fact_to_chunk_ids": fact_support["fact_to_chunk_ids"],
                "matching_artifact_chunk_ids": matching_chunks,
                "top3_actual_chunk_ids": _response_chunk_ids(top3_response),
                "top10_actual_chunk_ids": _response_chunk_ids(top10_response),
                "top3_first_matching_rank": top3_rank,
                "top10_first_matching_rank": top10_rank,
                "top3_context_fact_present_count": len(top3_context_coverage["present_facts"]),
                "top3_context_missing_facts": top3_context_coverage["missing_facts"],
                "top10_context_fact_present_count": len(top10_context_coverage["present_facts"]),
                "top10_context_missing_facts": top10_context_coverage["missing_facts"],
                "top3_retrieval_status": top3_row["status"],
                "top10_retrieval_status": top10_row["status"],
                "verdict": verdict,
            }
        )
    return rows


def _run_generation_variance_probe(
    samples: list[dict[str, Any]],
    *,
    baseline_by_id: dict[str, dict[str, Any]],
    retrieval_service,
    metadata_store: KnowledgeMetadataStore | None,
    generator: Any,
    variance_runs: int,
) -> list[dict[str, Any]]:
    rows = []
    for sample in samples:
        retrieval_row, response = _run_retrieval_variant(
            sample,
            retrieval_service=retrieval_service,
            metadata_store=metadata_store,
        )
        run_rows = []
        for run_index in range(max(variance_runs, 1)):
            if retrieval_row["status"] != "passed" or response is None:
                generation = GenerationResult("", success=False, error_type="retrieval_layer_failed")
                gate = check_answer_hard_gates(
                    sample=sample,
                    answer_text="",
                    context_text=response.context_text if response else "",
                    retrieval_row=retrieval_row,
                )
            else:
                generation = generator.generate(
                    query=str(sample["query"]),
                    context_text=response.context_text,
                    sample=sample,
                )
                gate = (
                    check_answer_hard_gates(
                        sample=sample,
                        answer_text=generation.answer_text,
                        context_text=response.context_text,
                        retrieval_row=retrieval_row,
                    )
                    if generation.success
                    else {}
                )
            run_rows.append(
                {
                    "run_index": run_index + 1,
                    "generation_success": generation.success,
                    "generation_error_type": generation.error_type,
                    "status": "passed" if gate.get("hard_gate_passed") else "failed",
                    "failure_category": gate.get("failure_category") or generation.error_type or "not_ready",
                    "missing_required_facts": gate.get("missing_required_facts", []),
                    "answer_text_chars": len(generation.answer_text),
                }
            )
        passed_runs = sum(1 for row in run_rows if row["status"] == "passed")
        if passed_runs >= max(variance_runs, 1) - 1:
            verdict = "stable_pass"
        elif 2 <= passed_runs <= 3:
            verdict = "unstable_generation"
        else:
            verdict = "stable_fail"
        rows.append(
            {
                "sample_id": sample["sample_id"],
                "query": sample["query"],
                "baseline_failure_category": _baseline_failure(baseline_by_id, sample["sample_id"]),
                "retrieval_status": retrieval_row["status"],
                "total_runs": len(run_rows),
                "passed_runs": passed_runs,
                "failed_runs": len(run_rows) - passed_runs,
                "failure_category_counts": dict(Counter(row["failure_category"] for row in run_rows)),
                "verdict": verdict,
                "runs": run_rows,
            }
        )
    return rows


def _run_retrieval_variant(
    sample: dict[str, Any],
    *,
    retrieval_service,
    metadata_store: KnowledgeMetadataStore | None,
    top_k: int | None = None,
    result_aggregation: ResultAggregation = ResultAggregation.NONE,
    context_granularity: ContextGranularity = ContextGranularity.CHUNK,
    top_chunks_per_doc: int = 1,
) -> tuple[dict[str, Any], RetrievalResponse | None]:
    selected_kb_ids = list(sample.get("allowed_kb_ids") or [])
    query = RetrievalQuery(
        query=str(sample["query"]),
        top_k=int(top_k if top_k is not None else sample.get("top_k") or 3),
        retrieval_mode=_retrieval_mode(sample.get("retrieval_mode")),
        knowledge_base_ids=selected_kb_ids,
        result_aggregation=result_aggregation,
        context_granularity=context_granularity,
        top_chunks_per_doc=top_chunks_per_doc,
    )
    context = _eval_context()
    try:
        response = retrieval_service.retrieve(query)
    except Exception as exc:  # noqa: BLE001 - report external retrieval failures
        return (
            {
                "sample_id": sample["sample_id"],
                "query": sample["query"],
                "status": "not_ready",
                "failure_category": "retrieval_not_ready",
                "selected_kb_ids": selected_kb_ids,
                "expected_doc_ids": list(sample.get("expected_doc_ids") or []),
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
            },
            None,
        )

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
    expected_doc_ids = list(sample.get("expected_doc_ids") or [])
    expected_doc_hit = bool(set(expected_doc_ids) & set(actual_doc_ids))
    failure_category = _retrieval_failure_category(
        response=response,
        integrity=integrity,
        expected_doc_hit=expected_doc_hit,
    )
    return (
        {
            "sample_id": sample["sample_id"],
            "query": sample["query"],
            "status": "passed" if failure_category == "passed" else "failed",
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


def _build_summary(
    *,
    baseline: dict[str, Any],
    prompt_rows: list[dict[str, Any]],
    top_k_row: dict[str, Any],
    pdf_rows: list[dict[str, Any]],
    variance_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_summary = baseline.get("summary") or {}
    prompt_passed = sum(1 for row in prompt_rows if row["enhanced_status"] == "passed")
    pdf_counts = Counter(row["verdict"] for row in pdf_rows)
    variance_counts = Counter(row["verdict"] for row in variance_rows)
    return {
        "sample_count": len(RESIDUAL_SAMPLE_IDS),
        "baseline_total": int(baseline_summary.get("total") or 20),
        "baseline_passed": int(baseline_summary.get("passed") or 0),
        "baseline_failed": int(baseline_summary.get("failed") or 0),
        "baseline_threshold_passed": 14,
        "prompt_policy_probe": {
            "sample_count": len(prompt_rows),
            "enhanced_passed_count": prompt_passed,
            "enhanced_failed_count": len(prompt_rows) - prompt_passed,
            "verdict_counts": dict(Counter(row["verdict"] for row in prompt_rows)),
        },
        "top_k_context_probe": {
            "sample_count": 1,
            "top_k_5_passed": bool(top_k_row["top_k_5_passed"]),
            "doc_level_passed": bool(top_k_row["doc_level_passed"]),
            "verdict": top_k_row["verdict"],
        },
        "pdf_chunk_source_support_probe": {
            "sample_count": len(pdf_rows),
            "source_support_issue_count": int(pdf_counts.get("source_support_issue") or 0),
            "chunk_indexed_but_ranked_low_count": int(pdf_counts.get("chunk_indexed_but_ranked_low") or 0),
            "top3_contains_source_support_count": int(pdf_counts.get("top3_contains_source_support") or 0),
            "verdict_counts": dict(pdf_counts),
        },
        "generation_variance_probe": {
            "sample_count": len(variance_rows),
            "stable_pass_count": int(variance_counts.get("stable_pass") or 0),
            "unstable_count": int(variance_counts.get("unstable_generation") or 0),
            "stable_fail_count": int(variance_counts.get("stable_fail") or 0),
            "verdict_counts": dict(variance_counts),
        },
        "formal_20q_rerun_required": True,
    }


def _required_fact_coverage(sample: dict[str, Any], text: str) -> dict[str, list[str]]:
    present = []
    missing = []
    for fact in sample.get("must_include_facts") or []:
        if contains_required_text(text, str(fact)):
            present.append(str(fact))
        else:
            missing.append(str(fact))
    return {"present_facts": present, "missing_facts": missing}


def _load_artifact_chunks(
    sample: dict[str, Any],
    metadata_store: KnowledgeMetadataStore | None,
) -> dict[str, Any]:
    if metadata_store is None:
        return {"status": "metadata_store_missing", "artifact_dir": "", "chunks": []}
    expected_doc_ids = list(sample.get("expected_doc_ids") or [])
    if not expected_doc_ids:
        return {"status": "expected_doc_missing", "artifact_dir": "", "chunks": []}
    document = metadata_store.get_document(str(expected_doc_ids[0]))
    if document is None:
        return {"status": "document_missing", "artifact_dir": "", "chunks": []}
    artifact_dir = Path(str(getattr(document, "artifact_dir", "") or ""))
    chunks_path = artifact_dir / "chunks.json"
    if not chunks_path.exists():
        return {"status": "chunks_json_missing", "artifact_dir": artifact_dir.as_posix(), "chunks": []}
    raw = json.loads(chunks_path.read_text(encoding="utf-8"))
    chunks = raw.get("chunks", raw) if isinstance(raw, dict) else raw
    if not isinstance(chunks, list):
        return {"status": "chunks_json_invalid", "artifact_dir": artifact_dir.as_posix(), "chunks": []}
    normalized = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        chunk_id = str(chunk.get("id") or chunk.get("chunk_id") or "")
        text = str(chunk.get("text") or chunk.get("content") or "")
        if chunk_id or text:
            normalized.append({"chunk_id": chunk_id, "text": text, "pages": chunk.get("pages", [])})
    return {"status": "loaded", "artifact_dir": artifact_dir.as_posix(), "chunks": normalized}


def _artifact_fact_support(
    sample: dict[str, Any],
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    fact_to_chunk_ids: dict[str, list[str]] = {}
    missing = []
    for fact in sample.get("must_include_facts") or []:
        matches = [
            str(chunk["chunk_id"])
            for chunk in chunks
            if contains_required_text(str(chunk.get("text") or ""), str(fact))
        ]
        fact_to_chunk_ids[str(fact)] = matches
        if not matches:
            missing.append(str(fact))
    return {
        "all_facts_supported": not missing,
        "missing_facts": missing,
        "fact_to_chunk_ids": fact_to_chunk_ids,
    }


def _first_matching_chunk_rank(response: RetrievalResponse | None, artifact_chunk_ids: list[str]) -> int | None:
    if response is None or not artifact_chunk_ids:
        return None
    targets = {_chunk_suffix(chunk_id) for chunk_id in artifact_chunk_ids}
    for index, result in enumerate(response.results, start=1):
        if _chunk_suffix(result.chunk_id) in targets:
            return index
    return None


def _response_chunk_ids(response: RetrievalResponse | None) -> list[str]:
    if response is None:
        return []
    return [result.chunk_id for result in response.results]


def _chunk_suffix(chunk_id: str) -> str:
    text = str(chunk_id)
    if ":" in text:
        return text.rsplit(":", 1)[1]
    return text


def _baseline_failure(baseline_by_id: dict[str, dict[str, Any]], sample_id: str) -> str:
    row = baseline_by_id.get(str(sample_id)) or {}
    return str(row.get("failure_category") or "")


def _load_baseline_report(path: str | Path) -> dict[str, Any]:
    baseline_path = Path(path)
    if not baseline_path.exists():
        raise FileNotFoundError(f"S5-P3.1 baseline report not found: {baseline_path}")
    return json.loads(baseline_path.read_text(encoding="utf-8"))


def _baseline_results_by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = report.get("results") or report.get("samples") or []
    return {str(row.get("sample_id")): row for row in rows if row.get("sample_id")}


def _display_rank(value: int | None) -> str:
    return "-" if value is None else str(value)


def _summarize_chunk_ids(chunk_ids: list[str], limit: int = 8) -> str:
    if not chunk_ids:
        return "-"
    if len(chunk_ids) <= limit:
        return ", ".join(chunk_ids)
    return ", ".join(chunk_ids[:limit]) + f", ... (+{len(chunk_ids) - limit})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run S5-P4 residual answer-failure observation probes.")
    parser.add_argument("--evalset", default=DEFAULT_EVALSET, help="Answer JSONL evalset path.")
    parser.add_argument("--baseline-report", default=DEFAULT_BASELINE_REPORT)
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", default="")
    parser.add_argument("--variance-runs", type=int, default=5)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    if args.no_write:
        report = build_s5_p4_residual_failure_probe_report(
            evalset_path=args.evalset,
            baseline_report_path=args.baseline_report,
            variance_runs=args.variance_runs,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        report = write_s5_p4_residual_failure_probe_report(
            output_json=args.output_json,
            output_md=args.output_md or None,
            evalset_path=args.evalset,
            baseline_report_path=args.baseline_report,
            variance_runs=args.variance_runs,
        )
        print(json.dumps({"report_json_path": report["report_json_path"], "status": report["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
