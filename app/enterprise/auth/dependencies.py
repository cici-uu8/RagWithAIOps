"""FastAPI dependencies for enterprise local auth."""

from collections.abc import AsyncGenerator
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from app.enterprise.auth.models import UserProfile
from app.enterprise.auth.service import AuthError, auth_service
from app.enterprise.context import (
    RequestContext,
    reset_current_request_context,
    set_current_request_context,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
TokenDep = Annotated[str, Depends(oauth2_scheme)]


async def get_current_user(
    request: Request,
    token: TokenDep,
) -> AsyncGenerator[UserProfile, None]:
    try:
        user, _payload = auth_service.validate_access_token(token)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    trace_id = request.headers.get("X-Trace-Id") or str(uuid4())
    request_id = request.headers.get("X-Request-Id") or str(uuid4())
    context_token = set_current_request_context(
        RequestContext(
            request_id=request_id,
            trace_id=trace_id,
            user_id=user.user_id,
            username=user.username,
            department_id=user.department_id,
            department_name=user.department_name,
            roles=user.roles,
        )
    )
    try:
        yield user
    finally:
        reset_current_request_context(context_token)


CurrentUser = Annotated[UserProfile, Depends(get_current_user)]
