"""Checklist 3 eval coverage inventory helpers."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_EVALSET_SPECS = [
    {
        "coverage_id": "e1_permission_isolation",
        "eval_type": "permission",
        "path": "<local-approved-evalset>",
    },
    {
        "coverage_id": "e1_scope_lock",
        "eval_type": "scope",
        "path": "<local-approved-evalset>",
    },
    {
        "coverage_id": "e1_citation_accuracy",
        "eval_type": "citation",
        "path": "<local-approved-evalset>",
    },
    {
        "coverage_id": "pdf_page_table_source_ref",
        "eval_type": "pdf_page_table",
        "path": "<local-approved-evalset>",
    },
]

DEFAULT_PDF_SMOKE_REPORT = "evals/knowledge_base/reports/pdf_agent_tool_smoke_b4_g7_local_enabled_20260609.json"


def build_checklist3_eval_coverage_report(
    evalset_specs: list[dict[str, str]] | None = None,
    *,
    pdf_smoke_report: str | Path | None = DEFAULT_PDF_SMOKE_REPORT,
) -> dict[str, Any]:
    rows = [_evaluate_evalset_spec(spec) for spec in evalset_specs or DEFAULT_EVALSET_SPECS]
    smoke = _evaluate_pdf_smoke_report(pdf_smoke_report)
    summary = _build_summary(rows, smoke)
    gaps = _coverage_gaps(summary)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "needs_expansion" if gaps else "covered",
        "summary": summary,
        "coverage_gaps": gaps,
        "evalsets": rows,
        "pdf_smoke": smoke,
    }


def write_checklist3_eval_coverage_report(
    evalset_specs: list[dict[str, str]] | None = None,
    *,
    pdf_smoke_report: str | Path | None = DEFAULT_PDF_SMOKE_REPORT,
    output_json: str | Path,
    output_md: str | Path | None = None,
) -> dict[str, Any]:
    report = build_checklist3_eval_coverage_report(
        evalset_specs,
        pdf_smoke_report=pdf_smoke_report,
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
    lines = [
        "# Checklist 3 Eval Coverage Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Status: `{report['status']}`",
        f"- Summary: {report['summary']}",
        f"- Coverage gaps: {report['coverage_gaps'] or []}",
        "",
        "| coverage_id | type | samples | kb_ids | doc_ids | key coverage | issues |",
        "|---|---|---:|---|---|---|---|",
    ]
    for row in report["evalsets"]:
        lines.append(
            "| {coverage_id} | {eval_type} | {sample_count} | {kb_ids} | {doc_ids} | {key_coverage} | {issues} |".format(
                coverage_id=row["coverage_id"],
                eval_type=row["eval_type"],
                sample_count=row["sample_count"],
                kb_ids=", ".join(row["kb_ids"]) or "-",
                doc_ids=", ".join(row["doc_ids"]) or "-",
                key_coverage=", ".join(row["key_coverage"]) or "-",
                issues=", ".join(row["issues"]) or "-",
            )
        )
    lines.extend(
        [
            "",
            "## PDF Smoke Coverage",
            "",
            f"- Status: `{report['pdf_smoke']['status']}`",
            f"- Checks: {report['pdf_smoke']['checks']}",
            "",
        ]
    )
    return "\n".join(lines)


def _evaluate_evalset_spec(spec: dict[str, str]) -> dict[str, Any]:
    path = Path(spec["path"])
    base = {
        "coverage_id": spec["coverage_id"],
        "eval_type": spec["eval_type"],
        "path": path.as_posix(),
        "status": "missing",
        "sample_count": 0,
        "kb_ids": [],
        "doc_ids": [],
        "retrieval_modes": [],
        "expected_failures": [],
        "key_coverage": [],
        "issues": ["evalset_missing"],
    }
    if not path.exists():
        return base
    samples = _load_samples(path)
    return _summarize_samples(
        samples,
        coverage_id=spec["coverage_id"],
        eval_type=spec["eval_type"],
        path=path,
    )


def _summarize_samples(
    samples: list[dict[str, Any]],
    *,
    coverage_id: str,
    eval_type: str,
    path: Path,
) -> dict[str, Any]:
    kb_ids = sorted(_collect_values(samples, "allowed_kb_ids") | _collect_values(samples, "kb_id"))
    doc_ids = sorted(_collect_values(samples, "expected_doc_ids") | _collect_values(samples, "doc_id"))
    expected_failures = sorted(str(sample.get("expected_failure")) for sample in samples if sample.get("expected_failure"))
    retrieval_modes = sorted(str(sample.get("retrieval_mode")) for sample in samples if sample.get("retrieval_mode"))
    key_coverage = _key_coverage(samples, eval_type)
    issues = _evalset_issues(samples, eval_type, doc_ids)
    return {
        "coverage_id": coverage_id,
        "eval_type": eval_type,
        "path": path.as_posix(),
        "status": "loaded",
        "sample_count": len(samples),
        "kb_ids": kb_ids,
        "doc_ids": doc_ids,
        "retrieval_modes": retrieval_modes,
        "expected_failures": expected_failures,
        "key_coverage": key_coverage,
        "issues": issues,
        "sample_ids": [str(sample.get("sample_id") or "") for sample in samples],
    }


def _key_coverage(samples: list[dict[str, Any]], eval_type: str) -> list[str]:
    coverage: list[str] = []
    if any(sample.get("expected_failure") == "permission_filtered" for sample in samples):
        coverage.append("permission_filtered")
    if any(sample.get("retrieved_must_not_contain_kb") for sample in samples):
        coverage.append("wrong_scope_guard")
    if any(sample.get("citation_must_resolvable") is True for sample in samples):
        coverage.append("citation_resolvable")
    if any(sample.get("expected_source_ref_fields") for sample in samples):
        coverage.append("source_ref_fields")
    if eval_type == "pdf_page_table" and samples:
        coverage.append("pdf_page")
        if any(sample.get("expected_table_id") for sample in samples):
            coverage.append("pdf_table")
    return coverage


def _evalset_issues(samples: list[dict[str, Any]], eval_type: str, doc_ids: list[str]) -> list[str]:
    issues: list[str] = []
    if not samples:
        issues.append("no_samples")
    if eval_type in {"permission", "scope", "citation"} and len(samples) < 10:
        issues.append("small_e1_evalset")
    if eval_type == "pdf_page_table":
        if len(samples) < 3:
            issues.append("pdf_eval_sample_count_below_3")
        if len(doc_ids) < 2:
            issues.append("pdf_eval_single_doc")
    if eval_type == "permission" and not any(sample.get("expected_failure") == "permission_filtered" for sample in samples):
        issues.append("permission_filtered_not_covered")
    if eval_type == "scope" and not any(sample.get("retrieved_must_not_contain_kb") for sample in samples):
        issues.append("wrong_scope_guard_not_covered")
    if eval_type == "citation" and not any(sample.get("citation_must_resolvable") is True for sample in samples):
        issues.append("citation_resolvable_not_covered")
    return issues


def _evaluate_pdf_smoke_report(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {
            "path": "",
            "status": "not_configured",
            "checks": {},
            "issues": ["pdf_smoke_report_not_configured"],
        }
    report_path = Path(path)
    if not report_path.exists():
        return {
            "path": report_path.as_posix(),
            "status": "missing",
            "checks": {},
            "issues": ["pdf_smoke_report_missing"],
        }
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    checks = {
        "schema_safe": bool(payload.get("schema_has_no_context_or_owner")),
        "authorized_page_success": _status(payload.get("authorized_page_read")) == "success",
        "authorized_table_success": _status(payload.get("authorized_table_extract")) == "success",
        "denied_page_no_leak": _permission_denied_no_leak(payload.get("denied_page_read")),
        "denied_table_no_leak": _permission_denied_no_leak(payload.get("denied_table_extract")),
    }
    issues = [f"{key}_not_covered" for key, value in checks.items() if not value]
    return {
        "path": report_path.as_posix(),
        "status": "loaded",
        "stage": payload.get("stage", ""),
        "doc_id": payload.get("doc_id", ""),
        "checks": checks,
        "issues": issues,
    }


def _build_summary(rows: list[dict[str, Any]], smoke: dict[str, Any]) -> dict[str, Any]:
    eval_type_counts = Counter(row["eval_type"] for row in rows)
    sample_counts = {row["coverage_id"]: row["sample_count"] for row in rows}
    pdf_rows = [row for row in rows if row["eval_type"] == "pdf_page_table"]
    kb_ids = sorted({kb_id for row in rows for kb_id in row["kb_ids"]})
    doc_ids = sorted({doc_id for row in rows for doc_id in row["doc_ids"]})
    key_coverage = sorted({item for row in rows for item in row["key_coverage"]})
    return {
        "total_evalsets": len(rows),
        "total_samples": sum(row["sample_count"] for row in rows),
        "eval_type_counts": dict(eval_type_counts),
        "sample_counts": sample_counts,
        "kb_ids": kb_ids,
        "doc_ids": doc_ids,
        "pdf_page_table_doc_count": len({doc_id for row in pdf_rows for doc_id in row["doc_ids"]}),
        "key_coverage": key_coverage,
        "pdf_smoke_denied_no_leak": bool(
            smoke.get("checks", {}).get("denied_page_no_leak")
            and smoke.get("checks", {}).get("denied_table_no_leak")
        ),
        "pdf_smoke_schema_safe": bool(smoke.get("checks", {}).get("schema_safe")),
    }


def _coverage_gaps(summary: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    sample_counts = summary["sample_counts"]
    if sample_counts.get("pdf_page_table_source_ref", 0) < 3:
        gaps.append("pdf_page_table_eval_needs_more_samples")
    if int(summary.get("pdf_page_table_doc_count") or 0) < 2:
        gaps.append("pdf_page_table_eval_needs_more_docs")
    if "pdf_table" not in summary["key_coverage"]:
        gaps.append("pdf_table_eval_not_covered")
    if not summary["pdf_smoke_denied_no_leak"]:
        gaps.append("pdf_tool_denied_no_leak_smoke_missing")
    if not summary["pdf_smoke_schema_safe"]:
        gaps.append("pdf_tool_schema_safety_smoke_missing")
    if sample_counts.get("e1_permission_isolation", 0) < 10:
        gaps.append("permission_eval_too_small")
    if sample_counts.get("e1_scope_lock", 0) < 10:
        gaps.append("scope_eval_too_small")
    if sample_counts.get("e1_citation_accuracy", 0) < 10:
        gaps.append("citation_eval_too_small")
    return gaps


def _status(value: Any) -> str:
    return str(value.get("status") or "") if isinstance(value, dict) else ""


def _permission_denied_no_leak(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return (
        value.get("status") == "error"
        and value.get("error") == "permission_denied"
        and value.get("leak_detected") is False
    )


def _collect_values(samples: list[dict[str, Any]], key: str) -> set[str]:
    values: set[str] = set()
    for sample in samples:
        value = sample.get(key)
        if isinstance(value, list):
            values.update(str(item) for item in value if item)
        elif value:
            values.add(str(value))
    return values


def _load_samples(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [dict(item) for item in payload]
    return [dict(item) for item in payload.get("samples") or []]


def _load_evalset_specs(path: str | Path | None) -> list[dict[str, str]] | None:
    if not path:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("evalsets") or payload.get("evalset_specs") or []
    if not isinstance(payload, list):
        raise ValueError("evalset spec file must contain a list or {evalsets: [...]}")
    return [dict(item) for item in payload]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Checklist 3 eval coverage inventory report.")
    parser.add_argument("--evalset-specs", default="", help="Optional JSON file with evalset spec list.")
    parser.add_argument("--pdf-smoke-report", default=DEFAULT_PDF_SMOKE_REPORT)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()
    write_checklist3_eval_coverage_report(
        _load_evalset_specs(args.evalset_specs),
        pdf_smoke_report=args.pdf_smoke_report,
        output_json=args.output_json,
        output_md=args.output_md or None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
