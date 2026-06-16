"""Models for the E2 request gateway."""

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.enterprise.auth.service import AuthError, auth_service
from app.enterprise.context import get_current_request_context


class GatewayRequest(BaseModel):
    route: str
    payload: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
    request_id: str | None = None
    user_id: str = "anonymous"
    username: str = "anonymous"
    department_id: str = "unknown"
    department_name: str = "Unknown"
    roles: list[str] = Field(default_factory=list)

    @classmethod
    def from_headers(
        cls,
        *,
        route: str,
        payload: dict[str, Any] | None = None,
        headers,
    ) -> "GatewayRequest":
        current_context = get_current_request_context()
        authenticated_user = None
        authorization = headers.get("Authorization") if headers else None
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()
            try:
                authenticated_user, _payload = auth_service.validate_access_token(token)
            except AuthError:
                authenticated_user = None

        if authenticated_user is not None:
            return cls(
                route=route,
                payload=payload or {},
                trace_id=headers.get("X-Trace-Id") or (current_context.trace_id if current_context else None),
                request_id=headers.get("X-Request-Id") or (current_context.request_id if current_context else None),
                user_id=authenticated_user.user_id,
                username=authenticated_user.username,
                department_id=authenticated_user.department_id,
                department_name=authenticated_user.department_name,
                roles=list(authenticated_user.roles),
            )

        return cls(
            route=route,
            payload=payload or {},
            trace_id=headers.get("X-Trace-Id") or (current_context.trace_id if current_context else None),
            request_id=headers.get("X-Request-Id") or (current_context.request_id if current_context else None),
            user_id=headers.get("X-User-Id") or (current_context.user_id if current_context else "anonymous"),
            username=headers.get("X-Username") or (current_context.username if current_context else "anonymous"),
            department_id=headers.get("X-Department-Id")
            or (current_context.department_id if current_context else "unknown"),
            department_name=headers.get("X-Department-Name")
            or (current_context.department_name if current_context else "Unknown"),
            roles=cls._parse_roles(
                headers.get("X-Roles") or (
                    ",".join(current_context.roles) if current_context else ""
                )
            ),
        )

    @staticmethod
    def _parse_roles(raw_roles: str) -> list[str]:
        if not raw_roles:
            return []
        return [role.strip() for role in raw_roles.split(",") if role.strip()]

    def ensure_trace_id(self) -> str:
        if not self.trace_id:
            self.trace_id = str(uuid4())
        return self.trace_id

    def ensure_request_id(self) -> str:
        if not self.request_id:
            self.request_id = str(uuid4())
        return self.request_id


class GuardrailDecision(BaseModel):
    allowed: bool = True
    decision: str = "allowed"
    reason: str | None = None
    rule_id: str | None = None


class RateLimitDecision(BaseModel):
    allowed: bool = True
    decision: str = "allowed"
    reason: str | None = None
