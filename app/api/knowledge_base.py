"""Knowledge-base search APIs with diagnostics."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.enterprise.admin.models import success_payload
from app.enterprise.auth.dependencies import CurrentUser
from app.enterprise.gateway.models import GatewayRequest
from app.enterprise.gateway.request_gateway import request_gateway
from app.models import RetrievalMode
from app.services.knowledge_search_service import knowledge_search_service

router = APIRouter(tags=["知识库"])


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    kb_scope: str = "auto"
    candidate_kb_ids: list[str] | None = None
    top_k: int = Field(5, ge=1, le=20)
    retrieval_mode: str = RetrievalMode.HYBRID.value
    per_kb_top_k: int = Field(3, ge=1, le=10)


@router.get("/knowledge-bases/{kb_id}/search")
async def search_knowledge_base(
    kb_id: str,
    http_request: Request,
    _current_user: CurrentUser,
    q: str = Query(..., min_length=1),
    top_k: int = Query(5, ge=1, le=20),
    retrieval_mode: str = RetrievalMode.HYBRID.value,
):
    gateway_request = GatewayRequest.from_headers(
        route="knowledge_search",
        payload={
            "kb_id": kb_id,
            "query": q,
            "top_k": top_k,
            "retrieval_mode": retrieval_mode,
        },
        headers=http_request.headers,
    )

    async def handler(context):
        return knowledge_search_service.search_scoped(
            context,
            kb_id=kb_id,
            query=q,
            top_k=top_k,
            retrieval_mode=retrieval_mode,
        )

    try:
        result = await request_gateway.execute(gateway_request, handler)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return success_payload(result)


@router.post("/knowledge-search")
async def search_knowledge(
    search_request: KnowledgeSearchRequest,
    http_request: Request,
    _current_user: CurrentUser,
):
    gateway_request = GatewayRequest.from_headers(
        route="knowledge_search",
        payload=search_request.model_dump(mode="json"),
        headers=http_request.headers,
    )

    async def handler(context):
        return knowledge_search_service.search_unscoped(
            context,
            query=search_request.query,
            kb_scope=search_request.kb_scope,
            candidate_kb_ids=search_request.candidate_kb_ids,
            top_k=search_request.top_k,
            retrieval_mode=search_request.retrieval_mode,
            per_kb_top_k=search_request.per_kb_top_k,
        )

    try:
        result = await request_gateway.execute(gateway_request, handler)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return success_payload(result)
