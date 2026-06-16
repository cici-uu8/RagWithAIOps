"""Scoped admin resolution for Stage 4."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field

from app.enterprise.auth.models import UserProfile
from app.enterprise.permissions.models import PrincipalType

from .departments import (
    DepartmentRecord,
    DepartmentResourceRef,
    DepartmentService,
    department_service,
)


class AdminScope(BaseModel):
    scope_type: Literal["global", "department"]
    department_id: str | None = None
    manageable_resources: list[DepartmentResourceRef] = Field(default_factory=list)

    @computed_field
    @property
    def manageable_resource_types(self) -> list[str]:
        return sorted({resource.resource_type for resource in self.manageable_resources})

    @computed_field
    @property
    def manageable_resource_ids(self) -> list[str]:
        return sorted({resource.resource_id for resource in self.manageable_resources})


class AdminScopeError(ValueError):
    pass


class AdminScopeService:
    def __init__(self, department_service: DepartmentService | None = None):
        self.department_service = department_service or department_service_default()

    def resolve_scope(self, user: UserProfile) -> AdminScope | None:
        roles = set(user.roles)
        if "admin" in roles:
            return AdminScope(scope_type="global", department_id=None, manageable_resources=[])
        if "department_admin" not in roles:
            return None

        department = self.department_service.get_department(user.department_id)
        if department is None:
            raise AdminScopeError(f"Department not found: {user.department_id}")
        if department.department_id == "system":
            raise AdminScopeError("System department is not configurable")
        return self._build_department_scope(department)

    def assert_request_in_scope(self, scope: AdminScope, request_payload: dict) -> None:
        if scope.scope_type == "global":
            return

        resource_type = request_payload.get("resource_type")
        resource_id = request_payload.get("resource_id")
        action = request_payload.get("action")
        if not self._resource_allowed(scope, resource_type, resource_id, action):
            raise AdminScopeError("Request resource is outside department scope")

    def filter_users(self, scope: AdminScope, users: list[UserProfile]) -> list[UserProfile]:
        if scope.scope_type == "global":
            return list(users)
        return [user for user in users if user.department_id == scope.department_id]

    def filter_resources(self, scope: AdminScope, resources: list) -> list:
        if scope.scope_type == "global":
            return list(resources)
        allowed = {
            (resource.resource_type, resource.resource_id)
            for resource in scope.manageable_resources
        }
        return [
            resource
            for resource in resources
            if (getattr(resource, "resource_type", None), getattr(resource, "resource_id", None)) in allowed
        ]

    def filter_grants(self, scope: AdminScope, grants: list, auth_service) -> list:
        if scope.scope_type == "global":
            return list(grants)

        department_user_ids = self._department_user_ids(scope, auth_service)
        return [
            grant
            for grant in grants
            if (
                grant.principal_type == PrincipalType.USER
                and grant.principal_id in department_user_ids
            )
            or (
                grant.principal_type == PrincipalType.DEPARTMENT
                and grant.principal_id == scope.department_id
            )
        ]

    def filter_audit_events(self, scope: AdminScope, events: list, auth_service) -> list:
        if scope.scope_type == "global":
            return list(events)

        department_user_ids = self._department_user_ids(scope, auth_service)
        return [
            event
            for event in events
            if event.user_id in department_user_ids
            or (
                event.event_type == "admin_operation"
                and event.user_id in department_user_ids
            )
        ]

    def _build_department_scope(self, department: DepartmentRecord) -> AdminScope:
        return AdminScope(
            scope_type="department",
            department_id=department.department_id,
            manageable_resources=list(department.manageable_resources),
        )

    def _resource_allowed(
        self,
        scope: AdminScope,
        resource_type: str | None,
        resource_id: str | None,
        action: str | None,
    ) -> bool:
        if not resource_type or not resource_id:
            return False
        return any(
            resource.allows(
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
            )
            for resource in scope.manageable_resources
        )

    def _department_user_ids(self, scope: AdminScope, auth_service) -> set[str]:
        if scope.department_id is None:
            return set()
        return {
            user.user_id
            for user in auth_service.list_users()
            if user.department_id == scope.department_id
        }


def department_service_default() -> DepartmentService:
    return department_service


admin_scope_service = AdminScopeService()
