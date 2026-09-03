"""OpenJudge shadow evaluator for Answer-layer reports.

This runner reads an existing deterministic Answer baseline report and writes a
separate OpenJudge shadow report. Shadow scores never write back to the baseline
and never affect deterministic pass/fail.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import config

DEFAULT_BASELINE_REPORT = (
    "evals/knowledge_base/reports/"
    "department_rag_answer_pilot_20q_baseline_after_s5_p31_repair_20260611.json"
)
DEFAULT_EVALSET: str | None = None
DEFAULT_OUTPUT_JSON = (
    "evals/knowledge_base/reports/openjudge_answer_shadow_eval_20260611.json"
)

GRADER_NAMES = ("relevance", "hallucination", "correctness", "instruction_following")
CONTEXT_DEPENDENT_GRADERS = {"hallucination"}
REFERENCE_DEPENDENT_GRADERS = {"correctness"}
OpenJudgeResultsProvider = Callable[[list[dict[str, Any]]], dict[str, list[Any]]]


def load_baseline_report(path: str | Path) -> dict[str, Any]:
    report_path = Path(path)
    if not report_path.exists():
        raise FileNotFoundError(f"baseline report not found: {report_path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report.get("results"), list):
        raise ValueError(f"baseline report missing results list: {report_path}")
    return report


def load_evalset_by_sample_id(path: str | Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    evalset_path = Path(path)
    if not evalset_path.exists():
        raise FileNotFoundError(f"answer evalset not found: {evalset_path}")
    samples: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(evalset_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        sample_id = str(row.get("sample_id") or "")
        if not sample_id:
            raise ValueError(f"{evalset_path}:{line_number} missing sample_id")
        samples[sample_id] = row
    return samples


def build_openjudge_answer_shadow_report(
    *,
    baseline_report_path: str | Path = DEFAULT_BASELINE_REPORT,
    evalset_path: str | Path | None = DEFAULT_EVALSET,
    openjudge_results_provider: OpenJudgeResultsProvider | None = None,
    max_concurrency: int = 4,
) -> dict[str, Any]:
    baseline = load_baseline_report(baseline_report_path)
    evalset_by_id = load_evalset_by_sample_id(evalset_path)
    cases = [_openjudge_case(row, evalset_by_id.get(str(row.get("sample_id") or ""))) for row in baseline["results"]]
    provider = openjudge_results_provider or (
        lambda rows: _default_openjudge_results_provider(rows, max_concurrency=max_concurrency)
    )
    raw_openjudge_results = provider(cases)
    results = [
        _result_row(
            baseline_row=baseline_row,
            case=case,
            raw_results=raw_openjudge_results,
            index=index,
        )
        for index, (baseline_row, case) in enumerate(zip(baseline["results"], cases, strict=True))
    ]

    return {
        "report_name": "openjudge_answer_shadow_eval",
        "generated_at": datetime.now(UTC).isoformat(),
        "baseline_report_path": Path(baseline_report_path).as_posix(),
        "evalset_path": Path(evalset_path).as_posix() if evalset_path is not None else "",
        "scope": {
            "layer": "answer",
            "report_kind": "openjudge_shadow",
            "shadow_only": True,
            "changes_main_gate": False,
            "writes_back_to_baseline": False,
            "changes_runtime_config": False,
            "changes_default_retrieval_mode": False,
            "changes_query_rewrite_mode": False,
            "changes_rerank_enabled": False,
            "changes_answer_prompt": False,
            "uses_llm_as_judge": True,
            "judge_policy": "openjudge_shadow",
        },
        "openjudge": {
            "graders": list(GRADER_NAMES),
            "provider": "injected" if openjudge_results_provider is not None else "py-openjudge",
            "max_concurrency": max_concurrency,
        },
        "summary": _summary(results),
        "correlation_analysis": _correlation_analysis(results),
        "results": results,
        "note": "OpenJudge shadow scores do not affect deterministic pass/fail.",
    }


def write_openjudge_answer_shadow_report(
    *,
    output_json: str | Path = DEFAULT_OUTPUT_JSON,
    output_md: str | Path | None = None,
    baseline_report_path: str | Path = DEFAULT_BASELINE_REPORT,
    evalset_path: str | Path | None = DEFAULT_EVALSET,
    openjudge_results_provider: OpenJudgeResultsProvider | None = None,
    max_concurrency: int = 4,
) -> dict[str, Any]:
    report = build_openjudge_answer_shadow_report(
        baseline_report_path=baseline_report_path,
        evalset_path=evalset_path,
        openjudge_results_provider=openjudge_results_provider,
        max_concurrency=max_concurrency,
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
        "# OpenJudge Answer Shadow Eval",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Baseline report: `{report['baseline_report_path']}`",
        f"- Evalset: `{report['evalset_path']}`",
        f"- Total: `{summary['total']}`",
        f"- Deterministic status counts: `{summary['deterministic_status_counts']}`",
        f"- OpenJudge status counts: `{summary['openjudge_status_counts']}`",
        f"- Context text available: `{summary['context_text_available_count']}`",
        "",
        "## Gate Boundary",
        "",
        "Shadow scores do not affect pass/fail. The deterministic Answer hard gate remains the source of truth.",
        "",
        "## Correlation Analysis",
        "",
    ]
    for metric, graders in report["correlation_analysis"]["metrics"].items():
        lines.append(f"- {metric}: `{graders}`")
    lines.extend(
        [
            "",
            "## Samples",
            "",
            "| sample_id | deterministic | failure_category | relevance | hallucination | correctness | instruction_following |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in report["results"]:
        shadow = row["openjudge_shadow"]
        lines.append(
            "| {sample_id} | {status} | {failure_category} | {relevance} | {hallucination} | {correctness} | {instruction_following} |".format(
                sample_id=row["sample_id"],
                status=row["deterministic"]["status"],
                failure_category=row["deterministic"]["failure_category"],
                relevance=_score_for_markdown(shadow["relevance"]),
                hallucination=_score_for_markdown(shadow["hallucination"]),
                correctness=_score_for_markdown(shadow["correctness"]),
                instruction_following=_score_for_markdown(shadow["instruction_following"]),
            )
        )
    return "\n".join(lines) + "\n"


def _openjudge_case(
    baseline_row: dict[str, Any],
    evalset_row: dict[str, Any] | None,
) -> dict[str, Any]:
    sample_id = str(baseline_row.get("sample_id") or "")
    query = str(baseline_row.get("query") or (evalset_row or {}).get("query") or "")
    response = str(baseline_row.get("answer_text") or "")
    context = _context_text(baseline_row)
    reference_response = str(
        baseline_row.get("reference_answer") or (evalset_row or {}).get("reference_answer") or ""
    )
    instruction = (
        "请只基于检索上下文回答用户问题，覆盖关键事实，避免编造，并在关键事实后给出来源引用。"
    )
    warnings = []
    if not response:
        warnings.append("answer_text_missing")
    if not context:
        warnings.append("context_text_missing")
    if not reference_response:
        warnings.append("reference_answer_missing")

    return {
        "sample_id": sample_id,
        "query": query,
        "response": response,
        "answer": response,
        "context": context,
        "reference_response": reference_response,
        "reference_answer": reference_response,
        "instruction": instruction,
        "input_warnings": warnings,
        "has_context_text": bool(context),
        "has_reference_answer": bool(reference_response),
    }


def _context_text(row: dict[str, Any]) -> str:
    if isinstance(row.get("context_text"), str):
        return str(row["context_text"])
    retrieval = row.get("retrieval")
    if isinstance(retrieval, dict) and isinstance(retrieval.get("context_text"), str):
        return str(retrieval["context_text"])
    return ""


def _result_row(
    *,
    baseline_row: dict[str, Any],
    case: dict[str, Any],
    raw_results: dict[str, list[Any]],
    index: int,
) -> dict[str, Any]:
    gate = baseline_row.get("gate") if isinstance(baseline_row.get("gate"), dict) else {}
    deterministic = {
        "status": str(baseline_row.get("status") or "unknown"),
        "failure_category": str(baseline_row.get("failure_category") or ""),
        "hard_gate_passed": bool(gate.get("hard_gate_passed")),
        "answer_missing_facts": int(gate.get("answer_missing_fact_count") or 0),
        "unsupported_claim_count": int(gate.get("unsupported_claim_count") or 0),
        "context_missing_facts": int(gate.get("context_missing_fact_count") or 0),
        "citation_required_but_missing": int(gate.get("citation_required_but_missing") or 0),
        "permission_leak_count": int(gate.get("permission_leak_count") or 0),
        "source_ref_unresolvable_count": int(gate.get("source_ref_unresolvable_count") or 0),
    }
    return {
        "sample_id": case["sample_id"],
        "query": case["query"],
        "deterministic": deterministic,
        "input_warnings": list(case["input_warnings"]),
        "input": {
            "has_answer_text": bool(case["response"]),
            "has_context_text": bool(case["context"]),
            "has_reference_answer": bool(case["reference_response"]),
            "answer_text_chars": len(case["response"]),
            "context_text_chars": len(case["context"]),
            "reference_answer_chars": len(case["reference_response"]),
        },
        "openjudge_shadow": {
            grader: _normalize_grader_result(
                _raw_result_for(raw_results, grader, index),
                grader=grader,
                has_context_text=case["has_context_text"],
                has_reference_answer=case["has_reference_answer"],
            )
            for grader in GRADER_NAMES
        },
    }


def _raw_result_for(raw_results: dict[str, list[Any]], grader: str, index: int) -> Any:
    values = raw_results.get(grader) or []
    if index >= len(values):
        return {
            "name": grader,
            "status": "not_ready",
            "error": f"OpenJudge provider returned no {grader} result for index {index}",
        }
    return values[index]


def _normalize_grader_result(
    raw: Any,
    *,
    grader: str,
    has_context_text: bool,
    has_reference_answer: bool,
) -> dict[str, Any]:
    payload = _model_dump(raw)
    error = payload.get("error") or payload.get("exception")
    score = payload.get("score")
    status = "scored" if error in {None, ""} and score is not None else "not_ready"
    confidence = "normal"
    if grader in CONTEXT_DEPENDENT_GRADERS and not has_context_text:
        confidence = "low"
    if grader in REFERENCE_DEPENDENT_GRADERS and not has_reference_answer:
        confidence = "low"
    normalized = {
        "status": status,
        "score": float(score) if score is not None else None,
        "reason": str(payload.get("reason") or ""),
        "confidence": confidence,
    }
    if error:
        normalized["error"] = str(error)
    metadata = payload.get("metadata")
    if isinstance(metadata, dict) and metadata:
        normalized["metadata"] = metadata
    return normalized


def _model_dump(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if hasattr(raw, "model_dump"):
        return dict(raw.model_dump(mode="json"))
    payload: dict[str, Any] = {}
    for field in ("name", "score", "reason", "metadata", "error"):
        if hasattr(raw, field):
            payload[field] = getattr(raw, field)
    return payload


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    deterministic_status_counts = dict(Counter(row["deterministic"]["status"] for row in results))
    openjudge_status_counts = {
        grader: dict(Counter(row["openjudge_shadow"][grader]["status"] for row in results))
        for grader in GRADER_NAMES
    }
    return {
        "total": len(results),
        "deterministic_status_counts": deterministic_status_counts,
        "openjudge_status_counts": openjudge_status_counts,
        "context_text_available_count": sum(1 for row in results if row["input"]["has_context_text"]),
        "reference_answer_available_count": sum(
            1 for row in results if row["input"]["has_reference_answer"]
        ),
        "shadow_scores_affect_pass_fail": False,
    }


def _correlation_analysis(results: list[dict[str, Any]]) -> dict[str, Any]:
    deterministic_metrics = {
        "answer_missing_facts": [
            float(row["deterministic"]["answer_missing_facts"]) for row in results
        ],
        "unsupported_claim_count": [
            float(row["deterministic"]["unsupported_claim_count"]) for row in results
        ],
        "context_missing_facts": [
            float(row["deterministic"]["context_missing_facts"]) for row in results
        ],
    }
    metrics: dict[str, dict[str, float | None]] = {}
    for metric, values in deterministic_metrics.items():
        metrics[metric] = {}
        for grader in GRADER_NAMES:
            scores = [row["openjudge_shadow"][grader]["score"] for row in results]
            metrics[metric][grader] = _pearson(scores, values)
    return {
        "method": "pearson",
        "metrics": metrics,
        "note": "Correlation is diagnostic only and never changes deterministic pass/fail.",
    }


def _pearson(scores: list[float | None], values: list[float]) -> float | None:
    paired = [(float(score), value) for score, value in zip(scores, values, strict=True) if score is not None]
    if len(paired) < 2:
        return None
    xs = [item[0] for item in paired]
    ys = [item[1] for item in paired]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    x_var = sum((x - x_mean) ** 2 for x in xs)
    y_var = sum((y - y_mean) ** 2 for y in ys)
    if x_var == 0 or y_var == 0:
        return None
    covariance = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True))
    return round(covariance / math.sqrt(x_var * y_var), 4)


def _score_for_markdown(result: dict[str, Any]) -> str:
    score = result.get("score")
    return "-" if score is None else str(score)


def _default_openjudge_results_provider(
    cases: list[dict[str, Any]],
    *,
    max_concurrency: int = 4,
) -> dict[str, list[Any]]:
    try:
        from openjudge.graders.common import (  # type: ignore[import-not-found]
            CorrectnessGrader,
            HallucinationGrader,
            InstructionFollowingGrader,
            RelevanceGrader,
        )
        from openjudge.models import OpenAIChatModel  # type: ignore[import-not-found]
        from openjudge.runner.grading_runner import GradingRunner  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001 - shadow report must capture optional dependency gaps
        return _not_ready_results(cases, f"py-openjudge import failed: {type(exc).__name__}: {exc}")

    if not config.dashscope_api_key:
        return _not_ready_results(cases, "DASHSCOPE_API_KEY is not configured for OpenJudge shadow eval")

    model = OpenAIChatModel(
        model=config.rag_model,
        api_key=config.dashscope_api_key,
        base_url=config.dashscope_api_base,
        timeout=45,
        temperature=0.0,
    )
    grader_configs = {
        "relevance": {
            "grader": RelevanceGrader(model=model, language="zh"),
            "mapper": {
                "query": "query",
                "response": "response",
                "context": "context",
                "reference_response": "reference_response",
            },
        },
        "hallucination": {
            "grader": HallucinationGrader(model=model, language="zh"),
            "mapper": {
                "query": "query",
                "response": "response",
                "context": "context",
                "reference_response": "reference_response",
            },
        },
        "correctness": {
            "grader": CorrectnessGrader(model=model, language="zh"),
            "mapper": {
                "query": "query",
                "response": "response",
                "context": "context",
                "reference_response": "reference_response",
            },
        },
        "instruction_following": {
            "grader": InstructionFollowingGrader(model=model, language="zh"),
            "mapper": {
                "instruction": "instruction",
                "response": "response",
                "query": "query",
            },
        },
    }

    async def _run() -> dict[str, list[Any]]:
        runner = GradingRunner(
            grader_configs=grader_configs,
            max_concurrency=max_concurrency,
            show_progress=False,
        )
        return await runner.arun(cases)

    try:
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 - keep shadow failure out of main gate
        return _not_ready_results(cases, f"OpenJudge shadow run failed: {type(exc).__name__}: {exc}")


def _not_ready_results(cases: list[dict[str, Any]], error: str) -> dict[str, list[dict[str, Any]]]:
    return {
        grader: [
            {
                "name": grader,
                "status": "not_ready",
                "error": error,
                "reason": error,
            }
            for _ in cases
        ]
        for grader in GRADER_NAMES
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run OpenJudge Answer-layer shadow eval.")
    parser.add_argument("--baseline-report", default=DEFAULT_BASELINE_REPORT)
    parser.add_argument("--evalset", required=False, default=DEFAULT_EVALSET)
    parser.add_argument("--output-json", "--output", dest="output_json", default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", default="")
    parser.add_argument("--max-concurrency", type=int, default=4)
    args = parser.parse_args()

    write_openjudge_answer_shadow_report(
        output_json=args.output_json,
        output_md=args.output_md or None,
        baseline_report_path=args.baseline_report,
        evalset_path=args.evalset,
        max_concurrency=args.max_concurrency,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
