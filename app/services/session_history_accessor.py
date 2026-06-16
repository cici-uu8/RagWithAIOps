"""Stable accessors for LangGraph session state used by memory candidates."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from loguru import logger

from app.models.memory_candidate import AIOpsPastStep, AIOpsSessionState, SessionHistoryMessage


class SessionHistoryAccessor:
    """Read RAG chat history without exposing MemorySaver internals downstream."""

    def __init__(self, checkpointer: Any):
        self.checkpointer = checkpointer

    def get_history(self, session_id: str) -> list[SessionHistoryMessage]:
        try:
            checkpoint_data = self._get_checkpoint_data(session_id)
            if not checkpoint_data:
                logger.info("获取会话历史: {}, 消息数量: 0", session_id)
                return []

            messages = checkpoint_data.get("channel_values", {}).get("messages", [])
            history: list[SessionHistoryMessage] = []
            for index, message in enumerate(messages):
                normalized = self._normalize_message(message, index)
                if normalized is not None:
                    history.append(normalized)

            logger.info("获取会话历史: {}, 消息数量: {}", session_id, len(history))
            return history
        except Exception as exc:
            logger.error("获取会话历史失败: {}, 错误: {}", session_id, exc)
            return []

    def get_history_dicts(self, session_id: str) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        for message in self.get_history(session_id):
            history.append(
                {
                    "role": message.role,
                    "content": message.content,
                    "timestamp": message.timestamp or datetime.now().isoformat(),
                }
            )
        return history

    def _get_checkpoint_data(self, session_id: str) -> dict[str, Any]:
        config = {"configurable": {"thread_id": session_id}}
        checkpoint_tuple = self.checkpointer.get(config)
        if not checkpoint_tuple:
            return {}
        if hasattr(checkpoint_tuple, "checkpoint"):
            return checkpoint_tuple.checkpoint
        return checkpoint_tuple[0] if checkpoint_tuple else {}

    def _normalize_message(self, message: Any, message_index: int) -> SessionHistoryMessage | None:
        if isinstance(message, SystemMessage):
            return None

        role = "user" if isinstance(message, HumanMessage) else "assistant"
        if isinstance(message, AIMessage):
            role = "assistant"
        elif isinstance(message, BaseMessage) and getattr(message, "type", None) == "human":
            role = "user"

        content = getattr(message, "content", None)
        if content is None:
            content = str(message)
        if isinstance(content, list):
            content = " ".join(str(part) for part in content)
        content = str(content).strip()
        if not content:
            return None

        return SessionHistoryMessage(
            role=role,
            content=content,
            message_index=message_index,
            timestamp=getattr(message, "timestamp", None),
        )


class AIOpsGraphStateAccessor:
    """Read AIOps graph state through the public compiled-graph state API."""

    def __init__(self, graph: Any):
        self.graph = graph

    def get_state(self, session_id: str) -> AIOpsSessionState | None:
        config = {"configurable": {"thread_id": session_id}}
        graph_state = self.graph.get_state(config)
        values = getattr(graph_state, "values", None) if graph_state else None
        if not values:
            return None
        return self.from_values(session_id, values)

    @classmethod
    def from_values(cls, session_id: str, values: dict[str, Any]) -> AIOpsSessionState:
        return AIOpsSessionState(
            session_id=session_id,
            input=str(values.get("input", "")),
            plan_steps=[str(step) for step in values.get("plan", []) if str(step).strip()],
            past_steps=cls._normalize_past_steps(values.get("past_steps", [])),
            response=str(values.get("response", "")),
        )

    @staticmethod
    def _normalize_past_steps(raw_steps: list[Any]) -> list[AIOpsPastStep]:
        normalized: list[AIOpsPastStep] = []
        for index, item in enumerate(raw_steps):
            if isinstance(item, dict):
                step = str(item.get("step", ""))
                result = str(item.get("result", item.get("observation", "")))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                step = str(item[0])
                result = str(item[1])
            else:
                step = str(item)
                result = ""
            if step.strip() or result.strip():
                normalized.append(AIOpsPastStep(step=step, result=result, step_index=index))
        return normalized
