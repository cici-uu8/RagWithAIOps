"""Checklist 3 long-log tool-result offload shadow report.

The report uses synthetic long tool output and a temporary SQLite DB. It
exercises the real AIOps offload helper without enabling offload globally and
without writing to the real session database.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from app.agent.aiops.executor import maybe_offload_aiops_step_result
from app.models.session_memory import utc_now
from app.services.session_memory_store import SessionToolResultOffloadStore

DEFAULT_SESSION_ID = "checklist3-long-log-session"
DEFAULT_OWNER_ID = "checklist3-owner"
DEFAULT_OTHER_OWNER_ID = "checklist3-other-owner"
DEFAULT_TASK = "查询 checkout-service 长日志"
DEFAULT_RESULT_BYTES = 12 * 1024
DEFAULT_THRESHOLD = 2000
DEFAULT_MAX_BYTES = 200000
RESULT_REF_PATTERN = re.compile(r"tool_result:[0-9a-f]+")
TAIL_SENTINEL = "CHECKLIST3_FULL_LOG_TAIL_SENTINEL"


def build_checklist3_long_log_offload_shadow_report(
    *,
    session_id: str = DEFAULT_SESSION_ID,
    owner_id: str = DEFAULT_OWNER_ID,
    other_owner_id: str = DEFAULT_OTHER_OWNER_ID,
    task: str = DEFAULT_TASK,
    result_bytes: int = DEFAULT_RESULT_BYTES,
    threshold: int = DEFAULT_THRESHOLD,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    long_result = _build_long_result(result_bytes)
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "checklist3_tool_offload.sqlite"
        state = {
            "plan": [task],
            "past_steps": [],
            "session_id": session_id,
            "memory_owner_id": owner_id,
            "memory_store_path": str(db_path),
        }
        with (
            patch("app.agent.aiops.executor.config.tool_result_offload_enabled", True),
            patch("app.agent.aiops.executor.config.tool_result_offload_threshold", threshold),
            patch("app.agent.aiops.executor.config.tool_result_offload_max_bytes", max_bytes),
        ):
            prompt_result = maybe_offload_aiops_step_result(
                state=state,
                task=task,
                result=long_result,
            )

        store = SessionToolResultOffloadStore(db_path)
        result_ref = _extract_result_ref(prompt_result)
        owner_record = (
            store.get_result(result_ref, owner_id=owner_id) if result_ref else None
        )
        other_owner_record = (
            store.get_result(result_ref, owner_id=other_owner_id) if result_ref else None
        )
        json_compatible = _json_compatible(task, prompt_result)

    long_log = {
        "definition": "original_result_bytes > 10240",
        "original_result_bytes": len(long_result.encode("utf-8")),
        "threshold": threshold,
        "max_bytes": max_bytes,
        "definition_met": len(long_result.encode("utf-8")) > 10 * 1024,
        "exceeds_threshold": len(long_result) > threshold,
        "within_max_bytes": len(long_result.encode("utf-8")) <= max_bytes,
    }
    prompt_payload = {
        "is_string": isinstance(prompt_result, str),
        "json_string_compatible": json_compatible,
        "result_ref_present": bool(result_ref),
        "result_ref_prefix": "tool_result" if result_ref else "",
        "prompt_chars": len(prompt_result),
        "contains_offload_notice": "完整工具结果已 offload" in prompt_result,
        "tail_sentinel_leaked": TAIL_SENTINEL in prompt_result,
        "equals_original_result": prompt_result == long_result,
    }
    retrieval = {
        "owner_can_read_full_original": (
            owner_record is not None and owner_record.content == long_result
        ),
        "other_owner_can_read": other_owner_record is not None,
        "stored_content_bytes": (
            len(owner_record.content.encode("utf-8")) if owner_record is not None else 0
        ),
        "stored_summary_chars": len(owner_record.summary) if owner_record is not None else 0,
        "stored_tool_name": owner_record.tool_name if owner_record is not None else "",
    }
    evidence = {
        "summary_only_state": not retrieval["owner_can_read_full_original"],
        "full_original_preserved": retrieval["owner_can_read_full_original"],
        "cross_owner_denied": not retrieval["other_owner_can_read"],
        "report_leaks_full_tail": TAIL_SENTINEL in json.dumps(
            {
                "long_log": long_log,
                "prompt_payload": prompt_payload,
                "retrieval": retrieval,
            },
            ensure_ascii=False,
        ),
    }
    checks = [
        long_log["definition_met"],
        long_log["exceeds_threshold"],
        long_log["within_max_bytes"],
        prompt_payload["is_string"],
        prompt_payload["json_string_compatible"],
        prompt_payload["result_ref_present"],
        prompt_payload["contains_offload_notice"],
        not prompt_payload["tail_sentinel_leaked"],
        not prompt_payload["equals_original_result"],
        retrieval["owner_can_read_full_original"],
        evidence["cross_owner_denied"],
        not evidence["summary_only_state"],
        not evidence["report_leaks_full_tail"],
    ]
    gaps = _gaps(
        long_log=long_log,
        prompt_payload=prompt_payload,
        retrieval=retrieval,
        evidence=evidence,
    )
    return {
        "generated_at": utc_now().isoformat(),
        "status": "passed" if all(checks) else "failed",
        "scope": {
            "phase": "S3-P1.4",
            "report_kind": "long_log_tool_offload_shadow",
            "uses_synthetic_data": True,
            "uses_temp_db": True,
            "writes_real_session_db": False,
            "changes_runtime_config": False,
        },
        "config_under_test": {
            "tool_result_offload_enabled": True,
            "threshold": threshold,
            "max_bytes": max_bytes,
        },
        "long_log": long_log,
        "prompt_payload": prompt_payload,
        "retrieval": retrieval,
        "evidence": evidence,
        "gaps": gaps,
    }


def write_checklist3_long_log_offload_shadow_report(
    *,
    output_json: str | Path,
    output_md: str | Path | None = None,
    session_id: str = DEFAULT_SESSION_ID,
    owner_id: str = DEFAULT_OWNER_ID,
    other_owner_id: str = DEFAULT_OTHER_OWNER_ID,
    task: str = DEFAULT_TASK,
    result_bytes: int = DEFAULT_RESULT_BYTES,
    threshold: int = DEFAULT_THRESHOLD,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    report = build_checklist3_long_log_offload_shadow_report(
        session_id=session_id,
        owner_id=owner_id,
        other_owner_id=other_owner_id,
        task=task,
        result_bytes=result_bytes,
        threshold=threshold,
        max_bytes=max_bytes,
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


def _build_long_result(result_bytes: int) -> str:
    target = max(0, int(result_bytes))
    line = (
        "2026-06-09T12:00:00Z checkout-service INFO synthetic long log "
        "owner scoped evidence line for offload shadow\n"
    )
    body = line * max(1, (target // len(line.encode("utf-8"))) + 1)
    trimmed = body.encode("utf-8")[: max(0, target - len(TAIL_SENTINEL) - 1)].decode(
        "utf-8",
        errors="ignore",
    )
    return f"{trimmed}\n{TAIL_SENTINEL}"


def _extract_result_ref(text: str) -> str:
    match = RESULT_REF_PATTERN.search(text)
    return match.group(0) if match else ""


def _json_compatible(task: str, prompt_result: str) -> bool:
    try:
        json.dumps({"past_steps": [(task, prompt_result)]}, ensure_ascii=False)
    except (TypeError, ValueError):
        return False
    return True


def _gaps(
    *,
    long_log: dict[str, Any],
    prompt_payload: dict[str, Any],
    retrieval: dict[str, Any],
    evidence: dict[str, Any],
) -> list[str]:
    gaps: list[str] = []
    if not long_log["definition_met"]:
        gaps.append("long_log_definition_not_met")
    if not long_log["exceeds_threshold"]:
        gaps.append("long_log_does_not_exceed_threshold")
    if not long_log["within_max_bytes"]:
        gaps.append("long_log_exceeds_max_bytes")
    if not prompt_payload["is_string"]:
        gaps.append("prompt_payload_not_string")
    if not prompt_payload["json_string_compatible"]:
        gaps.append("prompt_payload_not_json_compatible")
    if not prompt_payload["result_ref_present"]:
        gaps.append("tool_result_ref_missing")
    if not prompt_payload["contains_offload_notice"]:
        gaps.append("offload_notice_missing")
    if prompt_payload["tail_sentinel_leaked"]:
        gaps.append("prompt_leaks_full_tail")
    if prompt_payload["equals_original_result"]:
        gaps.append("prompt_kept_original_result_inline")
    if not retrieval["owner_can_read_full_original"]:
        gaps.append("owner_cannot_read_full_original")
    if retrieval["other_owner_can_read"]:
        gaps.append("cross_owner_read_allowed")
    if evidence["summary_only_state"]:
        gaps.append("summary_only_state")
    if evidence["report_leaks_full_tail"]:
        gaps.append("report_leaks_full_tail")
    return gaps


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Checklist 3 Long Log Offload Shadow Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Status: `{report['status']}`",
        f"- Scope: `{report['scope']['phase']}` / `{report['scope']['report_kind']}`",
        f"- Synthetic data: `{report['scope']['uses_synthetic_data']}`",
        f"- Uses temp DB: `{report['scope']['uses_temp_db']}`",
        f"- Writes real session DB: `{report['scope']['writes_real_session_db']}`",
        f"- Gaps: {report['gaps'] or []}",
        "",
        "| check | value |",
        "|---|---|",
        f"| long log definition met | {report['long_log']['definition_met']} |",
        f"| original result bytes | {report['long_log']['original_result_bytes']} |",
        f"| result ref present | {report['prompt_payload']['result_ref_present']} |",
        f"| JSON/string-compatible | {report['prompt_payload']['json_string_compatible']} |",
        f"| tail sentinel leaked in prompt | {report['prompt_payload']['tail_sentinel_leaked']} |",
        f"| owner can read full original | {report['retrieval']['owner_can_read_full_original']} |",
        f"| other owner can read | {report['retrieval']['other_owner_can_read']} |",
        f"| summary-only state | {report['evidence']['summary_only_state']} |",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    parser.add_argument("--owner-id", default=DEFAULT_OWNER_ID)
    parser.add_argument("--other-owner-id", default=DEFAULT_OTHER_OWNER_ID)
    parser.add_argument("--task", default=DEFAULT_TASK)
    parser.add_argument("--result-bytes", type=int, default=DEFAULT_RESULT_BYTES)
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md")
    args = parser.parse_args()

    write_checklist3_long_log_offload_shadow_report(
        session_id=args.session_id,
        owner_id=args.owner_id,
        other_owner_id=args.other_owner_id,
        task=args.task,
        result_bytes=args.result_bytes,
        threshold=args.threshold,
        max_bytes=args.max_bytes,
        output_json=args.output_json,
        output_md=args.output_md,
    )


if __name__ == "__main__":
    main()
