"""Admin HTTP control plane for durable memory operator workflows."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.enterprise.auth.dependencies import CurrentUser
from app.enterprise.auth.models import UserProfile
from app.enterprise.gateway.models import GatewayRequest
from app.enterprise.gateway.request_gateway import request_gateway

from .memory_operator_adapter import memory_operator_adapter
from .models import success_payload
from .routes import require_admin_user

router = APIRouter(prefix="/admin/memory-operator", tags=["Memory Operator"])
gateway = request_gateway


def require_memory_operator_admin(current_user: CurrentUser) -> UserProfile:
    return require_admin_user(current_user)


MemoryOperatorAdmin = Annotated[UserProfile, Depends(require_memory_operator_admin)]


class DecisionRequest(BaseModel):
    decision_note: str = Field(..., min_length=1)


class ReviewQueueRequest(BaseModel):
    owner_id: str = "default"
    limit: int = 20


class DeprecationOwnerRequest(BaseModel):
    owner_id: str = Field(..., min_length=1)
    confirm_owner_id: str = Field(..., min_length=1)
    decision_note: str = Field(..., min_length=1)


@router.get("/review-queue")
async def review_queue(
    http_request: Request,
    _admin: MemoryOperatorAdmin,
    owner_id: str = "default",
    limit: int = Query(default=20, ge=1, le=100),
):
    gateway_request = GatewayRequest.from_headers(
        route="memory_operator_review_queue",
        payload={"owner_id": owner_id, "limit": limit},
        headers=http_request.headers,
    )

    async def handler(context):
        payload = memory_operator_adapter.list_review_queue(
            context,
            owner_id=owner_id,
            limit=limit,
        )
        return success_payload({"items": payload["items"], "total": payload["total"], "owner_id": owner_id, "limit": limit})

    return await gateway.execute(gateway_request, handler)


@router.get("/validation-status")
async def validation_status(
    http_request: Request,
    _admin: MemoryOperatorAdmin,
    owner_id: str = "default",
):
    gateway_request = GatewayRequest.from_headers(
        route="memory_operator_validation_status",
        payload={"owner_id": owner_id},
        headers=http_request.headers,
    )

    async def handler(context):
        payload = memory_operator_adapter.validation_status(context, owner_id=owner_id)
        return success_payload({"status": payload})

    return await gateway.execute(gateway_request, handler)


@router.post("/atoms/{memory_id}/approve")
async def approve(
    http_request: Request,
    memory_id: str,
    request: DecisionRequest,
    _admin: MemoryOperatorAdmin,
):
    gateway_request = GatewayRequest.from_headers(
        route="memory_operator_approve",
        payload={"memory_id": memory_id, **request.model_dump()},
        headers=http_request.headers,
    )

    async def handler(context):
        payload = memory_operator_adapter.approve(
            context,
            memory_id,
            decision_note=request.decision_note,
        )
        return success_payload(payload)

    return await gateway.execute(gateway_request, handler)


@router.post("/atoms/{memory_id}/reject")
async def reject(
    http_request: Request,
    memory_id: str,
    request: DecisionRequest,
    _admin: MemoryOperatorAdmin,
):
    gateway_request = GatewayRequest.from_headers(
        route="memory_operator_reject",
        payload={"memory_id": memory_id, **request.model_dump()},
        headers=http_request.headers,
    )

    async def handler(context):
        payload = memory_operator_adapter.reject(
            context,
            memory_id,
            decision_note=request.decision_note,
        )
        return success_payload(payload)

    return await gateway.execute(gateway_request, handler)


@router.post("/deprecation-preview")
async def deprecation_preview(
    http_request: Request,
    request: ReviewQueueRequest,
    _admin: MemoryOperatorAdmin,
):
    gateway_request = GatewayRequest.from_headers(
        route="memory_operator_deprecation_preview",
        payload=request.model_dump(),
        headers=http_request.headers,
    )

    async def handler(context):
        payload = memory_operator_adapter.deprecation_preview(context, owner_id=request.owner_id)
        return success_payload(payload)

    return await gateway.execute(gateway_request, handler)


@router.post("/deprecate-owner")
async def deprecate_owner(
    http_request: Request,
    request: DeprecationOwnerRequest,
    _admin: MemoryOperatorAdmin,
):
    gateway_request = GatewayRequest.from_headers(
        route="memory_operator_deprecate_owner",
        payload=request.model_dump(),
        headers=http_request.headers,
    )

    async def handler(context):
        payload = memory_operator_adapter.deprecate_owner(
            context,
            owner_id=request.owner_id,
            confirm_owner_id=request.confirm_owner_id,
            decision_note=request.decision_note,
        )
        return success_payload(payload)

    try:
        return await gateway.execute(gateway_request, handler)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
