"""Permission and registry models for E3."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class PrincipalType(StrEnum):
    USER = "user"
    ROLE = "role"
    DEPARTMENT = "department"
    PUBLIC = "public"


class GrantEffect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class ResourceGrant(BaseModel):
    grant_id: str = Field(default_factory=lambda: str(uuid4()))
    resource_type: str
    resource_id: str
    action: str
    principal_type: PrincipalType
    principal_id: str
    effect: GrantEffect
    reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PermissionDecision(BaseModel):
    allowed: bool
    decision: str
    reason: str
    resource_type: str
    resource_id: str
    action: str
    matched_grant_id: str | None = None
    cache_hit: bool = False


class ResourceDescriptor(BaseModel):
    resource_type: str
    resource_id: str
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
