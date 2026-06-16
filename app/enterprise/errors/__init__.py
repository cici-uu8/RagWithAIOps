"""Enterprise structured error and recovery helpers for F5."""

from app.enterprise.errors.exceptions import EnterpriseError
from app.enterprise.errors.mapper import build_error_event, map_exception_to_error_context
from app.enterprise.errors.models import ErrorClass, ErrorContext, RecoveryDecision, RecoveryPlan
from app.enterprise.errors.recovery import RecoveryStrategy

__all__ = [
    "EnterpriseError",
    "ErrorClass",
    "ErrorContext",
    "RecoveryDecision",
    "RecoveryPlan",
    "RecoveryStrategy",
    "build_error_event",
    "map_exception_to_error_context",
]
