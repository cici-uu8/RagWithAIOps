"""Best-effort ingestion of completed AIOps diagnostics into L0 evidence."""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.models.memory_candidate import AIOpsSessionState
from app.services.memory_evidence_store import MemoryEvidenceStore, memory_evidence_store


class MemoryIngestionService:
    """Convert completed diagnostics into L0 raw evidence."""

    def __init__(self, *, store: MemoryEvidenceStore = memory_evidence_store):
        self.store = store

    def ingest_aiops_diagnosis(
        self,
        session_state: AIOpsSessionState | dict[str, Any],
        *,
        owner_id: str = "default",
        key_events: list[dict[str, Any]] | None = None,
        tool_results: list[dict[str, Any]] | None = None,
        memory_observation: dict[str, Any] | None = None,
        service: str | None = None,
        alert_name: str | None = None,
        environment: str | None = None,
        evidence_id: str | None = None,
        diagnosis_status: str | None = None,
    ):
        """Persist one completed diagnosis as L0 evidence."""

        state = self._coerce_state(session_state)
        final_response = state.response.strip()
        status = diagnosis_status or ("complete" if final_response else "partial")

        evidence = self.store.create_aiops_evidence(
            evidence_id=evidence_id,
            session_id=state.session_id,
            owner_id=owner_id,
            query=state.input,
            plan=state.plan_steps,
            past_steps=[step.model_dump(mode="json") for step in state.past_steps],
            final_response=final_response,
            key_events=key_events or [],
            tool_results=tool_results,
            memory_observation=memory_observation,
            service=service,
            alert_name=alert_name,
            environment=environment,
            diagnosis_status=status,
        )
        logger.info(
            "Ingested L0 evidence evidence_id={} session_id={} status={}",
            evidence.evidence_id,
            evidence.session_id,
            evidence.diagnosis_status,
        )
        return evidence

    @staticmethod
    def _coerce_state(session_state: AIOpsSessionState | dict[str, Any]) -> AIOpsSessionState:
        if isinstance(session_state, AIOpsSessionState):
            return session_state
        return AIOpsSessionState.model_validate(session_state)


memory_ingestion_service = MemoryIngestionService()
