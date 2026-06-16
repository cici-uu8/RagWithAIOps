"""Run the 12-query boundary test against HTTP chat plus direct retrieval."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from app.models import RetrievalMode, RetrievalQuery
from app.services.retrieval_service import retrieval_service

DEFAULT_EVALSET = "evals/knowledge_base/evalsets/boundary_test_12q.jsonl"
DEFAULT_OUTPUT = "evals/knowledge_base/reports"


def load_evalset(path: str | Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        for field in ("sample_id", "query", "allowed_kb_ids", "doc_policy"):
            if field not in row:
                raise ValueError(f"{path}:{line_number} missing {field}")
        cases.append(row)
    if not cases:
        raise ValueError(f"empty evalset: {path}")
    return cases


def login(base_url: str, username: str, password: str, timeout: int) -> str:
    response = requests.post(
        f"{base_url}/auth/login",
        json={"username": username, "password": password},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    return str(payload["data"]["access_token"])


def call_chat(
    *,
    base_url: str,
    token: str,
    case: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    response = requests.post(
        f"{base_url}/chat",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Trace-Id": f"boundary-{case['sample_id'].lower()}",
        },
        json={
            "Id": f"boundary_{case['sample_id'].lower()}",
            "Question": case["query"],
            "SelectedKbIds": list(case.get("allowed_kb_ids") or []),
            "ScopeSource": "user_selected",
        },
        timeout=timeout,
    )
    row: dict[str, Any] = {
        "status_code": response.status_code,
        "ok": response.ok,
        "answer": "",
        "answer_chars": 0,
        "query_intent_diagnostics": None,
        "error": "",
    }
    try:
        payload = response.json()
    except ValueError:
        row["error"] = response.text[:1000]
        return row

    if not response.ok:
        row["error"] = json.dumps(payload, ensure_ascii=False)[:1000]
        return row

    data = payload.get("data") or {}
    answer = str(data.get("answer") or "")
    row.update(
        {
            "answer": answer,
            "answer_chars": len(answer),
            "query_intent_diagnostics": data.get("query_intent_diagnostics"),
            "trace_id": data.get("trace_id", ""),
        }
    )
    return row


def run_direct_retrieval(case: dict[str, Any], retrieval_mode: RetrievalMode) -> dict[str, Any]:
    query = RetrievalQuery(
        query=str(case["query"]),
        top_k=int(case.get("top_k") or 3),
        retrieval_mode=retrieval_mode,
        knowledge_base_ids=list(case.get("allowed_kb_ids") or []),
    )
    try:
        response = retrieval_service.retrieve(query)
    except Exception as exc:  # noqa: BLE001 - report external infra failures
        return {
            "status": "not_ready",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "actual_doc_ids": [],
            "actual_source_files": [],
            "actual_kb_ids": [],
            "result_count": 0,
        }

    return {
        "status": "ok",
        "error_type": "",
        "error": "",
        "result_count": len(response.results),
        "actual_doc_ids": [result.doc_id for result in response.results],
        "actual_source_files": [
            result.source_ref.source_file if result.source_ref else ""
            for result in response.results
        ],
        "actual_kb_ids": [result.kb_id for result in response.results],
        "results": [
            {
                "rank": index + 1,
                "doc_id": result.doc_id,
                "kb_id": result.kb_id,
                "source_file": result.source_ref.source_file if result.source_ref else "",
                "chunk_id": result.chunk_id,
                "score": result.score,
            }
            for index, result in enumerate(response.results)
        ],
    }


def judge_case(case: dict[str, Any], retrieval: dict[str, Any], http: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    notes: list[str] = []

    doc_ok = judge_docs(case, retrieval, issues, notes)
    intent_ok = judge_intent(case, http, issues, notes)
    answer_ok = judge_answer(case, http, issues, notes)

    if not http.get("ok"):
        issues.append("http_call_failed")
    if retrieval.get("status") != "ok":
        issues.append("retrieval_not_ready")

    hard_fail_issues = {
        "intent_misroute",
        "wrong_scope",
        "retrieval_wrong_doc",
        "retrieval_no_hit",
        "answer_hallucination",
        "permission_not_blocked",
        "http_call_failed",
        "retrieval_not_ready",
    }
    if any(issue in hard_fail_issues for issue in issues):
        verdict = "FAIL"
    elif doc_ok and intent_ok and answer_ok:
        verdict = "PASS"
    else:
        verdict = "PARTIAL"

    if case.get("manual_followup") and verdict == "PASS":
        verdict = "PARTIAL"
        issues.append("manual_followup_required")
        notes.append("This case has table/tool/UX criteria that the HTTP response alone cannot fully prove.")

    return {
        "verdict": verdict,
        "doc_ok": doc_ok,
        "intent_ok": intent_ok,
        "answer_ok": answer_ok,
        "issues": sorted(set(issues)),
        "notes": notes,
    }


def judge_docs(
    case: dict[str, Any],
    retrieval: dict[str, Any],
    issues: list[str],
    notes: list[str],
) -> bool:
    if retrieval.get("status") != "ok":
        return False

    policy = str(case.get("doc_policy") or "any")
    expected = set(case.get("expected_doc_ids") or [])
    actual = set(retrieval.get("actual_doc_ids") or [])
    actual_kb_ids = set(retrieval.get("actual_kb_ids") or [])
    forbidden_kb_ids = set(case.get("forbidden_kb_ids") or [])

    if forbidden_kb_ids & actual_kb_ids:
        issues.append("wrong_scope")
        return False
    if policy == "all":
        missing = sorted(expected - actual)
        if missing:
            issues.append("retrieval_wrong_doc" if actual else "retrieval_no_hit")
            notes.append(f"Missing expected docs: {missing}")
            return False
        return True
    if policy == "any":
        if expected and not (expected & actual):
            issues.append("retrieval_wrong_doc" if actual else "retrieval_no_hit")
            return False
        return True
    if policy == "none":
        if retrieval.get("result_count", 0) > 0:
            issues.append("retrieval_wrong_doc")
            return False
        return True
    if policy == "blocked":
        if forbidden_kb_ids & actual_kb_ids:
            issues.append("wrong_scope")
            return False
        return True
    if policy == "optional":
        return True
    notes.append(f"Unknown doc_policy={policy}")
    return False


def judge_intent(case: dict[str, Any], http: dict[str, Any], issues: list[str], notes: list[str]) -> bool:
    expected_intent = str(case.get("expected_intent") or "")
    if not expected_intent:
        return True
    diagnostics = http.get("query_intent_diagnostics") or {}
    actual_intent = str(diagnostics.get("intent") or "")
    if actual_intent != expected_intent:
        issues.append("intent_misroute")
        notes.append(f"Expected intent={expected_intent}, actual intent={actual_intent or 'none'}")
        if expected_intent == "human_review":
            issues.append("permission_not_blocked")
        return False
    return True


def judge_answer(case: dict[str, Any], http: dict[str, Any], issues: list[str], notes: list[str]) -> bool:
    answer = str(http.get("answer") or "")
    if not answer:
        issues.append("answer_incomplete")
        return False

    policy = str(case.get("doc_policy") or "")
    if policy in {"all", "any"} and _claims_missing_context(answer):
        issues.append("answer_incomplete")
        notes.append("Answer says no direct/related knowledge was found even though this case expects indexed docs.")
        return False
    if policy in {"all", "any"} and _looks_like_unrelated_document_listing(answer):
        issues.append("answer_incomplete")
        notes.append("Answer lists unrelated/default documents instead of answering from the expected source.")
        return False

    forbidden_hits = [marker for marker in case.get("forbidden_markers") or [] if contains(answer, marker)]
    if forbidden_hits:
        issues.append("answer_hallucination")
        notes.append(f"Forbidden answer markers: {forbidden_hits}")
        return False

    markers = list(case.get("answer_markers") or [])
    required = int(case.get("answer_marker_min") or 0)
    marker_hits = [marker for marker in markers if contains(answer, marker)]
    boundary_markers = list(case.get("scope_boundary_markers") or [])
    boundary_hits = [marker for marker in boundary_markers if contains(answer, marker)]
    ok = len(marker_hits) >= required
    if boundary_markers and not boundary_hits:
        issues.append("answer_incomplete")
        notes.append("Scope-boundary wording was not found in the answer.")
        ok = False
    if not ok:
        issues.append("answer_incomplete")
        notes.append(f"Answer marker hits {len(marker_hits)}/{required}: {marker_hits}")
    return ok


def contains(text: str, marker: str) -> bool:
    return marker.casefold() in text.casefold()


def _claims_missing_context(answer: str) -> bool:
    markers = (
        "没有找到直接",
        "没有直接",
        "没有找到与",
        "知识库中没有",
        "当前访问的知识库中没有",
        "没有找到相关信息",
        "参考资料不足",
    )
    return any(marker in answer for marker in markers)


def _looks_like_unrelated_document_listing(answer: str) -> bool:
    return "文件名:" in answer and "x.md" in answer


def build_report(
    *,
    evalset_path: str | Path,
    cases: list[dict[str, Any]],
    base_url: str,
    retrieval_mode: RetrievalMode,
    username: str,
    password: str,
    timeout: int,
    http_enabled: bool,
    http_login_error: str,
) -> dict[str, Any]:
    token = ""
    if http_enabled:
        try:
            token = login(base_url, username, password, timeout)
        except Exception as exc:  # noqa: BLE001 - report login failures
            http_login_error = f"{type(exc).__name__}: {exc}"
            http_enabled = False

    results: list[dict[str, Any]] = []
    for case in cases:
        retrieval = run_direct_retrieval(case, retrieval_mode)
        if http_enabled:
            try:
                http = call_chat(base_url=base_url, token=token, case=case, timeout=timeout)
            except Exception as exc:  # noqa: BLE001 - report runtime failure per case
                http = {
                    "status_code": 0,
                    "ok": False,
                    "answer": "",
                    "answer_chars": 0,
                    "query_intent_diagnostics": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
        else:
            http = {
                "status_code": 0,
                "ok": False,
                "answer": "",
                "answer_chars": 0,
                "query_intent_diagnostics": None,
                "error": http_login_error or "HTTP disabled",
            }
        judgment = judge_case(case, retrieval, http)
        results.append(
            {
                "sample_id": case["sample_id"],
                "role": case.get("role", ""),
                "query": case["query"],
                "expected_behavior": case.get("expected_behavior", ""),
                "retrieval": retrieval,
                "http_chat": http,
                "judgment": judgment,
            }
        )

    verdict_counts = Counter(row["judgment"]["verdict"] for row in results)
    issue_counts = Counter(issue for row in results for issue in row["judgment"]["issues"])
    return {
        "report_name": "boundary_test_12q",
        "evalset_path": str(evalset_path),
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {
            "http_chat_url": f"{base_url}/chat",
            "http_enabled": http_enabled,
            "http_login_user": username if http_enabled else "",
            "http_login_error": http_login_error,
            "selected_kb_ids": ["process_digital_dept"],
            "scope_source": "user_selected",
            "retrieval_mode": retrieval_mode.value,
            "top_k": 3,
            "uses_frontend_browser": False,
            "uses_manual_human_review": False,
        },
        "summary": {
            "total": len(results),
            "verdict_counts": dict(verdict_counts),
            "issue_counts": dict(issue_counts),
            "retrieval_wrong_or_no_hit": issue_counts.get("retrieval_wrong_doc", 0)
            + issue_counts.get("retrieval_no_hit", 0),
            "answer_incomplete": issue_counts.get("answer_incomplete", 0),
            "permission_or_scope_issue": issue_counts.get("wrong_scope", 0)
            + issue_counts.get("permission_not_blocked", 0),
            "thresholds": {
                "reopen_retrieval_triage": (
                    issue_counts.get("retrieval_wrong_doc", 0)
                    + issue_counts.get("retrieval_no_hit", 0)
                )
                >= 3,
                "reopen_answer_revisit": issue_counts.get("answer_incomplete", 0) >= 3,
                "fix_permission_or_source_ref_bug_now": (
                    issue_counts.get("wrong_scope", 0)
                    + issue_counts.get("permission_not_blocked", 0)
                )
                > 0,
            },
        },
        "results": results,
    }


def write_report(report: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output / f"boundary_test_12q_{stamp}.json"
    md_path = output / f"boundary_test_12q_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"report_json_path": str(json_path), "report_markdown_path": str(md_path)}


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Boundary Test 12Q Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Evalset: `{report['evalset_path']}`",
        f"- HTTP chat: `{report['scope']['http_chat_url']}`",
        f"- Retrieval mode: `{report['scope']['retrieval_mode']}`",
        f"- Selected KB: `process_digital_dept`",
        f"- Verdict counts: `{summary['verdict_counts']}`",
        f"- Issue counts: `{summary['issue_counts']}`",
        f"- Thresholds: `{summary['thresholds']}`",
        "",
        "## Results",
        "",
        "| ID | Verdict | Issues | Retrieval docs | Intent | Answer chars |",
        "|---|---|---|---|---|---:|",
    ]
    for row in report["results"]:
        diagnostics = row["http_chat"].get("query_intent_diagnostics") or {}
        lines.append(
            "| {sample_id} | {verdict} | {issues} | {docs} | {intent} | {chars} |".format(
                sample_id=row["sample_id"],
                verdict=row["judgment"]["verdict"],
                issues=", ".join(row["judgment"]["issues"]) or "-",
                docs=", ".join(row["retrieval"].get("actual_source_files") or []) or "-",
                intent=diagnostics.get("intent") or "-",
                chars=row["http_chat"].get("answer_chars", 0),
            )
        )
    lines.extend(["", "## Notes", ""])
    for row in report["results"]:
        if row["judgment"]["notes"]:
            lines.append(f"- {row['sample_id']}: " + " / ".join(row["judgment"]["notes"]))
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the 12Q boundary eval.")
    parser.add_argument("--evalset", default=DEFAULT_EVALSET)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    parser.add_argument("--base-url", default="http://127.0.0.1:9900/api")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="Admin123!")
    parser.add_argument("--retrieval-mode", default="dense_only")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--no-http", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    retrieval_mode = RetrievalMode(args.retrieval_mode)
    report = build_report(
        evalset_path=args.evalset,
        cases=load_evalset(args.evalset),
        base_url=args.base_url.rstrip("/"),
        retrieval_mode=retrieval_mode,
        username=args.username,
        password=args.password,
        timeout=args.timeout,
        http_enabled=not args.no_http,
        http_login_error="",
    )
    written = write_report(report, args.output_dir)
    report.update(written)
    print(json.dumps({"summary": report["summary"], **written}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
