"""Request-scoped enterprise identity context."""

from collections.abc import Iterable
from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    trace_id: str
    user_id: str
    username: str
    department_id: str
    department_name: str
    roles: tuple[str, ...]

    def __init__(
        self,
        request_id: str,
        trace_id: str,
        user_id: str,
        username: str,
        department_id: str,
        department_name: str,
        roles: Iterable[str],
    ):
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "trace_id", trace_id)
        object.__setattr__(self, "user_id", user_id)
        object.__setattr__(self, "username", username)
        object.__setattr__(self, "department_id", department_id)
        object.__setattr__(self, "department_name", department_name)
        object.__setattr__(self, "roles", tuple(roles))


_current_request_context: ContextVar[RequestContext | None] = ContextVar(
    "enterprise_request_context",
    default=None,
)


def set_current_request_context(context: RequestContext) -> Token[RequestContext | None]:
    return _current_request_context.set(context)


def get_current_request_context() -> RequestContext | None:
    return _current_request_context.get()


def reset_current_request_context(token: Token[RequestContext | None]) -> None:
    _current_request_context.reset(token)


def clear_current_request_context() -> None:
    _current_request_context.set(None)
