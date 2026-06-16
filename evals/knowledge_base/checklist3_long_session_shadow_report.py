"""Checklist 3 long-session memory shadow report.

The report uses synthetic session data and the real ``RagAgentService``
prompt-construction path. It does not enable session memory globally and does
not write to the real session database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from app.enterprise.context import (
    RequestContext,
    reset_current_request_context,
    set_current_request_context,
)
from app.models.session_memory import SessionMemoryMessage, SessionMemorySnapshot, utc_now
from app.services.session_memory_store import InMemorySessionMemoryStore

DEFAULT_SESSION_ID = "checklist3-long-session"
DEFAULT_STALE_SESSION_ID = "checklist3-stale-session"
DEFAULT_OWNER_ID = "checklist3-owner"
DEFAULT_LONG_TURN_COUNT = 50
DEFAULT_ACTIVE_MAX_PROMPT_CHARS = 800
DEFAULT_TTL_SECONDS = 3600
FORBIDDEN_EVIDENCE_TERMS = ("source_ref", "sourceref", "citation")


class CountingMemoryStore(InMemorySessionMemoryStore):
    def __init__(self):
        super().__init__()
        self.get_snapshot_calls = 0
        self.cleanup_calls = 0

    def get_snapshot(self, session_id: str, owner_id: str):
        self.get_snapshot_calls += 1
        return super().get_snapshot(session_id, owner_id)

    def cleanup_expired(self, *, ttl_seconds: int, owner_id: str | None = None) -> int:
        self.cleanup_calls += 1
        return super().cleanup_expired(ttl_seconds=ttl_seconds, owner_id=owner_id)


def build_checklist3_long_session_shadow_report(
    *,
    session_id: str = DEFAULT_SESSION_ID,
    owner_id: str = DEFAULT_OWNER_ID,
    long_turn_count: int = DEFAULT_LONG_TURN_COUNT,
    active_max_prompt_chars: int = DEFAULT_ACTIVE_MAX_PROMPT_CHARS,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    return asyncio.run(
        _build_checklist3_long_session_shadow_report(
            session_id=session_id,
            owner_id=owner_id,
            long_turn_count=long_turn_count,
            active_max_prompt_chars=active_max_prompt_chars,
            ttl_seconds=ttl_seconds,
        )
    )


def write_checklist3_long_session_shadow_report(
    *,
    output_json: str | Path,
    output_md: str | Path | None = None,
    session_id: str = DEFAULT_SESSION_ID,
    owner_id: str = DEFAULT_OWNER_ID,
    long_turn_count: int = DEFAULT_LONG_TURN_COUNT,
    active_max_prompt_chars: int = DEFAULT_ACTIVE_MAX_PROMPT_CHARS,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    report = build_checklist3_long_session_shadow_report(
        session_id=session_id,
        owner_id=owner_id,
        long_turn_count=long_turn_count,
        active_max_prompt_chars=active_max_prompt_chars,
        ttl_seconds=ttl_seconds,
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


async def _build_checklist3_long_session_shadow_report(
    *,
    session_id: str,
    owner_id: str,
    long_turn_count: int,
    active_max_prompt_chars: int,
    ttl_seconds: int,
) -> dict[str, Any]:
    import app.services.rag_agent_service as rag_agent_service_module

    snapshot = _build_long_session_snapshot(
        session_id=session_id,
        owner_id=owner_id,
        turn_count=long_turn_count,
    )
    stale_snapshot = _build_long_session_snapshot(
        session_id=DEFAULT_STALE_SESSION_ID,
        owner_id=owner_id,
        turn_count=long_turn_count,
        updated_delta=timedelta(seconds=-(ttl_seconds + 60)),
    )
    context = _request_context(owner_id=owner_id)

    shadow_store = CountingMemoryStore()
    shadow_store.upsert_snapshot(snapshot)
    shadow_prompt = await _build_prompt(
        rag_agent_service_module,
        store=shadow_store,
        context=context,
        session_id=session_id,
        mode="shadow",
        ttl_seconds=ttl_seconds,
        max_prompt_chars=active_max_prompt_chars,
    )

    active_store = CountingMemoryStore()
    active_store.upsert_snapshot(snapshot)
    active_prompt = await _build_prompt(
        rag_agent_service_module,
        store=active_store,
        context=context,
        session_id=session_id,
        mode="active",
        ttl_seconds=ttl_seconds,
        max_prompt_chars=active_max_prompt_chars,
    )
    active_memory = _memory_section(
        active_prompt,
        header=rag_agent_service_module.SESSION_MEMORY_PROMPT_HEADER,
    )

    stale_store = CountingMemoryStore()
    stale_store.upsert_snapshot(stale_snapshot)
    stale_prompt = await _build_prompt(
        rag_agent_service_module,
        store=stale_store,
        context=context,
        session_id=DEFAULT_STALE_SESSION_ID,
        mode="active",
        ttl_seconds=ttl_seconds,
        max_prompt_chars=active_max_prompt_chars,
    )

    long_session = _long_session_summary(snapshot)
    shadow = {
        "mode": "shadow",
        "snapshot_read": shadow_store.get_snapshot_calls >= 1,
        "cleanup_called": shadow_store.cleanup_calls >= 1,
        "prompt_injected": rag_agent_service_module.SESSION_MEMORY_PROMPT_HEADER in shadow_prompt,
        "prompt_chars": len(shadow_prompt),
        "estimated_prompt_tokens": _estimate_tokens(shadow_prompt),
    }
    active_candidate = {
        "mode": "active_candidate",
        "snapshot_read": active_store.get_snapshot_calls >= 1,
        "cleanup_called": active_store.cleanup_calls >= 1,
        "prompt_injected": bool(active_memory),
        "memory_section_chars": len(active_memory),
        "max_prompt_chars": active_max_prompt_chars,
        "within_max_prompt_chars": len(active_memory.strip()) <= active_max_prompt_chars,
        "truncated": "[已截断]" in active_memory,
        "forbidden_hits": _forbidden_hits(active_memory),
        "estimated_memory_tokens": _estimate_tokens(active_memory),
    }
    stale_candidate = {
        "mode": "active_stale_candidate",
        "snapshot_read": stale_store.get_snapshot_calls >= 1,
        "cleanup_called": stale_store.cleanup_calls >= 1,
        "prompt_injected": rag_agent_service_module.SESSION_MEMORY_PROMPT_HEADER in stale_prompt,
        "stale_snapshot_remaining_after_cleanup": (
            stale_store.get_snapshot(DEFAULT_STALE_SESSION_ID, owner_id) is not None
        ),
    }
    pollution_checks = {
        "shadow_does_not_inject": not shadow["prompt_injected"],
        "active_candidate_has_no_evidence_terms": not active_candidate["forbidden_hits"],
        "active_candidate_is_bounded": active_candidate["within_max_prompt_chars"],
        "stale_snapshot_not_injected": not stale_candidate["prompt_injected"],
    }
    checks = [
        long_session["definition_met"],
        shadow["snapshot_read"],
        shadow["cleanup_called"],
        pollution_checks["shadow_does_not_inject"],
        active_candidate["prompt_injected"],
        active_candidate["truncated"],
        pollution_checks["active_candidate_has_no_evidence_terms"],
        pollution_checks["active_candidate_is_bounded"],
        stale_candidate["cleanup_called"],
        pollution_checks["stale_snapshot_not_injected"],
    ]
    gaps = _gaps(
        long_session=long_session,
        shadow=shadow,
        active_candidate=active_candidate,
        stale_candidate=stale_candidate,
        pollution_checks=pollution_checks,
    )
    return {
        "generated_at": utc_now().isoformat(),
        "status": "passed" if all(checks) else "failed",
        "scope": {
            "phase": "S3-P1.3",
            "report_kind": "long_session_memory_shadow",
            "uses_synthetic_data": True,
            "changes_runtime_config": False,
            "writes_real_session_db": False,
        },
        "config_under_test": {
            "shadow_mode": "shadow",
            "active_candidate_mode": "active",
            "active_max_prompt_chars": active_max_prompt_chars,
            "ttl_seconds": ttl_seconds,
            "forbidden_evidence_terms": list(FORBIDDEN_EVIDENCE_TERMS),
        },
        "long_session": long_session,
        "shadow": shadow,
        "active_candidate": active_candidate,
        "stale_candidate": stale_candidate,
        "pollution_checks": pollution_checks,
        "cost": {
            "shadow_prompt_chars": len(shadow_prompt),
            "shadow_estimated_prompt_tokens": _estimate_tokens(shadow_prompt),
            "active_memory_candidate_chars": len(active_memory),
            "active_memory_candidate_estimated_tokens": _estimate_tokens(active_memory),
        },
        "gaps": gaps,
    }


async def _build_prompt(
    rag_agent_service_module,
    *,
    store: CountingMemoryStore,
    context: RequestContext,
    session_id: str,
    mode: str,
    ttl_seconds: int,
    max_prompt_chars: int,
) -> str:
    service = rag_agent_service_module.RagAgentService(
        streaming=False,
        session_memory_store=store,
    )
    token = set_current_request_context(context)
    try:
        with (
            patch.object(
                rag_agent_service_module.profile_service,
                "build_profile",
                AsyncMock(side_effect=_fake_profile),
            ),
            patch.object(rag_agent_service_module.config, "rag_session_memory_mode", mode),
            patch.object(
                rag_agent_service_module.config,
                "rag_session_memory_snapshot_ttl_seconds",
                ttl_seconds,
            ),
            patch.object(
                rag_agent_service_module.config,
                "rag_session_memory_max_prompt_chars",
                max_prompt_chars,
            ),
            patch.object(rag_agent_service_module.config, "rag_session_memory_max_tail_messages", 100),
        ):
            return await service._build_runtime_system_prompt(session_id=session_id)
    finally:
        reset_current_request_context(token)


async def _fake_profile(_context, *, include_gateway_tools: bool = False):
    return {
        "user": {
            "user_id": DEFAULT_OWNER_ID,
            "username": "checklist3_owner",
            "department_id": "checklist3_dept",
            "department_name": "Checklist 3 Department",
            "roles": ["user"],
        },
        "visible_tools": ["retrieve_knowledge"],
        "visible_kb_ids": ["craft_dept"],
        "feature_flags": {},
        "unavailable_reasons": {},
    }


def _build_long_session_snapshot(
    *,
    session_id: str,
    owner_id: str,
    turn_count: int,
    updated_delta: timedelta | None = None,
) -> SessionMemorySnapshot:
    now = utc_now()
    updated_at = now + (updated_delta or timedelta())
    messages: list[SessionMemoryMessage] = []
    for index in range(1, max(0, int(turn_count)) + 1):
        messages.append(
            SessionMemoryMessage(
                role="user",
                content=f"第 {index} 轮：继续排查 checkout-service backlog 和告警升级。",
                created_at=updated_at,
            )
        )
        messages.append(
            SessionMemoryMessage(
                role="assistant",
                content=f"第 {index} 轮结论：保留 owner 边界，下一步看队列和重试窗口。",
                created_at=updated_at,
            )
        )
    return SessionMemorySnapshot(
        session_id=session_id,
        owner_id=owner_id,
        latest_summary=(
            "source_ref citation SourceRef 已确认 checkout-service backlog "
            "需要保持 owner 权限边界和升级记录；"
        )
        * 30,
        live_tail=messages,
        metadata={"synthetic": True, "turn_count": turn_count},
        created_at=updated_at,
        updated_at=updated_at,
    )


def _request_context(*, owner_id: str) -> RequestContext:
    return RequestContext(
        request_id="checklist3-long-session-report",
        trace_id="trace-checklist3-long-session",
        user_id=owner_id,
        username="checklist3_owner",
        department_id="checklist3_dept",
        department_name="Checklist 3 Department",
        roles=["user"],
    )


def _long_session_summary(snapshot: SessionMemorySnapshot) -> dict[str, Any]:
    user_messages = sum(1 for message in snapshot.live_tail if message.role == "user")
    assistant_messages = sum(1 for message in snapshot.live_tail if message.role == "assistant")
    turn_count = min(user_messages, assistant_messages)
    raw_context = snapshot.to_prompt_context()
    return {
        "session_id": snapshot.session_id,
        "owner_id": snapshot.owner_id,
        "turn_count": turn_count,
        "message_count": len(snapshot.live_tail),
        "raw_context_chars": len(raw_context),
        "estimated_raw_context_tokens": _estimate_tokens(raw_context),
        "definition": "turn_count >= 50",
        "definition_met": turn_count >= 50,
    }


def _memory_section(prompt: str, *, header: str) -> str:
    if header not in prompt:
        return ""
    return prompt.split(header, 1)[1].strip()


def _forbidden_hits(text: str) -> list[str]:
    lowered = text.lower()
    return [term for term in FORBIDDEN_EVIDENCE_TERMS if term in lowered]


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _gaps(
    *,
    long_session: dict[str, Any],
    shadow: dict[str, Any],
    active_candidate: dict[str, Any],
    stale_candidate: dict[str, Any],
    pollution_checks: dict[str, bool],
) -> list[str]:
    gaps: list[str] = []
    if not long_session["definition_met"]:
        gaps.append("long_session_definition_not_met")
    if not shadow["snapshot_read"]:
        gaps.append("shadow_snapshot_not_read")
    if not shadow["cleanup_called"]:
        gaps.append("shadow_cleanup_not_called")
    if not pollution_checks["shadow_does_not_inject"]:
        gaps.append("shadow_prompt_injected_memory")
    if not active_candidate["prompt_injected"]:
        gaps.append("active_candidate_not_injected")
    if not active_candidate["truncated"]:
        gaps.append("active_candidate_not_truncated")
    if not pollution_checks["active_candidate_has_no_evidence_terms"]:
        gaps.append("active_candidate_contains_evidence_terms")
    if not pollution_checks["active_candidate_is_bounded"]:
        gaps.append("active_candidate_exceeds_prompt_limit")
    if not stale_candidate["cleanup_called"]:
        gaps.append("stale_cleanup_not_called")
    if not pollution_checks["stale_snapshot_not_injected"]:
        gaps.append("stale_snapshot_injected")
    return gaps


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Checklist 3 Long Session Shadow Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Status: `{report['status']}`",
        f"- Scope: `{report['scope']['phase']}` / `{report['scope']['report_kind']}`",
        f"- Synthetic data: `{report['scope']['uses_synthetic_data']}`",
        f"- Runtime config changed: `{report['scope']['changes_runtime_config']}`",
        f"- Writes real session DB: `{report['scope']['writes_real_session_db']}`",
        f"- Gaps: {report['gaps'] or []}",
        "",
        "| check | value |",
        "|---|---|",
        f"| long session definition met | {report['long_session']['definition_met']} |",
        f"| turn count | {report['long_session']['turn_count']} |",
        f"| shadow snapshot read | {report['shadow']['snapshot_read']} |",
        f"| shadow prompt injected | {report['shadow']['prompt_injected']} |",
        f"| active candidate bounded | {report['active_candidate']['within_max_prompt_chars']} |",
        f"| active candidate truncated | {report['active_candidate']['truncated']} |",
        f"| active candidate forbidden hits | {report['active_candidate']['forbidden_hits']} |",
        f"| stale candidate prompt injected | {report['stale_candidate']['prompt_injected']} |",
        f"| active memory estimated tokens | {report['cost']['active_memory_candidate_estimated_tokens']} |",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    parser.add_argument("--owner-id", default=DEFAULT_OWNER_ID)
    parser.add_argument("--long-turn-count", type=int, default=DEFAULT_LONG_TURN_COUNT)
    parser.add_argument("--active-max-prompt-chars", type=int, default=DEFAULT_ACTIVE_MAX_PROMPT_CHARS)
    parser.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md")
    args = parser.parse_args()

    write_checklist3_long_session_shadow_report(
        session_id=args.session_id,
        owner_id=args.owner_id,
        long_turn_count=args.long_turn_count,
        active_max_prompt_chars=args.active_max_prompt_chars,
        ttl_seconds=args.ttl_seconds,
        output_json=args.output_json,
        output_md=args.output_md,
    )


if __name__ == "__main__":
    main()
