"""Checklist 3 report freshness and gate summary helpers."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_REPORT_SPECS = [
    {
        "gate_id": "pdf_page_table_source_ref",
        "report_type": "pdf_page_table",
        "path": "evals/knowledge_base/reports/pdf_page_table_eval_b4_g4_20260609.json",
    },
    {
        "gate_id": "e1_permission_isolation",
        "report_type": "rag_permission",
        "path": "evals/knowledge_base/reports/department_rag_permission_isolation_b4_g5_20260609.json",
    },
    {
        "gate_id": "e1_scope_lock",
        "report_type": "rag_scope",
        "path": "evals/knowledge_base/reports/department_rag_scope_lock_b4_g5_20260609.json",
    },
    {
        "gate_id": "e1_citation_accuracy",
        "report_type": "rag_citation",
        "path": "evals/knowledge_base/reports/department_rag_citation_accuracy_b4_g5_20260609.json",
    },
]


def build_checklist3_gate_report(
    report_specs: list[dict[str, str]] | None = None,
    *,
    as_of: str | datetime | None = None,
    max_age_days: int = 7,
) -> dict[str, Any]:
    as_of_dt = _as_datetime(as_of) if as_of is not None else datetime.now(timezone.utc)
    rows = [_evaluate_report_spec(spec, as_of=as_of_dt, max_age_days=max_age_days) for spec in report_specs or DEFAULT_REPORT_SPECS]
    blockers = sorted({blocker for row in rows for blocker in row["blockers"]})
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of_dt.isoformat(),
        "max_age_days": max_age_days,
        "status": "passed" if not blockers else "failed",
        "summary": {
            "total_reports": len(rows),
            "fresh_reports": sum(1 for row in rows if row["freshness_status"] == "fresh"),
            "stale_reports": sum(1 for row in rows if row["freshness_status"] == "stale"),
            "missing_reports": sum(1 for row in rows if row["freshness_status"] == "missing"),
            "blocking_reports": sum(1 for row in rows if row["gate_status"] == "failed"),
            "blockers": blockers,
        },
        "reports": rows,
    }


def write_checklist3_gate_report(
    report_specs: list[dict[str, str]] | None = None,
    *,
    as_of: str | datetime | None = None,
    max_age_days: int = 7,
    output_json: str | Path,
    output_md: str | Path | None = None,
) -> dict[str, Any]:
    report = build_checklist3_gate_report(report_specs, as_of=as_of, max_age_days=max_age_days)
    output_json_path = Path(output_json)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if output_md is not None:
        output_md_path = Path(output_md)
        output_md_path.parent.mkdir(parents=True, exist_ok=True)
        output_md_path.write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Checklist 3 Gate Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- As of: `{report['as_of']}`",
        f"- Max age days: `{report['max_age_days']}`",
        f"- Status: `{report['status']}`",
        f"- Summary: {report['summary']}",
        "",
        "| gate_id | type | freshness | age_days | gate_status | blockers |",
        "|---|---|---|---:|---|---|",
    ]
    for row in report["reports"]:
        lines.append(
            "| {gate_id} | {report_type} | {freshness_status} | {age_days} | {gate_status} | {blockers} |".format(
                gate_id=row["gate_id"],
                report_type=row["report_type"],
                freshness_status=row["freshness_status"],
                age_days=row["age_days"],
                gate_status=row["gate_status"],
                blockers=", ".join(row["blockers"]) or "-",
            )
        )
    lines.append("")
    return "\n".join(lines)


def _evaluate_report_spec(
    spec: dict[str, str],
    *,
    as_of: datetime,
    max_age_days: int,
) -> dict[str, Any]:
    path = Path(spec["path"])
    base = {
        "gate_id": spec["gate_id"],
        "report_type": spec["report_type"],
        "path": path.as_posix(),
        "generated_at": "",
        "age_days": None,
        "freshness_status": "missing",
        "gate_status": "failed",
        "blockers": ["report_missing"],
        "summary": {},
    }
    if not path.exists():
        return base
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {**base, "freshness_status": "invalid", "blockers": ["report_invalid_json"]}

    summary = payload.get("summary") if isinstance(payload, dict) else {}
    summary = summary if isinstance(summary, dict) else {}
    generated_at = str(payload.get("generated_at") or "") if isinstance(payload, dict) else ""
    blockers = _freshness_blockers(generated_at, as_of=as_of, max_age_days=max_age_days)
    blockers.extend(_gate_blockers(spec["report_type"], summary))
    freshness_status = _freshness_status(blockers)
    return {
        **base,
        "generated_at": generated_at,
        "age_days": _age_days(generated_at, as_of),
        "freshness_status": freshness_status,
        "gate_status": "passed" if not blockers else "failed",
        "blockers": blockers,
        "summary": summary,
    }


def _freshness_blockers(generated_at: str, *, as_of: datetime, max_age_days: int) -> list[str]:
    if not generated_at:
        return ["generated_at_missing"]
    try:
        generated = _as_datetime(generated_at)
    except ValueError:
        return ["generated_at_invalid"]
    age_seconds = (as_of - generated).total_seconds()
    if age_seconds < 0:
        return ["generated_at_in_future"]
    if age_seconds > max_age_days * 24 * 60 * 60:
        return ["report_stale"]
    return []


def _age_days(generated_at: str, as_of: datetime) -> float | None:
    if not generated_at:
        return None
    try:
        generated = _as_datetime(generated_at)
    except ValueError:
        return None
    return round((as_of - generated).total_seconds() / 86400, 4)


def _freshness_status(blockers: list[str]) -> str:
    freshness_blockers = {
        "generated_at_missing",
        "generated_at_invalid",
        "generated_at_in_future",
    }
    if "report_stale" in blockers:
        return "stale"
    if any(blocker in blockers for blocker in freshness_blockers):
        return "invalid"
    return "fresh"


def _gate_blockers(report_type: str, summary: dict[str, Any]) -> list[str]:
    if report_type == "pdf_page_table":
        return _pdf_page_table_blockers(summary)
    if report_type == "rag_permission":
        return _rag_common_blockers(summary) + _rag_permission_blockers(summary)
    if report_type == "rag_scope":
        return _rag_common_blockers(summary)
    if report_type == "rag_citation":
        return _rag_common_blockers(summary)
    return ["unknown_report_type"]


def _pdf_page_table_blockers(summary: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    total = int(summary.get("total") or 0)
    if total <= 0:
        blockers.append("pdf_total_zero")
    if int(summary.get("artifact_missing_count") or 0) != 0:
        blockers.append("artifact_missing_count_nonzero")
    for key, blocker in (
        ("page_accuracy_passed", "page_accuracy_not_all_passed"),
        ("table_presence_passed", "table_presence_not_all_passed"),
        ("source_ref_resolvable_passed", "source_ref_not_all_resolvable"),
    ):
        if total <= 0 or int(summary.get(key) or 0) != total:
            blockers.append(blocker)
    return blockers


def _rag_common_blockers(summary: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if int(summary.get("total") or 0) <= 0:
        blockers.append("rag_total_zero")
    if int(summary.get("not_ready") or 0) != 0:
        blockers.append("not_ready_nonzero")
    if int(summary.get("asset_blocked") or 0) != 0:
        blockers.append("asset_blocked_nonzero")
    if int(summary.get("wrong_scope_count") or 0) != 0:
        blockers.append("wrong_scope_count_nonzero")
    if int(summary.get("citation_unresolvable_count") or 0) != 0:
        blockers.append("citation_unresolvable_count_nonzero")
    if summary.get("all_source_ref_resolvable") is not True:
        blockers.append("source_ref_not_all_resolvable")
    return blockers


def _rag_permission_blockers(summary: dict[str, Any]) -> list[str]:
    total = int(summary.get("total") or 0)
    permission_filtered_passed = int(summary.get("permission_filtered_passed") or 0)
    if total <= 0 or permission_filtered_passed != total:
        return ["permission_filtered_not_all_passed"]
    return []


def _as_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _load_report_specs(path: str | Path | None) -> list[dict[str, str]] | None:
    if not path:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("reports") or payload.get("report_specs") or []
    if not isinstance(payload, list):
        raise ValueError("report spec file must contain a list or {reports: [...]}")
    return [dict(item) for item in payload]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Checklist 3 report freshness and gate summary.")
    parser.add_argument("--report-specs", default="", help="Optional JSON file with report spec list.")
    parser.add_argument("--as-of", default="", help="ISO timestamp used for freshness checks.")
    parser.add_argument("--max-age-days", type=int, default=7)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()
    report = write_checklist3_gate_report(
        _load_report_specs(args.report_specs),
        as_of=args.as_of or None,
        max_age_days=args.max_age_days,
        output_json=args.output_json,
        output_md=args.output_md or None,
    )
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
