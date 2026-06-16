"""Verification result models for Enterprise 2.0 F4."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class VerificationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NEEDS_REVISION = "needs_revision"


class VerificationFinding(BaseModel):
    code: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    verifier: str
    status: VerificationStatus
    findings: list[VerificationFinding] = Field(default_factory=list)
    revision_required: bool = False
    max_revision_attempts: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == VerificationStatus.PASSED
