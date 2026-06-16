"""Service for permission request submission and review routing."""

from datetime import UTC, datetime

from app.enterprise.admin.departments import DepartmentService, department_service
from app.enterprise.admin.models import GrantCreateRequest
from app.enterprise.admin.resources import ResourceCatalogService, resource_catalog_service
from app.enterprise.admin.scopes import AdminScope
from app.enterprise.auth.service import AuthService, auth_service
from app.enterprise.context import RequestContext
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.observability.models import AuditEvent
from app.enterprise.permission_requests.models import (
    PermissionRequestCreateRequest,
    PermissionRequestRecord,
    PermissionRequestStatus,
)
from app.enterprise.permissions.models import GrantEffect, PrincipalType
from app.enterprise.permissions.service import (
    PermissionService,
    permission_service as default_permission_service,
)


class PermissionRequestError(ValueError):
    pass


class PermissionRequestService:
    def __init__(
        self,
        *,
        resource_catalog: ResourceCatalogService | None = None,
        permission_service: PermissionService | None = None,
        auth: AuthService | None = None,
        departments: DepartmentService | None = None,
        audit_service: AuditService | None = None,
    ):
        self.resource_catalog = resource_catalog or resource_catalog_service
        self.permission_service = permission_service or default_permission_service
        self.auth = auth or auth_service
        self.departments = departments or department_service
        self.audit_service = audit_service or AuditService()
        self._requests_by_id: dict[str, PermissionRequestRecord] = {}

    async def list_requestable_resources(self, context: RequestContext) -> list[dict]:
        resources = await self.resource_catalog.list_resources()
        payloads: list[dict] = []
        for resource in resources:
            action_grants = {
                action: self.permission_service.check(
                    context,
                    resource_type=resource.resource_type,
                    resource_id=resource.resource_id,
                    action=action,
                ).allowed
                for action in resource.actions_supported
            }
            payload = resource.model_dump(mode="json")
            payload["already_granted"] = bool(action_grants) and all(action_grants.values())
            payload["action_options"] = [
                {
                    "action": action,
                    "display_name": _action_display_name(action),
                    "already_granted": action_grants[action],
                }
                for action in resource.actions_supported
            ]
            payload["metadata"] = {
                **payload.get("metadata", {}),
                "display_name": payload.get("metadata", {}).get("display_name", resource.name),
            }
            payloads.append(payload)
        return payloads

    async def create_request(
        self,
        context: RequestContext,
        request: PermissionRequestCreateRequest,
    ) -> PermissionRequestRecord:
        resource = await self.resource_catalog.get_resource(
            resource_type=request.resource_type,
            resource_id=request.resource_id,
        )
        if resource is None:
            raise PermissionRequestError("permission_request_resource_not_found")
        if request.action not in resource.actions_supported:
            raise PermissionRequestError("permission_request_action_not_supported")

        decision = self.permission_service.check(
            context,
            resource_type=request.resource_type,
            resource_id=request.resource_id,
            action=request.action,
        )
        if decision.allowed:
            raise PermissionRequestError("permission_already_granted")
        if self._has_duplicate_pending(context, request):
            raise PermissionRequestError("permission_request_duplicate_pending")

        candidate_department_ids = self._candidate_department_ids(request)
        review_queue, requires_global_review = self._route_request(
            context,
            candidate_department_ids,
        )
        record = PermissionRequestRecord(
            requester_user_id=context.user_id,
            requester_username=context.username,
            requester_department_id=context.department_id,
            requester_department_name=context.department_name,
            resource_type=request.resource_type,
            resource_id=request.resource_id,
            action=request.action,
            reason=request.reason,
            review_queue=review_queue,
            requires_global_review=requires_global_review,
            candidate_department_ids=candidate_department_ids,
        )
        self._requests_by_id[record.request_id] = record
        self._record_audit(context, "permission_request_created", record)
        return record

    def list_my_requests(self, context: RequestContext) -> list[PermissionRequestRecord]:
        return [
            record
            for record in sorted(
                self._requests_by_id.values(),
                key=lambda item: item.created_at,
                reverse=True,
            )
            if record.requester_user_id == context.user_id
        ]

    def list_reviewable_requests(self, scope: AdminScope) -> list[PermissionRequestRecord]:
        pending = [
            record
            for record in sorted(
                self._requests_by_id.values(),
                key=lambda item: item.created_at,
                reverse=True,
            )
            if record.status == PermissionRequestStatus.PENDING
        ]
        if scope.scope_type == "global":
            return pending
        return [
            record
            for record in pending
            if record.review_queue == f"department:{scope.department_id}"
        ]

    async def request_payload(self, record: PermissionRequestRecord) -> dict:
        payload = record.model_dump(mode="json")
        resource = await self.resource_catalog.get_resource(
            resource_type=record.resource_type,
            resource_id=record.resource_id,
        )
        payload["resource_display_name"] = resource.name if resource is not None else record.resource_id
        payload["resource_description"] = resource.description if resource is not None else ""
        payload["resource_metadata"] = resource.metadata if resource is not None else {}
        payload["action_display_name"] = _action_display_name(record.action)
        return payload

    async def approve_request(
        self,
        context: RequestContext,
        scope: AdminScope,
        request_id: str,
        *,
        reason: str | None,
        admin_service,
    ) -> PermissionRequestRecord:
        record = self._require_pending_reviewable_request(scope, request_id)
        if record.requires_global_review and scope.scope_type != "global":
            raise PermissionRequestError("permission_request_requires_global_review")
        grant = await admin_service.grant_access(
            context,
            scope,
            GrantCreateRequest(
                resource_type=record.resource_type,
                resource_id=record.resource_id,
                action=record.action,
                principal_type=PrincipalType.USER,
                principal_id=record.requester_user_id,
                effect=GrantEffect.ALLOW,
                reason=reason,
            ),
        )
        updated = record.model_copy(
            update={
                "status": PermissionRequestStatus.APPROVED,
                "approver_user_id": context.user_id,
                "approver_reason": reason,
                "grant_id": grant.grant_id,
                "decided_at": datetime.now(UTC),
            }
        )
        self._requests_by_id[request_id] = updated
        self._record_audit(context, "permission_request_approved", updated)
        return updated

    def reject_request(
        self,
        context: RequestContext,
        scope: AdminScope,
        request_id: str,
        *,
        reason: str | None,
    ) -> PermissionRequestRecord:
        record = self._require_pending_reviewable_request(scope, request_id)
        updated = record.model_copy(
            update={
                "status": PermissionRequestStatus.REJECTED,
                "approver_user_id": context.user_id,
                "approver_reason": reason,
                "decided_at": datetime.now(UTC),
            }
        )
        self._requests_by_id[request_id] = updated
        self._record_audit(context, "permission_request_rejected", updated)
        return updated

    def reset(self) -> None:
        self._requests_by_id.clear()

    def _require_pending_reviewable_request(
        self,
        scope: AdminScope,
        request_id: str,
    ) -> PermissionRequestRecord:
        record = self._requests_by_id.get(request_id)
        if record is None or record.status != PermissionRequestStatus.PENDING:
            raise PermissionRequestError("permission_request_not_found")
        if record not in self.list_reviewable_requests(scope):
            raise PermissionRequestError("permission_request_not_found")
        return record

    def _has_duplicate_pending(
        self,
        context: RequestContext,
        request: PermissionRequestCreateRequest,
    ) -> bool:
        return any(
            record.requester_user_id == context.user_id
            and record.resource_type == request.resource_type
            and record.resource_id == request.resource_id
            and record.action == request.action
            and record.status == PermissionRequestStatus.PENDING
            for record in self._requests_by_id.values()
        )

    def _candidate_department_ids(
        self,
        request: PermissionRequestCreateRequest,
    ) -> list[str]:
        department_ids = [
            department.department_id
            for department in self.departments.list_departments()
            if department.department_id != "system"
            and any(
                resource.allows(
                    resource_type=request.resource_type,
                    resource_id=request.resource_id,
                    action=request.action,
                )
                for resource in department.manageable_resources
            )
        ]
        return sorted(department_ids)

    def _route_request(
        self,
        context: RequestContext,
        candidate_department_ids: list[str],
    ) -> tuple[str, bool]:
        if context.department_id == "system" or not self._department_has_admin(context.department_id):
            return "global", True
        return (
            f"department:{context.department_id}",
            context.department_id not in candidate_department_ids,
        )

    def _department_has_admin(self, department_id: str) -> bool:
        return any(
            user.department_id == department_id and "department_admin" in user.roles
            for user in self.auth.list_users()
        )

    def _record_audit(
        self,
        context: RequestContext,
        event_type: str,
        record: PermissionRequestRecord,
    ) -> None:
        metadata = {
            "permission_request_id": record.request_id,
            "requester_user_id": record.requester_user_id,
            "requester_department_id": record.requester_department_id,
            "resource_type": record.resource_type,
            "resource_id": record.resource_id,
            "action": record.action,
            "review_queue": record.review_queue,
            "requires_global_review": record.requires_global_review,
            "candidate_department_ids": record.candidate_department_ids,
        }
        reason = record.reason
        if event_type in {"permission_request_approved", "permission_request_rejected"}:
            metadata["approver_user_id"] = record.approver_user_id
            reason = record.approver_reason
        if event_type == "permission_request_approved":
            metadata["grant_id"] = record.grant_id

        self.audit_service.record(
            AuditEvent(
                event_type=event_type,
                route="permission_requests",
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision=record.status.value,
                reason=reason,
                metadata=metadata,
            )
        )


permission_request_service = PermissionRequestService()


def _action_display_name(action: str) -> str:
    labels = {
        "read": "读取",
        "use": "使用",
        "write": "写入",
        "admin": "管理",
        "execute": "执行",
    }
    return labels.get(action, action)
