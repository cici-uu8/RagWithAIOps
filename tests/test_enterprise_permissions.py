import unittest

from app.enterprise.context import RequestContext
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permissions.models import (
    GrantEffect,
    PrincipalType,
    ResourceDescriptor,
    ResourceGrant,
)
from app.enterprise.permissions.registry import (
    DocumentAccessRegistry,
    ModelEndpointRegistry,
    ToolRegistry,
)
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService


class EnterprisePermissionServiceTests(unittest.TestCase):
    def setUp(self):
        self.repository = InMemoryGovernanceRepository()
        self.sink = InMemoryAuditSink()
        self.service = PermissionService(
            repository=self.repository,
            audit_service=AuditService(sinks=[self.sink]),
        )
        self.context = RequestContext(
            request_id="request-permission",
            trace_id="trace-permission",
            user_id="user_demo_dept1",
            username="demo_user_dept1",
            department_id="dept_1",
            department_name="Department 1",
            roles=["user"],
        )

    def test_default_denies_and_writes_permission_audit(self):
        decision = self.service.check(
            self.context,
            resource_type="document",
            resource_id="doc-private",
            action="read",
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.decision, "denied")
        self.assertEqual(decision.reason, "default_deny")
        audit = self.sink.events[-1]
        self.assertEqual(audit.event_type, "permission_checked")
        self.assertEqual(audit.decision, "denied")
        self.assertEqual(audit.reason, "default_deny")
        self.assertEqual(audit.trace_id, "trace-permission")
        self.assertEqual(audit.request_id, "request-permission")
        self.assertEqual(audit.metadata["resource_type"], "document")
        self.assertEqual(audit.metadata["resource_id"], "doc-private")

    def test_explicit_user_allow_grants_access(self):
        self.service.grant_access(
            ResourceGrant(
                resource_type="document",
                resource_id="doc-allowed",
                action="read",
                principal_type=PrincipalType.USER,
                principal_id="user_demo_dept1",
                effect=GrantEffect.ALLOW,
                reason="case-owner",
            )
        )

        decision = self.service.check(
            self.context,
            resource_type="document",
            resource_id="doc-allowed",
            action="read",
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "case-owner")
        self.assertEqual(self.sink.events[-1].decision, "allowed")

    def test_deny_overrides_role_allow(self):
        self.service.grant_access(
            ResourceGrant(
                resource_type="tool",
                resource_id="diagnose-tool",
                action="use",
                principal_type=PrincipalType.ROLE,
                principal_id="user",
                effect=GrantEffect.ALLOW,
                reason="role-user",
            )
        )
        self.service.grant_access(
            ResourceGrant(
                resource_type="tool",
                resource_id="diagnose-tool",
                action="use",
                principal_type=PrincipalType.USER,
                principal_id="user_demo_dept1",
                effect=GrantEffect.DENY,
                reason="incident-freeze",
            )
        )

        decision = self.service.check(
            self.context,
            resource_type="tool",
            resource_id="diagnose-tool",
            action="use",
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.decision, "denied")
        self.assertEqual(decision.reason, "incident-freeze")

    def test_cache_invalidation_after_revoke(self):
        grant = ResourceGrant(
            resource_type="model_endpoint",
            resource_id="qwen-max",
            action="use",
            principal_type=PrincipalType.USER,
            principal_id="user_demo_dept1",
            effect=GrantEffect.ALLOW,
            reason="model-access",
        )
        self.service.grant_access(grant)
        first = self.service.check(
            self.context,
            resource_type="model_endpoint",
            resource_id="qwen-max",
            action="use",
        )

        self.service.revoke_grant(grant.grant_id)
        second = self.service.check(
            self.context,
            resource_type="model_endpoint",
            resource_id="qwen-max",
            action="use",
        )

        self.assertTrue(first.allowed)
        self.assertFalse(second.allowed)
        self.assertEqual(second.reason, "default_deny")

    def test_explicit_cache_invalidation_after_external_grant_change(self):
        grant = ResourceGrant(
            resource_type="tool",
            resource_id="rag",
            action="use",
            principal_type=PrincipalType.USER,
            principal_id="user_demo_dept1",
            effect=GrantEffect.ALLOW,
        )
        self.service.grant_access(grant)
        allowed = self.service.check(
            self.context,
            resource_type="tool",
            resource_id="rag",
            action="use",
        )

        self.repository.revoke_grant(grant.grant_id)
        stale = self.service.check(
            self.context,
            resource_type="tool",
            resource_id="rag",
            action="use",
        )
        removed = self.service.invalidate_cache(resource_type="tool", resource_id="rag")
        after_invalidate = self.service.check(
            self.context,
            resource_type="tool",
            resource_id="rag",
            action="use",
        )

        self.assertTrue(allowed.allowed)
        self.assertTrue(stale.allowed)
        self.assertEqual(removed, 1)
        self.assertFalse(after_invalidate.allowed)

    def test_document_registry_filters_title_and_source_ref(self):
        registry = DocumentAccessRegistry(permission_service=self.service)
        registry.register(
            ResourceDescriptor(
                resource_type="document",
                resource_id="doc-visible",
                name="Visible SOP",
                metadata={"source_ref": "kb/default/doc-visible/chunk-1"},
            )
        )
        registry.register(
            ResourceDescriptor(
                resource_type="document",
                resource_id="doc-hidden",
                name="Hidden Root Cause",
                metadata={"source_ref": "kb/default/doc-hidden/chunk-9"},
            )
        )
        self.service.grant_access(
            ResourceGrant(
                resource_type="document",
                resource_id="doc-visible",
                action="read",
                principal_type=PrincipalType.USER,
                principal_id="user_demo_dept1",
                effect=GrantEffect.ALLOW,
            )
        )

        visible = registry.list_visible(self.context)

        self.assertEqual([item.resource_id for item in visible], ["doc-visible"])
        self.assertEqual([item.name for item in visible], ["Visible SOP"])
        self.assertNotIn(
            "doc-hidden",
            [item.metadata["source_ref"].split("/")[2] for item in visible],
        )

    def test_tool_and_model_registries_filter_visible_resources(self):
        tool_registry = ToolRegistry(permission_service=self.service)
        model_registry = ModelEndpointRegistry(permission_service=self.service)
        tool_registry.register(ResourceDescriptor(resource_type="tool", resource_id="rag", name="RAG"))
        tool_registry.register(ResourceDescriptor(resource_type="tool", resource_id="db", name="DB"))
        model_registry.register(
            ResourceDescriptor(
                resource_type="model_endpoint",
                resource_id="qwen-max",
                name="qwen-max",
            )
        )
        model_registry.register(
            ResourceDescriptor(
                resource_type="model_endpoint",
                resource_id="admin-model",
                name="admin-model",
            )
        )
        self.service.grant_access(
            ResourceGrant(
                resource_type="tool",
                resource_id="rag",
                action="use",
                principal_type=PrincipalType.ROLE,
                principal_id="user",
                effect=GrantEffect.ALLOW,
            )
        )
        self.service.grant_access(
            ResourceGrant(
                resource_type="model_endpoint",
                resource_id="qwen-max",
                action="use",
                principal_type=PrincipalType.DEPARTMENT,
                principal_id="dept_1",
                effect=GrantEffect.ALLOW,
            )
        )

        self.assertEqual(
            [item.resource_id for item in tool_registry.list_visible(self.context)],
            ["rag"],
        )
        self.assertEqual(
            [item.resource_id for item in model_registry.list_visible(self.context)],
            ["qwen-max"],
        )


if __name__ == "__main__":
    unittest.main()
