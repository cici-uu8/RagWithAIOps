"""Checklist 3 P2.6 Benefit-B/C shadow probe report.

The report reads the P2.6 candidate markdown, probes Benefit-B and Benefit-C
without creating formal evalsets, and keeps runtime defaults unchanged.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.models import RetrievalMode
from app.services.rerank_service import rerank_service
from evals.knowledge_base.retrieval_mode_comparison_report import (
    build_retrieval_mode_comparison_report,
)

DEFAULT_CANDIDATE_DOC_PATH = "docs/RAG_PDF_Memory_P2.6_evalset候选样本草案.md"
DEFAULT_MODES = [
    RetrievalMode.DENSE_ONLY,
    RetrievalMode.SPARSE_ONLY,
    RetrievalMode.HYBRID,
    RetrievalMode.HYBRID_RERANK,
]


def build_p26_bc_shadow_probe_report(
    *,
    candidate_doc_path: str | Path = DEFAULT_CANDIDATE_DOC_PATH,
    retrieval_service=None,
    min_effective_samples: int = 10,
    enable_true_rerank_for_c: bool = True,
) -> dict[str, Any]:
    candidate_doc_path = Path(candidate_doc_path)
    candidate_groups = load_bc_candidates(candidate_doc_path)

    b_comparison = build_retrieval_mode_comparison_report(
        candidate_groups["benefit_b"],
        retrieval_service=retrieval_service,
        modes=DEFAULT_MODES,
    )
    benefit_b = _benefit_b_summary(
        b_comparison,
        expected_doc_ids_by_sample=_expected_doc_ids_by_sample(candidate_groups["benefit_b"]),
        min_effective_samples=min_effective_samples,
    )

    c_comparison = _run_c_comparison(
        candidate_groups["benefit_c"],
        retrieval_service=retrieval_service,
        enable_true_rerank_for_c=enable_true_rerank_for_c,
    )
    benefit_c = _benefit_c_summary(
        c_comparison,
        expected_doc_ids_by_sample=_expected_doc_ids_by_sample(candidate_groups["benefit_c"]),
        min_effective_samples=min_effective_samples,
        enable_true_rerank_for_c=enable_true_rerank_for_c,
    )

    blockers = _blockers(benefit_b, benefit_c)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": _status(benefit_b, benefit_c, blockers),
        "scope": {
            "phase": "S3-P2.6",
            "report_kind": "benefit_b_c_shadow_probe",
            "candidate_doc_path": candidate_doc_path.as_posix(),
            "creates_formal_evalsets": False,
            "changes_app_config": False,
            "changes_default_retrieval_mode": False,
            "changes_query_rewrite_mode": False,
            "changes_runtime_rerank_default": False,
            "true_rerank_for_c_process_only": enable_true_rerank_for_c,
        },
        "candidate_counts": {
            "benefit_b": len(candidate_groups["benefit_b"]),
            "benefit_c": len(candidate_groups["benefit_c"]),
        },
        "benefit_b": benefit_b,
        "benefit_c": benefit_c,
        "decisions": {
            "create_benefit_b_formal_evalset": benefit_b["eligible_for_formal_evalset"],
            "create_benefit_c_formal_evalset": benefit_c["eligible_for_formal_evalset"],
            "default_switch_eligibility": "not_eligible_for_default_switch",
            "query_rewrite_shadow_status": "deferred_until_retrieval_failure_evidence",
        },
        "blockers": blockers,
    }


def write_p26_bc_shadow_probe_report(
    *,
    output_json: str | Path,
    output_md: str | Path | None = None,
    candidate_doc_path: str | Path = DEFAULT_CANDIDATE_DOC_PATH,
    retrieval_service=None,
    min_effective_samples: int = 10,
    enable_true_rerank_for_c: bool = True,
) -> dict[str, Any]:
    report = build_p26_bc_shadow_probe_report(
        candidate_doc_path=candidate_doc_path,
        retrieval_service=retrieval_service,
        min_effective_samples=min_effective_samples,
        enable_true_rerank_for_c=enable_true_rerank_for_c,
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


def load_bc_candidates(candidate_doc_path: str | Path) -> dict[str, list[dict[str, Any]]]:
    text = Path(candidate_doc_path).read_text(encoding="utf-8")
    return {
        "benefit_b": _parse_candidate_section(text, "P26-B-"),
        "benefit_c": _parse_candidate_section(text, "P26-C-"),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Checklist 3 P2.6 Benefit-B/C Shadow Probe Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Status: `{report['status']}`",
        f"- Benefit-B effective lift: `{report['benefit_b']['effective_lift_count']}`",
        f"- Benefit-C effective rank lift: `{report['benefit_c']['effective_rank_lift_count']}`",
        f"- Create Benefit-B formal evalset: `{report['decisions']['create_benefit_b_formal_evalset']}`",
        f"- Create Benefit-C formal evalset: `{report['decisions']['create_benefit_c_formal_evalset']}`",
        f"- Default switch eligibility: `{report['decisions']['default_switch_eligibility']}`",
        "",
        "## Benefit-B",
        "",
        "| candidate_id | verdict | dense_rank | sparse_rank | hybrid_rank | reason |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in report["benefit_b"]["candidates"]:
        lines.append(
            "| {candidate_id} | {verdict} | {dense_rank} | {sparse_rank} | {hybrid_rank} | {reason} |".format(
                candidate_id=row["candidate_id"],
                verdict=row["verdict"],
                dense_rank=_display_rank(row["dense_rank"]),
                sparse_rank=_display_rank(row["sparse_rank"]),
                hybrid_rank=_display_rank(row["hybrid_rank"]),
                reason=row["reason"],
            )
        )

    lines.extend(
        [
            "",
            "## Benefit-C",
            "",
            "| candidate_id | verdict | hybrid_rank | true_rerank_rank | rerank_status | reason |",
            "|---|---|---:|---:|---|---|",
        ]
    )
    for row in report["benefit_c"]["candidates"]:
        lines.append(
            "| {candidate_id} | {verdict} | {hybrid_rank} | {rerank_rank} | {statuses} | {reason} |".format(
                candidate_id=row["candidate_id"],
                verdict=row["verdict"],
                hybrid_rank=_display_rank(row["hybrid_rank"]),
                rerank_rank=_display_rank(row["hybrid_rerank_rank"]),
                statuses=row["hybrid_rerank_status_counts"],
                reason=row["reason"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def _run_c_comparison(
    samples: list[dict[str, Any]],
    *,
    retrieval_service,
    enable_true_rerank_for_c: bool,
) -> dict[str, Any]:
    original_enabled = rerank_service.enabled
    try:
        if enable_true_rerank_for_c:
            rerank_service.enabled = True
        return build_retrieval_mode_comparison_report(
            samples,
            retrieval_service=retrieval_service,
            modes=DEFAULT_MODES,
        )
    finally:
        rerank_service.enabled = original_enabled


def _benefit_b_summary(
    comparison: dict[str, Any],
    *,
    expected_doc_ids_by_sample: dict[str, set[str]],
    min_effective_samples: int,
) -> dict[str, Any]:
    rows = [
        _classify_b_candidate(
            row,
            expected_doc_ids=expected_doc_ids_by_sample.get(row["sample_id"], set()),
        )
        for row in comparison["samples"]
    ]
    effective = [row for row in rows if row["lift_proven"]]
    guardrail_clean = _guardrail_clean(comparison)
    return {
        "candidate_count": len(rows),
        "effective_lift_count": len(effective),
        "min_effective_samples": min_effective_samples,
        "eligible_for_formal_evalset": len(effective) >= min_effective_samples and guardrail_clean,
        "downgrade_to": (
            "" if len(effective) >= min_effective_samples else "lexical_lift_observation_report"
        ),
        "guardrail_clean": guardrail_clean,
        "comparison_summary": comparison["summary"],
        "candidates": rows,
    }


def _benefit_c_summary(
    comparison: dict[str, Any],
    *,
    expected_doc_ids_by_sample: dict[str, set[str]],
    min_effective_samples: int,
    enable_true_rerank_for_c: bool,
) -> dict[str, Any]:
    rows = [
        _classify_c_candidate(
            row,
            expected_doc_ids=expected_doc_ids_by_sample.get(row["sample_id"], set()),
        )
        for row in comparison["samples"]
    ]
    effective = [row for row in rows if row["rank_lift_proven"]]
    guardrail_clean = _guardrail_clean(comparison)
    true_rerank_applied = _count_rerank_status(comparison, "applied") > 0
    return {
        "candidate_count": len(rows),
        "effective_rank_lift_count": len(effective),
        "min_effective_samples": min_effective_samples,
        "eligible_for_formal_evalset": (
            len(effective) >= min_effective_samples and guardrail_clean and true_rerank_applied
        ),
        "downgrade_to": (
            "" if len(effective) >= min_effective_samples else "rank_lift_observation_report"
        ),
        "guardrail_clean": guardrail_clean,
        "true_rerank_requested": enable_true_rerank_for_c,
        "true_rerank_applied": true_rerank_applied,
        "rerank_status_counts_by_mode": (
            comparison.get("summary", {}).get("rerank_status_counts_by_mode", {})
        ),
        "comparison_summary": comparison["summary"],
        "candidates": rows,
    }


def _classify_b_candidate(row: dict[str, Any], *, expected_doc_ids: set[str]) -> dict[str, Any]:
    dense_rank = _first_expected_doc_rank(row["dense_only"], expected_doc_ids)
    sparse_rank = _first_expected_doc_rank(row["sparse_only"], expected_doc_ids)
    hybrid_rank = _first_expected_doc_rank(row["hybrid"], expected_doc_ids)
    lift_proven = dense_rank is None and (sparse_rank is not None or hybrid_rank is not None)
    rank_observation = (
        dense_rank is not None
        and (
            (sparse_rank is not None and sparse_rank < dense_rank)
            or (hybrid_rank is not None and hybrid_rank < dense_rank)
        )
    )
    if lift_proven:
        verdict = "proven_lift"
        reason = "dense_miss_sparse_or_hybrid_hit"
    elif rank_observation:
        verdict = "rank_observation_only"
        reason = "dense_found_but_sparse_or_hybrid_ranked_higher"
    else:
        verdict = "no_lift"
        reason = "dense_already_found_or_non_dense_did_not_recover"
    return {
        "candidate_id": row["sample_id"],
        "query": row["query"],
        "expected_doc_ids": sorted(expected_doc_ids),
        "dense_rank": dense_rank,
        "sparse_rank": sparse_rank,
        "hybrid_rank": hybrid_rank,
        "hybrid_rerank_rank": _first_expected_doc_rank(row["hybrid_rerank"], expected_doc_ids),
        "lift_proven": lift_proven,
        "rank_observation": rank_observation,
        "verdict": verdict,
        "reason": reason,
    }


def _classify_c_candidate(row: dict[str, Any], *, expected_doc_ids: set[str]) -> dict[str, Any]:
    hybrid_rank = _first_expected_doc_rank(row["hybrid"], expected_doc_ids)
    hybrid_rerank_rank = _first_expected_doc_rank(row["hybrid_rerank"], expected_doc_ids)
    status_counts = _result_metadata_counts(row["hybrid_rerank"], "rerank_status")
    applied = status_counts.get("applied", 0) > 0
    recovered_into_top_k = hybrid_rank is None and hybrid_rerank_rank is not None
    improved_rank = (
        hybrid_rank is not None
        and hybrid_rerank_rank is not None
        and hybrid_rerank_rank < hybrid_rank
    )
    rank_lift_proven = applied and (recovered_into_top_k or improved_rank)
    if rank_lift_proven:
        verdict = "proven_rank_lift"
        reason = "true_rerank_promoted_expected_doc"
    elif not applied:
        verdict = "not_true_rerank"
        reason = "hybrid_rerank_did_not_apply"
    else:
        verdict = "no_rank_lift"
        reason = "true_rerank_applied_but_expected_doc_not_promoted"
    return {
        "candidate_id": row["sample_id"],
        "query": row["query"],
        "expected_doc_ids": sorted(expected_doc_ids),
        "hybrid_rank": hybrid_rank,
        "hybrid_rerank_rank": hybrid_rerank_rank,
        "hybrid_rerank_status_counts": dict(status_counts),
        "rank_lift_proven": rank_lift_proven,
        "recovered_into_top_k": recovered_into_top_k,
        "improved_rank": improved_rank,
        "verdict": verdict,
        "reason": reason,
    }


def _parse_candidate_section(text: str, candidate_prefix: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(f"| {candidate_prefix}"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 7:
            continue
        candidate_id, query, allowed, expected, keywords, failure_class, support = cells[:7]
        rows.append(
            {
                "sample_id": candidate_id,
                "query": query,
                "allowed_kb_ids": _backtick_values(allowed),
                "expected_doc_ids": _backtick_values(expected),
                "expected_answer_keywords": _backtick_values(keywords),
                "scope": "scoped",
                "retrieval_mode": "hybrid",
                "top_k": 3,
                "failure_class": _strip_code(failure_class),
                "support_check_status": _strip_code(support),
                "candidate_group": "benefit_b" if candidate_prefix == "P26-B-" else "benefit_c",
            }
        )
    return rows


def _expected_doc_ids_by_sample(samples: list[dict[str, Any]]) -> dict[str, set[str]]:
    return {
        str(sample["sample_id"]): {
            str(doc_id) for doc_id in sample.get("expected_doc_ids", []) if doc_id
        }
        for sample in samples
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


def _backtick_values(cell: str) -> list[str]:
    values = re.findall(r"`([^`]+)`", cell)
    if values:
        return [value.strip() for value in values if value.strip()]
    stripped = _strip_code(cell)
    return [stripped] if stripped else []


def _strip_code(value: str) -> str:
    return value.replace("`", "").strip()


def _display_rank(value: int | None) -> str:
    return "-" if value is None else str(value)


def _blockers(benefit_b: dict[str, Any], benefit_c: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not benefit_b["guardrail_clean"]:
        blockers.append("benefit_b_guardrail_regression")
    if not benefit_c["guardrail_clean"]:
        blockers.append("benefit_c_guardrail_regression")
    if benefit_c["true_rerank_requested"] and not benefit_c["true_rerank_applied"]:
        blockers.append("benefit_c_true_rerank_not_applied")
    return blockers


def _status(
    benefit_b: dict[str, Any],
    benefit_c: dict[str, Any],
    blockers: list[str],
) -> str:
    if blockers:
        return "needs_attention"
    if benefit_b["eligible_for_formal_evalset"] or benefit_c["eligible_for_formal_evalset"]:
        return "passed_formal_upgrade_candidate"
    return "passed_no_formal_upgrade"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build P2.6 Benefit-B/C shadow probe report.")
    parser.add_argument("--candidate-doc", default=DEFAULT_CANDIDATE_DOC_PATH)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    parser.add_argument("--min-effective-samples", type=int, default=10)
    parser.add_argument(
        "--no-true-rerank-for-c",
        action="store_true",
        help="Do not temporarily enable rerank_service.enabled for Benefit-C.",
    )
    args = parser.parse_args()
    write_p26_bc_shadow_probe_report(
        candidate_doc_path=args.candidate_doc,
        output_json=args.output_json,
        output_md=args.output_md or None,
        min_effective_samples=args.min_effective_samples,
        enable_true_rerank_for_c=not args.no_true_rerank_for_c,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
