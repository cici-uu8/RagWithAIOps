"""Session ownership and persistent history service."""

from __future__ import annotations

from loguru import logger

from app.enterprise.context import RequestContext
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.observability.models import AuditEvent
from app.enterprise.sessions.models import ChatMessageRecord, ChatSessionRecord
from app.enterprise.sessions.repository import (
    ChatSessionRepository,
    InMemoryChatSessionRepository,
    SQLiteChatSessionRepository,
)


class SessionAccessError(PermissionError):
    pass


class SessionAccess:
    def __init__(
        self,
        *,
        repository: ChatSessionRepository | None = None,
        audit_service: AuditService | None = None,
    ):
        self.repository = repository or InMemoryChatSessionRepository()
        self.audit_service = audit_service or AuditService()

    def claim_or_assert_owner(
        self,
        context: RequestContext,
        session_id: str,
        *,
        kind: str = "chat",
        title: str | None = None,
        route: str = "chat_session",
    ) -> ChatSessionRecord:
        session_id = self._require_text(session_id, "session_id")
        existing = self.repository.get(session_id)
        if existing is not None and existing.user_id != context.user_id:
            self.audit_denial(context, session_id, route=route, action="write")
            raise SessionAccessError("Session belongs to another user")
        return self.repository.create_or_touch(
            session_id,
            context.user_id,
            kind=kind,
            title=title,
        )

    def assert_read(
        self,
        context: RequestContext,
        session_id: str,
        *,
        route: str = "chat_session",
    ) -> ChatSessionRecord:
        return self._assert_owner(context, session_id, route=route, action="read")

    def assert_write(
        self,
        context: RequestContext,
        session_id: str,
        *,
        route: str = "chat_session",
    ) -> ChatSessionRecord:
        return self._assert_owner(context, session_id, route=route, action="write")

    def assert_clear(
        self,
        context: RequestContext,
        session_id: str,
        *,
        route: str = "chat_session",
    ) -> ChatSessionRecord:
        return self._assert_owner(context, session_id, route=route, action="clear")

    def append_message(
        self,
        context: RequestContext,
        session_id: str,
        *,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> ChatMessageRecord | None:
        if not content:
            return None
        self.assert_write(context, session_id)
        try:
            return self.repository.append_message(
                session_id,
                context.user_id,
                role,
                content,
                metadata or {},
            )
        except Exception as exc:
            self.audit_degraded(context, session_id, reason=type(exc).__name__)
            logger.warning("Persistent chat message write failed: {}", exc)
            return None

    def list_by_user(self, context: RequestContext) -> list[ChatSessionRecord]:
        return self.repository.list_by_user(context.user_id)

    def get_messages(
        self,
        context: RequestContext,
        session_id: str,
    ) -> list[ChatMessageRecord]:
        self.assert_read(context, session_id)
        return self.repository.get_messages(session_id, context.user_id)

    def archive(self, context: RequestContext, session_id: str) -> bool:
        self.assert_clear(context, session_id)
        return self.repository.archive(session_id, context.user_id)

    def clear(self) -> None:
        self.repository.clear()

    def audit_denial(
        self,
        context: RequestContext,
        session_id: str,
        *,
        route: str,
        action: str,
    ) -> None:
        self.audit_service.record(
            AuditEvent(
                event_type="permission_checked",
                route=route,
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision="denied",
                reason="session_owner_mismatch",
                metadata={
                    "resource_type": "chat_session",
                    "resource_id": session_id,
                    "action": action,
                    "denial_reason": "session_owner_mismatch",
                },
            )
        )

    def audit_degraded(
        self,
        context: RequestContext,
        session_id: str,
        *,
        reason: str,
    ) -> None:
        self.audit_service.record(
            AuditEvent(
                event_type="chat_session_persistence_degraded",
                route="chat_session",
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision="degraded",
                reason=reason,
                metadata={
                    "resource_type": "chat_session",
                    "resource_id": session_id,
                },
            )
        )

    def _assert_owner(
        self,
        context: RequestContext,
        session_id: str,
        *,
        route: str,
        action: str,
    ) -> ChatSessionRecord:
        session_id = self._require_text(session_id, "session_id")
        session = self.repository.get(session_id)
        if session is None or session.user_id != context.user_id:
            self.audit_denial(context, session_id, route=route, action=action)
            raise SessionAccessError("Session belongs to another user")
        return session

    @staticmethod
    def _require_text(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise SessionAccessError(f"{field_name} is required")
        return value.strip()


session_access = SessionAccess(repository=SQLiteChatSessionRepository())
