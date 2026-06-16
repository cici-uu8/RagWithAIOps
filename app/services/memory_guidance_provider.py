"""Planner-facing provider for reviewed oncall memory guidance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.models.memory_mode import MemoryMode
from app.services.hierarchical_retrieval_service import HierarchicalRetrievalService
from app.services.memory_guidance_service import MemoryGuidanceService
from app.services.memory_store import MemoryStore
from app.services.memory_trace_service import MemoryTraceService

if TYPE_CHECKING:
    from app.agent.aiops.state import PlanExecuteState


@dataclass
class MemoryGuidanceResult:
    guidance_text: str
    observation: dict | None
    mode: MemoryMode


class MemoryGuidanceProvider:
    """Build memory guidance and trace observations for the AIOps planner."""

    def __init__(self, trace_service: MemoryTraceService | None = None):
        self._trace_service = trace_service or MemoryTraceService()

    def build(self, state: PlanExecuteState) -> MemoryGuidanceResult:
        memory_mode = MemoryMode.from_state(state)
        if memory_mode == MemoryMode.OFF:
            return MemoryGuidanceResult(guidance_text="", observation=None, mode=memory_mode)

        input_text = state.get("input", "")
        owner_id = state.get("memory_owner_id", "default")
        memory_service = self._build_retrieval_service(state)
        memory_response = memory_service.retrieve_hierarchical(
            input_text,
            owner_id=owner_id,
            top_k_l2=2,
            top_k_l1=3,
            top_k_legacy=3,
        )

        if not memory_response.memory_results:
            return MemoryGuidanceResult(guidance_text="", observation=None, mode=memory_mode)

        memory_guidance_text = MemoryGuidanceService.format_hierarchical_guidance(
            memory_response,
            include_metadata=True,
        )
        observation = self._trace_service.create_observation(
            mode=memory_mode,
            memory_response=memory_response,
            memory_guidance_text=memory_guidance_text,
            query=input_text,
            owner_id=owner_id,
        )

        if memory_mode == MemoryMode.ACTIVE:
            return MemoryGuidanceResult(
                guidance_text=memory_guidance_text,
                observation=observation,
                mode=memory_mode,
            )

        return MemoryGuidanceResult(guidance_text="", observation=observation, mode=memory_mode)

    def _build_retrieval_service(self, state: PlanExecuteState) -> HierarchicalRetrievalService:
        custom_store_path = state.get("memory_store_path")
        if custom_store_path:
            return HierarchicalRetrievalService(store=MemoryStore(store_path=custom_store_path))
        return HierarchicalRetrievalService()


memory_guidance_provider = MemoryGuidanceProvider()
