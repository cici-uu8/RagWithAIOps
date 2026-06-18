"""Month1 Week3 Day0 top_k / rerank shadow matrix report.

This runner keeps runtime defaults locked and evaluates shadow-only candidate
groups on the existing 54q retrieval evalset. It separates:

- retrieval_top_k: first-stage dense recall pool size
- rerank_top_n: rerank-retained candidate size
- final_context_k: final context slice sent to deterministic answer proxy

It does not mutate runtime config or production defaults.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import config
from app.models import RetrievalMode, RetrievalQuery, RetrievalResponse, RetrievalResult
from app.services.chunk_text_helpers import build_search_text
from app.services.knowledge_metadata_store import KnowledgeMetadataStore, knowledge_metadata_store
from app.services.rerank_service import (
    BailianTextRerankScorer,
    LexicalRerankScorer,
    RerankScorer,
)
from app.services.retrieval_metrics import mrr_at_k, ndcg_at_k, recall_at_k
from app.services.retrieval_service import retrieval_service
from app.services.token_estimator import approx_token_count, detect_language
from app.services.vector_search_service import SearchResult
from evals.knowledge_base.run_department_rag_eval import (
    _answer_score,
    _failure_category,
    load_evalset,
    verify_source_ref_integrity,
)

DEFAULT_EVALSET = "evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_54q_after_c6_p2.jsonl"
DEFAULT_OUTPUT_JSON = "evals/knowledge_base/reports/month1_topk_rerank_shadow_matrix_54q_20260618.json"
DEFAULT_PRIOR_ANSWER_SHADOW = "evals/knowledge_base/reports/department_rag_answer_3q_top_k5_shadow_20260612.json"

DEFAULT_SCENARIOS = [
    {
        "scenario_id": "dense_k3_ctx3_default",
        "label": "当前默认",
        "retrieval_top_k": 3,
        "rerank_mode": "off",
        "rerank_top_n": None,
        "final_context_k": 3,
    },
    {
        "scenario_id": "dense_k5_ctx3_no_rerank",
        "label": "扩召回无 rerank (k=5)",
        "retrieval_top_k": 5,
        "rerank_mode": "off",
        "rerank_top_n": None,
        "final_context_k": 3,
    },
    {
        "scenario_id": "dense_k20_ctx5_no_rerank",
        "label": "扩召回无 rerank (k=20)",
        "retrieval_top_k": 20,
        "rerank_mode": "off",
        "rerank_top_n": None,
        "final_context_k": 5,
    },
    {
        "scenario_id": "dense_k10_lexical_rn5_ctx3",
        "label": "扩召回 + local lexical rerank",
        "retrieval_top_k": 10,
        "rerank_mode": "local_lexical",
        "rerank_top_n": 5,
        "final_context_k": 3,
    },
    {
        "scenario_id": "dense_k20_bailian_rn5_ctx3",
        "label": "扩召回 + Bailian rerank",
        "retrieval_top_k": 20,
        "rerank_mode": "bailian",
        "rerank_top_n": 5,
        "final_context_k": 3,
    },
    {
        "scenario_id": "dense_k50_lexical_rn8_ctx5",
        "label": "高召回压力 + local lexical rerank",
        "retrieval_top_k": 50,
        "rerank_mode": "local_lexical",
        "rerank_top_n": 8,
        "final_context_k": 5,
    },
]

DEFAULTS_LOCKED = {
    "rag_default_retrieval_mode": "dense_only",
    "rag_query_rewrite_mode": "off",
    "rerank_enabled": False,
    "rag_top_k": 3,
}


DenseRetrievalProvider = Callable[[dict[str, Any], int], dict[str, Any]]


class _Unset:
    pass


_UNSET = _Unset()


def build_topk_rerank_shadow_matrix_report(
    evalset_path: str | Path = DEFAULT_EVALSET,
    *,
    scenarios: list[dict[str, Any]] | None = None,
    retrieval_provider: DenseRetrievalProvider | None = None,
    metadata_store: KnowledgeMetadataStore | None = knowledge_metadata_store,
    local_scorer: RerankScorer | None = None,
    external_scorer: RerankScorer | None | object = _UNSET,
    prior_answer_shadow_path: str | Path = DEFAULT_PRIOR_ANSWER_SHADOW,
) -> dict[str, Any]:
    cases = load_evalset(evalset_path)
    selected_scenarios = _normalize_scenarios(scenarios or DEFAULT_SCENARIOS)
    provider = retrieval_provider or _default_dense_retrieval_provider
    local = local_scorer or LexicalRerankScorer()
    external = _resolve_external_scorer(external_scorer)
    scorer_inventory = _scorer_inventory(local_scorer=local, external_scorer=external)

    scenario_reports = [
        _evaluate_scenario(
            scenario,
            cases=cases,
            retrieval_provider=provider,
            metadata_store=metadata_store,
            local_scorer=local,
            external_scorer=external,
        )
        for scenario in selected_scenarios
    ]
    baseline = _baseline_scenario(scenario_reports)
    _attach_baseline_comparisons(scenario_reports, baseline)

    prior_answer_shadow = _load_prior_answer_shadow(prior_answer_shadow_path)
    summary = _build_report_summary(
        cases=cases,
        scenario_reports=scenario_reports,
        baseline_scenario_id=baseline["scenario_id"],
        prior_answer_shadow=prior_answer_shadow,
    )
    return {
        "report_name": "month1_topk_rerank_shadow_matrix",
        "generated_at": datetime.now(UTC).isoformat(),
        "evalset_path": str(evalset_path),
        "scope": {
            "phase": "Month1 Week3 Day0",
            "shadow_only": True,
            "changes_runtime_config": False,
            "changes_default_retrieval_mode": False,
            "changes_query_rewrite_mode": False,
            "changes_rerank_enabled": False,
            "changes_default_top_k": False,
            "calls_llm_answer_generator": False,
            "uses_llm_as_judge_for_this_gate": False,
        },
        "defaults_locked": dict(DEFAULTS_LOCKED),
        "scorers": scorer_inventory,
        "summary": summary,
        "prior_answer_shadow": prior_answer_shadow,
        "scenarios": scenario_reports,
    }

def write_topk_rerank_shadow_matrix_report(
    evalset_path: str | Path = DEFAULT_EVALSET,
    *,
    output_json: str | Path = DEFAULT_OUTPUT_JSON,
    output_md: str | Path | None = None,
    scenarios: list[dict[str, Any]] | None = None,
    retrieval_provider: DenseRetrievalProvider | None = None,
    metadata_store: KnowledgeMetadataStore | None = knowledge_metadata_store,
    local_scorer: RerankScorer | None = None,
    external_scorer: RerankScorer | None | object = _UNSET,
    prior_answer_shadow_path: str | Path = DEFAULT_PRIOR_ANSWER_SHADOW,
) -> dict[str, Any]:
    report = build_topk_rerank_shadow_matrix_report(
        evalset_path,
        scenarios=scenarios,
        retrieval_provider=retrieval_provider,
        metadata_store=metadata_store,
        local_scorer=local_scorer,
        external_scorer=external_scorer,
        prior_answer_shadow_path=prior_answer_shadow_path,
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
    lines = [
        "# Top-K / Rerank Shadow Matrix Report",
        "",
        f"- Evalset: `{report['evalset_path']}`",
        f"- Generated at: `{report['generated_at']}`",
        f"- Defaults locked: `{report['defaults_locked']}`",
        f"- Shadow only: `{report['scope']['shadow_only']}`",
        f"- Prior answer shadow: `{report['prior_answer_shadow']['status']}`",
        "",
        "## Scenario Summary",
        "",
        "| scenario_id | retrieval_top_k | rerank | rerank_top_n | final_context_k | pass_rate | expected_doc_hit | answer_score_avg | latency_p95_ms | gate |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for scenario in report["scenarios"]:
        summary = scenario["summary"]
        lines.append(
            "| {scenario_id} | {retrieval_top_k} | {rerank_mode} | {rerank_top_n} | {final_context_k} | {pass_rate} | {hit_rate} | {answer_score} | {latency_p95} | {gate} |".format(
                scenario_id=scenario["scenario_id"],
                retrieval_top_k=scenario["retrieval_top_k"],
                rerank_mode=scenario["rerank_mode"],
                rerank_top_n=scenario["rerank_top_n"] if scenario["rerank_top_n"] is not None else "-",
                final_context_k=scenario["final_context_k"],
                pass_rate=_fmt_pct(summary["pass_rate"]),
                hit_rate=_fmt_pct(summary["final_expected_doc_hit_rate"]),
                answer_score=_fmt_float(summary["answer_score_avg"]),
                latency_p95=summary["latency_ms"]["p95"],
                gate=summary["gate_decision"],
            )
        )
    lines.extend(
        [
            "",
            "## Gate Notes",
            "",
        ]
    )
    for note in report["summary"]["gate_notes"]:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def _normalize_scenarios(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for scenario in scenarios:
        scenario_id = str(scenario["scenario_id"])
        if scenario_id in seen:
            raise ValueError(f"duplicate scenario_id: {scenario_id}")
        seen.add(scenario_id)
        retrieval_top_k = int(scenario["retrieval_top_k"])
        final_context_k = int(scenario["final_context_k"])
        rerank_top_n = scenario.get("rerank_top_n")
        rerank_mode = str(scenario.get("rerank_mode") or "off")
        if final_context_k > retrieval_top_k:
            raise ValueError(f"{scenario_id}: final_context_k > retrieval_top_k")
        if rerank_mode == "off" and rerank_top_n not in (None, 0):
            raise ValueError(f"{scenario_id}: rerank_top_n must be null when rerank is off")
        if rerank_mode != "off":
            if rerank_top_n is None:
                raise ValueError(f"{scenario_id}: rerank_top_n required when rerank is enabled")
            rerank_top_n = int(rerank_top_n)
            if final_context_k > rerank_top_n:
                raise ValueError(f"{scenario_id}: final_context_k > rerank_top_n")
        normalized.append(
            {
                "scenario_id": scenario_id,
                "label": str(scenario.get("label") or scenario_id),
                "retrieval_top_k": retrieval_top_k,
                "rerank_mode": rerank_mode,
                "rerank_top_n": rerank_top_n,
                "final_context_k": final_context_k,
            }
        )
    return normalized


def _resolve_external_scorer(value: RerankScorer | None | object) -> RerankScorer | None:
    if value is _UNSET:
        if config.dashscope_api_key:
            return BailianTextRerankScorer()
        return None
    if value is None:
        return None
    return value


def _scorer_inventory(
    *,
    local_scorer: RerankScorer,
    external_scorer: RerankScorer | None,
) -> dict[str, Any]:
    return {
        "local_lexical": {
            "available": True,
            "model": getattr(local_scorer, "model", "local_lexical_v1") or "local_lexical_v1",
        },
        "bailian": {
            "available": external_scorer is not None,
            "model": getattr(external_scorer, "model", config.rerank_bailian_model)
            if external_scorer is not None
            else config.rerank_bailian_model,
            "endpoint": config.rerank_bailian_endpoint,
        },
    }


def _default_dense_retrieval_provider(case: dict[str, Any], top_k: int) -> dict[str, Any]:
    query = RetrievalQuery(
        query=str(case["query"]),
        top_k=top_k,
        retrieval_mode=RetrievalMode.DENSE_ONLY,
        knowledge_base_ids=list(case.get("allowed_kb_ids") or []),
        document_ids=list(case.get("document_ids") or []),
    )
    started_at = time.perf_counter()
    try:
        response = retrieval_service.retrieve(query)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        return {
            "response": None,
            "latency_ms": latency_ms,
            "embedding_api_calls": 1,
            "error": exc,
        }
    latency_ms = int((time.perf_counter() - started_at) * 1000)
    return {
        "response": response,
        "latency_ms": latency_ms,
        "embedding_api_calls": 1,
        "error": None,
    }


def _evaluate_scenario(
    scenario: dict[str, Any],
    *,
    cases: list[dict[str, Any]],
    retrieval_provider: DenseRetrievalProvider,
    metadata_store: KnowledgeMetadataStore | None,
    local_scorer: RerankScorer,
    external_scorer: RerankScorer | None,
) -> dict[str, Any]:
    rows = [
        _evaluate_case(
            case,
            scenario=scenario,
            retrieval_provider=retrieval_provider,
            metadata_store=metadata_store,
            local_scorer=local_scorer,
            external_scorer=external_scorer,
        )
        for case in cases
    ]
    return {
        **scenario,
        "summary": _scenario_summary(rows),
        "rows": rows,
    }


def _evaluate_case(
    case: dict[str, Any],
    *,
    scenario: dict[str, Any],
    retrieval_provider: DenseRetrievalProvider,
    metadata_store: KnowledgeMetadataStore | None,
    local_scorer: RerankScorer,
    external_scorer: RerankScorer | None,
) -> dict[str, Any]:
    retrieval_run = retrieval_provider(case, scenario["retrieval_top_k"])
    retrieval_error = retrieval_run.get("error")
    if retrieval_error is not None:
        return _blocked_case_row(
            case,
            scenario=scenario,
            blocked_stage="retrieval",
            exc=retrieval_error,
            retrieval_latency_ms=int(retrieval_run.get("latency_ms") or 0),
            embedding_api_calls=int(retrieval_run.get("embedding_api_calls") or 0),
        )

    response = retrieval_run["response"]
    pool_results = list((response.results if response is not None else [])[: scenario["retrieval_top_k"]])
    rerank_run = _apply_rerank(
        case,
        pool_results=pool_results,
        scenario=scenario,
        local_scorer=local_scorer,
        external_scorer=external_scorer,
    )
    reranked_results = rerank_run["ranked_results"]
    final_results = list(reranked_results[: scenario["final_context_k"]])
    final_response = RetrievalResponse(
        query=RetrievalQuery(
            query=str(case["query"]),
            top_k=scenario["final_context_k"],
            retrieval_mode=RetrievalMode.DENSE_ONLY,
            knowledge_base_ids=list(case.get("allowed_kb_ids") or []),
        ),
        results=final_results,
        context_text=_build_context_text(final_results),
    )
    integrity = (
        verify_source_ref_integrity(
            final_response,
            metadata_store=metadata_store,
            allowed_kb_ids=list(case.get("allowed_kb_ids") or []),
        )
        if metadata_store is not None
        else {
            "result_count": len(final_results),
            "all_source_ref_complete": True,
            "all_resolvable": True,
            "citation_unresolvable_count": 0,
            "cross_scope_error_count": 0,
            "results": [],
        }
    )
    answer_score = _answer_score(
        final_response.context_text,
        list(case.get("expected_answer_keywords") or []),
    )
    failure_category = _failure_category(case, final_response, integrity, metadata_store)
    status = "passed" if failure_category == "passed" else "failed"
    if rerank_run["status"] == "external_blocked":
        status = "external_blocked"
    elif rerank_run["status"] == "not_ready":
        status = "not_ready"

    expected_doc_ids = [str(item) for item in case.get("expected_doc_ids") or []]
    pool_doc_ids = [result.doc_id for result in pool_results]
    reranked_doc_ids = [result.doc_id for result in reranked_results]
    final_doc_ids = [result.doc_id for result in final_results]
    diagnostics = _diagnostics(
        expected_doc_ids=expected_doc_ids,
        pool_doc_ids=pool_doc_ids,
        final_doc_ids=final_doc_ids,
        rerank_mode=scenario["rerank_mode"],
    )
    context_text = final_response.context_text
    context_tokens = _estimate_tokens(context_text)
    rerank_input_tokens = _estimate_rerank_input_tokens(case["query"], pool_results)
    total_latency_ms = int(retrieval_run.get("latency_ms") or 0) + int(rerank_run["latency_ms"])
    return {
        "sample_id": case["sample_id"],
        "query": case["query"],
        "status": status,
        "failure_category": failure_category,
        "expected_doc_ids": expected_doc_ids,
        "retrieval_pool_doc_ids": pool_doc_ids,
        "reranked_doc_ids": reranked_doc_ids,
        "final_doc_ids": final_doc_ids,
        "answer_score": answer_score,
        "source_ref_integrity": integrity,
        "retrieval_metrics": {
            "pool_recall_at_k": round(recall_at_k([expected_doc_ids], pool_doc_ids), 4) if expected_doc_ids else 0.0,
            "final_recall_at_k": round(recall_at_k([expected_doc_ids], final_doc_ids), 4) if expected_doc_ids else 0.0,
            "pool_expected_doc_hit": diagnostics["pool_expected_doc_hit"],
            "final_expected_doc_hit": diagnostics["final_expected_doc_hit"],
        },
        "rerank_metrics": _rerank_metrics(
            expected_doc_ids=expected_doc_ids,
            pool_doc_ids=pool_doc_ids,
            reranked_doc_ids=reranked_doc_ids,
            rerank_run=rerank_run,
        ),
        "engineering_metrics": {
            "retrieval_latency_ms": int(retrieval_run.get("latency_ms") or 0),
            "rerank_latency_ms": int(rerank_run["latency_ms"]),
            "total_latency_ms": total_latency_ms,
            "context_estimated_tokens": context_tokens,
            "rerank_input_estimated_tokens": rerank_input_tokens,
            "embedding_api_calls": int(retrieval_run.get("embedding_api_calls") or 0),
            "rerank_api_calls": int(rerank_run["api_calls"]),
            "timeout": bool(rerank_run["timeout"]),
        },
        "rerank_status": rerank_run["status"],
        "rerank_model": rerank_run["model"],
        "rerank_error": rerank_run["error"],
        "diagnostics": diagnostics,
    }


def _blocked_case_row(
    case: dict[str, Any],
    *,
    scenario: dict[str, Any],
    blocked_stage: str,
    exc: Exception,
    retrieval_latency_ms: int,
    embedding_api_calls: int,
) -> dict[str, Any]:
    return {
        "sample_id": case["sample_id"],
        "query": case["query"],
        "status": "not_ready" if blocked_stage == "retrieval" else "external_blocked",
        "failure_category": f"{blocked_stage}_blocked",
        "expected_doc_ids": list(case.get("expected_doc_ids") or []),
        "retrieval_pool_doc_ids": [],
        "reranked_doc_ids": [],
        "final_doc_ids": [],
        "answer_score": 0.0,
        "source_ref_integrity": {
            "result_count": 0,
            "all_source_ref_complete": False,
            "all_resolvable": False,
            "citation_unresolvable_count": 0,
            "cross_scope_error_count": 0,
            "results": [],
        },
        "retrieval_metrics": {
            "pool_recall_at_k": 0.0,
            "final_recall_at_k": 0.0,
            "pool_expected_doc_hit": False,
            "final_expected_doc_hit": False,
        },
        "rerank_metrics": {
            "mrr_before": None,
            "mrr_after": None,
            "ndcg_before": None,
            "ndcg_after": None,
            "rank_before": None,
            "rank_after": None,
            "rank_lift": None,
            "rerank_latency_ms": 0,
            "blocked": blocked_stage != "retrieval",
        },
        "engineering_metrics": {
            "retrieval_latency_ms": retrieval_latency_ms,
            "rerank_latency_ms": 0,
            "total_latency_ms": retrieval_latency_ms,
            "context_estimated_tokens": 0,
            "rerank_input_estimated_tokens": 0,
            "embedding_api_calls": embedding_api_calls,
            "rerank_api_calls": 0,
            "timeout": isinstance(exc, TimeoutError),
        },
        "rerank_status": "not_requested" if scenario["rerank_mode"] == "off" else "blocked",
        "rerank_model": "",
        "rerank_error": str(exc),
        "diagnostics": {
            "pool_expected_doc_hit": False,
            "final_expected_doc_hit": False,
            "retrieval_pool_miss": True,
            "rerank_ceiling_limited": scenario["rerank_mode"] != "off",
            "context_pollution": False,
        },
    }


def _apply_rerank(
    case: dict[str, Any],
    *,
    pool_results: list[RetrievalResult],
    scenario: dict[str, Any],
    local_scorer: RerankScorer,
    external_scorer: RerankScorer | None,
) -> dict[str, Any]:
    if scenario["rerank_mode"] == "off":
        return {
            "status": "not_requested",
            "latency_ms": 0,
            "ranked_results": list(pool_results),
            "model": "",
            "api_calls": 0,
            "timeout": False,
            "error": "",
        }

    scorer: RerankScorer | None
    api_calls = 0
    model = ""
    if scenario["rerank_mode"] == "local_lexical":
        scorer = local_scorer
        model = getattr(local_scorer, "model", "local_lexical_v1") or "local_lexical_v1"
    elif scenario["rerank_mode"] == "bailian":
        scorer = external_scorer
        model = getattr(external_scorer, "model", config.rerank_bailian_model) if external_scorer else config.rerank_bailian_model
        api_calls = 1
    else:
        raise ValueError(f"unsupported rerank_mode: {scenario['rerank_mode']}")

    if scorer is None:
        return {
            "status": "external_blocked",
            "latency_ms": 0,
            "ranked_results": list(pool_results),
            "model": model,
            "api_calls": api_calls,
            "timeout": False,
            "error": "external_rerank_scorer_unavailable",
        }

    search_results = [_to_search_result(item) for item in pool_results]
    started_at = time.perf_counter()
    try:
        scores = scorer.score(str(case["query"]), search_results)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        return {
            "status": "external_blocked" if scenario["rerank_mode"] == "bailian" else "not_ready",
            "latency_ms": latency_ms,
            "ranked_results": list(pool_results),
            "model": model,
            "api_calls": api_calls,
            "timeout": isinstance(exc, TimeoutError),
            "error": str(exc),
        }

    latency_ms = int((time.perf_counter() - started_at) * 1000)
    ranked_pairs = sorted(
        enumerate(zip(pool_results, scores, strict=True)),
        key=lambda item: (-item[1][1], item[0]),
    )
    rerank_top_n = int(scenario["rerank_top_n"])
    ranked_results = [
        _copy_with_rerank_metadata(
            result,
            rerank_score=float(score),
            rerank_status="applied",
            rerank_model=model,
            rerank_latency_ms=latency_ms,
        )
        for _, (result, score) in ranked_pairs[:rerank_top_n]
    ]
    return {
        "status": "applied",
        "latency_ms": latency_ms,
        "ranked_results": ranked_results,
        "model": model,
        "api_calls": api_calls,
        "timeout": False,
        "error": "",
    }


def _to_search_result(result: RetrievalResult) -> SearchResult:
    metadata = dict(result.metadata)
    metadata.setdefault("heading_path", list(result.source_ref.heading_path))
    metadata.setdefault("source_ref", result.source_ref.model_dump(mode="json"))
    metadata.setdefault("chunk_id", result.chunk_id)
    metadata.setdefault("doc_id", result.doc_id)
    metadata.setdefault("kb_id", result.kb_id)
    return SearchResult(
        id=result.chunk_id,
        content=result.content,
        score=float(result.score or 0.0),
        metadata=metadata,
    )


def _copy_with_rerank_metadata(result: RetrievalResult, **updates: Any) -> RetrievalResult:
    copied = result.model_copy(deep=True)
    copied.metadata.update(updates)
    return copied


def _build_context_text(results: list[RetrievalResult]) -> str:
    if not results:
        return "没有找到相关信息。"
    formatted: list[str] = []
    for index, result in enumerate(results, start=1):
        headers = " > ".join(result.source_ref.heading_path) if result.source_ref.heading_path else ""
        block = [f"【参考资料 {index}】"]
        if headers:
            block.append(f"标题: {headers}")
        if result.source_ref.source_file:
            block.append(f"来源: {result.source_ref.source_file}")
        block.append("内容:")
        block.append(result.content)
        formatted.append("\n".join(block))
    return "\n\n".join(formatted)


def _estimate_rerank_input_tokens(query: str, results: list[RetrievalResult]) -> int:
    total = _estimate_tokens(str(query))
    for result in results:
        text = build_search_text(result.source_ref.heading_path, result.content)
        total += _estimate_tokens(text)
    return total


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return approx_token_count(text, detect_language(text))


def _diagnostics(
    *,
    expected_doc_ids: list[str],
    pool_doc_ids: list[str],
    final_doc_ids: list[str],
    rerank_mode: str,
) -> dict[str, Any]:
    expected = set(expected_doc_ids)
    pool_hit = bool(expected and expected.intersection(pool_doc_ids))
    final_hit = bool(expected and expected.intersection(final_doc_ids))
    return {
        "pool_expected_doc_hit": pool_hit,
        "final_expected_doc_hit": final_hit,
        "retrieval_pool_miss": expected_doc_ids and not pool_hit,
        "rerank_ceiling_limited": rerank_mode != "off" and expected_doc_ids and not pool_hit,
        "context_pollution": pool_hit and not final_hit,
    }


def _rerank_metrics(
    *,
    expected_doc_ids: list[str],
    pool_doc_ids: list[str],
    reranked_doc_ids: list[str],
    rerank_run: dict[str, Any],
) -> dict[str, Any]:
    if not expected_doc_ids:
        return {
            "mrr_before": None,
            "mrr_after": None,
            "ndcg_before": None,
            "ndcg_after": None,
            "rank_before": None,
            "rank_after": None,
            "rank_lift": None,
            "rerank_latency_ms": int(rerank_run["latency_ms"]),
            "blocked": rerank_run["status"] not in {"applied", "not_requested"},
        }
    rank_before = _first_rank(expected_doc_ids, pool_doc_ids)
    rank_after = _first_rank(expected_doc_ids, reranked_doc_ids)
    return {
        "mrr_before": round(mrr_at_k([expected_doc_ids], pool_doc_ids), 4),
        "mrr_after": round(mrr_at_k([expected_doc_ids], reranked_doc_ids), 4),
        "ndcg_before": round(ndcg_at_k([expected_doc_ids], pool_doc_ids), 4),
        "ndcg_after": round(ndcg_at_k([expected_doc_ids], reranked_doc_ids), 4),
        "rank_before": rank_before,
        "rank_after": rank_after,
        "rank_lift": (rank_before - rank_after) if rank_before is not None and rank_after is not None else None,
        "rerank_latency_ms": int(rerank_run["latency_ms"]),
        "blocked": rerank_run["status"] not in {"applied", "not_requested"},
    }


def _first_rank(expected_doc_ids: list[str], retrieved_doc_ids: list[str]) -> int | None:
    expected = set(expected_doc_ids)
    for index, doc_id in enumerate(retrieved_doc_ids, start=1):
        if doc_id in expected:
            return index
    return None


def _scenario_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    status_counts = dict(Counter(row["status"] for row in rows))
    failure_categories = dict(Counter(row["failure_category"] for row in rows))
    pass_count = status_counts.get("passed", 0)
    final_hit_count = sum(1 for row in rows if row["retrieval_metrics"]["final_expected_doc_hit"])
    pool_hit_count = sum(1 for row in rows if row["retrieval_metrics"]["pool_expected_doc_hit"])
    context_pollution_count = sum(1 for row in rows if row["diagnostics"]["context_pollution"])
    retrieval_pool_miss_count = sum(1 for row in rows if row["diagnostics"]["retrieval_pool_miss"])
    rerank_ceiling_limited_count = sum(1 for row in rows if row["diagnostics"]["rerank_ceiling_limited"])
    source_ref_incomplete_count = sum(
        1
        for row in rows
        if not row["source_ref_integrity"].get("all_source_ref_complete", False)
    )
    citation_unresolvable_count = sum(
        int(row["source_ref_integrity"].get("citation_unresolvable_count", 0))
        for row in rows
    )
    wrong_scope_count = sum(
        int(row["source_ref_integrity"].get("cross_scope_error_count", 0))
        for row in rows
    )
    timeouts = sum(1 for row in rows if row["engineering_metrics"]["timeout"])
    rerank_status_counts = dict(Counter(row["rerank_status"] for row in rows))
    return {
        "total": total,
        "status_counts": status_counts,
        "failure_categories": failure_categories,
        "pass_rate": round(pass_count / total, 4) if total else 0.0,
        "pool_expected_doc_hit_rate": round(pool_hit_count / total, 4) if total else 0.0,
        "final_expected_doc_hit_rate": round(final_hit_count / total, 4) if total else 0.0,
        "pool_recall_at_k_avg": _avg(row["retrieval_metrics"]["pool_recall_at_k"] for row in rows),
        "final_recall_at_k_avg": _avg(row["retrieval_metrics"]["final_recall_at_k"] for row in rows),
        "answer_score_avg": _avg(row["answer_score"] for row in rows),
        "wrong_scope_count": wrong_scope_count,
        "source_ref_incomplete_count": source_ref_incomplete_count,
        "citation_unresolvable_count": citation_unresolvable_count,
        "context_pollution_count": context_pollution_count,
        "retrieval_pool_miss_count": retrieval_pool_miss_count,
        "rerank_ceiling_limited_count": rerank_ceiling_limited_count,
        "rerank_status_counts": rerank_status_counts,
        "latency_ms": _distribution(row["engineering_metrics"]["total_latency_ms"] for row in rows),
        "rerank_latency_ms": _distribution(row["engineering_metrics"]["rerank_latency_ms"] for row in rows),
        "context_estimated_tokens": _distribution(
            row["engineering_metrics"]["context_estimated_tokens"] for row in rows
        ),
        "rerank_input_estimated_tokens": _distribution(
            row["engineering_metrics"]["rerank_input_estimated_tokens"] for row in rows
        ),
        "embedding_api_calls_total": sum(row["engineering_metrics"]["embedding_api_calls"] for row in rows),
        "rerank_api_calls_total": sum(row["engineering_metrics"]["rerank_api_calls"] for row in rows),
        "timeout_rate": round(timeouts / total, 4) if total else 0.0,
        "rerank_mrr_delta_avg": _avg(
            (row["rerank_metrics"]["mrr_after"] or 0.0) - (row["rerank_metrics"]["mrr_before"] or 0.0)
            for row in rows
            if row["rerank_metrics"]["mrr_before"] is not None and row["rerank_metrics"]["mrr_after"] is not None
        ),
        "rerank_ndcg_delta_avg": _avg(
            (row["rerank_metrics"]["ndcg_after"] or 0.0) - (row["rerank_metrics"]["ndcg_before"] or 0.0)
            for row in rows
            if row["rerank_metrics"]["ndcg_before"] is not None and row["rerank_metrics"]["ndcg_after"] is not None
        ),
        "positive_rank_lift_count": sum(
            1
            for row in rows
            if (row["rerank_metrics"]["rank_lift"] or 0) > 0
        ),
    }


def _baseline_scenario(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    for scenario in scenarios:
        if scenario["scenario_id"] == "dense_k3_ctx3_default":
            return scenario
    return scenarios[0]


def _attach_baseline_comparisons(
    scenarios: list[dict[str, Any]],
    baseline: dict[str, Any],
) -> None:
    baseline_rows = {row["sample_id"]: row for row in baseline["rows"]}
    baseline_summary = baseline["summary"]
    for scenario in scenarios:
        summary = scenario["summary"]
        summary["baseline_delta"] = {
            "pass_rate": round(summary["pass_rate"] - baseline_summary["pass_rate"], 4),
            "final_expected_doc_hit_rate": round(
                summary["final_expected_doc_hit_rate"] - baseline_summary["final_expected_doc_hit_rate"],
                4,
            ),
            "answer_score_avg": round(summary["answer_score_avg"] - baseline_summary["answer_score_avg"], 4),
            "latency_p95_ms": summary["latency_ms"]["p95"] - baseline_summary["latency_ms"]["p95"],
            "context_tokens_p95": summary["context_estimated_tokens"]["p95"]
            - baseline_summary["context_estimated_tokens"]["p95"],
        }
        summary["answer_proxy_regression_count"] = sum(
            1
            for row in scenario["rows"]
            if baseline_rows.get(row["sample_id"], {}).get("status") == "passed" and row["status"] != "passed"
        )
        summary["answer_proxy_lift_count"] = sum(
            1
            for row in scenario["rows"]
            if baseline_rows.get(row["sample_id"], {}).get("status") != "passed" and row["status"] == "passed"
        )
        summary["gate_decision"] = _gate_decision(
            summary=summary,
            baseline_summary=baseline_summary,
            is_baseline=scenario["scenario_id"] == baseline["scenario_id"],
        )


def _gate_decision(
    *,
    summary: dict[str, Any],
    baseline_summary: dict[str, Any],
    is_baseline: bool,
) -> str:
    if is_baseline:
        return "baseline"
    if summary["rerank_status_counts"].get("external_blocked", 0) == summary["total"]:
        return "external-blocked"
    if summary["wrong_scope_count"] > baseline_summary["wrong_scope_count"]:
        return "reject"
    if summary["source_ref_incomplete_count"] > baseline_summary["source_ref_incomplete_count"]:
        return "reject"
    if summary["final_expected_doc_hit_rate"] < baseline_summary["final_expected_doc_hit_rate"]:
        return "reject"
    if summary["answer_proxy_regression_count"] > max(1, summary["answer_proxy_lift_count"]):
        return "reject"
    if summary["latency_ms"]["p95"] > max(baseline_summary["latency_ms"]["p95"] * 1.8, baseline_summary["latency_ms"]["p95"] + 1200):
        return "keep-shadow"
    if summary["answer_score_avg"] > baseline_summary["answer_score_avg"] and summary["context_pollution_count"] == 0:
        return "keep-shadow"
    return "keep-shadow"


def _load_prior_answer_shadow(path: str | Path) -> dict[str, Any]:
    report_path = Path(path)
    if not report_path.exists():
        return {
            "path": report_path.as_posix(),
            "status": "missing",
            "summary": {},
        }
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    return {
        "path": report_path.as_posix(),
        "status": "loaded",
        "summary": dict(payload.get("summary") or {}),
    }


def _build_report_summary(
    *,
    cases: list[dict[str, Any]],
    scenario_reports: list[dict[str, Any]],
    baseline_scenario_id: str,
    prior_answer_shadow: dict[str, Any],
) -> dict[str, Any]:
    scenario_decisions = {
        scenario["scenario_id"]: scenario["summary"]["gate_decision"]
        for scenario in scenario_reports
    }
    promote_ready = [
        scenario_id
        for scenario_id, decision in scenario_decisions.items()
        if decision == "promote"
    ]
    gate_notes = [
        "本 gate 只做 shadow compare，不改 runtime 默认值。",
        "Retrieval 层用 54q 代表集做 dense recall pool 比较；rerank 只在 dense candidate pool 内重排。",
        "Answer 层本次使用 deterministic context/answer proxy；真实答案生成与 OpenJudge 不在本 gate 内重跑。",
    ]
    if prior_answer_shadow["status"] == "loaded":
        prior = prior_answer_shadow["summary"]
        gate_notes.append(
            "既有 3q sample-local top_k=5 Answer shadow 为 `passed={}/{}`，说明 context lift 不是 answer pass 的充分条件。".format(
                int(prior.get("passed") or 0),
                int(prior.get("total") or 0),
            )
        )
    return {
        "sample_count": len(cases),
        "scenario_count": len(scenario_reports),
        "baseline_scenario_id": baseline_scenario_id,
        "scenario_decisions": scenario_decisions,
        "promote_ready_scenarios": promote_ready,
        "gate_notes": gate_notes,
    }


def _distribution(values: Any) -> dict[str, int]:
    data = [int(value) for value in values]
    if not data:
        return {"avg": 0, "p50": 0, "p95": 0, "max": 0}
    sorted_data = sorted(data)
    return {
        "avg": int(sum(sorted_data) / len(sorted_data)),
        "p50": _percentile(sorted_data, 0.5),
        "p95": _percentile(sorted_data, 0.95),
        "max": sorted_data[-1],
    }


def _percentile(sorted_values: list[int], pct: float) -> int:
    if not sorted_values:
        return 0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = max(0, math.ceil(len(sorted_values) * pct) - 1)
    return sorted_values[min(rank, len(sorted_values) - 1)]


def _avg(values: Any) -> float:
    data = [float(value) for value in values]
    if not data:
        return 0.0
    return round(sum(data) / len(data), 4)


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _fmt_float(value: float) -> str:
    return f"{value:.4f}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run top_k / rerank shadow matrix report.")
    parser.add_argument("--evalset", default=DEFAULT_EVALSET, help="Path to retrieval evalset JSONL.")
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON, help="Output JSON report path.")
    parser.add_argument("--output-md", default="", help="Optional output Markdown report path.")
    args = parser.parse_args()
    write_topk_rerank_shadow_matrix_report(
        evalset_path=args.evalset,
        output_json=args.output_json,
        output_md=args.output_md or None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
