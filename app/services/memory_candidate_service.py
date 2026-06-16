"""Operator-triggered extraction of reviewed-later memory candidates."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from app.models.memory import (
    AlertPatternPayload,
    CandidateSummaryPayload,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    PlanTemplatePayload,
    PreferencePayload,
    RuntimeContextPayload,
    L2ScenarioPayload,
)
from app.models.memory_candidate import (
    AIOpsSessionState,
    MemoryCandidateExtractionResult,
    SessionHistoryMessage,
)
from app.services.memory_store import MemoryStore, memory_store


SESSION_CANDIDATE_SOURCE = "session-candidate, NOT reviewed active memory"


def dedup_key(record: MemoryRecord) -> tuple[Any, ...]:
    """Return the exact-duplicate key for a memory record."""

    payload = record.payload
    if isinstance(payload, AlertPatternPayload):
        return (
            MemoryType.ALERT_PATTERN.value,
            record.owner_id,
            _norm(payload.alert_name),
            _norm(payload.service),
            tuple(sorted(_norm(key) for key in payload.signal_keys)),
        )
    if isinstance(payload, PlanTemplatePayload):
        return (
            MemoryType.PLAN_TEMPLATE.value,
            record.owner_id,
            _norm(payload.alert_type),
            _hash_json(payload.plan_steps),
        )
    if isinstance(payload, PreferencePayload):
        return (
            MemoryType.PREFERENCE.value,
            record.owner_id,
            _norm(payload.preference_scope),
            tuple(sorted(_norm(value) for value in payload.applies_to)),
        )
    if isinstance(payload, RuntimeContextPayload):
        return (
            MemoryType.RUNTIME_CONTEXT.value,
            record.owner_id,
            _norm(payload.context_key),
        )
    if isinstance(payload, CandidateSummaryPayload):
        return (
            MemoryType.CANDIDATE_SUMMARY.value,
            record.owner_id,
            _norm(record.evidence.get("session_id", "")),
            _hash_json(payload.summary),
        )
    if isinstance(payload, L2ScenarioPayload):
        return (
            MemoryType.L2_SCENARIO.value,
            record.owner_id,
            _norm(payload.scenario_key),
            tuple(sorted(_norm(atom_id) for atom_id in payload.l1_atom_ids)),
        )
    raise ValueError(f"unsupported payload type for dedup: {type(payload)}")


def conflict_key(record: MemoryRecord) -> tuple[Any, ...]:
    """Return the broader key where records can conflict."""

    payload = record.payload
    if isinstance(payload, AlertPatternPayload):
        return dedup_key(record)
    if isinstance(payload, PlanTemplatePayload):
        return (MemoryType.PLAN_TEMPLATE.value, record.owner_id, _norm(payload.alert_type))
    if isinstance(payload, PreferencePayload):
        return dedup_key(record)
    if isinstance(payload, RuntimeContextPayload):
        return dedup_key(record)
    if isinstance(payload, CandidateSummaryPayload):
        return dedup_key(record)
    if isinstance(payload, L2ScenarioPayload):
        return (
            MemoryType.L2_SCENARIO.value,
            record.owner_id,
            _norm(payload.scenario_key),
            tuple(sorted(_norm(atom_id) for atom_id in payload.l1_atom_ids)),
        )
    raise ValueError(f"unsupported payload type for conflict: {type(payload)}")


def is_conflict(existing: MemoryRecord, candidate: MemoryRecord) -> bool:
    """Detect candidate conflicts without silently promoting new information."""

    if existing.memory_type != candidate.memory_type:
        return False
    if conflict_key(existing) != conflict_key(candidate):
        return False

    existing_payload = existing.payload
    candidate_payload = candidate.payload
    if isinstance(existing_payload, AlertPatternPayload) and isinstance(candidate_payload, AlertPatternPayload):
        return (
            _norm(existing_payload.root_cause) != _norm(candidate_payload.root_cause)
            or _norm(existing_payload.fix) != _norm(candidate_payload.fix)
        )
    if isinstance(existing_payload, PlanTemplatePayload) and isinstance(candidate_payload, PlanTemplatePayload):
        if dedup_key(existing) == dedup_key(candidate):
            return False
        return (
            _hash_json(existing_payload.stop_conditions) != _hash_json(candidate_payload.stop_conditions)
            or _hash_json(existing_payload.tool_hints) != _hash_json(candidate_payload.tool_hints)
        )
    if isinstance(existing_payload, PreferencePayload) and isinstance(candidate_payload, PreferencePayload):
        return _norm(existing_payload.preference) != _norm(candidate_payload.preference)
    if isinstance(existing_payload, RuntimeContextPayload) and isinstance(candidate_payload, RuntimeContextPayload):
        if existing_payload.expires_at and existing_payload.expires_at <= _now_like(existing_payload.expires_at):
            return False
        return _norm(existing_payload.context_value) != _norm(candidate_payload.context_value)
    if isinstance(existing_payload, L2ScenarioPayload) and isinstance(candidate_payload, L2ScenarioPayload):
        return False
    return False


class MemoryCandidateService:
    """Create durable memory candidates from stable session accessors only."""

    def __init__(
        self,
        *,
        store: MemoryStore = memory_store,
        session_history_accessor: Any | None = None,
        aiops_state_accessor: Any | None = None,
    ):
        self.store = store
        self.session_history_accessor = session_history_accessor
        self.aiops_state_accessor = aiops_state_accessor

    def extract_from_rag_session(
        self,
        session_id: str,
        *,
        owner_id: str = "default",
    ) -> MemoryCandidateExtractionResult:
        """Create a candidate summary from normalized RAG chat history."""

        if self.session_history_accessor is None:
            return self._skipped(session_id, "rag_chat", "session_history_accessor is required")

        messages = self.session_history_accessor.get_history(session_id)
        meaningful = [message for message in messages if message.content.strip()]
        if len(meaningful) < 2:
            return self._skipped(session_id, "rag_chat", "at least two chat messages are required")

        record = self._build_rag_candidate(session_id, owner_id, meaningful)
        action, stored = self._store_candidate_with_action(record)
        return MemoryCandidateExtractionResult(
            session_id=session_id,
            source_type="rag_chat",
            action=action,
            records=[stored],
        )

    def extract_from_aiops_session(
        self,
        session_id: str,
        *,
        owner_id: str = "default",
    ) -> MemoryCandidateExtractionResult:
        """Create a plan-template candidate from normalized AIOps graph state."""

        if self.aiops_state_accessor is None:
            return self._skipped(session_id, "aiops_diagnosis", "aiops_state_accessor is required")

        state: AIOpsSessionState | None = self.aiops_state_accessor.get_state(session_id)
        if state is None:
            return self._skipped(session_id, "aiops_diagnosis", "aiops graph state is missing")

        plan_steps = list(state.plan_steps) or [step.step for step in state.past_steps if step.step.strip()]
        if len(plan_steps) < 2:
            return self._skipped(session_id, "aiops_diagnosis", "at least two plan steps are required")
        if not state.response.strip():
            return self._skipped(session_id, "aiops_diagnosis", "final response is required")

        record = self._build_aiops_plan_candidate(session_id, owner_id, state, plan_steps)
        action, stored = self._store_candidate_with_action(record)
        return MemoryCandidateExtractionResult(
            session_id=session_id,
            source_type="aiops_diagnosis",
            action=action,
            records=[stored],
        )

    def store_candidate(self, record: MemoryRecord) -> MemoryRecord:
        """Persist one reviewed-later candidate without auto-promotion."""

        _, stored = self._store_candidate_with_action(record)
        return stored

    def _store_candidate_with_action(self, record: MemoryRecord) -> tuple[str, MemoryRecord]:
        candidate = record.model_copy(update={"status": MemoryStatus.CANDIDATE})
        existing_records = [
            existing
            for existing in self.store.list_memories(
                owner_id=candidate.owner_id,
                memory_type=candidate.memory_type,
            )
            if existing.status != MemoryStatus.DEPRECATED
        ]

        conflicts = [existing for existing in existing_records if is_conflict(existing, candidate)]
        if conflicts:
            evidence = dict(candidate.evidence)
            evidence["conflicts_with"] = [existing.memory_id for existing in conflicts]
            candidate = candidate.model_copy(
                update={
                    "status": MemoryStatus.CONFLICT,
                    "evidence": evidence,
                }
            )
            return "conflict", self.store.upsert(candidate)

        for existing in existing_records:
            if dedup_key(existing) == dedup_key(candidate):
                return "duplicate", existing

        return "created", self.store.upsert(candidate)

    def _build_rag_candidate(
        self,
        session_id: str,
        owner_id: str,
        messages: list[SessionHistoryMessage],
    ) -> MemoryRecord:
        first_user = next((message for message in messages if message.role == "user"), messages[0])
        last_assistant = next((message for message in reversed(messages) if message.role == "assistant"), messages[-1])
        summary = _truncate(f"{first_user.content} -> {last_assistant.content}", 240)
        evidence_refs = [
            {
                "evidence_type": "session_message_ref",
                "session_id": session_id,
                "source_type": "rag_chat",
                "role": message.role,
                "message_index": message.message_index,
            }
            for message in messages
        ]
        evidence = {
            "evidence_type": "session_candidate",
            "session_id": session_id,
            "source_type": "rag_chat",
            "message_refs": [
                {
                    "role": message.role,
                    "message_index": message.message_index,
                }
                for message in messages
            ],
        }
        payload = CandidateSummaryPayload(
            candidate_kind="rag_chat_summary",
            summary=summary,
            evidence_refs=evidence_refs,
        )
        return MemoryRecord(
            memory_id=f"mem_candidate_rag_{_hash_json([session_id, summary])}",
            owner_id=owner_id,
            namespace="memory://candidate/session",
            memory_type=MemoryType.CANDIDATE_SUMMARY,
            content=summary,
            summary=summary,
            payload=payload,
            source=SESSION_CANDIDATE_SOURCE,
            evidence=evidence,
            status=MemoryStatus.CANDIDATE,
            tags=["session_candidate", "rag_chat"],
        )

    def _build_aiops_plan_candidate(
        self,
        session_id: str,
        owner_id: str,
        state: AIOpsSessionState,
        plan_steps: list[str],
    ) -> MemoryRecord:
        alert_type = _derive_alert_type(state.input)
        evidence_refs = [
            {
                "evidence_type": "graph_state_field_ref",
                "session_id": session_id,
                "source_type": "aiops_diagnosis",
                "field": "input",
            },
            {
                "evidence_type": "graph_state_field_ref",
                "session_id": session_id,
                "source_type": "aiops_diagnosis",
                "field": "response",
            },
            *[
                {
                    "evidence_type": "graph_state_field_ref",
                    "session_id": session_id,
                    "source_type": "aiops_diagnosis",
                    "field": f"plan_steps[{index}]",
                }
                for index, _ in enumerate(plan_steps)
            ],
        ]
        payload = PlanTemplatePayload(
            alert_type=alert_type,
            plan_steps=plan_steps,
            evidence_refs=evidence_refs,
        )
        content = f"AIOps plan candidate for {alert_type}: " + " -> ".join(plan_steps)
        evidence = {
            "evidence_type": "session_candidate",
            "session_id": session_id,
            "source_type": "aiops_diagnosis",
            "state_refs": ["input", "response", "plan_steps"],
        }
        return MemoryRecord(
            memory_id=f"mem_candidate_plan_{_hash_json([owner_id, alert_type, plan_steps])}",
            owner_id=owner_id,
            namespace="memory://oncall/plan-templates",
            memory_type=MemoryType.PLAN_TEMPLATE,
            content=_truncate(content, 800),
            summary=_truncate(content, 240),
            payload=payload,
            source=SESSION_CANDIDATE_SOURCE,
            evidence=evidence,
            status=MemoryStatus.CANDIDATE,
            tags=["session_candidate", "aiops_diagnosis", "plan_template"],
        )

    def _skipped(self, session_id: str, source_type: str, reason: str) -> MemoryCandidateExtractionResult:
        return MemoryCandidateExtractionResult(
            session_id=session_id,
            source_type=source_type,
            action="skipped",
            skipped_reason=reason,
        )


def _derive_alert_type(user_input: str) -> str:
    first_line = user_input.strip().splitlines()[0].strip()
    return _truncate(first_line, 120)


def _hash_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _truncate(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _now_like(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return datetime.now(value.tzinfo)
    return datetime.now()
