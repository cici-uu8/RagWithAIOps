"""FastAPI routes for permission requests."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.enterprise.admin.models import success_payload
from app.enterprise.admin.scopes import AdminScope, AdminScopeError, admin_scope_service
from app.enterprise.admin.service import AdminError, AdminScopeDenied, admin_service
from app.enterprise.auth.dependencies import CurrentUser
from app.enterprise.context import RequestContext, get_current_request_context
from app.enterprise.permission_requests.models import (
    PermissionRequestCreateRequest,
    PermissionRequestDecisionRequest,
)
from app.enterprise.permission_requests.service import (
    PermissionRequestError,
    permission_request_service,
)

router = APIRouter(prefix="/permission-requests", tags=["权限申请"])
admin_router = APIRouter(prefix="/admin/permission-requests", tags=["权限申请审批"])


def _require_context() -> RequestContext:
    context = get_current_request_context()
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="RequestContext is missing",
        )
    return context


def require_permission_request_admin(current_user: CurrentUser) -> AdminScope:
    try:
        scope = admin_scope_service.resolve_scope(current_user)
    except AdminScopeError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if scope is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return scope


AdminActorScope = Annotated[AdminScope, Depends(require_permission_request_admin)]


def _permission_request_error_to_http(exc: PermissionRequestError) -> HTTPException:
    detail = str(exc)
    if detail == "permission_request_not_found":
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    if detail == "permission_request_requires_global_review":
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _admin_error_to_http(exc: AdminError) -> HTTPException:
    if isinstance(exc, AdminScopeDenied):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/resources")
async def list_requestable_permission_resources(_current_user: CurrentUser):
    context = _require_context()
    resources = await permission_request_service.list_requestable_resources(context)
    return success_payload({"resources": resources})


@router.post("")
async def create_permission_request(
    request: PermissionRequestCreateRequest,
    _current_user: CurrentUser,
):
    context = _require_context()
    try:
        record = await permission_request_service.create_request(context, request)
    except PermissionRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return success_payload(
        {
            "permission_request": await permission_request_service.request_payload(record)
        }
    )


@router.get("/mine")
async def list_my_permission_requests(_current_user: CurrentUser):
    context = _require_context()
    requests = permission_request_service.list_my_requests(context)
    return success_payload(
        {
            "permission_requests": [
                await permission_request_service.request_payload(record)
                for record in requests
            ]
        }
    )


@admin_router.get("")
async def list_admin_permission_requests(scope: AdminActorScope):
    requests = permission_request_service.list_reviewable_requests(scope)
    return success_payload(
        {
            "permission_requests": [
                await permission_request_service.request_payload(record)
                for record in requests
            ],
            "pending_count": len(requests),
            "requires_global_review_count": sum(
                1
                for record in requests
                if record.requires_global_review
            ),
        }
    )


@admin_router.post("/{request_id}/approve")
async def approve_permission_request(
    request_id: str,
    request: PermissionRequestDecisionRequest,
    scope: AdminActorScope,
):
    context = _require_context()
    try:
        record = await permission_request_service.approve_request(
            context,
            scope,
            request_id,
            reason=request.reason,
            admin_service=admin_service,
        )
    except PermissionRequestError as exc:
        raise _permission_request_error_to_http(exc) from exc
    except AdminError as exc:
        raise _admin_error_to_http(exc) from exc
    return success_payload(
        {
            "permission_request": await permission_request_service.request_payload(record)
        }
    )


@admin_router.post("/{request_id}/reject")
async def reject_permission_request(
    request_id: str,
    request: PermissionRequestDecisionRequest,
    scope: AdminActorScope,
):
    context = _require_context()
    try:
        record = permission_request_service.reject_request(
            context,
            scope,
            request_id,
            reason=request.reason,
        )
    except PermissionRequestError as exc:
        raise _permission_request_error_to_http(exc) from exc
    return success_payload(
        {
            "permission_request": await permission_request_service.request_payload(record)
        }
    )
