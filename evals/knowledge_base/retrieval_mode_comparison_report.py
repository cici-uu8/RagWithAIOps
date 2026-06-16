"""Retrieval-mode comparison report helpers."""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.models import RetrievalMode, RetrievalQuery

DEFAULT_MODES = [RetrievalMode.DENSE_ONLY, RetrievalMode.HYBRID]
ALL_SHADOW_MODES = [
    RetrievalMode.DENSE_ONLY,
    RetrievalMode.SPARSE_ONLY,
    RetrievalMode.HYBRID,
    RetrievalMode.HYBRID_RERANK,
]


def build_retrieval_mode_comparison_report(
    samples: list[dict[str, Any]],
    *,
    retrieval_service=None,
    modes: list[str | RetrievalMode] | None = None,
) -> dict[str, Any]:
    retrieval_service = retrieval_service or _default_retrieval_service()
    selected_modes = _coerce_modes(modes)
    rows = [
        _evaluate_sample(
            sample,
            retrieval_service=retrieval_service,
            modes=selected_modes,
        )
        for sample in samples
    ]
    summary = _summary(rows, modes=selected_modes)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "modes": [mode.value for mode in selected_modes],
        "summary": summary,
        "comparison": _aggregate_comparison(rows, modes=selected_modes),
        "samples": rows,
    }


def write_retrieval_mode_comparison_report(
    samples: list[dict[str, Any]],
    *,
    output_json: str | Path,
    output_md: str | Path | None = None,
    retrieval_service=None,
    modes: list[str | RetrievalMode] | None = None,
) -> dict[str, Any]:
    report = build_retrieval_mode_comparison_report(
        samples,
        retrieval_service=retrieval_service,
        modes=modes,
    )
    output_json_path = Path(output_json)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if output_md is not None:
        output_md_path = Path(output_md)
        output_md_path.parent.mkdir(parents=True, exist_ok=True)
        output_md_path.write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    modes = list(report.get("modes") or DEFAULT_MODES)
    lines = [
        "# Retrieval Mode Comparison Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Modes: `{', '.join(str(mode) for mode in modes)}`",
        f"- Summary: {report['summary']}",
        "",
        "| sample_id | mode_counts | expected_found | wrong_scope | latency_ms |",
        "|---|---|---|---|---|",
    ]
    for row in report["samples"]:
        mode_counts = ", ".join(
            f"{mode}={row[mode]['result_count']}" for mode in modes if mode in row
        )
        expected_found = ", ".join(
            f"{mode}={row['expected_doc_found'].get(mode)}" for mode in modes
        )
        wrong_scope = ", ".join(
            f"{mode}={row['wrong_scope_count_by_mode'].get(mode)}" for mode in modes
        )
        latency = ", ".join(
            f"{mode}={row[mode].get('latency_ms', 0)}" for mode in modes if mode in row
        )
        lines.append(
            "| {sample_id} | {mode_counts} | {expected_found} | {wrong_scope} | {latency} |".format(
                sample_id=row["sample_id"],
                mode_counts=mode_counts,
                expected_found=expected_found,
                wrong_scope=wrong_scope,
                latency=latency,
            )
        )
    lines.append("")
    return "\n".join(lines)


def _evaluate_sample(
    sample: dict[str, Any],
    *,
    retrieval_service,
    modes: list[RetrievalMode],
) -> dict[str, Any]:
    mode_results = {
        mode.value: _retrieve_mode(sample, retrieval_service=retrieval_service, mode=mode)
        for mode in modes
    }
    expected_doc_ids = set(sample.get("expected_doc_ids") or [])
    allowed_kb_ids = set(sample.get("allowed_kb_ids") or [])
    expected_doc_found = {
        mode.value: _expected_doc_found(mode_results[mode.value], expected_doc_ids)
        for mode in modes
    }
    wrong_scope_by_mode = {
        mode.value: _wrong_scope_count(mode_results[mode.value], allowed_kb_ids)
        for mode in modes
    }
    row = {
        "sample_id": sample.get("sample_id") or sample.get("query", ""),
        "query": sample.get("query", ""),
        "modes": [mode.value for mode in modes],
        "expected_doc_found": expected_doc_found,
        "wrong_scope_count_by_mode": wrong_scope_by_mode,
        "wrong_scope_count": sum(wrong_scope_by_mode.values()),
        "doc_overlap_matrix": _doc_overlap_matrix(mode_results, modes=modes),
        "rank_diff_matrix": _rank_diff_matrix(mode_results, modes=modes),
    }
    row.update(mode_results)
    if "dense_only" in mode_results and "hybrid" in mode_results:
        row["hybrid_added_result_count"] = max(
            0,
            mode_results["hybrid"]["result_count"]
            - mode_results["dense_only"]["result_count"],
        )
    else:
        row["hybrid_added_result_count"] = 0
    return row


