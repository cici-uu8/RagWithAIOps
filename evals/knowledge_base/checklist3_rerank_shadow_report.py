"""Checklist 3 rerank shadow readiness report.

This report explains why the latest ``hybrid_rerank`` comparison may show
``rerank_status=disabled`` and exercises the local rerank scorer on synthetic
candidates. It does not change runtime config, call Milvus, or call external
rerank APIs.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import Settings, config
from app.models import ParserEngine, RetrievalMode, RetrievalQuery, SourceRef
from app.services.rerank_service import RerankService
from app.services.vector_search_service import SearchResult

DEFAULT_COMPARISON_REPORT_PATH = (
    "evals/knowledge_base/reports/retrieval_4mode_comparison_20260609.json"
)


class _BrokenScorer:
    def score(self, query: str, candidates: list[SearchResult]) -> list[float]:
        raise TimeoutError("synthetic rerank timeout")


def build_checklist3_rerank_shadow_report(
    *,
    comparison_report_path: str | Path = DEFAULT_COMPARISON_REPORT_PATH,
) -> dict[str, Any]:
    comparison = _comparison_inventory(Path(comparison_report_path))
    config_state = _config_state()
    disabled_explanation = _disabled_explanation(
        comparison=comparison,
        config_state=config_state,
    )
    active_shadow = _run_active_shadow()
    fallback_shadow = _run_fallback_shadow()
    gaps = _gaps(
        comparison=comparison,
        config_state=config_state,
        active_shadow=active_shadow,
        fallback_shadow=fallback_shadow,
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "passed" if not gaps else "needs_attention",
        "scope": {
            "phase": "S3-P2.4",
            "report_kind": "rerank_shadow_readiness",
            "uses_synthetic_data": True,
            "runs_retrieval": False,
            "calls_external_rerank_api": False,
            "changes_runtime_config": False,
            "changes_default_retrieval_mode": False,
        },
        "config_state": config_state,
        "latest_comparison": comparison,
        "disabled_explanation": disabled_explanation,
        "active_shadow": active_shadow,
        "fallback_shadow": fallback_shadow,
        "gaps": gaps,
    }


def write_checklist3_rerank_shadow_report(
    *,
    output_json: str | Path,
    output_md: str | Path | None = None,
    comparison_report_path: str | Path = DEFAULT_COMPARISON_REPORT_PATH,
) -> dict[str, Any]:
    report = build_checklist3_rerank_shadow_report(
        comparison_report_path=comparison_report_path,
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


def _comparison_inventory(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "path": path.as_posix(),
            "exists": False,
            "hybrid_rerank_status_counts": {},
            "hybrid_rerank_disabled_count": 0,
            "hybrid_rerank_applied_count": 0,
            "not_ready_count": None,
            "wrong_scope_count": None,
            "citation_incomplete_count": None,
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = payload.get("summary") or {}
    status_counts = (
        summary.get("rerank_status_counts_by_mode", {})
        .get("hybrid_rerank", {})
    )
    return {
        "path": path.as_posix(),
        "exists": True,
        "total": int(summary.get("total") or 0),
        "hybrid_rerank_status_counts": dict(status_counts),
        "hybrid_rerank_disabled_count": int(status_counts.get("disabled") or 0),
        "hybrid_rerank_applied_count": int(status_counts.get("applied") or 0),
        "hybrid_rerank_result_count": int(
            (summary.get("mode_result_counts") or {}).get("hybrid_rerank") or 0
        ),
        "not_ready_count": int(summary.get("not_ready_count") or 0),
        "wrong_scope_count": int(summary.get("wrong_scope_count") or 0),
        "citation_incomplete_count": int(summary.get("citation_incomplete_count") or 0),
    }


def _config_state() -> dict[str, Any]:
    defaults = Settings.model_fields
    return {
        "source_defaults": {
            "rerank_enabled": defaults["rerank_enabled"].default,
            "rerank_model": defaults["rerank_model"].default,
            "rerank_timeout_ms": defaults["rerank_timeout_ms"].default,
            "rerank_top_k": defaults["rerank_top_k"].default,
            "rerank_fallback_on_error": defaults["rerank_fallback_on_error"].default,
        },
        "runtime_config": {
            "rerank_enabled": config.rerank_enabled,
            "rerank_model": config.rerank_model,
            "rerank_timeout_ms": config.rerank_timeout_ms,
            "rerank_top_k": config.rerank_top_k,
            "rerank_fallback_on_error": config.rerank_fallback_on_error,
        },
        "current_scorer": "LexicalRerankScorer",
        "current_model_is_local": config.rerank_model == "local_lexical_v1",
        "external_dependency_required_for_current_scorer": False,
    }


def _disabled_explanation(
    *,
    comparison: dict[str, Any],
    config_state: dict[str, Any],
) -> dict[str, Any]:
    runtime_enabled = bool(config_state["runtime_config"]["rerank_enabled"])
    disabled_count = int(comparison.get("hybrid_rerank_disabled_count") or 0)
    if not comparison["exists"]:
        reason = "comparison_report_missing"
    elif not runtime_enabled and disabled_count > 0:
        reason = "runtime_rerank_disabled"
    elif runtime_enabled and disabled_count > 0:
        reason = "comparison_report_contains_disabled_status_despite_runtime_enabled"
    elif comparison.get("hybrid_rerank_applied_count", 0) > 0:
        reason = "latest_comparison_has_applied_rerank"
    else:
        reason = "no_hybrid_rerank_status_observed"
    return {
        "reason": reason,
        "is_expected_default_off_behavior": reason == "runtime_rerank_disabled",
        "requires_external_api_to_investigate": False,
        "human_readable": (
            "hybrid_rerank is disabled because rerank_enabled is false."
            if reason == "runtime_rerank_disabled"
            else reason
        ),
    }


def _run_active_shadow() -> dict[str, Any]:
    query = RetrievalQuery(
        query="HighCPUUsage system-metrics",
        top_k=2,
        retrieval_mode=RetrievalMode.HYBRID_RERANK,
    )
    candidates = [
        _hit("doc_cpu:c00002", "CPU 告警可能来自流量突增。", 0.4),
        _hit(
            "doc_cpu:c00001",
            "HighCPUUsage 告警需要查询 system-metrics 日志并检查 CPU 使用率。",
            0.3,
        ),
        _hit("doc_cpu:c00003", "CPU 历史曲线可以辅助排查。", 0.2),
    ]
    reranker = RerankService(enabled=True)
    ranked = reranker.rerank(query=query, candidates=candidates)
    statuses = _metadata_counts(ranked, "rerank_status")
    return {
        "config_override": "enabled=True in report process only",
        "input_count": len(candidates),
        "top_k": query.top_k,
        "output_count": len(ranked),
        "top_k_respected": len(ranked) <= query.top_k,
        "result_ids": [result.id for result in ranked],
        "rerank_status_counts": statuses,
        "applied": statuses.get("applied", 0) == len(ranked) and bool(ranked),
        "reordered_expected_strong_hit_first": (
            bool(ranked) and ranked[0].id == "doc_cpu:c00001"
        ),
        "source_ref_identity_preserved": _source_ref_identity_preserved(ranked),
        "external_dependency_used": False,
        "model": config.rerank_model,
    }


def _run_fallback_shadow() -> dict[str, Any]:
    query = RetrievalQuery(
        query="HighCPUUsage system-metrics",
        top_k=2,
        retrieval_mode=RetrievalMode.HYBRID_RERANK,
    )
    candidates = [
        _hit("doc_cpu:c00002", "CPU 告警可能来自流量突增。", 0.4),
        _hit("doc_cpu:c00001", "HighCPUUsage 告警需要查询 system-metrics 日志。", 0.3),
        _hit("doc_cpu:c00003", "CPU 历史曲线可以辅助排查。", 0.2),
    ]
    reranker = RerankService(enabled=True, scorer=_BrokenScorer())
    ranked = reranker.rerank(query=query, candidates=candidates)
    statuses = _metadata_counts(ranked, "rerank_status")
    return {
        "input_count": len(candidates),
        "top_k": query.top_k,
        "output_count": len(ranked),
        "top_k_respected": len(ranked) <= query.top_k,
        "rerank_status_counts": statuses,
        "fallback": statuses.get("fallback", 0) == len(ranked) and bool(ranked),
        "error_recorded": all(
            bool(result.metadata.get("rerank_error")) for result in ranked
        ),
        "source_ref_identity_preserved": _source_ref_identity_preserved(ranked),
    }


def _hit(chunk_id: str, content: str, score: float) -> SearchResult:
    source_ref = SourceRef(
        kb_id="default",
        doc_id="doc_cpu",
        chunk_id=chunk_id,
        source_file="cpu_high_usage.md",
        heading_path=["CPU使用率过高告警处理方案"],
        content_type="markdown_section",
        parser_engine=ParserEngine.PLAIN_TEXT,
    )
    return SearchResult(
        id=chunk_id,
        content=content,
        score=score,
        metadata={
            "kb_id": "default",
            "doc_id": "doc_cpu",
            "chunk_id": chunk_id,
            "source_ref": source_ref.model_dump(mode="json"),
            "heading_path": ["CPU使用率过高告警处理方案"],
        },
    )


def _metadata_counts(results: list[SearchResult], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        value = result.metadata.get(key)
        if value:
            counts[str(value)] = counts.get(str(value), 0) + 1
    return counts


def _source_ref_identity_preserved(results: list[SearchResult]) -> bool:
    for result in results:
        source_ref = result.metadata.get("source_ref")
        if not isinstance(source_ref, dict):
            return False
        if source_ref.get("chunk_id") != result.metadata.get("chunk_id"):
            return False
    return True


def _gaps(
    *,
    comparison: dict[str, Any],
    config_state: dict[str, Any],
    active_shadow: dict[str, Any],
    fallback_shadow: dict[str, Any],
) -> list[str]:
    gaps: list[str] = []
    if not comparison["exists"]:
        gaps.append("latest_4mode_comparison_missing")
    if comparison["exists"] and comparison.get("hybrid_rerank_disabled_count", 0) == 0:
        gaps.append("latest_comparison_does_not_explain_disabled_rerank")
    if config_state["source_defaults"]["rerank_enabled"] is not False:
        gaps.append("source_default_rerank_enabled_not_false")
    if config_state["runtime_config"]["rerank_enabled"] is not False:
        gaps.append("runtime_rerank_enabled_not_false")
    if not config_state["current_model_is_local"]:
        gaps.append("current_rerank_model_not_local")
    if not active_shadow["applied"]:
        gaps.append("active_shadow_rerank_not_applied")
    if not active_shadow["top_k_respected"]:
        gaps.append("active_shadow_top_k_not_respected")
    if not active_shadow["source_ref_identity_preserved"]:
        gaps.append("active_shadow_source_ref_identity_not_preserved")
    if not fallback_shadow["fallback"]:
        gaps.append("fallback_shadow_not_triggered")
    if not fallback_shadow["top_k_respected"]:
        gaps.append("fallback_shadow_top_k_not_respected")
    if not fallback_shadow["source_ref_identity_preserved"]:
        gaps.append("fallback_shadow_source_ref_identity_not_preserved")
    return gaps


def render_markdown(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Checklist 3 Rerank Shadow Report",
            "",
            f"- Generated at: `{report['generated_at']}`",
            f"- Status: `{report['status']}`",
            f"- Phase: `{report['scope']['phase']}`",
            f"- Changes runtime config: `{report['scope']['changes_runtime_config']}`",
            f"- Calls external rerank API: `{report['scope']['calls_external_rerank_api']}`",
            f"- Disabled reason: `{report['disabled_explanation']['reason']}`",
            f"- Latest hybrid_rerank statuses: {report['latest_comparison']['hybrid_rerank_status_counts']}",
            f"- Active shadow statuses: {report['active_shadow']['rerank_status_counts']}",
            f"- Fallback shadow statuses: {report['fallback_shadow']['rerank_status_counts']}",
            f"- Gaps: {report['gaps'] or []}",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison-report", default=DEFAULT_COMPARISON_REPORT_PATH)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()
    write_checklist3_rerank_shadow_report(
        comparison_report_path=args.comparison_report,
        output_json=args.output_json,
        output_md=args.output_md or None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
