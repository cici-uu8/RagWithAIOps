"""Base verifier contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.enterprise.context import RequestContext
from app.enterprise.verifiers.models import (
    VerificationFinding,
    VerificationResult,
    VerificationStatus,
)


class BaseVerifier(ABC):
    name: str = "BaseVerifier"
    max_revision_attempts: int = 1

    @abstractmethod
    def verify(self, context: RequestContext, payload: dict[str, Any]) -> VerificationResult:
        """Return a deterministic verification result."""

    def _result(
        self,
        status: VerificationStatus,
        findings: list[VerificationFinding] | None = None,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> VerificationResult:
        findings = findings or []
        return VerificationResult(
            verifier=self.name,
            status=status,
            findings=findings,
            revision_required=status == VerificationStatus.NEEDS_REVISION,
            max_revision_attempts=self.max_revision_attempts,
            metadata=metadata or {},
        )

    def _finding(
        self,
        code: str,
        message: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> VerificationFinding:
        return VerificationFinding(
            code=code,
            message=message,
            metadata=metadata or {},
        )
