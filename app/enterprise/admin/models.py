"""Models for E8 admin management APIs."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, computed_field

from app.enterprise.permissions.models import GrantEffect, PrincipalType

from .departments import DepartmentResourceRef


class AdminUserCreateRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    department_id: str = Field(..., min_length=1)
    department_name: str = Field(..., min_length=1)
    roles: list[str] = Field(default_factory=list)


class AdminUserUpdateRequest(BaseModel):
    username: str | None = None
    password: str | None = None
    department_id: str | None = None
    department_name: str | None = None
    roles: list[str] | None = None
    is_active: bool | None = None


class RoleRecord(BaseModel):
    role_id: str
    name: str
    description: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RoleCreateRequest(BaseModel):
    role_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""


class RoleUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class GrantCreateRequest(BaseModel):
    resource_type: str = Field(..., min_length=1)
    resource_id: str = Field(..., min_length=1)
    action: str = Field(..., min_length=1)
    principal_type: PrincipalType
    principal_id: str = Field(..., min_length=1)
    effect: GrantEffect
    reason: str | None = None


class AdminResourceDescriptor(BaseModel):
    resource_type: str = Field(..., min_length=1)
    resource_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""
    actions_supported: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GrantValidationCheck(BaseModel):
    check: str
    status: str
    message: str
    matched_grant_ids: list[str] = Field(default_factory=list)


class GrantPreviewResult(BaseModel):
    can_submit: bool
    checks: list[GrantValidationCheck]

    @property
    def failed_check(self) -> str | None:
        for check in self.checks:
            if check.status == "failed":
                return check.check
        return None


class AuditQuery(BaseModel):
    trace_id: str | None = None
    user_id: str | None = None
    event_type: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None


class DepartmentResourceScopeUpdateRequest(BaseModel):
    resources: list[DepartmentResourceRef] = Field(default_factory=list)


class DepartmentScopeResponse(BaseModel):
    department_id: str
    name: str
    admin_user_ids: list[str] = Field(default_factory=list)
    manageable_resources: list[DepartmentResourceRef] = Field(default_factory=list)

    @computed_field
    @property
    def manageable_resource_types(self) -> list[str]:
        return sorted({resource.resource_type for resource in self.manageable_resources})

    @computed_field
    @property
    def manageable_resource_ids(self) -> list[str]:
        return sorted({resource.resource_id for resource in self.manageable_resources})


def success_payload(data: dict[str, Any]) -> dict[str, Any]:
    return {"code": 200, "message": "success", "data": data}
