import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.auth as auth_api
import app.api.file as file_api
from app.enterprise.auth.service import auth_service
from app.enterprise.context import (
    RequestContext,
    reset_current_request_context,
    set_current_request_context,
)
from app.enterprise.database.permissions import (
    database_column_resource_id,
    database_table_resource_id,
)
from app.enterprise.gateway.models import GatewayRequest
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.service import permission_service
from app.models import (
    DocumentRecord,
    DocumentStatus,
    ParserEngine,
    RetrievalQuery,
    RetrievalResponse,
)
from app.services.document_health_check_service import (
    DocumentHealthCheckResult,
    DocumentHealthCheckStore,
    DocumentHealthStatus,
)
from app.services.knowledge_metadata_store import KnowledgeMetadataStore


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    app.include_router(file_api.router, prefix="/api")
    return app


def _context() -> RequestContext:
    return RequestContext(
        request_id="request-opt",
        trace_id="trace-opt",
        user_id="user_demo_dept1",
        username="demo_user_dept1",
        department_id="dept_1",
        department_name="Department 1",
        roles=["user"],
    )


def _document(
    doc_id: str,
    kb_id: str,
    file_name: str,
    root: Path,
    *,
    status: DocumentStatus = DocumentStatus.INDEXED,
) -> DocumentRecord:
    return DocumentRecord(
        doc_id=doc_id,
        kb_id=kb_id,
        file_name=file_name,
        file_ext=file_name.rsplit(".", 1)[-1],
        original_path=(root / file_name).as_posix(),
        artifact_dir=(root / doc_id / "artifacts").as_posix(),
        parser_engine=ParserEngine.PLAIN_TEXT,
        status=status,
    )


def _grant_document(doc_id: str, *, user_id: str = "user_demo_dept1") -> None:
    _grant_resource("document", doc_id, user_id=user_id)


def _grant_resource(
    resource_type: str,
    resource_id: str,
    *,
    action: str = "read",
    user_id: str = "user_demo_dept1",
) -> None:
    permission_service.grant_access(
        ResourceGrant(
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            principal_type=PrincipalType.USER,
            principal_id=user_id,
            effect=GrantEffect.ALLOW,
            reason="assistant-optimization-test",
        )
    )


