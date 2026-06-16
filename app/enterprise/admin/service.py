"""Local admin service for E8 minimal management APIs."""

import hashlib
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from app.enterprise.auth.models import UserProfile
from app.enterprise.auth.service import AuthError, AuthService, auth_service
from app.enterprise.context import RequestContext
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.observability.models import AuditEvent
from app.enterprise.permissions.models import ResourceGrant
from app.enterprise.permissions.service import (
    PermissionService,
    permission_service as enterprise_permission_service,
)

from .departments import (
    DepartmentRecord,
    DepartmentResourceRef,
    DepartmentService,
    department_service as default_department_service,
)
from .grant_validator import CHECK_SCOPE_ALLOWED, GrantValidator
from .models import GrantCreateRequest, GrantPreviewResult, RoleRecord
from .resources import ResourceCatalogService, resource_catalog_service
from .scopes import AdminScope, AdminScopeService, admin_scope_service


class AdminError(ValueError):
    pass


class AdminScopeDenied(AdminError):
    pass


PRIVILEGED_ADMIN_ROLES = {"admin", "department_admin"}
TRACE_RETENTION_DAYS = 30
TRACE_QUERY_TARGET_MS = 2000
TRACE_TIMELINE_EVENT_TYPES = {"routing_decision", "rag_retrieval"}
TRACE_EXPECTED_SOURCES = ("routing", "retrieval", "tool", "database", "memory", "sse")
TRACE_TERMINAL_EVENT_TYPES = {"request_completed", "request_failed"}
SENSITIVE_FIELD_NAMES = {
    "authorization",
    "credential",
    "email",
    "password",
    "phone",
    "secret",
    "token",
    "api_key",
}
RAW_TRACE_FIELD_NAMES = {
    "content",
    "full_content",
    "full_result",
    "original",
    "original_content",
    "offload_content",
    "prompt",
    "raw",
    "raw_content",
}