def _retrieve_mode(sample: dict[str, Any], *, retrieval_service, mode: RetrievalMode) -> dict[str, Any]:
    query = RetrievalQuery(
        query=str(sample["query"]),
        top_k=int(sample.get("top_k") or 3),
        retrieval_mode=mode,
        knowledge_base_ids=list(sample.get("allowed_kb_ids") or []),
        document_ids=list(sample.get("document_ids") or []),
    )
    started_at = time.perf_counter()
    try:
        response = retrieval_service.retrieve(query)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        return _not_ready_mode_result(mode, exc, latency_ms=latency_ms)
    latency_ms = int((time.perf_counter() - started_at) * 1000)
    results = list(response.results)
    return {
        "status": "evaluated",
        "retrieval_mode": mode.value,
        "latency_ms": latency_ms,
        "result_count": len(results),
        "doc_ids": [result.doc_id for result in results],
        "chunk_ids": [result.chunk_id for result in results],
        "recall_sources": dict(Counter(_recall_source(result) for result in results)),
        "source_ref_complete": all(_source_ref_complete(result) for result in results),
        "results": [
            {
                "kb_id": result.kb_id,
                "doc_id": result.doc_id,
                "chunk_id": result.chunk_id,
                "score": result.score,
                "source_ref": result.source_ref.model_dump(mode="json"),
                "metadata": dict(result.metadata),
            }
            for result in results
        ],
    }


def _not_ready_mode_result(
    mode: RetrievalMode,
    exc: Exception,
    *,
    latency_ms: int = 0,
) -> dict[str, Any]:
    return {
        "status": "not_ready",
        "retrieval_mode": mode.value,
        "latency_ms": latency_ms,
        "result_count": 0,
        "doc_ids": [],
        "chunk_ids": [],
        "recall_sources": {},
        "source_ref_complete": False,
        "results": [],
        "blocked_error_type": type(exc).__name__,
        "blocked_error": str(exc),
    }


def _summary(rows: list[dict[str, Any]], *, modes: list[RetrievalMode]) -> dict[str, Any]:
    mode_values = [mode.value for mode in modes]
    mode_result_counts = {
        mode: sum(row[mode]["result_count"] for row in rows)
        for mode in mode_values
    }
    mode_not_ready_counts = {
        mode: sum(1 for row in rows if row[mode]["status"] == "not_ready")
        for mode in mode_values
    }
    mode_wrong_scope_counts = {
        mode: sum(row["wrong_scope_count_by_mode"][mode] for row in rows)
        for mode in mode_values
    }
    mode_citation_incomplete_counts = {
        mode: sum(1 for row in rows if not row[mode]["source_ref_complete"])
        for mode in mode_values
    }
    mode_expected_doc_found_counts = {
        mode: sum(1 for row in rows if row["expected_doc_found"][mode])
        for mode in mode_values
    }
    latency_ms_by_mode = {
        mode: _latency_summary([row[mode]["latency_ms"] for row in rows])
        for mode in mode_values
    }
    rerank_status_counts_by_mode = _rerank_status_counts_by_mode(
        rows,
        modes=mode_values,
    )
    summary = {
        "total": len(rows),
        "modes": mode_values,
        "mode_result_counts": mode_result_counts,
        "mode_not_ready_counts": mode_not_ready_counts,
        "mode_wrong_scope_counts": mode_wrong_scope_counts,
        "mode_citation_incomplete_counts": mode_citation_incomplete_counts,
        "mode_expected_doc_found_counts": mode_expected_doc_found_counts,
        "latency_ms_by_mode": latency_ms_by_mode,
        "rerank_status_counts_by_mode": rerank_status_counts_by_mode,
        "wrong_scope_count": sum(mode_wrong_scope_counts.values()),
        "not_ready_count": sum(mode_not_ready_counts.values()),
        "citation_incomplete_count": sum(mode_citation_incomplete_counts.values()),
    }
    summary.update(_legacy_summary_fields(rows, mode_result_counts=mode_result_counts))
    return summary


def _rerank_status_counts_by_mode(
    rows: list[dict[str, Any]],
    *,
    modes: list[str],
) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for mode in modes:
        counter: Counter[str] = Counter()
        for row in rows:
            for result in row[mode]["results"]:
                status = result["metadata"].get("rerank_status")
                if status:
                    counter[str(status)] += 1
        counts[mode] = dict(counter)
    return counts


def _legacy_summary_fields(
    rows: list[dict[str, Any]],
    *,
    mode_result_counts: dict[str, int],
) -> dict[str, Any]:
    return {
        "dense_result_count": mode_result_counts.get("dense_only", 0),
        "hybrid_result_count": mode_result_counts.get("hybrid", 0),
        "hybrid_added_result_count": sum(
            row.get("hybrid_added_result_count", 0) for row in rows
        ),
    }


def _latency_summary(values: list[int]) -> dict[str, int]:
    if not values:
        return {"avg": 0, "p95": 0, "max": 0}
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return {
        "avg": int(sum(ordered) / len(ordered)),
        "p95": int(ordered[p95_index]),
        "max": int(max(ordered)),
    }


