"""Run offline agent evaluation gates as one pre-release scorecard."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

import evals.enterprise.run_audit_evidence_gate as audit_evidence_gate
from evals.enterprise.run_trace_eval import run_trace_eval

REPORT_DIR = Path(__file__).resolve().parent / "reports"
SCORECARD_ID = "AGENT-EVAL-PRE-RELEASE"
AUDIT_EVIDENCE_GATE_ID = audit_evidence_gate.GATE_ID
TRACE_TRAJECTORY_GATE_ID = "G-P1-TRACE-TRAJECTORY"


class AgentEvalGateResult(BaseModel):
    gate_id: str
    passed: bool
    summary: dict[str, Any] = Field(default_factory=dict)
    reports: list[dict[str, str | None]] = Field(default_factory=list)


class AgentEvalScorecardReport(BaseModel):
    scorecard_id: str = SCORECARD_ID
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    passed: bool
    summary: dict[str, Any] = Field(default_factory=dict)
    gates: list[AgentEvalGateResult] = Field(default_factory=list)
    report_json_path: str | None = None
    report_markdown_path: str | None = None


def run_agent_eval_scorecard(
    *,
    trace_evalsets: list[Path],
    trace_mode: str = "reference",
    audit_events_path: Path | None = None,
    audit_source_kind: str | None = None,
    audit_source_path: Path | None = None,
    audit_trace_id: str | None = None,
    audit_request_id: str | None = None,
    output_dir: Path | None = None,
    write_report: bool = True,
) -> AgentEvalScorecardReport:
    trace_gate = _run_trace_gate(
        trace_evalsets=trace_evalsets,
        trace_mode=trace_mode,
        output_dir=output_dir,
        write_report=write_report,
    )
    audit_gate = _run_audit_gate(
        audit_events_path=audit_events_path,
        audit_source_kind=audit_source_kind,
        audit_source_path=audit_source_path,
        audit_trace_id=audit_trace_id,
        audit_request_id=audit_request_id,
        output_dir=output_dir,
        write_report=write_report,
    )

    gates = [trace_gate, audit_gate]
    report = AgentEvalScorecardReport(
        passed=all(gate.passed for gate in gates),
        gates=gates,
        summary=_summarize_gates(gates),
    )
    if write_report:
        json_path, markdown_path = write_reports(report, output_dir=output_dir)
        report.report_json_path = json_path.as_posix()
        report.report_markdown_path = markdown_path.as_posix()
    return report


def write_reports(
    report: AgentEvalScorecardReport,
    *,
    output_dir: Path | None = None,
) -> tuple[Path, Path]:
    report_dir = output_dir or REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = report_dir / f"agent_eval_scorecard_{timestamp}.json"
    markdown_path = report_dir / f"agent_eval_scorecard_{timestamp}.md"

    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-evalset", action="append", type=Path, required=True)
    parser.add_argument("--trace-mode", choices=("reference", "live_agent"), default="reference")
    parser.add_argument("--audit-events", type=Path, default=None)
    parser.add_argument("--audit-source-kind", choices=("jsonl", "sqlite"), default=None)
    parser.add_argument("--audit-path", dest="audit_source_path", type=Path, default=None)
    parser.add_argument("--audit-trace-id", default=None)
    parser.add_argument("--audit-request-id", default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    _validate_audit_source_args(parser, args)

    report = run_agent_eval_scorecard(
        trace_evalsets=args.trace_evalset,
        trace_mode=args.trace_mode,
        audit_events_path=args.audit_events,
        audit_source_kind=args.audit_source_kind,
        audit_source_path=args.audit_source_path,
        audit_trace_id=args.audit_trace_id,
        audit_request_id=args.audit_request_id,
        output_dir=args.output_dir,
        write_report=not args.no_write,
    )
    summary = report.summary
    print(
        "agent_eval_scorecard "
        f"scorecard_id={report.scorecard_id} "
        f"gates={summary['gate_count']} "
        f"failed_gates={summary['failed_gate_count']} "
        f"passed={str(report.passed).lower()}"
    )
    if report.report_json_path:
        print(f"json_report={report.report_json_path}")
    if report.report_markdown_path:
        print(f"markdown_report={report.report_markdown_path}")
    return 0 if report.passed else 1


def _run_trace_gate(
    *,
    trace_evalsets: list[Path],
    trace_mode: str,
    output_dir: Path | None,
    write_report: bool,
) -> AgentEvalGateResult:
    trace_reports = [
        run_trace_eval(
            evalset_path=evalset,
            mode=trace_mode,
            output_dir=output_dir,
            write_report=write_report,
        )
        for evalset in trace_evalsets
    ]
    summary = _summarize_trace_reports(trace_reports)
    return AgentEvalGateResult(
        gate_id=TRACE_TRAJECTORY_GATE_ID,
        passed=summary["failed"] == 0,
        summary=summary,
        reports=[
            {
                "evalset_path": report.evalset_path,
                "json_report": report.report_json_path,
                "markdown_report": report.report_markdown_path,
            }
            for report in trace_reports
        ],
    )


def _run_audit_gate(
    *,
    audit_events_path: Path | None,
    audit_source_kind: str | None,
    audit_source_path: Path | None,
    audit_trace_id: str | None,
    audit_request_id: str | None,
    output_dir: Path | None,
    write_report: bool,
) -> AgentEvalGateResult:
    audit_report = audit_evidence_gate.run_audit_evidence_gate(
        audit_events_path=audit_events_path,
        source_kind=audit_source_kind,
        source_path=audit_source_path,
        trace_id=audit_trace_id,
        request_id=audit_request_id,
        output_dir=output_dir,
        write_report=write_report,
    )
    return AgentEvalGateResult(
        gate_id=AUDIT_EVIDENCE_GATE_ID,
        passed=audit_report.passed,
        summary=dict(audit_report.summary),
        reports=[
            {
                "source_kind": audit_report.source_kind,
                "source_path": audit_report.source_path,
                "trace_id": audit_report.trace_id,
                "request_id": audit_report.request_id,
                "json_report": audit_report.report_json_path,
                "markdown_report": audit_report.report_markdown_path,
            }
        ],
    )


def _summarize_trace_reports(reports) -> dict[str, Any]:
    mismatch_codes: Counter[str] = Counter()
    mismatch_categories: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    total = passed = failed = mismatch_count = 0
    evalsets: list[dict[str, Any]] = []

    for report in reports:
        summary = report.summary
        total += int(summary.get("total", 0))
        passed += int(summary.get("passed", 0))
        failed += int(summary.get("failed", 0))
        mismatch_count += int(summary.get("mismatch_count", 0))
        mismatch_codes.update(summary.get("mismatch_codes", {}))
        mismatch_categories.update(summary.get("mismatch_categories", {}))
        outcomes.update(summary.get("outcomes", {}))
        evalsets.append(
            {
                "evalset_path": report.evalset_path,
                "mode": report.mode,
                "total": summary.get("total", 0),
                "passed": summary.get("passed", 0),
                "failed": summary.get("failed", 0),
            }
        )

    return {
        "evalset_count": len(reports),
        "total": total,
        "passed": passed,
        "failed": failed,
        "mismatch_count": mismatch_count,
        "mismatch_codes": dict(sorted(mismatch_codes.items())),
        "mismatch_categories": dict(sorted(mismatch_categories.items())),
        "outcomes": dict(sorted(outcomes.items())),
        "evalsets": evalsets,
    }


def _summarize_gates(gates: list[AgentEvalGateResult]) -> dict[str, Any]:
    failed = [gate.gate_id for gate in gates if not gate.passed]
    return {
        "gate_count": len(gates),
        "passed_gate_count": len(gates) - len(failed),
        "failed_gate_count": len(failed),
        "failed_gates": failed,
    }


def _validate_audit_source_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    has_audit_events = args.audit_events is not None
    has_audit_trace_args = any(
        value is not None
        for value in (
            args.audit_source_kind,
            args.audit_source_path,
            args.audit_trace_id,
            args.audit_request_id,
        )
    )
    if has_audit_events and has_audit_trace_args:
        parser.error(
            "--audit-events cannot be combined with "
            "--audit-source-kind/--audit-path/--audit-trace-id/--audit-request-id"
        )
    if has_audit_events:
        return
    if (
        args.audit_source_kind is None
        or args.audit_source_path is None
        or args.audit_trace_id is None
    ):
        parser.error(
            "provide an audit source via --audit-events or "
            "--audit-source-kind with --audit-path and --audit-trace-id"
        )


def _render_markdown(report: AgentEvalScorecardReport) -> str:
    lines = [
        "# Agent Eval Scorecard",
        "",
        f"- Scorecard: `{report.scorecard_id}`",
        f"- Generated at: `{report.generated_at.isoformat()}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Gate count: {report.summary.get('gate_count', 0)}",
        f"- Failed gate count: {report.summary.get('failed_gate_count', 0)}",
        f"- Failed gates: {_format_list(report.summary.get('failed_gates', []))}",
        "",
        "## Gates",
        "",
        "| gate_id | passed | key summary |",
        "|---|---|---|",
    ]
    for gate in report.gates:
        lines.append(
            f"| {gate.gate_id} | {str(gate.passed).lower()} | "
            f"`{json.dumps(gate.summary, ensure_ascii=False, sort_keys=True)}` |"
        )
    lines.append("")
    return "\n".join(lines)


def _format_list(values: list[str]) -> str:
    if not values:
        return "-"
    return ", ".join(f"`{value}`" for value in values)


if __name__ == "__main__":
    raise SystemExit(main())
