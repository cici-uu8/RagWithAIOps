"""Grant preview and create validation for Optimization 2 Stage 3-lite."""

from __future__ import annotations

from app.enterprise.admin.models import (
    GrantCreateRequest,
    GrantPreviewResult,
    GrantValidationCheck,
)
from app.enterprise.admin.resources import ResourceCatalogService
from app.enterprise.admin.scopes import AdminScope
from app.enterprise.auth.service import AuthService, auth_service
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.service import PermissionService

CHECK_RESOURCE_EXISTS = "resource_exists"
CHECK_ACTION_SUPPORTED = "action_supported"
CHECK_PRINCIPAL_EXISTS = "principal_exists"
CHECK_SCOPE_ALLOWED = "scope_allowed"
CHECK_DUPLICATE_GRANT = "duplicate_grant"
CHECK_DIRECT_CONFLICT = "direct_conflict"
CHECK_ORDER = [
    CHECK_RESOURCE_EXISTS,
    CHECK_ACTION_SUPPORTED,
    CHECK_PRINCIPAL_EXISTS,
    CHECK_SCOPE_ALLOWED,
    CHECK_DUPLICATE_GRANT,
    CHECK_DIRECT_CONFLICT,
]


class GrantValidator:
    def __init__(
        self,
        *,
        resource_catalog: ResourceCatalogService,
        permission_service: PermissionService,
        auth: AuthService | None = None,
        roles_by_id: dict[str, object] | None = None,
    ):
        self.resource_catalog = resource_catalog
        self.permission_service = permission_service
        self.auth = auth or auth_service
        self.roles_by_id = roles_by_id if roles_by_id is not None else {}

    async def preview(
        self,
        request: GrantCreateRequest,
        scope: AdminScope | None = None,
    ) -> GrantPreviewResult:
        checks: list[GrantValidationCheck] = []

        resource = await self.resource_catalog.get_resource(
            resource_type=request.resource_type,
            resource_id=request.resource_id,
        )
        if resource is None:
            checks.append(_failed(CHECK_RESOURCE_EXISTS, "Resource is not in catalog."))
            checks.extend(_skipped_after(CHECK_RESOURCE_EXISTS, start_after=CHECK_RESOURCE_EXISTS))
            return GrantPreviewResult(can_submit=False, checks=checks)
        checks.append(_passed(CHECK_RESOURCE_EXISTS, "Resource exists in catalog."))

        if request.action not in resource.actions_supported:
            checks.append(_failed(CHECK_ACTION_SUPPORTED, "Action is not supported for this resource."))
        else:
            checks.append(_passed(CHECK_ACTION_SUPPORTED, "Action is supported for this resource."))

        if not self._principal_exists(request.principal_type, request.principal_id):
            checks.append(_failed(CHECK_PRINCIPAL_EXISTS, "Principal does not exist."))
        else:
            checks.append(_passed(CHECK_PRINCIPAL_EXISTS, "Principal exists."))

        if self._scope_allowed(scope, request):
            checks.append(_passed(CHECK_SCOPE_ALLOWED, "Request is inside department scope."))
        else:
            checks.append(_failed(CHECK_SCOPE_ALLOWED, "Request is outside department scope."))

        duplicate_grants = self._matching_grants(request, include_effect=True)
        if duplicate_grants:
            checks.append(
                _failed(
                    CHECK_DUPLICATE_GRANT,
                    "Duplicate grant already exists.",
                    duplicate_grants,
                )
            )
        else:
            checks.append(_passed(CHECK_DUPLICATE_GRANT, "No duplicate grant found."))

        conflict_grants = self._opposite_effect_grants(request)
        if conflict_grants:
            checks.append(
                GrantValidationCheck(
                    check=CHECK_DIRECT_CONFLICT,
                    status="warning",
                    message=_conflict_message(request.effect),
                    matched_grant_ids=[grant.grant_id for grant in conflict_grants],
                )
            )
        else:
            checks.append(_passed(CHECK_DIRECT_CONFLICT, "No direct allow/deny conflict found."))

        can_submit = not any(check.status == "failed" for check in checks)
        return GrantPreviewResult(can_submit=can_submit, checks=checks)

    def _principal_exists(self, principal_type: PrincipalType, principal_id: str) -> bool:
        if principal_type == PrincipalType.PUBLIC:
            return principal_id == "*"
        if principal_type == PrincipalType.USER:
            return any(user.user_id == principal_id for user in self.auth.list_users())
        if principal_type == PrincipalType.ROLE:
            return principal_id in self.roles_by_id
        if principal_type == PrincipalType.DEPARTMENT:
            # Stage 3-lite: department validation is best-effort, derived from active user list.
            # Stage 4 will replace this with explicit DepartmentService.
            return principal_id in {user.department_id for user in self.auth.list_users()}
        return False

    def _matching_grants(
        self,
        request: GrantCreateRequest,
        *,
        include_effect: bool,
    ) -> list[ResourceGrant]:
        grants = self.permission_service.repository.list_all_grants(
            resource_type=request.resource_type,
            resource_id=request.resource_id,
            action=request.action,
            principal_type=request.principal_type.value,
            principal_id=request.principal_id,
        )
        if include_effect:
            grants = [grant for grant in grants if grant.effect == request.effect]
        return grants

    def _opposite_effect_grants(self, request: GrantCreateRequest) -> list[ResourceGrant]:
        opposite = GrantEffect.DENY if request.effect == GrantEffect.ALLOW else GrantEffect.ALLOW
        return [
            grant
            for grant in self._matching_grants(request, include_effect=False)
            if grant.effect == opposite
        ]

    def _scope_allowed(self, scope: AdminScope | None, request: GrantCreateRequest) -> bool:
        if scope is None or scope.scope_type == "global":
            return True

        if request.principal_type == PrincipalType.USER:
            if request.principal_id not in {
                user.user_id
                for user in self.auth.list_users()
                if user.department_id == scope.department_id
            }:
                return False
        elif request.principal_type == PrincipalType.DEPARTMENT:
            if request.principal_id != scope.department_id:
                return False
        else:
            return False

        return any(
            resource.allows(
                resource_type=request.resource_type,
                resource_id=request.resource_id,
                action=request.action,
            )
            for resource in scope.manageable_resources
        )


def _passed(check: str, message: str) -> GrantValidationCheck:
    return GrantValidationCheck(check=check, status="passed", message=message)


def _failed(
    check: str,
    message: str,
    matched_grants: list[ResourceGrant] | None = None,
) -> GrantValidationCheck:
    return GrantValidationCheck(
        check=check,
        status="failed",
        message=message,
        matched_grant_ids=[grant.grant_id for grant in matched_grants or []],
    )


def _skipped_after(failed_check: str, *, start_after: str) -> list[GrantValidationCheck]:
    start_index = CHECK_ORDER.index(start_after) + 1
    return [
        GrantValidationCheck(
            check=check,
            status="skipped",
            message=f"Skipped because {failed_check} failed.",
        )
        for check in CHECK_ORDER[start_index:]
    ]


def _conflict_message(effect: GrantEffect) -> str:
    if effect == GrantEffect.ALLOW:
        return "Existing deny will block this allow (deny precedes allow)."
    return "This deny will override existing allow grant."
