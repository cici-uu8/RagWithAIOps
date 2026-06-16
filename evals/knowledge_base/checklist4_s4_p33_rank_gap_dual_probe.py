"""Checklist 4 S4-P3.3 rank-gap dual probe: expression-gap rewrite + sparse/hybrid.

Phase 1: Hand-rewrite 8 rank_gap queries to test if expression-gap exists
Phase 2: Run sparse/hybrid on all 9 failed samples to test Benefit-B candidates

This is observation-only, does not create formal evalsets, does not change defaults.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.models import RetrievalMode
from evals.knowledge_base.retrieval_mode_comparison_report import (
    build_retrieval_mode_comparison_report,
)
from evals.knowledge_base.run_department_rag_eval import load_evalset

# 8 rank_gap samples + 1 confirmed expression_gap = 9 failed samples
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

EXPRESSION_GAP_SAMPLE_IDS = ["S4M-E-010"]

ALL_FAILED_SAMPLE_IDS = RANK_GAP_SAMPLE_IDS + EXPRESSION_GAP_SAMPLE_IDS


# Hand-crafted standard rewrites for the 8 rank_gap samples
HAND_REWRITE_MAP = {
    "S4M-A-012": "CPUThrottlingHigh 告警处理时机判断",
    "S4M-B-001": "PagerDuty incident response training 培训内容",
    "S4M-B-008": "Scoutflo SRE Playbooks 支持的平台和使用场景",
    "S4M-B-009": "Scoutflo Kubernetes playbook 主题覆盖范围",
    "S4M-C-003": "Unreliability Budgets 预算定义在第几页",
    "S4M-D-001": "Scoutflo 表格中 KubePodCrashLooping 对应的 playbook",
    "S4M-E-004": "页面响应慢排查步骤",
    "S4M-E-006": "CPU throttling 高是否应该增加 limit",
}


def run_dual_probe(
    *,
    evalset_path: str | Path,
    report_path: str | Path,
) -> dict[str, Any]:
    """Run dual probe: expression-gap rewrite + sparse/hybrid."""
    evalset_path = Path(evalset_path)
    samples = load_evalset(evalset_path)
    sample_map = {s["sample_id"]: s for s in samples}

    # Phase 1: Expression-gap rewrite probe on 8 rank_gap samples
    rewrite_results = []
    for sample_id in RANK_GAP_SAMPLE_IDS:
        sample = sample_map.get(sample_id)
        if not sample:
            continue

        original_query = sample["query"]
        rewrite_query = HAND_REWRITE_MAP.get(sample_id, original_query)

        # Create a temp rewrite sample
        rewrite_sample = sample.copy()
        rewrite_sample["query"] = rewrite_query
        rewrite_sample["sample_id"] = f"{sample_id}_rewrite"

        # Run dense-only comparison
        comparison_original = build_retrieval_mode_comparison_report(
            samples=[sample],
            modes=[RetrievalMode.DENSE_ONLY],
            retrieval_service=None,
        )

        comparison_rewrite = build_retrieval_mode_comparison_report(
            samples=[rewrite_sample],
            modes=[RetrievalMode.DENSE_ONLY],
            retrieval_service=None,
        )

        original_result = comparison_original["samples"][0]["dense_only"]
        rewrite_result = comparison_rewrite["samples"][0]["dense_only"]

        expected_doc_id = sample["expected_doc_ids"][0] if sample.get("expected_doc_ids") else None

        original_doc_ids = original_result.get("doc_ids", [])
        rewrite_doc_ids = rewrite_result.get("doc_ids", [])

        original_rank = _get_rank(expected_doc_id, original_doc_ids)
        rewrite_rank = _get_rank(expected_doc_id, rewrite_doc_ids)

        verdict = _classify_rewrite_verdict(original_rank, rewrite_rank)

        rewrite_results.append({
            "sample_id": sample_id,
            "original_query": original_query,
            "rewrite_query": rewrite_query,
            "expected_doc_id": expected_doc_id,
            "original_rank": original_rank,
            "rewrite_rank": rewrite_rank,
            "verdict": verdict,
            "original_doc_ids": list(dict.fromkeys(original_doc_ids))[:3],
            "rewrite_doc_ids": list(dict.fromkeys(rewrite_doc_ids))[:3],
        })

    # Phase 2: Sparse/hybrid probe on all 9 failed samples
    failed_samples = [sample_map[sid] for sid in ALL_FAILED_SAMPLE_IDS if sid in sample_map]

    comparison = build_retrieval_mode_comparison_report(
        samples=failed_samples,
        modes=[RetrievalMode.DENSE_ONLY, RetrievalMode.SPARSE_ONLY, RetrievalMode.HYBRID],
        retrieval_service=None,
    )

    sparse_hybrid_results = []
    for row in comparison["samples"]:
        sample_id = row["sample_id"]
        sample = sample_map.get(sample_id)
        if not sample:
            continue

        expected_doc_id = sample["expected_doc_ids"][0] if sample.get("expected_doc_ids") else None

        dense_result = row.get("dense_only", {})
        sparse_result = row.get("sparse_only", )
        hybrid_result = row.get("hybrid", {})

        dense_doc_ids = dense_result.get("doc_ids", [])
        sparse_doc_ids = sparse_result.get("doc_ids", [])
        hybrid_doc_ids = hybrid_result.get("doc_ids", [])

        dense_rank = _get_rank(expected_doc_id, dense_doc_ids)
        sparse_rank = _get_rank(expected_doc_id, sparse_doc_ids)
        hybrid_rank = _get_rank(expected_doc_id, hybrid_doc_ids)

        benefit_b_verdict = _classify_benefit_b_verdict(dense_rank, sparse_rank, hybrid_rank)

        sparse_hybrid_results.append({
            "sample_id": sample_id,
            "query": sample["query"],
            "expected_doc_id": expected_doc_id,
            "dense_rank": dense_rank,
            "sparse_rank": sparse_rank,
            "hybrid_rank": hybrid_rank,
            "benefit_b_verdict": benefit_b_verdict,
            "dense_doc_ids": list(dict.fromkeys(dense_doc_ids))[:3],
            "sparse_doc_ids": list(dict.fromkeys(sparse_doc_ids))[:3],
            "hybrid_doc_ids": list(dict.fromkeys(hybrid_doc_ids))[:3],
        })

    # Summarize
    rewrite_verdicts = Counter(r["verdict"] for r in rewrite_results)
    benefit_b_verdicts = Counter(r["benefit_b_verdict"] for r in sparse_hybrid_results)

    report = {
        "probe_name": "checklist4_s4_p33_rank_gap_dual_probe",
        "generated_at": datetime.now(UTC).isoformat(),
        "phase_1_expression_gap_rewrite": {
            "candidate_count": len(rewrite_results),
            "rewrite_lift_proven": rewrite_verdicts.get("rewrite_lift_proven", 0),
            "rewrite_observation_only": rewrite_verdicts.get("rewrite_observation_only", 0),
            "no_rewrite_lift": rewrite_verdicts.get("no_rewrite_lift", 0),
            "results": rewrite_results,
        },
        "phase_2_sparse_hybrid_benefit_b": {
            "candidate_count": len(sparse_hybrid_results),
            "sparse_lift_proven": benefit_b_verdicts.get("sparse_lift_proven", 0),
            "hybrid_lift_proven": benefit_b_verdicts.get("hybrid_lift_proven", 0),
            "observation_only": benefit_b_verdicts.get("observation_only", 0),
            "no_lift": benefit_b_verdicts.get("no_lift", 0),
            "results": sparse_hybrid_results,
        },
        "conclusion": {
            "expression_gap_new_confirmed": rewrite_verdicts.get("rewrite_lift_proven", 0),
            "benefit_b_new_confirmed": benefit_b_verdicts.get("sparse_lift_proven", 0) + benefit_b_verdicts.get("hybrid_lift_proven", 0),
            "expression_gap_eligible_for_formal_evalset": rewrite_verdicts.get("rewrite_lift_proven", 0) >= 3,
            "benefit_b_eligible_for_formal_evalset": (benefit_b_verdicts.get("sparse_lift_proven", 0) + benefit_b_verdicts.get("hybrid_lift_proven", 0)) >= 3,
        },
    }

    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return report


def _get_rank(expected_doc_id: str | None, doc_ids: list[str]) -> int:
    """Get rank of expected doc in results (1-indexed), 0 if not found."""
    if not expected_doc_id:
        return 0
    try:
        return doc_ids.index(expected_doc_id) + 1
    except ValueError:
        return 0


def _classify_rewrite_verdict(original_rank: int, rewrite_rank: int) -> str:
    """Classify rewrite verdict."""
    if rewrite_rank > 0 and rewrite_rank <= 3 and (original_rank == 0 or original_rank > 3 or rewrite_rank < original_rank):
        return "rewrite_lift_proven"
    elif rewrite_rank > 0 and rewrite_rank <= 3:
        return "rewrite_observation_only"
    else:
        return "no_rewrite_lift"


def _classify_benefit_b_verdict(dense_rank: int, sparse_rank: int, hybrid_rank: int) -> str:
    """Classify Benefit-B verdict."""
    if (dense_rank == 0 or dense_rank > 3) and sparse_rank > 0 and sparse_rank <= 3:
        return "sparse_lift_proven"
    elif (dense_rank == 0 or dense_rank > 3) and hybrid_rank > 0 and hybrid_rank <= 3:
        return "hybrid_lift_proven"
    elif (sparse_rank > 0 and sparse_rank <= 3) or (hybrid_rank > 0 and hybrid_rank <= 3):
        return "observation_only"
    else:
        return "no_lift"


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Checklist 4 S4-P3.3 rank-gap dual probe")
    parser.add_argument(
        "--evalset",
        default="evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_50q.jsonl",
    )
    parser.add_argument(
        "--output",
        default="evals/knowledge_base/reports/checklist4_s4_p33_rank_gap_dual_probe_20260611.json",
    )
    args = parser.parse_args()

    report = run_dual_probe(
        evalset_path=args.evalset,
        report_path=args.output,
    )

    print(f"Dual probe complete: {args.output}")
    print(f"Phase 1 expression-gap rewrite: {report['phase_1_expression_gap_rewrite']['rewrite_lift_proven']} proven")
    print(f"Phase 2 sparse/hybrid Benefit-B: {report['conclusion']['benefit_b_new_confirmed']} proven")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
