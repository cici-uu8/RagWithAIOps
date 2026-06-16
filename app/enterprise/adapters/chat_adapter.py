"""Thin chat adapter for E2 RequestGateway."""

from collections.abc import AsyncIterator

from app.enterprise.errors.mapper import build_error_event, map_exception_to_error_context
from app.enterprise.gateway.models import GatewayRequest
from app.enterprise.gateway.request_gateway import (
    RateLimitBlocked,
    RequestBlocked,
    RequestGateway,
    request_gateway,
)
from app.enterprise.routing.router import StrategyRouter, strategy_router
from app.models.request import ChatRequest


class ChatAdapter:
    def __init__(
        self,
        rag_service,
        gateway: RequestGateway | None = None,
        routing_service: StrategyRouter | None = None,
    ):
        self.rag_service = rag_service
        self.gateway = gateway or request_gateway
        self.routing_service = routing_service or strategy_router

    async def chat(self, request: ChatRequest, headers) -> dict:
        gateway_request = GatewayRequest.from_headers(
            route="chat",
            payload=request.model_dump(by_alias=True),
            headers=headers,
        )

        async def handler(context):
            self.routing_service.record_shadow_decision(
                audit_service=self.gateway.audit_service,
                context=context,
                actual_route="chat",
                payload=request.model_dump(by_alias=True),
            )
            answer = await self.rag_service.query(
                request.question,
                session_id=request.id,
                selected_kb_ids=request.selected_kb_ids,
                scope_source=request.scope_source,
                context=context,
            )
            return {
                "code": 200,
                "message": "success",
                "data": {
                    "success": True,
                    "answer": str(answer),
                    "errorMessage": None,
                    "trace_id": context.trace_id,
                    "query_intent_diagnostics": getattr(
                        answer,
                        "query_intent_diagnostics",
                        None,
                    ),
                },
            }

        return await self.gateway.execute(gateway_request, handler)

    async def chat_stream(self, request: ChatRequest, headers) -> AsyncIterator[dict]:
        gateway_request = GatewayRequest.from_headers(
            route="chat_stream",
            payload=request.model_dump(by_alias=True),
            headers=headers,
        )

        async def handler(context):
            self.routing_service.record_shadow_decision(
                audit_service=self.gateway.audit_service,
                context=context,
                actual_route="chat",
                payload=request.model_dump(by_alias=True),
            )
            async for chunk in self.rag_service.query_stream(
                request.question,
                session_id=request.id,
                selected_kb_ids=request.selected_kb_ids,
                scope_source=request.scope_source,
                context=context,
            ):
                if isinstance(chunk, dict):
                    chunk = {
                        **chunk,
                        "trace_id": context.trace_id,
                        "request_id": context.request_id,
                    }
                yield chunk

        try:
            async for chunk in self.gateway.execute_stream(gateway_request, handler):
                yield chunk
        except (RequestBlocked, RateLimitBlocked) as exc:
            yield build_error_event(
                map_exception_to_error_context(
                    exc,
                    stage="guardrail" if isinstance(exc, RequestBlocked) else "rate_limit",
                ),
                trace_id=exc.trace_id,
                request_id=getattr(exc, "request_id", ""),
            )

    async def clear_session(self, session_id: str, headers) -> dict:
        gateway_request = GatewayRequest.from_headers(
            route="chat_clear",
            payload={"session_id": session_id},
            headers=headers,
        )

        async def handler(context):
            success = self.rag_service.clear_session(session_id)
            return {
                "success": bool(success),
                "trace_id": context.trace_id,
                "request_id": context.request_id,
            }

        return await self.gateway.execute(gateway_request, handler)
