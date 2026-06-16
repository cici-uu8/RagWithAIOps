"""Enterprise exceptions carrying structured recovery metadata."""

from __future__ import annotations

from app.enterprise.errors.models import ErrorContext, RecoveryPlan
from app.enterprise.errors.recovery import RecoveryStrategy


class EnterpriseError(Exception):
    def __init__(
        self,
        context: ErrorContext,
        *,
        message: str | None = None,
        cause: BaseException | None = None,
        strategy: RecoveryStrategy | None = None,
    ):
        self.context = context
        self.cause = cause
        self.recovery: RecoveryPlan = (strategy or RecoveryStrategy()).decide(context)
        super().__init__(message or self.recovery.user_message)