class AssistantFrontendOptimizationTests(unittest.TestCase):
    def setUp(self):
        auth_service.reset_users()
        auth_service.clear_blacklist()
        permission_service.repository.clear()
        permission_service.invalidate_cache()

    def _login(self, client: TestClient, username: str = "demo_user_dept1") -> str:
        password = "Demo123!" if username == "demo_user_dept1" else "Admin123!"
        response = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["access_token"]

    def test_gateway_request_uses_bearer_token_over_spoofed_user_headers(self):
        user = auth_service.authenticate("demo_user_dept1", "Demo123!")
        token = auth_service.create_access_token(user)

        gateway_request = GatewayRequest.from_headers(
            route="chat",
            payload={"Question": "who am i"},
            headers={
                "Authorization": f"Bearer {token}",
                "X-User-Id": "user_admin",
                "X-Username": "admin",
                "X-Roles": "admin",
                "X-Department-Id": "system",
                "X-Department-Name": "System",
            },
        )

        self.assertEqual(gateway_request.user_id, "user_demo_dept1")
        self.assertEqual(gateway_request.username, "demo_user_dept1")
        self.assertEqual(gateway_request.roles, ["user"])
        self.assertEqual(gateway_request.department_id, "dept_1")

    def test_profile_endpoint_returns_user_visible_tools_and_visible_kb_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            metadata_store.upsert_document(_document("doc-guide", "guide", "guide.md", root))
            metadata_store.upsert_document(_document("doc-hidden", "secret", "secret.md", root))
            _grant_document("doc-guide")

            client = TestClient(_build_app())
            token = self._login(client)

            with patch.object(
                auth_api.profile_service.document_access_service,
                "metadata_store",
                metadata_store,
            ):
                response = client.get(
                    "/api/me/profile",
                    headers={"Authorization": f"Bearer {token}"},
                )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["user"]["user_id"], "user_demo_dept1")
        self.assertIn("retrieve_knowledge", data["visible_tools"])
        self.assertIn("list_knowledge_documents", data["visible_tools"])
        self.assertEqual(data["visible_kb_ids"], ["guide"])
        self.assertTrue(data["feature_flags"]["rag_chat"])
        self.assertFalse(data["feature_flags"]["admin"])

    def test_profile_exposes_capability_health_payload(self):
        client = TestClient(_build_app())
        token = self._login(client)

        response = client.get(
            "/api/me/profile",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        capabilities = response.json()["data"]["capabilities"]
        self.assertEqual(capabilities["profile"]["status"], "ok")
        self.assertEqual(capabilities["knowledge_base_api"]["status"], "ok")
        self.assertIn(capabilities["document_worker"]["status"], {"ok", "degraded", "unknown"})
        self.assertEqual(capabilities["database_catalog"]["status"], "ok")
        self.assertIn(capabilities["tool_gateway"]["status"], {"ok", "degraded"})
        self.assertIn("details", capabilities["document_worker"])

    def test_admin_profile_exposes_admin_feature_flag(self):
        client = TestClient(_build_app())
        token = self._login(client, username="admin")

        response = client.get(
            "/api/me/profile",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["user"]["user_id"], "user_admin")
        self.assertTrue(data["feature_flags"]["admin"])

    def test_profile_database_demo_unavailable_without_tool_or_table_grant(self):
        client = TestClient(_build_app())
        token = self._login(client)

        response = client.get(
            "/api/me/profile",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertFalse(data["feature_flags"]["database_demo"])
        self.assertEqual(
            data["database_demo"],
            {
                "enabled": False,
                "database_id": "sandbox_sales",
                "visible_tables": [],
                "readonly": True,
                "unavailable_reason": "permission_denied",
            },
        )
        self.assertNotIn("database_demo.safe_select", data["visible_tools"])

        _grant_resource("tool", "database_demo.safe_select", action="use")
        response = client.get(
            "/api/me/profile",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertFalse(data["database_demo"]["enabled"])
        self.assertEqual(data["database_demo"]["visible_tables"], [])
        self.assertEqual(data["database_demo"]["unavailable_reason"], "permission_denied")

    def test_profile_returns_database_demo_scope_when_authorized(self):
        for tool_id in (
            "database_demo.list_tables",
            "database_demo.describe_table",
            "database_demo.safe_select",
        ):
            _grant_resource("tool", tool_id, action="use")
        _grant_resource("database_table", database_table_resource_id("sandbox_sales", "factory_access_events"))
        _grant_resource(
            "database_column",
            database_column_resource_id("sandbox_sales", "factory_access_events", "event_id"),
        )
        _grant_resource(
            "database_column",
            database_column_resource_id("sandbox_sales", "factory_access_events", "direction"),
        )
        client = TestClient(_build_app())
        token = self._login(client)

        response = client.get(
            "/api/me/profile",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertTrue(data["feature_flags"]["database_demo"])
        self.assertEqual(
            data["database_demo"],
            {
                "enabled": True,
                "database_id": "sandbox_sales",
                "visible_tables": [
                    {
                        "table_name": "factory_access_events",
                        "resource_id": "sandbox_sales.factory_access_events",
                        "visible_columns": [
                            {
                                "column_name": "event_id",
                                "resource_id": "sandbox_sales.factory_access_events.event_id",
                            },
                            {
                                "column_name": "direction",
                                "resource_id": "sandbox_sales.factory_access_events.direction",
                            },
                        ],
                    },
                ],
                "readonly": True,
                "unavailable_reason": None,
            },
        )
        self.assertIn("database_demo.safe_select", data["visible_tools"])

    def test_profile_lists_visible_database_tables_and_columns(self):
        _grant_resource("tool", "database_demo.list_tables", action="use")
        _grant_resource("database_table", database_table_resource_id("sandbox_sales", "factory_access_events"))
        _grant_resource("database_table", database_table_resource_id("sandbox_sales", "building_access_events"))
        _grant_resource(
            "database_column",
            database_column_resource_id("sandbox_sales", "factory_access_events", "event_id"),
        )
        _grant_resource(
            "database_column",
            database_column_resource_id("sandbox_sales", "building_access_events", "building_name"),
        )
        client = TestClient(_build_app())
        token = self._login(client)

        response = client.get(
            "/api/me/profile",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        tables = response.json()["data"]["database_demo"]["visible_tables"]
        self.assertEqual([table["table_name"] for table in tables], ["factory_access_events", "building_access_events"])
        self.assertEqual(
            [[column["column_name"] for column in table["visible_columns"]] for table in tables],
            [["event_id"], ["building_name"]],
        )

    def test_static_admin_console_assets_reference_existing_admin_apis(self):
        static_root = Path(__file__).resolve().parents[1] / "static"
        index_html = (static_root / "index.html").read_text(encoding="utf-8")
        app_js = (static_root / "app.js").read_text(encoding="utf-8")
        app_css = (static_root / "styles.css").read_text(encoding="utf-8")
        html = (static_root / "admin-console.html").read_text(encoding="utf-8")
        js = (static_root / "admin-console.js").read_text(encoding="utf-8")
        admin_css = (static_root / "admin-console.css").read_text(encoding="utf-8")
        dashboard_html = (static_root / "enterprise-dashboard.html").read_text(encoding="utf-8")
        dashboard_js = (static_root / "enterprise-dashboard.js").read_text(encoding="utf-8")
        dashboard_css = (static_root / "enterprise-dashboard.css").read_text(encoding="utf-8")
        highlight_js = (static_root / "vendor" / "highlight" / "highlight.min.js").read_text(
            encoding="utf-8"
        )
        highlight_css = (static_root / "vendor" / "highlight" / "github.min.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("adminConsoleMenuItem", index_html)
        self.assertIn("executionDashboardMenuItem", index_html)
        self.assertIn("/static/enterprise-api-client.js", index_html)
        self.assertIn("/static/vendor/highlight/github.min.css", index_html)
        self.assertIn("/static/vendor/highlight/highlight.min.js", index_html)
        self.assertNotIn("cdn.jsdelivr.net/npm/highlight.js", index_html)
        self.assertIn("var hljs=", highlight_js)
        self.assertIn("pre code.hljs", highlight_css)
        self.assertIn("/static/admin-console.html", app_js)
        self.assertIn("/static/enterprise-dashboard.html", app_js)
        self.assertIn("EnterpriseApiClient", app_js)
        self.assertIn("/static/enterprise-api-client.js", html)
        self.assertLess(
            html.index("/static/enterprise-api-client.js"),
            html.index("/static/admin-console.js"),
        )
        self.assertIn("/static/admin-console.js", html)
        self.assertIn("EnterpriseApiClient", js)
        self.assertIn("capabilityHealth", js)
        self.assertIn("capabilityHealthItems", js)
        self.assertIn("capabilityStatusLabel", js)
        self.assertIn("capability-health-banner", html)
        self.assertIn("v-for=\"item in capabilityHealthItems\"", html)
        self.assertIn(".capability-health-banner", admin_css)
        self.assertIn("/static/enterprise-api-client.js", dashboard_html)
        self.assertLess(
            dashboard_html.index("/static/enterprise-api-client.js"),
            dashboard_html.index("/static/enterprise-dashboard.js"),
        )
        self.assertIn("EnterpriseApiClient", dashboard_js)
        self.assertIn("capabilityHealth", dashboard_js)
        self.assertIn("loadCapabilityHealth", dashboard_js)
        self.assertIn("capabilityHealthItems", dashboard_js)
        self.assertIn("capability-health-banner", dashboard_html)
        self.assertIn("v-for=\"item in capabilityHealthItems\"", dashboard_html)
        self.assertIn(".capability-health-banner", dashboard_css)
        self.assertIn("renderCapabilityHealthRows", app_js)
        self.assertIn("capability-health-banner", app_js)
        self.assertIn(".capability-health-banner", app_css)
        self.assertIn("/admin/users", js)
        self.assertIn("/admin/roles", js)
        self.assertIn("/admin/departments", js)
        self.assertIn("/admin/grants", js)
        self.assertIn("/admin/audit", js)
        self.assertIn("/admin/reviews/pending", js)

    def test_admin_console_refresh_only_shows_success_after_successful_load(self):
        static_root = Path(__file__).resolve().parents[1] / "static"
        js = (static_root / "admin-console.js").read_text(encoding="utf-8")

        self.assertIn("const ok = await this.loadRouteData(this.route);", js)
        self.assertIn("if (ok) {\n                        this.showToast('已刷新', 'success');", js)
        self.assertIn("return false;", js)

    def test_admin_console_handles_non_revoked_grant_response(self):
        static_root = Path(__file__).resolve().parents[1] / "static"
        js = (static_root / "admin-console.js").read_text(encoding="utf-8")

        self.assertIn("const payload = await this.adminFetch(`/admin/grants/${encodeURIComponent(grant.grant_id)}`", js)
        self.assertIn("if (!payload.data?.revoked) {", js)
        self.assertIn("Grant 不存在或已被撤销", js)

    def test_admin_console_stage3_lite_uses_resources_actions_and_preview_before_save(self):
        static_root = Path(__file__).resolve().parents[1] / "static"
        html = (static_root / "admin-console.html").read_text(encoding="utf-8")
        js = (static_root / "admin-console.js").read_text(encoding="utf-8")

        self.assertIn("{ key: 'resources', label: '资源' }", js)
        self.assertIn("loadResources", js)
        self.assertIn("/admin/resources", js)
        self.assertIn("/admin/grant-preview", js)
        self.assertIn("selectedResourceActions", js)
        self.assertIn("selectedResource?.actions_supported", js)
        self.assertIn("previewGrant", js)
        self.assertIn("grantPreview?.can_submit", js)
        self.assertIn("请先通过授权预览", js)
        self.assertIn("route === 'resources'", html)
        self.assertIn("actions_supported", html)
        self.assertIn("admin-preview-panel", html)

    def test_admin_console_groups_database_resources_by_table(self):
        static_root = Path(__file__).resolve().parents[1] / "static"
        html = (static_root / "admin-console.html").read_text(encoding="utf-8")
        js = (static_root / "admin-console.js").read_text(encoding="utf-8")

        self.assertIn("databaseResources", js)
        self.assertIn("databaseTables", js)
        self.assertIn("databaseColumnsByTable", js)
        self.assertIn("resource.resource_type === 'database_table'", js)
        self.assertIn("resource.resource_type === 'database_column'", js)
        self.assertIn('v-for="table in databaseTables"', html)
        self.assertIn("databaseColumnsByTable", html)

    def test_admin_console_explains_database_demo_readonly_boundary(self):
        static_root = Path(__file__).resolve().parents[1] / "static"
        html = (static_root / "admin-console.html").read_text(encoding="utf-8")

        self.assertIn("sandbox_sales", html)
        self.assertIn("只读", html)
        self.assertIn("DML / DDL", html)
        self.assertIn("SafeSqlKernel", html)

    def test_admin_console_database_resources_use_existing_resource_ids(self):
        static_root = Path(__file__).resolve().parents[1] / "static"
        html = (static_root / "admin-console.html").read_text(encoding="utf-8")
        js = (static_root / "admin-console.js").read_text(encoding="utf-8")

        self.assertNotIn("database_table_resource_id", js)
        self.assertNotIn("database_column_resource_id", js)
        self.assertIn("applyResourceToGrant(table)", html)
        self.assertIn("applyResourceToGrant(column)", html)
        self.assertIn("{{ table.resource_id }}", html)
        self.assertIn("{{ column.resource_id }}", html)

    def test_admin_console_stage4_uses_department_resource_scope_configuration(self):
        static_root = Path(__file__).resolve().parents[1] / "static"
        html = (static_root / "admin-console.html").read_text(encoding="utf-8")
        js = (static_root / "admin-console.js").read_text(encoding="utf-8")

        self.assertIn("{ key: 'departments', label: '部门' }", js)
        self.assertIn("visibleNavItems", js)
        self.assertIn("isGlobalAdmin", js)
        self.assertIn("/admin/departments", js)
        self.assertIn("/resource-scope", js)
        self.assertIn("forms.departmentScope.resource_type", html)
        self.assertIn("forms.departmentScope.resource_id", html)
        self.assertIn("forms.departmentScope.action", html)
        self.assertIn("manageable_resources", html)

    def test_admin_console_stage4_loads_admin_scope_and_shows_department_admin_badge(self):
        static_root = Path(__file__).resolve().parents[1] / "static"
        html = (static_root / "admin-console.html").read_text(encoding="utf-8")
        js = (static_root / "admin-console.js").read_text(encoding="utf-8")

        self.assertIn("scope: null", js)
        self.assertIn("const scopePayload = await this.adminFetch('/admin/scope');", js)
        self.assertIn("this.scope = scopePayload.data?.scope || null;", js)
        self.assertIn("isDepartmentAdmin()", js)
        self.assertIn("scopeLabel()", js)
        self.assertIn("admin-scope-badge", html)
        self.assertIn("{{ scopeLabel }}", html)
        self.assertIn("部门管理员", html)

    def test_admin_console_stage4_locks_department_admin_controls(self):
        static_root = Path(__file__).resolve().parents[1] / "static"
        html = (static_root / "admin-console.html").read_text(encoding="utf-8")
        js = (static_root / "admin-console.js").read_text(encoding="utf-8")

        self.assertIn("item.key !== 'roles' || this.isGlobalAdmin", js)
        self.assertIn("item.key !== 'departments' || this.isGlobalAdmin", js)
        self.assertIn("v-if=\"route === 'roles' && isGlobalAdmin\"", html)
        self.assertIn("v-model.trim=\"forms.user.department_id\" required :disabled=\"busy || isDepartmentAdmin\"", html)
        self.assertIn("v-model.trim=\"forms.user.department_name\" required :disabled=\"busy || isDepartmentAdmin\"", html)
        self.assertIn("仅显示本部门可管理资源", html)
        self.assertIn("只显示本部门相关审计", html)

    def test_stage5_chat_profile_modal_can_submit_and_list_permission_requests(self):
        static_root = Path(__file__).resolve().parents[1] / "static"
        html = (static_root / "index.html").read_text(encoding="utf-8")
        js = (static_root / "app.js").read_text(encoding="utf-8")
        css = (static_root / "styles.css").read_text(encoding="utf-8")

        self.assertIn("permissionsMenuItem", html)
        self.assertIn("permissionRequestForm", js)
        self.assertIn("quickPermissionRequestForm", js)
        self.assertIn("advancedPermissionRequestForm", js)
        self.assertIn("loadPermissionRequests", js)
        self.assertIn("loadRequestableResources", js)
        self.assertIn("submitPermissionRequest", js)
        self.assertIn("/permission-requests/mine", js)
        self.assertIn("/permission-requests/resources", js)
        self.assertIn("/permission-requests", js)
        self.assertIn("知识库快捷申请", js)
        self.assertIn("高级资源申请", js)
        self.assertIn("quickPermissionKbId", js)
        self.assertIn("quickPermissionReason", js)
        self.assertIn("advancedPermissionResourceType", js)
        self.assertIn("advancedPermissionResourceId", js)
        self.assertIn("advancedPermissionAction", js)
        self.assertNotIn("requestPermissionResourceId", js)
        self.assertIn("permission-request-status", js)
        self.assertIn("resource_display_name", js)
        self.assertIn("action_display_name", js)
        self.assertIn(".permission-request-form", css)
        self.assertIn(".permission-request-grid", css)
        self.assertIn("grid-template-columns", css)
        self.assertIn(".permission-request-form label", css)

    def test_database_operation_confirmations_render_in_user_permissions_modal(self):
        static_root = Path(__file__).resolve().parents[1] / "static"
        html = (static_root / "index.html").read_text(encoding="utf-8")
        js = (static_root / "app.js").read_text(encoding="utf-8")
        css = (static_root / "styles.css").read_text(encoding="utf-8")

        self.assertIn("permissionsMenuItem", html)
        self.assertIn("databaseConfirmations", js)
        self.assertIn("loadDatabaseConfirmations", js)
        self.assertIn("renderDatabaseConfirmationRows", js)
        self.assertIn("confirmDatabaseOperation", js)
        self.assertIn("cancelDatabaseOperation", js)
        self.assertIn("/database/confirmations", js)
        self.assertIn("database-confirmation-list", js)
        self.assertIn("database-confirmation-status", js)
        self.assertIn("databaseConfirmationStatusTone", js)
        self.assertIn(".database-confirmation-list", css)
        self.assertIn(".database-confirmation-row", css)
        self.assertIn(".database-confirmation-actions", css)
        self.assertIn(".database-confirmation-status", css)

    def test_user_database_catalog_panel_shows_capability_health(self):
        static_root = Path(__file__).resolve().parents[1] / "static"
        html = (static_root / "index.html").read_text(encoding="utf-8")
        js = (static_root / "app.js").read_text(encoding="utf-8")
        css = (static_root / "styles.css").read_text(encoding="utf-8")

        self.assertIn("databaseCatalogMenuItem", html)
        self.assertIn("openProfileModal('database')", js)
        self.assertIn("loadDatabaseCatalog", js)
        self.assertIn("/database/catalog", js)
        self.assertIn("renderDatabaseCatalog", js)
        self.assertIn("database-catalog-panel", js)
        self.assertIn("visible_databases", js)
        self.assertIn("visible_tools", js)
        self.assertIn("safe_sql_kernel", js)
        self.assertIn("write_operations_enabled", js)
        self.assertIn("confirmation_required_for", js)
        self.assertIn(".database-catalog-panel", css)
        self.assertIn(".database-catalog-grid", css)
        self.assertIn(".database-catalog-table-row", css)

    def test_chat_frontend_exposes_document_manager_baseline(self):
        static_root = Path(__file__).resolve().parents[1] / "static"
        html = (static_root / "index.html").read_text(encoding="utf-8")
        js = (static_root / "app.js").read_text(encoding="utf-8")
        css = (static_root / "styles.css").read_text(encoding="utf-8")

        self.assertIn("fileManagerMenuItem", html)
        self.assertIn("openProfileModal('documents')", js)
        self.assertIn("documentPagination", js)
        self.assertIn("loadDocuments", js)
        self.assertIn("/documents?page=", js)
        self.assertIn("renderDocumentManager", js)
        self.assertIn("documentStatusLabel", js)
        self.assertIn("documentStatusTone", js)
        self.assertIn("documentHealthLabel", js)
        self.assertIn("documentHealthTone", js)
        self.assertIn("showDocumentHealthDetails", js)
        self.assertIn("markDocumentHealthFalsePositive", js)
        self.assertIn("/documents/${encodeURIComponent(docId)}/health", js)
        self.assertIn("健康度", js)
        self.assertIn("isDocumentTerminal", js)
        self.assertIn("setInterval(() => this.loadDocuments({ silent: true }), 10000)", js)
        self.assertIn("error_message", js)
        self.assertIn(".document-manager-panel", css)
        self.assertIn(".document-manager-table", css)
        self.assertIn(".document-status-badge", css)
        self.assertIn(".document-health-badge", css)
        self.assertIn(".document-health-details", css)

    def test_stage5_admin_console_exposes_permission_request_review_queue(self):
        static_root = Path(__file__).resolve().parents[1] / "static"
        html = (static_root / "admin-console.html").read_text(encoding="utf-8")
        js = (static_root / "admin-console.js").read_text(encoding="utf-8")

        self.assertIn("{ key: 'permission-requests', label: '权限申请' }", js)
        self.assertIn("permissionRequestSummary", js)
        self.assertIn("permissionRequestDecisionReasons", js)
        self.assertIn("loadPermissionRequests", js)
        self.assertIn("/admin/permission-requests", js)
        self.assertIn("approvePermissionRequest", js)
        self.assertIn("rejectPermissionRequest", js)
        self.assertIn("canApprovePermissionRequest", js)
        self.assertIn("permission_request_requires_global_review", js)
        self.assertIn("route === 'permission-requests'", html)
        self.assertIn("requires_global_review", html)
        self.assertIn("pending_count", html)

    def test_admin_console_exposes_trace_timeline_viewer(self):
        static_root = Path(__file__).resolve().parents[1] / "static"
        html = (static_root / "admin-console.html").read_text(encoding="utf-8")
        js = (static_root / "admin-console.js").read_text(encoding="utf-8")
        css = (static_root / "admin-console.css").read_text(encoding="utf-8")

        self.assertIn("'trace'", js)
        self.assertIn("{ key: 'trace', label: 'Trace' }", js)
        self.assertIn("traceTimeline", js)
        self.assertIn("loadTraceTimeline", js)
        self.assertIn("/admin/traces/", js)
        self.assertIn("traceFilters", js)
        self.assertIn("filteredTraceTimeline", js)
        self.assertIn("traceCompareEnabled", js)
        self.assertIn("traceComparison", js)
        self.assertIn("loadTraceComparison", js)
        self.assertIn("copyTraceJson", js)
        self.assertIn("copyTraceId", js)
        self.assertIn("request_id", html)
        self.assertIn("tool", html)
        self.assertIn("database", html)
        self.assertIn("memory", html)
        self.assertIn("sse", html)
        self.assertIn("trace-timeline-panel", html)
        self.assertIn("route === 'trace'", html)
        self.assertIn("timelineItemTone", js)
        self.assertIn("not_recorded", html)
        self.assertIn("trace-comparison-panel", html)
        self.assertIn(".trace-filter-row", css)
        self.assertIn(".trace-comparison-panel", css)
        self.assertIn(".trace-timeline-panel", css)
        self.assertIn(".trace-timeline-item", css)

    def test_admin_console_exposes_memory_operator_ui(self):
        static_root = Path(__file__).resolve().parents[1] / "static"
        html = (static_root / "admin-console.html").read_text(encoding="utf-8")
        js = (static_root / "admin-console.js").read_text(encoding="utf-8")
        css = (static_root / "admin-console.css").read_text(encoding="utf-8")
        memory_decision_method = js.split("async decideMemory(memory, decision)", 1)[1].split(
            "async refreshCurrent", 1
        )[0]

        self.assertIn("'memory-operator'", js)
        self.assertIn("{ key: 'memory-operator', label: 'Memory Operator' }", js)
        self.assertIn("memoryOperator", js)
        self.assertIn("loadMemoryOperator", js)
        self.assertIn("loadMemoryReviewQueue", js)
        self.assertIn("loadMemoryValidationStatus", js)
        self.assertIn("previewMemoryDeprecation", js)
        self.assertIn("decideMemory", js)
        self.assertIn("/admin/memory-operator/review-queue", js)
        self.assertIn("/admin/memory-operator/validation-status", js)
        self.assertIn("/admin/memory-operator/deprecation-preview", js)
        self.assertIn("/admin/memory-operator/atoms/", js)
        self.assertIn("body: JSON.stringify({ decision_note: note })", memory_decision_method)
        self.assertNotIn("reviewer_id", memory_decision_method)
        self.assertIn("route === 'memory-operator'", html)
        self.assertIn("Memory Operator", html)
        self.assertIn("⚠️ Memory 当前默认关闭（memory_mode=off），此界面仅供 operator review", html)
        self.assertIn("Review Queue", html)
        self.assertIn("Validation Status", html)
        self.assertIn("Deprecation Preview", html)
        self.assertIn("candidate_review_deadline", html)
        self.assertIn("records_to_deprecate", html)
        self.assertIn("Deprecation Preview 只读", html)
        self.assertIn("admin-tabs", html)
        self.assertIn(".admin-tabs", css)
        self.assertIn(".memory-operator-panel", css)

    def test_admin_console_exposes_database_catalog_browser(self):
        static_root = Path(__file__).resolve().parents[1] / "static"
        html = (static_root / "admin-console.html").read_text(encoding="utf-8")
        js = (static_root / "admin-console.js").read_text(encoding="utf-8")
        css = (static_root / "admin-console.css").read_text(encoding="utf-8")

        self.assertIn("'database-catalog'", js)
        self.assertIn("{ key: 'database-catalog', label: '数据库查看' }", js)
        self.assertIn("databaseCatalog", js)
        self.assertIn("loadDatabaseCatalog", js)
        self.assertIn("selectDatabaseCatalog", js)
        self.assertIn("selectDatabaseTable", js)
        self.assertIn("loadDatabaseSampleRows", js)
        self.assertIn("/database/catalog", js)
        self.assertIn("/tables/${encodeURIComponent(tableName)}/sample", js)
        self.assertIn("sample.columns", js)
        self.assertIn("sample.rows", js)
        self.assertIn("safe_sql_verified", js)
        self.assertIn("route === 'database-catalog'", html)
        self.assertIn("此界面只展示 sandbox/database-demo/已授权 MySQL allowlist", html)
        self.assertIn("Authorized Columns", html)
        self.assertIn("selectedDatabaseColumns", html)
        self.assertIn("Sample Rows", html)
        self.assertIn("databaseCatalog.sampleColumns", html)
        self.assertIn("databaseCatalog.sampleRows", html)
        self.assertIn("未授权列不显示", html)
        self.assertIn(".database-catalog-layout", css)
        self.assertIn(".database-catalog-panel", css)
        self.assertIn(".database-catalog-section", css)

    def test_chat_history_uses_authenticated_user_scoped_storage_key(self):
        static_root = Path(__file__).resolve().parents[1] / "static"
        js = (static_root / "app.js").read_text(encoding="utf-8")
        clear_auth_state = js.split("clearAuthState(showMessage = true) {", 1)[1].split(
            "async openProfileModal", 1
        )[0]

        self.assertIn("getChatHistoryStorageKey", js)
        self.assertIn("loadServerChatHistories", js)
        self.assertIn("/chat/sessions", js)
        self.assertIn("server sessions failed, using local cache", js)
        self.assertIn("`chatHistories:${userId}`", js)
        self.assertIn("localStorage.getItem(storageKey)", js)
        self.assertIn("localStorage.setItem(storageKey", js)
        self.assertNotIn("localStorage.getItem('chatHistories')", js)
        self.assertNotIn("localStorage.setItem('chatHistories'", js)
        self.assertIn("this.currentChatHistory = [];", clear_auth_state)
        self.assertIn("this.sessionId = this.generateSessionId();", clear_auth_state)
        self.assertIn("this.chatMessages.innerHTML = '';", clear_auth_state)

    def test_documents_endpoint_returns_p0a_file_management_contract(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            created_at = datetime(2026, 6, 13, 9, 0, 0)
            updated_at = datetime(2026, 6, 13, 9, 5, 0)
            metadata_store.upsert_document(
                _document("doc-guide", "guide", "guide.md", root).model_copy(
                    update={"created_at": created_at, "updated_at": updated_at}
                )
            )
            metadata_store.upsert_document(_document("doc-hidden", "secret", "secret.md", root))
            metadata_store.upsert_document(
                _document(
                    "doc-pending",
                    "guide",
                    "pending.md",
                    root,
                    status=DocumentStatus.PARSE_PENDING,
                ).model_copy(
                    update={
                        "created_at": created_at,
                        "updated_at": updated_at,
                        "status_detail": "等待解析",
                        "status_evidence": {"trace_id": "trace-pending"},
                    }
                )
            )
            metadata_store.upsert_document(
                _document(
                    "doc-failed",
                    "guide",
                    "failed.md",
                    root,
                    status=DocumentStatus.INDEX_FAILED,
                ).model_copy(
                    update={
                        "created_at": created_at,
                        "updated_at": updated_at,
                        "error_message": "index failed",
                    }
                )
            )
            _grant_document("doc-guide")
            _grant_document("doc-pending")
            _grant_document("doc-failed")
            health_store = DocumentHealthCheckStore(root / "health.json")
            health_store.upsert(
                DocumentHealthCheckResult(
                    doc_id="doc-guide",
                    kb_id="guide",
                    status=DocumentHealthStatus.PASSED,
                    summary="all diagnostics passed",
                    retrieval={"passed": True, "queries": []},
                    source_ref={"passed": True, "errors": []},
                    pdf={"passed": True, "skipped": "not a PDF", "errors": []},
                    checked_at=updated_at,
                )
            )

            client = TestClient(_build_app())
            token = self._login(client)

            with patch.object(file_api.document_access_service, "metadata_store", metadata_store):
                with patch.object(file_api, "document_health_check_store", health_store):
                    response = client.get(
                        "/api/documents?page=1&limit=20",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    pending_response = client.get(
                        "/api/documents?status=parse_pending&page=1&limit=20",
                        headers={"Authorization": f"Bearer {token}"},
                    )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        documents = data["documents"]
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["limit"], 20)
        self.assertEqual(data["offset"], 0)
        self.assertEqual(data["total"], 3)
        self.assertEqual({document["doc_id"] for document in documents}, {"doc-guide", "doc-pending", "doc-failed"})
        pending = next(document for document in documents if document["doc_id"] == "doc-pending")
        self.assertEqual(pending["id"], "doc-pending")
        self.assertEqual(pending["filename"], "pending.md")
        self.assertEqual(pending["file_name"], "pending.md")
        self.assertEqual(pending["kb_id"], "guide")
        self.assertEqual(pending["status"], "parse_pending")
        self.assertEqual(pending["uploaded_at"], "2026-06-13T09:00:00")
        self.assertEqual(pending["updated_at"], "2026-06-13T09:05:00")
        self.assertEqual(pending["trace_id"], "trace-pending")
        self.assertEqual(pending["error_message"], "")
        guide = next(document for document in documents if document["doc_id"] == "doc-guide")
        self.assertEqual(guide["health_check"]["status"], "passed")
        self.assertEqual(guide["health_check"]["summary"], "all diagnostics passed")
        self.assertEqual(guide["health_check"]["checked_at"], "2026-06-13T09:05:00")

        self.assertEqual(pending_response.status_code, 200, pending_response.text)
        pending_data = pending_response.json()["data"]
        self.assertEqual(pending_data["page"], 1)
        self.assertEqual(pending_data["limit"], 20)
        self.assertEqual(pending_data["total"], 1)
        self.assertEqual([document["doc_id"] for document in pending_data["documents"]], ["doc-pending"])

    def test_upload_auto_grant_makes_uploader_document_visible_without_kb_scope(self):
        from app.enterprise.adapters.upload_adapter import UploadAdapter
        from app.services import document_ingestion_service as ingestion_module

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            upload_root = root / "uploads"
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            metadata_store.upsert_document(_document("doc-other", "default", "other.md", root))
            health_store = DocumentHealthCheckStore(root / "health.json")
            fake_indexer = type(
                "FakeIndexer",
                (),
                {
                    "index_document_record": lambda _self, record: ingestion_module.knowledge_metadata_store.transition_document_status(
                        record.doc_id,
                        DocumentStatus.INDEXED,
                        status_source="FakeIndexer.index_document_record",
                        status_detail="fake index complete",
                        status_evidence={"doc_id": record.doc_id},
                    )
                },
            )()
            ingestion_service = ingestion_module.DocumentIngestionService(upload_root=upload_root)
            upload_adapter = UploadAdapter(
                ingestion_service,
                max_file_size=1024,
                permission_service=permission_service,
            )

            client = TestClient(_build_app())
            token = self._login(client)

            original_store = ingestion_module.knowledge_metadata_store
            original_indexer = ingestion_module.vector_index_service
            ingestion_module.knowledge_metadata_store = metadata_store
            ingestion_module.vector_index_service = fake_indexer
            try:
                with patch.object(file_api, "upload_adapter", upload_adapter):
                    with patch.object(file_api.document_access_service, "metadata_store", metadata_store):
                        with patch.object(file_api, "document_health_check_store", health_store):
                            upload_response = client.post(
                                "/api/upload",
                                data={"kb_id": "default"},
                                files={"file": ("notes.md", b"# Title\n\nBody", "text/markdown")},
                                headers={"Authorization": f"Bearer {token}"},
                            )
                            self.assertEqual(upload_response.status_code, 200, upload_response.text)
                            uploaded_doc_id = upload_response.json()["data"]["doc_id"]
                            list_response = client.get(
                                "/api/documents?kb_id=default&status=indexed&page=1&limit=20",
                                headers={"Authorization": f"Bearer {token}"},
                            )
                            health_response = client.get(
                                f"/api/documents/{uploaded_doc_id}/health",
                                headers={"Authorization": f"Bearer {token}"},
                            )
                            hidden_health_response = client.get(
                                "/api/documents/doc-other/health",
                                headers={"Authorization": f"Bearer {token}"},
                            )
            finally:
                ingestion_module.knowledge_metadata_store = original_store
                ingestion_module.vector_index_service = original_indexer

            document_grants = permission_service.repository.list_all_grants(
                resource_type="document",
                resource_id=uploaded_doc_id,
                action="read",
                principal_type=PrincipalType.USER,
                principal_id="user_demo_dept1",
            )
            kb_grants = permission_service.repository.list_all_grants(
                resource_type="knowledge_base",
                resource_id="default",
                action="read",
                principal_type=PrincipalType.USER,
                principal_id="user_demo_dept1",
            )

        self.assertEqual(upload_response.status_code, 200, upload_response.text)
        self.assertEqual(list_response.status_code, 200, list_response.text)
        documents = list_response.json()["data"]["documents"]
        self.assertEqual([document["doc_id"] for document in documents], [uploaded_doc_id])
        self.assertEqual(health_response.status_code, 200, health_response.text)
        self.assertEqual(hidden_health_response.status_code, 404)
        self.assertEqual(len(document_grants), 1)
        self.assertEqual(document_grants[0].reason, "document_uploader_auto_read")
        self.assertEqual(kb_grants, [])

    def test_document_health_api_returns_details_and_allows_false_positive_mark(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            health_store = DocumentHealthCheckStore(root / "health.json")
            metadata_store.upsert_document(_document("doc-guide", "guide", "guide.md", root))
            metadata_store.upsert_document(_document("doc-hidden", "secret", "secret.md", root))
            health_store.upsert(
                DocumentHealthCheckResult(
                    doc_id="doc-guide",
                    kb_id="guide",
                    status=DocumentHealthStatus.FAILED,
                    summary="retrieval_no_hit",
                    retrieval={
                        "passed": False,
                        "queries": [{"query": "guide", "hit": False, "rank": None}],
                    },
                    source_ref={"passed": True, "errors": []},
                    pdf={"passed": True, "skipped": "not a PDF", "errors": []},
                )
            )
            _grant_document("doc-guide")

            client = TestClient(_build_app())
            token = self._login(client)

            with patch.object(file_api.document_access_service, "metadata_store", metadata_store):
                with patch.object(file_api, "document_health_check_store", health_store):
                    response = client.get(
                        "/api/documents/doc-guide/health",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    mark_response = client.post(
                        "/api/documents/doc-guide/health/mark-false-positive",
                        json={"reason": "query wording too narrow"},
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    hidden_response = client.get(
                        "/api/documents/doc-hidden/health",
                        headers={"Authorization": f"Bearer {token}"},
                    )

            stored_document = metadata_store.get_document("doc-guide")

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["status"], "failed")
        self.assertFalse(data["retrieval"]["passed"])
        self.assertTrue(data["source_ref"]["passed"])
        self.assertEqual(data["pdf"]["skipped"], "not a PDF")

        self.assertEqual(mark_response.status_code, 200, mark_response.text)
        marked = mark_response.json()["data"]
        self.assertTrue(marked["marked_as_false_positive"])
        self.assertEqual(marked["false_positive_reason"], "query wording too narrow")
        self.assertEqual(stored_document.status, DocumentStatus.INDEXED)
        self.assertEqual(hidden_response.status_code, 404)

    def test_list_knowledge_documents_tool_returns_visible_indexed_documents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            metadata_store.upsert_document(
                _document("doc-runbook", "guide", "enterprise_guide_runbook.md", root)
            )
            metadata_store.upsert_document(_document("doc-hidden", "secret", "secret.md", root))
            _grant_document("doc-runbook")
            context_token = set_current_request_context(_context())
            try:
                import app.tools.knowledge_tool as knowledge_tool_module

                with patch.object(
                    knowledge_tool_module.document_access_service,
                    "metadata_store",
                    metadata_store,
                ):
                    payload = knowledge_tool_module.list_knowledge_documents.func()
                    denied = knowledge_tool_module.list_knowledge_documents.func(kb_id="secret")
            finally:
                reset_current_request_context(context_token)

        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["documents"][0]["file_name"], "enterprise_guide_runbook.md")
        self.assertEqual(payload["kb_ids"], ["guide"])
        self.assertEqual(denied["total"], 0)
        self.assertIn("没有权限", denied["message"])

    def test_retrieve_knowledge_accepts_file_name_and_doc_id_filters(self):
        response = RetrievalResponse(
            query=RetrievalQuery(query="runbook", top_k=5, document_ids=["doc-runbook"]),
            results=[],
            context_text="没有找到相关信息。",
        )

        class FakeRetrievalService:
            def __init__(self):
                self.calls = []

            def retrieve(self, query, *, allowed_document_ids=None):
                self.calls.append((query, allowed_document_ids))
                return response.model_copy(update={"query": query})

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            metadata_store.upsert_document(
                _document("doc-runbook", "guide", "enterprise_guide_runbook.md", root)
            )
            fake_service = FakeRetrievalService()

            import app.tools.knowledge_tool as knowledge_tool_module

            with patch.object(
                knowledge_tool_module.document_access_service,
                "metadata_store",
                metadata_store,
            ), patch.object(knowledge_tool_module, "retrieval_service", fake_service):
                _content, artifact = knowledge_tool_module.retrieve_knowledge.func(
                    "runbook",
                    file_name="enterprise_guide_runbook",
                    top_k=5,
                )

        self.assertEqual(len(fake_service.calls), 1)
        query, allowed_document_ids = fake_service.calls[0]
        self.assertEqual(query.document_ids, ["doc-runbook"])
        self.assertEqual(query.top_k, 5)
        self.assertEqual(allowed_document_ids, ["doc-runbook"])
        self.assertEqual(artifact["query"]["document_ids"], ["doc-runbook"])


if __name__ == "__main__":
    unittest.main()
