import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.auth as auth_api
import app.enterprise.admin.routes as admin_routes
from app.enterprise.admin.service import AdminService
from app.enterprise.auth.service import auth_service
from app.enterprise.observability.audit_service import (
    AuditService,
    InMemoryAuditSink,
    SQLiteAuditSink,
)
from app.enterprise.observability.models import AuditEvent
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService


def build_admin_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    app.include_router(admin_routes.router, prefix="/api")
    return app


class EnterpriseAdminE8Tests(unittest.TestCase):
    def setUp(self):
        auth_service.reset_users()
        auth_service.clear_blacklist()
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

    def login(self, username: str = "admin", password: str = "Admin123!") -> str:
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["access_token"]

    def test_non_admin_cannot_access_admin_api(self):
        token = self.login("demo_user_dept1", "Demo123!")

        response = self.client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_can_manage_users_and_operations_are_audited(self):
        token = self.login()
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Trace-Id": "trace-admin-users",
        }

        create_response = self.client.post(
            "/api/admin/users",
            headers=headers,
            json={
                "user_id": "user_ops",
                "username": "ops_user",
                "password": "Ops123!",
                "department_id": "ops",
                "department_name": "Operations",
                "roles": ["user"],
            },
        )
        update_response = self.client.patch(
            "/api/admin/users/user_ops",
            headers=headers,
            json={
                "department_name": "Operations Updated",
                "roles": ["user", "analyst"],
            },
        )
        disable_response = self.client.post(
            "/api/admin/users/user_ops/disable",
            headers=headers,
        )
        list_response = self.client.get("/api/admin/users", headers=headers)
        disabled_login = self.client.post(
            "/api/auth/login",
            json={"username": "ops_user", "password": "Ops123!"},
        )

        self.assertEqual(create_response.status_code, 200, create_response.text)
        self.assertEqual(update_response.status_code, 200, update_response.text)
        self.assertEqual(disable_response.status_code, 200, disable_response.text)
        self.assertEqual(list_response.status_code, 200, list_response.text)
        self.assertEqual(disabled_login.status_code, 401)
        self.assertEqual(create_response.json()["data"]["user"]["user_id"], "user_ops")
        self.assertEqual(update_response.json()["data"]["user"]["roles"], ["user", "analyst"])
        self.assertFalse(disable_response.json()["data"]["user"]["is_active"])
        self.assertIn(
            "user_ops",
            {user["user_id"] for user in list_response.json()["data"]["users"]},
        )

        operations = [
            event.metadata["operation"]
            for event in self.sink.events
            if event.event_type == "admin_operation"
        ]
        self.assertIn("create_user", operations)
        self.assertIn("update_user", operations)
        self.assertIn("disable_user", operations)

    def test_admin_can_manage_roles(self):
        token = self.login()
        headers = {"Authorization": f"Bearer {token}"}

        create_response = self.client.post(
            "/api/admin/roles",
            headers=headers,
            json={
                "role_id": "analyst",
                "name": "Analyst",
                "description": "Can inspect governed resources",
            },
        )
        update_response = self.client.patch(
            "/api/admin/roles/analyst",
            headers=headers,
            json={"description": "Updated description"},
        )
        list_response = self.client.get("/api/admin/roles", headers=headers)
        delete_response = self.client.delete("/api/admin/roles/analyst", headers=headers)
        after_delete = self.client.get("/api/admin/roles", headers=headers)

        self.assertEqual(create_response.status_code, 200, create_response.text)
        self.assertEqual(update_response.status_code, 200, update_response.text)
        self.assertEqual(list_response.status_code, 200, list_response.text)
        self.assertEqual(delete_response.status_code, 200, delete_response.text)
        self.assertNotIn(
            "analyst",
            {role["role_id"] for role in after_delete.json()["data"]["roles"]},
        )
        self.assertEqual(
            update_response.json()["data"]["role"]["description"],
            "Updated description",
        )

    def test_admin_can_grant_revoke_and_list_permissions(self):
        token = self.login()
        headers = {"Authorization": f"Bearer {token}"}

        grant_response = self.client.post(
            "/api/admin/grants",
            headers=headers,
            json={
                "resource_type": "tool",
                "resource_id": "retrieve_knowledge",
                "action": "use",
                "principal_type": "role",
                "principal_id": "admin",
                "effect": "allow",
                "reason": "E8 test grant",
            },
        )
        grant_id = grant_response.json()["data"]["grant"]["grant_id"]
        list_response = self.client.get(
            "/api/admin/grants?resource_type=tool",
            headers=headers,
        )
        revoke_response = self.client.delete(
            f"/api/admin/grants/{grant_id}",
            headers=headers,
        )
        after_revoke = self.client.get(
            "/api/admin/grants?resource_type=tool",
            headers=headers,
        )

        self.assertEqual(grant_response.status_code, 200, grant_response.text)
        self.assertEqual(list_response.status_code, 200, list_response.text)
        self.assertEqual(revoke_response.status_code, 200, revoke_response.text)
        self.assertEqual(
            [grant["grant_id"] for grant in list_response.json()["data"]["grants"]],
            [grant_id],
        )
        self.assertTrue(revoke_response.json()["data"]["revoked"])
        self.assertEqual(after_revoke.json()["data"]["grants"], [])

    def test_admin_can_query_audit_events_by_trace_user_and_type(self):
        token = self.login()
        self.sink.emit(
            AuditEvent(
                event_type="request_completed",
                route="chat",
                trace_id="trace-audit-query",
                request_id="request-audit-query",
                user_id="user_demo_dept1",
                decision="allowed",
            )
        )
        self.sink.emit(
            AuditEvent(
                event_type="database_query",
                route="database_demo",
                trace_id="trace-other",
                request_id="request-other",
                user_id="user_demo_dept1",
                decision="allowed",
            )
        )

        response = self.client.get(
            "/api/admin/audit",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "trace_id": "trace-audit-query",
                "user_id": "user_demo_dept1",
                "event_type": "request_completed",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        events = response.json()["data"]["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["trace_id"], "trace-audit-query")
        self.assertEqual(events[0]["event_type"], "request_completed")

    def test_admin_audit_query_honors_limit_parameter(self):
        token = self.login()
        for index in range(3):
            self.sink.emit(
                AuditEvent(
                    event_type="admin_operation",
                    route="admin",
                    trace_id="trace-audit-limit",
                    request_id=f"request-audit-limit-{index}",
                    user_id="user_admin",
                    decision="allowed",
                    metadata={"operation": f"operation_{index}"},
                )
            )

        response = self.client.get(
            "/api/admin/audit",
            headers={"Authorization": f"Bearer {token}"},
            params={"event_type": "admin_operation", "limit": 2},
        )

        self.assertEqual(response.status_code, 200, response.text)
        events = response.json()["data"]["events"]
        self.assertEqual(len(events), 2)
        self.assertEqual(
            [event["request_id"] for event in events],
            ["request-audit-limit-1", "request-audit-limit-2"],
        )

    def test_admin_can_query_persisted_sqlite_audit_events(self):
        token = self.login()
        with TemporaryDirectory() as temp_dir:
            audit_service = AuditService(
                sinks=[SQLiteAuditSink(Path(temp_dir) / "enterprise_audit.sqlite")]
            )
            audit_service.record(
                AuditEvent(
                    event_type="request_completed",
                    route="chat",
                    trace_id="trace-sqlite-audit",
                    request_id="request-sqlite-audit",
                    user_id="user_demo_dept1",
                    decision="allowed",
                )
            )
            audit_service.record(
                AuditEvent(
                    event_type="request_failed",
                    route="chat",
                    trace_id="trace-sqlite-other",
                    request_id="request-sqlite-other",
                    user_id="user_demo_dept1",
                    decision="failed",
                )
            )
            persisted_admin_service = AdminService(
                audit_service=audit_service,
                permission_service=self.permission_service,
            )

            admin_routes.admin_service = persisted_admin_service
            response = self.client.get(
                "/api/admin/audit",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "trace_id": "trace-sqlite-audit",
                    "event_type": "request_completed",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        events = response.json()["data"]["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["trace_id"], "trace-sqlite-audit")
        self.assertEqual(events[0]["event_type"], "request_completed")

    def test_admin_can_query_routing_and_retrieval_trace_timeline(self):
        token = self.login()
        self.sink.emit(
            AuditEvent(
                event_type="routing_decision",
                route="chat",
                trace_id="trace-p11",
                request_id="request-p11",
                user_id="user_demo_dept1",
                decision="shadow",
                reason="knowledge question",
                metadata={
                    "actual_route": "chat",
                    "suggested_route": "rag",
                    "routing_diagnostics": {"intent": "knowledge_retrieval"},
                    "token": "secret-token",
                },
            )
        )
        self.sink.emit(
            AuditEvent(
                event_type="rag_retrieval",
                route="rag",
                trace_id="trace-p11",
                request_id="request-p11",
                user_id="user_demo_dept1",
                decision="allowed",
                metadata={
                    "result_doc_ids": ["doc-cpu", "doc-runbook"],
                    "result_count": 2,
                    "allowed_doc_ids": ["doc-cpu", "doc-runbook"],
                },
            )
        )

        response = self.client.get(
            "/api/admin/traces/trace-p11",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        trace = response.json()["data"]["trace"]
        self.assertEqual(trace["trace_id"], "trace-p11")
        self.assertEqual(trace["request_id"], "request-p11")
        self.assertEqual(trace["user_id"], "user_demo_dept1")
        self.assertEqual(trace["retention_days"], 30)
        self.assertEqual(trace["query_target_ms"], 2000)
        self.assertEqual(trace["summary"]["routing_intent"], "knowledge_retrieval")
        self.assertEqual(trace["summary"]["actual_route"], "chat")
        self.assertEqual(trace["summary"]["suggested_route"], "rag")
        self.assertEqual(trace["summary"]["retrieval_hits"], 2)
        self.assertEqual(trace["summary"]["retrieval_top1"], "doc-cpu")
        self.assertEqual(trace["summary"]["status"], "success")
        self.assertEqual([item["source"] for item in trace["timeline"][:2]], ["routing", "retrieval"])
        retrieval = trace["timeline"][1]
        self.assertEqual(retrieval["event_type"], "hit")
        self.assertEqual(retrieval["data"]["hits"][0], {"rank": 1, "doc_id": "doc-cpu"})
        self.assertEqual(trace["timeline"][0]["data"]["metadata"]["token"], "[REDACTED]")

    def test_trace_timeline_marks_missing_source_as_not_recorded(self):
        token = self.login()
        self.sink.emit(
            AuditEvent(
                event_type="routing_decision",
                route="chat",
                trace_id="trace-routing-only",
                request_id="request-routing-only",
                user_id="user_demo_dept1",
                decision="shadow",
                metadata={"actual_route": "chat", "suggested_route": "rag"},
            )
        )

        response = self.client.get(
            "/api/admin/traces/trace-routing-only",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        trace = response.json()["data"]["trace"]
        self.assertEqual([item["source"] for item in trace["timeline"][:2]], ["routing", "not_recorded"])
        self.assertEqual(trace["timeline"][1]["stage"], "retrieval")
        self.assertEqual(trace["timeline"][1]["status"], "not_recorded")
        missing_stages = {
            item["stage"]
            for item in trace["timeline"]
            if item["source"] == "not_recorded"
        }
        self.assertTrue({"retrieval", "tool", "database", "memory", "sse"}.issubset(missing_stages))
        self.assertEqual(trace["summary"]["status"], "partial")
        self.assertEqual(trace["summary"]["failure_reason"], "retrieval_not_recorded")

    def test_trace_timeline_supports_request_id_lookup_and_expanded_sources(self):
        token = self.login()
        trace_id = "trace-p12"
        request_id = "request-p12"
        for event in [
            AuditEvent(
                event_type="routing_decision",
                route="chat",
                trace_id=trace_id,
                request_id=request_id,
                user_id="user_demo_dept1",
                decision="shadow",
                metadata={
                    "actual_route": "chat",
                    "suggested_route": "rag",
                    "routing_diagnostics": {"intent": "knowledge_retrieval"},
                    "api_token": "secret-token",
                },
            ),
            AuditEvent(
                event_type="rag_retrieval",
                route="rag",
                trace_id=trace_id,
                request_id=request_id,
                user_id="user_demo_dept1",
                decision="allowed",
                metadata={
                    "result_doc_ids": ["doc-cpu"],
                    "result_count": 1,
                    "source_refs": [
                        {
                            "kb_id": "process_digital_dept",
                            "doc_id": "doc-cpu",
                            "chunk_id": "doc-cpu:c00001",
                        }
                    ],
                    "source_ref_resolvable": True,
                },
            ),
            AuditEvent(
                event_type="permission_checked",
                route="permission",
                trace_id=trace_id,
                request_id=request_id,
                user_id="user_demo_dept1",
                decision="allowed",
                metadata={"resource_type": "document", "resource_id": "doc-cpu", "action": "read"},
            ),
            AuditEvent(
                event_type="tool_call",
                route="tool_gateway",
                trace_id=trace_id,
                request_id=request_id,
                user_id="user_demo_dept1",
                decision="allowed",
                latency_ms=12.5,
                metadata={"tool_id": "retrieve_knowledge", "tool_name": "Retrieve Knowledge", "token": "tool-secret"},
            ),
            AuditEvent(
                event_type="database_query",
                route="database_demo",
                trace_id=trace_id,
                request_id=request_id,
                user_id="user_demo_dept1",
                decision="allowed",
                latency_ms=35.0,
                metadata={
                    "database_id": "sandbox_sales",
                    "sanitized_sql": "SELECT email FROM customers",
                    "rows_returned": 2,
                },
            ),
            AuditEvent(
                event_type="session_memory_injected",
                route="rag",
                trace_id=trace_id,
                request_id=request_id,
                user_id="user_demo_dept1",
                decision="allowed",
                metadata={"mode": "active", "hit_count": 2, "raw_content": "do not leak memory text"},
            ),
            AuditEvent(
                event_type="sse_event",
                route="chat_stream",
                trace_id=trace_id,
                request_id=request_id,
                user_id="user_demo_dept1",
                decision="allowed",
                metadata={"sse_event_type": "message", "data": "stream token chunk should not leak"},
            ),
            AuditEvent(
                event_type="request_completed",
                route="chat_stream",
                trace_id=trace_id,
                request_id=request_id,
                user_id="user_demo_dept1",
                decision="allowed",
                latency_ms=321.0,
            ),
        ]:
            self.sink.emit(event)

        response = self.client.get(
            f"/api/admin/traces/{request_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        trace = response.json()["data"]["trace"]
        self.assertEqual(trace["trace_id"], trace_id)
        self.assertEqual(trace["request_id"], request_id)
        self.assertEqual(trace["lookup"]["identifier"], request_id)
        self.assertEqual(trace["lookup"]["matched_by"], "request_id")
        sources = [item["source"] for item in trace["timeline"]]
        for source in ["routing", "retrieval", "permission", "tool", "database", "memory", "sse", "audit"]:
            self.assertIn(source, sources)
        self.assertEqual(trace["summary"]["source_ref_status"], "resolvable")
        self.assertEqual(trace["summary"]["terminal_status"], "completed")
        self.assertEqual(trace["summary"]["latency_ms"], 321.0)

        routing = next(item for item in trace["timeline"] if item["source"] == "routing")
        self.assertEqual(routing["data"]["metadata"]["api_token"], "[REDACTED]")
        retrieval = next(item for item in trace["timeline"] if item["source"] == "retrieval")
        self.assertEqual(retrieval["data"]["source_refs"][0]["chunk_id"], "doc-cpu:c00001")
        database = next(item for item in trace["timeline"] if item["source"] == "database")
        self.assertNotIn("sanitized_sql", database["data"]["metadata"])
        self.assertIn("sql_hash", database["data"]["metadata"])
        memory = next(item for item in trace["timeline"] if item["source"] == "memory")
        self.assertEqual(memory["data"]["metadata"]["raw_content"], "[REDACTED]")
        sse = next(item for item in trace["timeline"] if item["source"] == "sse")
        self.assertNotIn("data", sse["data"]["metadata"])
        self.assertGreater(sse["data"]["metadata"]["payload_size_bytes"], 0)

    def test_trace_comparison_summarizes_two_traces(self):
        token = self.login()
        samples = [
            ("trace-compare-a", "request-compare-a", "rag", "doc-cpu", True, 120.0),
            ("trace-compare-b", "request-compare-b", "chat", "doc-network", False, 250.0),
        ]
        for trace_id, request_id, suggested_route, top_doc, source_ref_ok, latency_ms in samples:
            self.sink.emit(
                AuditEvent(
                    event_type="routing_decision",
                    route="chat",
                    trace_id=trace_id,
                    request_id=request_id,
                    user_id="user_demo_dept1",
                    decision="shadow",
                    metadata={"actual_route": "chat", "suggested_route": suggested_route},
                )
            )
            self.sink.emit(
                AuditEvent(
                    event_type="rag_retrieval",
                    route="rag",
                    trace_id=trace_id,
                    request_id=request_id,
                    user_id="user_demo_dept1",
                    decision="allowed",
                    metadata={
                        "result_doc_ids": [top_doc],
                        "result_count": 1,
                        "source_ref_resolvable": source_ref_ok,
                    },
                )
            )
            self.sink.emit(
                AuditEvent(
                    event_type="request_completed",
                    route="chat_stream",
                    trace_id=trace_id,
                    request_id=request_id,
                    user_id="user_demo_dept1",
                    decision="allowed",
                    latency_ms=latency_ms,
                )
            )

        response = self.client.get(
            "/api/admin/traces/compare",
            headers={"Authorization": f"Bearer {token}"},
            params={"left": "trace-compare-a", "right": "trace-compare-b"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        comparison = response.json()["data"]["comparison"]
        self.assertEqual(comparison["left"]["trace_id"], "trace-compare-a")
        self.assertEqual(comparison["right"]["trace_id"], "trace-compare-b")
        rows = {row["key"]: row for row in comparison["rows"]}
        self.assertEqual(rows["routing"]["left"], "chat/rag")
        self.assertEqual(rows["retrieval_top1"]["right"], "doc-network")
        self.assertEqual(rows["source_ref"]["left"], "resolvable")
        self.assertEqual(rows["source_ref"]["right"], "unresolvable")
        self.assertEqual(rows["latency_ms"]["left"], 120.0)
        self.assertEqual(rows["terminal_status"]["right"], "completed")
        self.assertIn("routing", comparison["differences"])

    def test_department_admin_cannot_query_trace_outside_department_scope(self):
        self.admin_service.auth.create_user(
            user_id="user_dept1_manager",
            username="dept1_manager",
            password="Manager123!",
            department_id="dept_1",
            department_name="Department 1",
            roles=["department_admin"],
        )
        token = self.login("dept1_manager", "Manager123!")
        self.sink.emit(
            AuditEvent(
                event_type="routing_decision",
                route="chat",
                trace_id="trace-dept2",
                request_id="request-dept2",
                user_id="user_demo_dept2",
                decision="shadow",
                metadata={"actual_route": "chat"},
            )
        )

        response = self.client.get(
            "/api/admin/traces/trace-dept2",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 403)

    def test_sqlite_audit_sink_creates_trace_query_indexes(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise_audit.sqlite"
            sink = SQLiteAuditSink(db_path)
            sink.emit(
                AuditEvent(
                    event_type="routing_decision",
                    route="chat",
                    trace_id="trace-index",
                    request_id="request-index",
                    user_id="user_demo_dept1",
                )
            )

            import sqlite3

            with sqlite3.connect(db_path) as connection:
                indexes = {
                    row[1]
                    for row in connection.execute("PRAGMA index_list('enterprise_audit_events')").fetchall()
                }

        self.assertIn("idx_enterprise_audit_events_trace_id", indexes)
        self.assertIn("idx_enterprise_audit_events_trace_timestamp", indexes)
        self.assertIn("idx_enterprise_audit_events_request_id", indexes)
        self.assertIn("idx_enterprise_audit_events_request_timestamp", indexes)

    def test_sqlite_audit_sink_can_query_by_request_id(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise_audit.sqlite"
            sink = SQLiteAuditSink(db_path)
            sink.emit(
                AuditEvent(
                    event_type="routing_decision",
                    route="chat",
                    trace_id="trace-request-query",
                    request_id="request-query",
                    user_id="user_demo_dept1",
                )
            )

            events = sink.query(request_id="request-query")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].trace_id, "trace-request-query")

    def test_admin_resource_catalog_lists_indexed_documents_tools_and_database_resources(self):
        from app.enterprise.admin.resources import ResourceCatalogService
        from app.enterprise.database.permissions import (
            database_column_resource_id,
            database_operation_resource_id,
            database_table_resource_id,
        )
        from app.enterprise.database.registry import build_default_sandbox_registry
        from app.models import DocumentRecord, DocumentStatus, ParserEngine
        from app.services.knowledge_metadata_store import KnowledgeMetadataStore

        token = self.login()

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            metadata_store.upsert_document(
                DocumentRecord(
                    doc_id="doc-guide",
                    kb_id="guide",
                    file_name="guide.md",
                    file_ext="md",
                    original_path=(root / "guide.md").as_posix(),
                    artifact_dir=(root / "doc-guide" / "artifacts").as_posix(),
                    parser_engine=ParserEngine.PLAIN_TEXT,
                    status=DocumentStatus.INDEXED,
                )
            )
            metadata_store.upsert_document(
                DocumentRecord(
                    doc_id="doc-pending",
                    kb_id="guide",
                    file_name="pending.md",
                    file_ext="md",
                    original_path=(root / "pending.md").as_posix(),
                    artifact_dir=(root / "doc-pending" / "artifacts").as_posix(),
                    parser_engine=ParserEngine.PLAIN_TEXT,
                    status=DocumentStatus.PARSE_PENDING,
                )
            )
            registry = build_default_sandbox_registry()
            self.admin_service.resource_catalog = ResourceCatalogService(
                metadata_store=metadata_store,
                database_registry=registry,
            )

            response = self.client.get(
                "/api/admin/resources",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        resources = response.json()["data"]["resources"]
        by_id = {resource["resource_id"]: resource for resource in resources}

        self.assertIn("doc-guide", by_id)
        self.assertNotIn("doc-pending", by_id)
        self.assertEqual(by_id["doc-guide"]["resource_type"], "document")
        self.assertEqual(by_id["doc-guide"]["actions_supported"], ["read"])
        self.assertEqual(by_id["doc-guide"]["metadata"]["kb_id"], "guide")
        self.assertNotIn("status", by_id["doc-guide"])
        self.assertNotIn("source", by_id["doc-guide"])

        self.assertIn("retrieve_knowledge", by_id)
        self.assertEqual(by_id["retrieve_knowledge"]["actions_supported"], ["use"])
        self.assertIn("list_knowledge_documents", by_id)
        self.assertEqual(by_id["list_knowledge_documents"]["actions_supported"], ["use"])
        self.assertIn("get_current_time", by_id)
        self.assertEqual(by_id["get_current_time"]["actions_supported"], ["use"])

        table_id = database_table_resource_id(registry.database_id, "factory_access_events")
        column_id = database_column_resource_id(registry.database_id, "factory_access_events", "event_id")
        self.assertIn(table_id, by_id)
        self.assertIn(column_id, by_id)
        self.assertEqual(by_id[table_id]["actions_supported"], ["read"])
        self.assertEqual(by_id[column_id]["metadata"]["column_name"], "event_id")
        operation_id = database_operation_resource_id(registry.database_id, "delete")
        self.assertIn(operation_id, by_id)
        self.assertEqual(by_id[operation_id]["resource_type"], "database_operation")
        self.assertEqual(by_id[operation_id]["actions_supported"], ["execute"])
        self.assertEqual(by_id[operation_id]["metadata"]["operation_type"], "delete")
        self.assertNotIn("kbs", response.json()["data"])

    def test_non_admin_cannot_read_resource_catalog(self):
        token = self.login("demo_user_dept1", "Demo123!")

        response = self.client.get(
            "/api/admin/resources",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 403)

    def test_grant_preview_passes_for_existing_resource_action_and_principal(self):
        from app.enterprise.admin.resources import ResourceCatalogService
        from app.models import DocumentRecord, DocumentStatus, ParserEngine
        from app.services.knowledge_metadata_store import KnowledgeMetadataStore

        token = self.login()
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            metadata_store.upsert_document(
                DocumentRecord(
                    doc_id="doc-guide",
                    kb_id="guide",
                    file_name="guide.md",
                    file_ext="md",
                    original_path=(root / "guide.md").as_posix(),
                    artifact_dir=(root / "doc-guide" / "artifacts").as_posix(),
                    parser_engine=ParserEngine.PLAIN_TEXT,
                    status=DocumentStatus.INDEXED,
                )
            )
            self.admin_service.resource_catalog = ResourceCatalogService(metadata_store=metadata_store)

            response = self.client.post(
                "/api/admin/grant-preview",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "resource_type": "document",
                    "resource_id": "doc-guide",
                    "action": "read",
                    "principal_type": "user",
                    "principal_id": "user_demo_dept1",
                    "effect": "allow",
                    "reason": "preview pass",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertTrue(data["can_submit"])
        self.assertEqual(
            [check["check"] for check in data["checks"]],
            [
                "resource_exists",
                "action_supported",
                "principal_exists",
                "scope_allowed",
                "duplicate_grant",
                "direct_conflict",
            ],
        )
        self.assertTrue(all(check["status"] == "passed" for check in data["checks"]))

    def test_grant_preview_passes_for_database_operation_execute_resource(self):
        from app.enterprise.database.permissions import database_operation_resource_id

        token = self.login()

        response = self.client.post(
            "/api/admin/grant-preview",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "resource_type": "database_operation",
                "resource_id": database_operation_resource_id("sandbox_sales", "delete"),
                "action": "execute",
                "principal_type": "user",
                "principal_id": "user_demo_dept1",
                "effect": "allow",
                "reason": "can delete with confirmation",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertTrue(data["can_submit"])
        self.assertTrue(all(check["status"] == "passed" for check in data["checks"]))

    def test_grant_preview_blocks_missing_resource_and_skips_dependent_checks(self):
        token = self.login()

        response = self.client.post(
            "/api/admin/grant-preview",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "resource_type": "document",
                "resource_id": "doc-missing",
                "action": "read",
                "principal_type": "user",
                "principal_id": "user_demo_dept1",
                "effect": "allow",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertFalse(data["can_submit"])
        self.assertEqual(data["checks"][0]["check"], "resource_exists")
        self.assertEqual(data["checks"][0]["status"], "failed")
        self.assertEqual(
            [check["status"] for check in data["checks"][1:]],
            ["skipped", "skipped", "skipped", "skipped", "skipped"],
        )

    def test_grant_preview_blocks_unsupported_action_and_missing_principal(self):
        from app.enterprise.admin.resources import ResourceCatalogService
        from app.models import DocumentRecord, DocumentStatus, ParserEngine
        from app.services.knowledge_metadata_store import KnowledgeMetadataStore

        token = self.login()
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            metadata_store.upsert_document(
                DocumentRecord(
                    doc_id="doc-guide",
                    kb_id="guide",
                    file_name="guide.md",
                    file_ext="md",
                    original_path=(root / "guide.md").as_posix(),
                    artifact_dir=(root / "doc-guide" / "artifacts").as_posix(),
                    parser_engine=ParserEngine.PLAIN_TEXT,
                    status=DocumentStatus.INDEXED,
                )
            )
            self.admin_service.resource_catalog = ResourceCatalogService(metadata_store=metadata_store)

            response = self.client.post(
                "/api/admin/grant-preview",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "resource_type": "document",
                    "resource_id": "doc-guide",
                    "action": "use",
                    "principal_type": "user",
                    "principal_id": "user_missing",
                    "effect": "allow",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        checks = {check["check"]: check for check in response.json()["data"]["checks"]}
        self.assertFalse(response.json()["data"]["can_submit"])
        self.assertEqual(checks["resource_exists"]["status"], "passed")
        self.assertEqual(checks["action_supported"]["status"], "failed")
        self.assertEqual(checks["principal_exists"]["status"], "failed")

    def test_grant_preview_reports_duplicate_and_direct_conflict(self):
        from app.enterprise.admin.resources import ResourceCatalogService
        from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
        from app.models import DocumentRecord, DocumentStatus, ParserEngine
        from app.services.knowledge_metadata_store import KnowledgeMetadataStore

        token = self.login()
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            metadata_store.upsert_document(
                DocumentRecord(
                    doc_id="doc-guide",
                    kb_id="guide",
                    file_name="guide.md",
                    file_ext="md",
                    original_path=(root / "guide.md").as_posix(),
                    artifact_dir=(root / "doc-guide" / "artifacts").as_posix(),
                    parser_engine=ParserEngine.PLAIN_TEXT,
                    status=DocumentStatus.INDEXED,
                )
            )
            self.admin_service.resource_catalog = ResourceCatalogService(metadata_store=metadata_store)
            duplicate = self.permission_service.grant_access(
                ResourceGrant(
                    resource_type="document",
                    resource_id="doc-guide",
                    action="read",
                    principal_type=PrincipalType.USER,
                    principal_id="user_demo_dept1",
                    effect=GrantEffect.ALLOW,
                )
            )
            conflict = self.permission_service.grant_access(
                ResourceGrant(
                    resource_type="document",
                    resource_id="doc-guide",
                    action="read",
                    principal_type=PrincipalType.USER,
                    principal_id="user_demo_dept1",
                    effect=GrantEffect.DENY,
                )
            )

            response = self.client.post(
                "/api/admin/grant-preview",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "resource_type": "document",
                    "resource_id": "doc-guide",
                    "action": "read",
                    "principal_type": "user",
                    "principal_id": "user_demo_dept1",
                    "effect": "allow",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        checks = {check["check"]: check for check in data["checks"]}
        self.assertFalse(data["can_submit"])
        self.assertEqual(checks["duplicate_grant"]["status"], "failed")
        self.assertEqual(checks["duplicate_grant"]["matched_grant_ids"], [duplicate.grant_id])
        self.assertEqual(checks["direct_conflict"]["status"], "warning")
        self.assertEqual(checks["direct_conflict"]["matched_grant_ids"], [conflict.grant_id])
        self.assertIn("Existing deny will block this allow", checks["direct_conflict"]["message"])

    def test_grant_create_rejects_missing_resource_and_writes_failed_audit(self):
        token = self.login()

        response = self.client.post(
            "/api/admin/grants",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Trace-Id": "trace-grant-rejected",
            },
            json={
                "resource_type": "document",
                "resource_id": "doc-missing",
                "action": "read",
                "principal_type": "user",
                "principal_id": "user_demo_dept1",
                "effect": "allow",
            },
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("resource_exists", response.json()["detail"])
        rejected_events = [
            event
            for event in self.sink.events
            if event.event_type == "admin_operation"
            and event.metadata.get("operation") == "grant_access_rejected"
        ]
        self.assertEqual(len(rejected_events), 1)
        self.assertEqual(rejected_events[0].decision, "failed")
        self.assertEqual(rejected_events[0].reason, "resource_exists")
        self.assertEqual(rejected_events[0].metadata["failed_check"], "resource_exists")
        self.assertEqual(rejected_events[0].metadata["target_type"], "grant")
        self.assertEqual(rejected_events[0].metadata["status"], "failed")

    def test_grant_create_rejects_duplicate_but_allows_direct_conflict_warning(self):
        from app.enterprise.admin.resources import ResourceCatalogService
        from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
        from app.models import DocumentRecord, DocumentStatus, ParserEngine
        from app.services.knowledge_metadata_store import KnowledgeMetadataStore

        token = self.login()
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            metadata_store.upsert_document(
                DocumentRecord(
                    doc_id="doc-guide",
                    kb_id="guide",
                    file_name="guide.md",
                    file_ext="md",
                    original_path=(root / "guide.md").as_posix(),
                    artifact_dir=(root / "doc-guide" / "artifacts").as_posix(),
                    parser_engine=ParserEngine.PLAIN_TEXT,
                    status=DocumentStatus.INDEXED,
                )
            )
            self.admin_service.resource_catalog = ResourceCatalogService(metadata_store=metadata_store)
            self.permission_service.grant_access(
                ResourceGrant(
                    resource_type="document",
                    resource_id="doc-guide",
                    action="read",
                    principal_type=PrincipalType.USER,
                    principal_id="user_demo_dept1",
                    effect=GrantEffect.ALLOW,
                )
            )

            duplicate = self.client.post(
                "/api/admin/grants",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "resource_type": "document",
                    "resource_id": "doc-guide",
                    "action": "read",
                    "principal_type": "user",
                    "principal_id": "user_demo_dept1",
                    "effect": "allow",
                },
            )
            deny_response = self.client.post(
                "/api/admin/grants",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "resource_type": "document",
                    "resource_id": "doc-guide",
                    "action": "read",
                    "principal_type": "user",
                    "principal_id": "user_demo_dept1",
                    "effect": "deny",
                    "reason": "deny overrides old allow",
                },
            )

        self.assertEqual(duplicate.status_code, 400, duplicate.text)
        self.assertIn("duplicate_grant", duplicate.json()["detail"])
        self.assertEqual(deny_response.status_code, 200, deny_response.text)
        self.assertEqual(deny_response.json()["data"]["grant"]["effect"], "deny")


if __name__ == "__main__":
    unittest.main()