class AdminService:
    def __init__(
        self,
        *,
        auth: AuthService | None = None,
        permission_service: PermissionService | None = None,
        audit_service: AuditService | None = None,
        audit_events: Iterable[AuditEvent] | None = None,
        roles: list[RoleRecord] | None = None,
        resource_catalog: ResourceCatalogService | None = None,
        department_service: DepartmentService | None = None,
        scope_service: AdminScopeService | None = None,
    ):
        self.auth = auth or auth_service
        self.permission_service = permission_service or enterprise_permission_service
        self.audit_service = audit_service or AuditService()
        self.audit_events = audit_events
        self.resource_catalog = resource_catalog or resource_catalog_service
        self.department_service = department_service or default_department_service
        self.scope_service = scope_service or admin_scope_service
        self._roles: dict[str, RoleRecord] = {
            role.role_id: role
            for role in roles
            or [
                RoleRecord(role_id="admin", name="Admin", description="System administrator"),
                RoleRecord(
                    role_id="department_admin",
                    name="Department Admin",
                    description="Scoped department administrator",
                ),
                RoleRecord(role_id="user", name="User", description="Default user"),
            ]
        }

    def list_users(self, scope: AdminScope) -> list[UserProfile]:
        return self.scope_service.filter_users(scope, self.auth.list_users())

    def create_user(
        self,
        context: RequestContext,
        scope: AdminScope,
        *,
        user_id: str,
        username: str,
        password: str,
        department_id: str,
        department_name: str,
        roles: list[str],
    ) -> UserProfile:
        if scope.scope_type == "department":
            department = self._department_for_scope(scope)
            if department_id != department.department_id:
                self._deny_scoped_admin(
                    context,
                    "user",
                    user_id,
                    scope,
                    "user_outside_department_scope",
                    metadata_extra={
                        "requested_department_id": department_id,
                        "requested_department_name": department_name,
                    },
                )
            department_id = department.department_id
            department_name = department.name
            roles = self._sanitize_roles_for_scope(roles)
        try:
            user = self.auth.create_user(
                user_id=user_id,
                username=username,
                password=password,
                department_id=department_id,
                department_name=department_name,
                roles=roles,
            )
        except AuthError as exc:
            self._record_admin_operation(context, "create_user", "user", user_id, "failed", str(exc))
            raise AdminError(str(exc)) from exc
        self._record_admin_operation(context, "create_user", "user", user.user_id)
        return user

    def update_user(
        self,
        context: RequestContext,
        scope: AdminScope,
        user_id: str,
        **changes,
    ) -> UserProfile:
        current = self._find_user(user_id)
        if current is None:
            self._record_admin_operation(context, "update_user", "user", user_id, "failed", "user_not_found")
            raise AdminError("User not found")
        if scope.scope_type == "department":
            self._assert_user_in_scope(context, scope, current, operation="update_user")
            if changes.get("department_id") not in (None, scope.department_id):
                self._deny_scoped_admin(
                    context,
                    "user",
                    user_id,
                    scope,
                    "user_outside_department_scope",
                )
            requested_roles = changes.get("roles")
            if requested_roles is not None and self._has_privileged_roles(requested_roles):
                self._deny_scoped_admin(
                    context,
                    "user",
                    user_id,
                    scope,
                    "admin_role_not_allowed",
                )
        try:
            user = self.auth.update_user(user_id, **changes)
        except AuthError as exc:
            self._record_admin_operation(context, "update_user", "user", user_id, "failed", str(exc))
            raise AdminError(str(exc)) from exc
        if self._requires_token_invalidation(current, user):
            self.auth.invalidate_tokens_for_user(user.user_id)
        self._record_admin_operation(context, "update_user", "user", user.user_id)
        return user

    def disable_user(self, context: RequestContext, scope: AdminScope, user_id: str) -> UserProfile:
        current = self._find_user(user_id)
        if current is None:
            self._record_admin_operation(context, "disable_user", "user", user_id, "failed", "user_not_found")
            raise AdminError("User not found")
        if scope.scope_type == "department":
            self._assert_user_in_scope(context, scope, current, operation="disable_user")
        try:
            user = self.auth.disable_user(user_id)
        except AuthError as exc:
            self._record_admin_operation(context, "disable_user", "user", user_id, "failed", str(exc))
            raise AdminError(str(exc)) from exc
        self.auth.invalidate_tokens_for_user(user.user_id)
        self._record_admin_operation(context, "disable_user", "user", user.user_id)
        return user

    def _find_user(self, user_id: str) -> UserProfile | None:
        return next((user for user in self.auth.list_users() if user.user_id == user_id), None)

    def _department_for_scope(self, scope: AdminScope) -> DepartmentRecord:
        if scope.department_id is None:
            raise AdminScopeDenied("department_scope_required")
        department = self.department_service.get_department(scope.department_id)
        if department is None:
            raise AdminScopeDenied("department_not_found")
        return department

    def _sanitize_roles_for_scope(self, roles: list[str]) -> list[str]:
        sanitized = [
            role
            for role in dict.fromkeys(roles)
            if role not in PRIVILEGED_ADMIN_ROLES
        ]
        return sanitized or ["user"]

    def _has_privileged_roles(self, roles: list[str]) -> bool:
        return bool(PRIVILEGED_ADMIN_ROLES.intersection(roles))

    def _assert_user_in_scope(
        self,
        context: RequestContext,
        scope: AdminScope,
        user: UserProfile,
        *,
        operation: str,
    ) -> None:
        if user.department_id != scope.department_id or self._has_privileged_roles(user.roles):
            self._deny_scoped_admin(
                context,
                "user",
                user.user_id,
                scope,
                f"{operation}_outside_department_scope",
            )

    def _requires_token_invalidation(self, before: UserProfile, after: UserProfile) -> bool:
        return (
            before.roles != after.roles
            or before.department_id != after.department_id
            or before.is_active != after.is_active
        )

    def list_roles(self) -> list[RoleRecord]:
        return sorted(self._roles.values(), key=lambda role: role.role_id)

    def create_role(
        self,
        context: RequestContext,
        *,
        role_id: str,
        name: str,
        description: str = "",
    ) -> RoleRecord:
        if role_id in self._roles:
            self._record_admin_operation(context, "create_role", "role", role_id, "failed", "role_exists")
            raise AdminError("Role already exists")
        role = RoleRecord(role_id=role_id, name=name, description=description)
        self._roles[role_id] = role
        self._record_admin_operation(context, "create_role", "role", role_id)
        return role

    def update_role(
        self,
        context: RequestContext,
        role_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> RoleRecord:
        role = self._roles.get(role_id)
        if role is None:
            self._record_admin_operation(context, "update_role", "role", role_id, "failed", "role_not_found")
            raise AdminError("Role not found")
        updated = role.model_copy(
            update={
                key: value
                for key, value in {"name": name, "description": description}.items()
                if value is not None
            }
        )
        self._roles[role_id] = updated
        self._record_admin_operation(context, "update_role", "role", role_id)
        return updated

    def delete_role(self, context: RequestContext, role_id: str) -> bool:
        removed = self._roles.pop(role_id, None) is not None
        self._record_admin_operation(
            context,
            "delete_role",
            "role",
            role_id,
            "success" if removed else "failed",
            None if removed else "role_not_found",
        )
        if not removed:
            raise AdminError("Role not found")
        return True

    def _grant_validator(self) -> GrantValidator:
        return GrantValidator(
            resource_catalog=self.resource_catalog,
            permission_service=self.permission_service,
            auth=self.auth,
            roles_by_id=self._roles,
        )

    async def preview_grant(self, scope: AdminScope, request: GrantCreateRequest) -> GrantPreviewResult:
        return await self._grant_validator().preview(request, scope=scope)

    async def grant_access(
        self,
        context: RequestContext,
        scope: AdminScope,
        request: GrantCreateRequest,
    ) -> ResourceGrant:
        preview = await self.preview_grant(scope, request)
        if not preview.can_submit:
            failed_check = preview.failed_check or "grant_validation_failed"
            if failed_check == CHECK_SCOPE_ALLOWED:
                self._deny_scoped_admin(
                    context,
                    "grant",
                    f"{request.resource_type}:{request.resource_id}",
                    scope,
                    CHECK_SCOPE_ALLOWED,
                    metadata_extra={
                        "principal_type": request.principal_type.value,
                        "principal_id": request.principal_id,
                        "resource_type": request.resource_type,
                        "resource_id": request.resource_id,
                        "action": request.action,
                        "effect": request.effect.value,
                    },
                )
            self._record_admin_operation(
                context,
                "grant_access_rejected",
                "grant",
                f"{request.resource_type}:{request.resource_id}",
                "failed",
                failed_check,
                metadata_extra={
                    "failed_check": failed_check,
                    "principal_type": request.principal_type.value,
                    "principal_id": request.principal_id,
                    "resource_type": request.resource_type,
                    "resource_id": request.resource_id,
                    "action": request.action,
                    "effect": request.effect.value,
                },
            )
            raise AdminError(f"Grant validation failed: {failed_check}")

        stored = self.permission_service.grant_access(ResourceGrant(**request.model_dump()))
        self._record_admin_operation(context, "grant_access", "grant", stored.grant_id)
        return stored

    def revoke_grant(self, context: RequestContext, grant_id: str) -> bool:
        revoked = self.permission_service.revoke_grant(grant_id)
        self._record_admin_operation(
            context,
            "revoke_grant",
            "grant",
            grant_id,
            "success" if revoked else "failed",
            None if revoked else "grant_not_found",
        )
        return revoked

    def list_grants(
        self,
        scope: AdminScope,
        *,
        resource_type: str | None = None,
        resource_id: str | None = None,
        action: str | None = None,
        principal_type: str | None = None,
        principal_id: str | None = None,
    ) -> list[ResourceGrant]:
        grants = self.permission_service.repository.list_all_grants(
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            principal_type=principal_type,
            principal_id=principal_id,
        )
        return self.scope_service.filter_grants(scope, grants, self.auth)

    async def list_resources(self, scope: AdminScope) -> list:
        resources = await self.resource_catalog.list_resources()
        return self.scope_service.filter_resources(scope, resources)

    def list_departments(self) -> list[DepartmentRecord]:
        return self.department_service.list_departments()

    async def update_department_resource_scope(
        self,
        context: RequestContext,
        department_id: str,
        resources: list[DepartmentResourceRef],
    ) -> DepartmentRecord:
        normalized_resources = await self._validate_department_resources(resources)
        try:
            department = self.department_service.update_manageable_resources(
                department_id,
                normalized_resources,
            )
        except KeyError as exc:
            self._record_admin_operation(
                context,
                "update_department_resource_scope",
                "department",
                department_id,
                "failed",
                "department_not_found",
            )
            raise AdminError("Department not found") from exc
        except ValueError as exc:
            self._record_admin_operation(
                context,
                "update_department_resource_scope",
                "department",
                department_id,
                "failed",
                "system_department_not_configurable",
            )
            raise AdminError(str(exc)) from exc

        self._record_admin_operation(
            context,
            "update_department_resource_scope",
            "department",
            department_id,
            metadata_extra={
                "resource_count": len(department.manageable_resources),
                "resource_keys": [
                    f"{resource.resource_type}:{resource.resource_id}:{','.join(resource.actions)}"
                    for resource in department.manageable_resources
                ],
            },
        )
        return department

    async def _validate_department_resources(
        self,
        resources: list[DepartmentResourceRef],
    ) -> list[DepartmentResourceRef]:
        normalized: list[DepartmentResourceRef] = []
        seen: set[tuple[str, str, tuple[str, ...]]] = set()
        for resource in resources:
            catalog_resource = await self.resource_catalog.get_resource(
                resource_type=resource.resource_type,
                resource_id=resource.resource_id,
            )
            if catalog_resource is None:
                raise AdminError("resource_not_found")
            if any(action not in catalog_resource.actions_supported for action in resource.actions):
                raise AdminError("action_not_supported")
            actions = list(dict.fromkeys(resource.actions))
            key = (resource.resource_type, resource.resource_id, tuple(actions))
            if key in seen:
                continue
            seen.add(key)
            normalized.append(
                DepartmentResourceRef(
                    resource_type=resource.resource_type,
                    resource_id=resource.resource_id,
                    actions=actions,
                )
            )
        return normalized

    def query_audit_events(
        self,
        context: RequestContext,
        scope: AdminScope,
        *,
        trace_id: str | None = None,
        user_id: str | None = None,
        event_type: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int | None = None,
    ) -> list[AuditEvent]:
        events = self._load_audit_events(
            trace_id=trace_id,
            user_id=user_id,
            event_type=event_type,
            start_time=start_time,
            end_time=end_time,
            limit=None,
        )
        events = self.scope_service.filter_audit_events(scope, events, self.auth)
        if limit is not None:
            events = events[-limit:]
        self._record_admin_operation(context, "query_audit", "audit", trace_id or "*")
        return events

    def get_trace_timeline(
        self,
        context: RequestContext,
        scope: AdminScope,
        *,
        trace_id: str,
    ) -> dict[str, Any]:
        normalized_trace_id = trace_id.strip()
        if not normalized_trace_id:
            raise AdminError("Trace not found")

        matched_by, events = self._resolve_trace_events(normalized_trace_id)
        if not events:
            raise AdminError("Trace not found")

        visible_events = self.scope_service.filter_audit_events(scope, events, self.auth)
        if not visible_events:
            self._deny_scoped_admin(
                context,
                "trace",
                normalized_trace_id,
                scope,
                "trace_outside_scope",
            )

        timeline = [self._trace_timeline_item(event) for event in visible_events]

        recorded_sources = {
            item["source"]
            for item in timeline
            if item["source"] != "not_recorded"
        }
        for source in TRACE_EXPECTED_SOURCES:
            if source not in recorded_sources:
                timeline.append(self._not_recorded_timeline_item(source))

        first_event = visible_events[0]
        canonical_trace_id = first_event.trace_id or normalized_trace_id
        trace = {
            "trace_id": canonical_trace_id,
            "request_id": first_event.request_id,
            "user_id": first_event.user_id,
            "created_at": first_event.timestamp.isoformat(),
            "lookup": {
                "identifier": normalized_trace_id,
                "matched_by": matched_by,
            },
            "retention_days": TRACE_RETENTION_DAYS,
            "query_target_ms": TRACE_QUERY_TARGET_MS,
            "summary": self._trace_summary(
                visible_events,
                has_routing="routing" in recorded_sources,
                has_retrieval="retrieval" in recorded_sources,
            ),
            "timeline": timeline,
        }
        self._record_admin_operation(context, "query_trace", "trace", canonical_trace_id)
        return trace

    def compare_traces(
        self,
        context: RequestContext,
        scope: AdminScope,
        *,
        left: str,
        right: str,
    ) -> dict[str, Any]:
        left_trace = self.get_trace_timeline(context, scope, trace_id=left)
        right_trace = self.get_trace_timeline(context, scope, trace_id=right)
        left_summary = left_trace["summary"]
        right_summary = right_trace["summary"]
        rows = [
            self._comparison_row(
                "routing",
                "Routing",
                self._routing_comparison_value(left_summary),
                self._routing_comparison_value(right_summary),
            ),
            self._comparison_row(
                "retrieval_top1",
                "Retrieval top hit",
                left_summary.get("retrieval_top1"),
                right_summary.get("retrieval_top1"),
            ),
            self._comparison_row(
                "source_ref",
                "Source ref",
                left_summary.get("source_ref_status"),
                right_summary.get("source_ref_status"),
            ),
            self._comparison_row(
                "latency_ms",
                "Latency ms",
                left_summary.get("latency_ms"),
                right_summary.get("latency_ms"),
            ),
            self._comparison_row(
                "terminal_status",
                "Terminal status",
                left_summary.get("terminal_status"),
                right_summary.get("terminal_status"),
            ),
        ]
        comparison = {
            "left": self._comparison_side(left_trace),
            "right": self._comparison_side(right_trace),
            "rows": rows,
            "differences": [row["key"] for row in rows if row["different"]],
        }
        self._record_admin_operation(
            context,
            "compare_traces",
            "trace",
            f"{left_trace['trace_id']}..{right_trace['trace_id']}",
        )
        return comparison

    def _resolve_trace_events(self, identifier: str) -> tuple[str, list[AuditEvent]]:
        trace_events = sorted(
            self._load_audit_events(trace_id=identifier, limit=None),
            key=lambda event: event.timestamp,
        )
        if trace_events:
            return "trace_id", trace_events
        request_events = sorted(
            self._load_audit_events(request_id=identifier, limit=None),
            key=lambda event: event.timestamp,
        )
        if request_events:
            return "request_id", request_events
        return "trace_id", []

    def _comparison_side(self, trace: dict[str, Any]) -> dict[str, Any]:
        return {
            "trace_id": trace["trace_id"],
            "request_id": trace["request_id"],
            "lookup": trace["lookup"],
            "summary": trace["summary"],
        }

    def _comparison_row(self, key: str, label: str, left: Any, right: Any) -> dict[str, Any]:
        return {
            "key": key,
            "label": label,
            "left": left,
            "right": right,
            "different": left != right,
        }

    def _routing_comparison_value(self, summary: dict[str, Any]) -> str:
        actual = summary.get("actual_route") or "-"
        suggested = summary.get("suggested_route") or "-"
        return f"{actual}/{suggested}"

    def _trace_timeline_item(self, event: AuditEvent) -> dict[str, Any]:
        source = self._trace_event_source(event)
        if source == "routing":
            return self._routing_timeline_item(event)
        if source == "retrieval":
            return self._retrieval_timeline_item(event)
        return self._generic_timeline_item(event, source)

    def _trace_event_source(self, event: AuditEvent) -> str:
        event_type = event.event_type.lower()
        if event_type in {"routing_decision", "query_intent_decision"}:
            return "routing"
        if event_type == "rag_retrieval" or "retrieval" in event_type:
            return "retrieval"
        if event_type.startswith("tool_") or "tool" in event_type:
            return "tool"
        if event_type.startswith("database_"):
            return "database"
        if "memory" in event_type or "offload" in event_type:
            return "memory"
        if "sse" in event_type:
            return "sse"
        if event_type == "permission_checked" or "permission" in event_type:
            return "permission"
        return "audit"

    def _routing_timeline_item(self, event: AuditEvent) -> dict[str, Any]:
        metadata = event.metadata or {}
        actual_route = metadata.get("actual_route") or event.route
        suggested_route = metadata.get("suggested_route") or metadata.get("route") or "-"
        status = "failure" if event.decision == "failed" else "success"
        return {
            "timestamp": event.timestamp.isoformat(),
            "source": "routing",
            "stage": "intent_detection",
            "event_type": "error" if status == "failure" else "decision",
            "audit_event_type": event.event_type,
            "status": status,
            "message": f"Routing suggested {suggested_route} for {actual_route}",
            "data": self._sanitize_sensitive_fields(event.model_dump(mode="json")),
        }

    def _retrieval_timeline_item(self, event: AuditEvent) -> dict[str, Any]:
        metadata = event.metadata or {}
        result_doc_ids = list(metadata.get("result_doc_ids") or [])
        result_count = self._safe_int(metadata.get("result_count"), fallback=len(result_doc_ids))
        hits = [
            {"rank": index + 1, "doc_id": doc_id}
            for index, doc_id in enumerate(result_doc_ids)
        ]
        has_hits = result_count > 0 or bool(hits)
        data = self._sanitize_sensitive_fields(event.model_dump(mode="json"))
        source_refs = self._source_refs_from_metadata(metadata)
        data["hits"] = hits
        data["source_refs"] = source_refs
        data["source_ref_status"] = self._source_ref_status(metadata)
        return {
            "timestamp": event.timestamp.isoformat(),
            "source": "retrieval",
            "stage": "retrieval",
            "event_type": "hit" if has_hits else "miss",
            "audit_event_type": event.event_type,
            "status": "success" if has_hits else "failure",
            "message": f"Retrieval returned {result_count} hit(s)",
            "data": data,
        }

    def _generic_timeline_item(self, event: AuditEvent, source: str) -> dict[str, Any]:
        status = self._event_status(event)
        return {
            "timestamp": event.timestamp.isoformat(),
            "source": source,
            "stage": self._trace_stage(event, source),
            "event_type": event.event_type,
            "audit_event_type": event.event_type,
            "status": status,
            "message": self._trace_message(event, source, status),
            "data": self._trace_event_data(event, source),
        }

    def _event_status(self, event: AuditEvent) -> str:
        event_type = event.event_type.lower()
        decision = (event.decision or "").lower()
        if event_type == "request_failed" or decision in {"blocked", "denied", "failed", "rejected"}:
            return "failure"
        if decision in {"degraded", "partial"}:
            return "partial"
        return "success"

    def _trace_stage(self, event: AuditEvent, source: str) -> str:
        metadata = event.metadata or {}
        if source == "sse":
            return str(metadata.get("sse_event_type") or metadata.get("type") or "sse_event")
        if source == "memory":
            return str(metadata.get("mode") or "memory")
        if source == "tool":
            return str(metadata.get("tool_id") or metadata.get("tool_name") or event.event_type)
        if source == "database":
            return str(metadata.get("operation") or metadata.get("database_id") or event.event_type)
        if source == "permission":
            return str(metadata.get("resource_type") or "permission")
        return event.event_type

    def _trace_message(self, event: AuditEvent, source: str, status: str) -> str:
        metadata = event.metadata or {}
        if source == "tool":
            tool = metadata.get("tool_id") or metadata.get("tool_name") or "tool"
            return f"Tool {tool} {status}"
        if source == "database":
            target = metadata.get("database_id") or metadata.get("operation") or "database"
            return f"Database {target} {status}"
        if source == "memory":
            mode = metadata.get("mode") or metadata.get("offload_ref") or "memory/offload"
            return f"Memory/offload summary {mode} {status}"
        if source == "sse":
            event_type = metadata.get("sse_event_type") or metadata.get("type") or event.event_type
            return f"SSE event {event_type} {status}"
        if source == "permission":
            resource = metadata.get("resource_type") or "resource"
            action = metadata.get("action") or "access"
            return f"Permission {action} on {resource} {status}"
        return f"{event.event_type} {status}"

    def _trace_event_data(self, event: AuditEvent, source: str) -> dict[str, Any]:
        data = self._sanitize_sensitive_fields(event.model_dump(mode="json"))
        metadata = data.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            data["metadata"] = {}
            metadata = data["metadata"]
        original_metadata = event.metadata or {}
        if source == "database":
            self._sanitize_database_metadata(metadata, original_metadata)
        elif source == "sse":
            self._sanitize_sse_metadata(metadata, original_metadata)
        return data

    def _sanitize_database_metadata(self, metadata: dict[str, Any], original_metadata: dict[str, Any]) -> None:
        raw_sql = (
            original_metadata.get("sql")
            or original_metadata.get("sanitized_sql")
            or original_metadata.get("query")
        )
        if raw_sql and not metadata.get("sql_hash"):
            metadata["sql_hash"] = hashlib.sha256(str(raw_sql).encode("utf-8")).hexdigest()
        for key in ("sql", "sanitized_sql", "query", "rows", "result_rows", "results", "data"):
            metadata.pop(key, None)

    def _sanitize_sse_metadata(self, metadata: dict[str, Any], original_metadata: dict[str, Any]) -> None:
        raw_payload = None
        for key in ("data", "chunk", "delta", "payload", "content"):
            if key in original_metadata:
                raw_payload = original_metadata[key]
            metadata.pop(key, None)
        if raw_payload is not None:
            metadata["payload_size_bytes"] = len(str(raw_payload).encode("utf-8"))

    def _not_recorded_timeline_item(self, stage: str) -> dict[str, Any]:
        return {
            "timestamp": None,
            "source": "not_recorded",
            "stage": stage,
            "event_type": "not_recorded",
            "audit_event_type": "not_recorded",
            "status": "not_recorded",
            "message": f"{stage} audit event was not recorded",
            "data": {},
        }

    def _trace_summary(
        self,
        events: list[AuditEvent],
        *,
        has_routing: bool,
        has_retrieval: bool,
    ) -> dict[str, Any]:
        routing_event = self._latest_event(events, "routing_decision")
        retrieval_event = self._latest_event(events, "rag_retrieval")
        routing_metadata = routing_event.metadata if routing_event else {}
        retrieval_metadata = retrieval_event.metadata if retrieval_event else {}
        result_doc_ids = list(retrieval_metadata.get("result_doc_ids") or [])
        retrieval_hits = self._safe_int(retrieval_metadata.get("result_count"), fallback=len(result_doc_ids))
        terminal_event = self._latest_terminal_event(events)

        status = "success"
        failure_reason = None
        if terminal_event and terminal_event.event_type == "request_failed":
            status = "failure"
            failure_reason = terminal_event.reason or "request_failed"
        elif not has_routing:
            status = "partial"
            failure_reason = "routing_not_recorded"
        elif not has_retrieval:
            status = "partial"
            failure_reason = "retrieval_not_recorded"
        elif retrieval_hits <= 0:
            status = "failure"
            failure_reason = "retrieval_no_hit"

        diagnostics = routing_metadata.get("routing_diagnostics") or {}
        return {
            "routing_intent": diagnostics.get("intent") or routing_metadata.get("intent"),
            "actual_route": routing_metadata.get("actual_route") or (routing_event.route if routing_event else None),
            "suggested_route": routing_metadata.get("suggested_route") or routing_metadata.get("route"),
            "retrieval_hits": retrieval_hits,
            "retrieval_top1": result_doc_ids[0] if result_doc_ids else None,
            "source_ref_status": self._source_ref_status(retrieval_metadata),
            "latency_ms": terminal_event.latency_ms if terminal_event else None,
            "terminal_status": self._terminal_status(terminal_event),
            "status": status,
            "failure_reason": failure_reason,
        }

    def _latest_event(self, events: list[AuditEvent], event_type: str) -> AuditEvent | None:
        for event in reversed(events):
            if event.event_type == event_type:
                return event
        return None

    def _latest_terminal_event(self, events: list[AuditEvent]) -> AuditEvent | None:
        for event in reversed(events):
            if event.event_type in TRACE_TERMINAL_EVENT_TYPES:
                return event
        return None

    def _terminal_status(self, event: AuditEvent | None) -> str:
        if event is None:
            return "not_recorded"
        if event.event_type == "request_failed":
            return "failed"
        if event.event_type == "request_completed":
            return "completed"
        return event.decision or "unknown"

    def _source_refs_from_metadata(self, metadata: dict[str, Any]) -> list[dict[str, Any]]:
        source_refs = metadata.get("source_refs")
        if isinstance(source_refs, list):
            return [
                self._sanitize_sensitive_fields(source_ref)
                for source_ref in source_refs
                if isinstance(source_ref, dict)
            ]
        source_ref = metadata.get("source_ref")
        if isinstance(source_ref, dict):
            return [self._sanitize_sensitive_fields(source_ref)]
        return []

    def _source_ref_status(self, metadata: dict[str, Any]) -> str:
        for key in ("source_ref_resolvable", "all_source_ref_resolvable"):
            if key in metadata:
                return "resolvable" if bool(metadata.get(key)) else "unresolvable"
        if self._source_refs_from_metadata(metadata):
            return "recorded"
        return "not_recorded"

    def _safe_int(self, value: Any, *, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    def _sanitize_sensitive_fields(self, value: Any) -> Any:
        if isinstance(value, dict):
            sanitized = {}
            for key, item in value.items():
                key_lower = str(key).lower()
                if (
                    key_lower in SENSITIVE_FIELD_NAMES
                    or key_lower in RAW_TRACE_FIELD_NAMES
                    or any(name in key_lower for name in SENSITIVE_FIELD_NAMES)
                ):
                    sanitized[key] = "[REDACTED]"
                else:
                    sanitized[key] = self._sanitize_sensitive_fields(item)
            return sanitized
        if isinstance(value, list):
            return [self._sanitize_sensitive_fields(item) for item in value]
        return value

    def _load_audit_events(
        self,
        *,
        trace_id: str | None = None,
        request_id: str | None = None,
        user_id: str | None = None,
        event_type: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int | None = None,
    ) -> list[AuditEvent]:
        if self.audit_events is not None:
            events = [
                event
                for event in self.audit_events
                if (trace_id is None or event.trace_id == trace_id)
                and (request_id is None or event.request_id == request_id)
                and (user_id is None or event.user_id == user_id)
                and (event_type is None or event.event_type == event_type)
                and (start_time is None or event.timestamp >= start_time)
                and (end_time is None or event.timestamp <= end_time)
            ]
            return events[-limit:] if limit is not None else events

        for sink in self.audit_service.sinks:
            query = getattr(sink, "query", None)
            if callable(query):
                return list(
                    query(
                        trace_id=trace_id,
                        request_id=request_id,
                        user_id=user_id,
                        event_type=event_type,
                        start_time=start_time,
                        end_time=end_time,
                        limit=limit,
                    )
                )
        return []

    def _deny_scoped_admin(
        self,
        context: RequestContext,
        target_type: str,
        target_id: str,
        scope: AdminScope,
        denial_reason: str,
        metadata_extra: dict | None = None,
    ) -> None:
        metadata = {
            "scope_type": scope.scope_type,
            "department_id": scope.department_id,
            "denial_reason": denial_reason,
        }
        if metadata_extra:
            metadata.update(metadata_extra)
        self._record_admin_operation(
            context,
            "scoped_admin_rejected",
            target_type,
            target_id,
            "failed",
            denial_reason,
            metadata_extra=metadata,
        )
        raise AdminScopeDenied(denial_reason)

    def _record_admin_operation(
        self,
        context: RequestContext,
        operation: str,
        target_type: str,
        target_id: str,
        status: str = "success",
        reason: str | None = None,
        metadata_extra: dict | None = None,
    ) -> None:
        metadata = {
            "operation": operation,
            "target_type": target_type,
            "target_id": target_id,
            "status": status,
        }
        if metadata_extra:
            metadata.update(metadata_extra)
        self.audit_service.record(
            AuditEvent(
                event_type="admin_operation",
                route="admin",
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision="allowed" if status == "success" else "failed",
                reason=reason,
                metadata=metadata,
            )
        )


admin_service = AdminService()
