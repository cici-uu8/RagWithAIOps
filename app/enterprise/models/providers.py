"""Model providers for ModelGateway."""

from __future__ import annotations

from typing import Protocol

from app.core.llm_factory import LLMFactory
from app.enterprise.models.models import ModelEndpoint, ModelRequest, ModelResponse


class ModelProvider(Protocol):
    async def generate(self, request: ModelRequest, endpoint: ModelEndpoint) -> ModelResponse:
        ...


class StaticModelProvider:
    def __init__(
        self,
        *,
        response: ModelResponse | None = None,
        error: BaseException | None = None,
    ):
        self.response = response or ModelResponse(content="")
        self.error = error
        self.calls: list[tuple[ModelRequest, ModelEndpoint]] = []

    async def generate(self, request: ModelRequest, endpoint: ModelEndpoint) -> ModelResponse:
        self.calls.append((request, endpoint))
        if self.error is not None:
            raise self.error
        return self.response


class DashScopeModelProvider:
    """Default provider preserving the current DashScope OpenAI-compatible path."""

    async def generate(self, request: ModelRequest, endpoint: ModelEndpoint) -> ModelResponse:
        llm = LLMFactory.create_chat_model(
            model=endpoint.model_name,
            temperature=request.temperature if request.temperature is not None else 0.7,
            streaming=False,
        )
        result = await llm.ainvoke(request.messages)
        usage = _extract_usage(result)
        content = result.content if hasattr(result, "content") else str(result)
        return ModelResponse(content=content, usage=usage, raw_response=result)


def _extract_usage(result) -> dict:
    usage_metadata = getattr(result, "usage_metadata", None)
    if isinstance(usage_metadata, dict):
        return dict(usage_metadata)

    response_metadata = getattr(result, "response_metadata", None)
    if isinstance(response_metadata, dict):
        token_usage = response_metadata.get("token_usage") or response_metadata.get("usage")
        if isinstance(token_usage, dict):
            return dict(token_usage)

    return {}
