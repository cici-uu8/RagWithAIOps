import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.enterprise.admin.departments import department_service
from app.enterprise.admin.resources import ResourceCatalogService, resource_catalog_service
from app.enterprise.admin.service import admin_service
from app.enterprise.auth.service import auth_service
from app.enterprise.context import RequestContext
from app.enterprise.documents.service import DocumentAccessService
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permission_requests.service import permission_request_service
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.service import permission_service
from app.main import app
from app.models import DocumentRecord, DocumentStatus, ParserEngine
from app.services.knowledge_metadata_store import KnowledgeMetadataStore


class EnterprisePermissionRequestTests(unittest.TestCase):
    def setUp(self):
        auth_service.reset_users()
        auth_service.clear_blacklist()
        department_service.reset_departments()
        permission_service.repository.clear()
        permission_service.invalidate_cache()
        permission_request_service.reset()
        self.sink = InMemoryAuditSink()
        permission_request_service.audit_service = AuditService(sinks=[self.sink])
        permission_request_service.resource_catalog = resource_catalog_service
        admin_service.audit_service = AuditService(sinks=[self.sink])
        admin_service.audit_events = self.sink.events
        admin_service.permission_service = permission_service
        admin_service.resource_catalog = resource_catalog_service
        auth_service.create_user(
            user_id="user_dept1_manager",
            username="dept1_manager",
            password="Manager123!",
            department_id="dept_1",
            department_name="Department 1",
            roles=["department_admin"],
        )
        self.client = TestClient(app)

    def build_metadata_store(self, root: Path) -> KnowledgeMetadataStore:
        metadata_store = KnowledgeMetadataStore(root / "metadata.json")
        metadata_store.upsert_document(
            DocumentRecord(
                doc_id="doc-guide-a",
                kb_id="guide",
                file_name="工艺部资料A.md",
                file_ext="md",
                original_path=(root / "guide-a.md").as_posix(),
                artifact_dir=(root / "doc-guide-a" / "artifacts").as_posix(),
                parser_engine=ParserEngine.PLAIN_TEXT,
                status=DocumentStatus.INDEXED,
            )
        )
        metadata_store.upsert_document(
            DocumentRecord(
                doc_id="doc-guide-b",
                kb_id="guide",
                file_name="工艺部资料B.md",
                file_ext="md",
                original_path=(root / "guide-b.md").as_posix(),
                artifact_dir=(root / "doc-guide-b" / "artifacts").as_posix(),
                parser_engine=ParserEngine.PLAIN_TEXT,
                status=DocumentStatus.INDEXED,
            )
        )
        metadata_store.upsert_document(
            DocumentRecord(
                doc_id="doc-other",
                kb_id="other",
                file_name="其它资料.md",
                file_ext="md",
                original_path=(root / "other.md").as_posix(),
                artifact_dir=(root / "doc-other" / "artifacts").as_posix(),
                parser_engine=ParserEngine.PLAIN_TEXT,
                status=DocumentStatus.INDEXED,
            )
        )
        metadata_store.upsert_document(
            DocumentRecord(
                doc_id="doc-public",
                kb_id="public",
                file_name="公开资料.md",
                file_ext="md",
                original_path=(root / "public.md").as_posix(),
                artifact_dir=(root / "doc-public" / "artifacts").as_posix(),
                parser_engine=ParserEngine.PLAIN_TEXT,
                status=DocumentStatus.INDEXED,
                metadata={"visibility": "public"},
            )
        )
        return metadata_store

    def demo_user_context(self) -> RequestContext:
        return RequestContext(
            request_id="test-request",
            trace_id="test-trace",
            user_id="user_demo_dept1",
            username="demo_user_dept1",
            department_id="dept_1",
            department_name="Department 1",
            roles=["user"],
        )

    def login(self, username: str = "demo_user_dept1", password: str = "Demo123!") -> str:
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["access_token"]

    def test_user_can_create_permission_request_for_catalog_resource(self):
        token = self.login()

        response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "use",
                "reason": "need document search access",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()["data"]["permission_request"]
        self.assertEqual(payload["requester_user_id"], "user_demo_dept1")
        self.assertEqual(payload["requester_department_id"], "dept_1")
        self.assertEqual(payload["review_queue"], "department:dept_1")
        self.assertFalse(payload["requires_global_review"])

    def test_user_can_list_requestable_kb_tool_database_and_document_resources(self):
        token = self.login()
        with TemporaryDirectory() as temp_dir:
            metadata_store = self.build_metadata_store(Path(temp_dir))
            catalog = ResourceCatalogService(metadata_store=metadata_store)
            permission_request_service.resource_catalog = catalog
            admin_service.resource_catalog = catalog

            response = self.client.get(
                "/api/permission-requests/resources",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        resources = response.json()["data"]["resources"]
        by_key = {
            (resource["resource_type"], resource["resource_id"]): resource
            for resource in resources
        }
        self.assertIn(("knowledge_base", "guide"), by_key)
        self.assertEqual(by_key[("knowledge_base", "guide")]["actions_supported"], ["read"])
        self.assertEqual(by_key[("knowledge_base", "guide")]["metadata"]["document_count"], 2)
        self.assertEqual(by_key[("knowledge_base", "guide")]["metadata"]["display_name"], "guide")
        self.assertIn(("database", "sandbox_sales"), by_key)
        self.assertEqual(
            by_key[("database", "sandbox_sales")]["actions_supported"],
            ["read", "write", "admin"],
        )
        self.assertIn(("tool", "retrieve_knowledge"), by_key)
        self.assertIn(("document", "doc-guide-a"), by_key)
        self.assertNotIn(("knowledge_base", "public"), by_key)
        self.assertNotIn(("document", "doc-public"), by_key)
        self.assertFalse(by_key[("knowledge_base", "guide")]["already_granted"])

    def test_requestable_resource_tracks_grants_per_action(self):
        permission_service.grant_access(
            ResourceGrant(
                resource_type="database",
                resource_id="sandbox_sales",
                action="read",
                principal_type=PrincipalType.USER,
                principal_id="user_demo_dept1",
                effect=GrantEffect.ALLOW,
                reason="pre-approved database read",
            )
        )
        token = self.login()

        response = self.client.get(
            "/api/permission-requests/resources",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        database_resource = next(
            resource
            for resource in response.json()["data"]["resources"]
            if resource["resource_type"] == "database"
            and resource["resource_id"] == "sandbox_sales"
        )
        self.assertFalse(database_resource["already_granted"])
        by_action = {
            option["action"]: option
            for option in database_resource["action_options"]
        }
        self.assertTrue(by_action["read"]["already_granted"])
        self.assertFalse(by_action["write"]["already_granted"])
        self.assertFalse(by_action["admin"]["already_granted"])

    def test_kb_quick_permission_request_approval_grants_kb_read_for_documents(self):
        requester_token = self.login()
        with TemporaryDirectory() as temp_dir:
            metadata_store = self.build_metadata_store(Path(temp_dir))
            catalog = ResourceCatalogService(metadata_store=metadata_store)
            permission_request_service.resource_catalog = catalog
            admin_service.resource_catalog = catalog
            document_access = DocumentAccessService(
                metadata_store=metadata_store,
                permission_service=permission_service,
            )

            before = document_access.list_visible_documents(
                self.demo_user_context(),
                kb_id="guide",
            )
            self.assertEqual(before, [])

            create_response = self.client.post(
                "/api/permission-requests",
                headers={"Authorization": f"Bearer {requester_token}"},
                json={
                    "resource_type": "knowledge_base",
                    "resource_id": "guide",
                    "action": "read",
                    "reason": "need guide knowledge base",
                },
            )
            self.assertEqual(create_response.status_code, 200, create_response.text)
            request_payload = create_response.json()["data"]["permission_request"]
            self.assertEqual(request_payload["resource_type"], "knowledge_base")
            self.assertEqual(request_payload["resource_id"], "guide")

            admin_token = self.login(username="admin", password="Admin123!")
            approve_response = self.client.post(
                f"/api/admin/permission-requests/{request_payload['request_id']}/approve",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"reason": "approved guide access"},
            )
            self.assertEqual(approve_response.status_code, 200, approve_response.text)

            grants = permission_service.repository.list_all_grants(
                resource_type="knowledge_base",
                resource_id="guide",
                action="read",
                principal_type="user",
                principal_id="user_demo_dept1",
            )
            self.assertEqual(len(grants), 1)
            after = document_access.list_visible_documents(
                self.demo_user_context(),
                kb_id="guide",
            )
            self.assertEqual(
                [document.doc_id for document in after],
                ["doc-guide-a", "doc-guide-b"],
            )

    def test_public_documents_do_not_require_permission_request(self):
        with TemporaryDirectory() as temp_dir:
            metadata_store = self.build_metadata_store(Path(temp_dir))
            document_access = DocumentAccessService(
                metadata_store=metadata_store,
                permission_service=permission_service,
            )

            visible = document_access.list_visible_documents(
                self.demo_user_context(),
                kb_id="public",
            )

        self.assertEqual([document.doc_id for document in visible], ["doc-public"])

    def test_database_permission_request_approval_grants_database_read(self):
        token = self.login()

        create_response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "resource_type": "database",
                "resource_id": "sandbox_sales",
                "action": "read",
                "reason": "need database catalog visibility",
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        request_id = create_response.json()["data"]["permission_request"]["request_id"]

        admin_token = self.login(username="admin", password="Admin123!")
        approve_response = self.client.post(
            f"/api/admin/permission-requests/{request_id}/approve",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"reason": "approved database read"},
        )

        self.assertEqual(approve_response.status_code, 200, approve_response.text)
        grants = permission_service.repository.list_all_grants(
            resource_type="database",
            resource_id="sandbox_sales",
            action="read",
            principal_type="user",
            principal_id="user_demo_dept1",
        )
        self.assertEqual(len(grants), 1)

    def test_user_can_list_own_permission_requests(self):
        token = self.login()
        create_response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "use",
                "reason": "need document search access",
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)

        response = self.client.get(
            "/api/permission-requests/mine",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        requests = response.json()["data"]["permission_requests"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["requester_user_id"], "user_demo_dept1")
        self.assertEqual(requests[0]["resource_id"], "retrieve_knowledge")
        self.assertEqual(requests[0]["resource_display_name"], "retrieve_knowledge")
        self.assertEqual(requests[0]["action_display_name"], "使用")

    def test_user_cannot_request_unknown_resource(self):
        token = self.login()

        response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "resource_type": "tool",
                "resource_id": "missing_tool",
                "action": "use",
                "reason": "need access",
            },
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "permission_request_resource_not_found")

    def test_user_cannot_request_unsupported_action_for_resource(self):
        token = self.login()

        response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "read",
                "reason": "need access",
            },
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "permission_request_action_not_supported")

    def test_user_cannot_create_duplicate_pending_permission_request(self):
        token = self.login()
        request_body = {
            "resource_type": "tool",
            "resource_id": "retrieve_knowledge",
            "action": "use",
            "reason": "need access",
        }
        first_response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {token}"},
            json=request_body,
        )
        self.assertEqual(first_response.status_code, 200, first_response.text)

        response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {token}"},
            json=request_body,
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "permission_request_duplicate_pending")

    def test_user_cannot_request_permission_that_is_already_granted(self):
        token = self.login()
        permission_service.grant_access(
            ResourceGrant(
                resource_type="tool",
                resource_id="retrieve_knowledge",
                action="use",
                principal_type=PrincipalType.USER,
                principal_id="user_demo_dept1",
                effect=GrantEffect.ALLOW,
                reason="pre-approved access",
            )
        )

        response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "use",
                "reason": "need access",
            },
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "permission_already_granted")

    def test_mine_endpoint_does_not_return_other_users_requests(self):
        requester_token = self.login()
        create_response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {requester_token}"},
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "use",
                "reason": "need document search access",
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        other_token = self.login(username="dept1_manager", password="Manager123!")

        response = self.client.get(
            "/api/permission-requests/mine",
            headers={"Authorization": f"Bearer {other_token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"]["permission_requests"], [])

    def test_cross_scope_request_uses_requester_department_queue_with_global_review_flag(self):
        auth_service.create_user(
            user_id="user_dept2_manager",
            username="dept2_manager",
            password="Manager123!",
            department_id="dept_2",
            department_name="Department 2",
            roles=["department_admin"],
        )
        auth_service.create_user(
            user_id="user_demo_dept2",
            username="demo_user_dept2",
            password="Demo123!",
            department_id="dept_2",
            department_name="Department 2",
            roles=["user"],
        )
        token = self.login(username="demo_user_dept2", password="Demo123!")

        response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "use",
                "reason": "need access to dept 1 knowledge retrieval",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()["data"]["permission_request"]
        self.assertEqual(payload["requester_department_id"], "dept_2")
        self.assertEqual(payload["review_queue"], "department:dept_2")
        self.assertTrue(payload["requires_global_review"])
        self.assertEqual(payload["candidate_department_ids"], ["dept_1"])

    def test_create_permission_request_records_audit_event(self):
        token = self.login()

        response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "use",
                "reason": "need document search access",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        audit_events = [
            event
            for event in self.sink.events
            if event.event_type == "permission_request_created"
        ]
        self.assertEqual(len(audit_events), 1)
        event = audit_events[0]
        self.assertEqual(event.user_id, "user_demo_dept1")
        self.assertEqual(event.decision, "pending")
        self.assertEqual(event.metadata["resource_type"], "tool")
        self.assertEqual(event.metadata["resource_id"], "retrieve_knowledge")
        self.assertEqual(event.metadata["action"], "use")
        self.assertEqual(event.metadata["review_queue"], "department:dept_1")
        self.assertFalse(event.metadata["requires_global_review"])

    def test_requester_department_without_admin_falls_back_to_global_queue(self):
        auth_service.create_user(
            user_id="user_demo_dept2",
            username="demo_user_dept2",
            password="Demo123!",
            department_id="dept_2",
            department_name="Department 2",
            roles=["user"],
        )
        token = self.login(username="demo_user_dept2", password="Demo123!")

        response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "use",
                "reason": "need access to dept 1 knowledge retrieval",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()["data"]["permission_request"]
        self.assertEqual(payload["requester_department_id"], "dept_2")
        self.assertEqual(payload["review_queue"], "global")
        self.assertTrue(payload["requires_global_review"])
        self.assertEqual(payload["candidate_department_ids"], ["dept_1"])

    def test_global_admin_can_list_pending_permission_requests(self):
        requester_token = self.login()
        create_response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {requester_token}"},
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "use",
                "reason": "need document search access",
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        admin_token = self.login(username="admin", password="Admin123!")

        response = self.client.get(
            "/api/admin/permission-requests",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()["data"]
        self.assertEqual(payload["pending_count"], 1)
        self.assertEqual(payload["requires_global_review_count"], 0)
        requests = payload["permission_requests"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["requester_user_id"], "user_demo_dept1")
        self.assertEqual(requests[0]["status"], "pending")

    def test_department_admin_lists_own_department_permission_requests_only(self):
        dept1_token = self.login()
        dept1_response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {dept1_token}"},
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "use",
                "reason": "need document search access",
            },
        )
        self.assertEqual(dept1_response.status_code, 200, dept1_response.text)
        auth_service.create_user(
            user_id="user_dept2_manager",
            username="dept2_manager",
            password="Manager123!",
            department_id="dept_2",
            department_name="Department 2",
            roles=["department_admin"],
        )
        auth_service.create_user(
            user_id="user_demo_dept2",
            username="demo_user_dept2",
            password="Demo123!",
            department_id="dept_2",
            department_name="Department 2",
            roles=["user"],
        )
        dept2_token = self.login(username="demo_user_dept2", password="Demo123!")
        dept2_response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {dept2_token}"},
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "use",
                "reason": "need cross-scope access",
            },
        )
        self.assertEqual(dept2_response.status_code, 200, dept2_response.text)
        dept1_manager_token = self.login(username="dept1_manager", password="Manager123!")

        response = self.client.get(
            "/api/admin/permission-requests",
            headers={"Authorization": f"Bearer {dept1_manager_token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()["data"]
        self.assertEqual(payload["pending_count"], 1)
        self.assertEqual(payload["requires_global_review_count"], 0)
        requests = payload["permission_requests"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["requester_department_id"], "dept_1")

    def test_department_admin_sees_own_department_global_review_requests(self):
        auth_service.create_user(
            user_id="user_dept2_manager",
            username="dept2_manager",
            password="Manager123!",
            department_id="dept_2",
            department_name="Department 2",
            roles=["department_admin"],
        )
        auth_service.create_user(
            user_id="user_demo_dept2",
            username="demo_user_dept2",
            password="Demo123!",
            department_id="dept_2",
            department_name="Department 2",
            roles=["user"],
        )
        requester_token = self.login(username="demo_user_dept2", password="Demo123!")
        create_response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {requester_token}"},
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "use",
                "reason": "need cross-scope access",
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        dept2_manager_token = self.login(username="dept2_manager", password="Manager123!")

        response = self.client.get(
            "/api/admin/permission-requests",
            headers={"Authorization": f"Bearer {dept2_manager_token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()["data"]
        self.assertEqual(payload["pending_count"], 1)
        self.assertEqual(payload["requires_global_review_count"], 1)
        request = payload["permission_requests"][0]
        self.assertEqual(request["requester_department_id"], "dept_2")
        self.assertEqual(request["review_queue"], "department:dept_2")
        self.assertTrue(request["requires_global_review"])

    def test_global_admin_can_approve_permission_request_and_create_grant(self):
        requester_token = self.login()
        create_response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {requester_token}"},
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "use",
                "reason": "need document search access",
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        request_id = create_response.json()["data"]["permission_request"]["request_id"]
        admin_token = self.login(username="admin", password="Admin123!")

        response = self.client.post(
            f"/api/admin/permission-requests/{request_id}/approve",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"reason": "approved for project work"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        record = response.json()["data"]["permission_request"]
        self.assertEqual(record["status"], "approved")
        self.assertEqual(record["approver_user_id"], "user_admin")
        self.assertEqual(record["approver_reason"], "approved for project work")
        self.assertIsNotNone(record["grant_id"])
        grants = permission_service.repository.list_all_grants(
            resource_type="tool",
            resource_id="retrieve_knowledge",
            action="use",
            principal_type="user",
            principal_id="user_demo_dept1",
        )
        self.assertEqual(len(grants), 1)

    def test_department_admin_can_approve_in_scope_permission_request(self):
        requester_token = self.login()
        create_response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {requester_token}"},
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "use",
                "reason": "need document search access",
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        request_id = create_response.json()["data"]["permission_request"]["request_id"]
        manager_token = self.login(username="dept1_manager", password="Manager123!")

        response = self.client.post(
            f"/api/admin/permission-requests/{request_id}/approve",
            headers={"Authorization": f"Bearer {manager_token}"},
            json={"reason": "approved by department"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        record = response.json()["data"]["permission_request"]
        self.assertEqual(record["status"], "approved")
        self.assertEqual(record["approver_user_id"], "user_dept1_manager")
        grants = permission_service.repository.list_all_grants(
            resource_type="tool",
            resource_id="retrieve_knowledge",
            action="use",
            principal_type="user",
            principal_id="user_demo_dept1",
        )
        self.assertEqual(len(grants), 1)

    def test_department_admin_cannot_approve_request_requiring_global_review(self):
        auth_service.create_user(
            user_id="user_dept2_manager",
            username="dept2_manager",
            password="Manager123!",
            department_id="dept_2",
            department_name="Department 2",
            roles=["department_admin"],
        )
        auth_service.create_user(
            user_id="user_demo_dept2",
            username="demo_user_dept2",
            password="Demo123!",
            department_id="dept_2",
            department_name="Department 2",
            roles=["user"],
        )
        requester_token = self.login(username="demo_user_dept2", password="Demo123!")
        create_response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {requester_token}"},
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "use",
                "reason": "need cross-scope access",
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        request_id = create_response.json()["data"]["permission_request"]["request_id"]
        manager_token = self.login(username="dept2_manager", password="Manager123!")

        response = self.client.post(
            f"/api/admin/permission-requests/{request_id}/approve",
            headers={"Authorization": f"Bearer {manager_token}"},
            json={"reason": "approve anyway"},
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], "permission_request_requires_global_review")
        grants = permission_service.repository.list_all_grants(
            resource_type="tool",
            resource_id="retrieve_knowledge",
            action="use",
            principal_type="user",
            principal_id="user_demo_dept2",
        )
        self.assertEqual(grants, [])

    def test_department_admin_can_reject_own_department_permission_request(self):
        auth_service.create_user(
            user_id="user_dept2_manager",
            username="dept2_manager",
            password="Manager123!",
            department_id="dept_2",
            department_name="Department 2",
            roles=["department_admin"],
        )
        auth_service.create_user(
            user_id="user_demo_dept2",
            username="demo_user_dept2",
            password="Demo123!",
            department_id="dept_2",
            department_name="Department 2",
            roles=["user"],
        )
        requester_token = self.login(username="demo_user_dept2", password="Demo123!")
        create_response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {requester_token}"},
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "use",
                "reason": "need cross-scope access",
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        request_id = create_response.json()["data"]["permission_request"]["request_id"]
        manager_token = self.login(username="dept2_manager", password="Manager123!")

        response = self.client.post(
            f"/api/admin/permission-requests/{request_id}/reject",
            headers={"Authorization": f"Bearer {manager_token}"},
            json={"reason": "not justified"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        record = response.json()["data"]["permission_request"]
        self.assertEqual(record["status"], "rejected")
        self.assertEqual(record["approver_user_id"], "user_dept2_manager")
        self.assertEqual(record["approver_reason"], "not justified")
        self.assertIsNone(record["grant_id"])
        grants = permission_service.repository.list_all_grants(
            resource_type="tool",
            resource_id="retrieve_knowledge",
            action="use",
            principal_type="user",
            principal_id="user_demo_dept2",
        )
        self.assertEqual(grants, [])

    def test_non_admin_cannot_list_admin_permission_request_queue(self):
        token = self.login()

        response = self.client.get(
            "/api/admin/permission-requests",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], "Admin role required")

    def test_decided_permission_request_cannot_be_approved_again(self):
        requester_token = self.login()
        create_response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {requester_token}"},
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "use",
                "reason": "need document search access",
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        request_id = create_response.json()["data"]["permission_request"]["request_id"]
        admin_token = self.login(username="admin", password="Admin123!")
        first_response = self.client.post(
            f"/api/admin/permission-requests/{request_id}/approve",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"reason": "approved once"},
        )
        self.assertEqual(first_response.status_code, 200, first_response.text)

        response = self.client.post(
            f"/api/admin/permission-requests/{request_id}/approve",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"reason": "approve again"},
        )

        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["detail"], "permission_request_not_found")

    def test_global_admin_can_approve_request_requiring_global_review(self):
        auth_service.create_user(
            user_id="user_dept2_manager",
            username="dept2_manager",
            password="Manager123!",
            department_id="dept_2",
            department_name="Department 2",
            roles=["department_admin"],
        )
        auth_service.create_user(
            user_id="user_demo_dept2",
            username="demo_user_dept2",
            password="Demo123!",
            department_id="dept_2",
            department_name="Department 2",
            roles=["user"],
        )
        requester_token = self.login(username="demo_user_dept2", password="Demo123!")
        create_response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {requester_token}"},
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "use",
                "reason": "need cross-scope access",
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        request_id = create_response.json()["data"]["permission_request"]["request_id"]
        admin_token = self.login(username="admin", password="Admin123!")

        response = self.client.post(
            f"/api/admin/permission-requests/{request_id}/approve",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"reason": "global approved"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        record = response.json()["data"]["permission_request"]
        self.assertEqual(record["status"], "approved")
        self.assertTrue(record["requires_global_review"])
        grants = permission_service.repository.list_all_grants(
            resource_type="tool",
            resource_id="retrieve_knowledge",
            action="use",
            principal_type="user",
            principal_id="user_demo_dept2",
        )
        self.assertEqual(len(grants), 1)

    def test_permission_request_decisions_record_audit_metadata(self):
        requester_token = self.login()
        approved_response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {requester_token}"},
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "use",
                "reason": "need document search access",
            },
        )
        self.assertEqual(approved_response.status_code, 200, approved_response.text)
        approved_request_id = approved_response.json()["data"]["permission_request"]["request_id"]
        rejected_response = self.client.post(
            "/api/permission-requests",
            headers={"Authorization": f"Bearer {requester_token}"},
            json={
                "resource_type": "tool",
                "resource_id": "list_knowledge_documents",
                "action": "use",
                "reason": "need listing access",
            },
        )
        self.assertEqual(rejected_response.status_code, 200, rejected_response.text)
        rejected_request_id = rejected_response.json()["data"]["permission_request"]["request_id"]
        manager_token = self.login(username="dept1_manager", password="Manager123!")

        approve_response = self.client.post(
            f"/api/admin/permission-requests/{approved_request_id}/approve",
            headers={"Authorization": f"Bearer {manager_token}"},
            json={"reason": "approved for project work"},
        )
        self.assertEqual(approve_response.status_code, 200, approve_response.text)

        reject_response = self.client.post(
            f"/api/admin/permission-requests/{rejected_request_id}/reject",
            headers={"Authorization": f"Bearer {manager_token}"},
            json={"reason": "not needed"},
        )

        self.assertEqual(reject_response.status_code, 200, reject_response.text)
        approved_events = [
            event
            for event in self.sink.events
            if event.event_type == "permission_request_approved"
        ]
        self.assertEqual(len(approved_events), 1)
        approved_event = approved_events[0]
        self.assertEqual(approved_event.user_id, "user_dept1_manager")
        self.assertEqual(approved_event.decision, "approved")
        self.assertEqual(
            approved_event.metadata["permission_request_id"],
            approved_request_id,
        )
        self.assertEqual(approved_event.metadata["resource_type"], "tool")
        self.assertEqual(approved_event.metadata["resource_id"], "retrieve_knowledge")
        self.assertEqual(approved_event.metadata["review_queue"], "department:dept_1")
        self.assertEqual(approved_event.metadata["approver_user_id"], "user_dept1_manager")
        self.assertIsNotNone(approved_event.metadata["grant_id"])
        self.assertEqual(approved_event.reason, "approved for project work")

        rejected_events = [
            event
            for event in self.sink.events
            if event.event_type == "permission_request_rejected"
        ]
        self.assertEqual(len(rejected_events), 1)
        rejected_event = rejected_events[0]
        self.assertEqual(rejected_event.user_id, "user_dept1_manager")
        self.assertEqual(rejected_event.decision, "rejected")
        self.assertEqual(
            rejected_event.metadata["permission_request_id"],
            rejected_request_id,
        )
        self.assertEqual(rejected_event.metadata["resource_type"], "tool")
        self.assertEqual(rejected_event.metadata["resource_id"], "list_knowledge_documents")
        self.assertEqual(rejected_event.metadata["review_queue"], "department:dept_1")
        self.assertEqual(rejected_event.metadata["approver_user_id"], "user_dept1_manager")
        self.assertEqual(rejected_event.reason, "not needed")
