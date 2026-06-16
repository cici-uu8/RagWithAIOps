"""Run Enterprise 2.0 deterministic trace trajectory evals."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import config
from evals.enterprise.extractors import AuditTraceExtractor
from evals.enterprise.matcher import TrajectoryMatcher
from evals.enterprise.models import ExpectedTrajectory, TraceEvalReport, TraceEvalResult

REPORT_DIR = Path(__file__).resolve().parent / "reports"


def load_evalset(evalset_path: Path) -> list[ExpectedTrajectory]:
    samples: list[ExpectedTrajectory] = []
    with evalset_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                samples.append(ExpectedTrajectory.model_validate(json.loads(stripped)))
            except Exception as exc:
                raise ValueError(f"Invalid evalset row {line_number} in {evalset_path}: {exc}") from exc
    return samples


def run_trace_eval(
    *,
    evalset_path: Path,
    mode: str = "reference",
    output_dir: Path | None = None,
    write_report: bool = True,
) -> TraceEvalReport:
    if mode not in {"reference", "live_agent"}:
        raise ValueError(f"Unsupported trace eval mode: {mode}")
    samples = load_evalset(evalset_path)
    extractor = AuditTraceExtractor()
    matcher = TrajectoryMatcher()

    results: list[TraceEvalResult] = []
    for sample in samples:
        if mode == "live_agent" and not _live_agent_ready():
            results.append(_not_ready_live_agent_result(sample))
            continue
        actual = extractor.extract(sample.trace_source)
        result = matcher.match(sample, actual)
        result.mode = mode
        result.outcome = "passed" if result.passed else _first_mismatch_code(result)
        results.append(result)

    report = TraceEvalReport(
        evalset_path=evalset_path.as_posix(),
        mode=mode,
        summary=_summarize_results(results),
        results=results,
    )
    if write_report:
        json_path, markdown_path = write_reports(report, output_dir=output_dir)
        report.report_json_path = json_path.as_posix()
        report.report_markdown_path = markdown_path.as_posix()
    return report


def write_reports(report: TraceEvalReport, *, output_dir: Path | None = None) -> tuple[Path, Path]:
    report_dir = output_dir or REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    evalset_stem = Path(report.evalset_path).stem
    json_path = report_dir / f"trace_eval_{evalset_stem}_{timestamp}.json"
    markdown_path = report_dir / f"trace_eval_{evalset_stem}_{timestamp}.md"

    payload = report.model_dump(mode="json")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def _summarize_results(results: list[TraceEvalResult]) -> dict[str, Any]:
    mismatch_codes: Counter[str] = Counter()
    mismatch_categories: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    for result in results:
        outcomes[result.outcome] += 1
        for mismatch in result.mismatches:
            mismatch_codes[mismatch.code] += 1
            mismatch_categories[mismatch.category] += 1

    passed = sum(1 for result in results if result.passed)
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "mismatch_count": sum(mismatch_codes.values()),
        "mismatch_codes": dict(sorted(mismatch_codes.items())),
        "mismatch_categories": dict(sorted(mismatch_categories.items())),
        "outcomes": dict(sorted(outcomes.items())),
    }


def _render_markdown(report: TraceEvalReport) -> str:
    lines = [
        "# Enterprise Trace Eval Report",
        "",
        f"- Evalset: `{report.evalset_path}`",
        f"- Mode: `{report.mode}`",
        f"- Generated at: `{report.generated_at.isoformat()}`",
        f"- Total: {report.summary.get('total', 0)}",
        f"- Passed: {report.summary.get('passed', 0)}",
        f"- Failed: {report.summary.get('failed', 0)}",
        f"- Mismatch count: {report.summary.get('mismatch_count', 0)}",
        f"- Mismatch categories: {_format_categories(report.summary.get('mismatch_categories', {}))}",
        "",
        "## Results",
        "",
        "| eval_id | mode | outcome | trace_id | request_id | final_status | passed | mismatches |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for result in report.results:
        mismatch_codes = ", ".join(mismatch.code for mismatch in result.mismatches) or "-"
        lines.append(
            "| "
            f"{result.eval_id} | {result.mode} | {result.outcome} | "
            f"{result.trace_id} | {result.request_id} | "
            f"{result.final_status} | {str(result.passed).lower()} | {mismatch_codes} |"
        )
    lines.append("")
    return "\n".join(lines)


def _format_categories(categories: dict[str, Any]) -> str:
    if not categories:
        return "-"
    return ", ".join(f"{key}={value}" for key, value in categories.items())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evalset", required=True, type=Path)
    parser.add_argument("--mode", choices=["reference", "live_agent"], default="reference")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    report = run_trace_eval(
        evalset_path=args.evalset,
        mode=args.mode,
        output_dir=args.output_dir,
        write_report=not args.no_write,
    )
    summary = report.summary
    print(
        "enterprise_trace_eval "
        f"evalset={args.evalset} "
        f"mode={args.mode} "
        f"total={summary['total']} "
        f"passed={summary['passed']} "
        f"failed={summary['failed']} "
        f"mismatch_count={summary['mismatch_count']}"
    )
    if report.report_json_path:
        print(f"json_report={report.report_json_path}")
    if report.report_markdown_path:
        print(f"markdown_report={report.report_markdown_path}")
    return 0 if summary["failed"] == 0 else 1


def _live_agent_ready() -> bool:
    return (
        os.environ.get("ENTERPRISE_DB_LIVE_AGENT_EVAL_ENABLED") == "1"
        and bool(config.dashscope_api_key)
    )


def _not_ready_live_agent_result(sample: ExpectedTrajectory) -> TraceEvalResult:
    return TraceEvalResult(
        eval_id=sample.eval_id,
        mode="live_agent",
        outcome="not_ready_live_agent",
        trace_id=sample.trace_source.trace_id,
        request_id=sample.trace_source.request_id or "",
        route=sample.input.get("route", sample.trace_source.route or "database_demo"),
        final_status="not_ready_live_agent",
        passed=False,
        mismatches=[],
    )


def _first_mismatch_code(result: TraceEvalResult) -> str:
    return result.mismatches[0].code if result.mismatches else "failed"


if __name__ == "__main__":
    raise SystemExit(main())
