"""Build read-only baseline summaries from existing department RAG reports."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_baseline_summary(report_paths: list[str | Path]) -> dict[str, Any]:
    reports = [_summarize_report(Path(path)) for path in report_paths]
    failure_totals: dict[str, int] = {}
    for report in reports:
        for category, count in report["failure_categories"].items():
            failure_totals[category] = failure_totals.get(category, 0) + int(count)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_reports": len(reports),
        "reports": reports,
        "failure_totals": failure_totals,
        "gates": {
            "data_not_indexed_present": failure_totals.get("data_not_indexed", 0) > 0,
            "source_ref_unresolvable_present": any(
                not report["all_source_ref_resolvable"] for report in reports
            ),
            "not_ready_present": any(report["not_ready"] > 0 for report in reports),
        },
    }


def write_baseline_summary(
    report_paths: list[str | Path],
    *,
    output_json: str | Path,
    output_md: str | Path | None = None,
) -> dict[str, Any]:
    summary = build_baseline_summary(report_paths)
    output_json_path = Path(output_json)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if output_md is not None:
        output_md_path = Path(output_md)
        output_md_path.parent.mkdir(parents=True, exist_ok=True)
        output_md_path.write_text(render_markdown(summary), encoding="utf-8")
    return summary


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# RAG Baseline Summary",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Total reports: {summary['total_reports']}",
        f"- Gates: {summary['gates']}",
        "",
        "| report | total | passed | failed | not_ready | source_ref_resolvable | failure_categories |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for report in summary["reports"]:
        lines.append(
            "| {path} | {total} | {passed} | {failed} | {not_ready} | {source_ref} | {failures} |".format(
                path=report["path"],
                total=report["total"],
                passed=report["passed"],
                failed=report["failed"],
                not_ready=report["not_ready"],
                source_ref=report["all_source_ref_resolvable"],
                failures=report["failure_categories"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def _summarize_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = payload.get("summary") or {}
    status_counts = summary.get("status_counts") or {}
    failure_categories = summary.get("failure_categories") or {}
    return {
        "path": path.as_posix(),
        "evalset_path": payload.get("evalset_path", ""),
        "generated_at": payload.get("generated_at", ""),
        "total": int(summary.get("total") or 0),
        "passed": int(status_counts.get("passed") or failure_categories.get("passed") or 0),
        "failed": int(status_counts.get("failed") or 0),
        "not_ready": int(summary.get("not_ready") or status_counts.get("not_ready") or 0),
        "failure_categories": dict(failure_categories),
        "all_source_ref_resolvable": bool(summary.get("all_source_ref_resolvable")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize existing RAG eval reports.")
    parser.add_argument("reports", nargs="+", help="Existing department RAG report JSON paths.")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()
    write_baseline_summary(
        args.reports,
        output_json=args.output_json,
        output_md=args.output_md or None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