def _aggregate_comparison(
    rows: list[dict[str, Any]],
    *,
    modes: list[RetrievalMode],
) -> dict[str, Any]:
    mode_values = [mode.value for mode in modes]
    return {
        "doc_overlap_matrix": _average_matrix(
            [row["doc_overlap_matrix"] for row in rows],
            modes=mode_values,
        ),
        "rank_diff_matrix": _average_matrix(
            [row["rank_diff_matrix"] for row in rows],
            modes=mode_values,
        ),
    }


def _average_matrix(
    matrices: list[dict[str, dict[str, float | None]]],
    *,
    modes: list[str],
) -> dict[str, dict[str, float | None]]:
    averaged: dict[str, dict[str, float | None]] = {}
    for left in modes:
        averaged[left] = {}
        for right in modes:
            values = [
                matrix[left][right]
                for matrix in matrices
                if matrix[left][right] is not None
            ]
            averaged[left][right] = (
                round(sum(values) / len(values), 4) if values else None
            )
    return averaged


def _doc_overlap_matrix(
    mode_results: dict[str, dict[str, Any]],
    *,
    modes: list[RetrievalMode],
) -> dict[str, dict[str, float]]:
    matrix: dict[str, dict[str, float]] = {}
    for left in modes:
        left_docs = set(mode_results[left.value]["doc_ids"])
        matrix[left.value] = {}
        for right in modes:
            right_docs = set(mode_results[right.value]["doc_ids"])
            union = left_docs | right_docs
            matrix[left.value][right.value] = (
                1.0 if not union else round(len(left_docs & right_docs) / len(union), 4)
            )
    return matrix


def _rank_diff_matrix(
    mode_results: dict[str, dict[str, Any]],
    *,
    modes: list[RetrievalMode],
) -> dict[str, dict[str, float | None]]:
    matrix: dict[str, dict[str, float | None]] = {}
    for left in modes:
        left_rank = {
            chunk_id: index
            for index, chunk_id in enumerate(mode_results[left.value]["chunk_ids"], start=1)
        }
        matrix[left.value] = {}
        for right in modes:
            right_rank = {
                chunk_id: index
                for index, chunk_id in enumerate(mode_results[right.value]["chunk_ids"], start=1)
            }
            common = set(left_rank) & set(right_rank)
            if not common:
                matrix[left.value][right.value] = None
                continue
            matrix[left.value][right.value] = round(
                sum(abs(left_rank[chunk_id] - right_rank[chunk_id]) for chunk_id in common)
                / len(common),
                4,
            )
    return matrix


def _expected_doc_found(report: dict[str, Any], expected_doc_ids: set[str]) -> bool:
    doc_ids = set(report["doc_ids"])
    if expected_doc_ids:
        return bool(expected_doc_ids & doc_ids)
    return bool(doc_ids)


def _recall_source(result) -> str:
    return str(result.metadata.get("recall_source") or result.metadata.get("retrieval_mode") or "unknown")


def _source_ref_complete(result) -> bool:
    source_ref = result.source_ref
    return all(
        [
            bool(source_ref.kb_id),
            bool(source_ref.doc_id),
            bool(source_ref.chunk_id),
            bool(source_ref.source_file),
        ]
    )


def _wrong_scope_count(report: dict[str, Any], allowed_kb_ids: set[str]) -> int:
    if not allowed_kb_ids:
        return 0
    return sum(1 for result in report["results"] if result["kb_id"] not in allowed_kb_ids)


def _load_samples(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    if path.suffix == ".jsonl":
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    return list(payload.get("samples") or [])


def _coerce_modes(modes: list[str | RetrievalMode] | None) -> list[RetrievalMode]:
    values = modes or DEFAULT_MODES
    parsed: list[RetrievalMode] = []
    for value in values:
        mode = value if isinstance(value, RetrievalMode) else RetrievalMode(str(value))
        if mode not in parsed:
            parsed.append(mode)
    return parsed


def _default_retrieval_service():
    from app.services.retrieval_service import retrieval_service

    return retrieval_service


def main() -> int:
    parser = argparse.ArgumentParser(description="Build retrieval-mode comparison report.")
    parser.add_argument("--samples", default="", help="JSON/JSONL file with samples.")
    parser.add_argument("--evalset", default="", help="Alias for --samples.")
    parser.add_argument(
        "--modes",
        nargs="+",
        default=[mode.value for mode in DEFAULT_MODES],
        choices=[mode.value for mode in ALL_SHADOW_MODES],
    )
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output", default="", help="Alias for --output-json.")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()
    sample_path = args.samples or args.evalset
    if not sample_path:
        parser.error("--samples or --evalset is required")
    output_json = args.output_json or args.output
    if not output_json:
        parser.error("--output-json or --output is required")
    write_retrieval_mode_comparison_report(
        _load_samples(sample_path),
        output_json=output_json,
        output_md=args.output_md or None,
        modes=args.modes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
