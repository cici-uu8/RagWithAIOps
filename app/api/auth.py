"""Enterprise E1 auth routes."""

from fastapi import APIRouter, HTTPException, status

from app.enterprise.auth.dependencies import CurrentUser, TokenDep
from app.enterprise.auth.models import LoginRequest, UserProfile
from app.enterprise.auth.service import AuthError, auth_service
from app.enterprise.context import RequestContext, get_current_request_context
from app.enterprise.profile import profile_service

router = APIRouter()


def _success(data: dict) -> dict:
    return {
        "code": 200,
        "message": "success",
        "data": data,
    }


def _profile_payload(user: UserProfile) -> dict:
    return user.model_dump()


def _require_request_context() -> RequestContext:
    context = get_current_request_context()
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="RequestContext is missing",
        )
    return context


@router.post("/auth/login")
async def login(request: LoginRequest):
    try:
        user = auth_service.authenticate(request.username, request.password)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    access_token = auth_service.create_access_token(user)
    return _success(
        {
            "access_token": access_token,
            "token_type": "bearer",
            "user": _profile_payload(user),
        }
    )


@router.post("/auth/logout")
async def logout(token: TokenDep, _current_user: CurrentUser):
    auth_service.blacklist_token(token)
    return _success({"success": True})


@router.get("/auth/me")
async def me(current_user: CurrentUser):
    context = _require_request_context()
    return _success(
        {
            "user": _profile_payload(current_user),
            "trace_id": context.trace_id,
        }
    )


@router.get("/me/profile")
async def me_profile(current_user: CurrentUser):
    context = _require_request_context()
    profile = await profile_service.build_profile(context)
    profile["trace_id"] = context.trace_id
    profile["request_id"] = context.request_id
    profile["user"] = _profile_payload(current_user)
    return _success(profile)


@router.get("/auth/protected")
async def protected(_current_user: CurrentUser):
    context = _require_request_context()
    return _success(
        {
            "user_id": context.user_id,
            "department_id": context.department_id,
            "roles": list(context.roles),
            "trace_id": context.trace_id,
        }
    )
