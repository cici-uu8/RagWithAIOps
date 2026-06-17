"""Admin Ops Metrics routes for audit/trace dashboard."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.enterprise.auth.dependencies import CurrentUser
from app.enterprise.auth.models import UserProfile
from app.enterprise.gateway.models import GatewayRequest
from app.enterprise.gateway.request_gateway import request_gateway

from .models import success_payload
from .ops_metrics_adapter import ops_metrics_adapter
from .routes import require_admin_user

router = APIRouter(prefix="/admin/ops-metrics", tags=["Ops Metrics"])
gateway = request_gateway


def require_ops_metrics_admin(current_user: CurrentUser) -> UserProfile:
    return require_admin_user(current_user)


OpsMetricsAdmin = Annotated[UserProfile, Depends(require_ops_metrics_admin)]


@router.get("/summary")
async def get_ops_summary(
    http_request: Request,
    _admin: OpsMetricsAdmin,
    time_range: str = "24h",
):
    gateway_request = GatewayRequest.from_headers(
        route="ops_metrics_summary",
        payload={"time_range": time_range},
        headers=http_request.headers,
    )

    async def handler(context):
        return success_payload(
            await ops_metrics_adapter.get_summary(context, time_range)
        )

    try:
        return await gateway.execute(gateway_request, handler)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/timeline")
async def get_ops_timeline(
    http_request: Request,
    _admin: OpsMetricsAdmin,
    time_range: str = "24h",
    bucket: str = "1h",
):
    gateway_request = GatewayRequest.from_headers(
        route="ops_metrics_timeline",
        payload={"time_range": time_range, "bucket": bucket},
        headers=http_request.headers,
    )

    async def handler(context):
        timeline = await ops_metrics_adapter.get_timeline(context, time_range, bucket)
        return success_payload({"timeline": timeline})

    try:
        return await gateway.execute(gateway_request, handler)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/failures")
async def get_ops_failures(
    http_request: Request,
    _admin: OpsMetricsAdmin,
    time_range: str = "24h",
    limit: int = Query(default=20, ge=1, le=100),
):
    gateway_request = GatewayRequest.from_headers(
        route="ops_metrics_failures",
        payload={"time_range": time_range, "limit": limit},
        headers=http_request.headers,
    )

    async def handler(context):
        failures = await ops_metrics_adapter.get_failures(context, time_range, limit)
        return success_payload({"failures": failures})

    try:
        return await gateway.execute(gateway_request, handler)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
