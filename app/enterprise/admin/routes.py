"""FastAPI routes for E8 minimal admin management."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.enterprise.auth.dependencies import CurrentUser
from app.enterprise.auth.models import UserProfile
from app.enterprise.context import RequestContext, get_current_request_context

from .models import (
    AdminUserCreateRequest,
    AdminUserUpdateRequest,
    DepartmentResourceScopeUpdateRequest,
    DepartmentScopeResponse,
    GrantCreateRequest,
    RoleCreateRequest,
    RoleUpdateRequest,
    success_payload,
)
from .scopes import AdminScope, AdminScopeError, admin_scope_service
from .service import AdminError, AdminScopeDenied, admin_service

router = APIRouter(prefix="/admin", tags=["企业管理"])


def _require_context() -> RequestContext:
    context = get_current_request_context()
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="RequestContext is missing",
        )
    return context


def require_admin_user(current_user: CurrentUser) -> UserProfile:
    if "admin" not in current_user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return current_user


AdminUser = Annotated[UserProfile, Depends(require_admin_user)]


def require_admin_actor(current_user: CurrentUser) -> AdminScope:
    try:
        scope = admin_scope_service.resolve_scope(current_user)
    except AdminScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    if scope is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return scope


AdminActorScope = Annotated[AdminScope, Depends(require_admin_actor)]


def _admin_error_to_http(exc: AdminError) -> HTTPException:
    if isinstance(exc, AdminScopeDenied):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    detail = str(exc)
    status_code = status.HTTP_404_NOT_FOUND if "not found" in detail.lower() else status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=status_code, detail=detail)


@router.get("/scope")
async def get_admin_scope(scope: AdminActorScope):
    return success_payload({"scope": scope.model_dump(mode="json")})


@router.get("/departments")
async def list_departments(_admin: AdminUser):
    departments = [department.model_dump(mode="json") for department in admin_service.list_departments()]
    return success_payload({"departments": departments})


@router.patch("/departments/{department_id}/resource-scope")
async def update_department_resource_scope(
    department_id: str,
    request: DepartmentResourceScopeUpdateRequest,
    _admin: AdminUser,
):
    context = _require_context()
    try:
        department = await admin_service.update_department_resource_scope(
            context,
            department_id,
            request.resources,
        )
    except AdminError as exc:
        raise _admin_error_to_http(exc) from exc
    response = DepartmentScopeResponse.model_validate(department.model_dump(mode="json"))
    return success_payload({"department": response.model_dump(mode="json")})


@router.get("/users")
async def list_users(scope: AdminActorScope):
    users = [user.model_dump(mode="json") for user in admin_service.list_users(scope)]
    return success_payload({"users": users})


@router.post("/users")
async def create_user(request: AdminUserCreateRequest, scope: AdminActorScope):
    context = _require_context()
    try:
        user = admin_service.create_user(context, scope, **request.model_dump())
    except AdminError as exc:
        raise _admin_error_to_http(exc) from exc
    return success_payload({"user": user.model_dump(mode="json")})


@router.patch("/users/{user_id}")
async def update_user(user_id: str, request: AdminUserUpdateRequest, scope: AdminActorScope):
    context = _require_context()
    try:
        user = admin_service.update_user(
            context,
            scope,
            user_id,
            **request.model_dump(exclude_unset=True),
        )
    except AdminError as exc:
        raise _admin_error_to_http(exc) from exc
    return success_payload({"user": user.model_dump(mode="json")})


@router.post("/users/{user_id}/disable")
async def disable_user(user_id: str, scope: AdminActorScope):
    context = _require_context()
    try:
        user = admin_service.disable_user(context, scope, user_id)
    except AdminError as exc:
        raise _admin_error_to_http(exc) from exc
    return success_payload({"user": user.model_dump(mode="json")})


@router.get("/roles")
async def list_roles(_admin: AdminUser):
    roles = [role.model_dump(mode="json") for role in admin_service.list_roles()]
    return success_payload({"roles": roles})


@router.post("/roles")
async def create_role(request: RoleCreateRequest, _admin: AdminUser):
    context = _require_context()
    try:
        role = admin_service.create_role(context, **request.model_dump())
    except AdminError as exc:
        raise _admin_error_to_http(exc) from exc
    return success_payload({"role": role.model_dump(mode="json")})


@router.patch("/roles/{role_id}")
async def update_role(role_id: str, request: RoleUpdateRequest, _admin: AdminUser):
    context = _require_context()
    try:
        role = admin_service.update_role(
            context,
            role_id,
            **request.model_dump(exclude_unset=True),
        )
    except AdminError as exc:
        raise _admin_error_to_http(exc) from exc
    return success_payload({"role": role.model_dump(mode="json")})


@router.delete("/roles/{role_id}")
async def delete_role(role_id: str, _admin: AdminUser):
    context = _require_context()
    try:
        admin_service.delete_role(context, role_id)
    except AdminError as exc:
        raise _admin_error_to_http(exc) from exc
    return success_payload({"deleted": True})


@router.get("/grants")
async def list_grants(
    scope: AdminActorScope,
    resource_type: str | None = None,
    resource_id: str | None = None,
    action: str | None = None,
    principal_type: str | None = None,
    principal_id: str | None = None,
):
    grants = admin_service.list_grants(
        scope,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        principal_type=principal_type,
        principal_id=principal_id,
    )
    return success_payload({"grants": [grant.model_dump(mode="json") for grant in grants]})


@router.get("/resources")
async def list_resources(scope: AdminActorScope):
    resources = await admin_service.list_resources(scope)
    return success_payload({"resources": [resource.model_dump(mode="json") for resource in resources]})


@router.post("/grant-preview")
async def preview_grant(request: GrantCreateRequest, scope: AdminActorScope):
    preview = await admin_service.preview_grant(scope, request)
    return success_payload(preview.model_dump(mode="json"))


# Do not add POST /grants/preview here: it is shadowed by DELETE /grants/{grant_id}.
@router.post("/grants")
async def grant_access(request: GrantCreateRequest, scope: AdminActorScope):
    context = _require_context()
    try:
        grant = await admin_service.grant_access(context, scope, request)
    except AdminError as exc:
        raise _admin_error_to_http(exc) from exc
    return success_payload({"grant": grant.model_dump(mode="json")})


@router.delete("/grants/{grant_id}")
async def revoke_grant(grant_id: str, _admin: AdminUser):
    context = _require_context()
    revoked = admin_service.revoke_grant(context, grant_id)
    return success_payload({"revoked": revoked})


@router.get("/audit")
async def query_audit(
    scope: AdminActorScope,
    trace_id: str | None = None,
    user_id: str | None = None,
    event_type: str | None = None,
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
):
    context = _require_context()
    events = admin_service.query_audit_events(
        context,
        scope,
        trace_id=trace_id,
        user_id=user_id,
        event_type=event_type,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )
    return success_payload({"events": [event.model_dump(mode="json") for event in events]})


@router.get("/traces/compare")
async def compare_traces(
    scope: AdminActorScope,
    left: str = Query(..., min_length=1),
    right: str = Query(..., min_length=1),
):
    context = _require_context()
    try:
        comparison = admin_service.compare_traces(context, scope, left=left, right=right)
    except AdminError as exc:
        raise _admin_error_to_http(exc) from exc
    return success_payload({"comparison": comparison})


@router.get("/traces/{trace_id}")
async def get_trace_timeline(trace_id: str, scope: AdminActorScope):
    context = _require_context()
    try:
        trace = admin_service.get_trace_timeline(context, scope, trace_id=trace_id)
    except AdminError as exc:
        raise _admin_error_to_http(exc) from exc
    return success_payload({"trace": trace})
