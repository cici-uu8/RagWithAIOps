import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.auth as auth_api
import app.enterprise.admin.routes as admin_routes
from app.enterprise.admin.departments import department_service
from app.enterprise.admin.service import AdminService
from app.enterprise.auth.service import auth_service
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.observability.models import AuditEvent
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService


def build_admin_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    app.include_router(admin_routes.router, prefix="/api")
    return app


class EnterpriseAdminStage4ScopeTests(unittest.TestCase):
    def setUp(self):
        auth_service.reset_users()
        auth_service.clear_blacklist()
        department_service.reset_departments()
        self.sink = InMemoryAuditSink()
        self.audit_service = AuditService(sinks=[self.sink])
        self.permission_service = PermissionService(
            repository=InMemoryGovernanceRepository(),
            audit_service=self.audit_service,
        )
        self.admin_service = AdminService(
            audit_service=self.audit_service,
            audit_events=self.sink.events,
            permission_service=self.permission_service,
        )
        self.original_admin_service = admin_routes.admin_service
        admin_routes.admin_service = self.admin_service
        self.client = TestClient(build_admin_app())

    def tearDown(self):
        admin_routes.admin_service = self.original_admin_service
        auth_service.reset_users()
        auth_service.clear_blacklist()
        department_service.reset_departments()

    def login(self, username: str = "admin", password: str = "Admin123!") -> str:
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["access_token"]

    def create_department_admin(self) -> None:
        auth_service.create_user(
            user_id="user_dept1_manager",
            username="dept1_manager",
            password="Manager123!",
            department_id="dept_1",
            department_name="Department 1",
            roles=["department_admin"],
        )

    def create_dept2_user(self) -> None:
        auth_service.create_user(
            user_id="user_dept2",
            username="dept2_user",
            password="Dept2123!",
            department_id="dept_2",
            department_name="Department 2",
            roles=["user"],
        )

    def test_global_admin_scope_can_see_all_departments(self):
        token = self.login()

        response = self.client.get(
            "/api/admin/scope",
            headers={"Authorization": f"Bearer {token}"},
        )
        roles_response = self.client.get(
            "/api/admin/roles",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(roles_response.status_code, 200, roles_response.text)
        scope = response.json()["data"]["scope"]
        self.assertEqual(scope["scope_type"], "global")
        self.assertIsNone(scope["department_id"])
        self.assertEqual(scope["manageable_resources"], [])
        self.assertIn(
            "department_admin",
            {role["role_id"] for role in roles_response.json()["data"]["roles"]},
        )

    def test_department_admin_scope_is_limited_to_own_department(self):
        self.create_department_admin()
        token = self.login("dept1_manager", "Manager123!")

        response = self.client.get(
            "/api/admin/scope",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        scope = response.json()["data"]["scope"]
        self.assertEqual(scope["scope_type"], "department")
        self.assertEqual(scope["department_id"], "dept_1")
        self.assertIn("tool", scope["manageable_resource_types"])
        self.assertIn("retrieve_knowledge", scope["manageable_resource_ids"])
        self.assertIn(
            {
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "actions": ["use"],
            },
            scope["manageable_resources"],
        )

    def test_plain_user_has_no_admin_scope(self):
        token = self.login("demo_user_dept1", "Demo123!")

        response = self.client.get(
            "/api/admin/scope",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 403)

    def test_global_admin_can_list_departments_with_resource_scope(self):
        token = self.login()

        response = self.client.get(
            "/api/admin/departments",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        departments = response.json()["data"]["departments"]
        departments_by_id = {department["department_id"]: department for department in departments}
        self.assertEqual(set(departments_by_id), {"dept_1", "dept_2", "system"})
        self.assertIn(
            {
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "actions": ["use"],
            },
            departments_by_id["dept_1"]["manageable_resources"],
        )
        self.assertEqual(departments_by_id["system"]["manageable_resources"], [])

    def test_global_admin_can_update_department_manageable_resources(self):
        token = self.login()

        response = self.client.patch(
            "/api/admin/departments/dept_1/resource-scope",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "resources": [
                    {
                        "resource_type": "tool",
                        "resource_id": "get_current_time",
                        "actions": ["use"],
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        department = response.json()["data"]["department"]
        self.assertEqual(department["department_id"], "dept_1")
        self.assertEqual(
            department["manageable_resources"],
            [
                {
                    "resource_type": "tool",
                    "resource_id": "get_current_time",
                    "actions": ["use"],
                }
            ],
        )

        self.create_department_admin()
        scope_token = self.login("dept1_manager", "Manager123!")
        scope_response = self.client.get(
            "/api/admin/scope",
            headers={"Authorization": f"Bearer {scope_token}"},
        )

        self.assertEqual(scope_response.status_code, 200, scope_response.text)
        scope = scope_response.json()["data"]["scope"]
        self.assertIn("get_current_time", scope["manageable_resource_ids"])
        self.assertNotIn("retrieve_knowledge", scope["manageable_resource_ids"])

    def test_department_admin_cannot_update_department_resource_scope(self):
        self.create_department_admin()
        token = self.login("dept1_manager", "Manager123!")

        response = self.client.patch(
            "/api/admin/departments/dept_1/resource-scope",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "resources": [
                    {
                        "resource_type": "tool",
                        "resource_id": "get_current_time",
                        "actions": ["use"],
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_department_scope_update_rejects_unknown_resource(self):
        token = self.login()

        response = self.client.patch(
            "/api/admin/departments/dept_1/resource-scope",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "resources": [
                    {
                        "resource_type": "tool",
                        "resource_id": "missing_tool",
                        "actions": ["use"],
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "resource_not_found")

    def test_department_scope_update_rejects_unsupported_action(self):
        token = self.login()

        response = self.client.patch(
            "/api/admin/departments/dept_1/resource-scope",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "resources": [
                    {
                        "resource_type": "tool",
                        "resource_id": "get_current_time",
                        "actions": ["write"],
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "action_not_supported")

    def test_department_admin_lists_only_own_department_users(self):
        self.create_department_admin()
        self.create_dept2_user()
        token = self.login("dept1_manager", "Manager123!")

        response = self.client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        user_ids = {user["user_id"] for user in response.json()["data"]["users"]}
        self.assertIn("user_demo_dept1", user_ids)
        self.assertIn("user_dept1_manager", user_ids)
        self.assertNotIn("user_dept2", user_ids)
        self.assertNotIn("user_admin", user_ids)

    def test_department_admin_resources_view_is_scope_filtered(self):
        self.create_department_admin()
        token = self.login("dept1_manager", "Manager123!")

        response = self.client.get(
            "/api/admin/resources",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        resource_keys = {
            (resource["resource_type"], resource["resource_id"])
            for resource in response.json()["data"]["resources"]
        }
        self.assertIn(("tool", "retrieve_knowledge"), resource_keys)
        self.assertIn(("database_table", "sandbox_sales.factory_access_events"), resource_keys)
        self.assertNotIn(("tool", "get_current_time"), resource_keys)
        self.assertNotIn(("database_table", "sandbox_sales.building_access_events"), resource_keys)

    def test_department_admin_grants_view_is_scope_filtered(self):
        self.create_department_admin()
        self.create_dept2_user()
        self.permission_service.grant_access(
            ResourceGrant(
                resource_type="tool",
                resource_id="retrieve_knowledge",
                action="use",
                principal_type=PrincipalType.USER,
                principal_id="user_demo_dept1",
                effect=GrantEffect.ALLOW,
            )
        )
        self.permission_service.grant_access(
            ResourceGrant(
                resource_type="tool",
                resource_id="retrieve_knowledge",
                action="use",
                principal_type=PrincipalType.DEPARTMENT,
                principal_id="dept_1",
                effect=GrantEffect.ALLOW,
            )
        )
        self.permission_service.grant_access(
            ResourceGrant(
                resource_type="tool",
                resource_id="get_current_time",
                action="use",
                principal_type=PrincipalType.USER,
                principal_id="user_dept2",
                effect=GrantEffect.ALLOW,
            )
        )
        self.permission_service.grant_access(
            ResourceGrant(
                resource_type="tool",
                resource_id="retrieve_knowledge",
                action="use",
                principal_type=PrincipalType.ROLE,
                principal_id="admin",
                effect=GrantEffect.ALLOW,
            )
        )
        token = self.login("dept1_manager", "Manager123!")

        response = self.client.get(
            "/api/admin/grants",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        visible_principals = {
            (grant["principal_type"], grant["principal_id"])
            for grant in response.json()["data"]["grants"]
        }
        self.assertEqual(
            visible_principals,
            {("user", "user_demo_dept1"), ("department", "dept_1")},
        )

    def test_department_admin_audit_query_is_department_scoped(self):
        self.create_department_admin()
        self.create_dept2_user()
        self.sink.emit(
            AuditEvent(
                event_type="request_completed",
                route="chat",
                trace_id="trace-dept1",
                request_id="request-dept1",
                user_id="user_demo_dept1",
                decision="allowed",
            )
        )
        self.sink.emit(
            AuditEvent(
                event_type="request_completed",
                route="chat",
                trace_id="trace-dept2",
                request_id="request-dept2",
                user_id="user_dept2",
                decision="allowed",
            )
        )
        self.sink.emit(
            AuditEvent(
                event_type="admin_operation",
                route="admin",
                trace_id="trace-manager",
                request_id="request-manager",
                user_id="user_dept1_manager",
                decision="allowed",
                metadata={"operation": "list_users"},
            )
        )
        token = self.login("dept1_manager", "Manager123!")

        response = self.client.get(
            "/api/admin/audit",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 20},
        )

        self.assertEqual(response.status_code, 200, response.text)
        trace_ids = {event["trace_id"] for event in response.json()["data"]["events"]}
        self.assertIn("trace-dept1", trace_ids)
        self.assertIn("trace-manager", trace_ids)
        self.assertNotIn("trace-dept2", trace_ids)

    def test_department_admin_cannot_create_user_outside_own_department(self):
        self.create_department_admin()
        token = self.login("dept1_manager", "Manager123!")

        response = self.client.post(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "user_id": "user_cross_department",
                "username": "cross_department_user",
                "password": "Cross123!",
                "department_id": "dept_2",
                "department_name": "Department 2",
                "roles": ["user"],
            },
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("user_outside_department_scope", response.json()["detail"])
        self.assertFalse(
            any(user.user_id == "user_cross_department" for user in auth_service.list_users())
        )
        rejection_events = [
            event
            for event in self.sink.events
            if event.event_type == "admin_operation"
            and event.metadata.get("operation") == "scoped_admin_rejected"
        ]
        self.assertTrue(rejection_events)
        self.assertEqual(
            rejection_events[-1].metadata["denial_reason"],
            "user_outside_department_scope",
        )

    def test_department_admin_cannot_assign_admin_roles(self):
        self.create_department_admin()
        token = self.login("dept1_manager", "Manager123!")

        response = self.client.post(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "user_id": "user_non_admin",
                "username": "non_admin_user",
                "password": "User123!",
                "department_id": "dept_1",
                "department_name": "Department 1",
                "roles": ["user", "admin", "department_admin", "analyst"],
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        roles = response.json()["data"]["user"]["roles"]
        self.assertIn("user", roles)
        self.assertIn("analyst", roles)
        self.assertNotIn("admin", roles)
        self.assertNotIn("department_admin", roles)

    def test_department_admin_can_disable_own_department_user_but_not_other_department_user(self):
        self.create_department_admin()
        self.create_dept2_user()
        token = self.login("dept1_manager", "Manager123!")

        own_response = self.client.post(
            "/api/admin/users/user_demo_dept1/disable",
            headers={"Authorization": f"Bearer {token}"},
        )
        cross_department_response = self.client.post(
            "/api/admin/users/user_dept2/disable",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(own_response.status_code, 200, own_response.text)
        self.assertFalse(own_response.json()["data"]["user"]["is_active"])
        self.assertEqual(cross_department_response.status_code, 403)

    def test_department_admin_can_update_own_department_user_but_not_other_department_user(self):
        self.create_department_admin()
        self.create_dept2_user()
        token = self.login("dept1_manager", "Manager123!")

        own_response = self.client.patch(
            "/api/admin/users/user_demo_dept1",
            headers={"Authorization": f"Bearer {token}"},
            json={"roles": ["user", "analyst"]},
        )
        cross_department_response = self.client.patch(
            "/api/admin/users/user_dept2",
            headers={"Authorization": f"Bearer {token}"},
            json={"department_name": "Department 2 Updated"},
        )

        self.assertEqual(own_response.status_code, 200, own_response.text)
        self.assertEqual(own_response.json()["data"]["user"]["roles"], ["user", "analyst"])
        self.assertEqual(cross_department_response.status_code, 403)

    def test_admin_role_change_invalidates_existing_tokens(self):
        admin_token = self.login()
        user_token = self.login("demo_user_dept1", "Demo123!")

        update_response = self.client.patch(
            "/api/admin/users/user_demo_dept1",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "roles": ["user", "analyst"],
            },
        )

        self.assertEqual(update_response.status_code, 200, update_response.text)
        stale_response = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        refreshed_token = self.login("demo_user_dept1", "Demo123!")
        fresh_response = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {refreshed_token}"},
        )

        self.assertEqual(stale_response.status_code, 401)
        self.assertEqual(fresh_response.status_code, 200, fresh_response.text)
        self.assertEqual(fresh_response.json()["data"]["user"]["roles"], ["user", "analyst"])

    def test_grant_validator_runs_scope_allowed_check(self):
        self.create_department_admin()
        token = self.login("dept1_manager", "Manager123!")

        response = self.client.post(
            "/api/admin/grant-preview",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "resource_type": "tool",
                "resource_id": "get_current_time",
                "action": "use",
                "principal_type": "user",
                "principal_id": "user_demo_dept1",
                "effect": "allow",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        checks = {check["check"]: check for check in response.json()["data"]["checks"]}
        self.assertEqual(checks["scope_allowed"]["status"], "failed")

    def test_department_admin_cannot_grant_resource_outside_scope(self):
        self.create_department_admin()
        token = self.login("dept1_manager", "Manager123!")

        response = self.client.post(
            "/api/admin/grants",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "resource_type": "tool",
                "resource_id": "get_current_time",
                "action": "use",
                "principal_type": "user",
                "principal_id": "user_demo_dept1",
                "effect": "allow",
                "reason": "outside scope",
            },
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("scope_allowed", response.json()["detail"])

    def test_department_admin_can_grant_resource_inside_scope_to_own_department_user(self):
        self.create_department_admin()
        token = self.login("dept1_manager", "Manager123!")

        response = self.client.post(
            "/api/admin/grants",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "use",
                "principal_type": "user",
                "principal_id": "user_demo_dept1",
                "effect": "allow",
                "reason": "in scope",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        grant = response.json()["data"]["grant"]
        self.assertEqual(grant["resource_id"], "retrieve_knowledge")
        self.assertEqual(grant["principal_id"], "user_demo_dept1")

    def test_department_admin_can_grant_database_operation_only_inside_scope(self):
        from app.enterprise.database.permissions import database_operation_resource_id

        admin_token = self.login()
        operation_id = database_operation_resource_id("sandbox_sales", "delete")
        scope_response = self.client.patch(
            "/api/admin/departments/dept_1/resource-scope",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "resources": [
                    {
                        "resource_type": "database_operation",
                        "resource_id": operation_id,
                        "actions": ["execute"],
                    }
                ]
            },
        )
        self.assertEqual(scope_response.status_code, 200, scope_response.text)

        self.create_department_admin()
        dept_token = self.login("dept1_manager", "Manager123!")
        allowed_response = self.client.post(
            "/api/admin/grants",
            headers={"Authorization": f"Bearer {dept_token}"},
            json={
                "resource_type": "database_operation",
                "resource_id": operation_id,
                "action": "execute",
                "principal_type": "user",
                "principal_id": "user_demo_dept1",
                "effect": "allow",
                "reason": "inside operation scope",
            },
        )
        outside_response = self.client.post(
            "/api/admin/grants",
            headers={"Authorization": f"Bearer {dept_token}"},
            json={
                "resource_type": "database_operation",
                "resource_id": database_operation_resource_id("sandbox_sales", "ddl"),
                "action": "execute",
                "principal_type": "user",
                "principal_id": "user_demo_dept1",
                "effect": "allow",
                "reason": "outside operation scope",
            },
        )

        self.assertEqual(allowed_response.status_code, 200, allowed_response.text)
        self.assertEqual(
            allowed_response.json()["data"]["grant"]["resource_id"],
            operation_id,
        )
        self.assertEqual(outside_response.status_code, 403, outside_response.text)
        self.assertIn("scope_allowed", outside_response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
