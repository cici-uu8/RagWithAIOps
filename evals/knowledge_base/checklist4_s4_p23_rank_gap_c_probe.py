"""Checklist 4 S4-P2.3 observation-only rank-gap C-probe report.

This probe only inspects the 8 residual ``rank_gap`` samples from the repaired
mixed 50q evalset. It temporarily enables rerank inside the process, runs a
three-mode comparison (dense_only / hybrid / hybrid_rerank), and classifies
whether rerank provides formal value for the expected document ranks.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.models import RetrievalMode
from app.services.rerank_service import rerank_service
from evals.knowledge_base.retrieval_mode_comparison_report import (
    build_retrieval_mode_comparison_report,
)
from evals.knowledge_base.run_department_rag_eval import load_evalset

DEFAULT_EVALSET_PATH = "<local-approved-evalset>"
RANK_GAP_SAMPLE_IDS = [
    "S4M-A-012",
    "S4M-B-001",
    "S4M-B-008",
    "S4M-B-009",
    "S4M-C-003",
    "S4M-D-001",
    "S4M-E-004",
    "S4M-E-006",
]
DEFAULT_MODES = [
    RetrievalMode.DENSE_ONLY,
    RetrievalMode.HYBRID,
    RetrievalMode.HYBRID_RERANK,
]


def build_rank_gap_c_probe_report(
    *,
    evalset_path: str | Path = DEFAULT_EVALSET_PATH,
    sample_ids: list[str] | None = None,
    retrieval_service=None,
    min_effective_samples: int = 6,
    enable_true_rerank: bool = True,
) -> dict[str, Any]:
    evalset = load_evalset(evalset_path)
    selected_sample_ids = list(sample_ids or RANK_GAP_SAMPLE_IDS)
    selected_samples = _filter_samples(evalset, selected_sample_ids)
    sample_by_id = {str(sample["sample_id"]): sample for sample in selected_samples}

    comparison = _run_three_mode_comparison(
        selected_samples,
        retrieval_service=retrieval_service,
        enable_true_rerank=enable_true_rerank,
    )

    rows = [
        _classify_rank_gap_candidate(
            row,
            expected_doc_ids={str(doc_id) for doc_id in sample_by_id[row["sample_id"]].get("expected_doc_ids", [])},
            top_k=int(sample_by_id[row["sample_id"]].get("top_k") or 3),
        )
        for row in comparison["samples"]
    ]
    counts = Counter(row["verdict"] for row in rows)
    guardrail_clean = _guardrail_clean(comparison)
    true_rerank_applied = _count_rerank_status(comparison, "applied") > 0
    rank_lift_proven_count = int(counts.get("rank_lift_proven") or 0)
    eligible_for_formal_evalset = (
        rank_lift_proven_count >= min_effective_samples and guardrail_clean and true_rerank_applied
    )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "probe_name": "checklist4_s4_p23_rank_gap_c_probe",
        "status": "formal_value_proven" if eligible_for_formal_evalset else "observation_only",
        "scope": {
            "phase": "S4-P2.3",
            "report_kind": "rank_gap_c_probe",
            "evalset_path": Path(evalset_path).as_posix(),
            "candidate_sample_ids": selected_sample_ids,
            "candidate_count": len(selected_samples),
            "creates_formal_evalsets": False,
            "changes_app_config": False,
            "changes_default_retrieval_mode": False,
            "changes_query_rewrite_mode": False,
            "changes_runtime_rerank_default": False,
            "temporary_rerank_enablement": bool(enable_true_rerank),
        },
        "candidate_count": len(selected_samples),
        "rank_lift_proven_count": rank_lift_proven_count,
        "rank_observation_only_count": int(counts.get("rank_observation_only") or 0),
        "no_rank_lift_count": int(counts.get("no_rank_lift") or 0),
        "min_effective_samples": min_effective_samples,
        "guardrail_clean": guardrail_clean,
        "true_rerank_requested": bool(enable_true_rerank),
        "true_rerank_applied": true_rerank_applied,
        "eligible_for_formal_evalset": eligible_for_formal_evalset,
        "verdict_counts": dict(counts),
        "comparison_summary": comparison["summary"],
        "samples": rows,
        "decisions": {
            "create_formal_evalset": eligible_for_formal_evalset,
            "default_switch_eligibility": "not_eligible_for_default_switch",
            "query_rewrite_shadow_status": "deferred_until_expression_gap_expansion",
        },
    }


def write_rank_gap_c_probe_report(
    *,
    output_json: str | Path,
    output_md: str | Path | None = None,
    evalset_path: str | Path = DEFAULT_EVALSET_PATH,
    sample_ids: list[str] | None = None,
    retrieval_service=None,
    min_effective_samples: int = 6,
    enable_true_rerank: bool = True,
) -> dict[str, Any]:
    report = build_rank_gap_c_probe_report(
        evalset_path=evalset_path,
        sample_ids=sample_ids,
        retrieval_service=retrieval_service,
        min_effective_samples=min_effective_samples,
        enable_true_rerank=enable_true_rerank,
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
        "# Checklist 4 S4-P2.3 Rank-Gap C-Probe Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Status: `{report['status']}`",
        f"- Rank-lift proven: `{report['rank_lift_proven_count']}`",
        f"- Rank observation only: `{report['rank_observation_only_count']}`",
        f"- No rank lift: `{report['no_rank_lift_count']}`",
        f"- Eligible for formal evalset: `{report['eligible_for_formal_evalset']}`",
        f"- Default switch eligibility: `{report['decisions']['default_switch_eligibility']}`",
        "",
        "| sample_id | verdict | dense_rank | hybrid_rank | hybrid_rerank_rank | reason |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in report["samples"]:
        lines.append(
            "| {sample_id} | {verdict} | {dense_rank} | {hybrid_rank} | {rerank_rank} | {reason} |".format(
                sample_id=row["candidate_id"],
                verdict=row["verdict"],
                dense_rank=_display_rank(row["dense_rank"]),
                hybrid_rank=_display_rank(row["hybrid_rank"]),
                rerank_rank=_display_rank(row["hybrid_rerank_rank"]),
                reason=row["reason"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def _run_three_mode_comparison(
    samples: list[dict[str, Any]],
    *,
    retrieval_service,
    enable_true_rerank: bool,
) -> dict[str, Any]:
    original_enabled = rerank_service.enabled
    try:
        if enable_true_rerank:
            rerank_service.enabled = True
        return build_retrieval_mode_comparison_report(
            samples,
            retrieval_service=retrieval_service,
            modes=DEFAULT_MODES,
        )
    finally:
        rerank_service.enabled = original_enabled


def _filter_samples(
    evalset: list[dict[str, Any]],
    sample_ids: list[str],
) -> list[dict[str, Any]]:
    sample_by_id = {str(sample["sample_id"]): sample for sample in evalset}
    missing = [sample_id for sample_id in sample_ids if sample_id not in sample_by_id]
    if missing:
        raise ValueError(f"rank-gap samples missing from evalset: {missing}")
    return [sample_by_id[sample_id] for sample_id in sample_ids]


def _classify_rank_gap_candidate(
    row: dict[str, Any],
    *,
    expected_doc_ids: set[str],
    top_k: int,
) -> dict[str, Any]:
    dense_rank = _first_expected_doc_rank(row["dense_only"], expected_doc_ids)
    hybrid_rank = _first_expected_doc_rank(row["hybrid"], expected_doc_ids)
    hybrid_rerank_rank = _first_expected_doc_rank(row["hybrid_rerank"], expected_doc_ids)
    status_counts = _result_metadata_counts(row["hybrid_rerank"], "rerank_status")
    applied = int(status_counts.get("applied") or 0) > 0

    recovered_into_top_k = hybrid_rank is None and hybrid_rerank_rank is not None and hybrid_rerank_rank <= top_k
    improved_rank = (
        hybrid_rank is not None
        and hybrid_rerank_rank is not None
        and hybrid_rerank_rank < hybrid_rank
    )
    rerank_within_top_k = hybrid_rerank_rank is not None and hybrid_rerank_rank <= top_k

    if applied and (recovered_into_top_k or improved_rank):
        verdict = "rank_lift_proven"
        reason = "true_rerank_promoted_expected_doc"
    elif rerank_within_top_k:
        verdict = "rank_observation_only"
        reason = "expected_doc_stayed_within_top_k_but_rerank_did_not_improve_rank"
    else:
        verdict = "no_rank_lift"
        reason = "true_rerank_did_not_move_expected_doc_into_top_k"

    return {
        "candidate_id": row["sample_id"],
        "query": row["query"],
        "expected_doc_ids": sorted(expected_doc_ids),
        "dense_rank": dense_rank,
        "hybrid_rank": hybrid_rank,
        "hybrid_rerank_rank": hybrid_rerank_rank,
        "hybrid_rerank_status_counts": dict(status_counts),
        "rank_lift_proven": verdict == "rank_lift_proven",
        "rank_observation_only": verdict == "rank_observation_only",
        "no_rank_lift": verdict == "no_rank_lift",
        "verdict": verdict,
        "reason": reason,
    }


def _first_expected_doc_rank(mode_result: dict[str, Any], expected_doc_ids: set[str]) -> int | None:
    for index, doc_id in enumerate(mode_result.get("doc_ids", []), start=1):
        if doc_id in expected_doc_ids:
            return index
    return None


def _guardrail_clean(comparison: dict[str, Any]) -> bool:
    summary = comparison.get("summary") or {}
    return (
        int(summary.get("not_ready_count") or 0) == 0
        and int(summary.get("wrong_scope_count") or 0) == 0
        and int(summary.get("citation_incomplete_count") or 0) == 0
    )


def _count_rerank_status(comparison: dict[str, Any], status: str) -> int:
    counts = (
        comparison.get("summary", {})
        .get("rerank_status_counts_by_mode", {})
        .get("hybrid_rerank", {})
    )
    return int(counts.get(status) or 0)


def _result_metadata_counts(mode_result: dict[str, Any], key: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    for result in mode_result.get("results", []):
        value = (result.get("metadata") or {}).get(key)
        if value:
            counter[str(value)] += 1
    return counter


def _display_rank(value: int | None) -> str:
    return "-" if value is None else str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the S4-P2.3 rank-gap C-probe")
    parser.add_argument("--evalset", default=DEFAULT_EVALSET_PATH)
    parser.add_argument(
        "--sample-ids",
        nargs="*",
        default=None,
        help="Optional explicit rank-gap sample ids; defaults to the 8 residual samples.",
    )
    parser.add_argument("--min-effective-samples", type=int, default=6)
    parser.add_argument("--no-true-rerank", action="store_true")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default=None)
    args = parser.parse_args(argv)

    write_rank_gap_c_probe_report(
        evalset_path=args.evalset,
        sample_ids=args.sample_ids,
        output_json=args.output_json,
        output_md=args.output_md,
        min_effective_samples=args.min_effective_samples,
        enable_true_rerank=not args.no_true_rerank,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
