"""Run the offline G-P0-AUDIT-EVIDENCE gate against audit events."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.enterprise.context import RequestContext
from app.enterprise.verifiers import AuditEvidenceVerifier, VerificationStatus
from evals.enterprise.extractors import AuditTraceExtractor
from evals.enterprise.models import TraceSource

REPORT_DIR = Path(__file__).resolve().parent / "reports"
GATE_ID = "G-P0-AUDIT-EVIDENCE"


class AuditEvidenceGateReport(BaseModel):
    gate_id: str = GATE_ID
    audit_events_path: str | None = None
    source_kind: str = "audit_events"
    source_path: str | None = None
    trace_id: str | None = None
    request_id: str | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    verifier: str
    passed: bool
    summary: dict[str, Any] = Field(default_factory=dict)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    report_json_path: str | None = None
    report_markdown_path: str | None = None


def run_audit_evidence_gate(
    *,
    audit_events_path: Path | None = None,
    source_kind: str | None = None,
    source_path: Path | None = None,
    trace_id: str | None = None,
    request_id: str | None = None,
    output_dir: Path | None = None,
    write_report: bool = True,
) -> AuditEvidenceGateReport:
    audit_events, source_metadata = _load_gate_source(
        audit_events_path=audit_events_path,
        source_kind=source_kind,
        source_path=source_path,
        trace_id=trace_id,
        request_id=request_id,
    )
    result = AuditEvidenceVerifier().verify(
        _context_from_events(audit_events),
        {"audit_events": audit_events},
    )
    finding_codes = Counter(finding.code for finding in result.findings)
    report = AuditEvidenceGateReport(
        audit_events_path=source_metadata["audit_events_path"],
        source_kind=source_metadata["source_kind"],
        source_path=source_metadata["source_path"],
        trace_id=source_metadata["trace_id"],
        request_id=source_metadata["request_id"],
        verifier=result.verifier,
        passed=result.status == VerificationStatus.PASSED,
        summary={
            "event_count": result.metadata.get("event_count", len(audit_events)),
            "checked_event_count": result.metadata.get("checked_event_count", len(audit_events)),
            "finding_count": len(result.findings),
            "finding_codes": dict(sorted(finding_codes.items())),
            "status": result.status.value,
        },
        findings=[finding.model_dump(mode="json") for finding in result.findings],
    )
    if write_report:
        json_path, markdown_path = write_reports(report, output_dir=output_dir)
        report.report_json_path = json_path.as_posix()
        report.report_markdown_path = markdown_path.as_posix()
    return report


def load_audit_events(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return _load_jsonl(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [_require_event_dict(event, path.as_posix()) for event in payload]
    if isinstance(payload, dict) and isinstance(payload.get("audit_events"), list):
        return [_require_event_dict(event, path.as_posix()) for event in payload["audit_events"]]
    raise ValueError(f"Unsupported audit events JSON shape in {path}")


def _load_gate_source(
    *,
    audit_events_path: Path | None,
    source_kind: str | None,
    source_path: Path | None,
    trace_id: str | None,
    request_id: str | None,
) -> tuple[list[dict[str, Any]], dict[str, str | None]]:
    if audit_events_path is not None:
        if any(value is not None for value in (source_kind, source_path, trace_id, request_id)):
            raise ValueError("audit_events_path cannot be combined with trace source fields")
        return load_audit_events(audit_events_path), {
            "audit_events_path": audit_events_path.as_posix(),
            "source_kind": "audit_events",
            "source_path": audit_events_path.as_posix(),
            "trace_id": None,
            "request_id": None,
        }

    if source_kind is None or source_path is None or trace_id is None:
        raise ValueError("trace source requires source_kind, source_path, and trace_id")

    actual = AuditTraceExtractor().extract(
        TraceSource(
            kind=source_kind,
            path=source_path.as_posix(),
            trace_id=trace_id,
            request_id=request_id,
        )
    )
    return [event.model_dump(mode="json") for event in actual.audit_events], {
        "audit_events_path": None,
        "source_kind": source_kind,
        "source_path": source_path.as_posix(),
        "trace_id": trace_id,
        "request_id": request_id,
    }


def write_reports(
    report: AuditEvidenceGateReport,
    *,
    output_dir: Path | None = None,
) -> tuple[Path, Path]:
    report_dir = output_dir or REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    input_stem = Path(report.source_path or report.audit_events_path or report.source_kind).stem
    json_path = report_dir / f"audit_evidence_gate_{input_stem}_{timestamp}.json"
    markdown_path = report_dir / f"audit_evidence_gate_{input_stem}_{timestamp}.md"

    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-events", type=Path, default=None)
    parser.add_argument("--source-kind", choices=("jsonl", "sqlite"), default=None)
    parser.add_argument("--path", dest="source_path", type=Path, default=None)
    parser.add_argument("--trace-id", default=None)
    parser.add_argument("--request-id", default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    _validate_source_args(parser, args)

    report = run_audit_evidence_gate(
        audit_events_path=args.audit_events,
        source_kind=args.source_kind,
        source_path=args.source_path,
        trace_id=args.trace_id,
        request_id=args.request_id,
        output_dir=args.output_dir,
        write_report=not args.no_write,
    )
    summary = report.summary
    print(
        "audit_evidence_gate "
        f"gate_id={report.gate_id} "
        f"events={summary['event_count']} "
        f"findings={summary['finding_count']} "
        f"passed={str(report.passed).lower()}"
    )
    if report.report_json_path:
        print(f"json_report={report.report_json_path}")
    if report.report_markdown_path:
        print(f"markdown_report={report.report_markdown_path}")
    return 0 if report.passed else 1


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            events.append(_require_event_dict(json.loads(stripped), f"{path}:{line_number}"))
    return events


def _validate_source_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    has_audit_events = args.audit_events is not None
    has_trace_source_args = any(
        value is not None
        for value in (args.source_kind, args.source_path, args.trace_id, args.request_id)
    )
    if has_audit_events and has_trace_source_args:
        parser.error(
            "--audit-events cannot be combined with --source-kind/--path/--trace-id/--request-id"
        )
    if has_audit_events:
        return
    if args.source_kind is None or args.source_path is None or args.trace_id is None:
        parser.error("provide either --audit-events or --source-kind with --path and --trace-id")


def _require_event_dict(event: Any, source: str) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValueError(f"Invalid audit event in {source}: expected object")
    return dict(event)


def _context_from_events(events: list[dict[str, Any]]) -> RequestContext:
    first = events[0] if events else {}
    return RequestContext(
        request_id=str(first.get("request_id") or "audit-evidence-gate"),
        trace_id=str(first.get("trace_id") or "audit-evidence-gate"),
        user_id=str(first.get("user_id") or "audit-evidence-gate"),
        username=str(first.get("user_id") or "audit-evidence-gate"),
        department_id="offline_gate",
        department_name="Offline Gate",
        roles=["offline_gate"],
    )


def _render_markdown(report: AuditEvidenceGateReport) -> str:
    input_path = report.source_path or report.audit_events_path or "-"
    lines = [
        "# Audit Evidence Gate Report",
        "",
        f"- Gate: `{report.gate_id}`",
        f"- Input: `{input_path}`",
        f"- Source kind: `{report.source_kind}`",
        f"- Trace ID: `{report.trace_id or '-'}`",
        f"- Request ID: `{report.request_id or '-'}`",
        f"- Generated at: `{report.generated_at.isoformat()}`",
        f"- Verifier: `{report.verifier}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Event count: {report.summary.get('event_count', 0)}",
        f"- Finding count: {report.summary.get('finding_count', 0)}",
        f"- Finding codes: {_format_codes(report.summary.get('finding_codes', {}))}",
        "",
        "## Findings",
        "",
        "| code | message | metadata |",
        "|---|---|---|",
    ]
    if not report.findings:
        lines.append("| - | - | - |")
    else:
        for finding in report.findings:
            metadata = json.dumps(finding.get("metadata", {}), ensure_ascii=False, sort_keys=True)
            lines.append(
                f"| {finding.get('code', '')} | {finding.get('message', '')} | `{metadata}` |"
            )
    lines.append("")
    return "\n".join(lines)


def _format_codes(codes: dict[str, Any]) -> str:
    if not codes:
        return "-"
    return ", ".join(f"{code}={count}" for code, count in codes.items())


if __name__ == "__main__":
    raise SystemExit(main())
