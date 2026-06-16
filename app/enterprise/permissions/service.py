"""PermissionService MVP for E3."""

from collections.abc import Iterable

from app.enterprise.context import RequestContext
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.observability.models import AuditEvent
from app.enterprise.permissions.models import (
    GrantEffect,
    PermissionDecision,
    PrincipalType,
    ResourceDescriptor,
    ResourceGrant,
)
from app.enterprise.permissions.repository import InMemoryGovernanceRepository


class PermissionService:
    def __init__(
        self,
        repository: InMemoryGovernanceRepository | None = None,
        audit_service: AuditService | None = None,
    ):
        self.repository = repository or InMemoryGovernanceRepository()
        self.audit_service = audit_service or AuditService()
        self._decision_cache: dict[tuple, PermissionDecision] = {}

    def check(
        self,
        context: RequestContext,
        *,
        resource_type: str,
        resource_id: str,
        action: str,
    ) -> PermissionDecision:
        cache_key = self._cache_key(context, resource_type, resource_id, action)
        cached = self._decision_cache.get(cache_key)
        if cached is not None:
            decision = cached.model_copy(update={"cache_hit": True})
            self._record_audit(context, decision)
            return decision

        decision = self._evaluate(context, resource_type, resource_id, action)
        self._decision_cache[cache_key] = decision
        self._record_audit(context, decision)
        return decision

    def filter_allowed(
        self,
        context: RequestContext,
        resources: Iterable[ResourceDescriptor],
        *,
        action: str,
    ) -> list[ResourceDescriptor]:
        allowed: list[ResourceDescriptor] = []
        for resource in resources:
            decision = self.check(
                context,
                resource_type=resource.resource_type,
                resource_id=resource.resource_id,
                action=action,
            )
            if decision.allowed:
                allowed.append(resource)
        return allowed

    def grant_access(self, grant: ResourceGrant) -> ResourceGrant:
        stored = self.repository.add_grant(grant)
        self.invalidate_cache(
            resource_type=grant.resource_type,
            resource_id=grant.resource_id,
        )
        return stored

    def revoke_grant(self, grant_id: str) -> bool:
        grant = self.repository.get_grant(grant_id)
        revoked = self.repository.revoke_grant(grant_id)
        if grant is not None:
            self.invalidate_cache(
                resource_type=grant.resource_type,
                resource_id=grant.resource_id,
            )
        elif revoked:
            self.invalidate_cache()
        return revoked

    def invalidate_cache(
        self,
        *,
        user_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> int:
        if user_id is None and resource_type is None and resource_id is None:
            removed = len(self._decision_cache)
            self._decision_cache.clear()
            return removed

        keys_to_delete = [
            key
            for key in self._decision_cache
            if (user_id is None or key[0] == user_id)
            and (resource_type is None or key[3] == resource_type)
            and (resource_id is None or key[4] == resource_id)
        ]
        for key in keys_to_delete:
            del self._decision_cache[key]
        return len(keys_to_delete)

    def _evaluate(
        self,
        context: RequestContext,
        resource_type: str,
        resource_id: str,
        action: str,
    ) -> PermissionDecision:
        grants = self.repository.list_grants(
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
        )
        principal_keys = self._principal_keys(context)
        matching = [
            grant
            for grant in grants
            if (grant.principal_type, grant.principal_id) in principal_keys
        ]

        deny = next((grant for grant in matching if grant.effect == GrantEffect.DENY), None)
        if deny is not None:
            return PermissionDecision(
                allowed=False,
                decision="denied",
                reason=deny.reason or "explicit_deny",
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                matched_grant_id=deny.grant_id,
            )

        allow = next((grant for grant in matching if grant.effect == GrantEffect.ALLOW), None)
        if allow is not None:
            return PermissionDecision(
                allowed=True,
                decision="allowed",
                reason=allow.reason or "explicit_allow",
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                matched_grant_id=allow.grant_id,
            )

        return PermissionDecision(
            allowed=False,
            decision="denied",
            reason="default_deny",
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
        )

    def _principal_keys(self, context: RequestContext) -> set[tuple[PrincipalType, str]]:
        keys: set[tuple[PrincipalType, str]] = {
            (PrincipalType.USER, context.user_id),
            (PrincipalType.DEPARTMENT, context.department_id),
            (PrincipalType.PUBLIC, "*"),
        }
        keys.update((PrincipalType.ROLE, role) for role in context.roles)
        return keys

    def _cache_key(
        self,
        context: RequestContext,
        resource_type: str,
        resource_id: str,
        action: str,
    ) -> tuple:
        return (
            context.user_id,
            tuple(sorted(context.roles)),
            context.department_id,
            resource_type,
            resource_id,
            action,
        )

    def _record_audit(self, context: RequestContext, decision: PermissionDecision) -> None:
        self.audit_service.record(
            AuditEvent(
                event_type="permission_checked",
                route="permission",
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision=decision.decision,
                reason=decision.reason,
                metadata={
                    "resource_type": decision.resource_type,
                    "resource_id": decision.resource_id,
                    "action": decision.action,
                    "matched_grant_id": decision.matched_grant_id,
                    "cache_hit": decision.cache_hit,
                },
            )
        )


permission_service = PermissionService()
