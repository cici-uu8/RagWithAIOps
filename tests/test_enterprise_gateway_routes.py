import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.aiops as aiops_api
import app.api.auth as auth_api
import app.api.chat as chat_api
import app.api.file as file_api
import app.services.aiops_service as aiops_service_module
from app.enterprise.aiops.tool_catalog import AIOpsToolCatalog
from app.enterprise.auth.service import auth_service
from app.enterprise.gateway.guardrail_providers import NoOpGuardrailProvider, RuleGuardrailProvider
from app.enterprise.gateway.guardrail_service import GuardrailService
from app.enterprise.gateway.rate_limit_service import NoOpRateLimitService
from app.enterprise.gateway.request_gateway import RequestGateway
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.session_ownership import session_ownership_service
from app.enterprise.sessions.repository import (
    InMemoryChatSessionRepository,
    SQLiteChatSessionRepository,
)
from app.enterprise.sessions.service import SessionAccess
from app.models import DocumentRecord, DocumentStatus, ParserEngine


def build_enterprise_test_gateway(provider=None):
    sink = InMemoryAuditSink()
    gateway = RequestGateway(
        audit_service=AuditService(sinks=[sink]),
        guardrail_service=GuardrailService(providers=[provider or NoOpGuardrailProvider()]),
        rate_limit_service=NoOpRateLimitService(),
    )
    return gateway, sink


def build_route_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    app.include_router(chat_api.router, prefix="/api")
    app.include_router(file_api.router, prefix="/api")
    app.include_router(aiops_api.router, prefix="/api")
    return app


class EnterpriseGatewayRouteTests(unittest.TestCase):
    def setUp(self):
        auth_service.reset_users()
        auth_service.clear_blacklist()
        session_ownership_service.clear()
        chat_api.session_access = SessionAccess()
        aiops_api.session_access = SessionAccess()

    def tearDown(self):
        gateway, _sink = build_enterprise_test_gateway()
        chat_api.chat_adapter.gateway = gateway
        file_api.upload_adapter.gateway = gateway
        aiops_api.aiops_adapter.gateway = gateway
        chat_api.session_access = SessionAccess()
        aiops_api.session_access = SessionAccess()
        session_ownership_service.clear()

    def _auth_headers(
        self,
        client: TestClient,
        *,
        username: str = "demo_user_dept1",
        trace_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, str]:
        password = "Demo123!" if username == "demo_user_dept1" else "Admin123!"
        response = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        headers = {"Authorization": f"Bearer {response.json()['data']['access_token']}"}
        if trace_id:
            headers["X-Trace-Id"] = trace_id
        if request_id:
            headers["X-Request-Id"] = request_id
        return headers

    def test_chat_upload_and_aiops_success_share_header_trace_id_and_audit(self):
        gateway, sink = build_enterprise_test_gateway()
        chat_api.chat_adapter.gateway = gateway
        file_api.upload_adapter.gateway = gateway
        aiops_api.aiops_adapter.gateway = gateway

        with tempfile.TemporaryDirectory() as tmpdir:
            upload_dir = Path(tmpdir) / "uploads"
            saved_path = upload_dir / "documents" / "default" / "doc_e2" / "original" / "notes.md"
            artifact_dir = upload_dir / "documents" / "default" / "doc_e2" / "artifacts"

            def fake_ingest_upload(filename: str, content: bytes, kb_id: str):
                saved_path.parent.mkdir(parents=True, exist_ok=True)
                artifact_dir.mkdir(parents=True, exist_ok=True)
                saved_path.write_bytes(content)
                return DocumentRecord(
                    doc_id="doc_e2",
                    kb_id=kb_id,
                    file_name=filename,
                    file_ext="md",
                    original_path=str(saved_path),
                    artifact_dir=str(artifact_dir),
                    parser_engine=ParserEngine.PLAIN_TEXT,
                    status=DocumentStatus.INDEXED,
                )

            async def fake_diagnose(**_kwargs):
                yield {"type": "complete", "stage": "done", "message": "ok"}

            with patch.object(
                chat_api.rag_agent_service,
                "query",
                new=AsyncMock(return_value="chat ok"),
            ), patch.object(
                file_api.document_ingestion_service,
                "ingest_upload",
                fake_ingest_upload,
            ), patch.object(
                aiops_api.aiops_service,
                "diagnose",
                fake_diagnose,
            ):
                client = TestClient(build_route_app())
                headers = self._auth_headers(
                    client,
                    trace_id="trace-route-success",
                    request_id="request-route-success",
                )

                chat_response = client.post(
                    "/api/chat",
                    json={"Id": "session-e2", "Question": "hello"},
                    headers=headers,
                )
                upload_response = client.post(
                    "/api/upload",
                    files={"file": ("notes.md", b"# title", "text/markdown")},
                    data={"kb_id": "default"},
                    headers=headers,
                )
                aiops_response = client.post(
                    "/api/aiops",
                    json={"session_id": "session-e2"},
                    headers=headers,
                )

        self.assertEqual(chat_response.status_code, 200, chat_response.text)
        self.assertEqual(upload_response.status_code, 200, upload_response.text)
        self.assertEqual(aiops_response.status_code, 200, aiops_response.text)
        self.assertEqual(chat_response.json()["data"]["trace_id"], "trace-route-success")
        self.assertEqual(upload_response.json()["data"]["trace_id"], "trace-route-success")
        self.assertIn("trace-route-success", aiops_response.text)
        self.assertIn("request-route-success", aiops_response.text)

        completed_routes = [
            event.route
            for event in sink.events
            if event.event_type == "request_completed"
        ]
        self.assertEqual(completed_routes, ["chat", "upload", "aiops"])
        self.assertTrue(all(event.trace_id == "trace-route-success" for event in sink.events))

    def test_rule_guardrail_blocks_chat_route_and_writes_audit(self):
        gateway, sink = build_enterprise_test_gateway(
            RuleGuardrailProvider.from_keywords(["删除日志"], reason="禁止删除日志操作")
        )
        chat_api.chat_adapter.gateway = gateway
        client = TestClient(build_route_app())

        response = client.post(
            "/api/chat",
            json={"Id": "session-e2", "Question": "请删除日志"},
            headers=self._auth_headers(client, trace_id="trace-route-blocked"),
        )

        self.assertEqual(response.status_code, 403)
        payload = response.json()
        self.assertEqual(payload["message"], "blocked")
        self.assertEqual(payload["data"]["trace_id"], "trace-route-blocked")
        self.assertEqual(sink.events[-1].error_class, "guardrail_blocked")
        self.assertEqual(sink.events[-1].decision, "blocked")
        self.assertEqual(sink.events[-1].metadata["recovery_decision"], "abort")

    def test_chat_stream_success_uses_gateway_trace_and_audit(self):
        gateway, sink = build_enterprise_test_gateway()
        chat_api.chat_adapter.gateway = gateway

        async def fake_query_stream(*_args, **_kwargs):
            yield {"type": "content", "data": "hello"}
            yield {"type": "complete", "data": {"answer": "hello"}}

        with patch.object(chat_api.rag_agent_service, "query_stream", fake_query_stream):
            client = TestClient(build_route_app())
            response = client.post(
                "/api/chat_stream",
                json={"Id": "session-e2-stream", "Question": "hello"},
                headers=self._auth_headers(
                    client,
                    trace_id="trace-stream-success",
                    request_id="request-stream-success",
                ),
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("trace-stream-success", response.text)
        self.assertIn("request-stream-success", response.text)
        completed = [
            event
            for event in sink.events
            if event.event_type == "request_completed"
        ]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].route, "chat_stream")
        self.assertEqual(completed[0].trace_id, "trace-stream-success")

    def test_rule_guardrail_blocks_chat_stream_and_writes_audit(self):
        gateway, sink = build_enterprise_test_gateway(
            RuleGuardrailProvider.from_keywords(["删除日志"], reason="禁止删除日志操作")
        )
        chat_api.chat_adapter.gateway = gateway
        client = TestClient(build_route_app())

        response = client.post(
            "/api/chat_stream",
            json={"Id": "session-e2-stream", "Question": "请删除日志"},
            headers=self._auth_headers(
                client,
                trace_id="trace-stream-blocked",
                request_id="request-stream-blocked",
            ),
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("blocked", response.text)
        self.assertIn("trace-stream-blocked", response.text)
        self.assertIn("request-stream-blocked", response.text)
        self.assertEqual(sink.events[-1].route, "chat_stream")
        self.assertEqual(sink.events[-1].error_class, "guardrail_blocked")
        self.assertEqual(sink.events[-1].decision, "blocked")
        self.assertEqual(sink.events[-1].metadata["recovery_decision"], "abort")

    def test_upload_failure_writes_failed_audit_without_stack_trace(self):
        gateway, sink = build_enterprise_test_gateway()
        file_api.upload_adapter.gateway = gateway
        client = TestClient(build_route_app())

        def boom(*_args, **_kwargs):
            raise RuntimeError("boom with secret stack details")

        with patch.object(file_api.document_ingestion_service, "ingest_upload", boom):
            response = client.post(
                "/api/upload",
                files={"file": ("notes.md", b"# title", "text/markdown")},
                data={"kb_id": "default"},
                headers={"X-Trace-Id": "trace-route-failed"},
            )

        self.assertEqual(response.status_code, 500)
        failed = sink.events[-1]
        self.assertEqual(failed.event_type, "request_failed")
        self.assertEqual(failed.route, "upload")
        self.assertEqual(failed.error_class, "tool_failed")
        self.assertEqual(failed.metadata["source_error_class"], "RuntimeError")
        self.assertEqual(failed.metadata["recovery_decision"], "abort")
        self.assertNotIn("secret", json.dumps(failed.model_dump(mode="json"), ensure_ascii=False))

    def test_chat_session_history_and_clear_require_current_session_owner(self):
        gateway, sink = build_enterprise_test_gateway()
        chat_api.chat_adapter.gateway = gateway

        client = TestClient(build_route_app())
        owner_headers = self._auth_headers(client, username="demo_user_dept1")
        admin_headers = self._auth_headers(client, username="admin")

        with patch.object(
            chat_api.rag_agent_service,
            "query",
            new=AsyncMock(return_value="owner answer"),
        ), patch.object(
            chat_api.rag_agent_service,
            "get_session_history",
            return_value=[],
        ), patch.object(
            chat_api.rag_agent_service,
            "clear_session",
            return_value=True,
        ):
            claim_response = client.post(
                "/api/chat",
                json={"Id": "session-owned-by-demo", "Question": "hello"},
                headers=owner_headers,
            )
            owner_get_response = client.get(
                "/api/chat/session/session-owned-by-demo",
                headers=owner_headers,
            )
            admin_get_response = client.get(
                "/api/chat/session/session-owned-by-demo",
                headers=admin_headers,
            )
            admin_clear_response = client.post(
                "/api/chat/clear",
                json={"session_id": "session-owned-by-demo"},
                headers=admin_headers,
            )
            admin_write_response = client.post(
                "/api/chat",
                json={"Id": "session-owned-by-demo", "Question": "pollute"},
                headers=admin_headers,
            )
            admin_stream_response = client.post(
                "/api/chat_stream",
                json={"Id": "session-owned-by-demo", "Question": "pollute"},
                headers=admin_headers,
            )

        self.assertEqual(claim_response.status_code, 200, claim_response.text)
        self.assertEqual(owner_get_response.status_code, 200, owner_get_response.text)
        self.assertEqual(admin_get_response.status_code, 403, admin_get_response.text)
        self.assertEqual(admin_clear_response.status_code, 403, admin_clear_response.text)
        self.assertEqual(admin_write_response.status_code, 403, admin_write_response.text)
        self.assertEqual(admin_stream_response.status_code, 403, admin_stream_response.text)
        denied_permissions = [
            event for event in sink.events if event.event_type == "permission_checked"
        ]
        self.assertEqual(len(denied_permissions), 4)
        self.assertEqual({event.decision for event in denied_permissions}, {"denied"})
        self.assertEqual(
            {event.metadata["action"] for event in denied_permissions},
            {"read", "clear", "write"},
        )
        self.assertTrue(
            all(
                event.metadata["denial_reason"] == "session_owner_mismatch"
                for event in denied_permissions
            )
        )

    def test_chat_clear_uses_gateway_and_writes_request_audit(self):
        gateway, sink = build_enterprise_test_gateway()
        chat_api.chat_adapter.gateway = gateway

        client = TestClient(build_route_app())
        owner_headers = self._auth_headers(
            client,
            username="demo_user_dept1",
            trace_id="trace-clear-session",
            request_id="request-clear-session",
        )

        with patch.object(
            chat_api.rag_agent_service,
            "query",
            new=AsyncMock(return_value="owner answer"),
        ), patch.object(
            chat_api.rag_agent_service,
            "clear_session",
            return_value=True,
        ):
            claim_response = client.post(
                "/api/chat",
                json={"Id": "session-clear-gateway", "Question": "hello"},
                headers=owner_headers,
            )
            clear_response = client.post(
                "/api/chat/clear",
                json={"session_id": "session-clear-gateway"},
                headers=owner_headers,
            )

        self.assertEqual(claim_response.status_code, 200, claim_response.text)
        self.assertEqual(clear_response.status_code, 200, clear_response.text)
        clear_completed = [
            event
            for event in sink.events
            if event.event_type == "request_completed"
            and event.route == "chat_clear"
        ]
        self.assertEqual(len(clear_completed), 1)
        self.assertEqual(clear_completed[0].trace_id, "trace-clear-session")
        self.assertEqual(clear_completed[0].request_id, "request-clear-session")

    def test_aiops_default_session_is_scoped_to_authenticated_user(self):
        captured_session_ids: list[str] = []

        async def fake_diagnose(**kwargs):
            captured_session_ids.append(kwargs["session_id"])
            yield {"type": "complete", "stage": "done", "message": "ok"}

        gateway, sink = build_enterprise_test_gateway()
        aiops_api.aiops_adapter.gateway = gateway
        client = TestClient(build_route_app())

        with patch.object(aiops_api.aiops_service, "diagnose", fake_diagnose):
            owner_headers = self._auth_headers(client, username="demo_user_dept1")
            response = client.post(
                "/api/aiops",
                json={},
                headers=owner_headers,
            )
            other_user_response = client.post(
                "/api/aiops",
                json={"session_id": "aiops:user_demo_dept1:default"},
                headers=self._auth_headers(client, username="admin"),
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(other_user_response.status_code, 403, other_user_response.text)
        self.assertEqual(captured_session_ids, ["aiops:user_demo_dept1:default"])
        denied_permissions = [
            event for event in sink.events if event.event_type == "permission_checked"
        ]
        self.assertEqual(len(denied_permissions), 1)
        self.assertEqual(denied_permissions[0].decision, "denied")
        self.assertEqual(denied_permissions[0].metadata["denial_reason"], "session_owner_mismatch")

    def test_aiops_failure_semantics_event_is_audited(self):
        async def fake_diagnose(**_kwargs):
            yield {
                "type": "status",
                "stage": "replanner",
                "message": "fallback recovered",
                "structured_output_recovered": True,
                "failure_semantics": "structured_output_recovered",
                "failure_semantics_hard_failure": False,
            }
            yield {
                "type": "complete",
                "stage": "done",
                "message": "ok",
                "diagnosis": {"status": "completed", "report": "ok"},
            }

        gateway, sink = build_enterprise_test_gateway()
        aiops_api.aiops_adapter.gateway = gateway
        client = TestClient(build_route_app())

        with patch.object(aiops_api.aiops_service, "diagnose", fake_diagnose):
            response = client.post(
                "/api/aiops",
                json={"session_id": "aiops:semantics"},
                headers=self._auth_headers(
                    client,
                    username="demo_user_dept1",
                    trace_id="trace-aiops-semantics-route",
                    request_id="request-aiops-semantics-route",
                ),
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("structured_output_recovered", response.text)
        degradation_events = [
            event for event in sink.events if event.event_type == "aiops_degradation"
        ]
        self.assertEqual(len(degradation_events), 1)
        self.assertEqual(degradation_events[0].decision, "degraded")
        self.assertEqual(
            degradation_events[0].metadata["failure_semantics"],
            "structured_output_recovered",
        )
        self.assertFalse(degradation_events[0].metadata["failure_semantics_hard_failure"])

    def test_aiops_recovered_infra_error_is_audited_as_degradation(self):
        async def fake_diagnose(**_kwargs):
            yield {
                "type": "step_complete",
                "stage": "step_executed",
                "message": "transient executor failure",
                "infra_error": True,
                "failure_semantics": "infra_error",
                "failure_semantics_hard_failure": True,
            }
            yield {
                "type": "complete",
                "stage": "diagnosis_complete",
                "message": "diagnosis complete",
                "diagnosis": {"status": "completed", "report": "RedisQueueBacklog final report"},
                "failure_semantics": "recovered_infra_error",
                "failure_semantics_hard_failure": False,
            }

        gateway, sink = build_enterprise_test_gateway()
        aiops_api.aiops_adapter.gateway = gateway
        client = TestClient(build_route_app())

        with patch.object(aiops_api.aiops_service, "diagnose", fake_diagnose):
            response = client.post(
                "/api/aiops",
                json={"session_id": "aiops:recovered-infra"},
                headers=self._auth_headers(
                    client,
                    username="demo_user_dept1",
                    trace_id="trace-aiops-recovered-infra-route",
                    request_id="request-aiops-recovered-infra-route",
                ),
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("infra_error", response.text)
        self.assertIn("recovered_infra_error", response.text)
        self.assertIn('"failure_semantics_hard_failure": false', response.text)
        hard_failures = [event for event in sink.events if event.event_type == "aiops_failure"]
        self.assertEqual(len(hard_failures), 1)
        self.assertEqual(hard_failures[0].reason, "infra_error")
        degradations = [event for event in sink.events if event.event_type == "aiops_degradation"]
        self.assertEqual(len(degradations), 1)
        self.assertEqual(degradations[0].reason, "recovered_infra_error")
        self.assertFalse(degradations[0].metadata["failure_semantics_hard_failure"])

    def test_aiops_runtime_missing_required_tool_fails_before_planner(self):
        async def execute_should_not_run(*_args, **_kwargs):
            raise AssertionError("planner should not run when required tools are missing")
            yield {}

        missing_tool_catalog = AIOpsToolCatalog(
            mcp_tool_loader=lambda: _async_tools([]),
        )

        gateway, sink = build_enterprise_test_gateway()
        aiops_api.aiops_adapter.gateway = gateway
        client = TestClient(build_route_app())

        with patch.object(
            aiops_api.aiops_service,
            "execute",
            execute_should_not_run,
        ), patch.object(
            aiops_service_module,
            "aiops_tool_catalog",
            missing_tool_catalog,
            create=True,
        ):
            response = client.post(
                "/api/aiops",
                json={
                    "session_id": "aiops:missing-required-tool",
                    "query": "CPUHigh alert on data-sync-service",
                },
                headers=self._auth_headers(
                    client,
                    username="demo_user_dept1",
                    trace_id="trace-aiops-missing-required-tool",
                    request_id="request-aiops-missing-required-tool",
                ),
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("missing_required_tool", response.text)
        self.assertIn('"failure_semantics_hard_failure": true', response.text)
        self.assertIn("query_active_alerts", response.text)
        self.assertTrue(
            any(
                event.event_type == "aiops_tool_validation"
                and event.decision == "blocked"
                and event.reason == "missing_required_tool"
                and "query_active_alerts" in event.metadata["missing_required_tools"]
                for event in sink.events
            )
        )
        self.assertTrue(
            any(
                event.event_type == "aiops_failure"
                and event.reason == "missing_required_tool"
                and event.metadata["failure_semantics_hard_failure"] is True
                for event in sink.events
            )
        )

    def test_chat_sessions_persist_after_repository_reopen_and_are_owner_scoped(self):
        gateway, sink = build_enterprise_test_gateway()
        chat_api.chat_adapter.gateway = gateway

        with tempfile.TemporaryDirectory() as tmpdir:
            repository_path = Path(tmpdir) / "chat_sessions.sqlite"
            chat_api.session_access = SessionAccess(
                repository=SQLiteChatSessionRepository(repository_path),
                audit_service=gateway.audit_service,
            )
            client = TestClient(build_route_app())
            owner_headers = self._auth_headers(client, username="demo_user_dept1")

            with patch.object(
                chat_api.rag_agent_service,
                "query",
                new=AsyncMock(return_value="persisted answer"),
            ):
                response = client.post(
                    "/api/chat",
                    json={"Id": "session-persisted", "Question": "hello"},
                    headers=owner_headers,
                )

            self.assertEqual(response.status_code, 200, response.text)

            reopened_access = SessionAccess(
                repository=SQLiteChatSessionRepository(repository_path),
                audit_service=gateway.audit_service,
            )
            chat_api.session_access = reopened_access

            list_response = client.get("/api/chat/sessions", headers=owner_headers)
            messages_response = client.get(
                "/api/chat/session/session-persisted",
                headers=owner_headers,
            )
            other_user_response = client.get(
                "/api/chat/session/session-persisted",
                headers=self._auth_headers(client, username="admin"),
            )

        self.assertEqual(list_response.status_code, 200, list_response.text)
        sessions = list_response.json()["data"]["sessions"]
        self.assertEqual([session["session_id"] for session in sessions], ["session-persisted"])
        self.assertEqual(sessions[0]["title"], "hello")
        self.assertEqual(messages_response.status_code, 200, messages_response.text)
        self.assertEqual(messages_response.json()["message_count"], 2)
        self.assertEqual(
            [message["role"] for message in messages_response.json()["history"]],
            ["user", "assistant"],
        )
        self.assertEqual(other_user_response.status_code, 403, other_user_response.text)
        self.assertTrue(
            any(
                event.event_type == "permission_checked"
                and event.metadata.get("denial_reason") == "session_owner_mismatch"
                for event in sink.events
            )
        )

    def test_chat_stream_persists_final_assistant_message(self):
        gateway, _sink = build_enterprise_test_gateway()
        chat_api.chat_adapter.gateway = gateway

        async def fake_query_stream(*_args, **_kwargs):
            yield {"type": "content", "data": "hello "}
            yield {"type": "content", "data": "stream"}
            yield {"type": "complete", "data": {"answer": "hello stream"}}

        with tempfile.TemporaryDirectory() as tmpdir:
            repository_path = Path(tmpdir) / "chat_sessions.sqlite"
            chat_api.session_access = SessionAccess(
                repository=SQLiteChatSessionRepository(repository_path),
                audit_service=gateway.audit_service,
            )
            client = TestClient(build_route_app())
            owner_headers = self._auth_headers(client, username="demo_user_dept1")
            with patch.object(chat_api.rag_agent_service, "query_stream", fake_query_stream):
                response = client.post(
                    "/api/chat_stream",
                    json={"Id": "session-stream-persisted", "Question": "hello"},
                    headers=owner_headers,
                )
            messages_response = client.get(
                "/api/chat/session/session-stream-persisted",
                headers=owner_headers,
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(messages_response.status_code, 200, messages_response.text)
        history = messages_response.json()["history"]
        self.assertEqual([message["role"] for message in history], ["user", "assistant"])
        self.assertEqual(history[-1]["content"], "hello stream")

    def test_archived_chat_session_is_revived_by_same_owner_write(self):
        gateway, _sink = build_enterprise_test_gateway()
        chat_api.chat_adapter.gateway = gateway

        with tempfile.TemporaryDirectory() as tmpdir:
            repository_path = Path(tmpdir) / "chat_sessions.sqlite"
            chat_api.session_access = SessionAccess(
                repository=SQLiteChatSessionRepository(repository_path),
                audit_service=gateway.audit_service,
            )
            client = TestClient(build_route_app())
            owner_headers = self._auth_headers(client, username="demo_user_dept1")

            with patch.object(
                chat_api.rag_agent_service,
                "query",
                new=AsyncMock(side_effect=["first answer", "second answer"]),
            ), patch.object(
                chat_api.rag_agent_service,
                "clear_session",
                return_value=True,
            ):
                first_response = client.post(
                    "/api/chat",
                    json={"Id": "session-revived", "Question": "first"},
                    headers=owner_headers,
                )
                clear_response = client.post(
                    "/api/chat/clear",
                    json={"session_id": "session-revived"},
                    headers=owner_headers,
                )
                second_response = client.post(
                    "/api/chat",
                    json={"Id": "session-revived", "Question": "second"},
                    headers=owner_headers,
                )

            list_response = client.get("/api/chat/sessions", headers=owner_headers)
            messages_response = client.get(
                "/api/chat/session/session-revived",
                headers=owner_headers,
            )

        self.assertEqual(first_response.status_code, 200, first_response.text)
        self.assertEqual(clear_response.status_code, 200, clear_response.text)
        self.assertEqual(second_response.status_code, 200, second_response.text)
        self.assertEqual(list_response.status_code, 200, list_response.text)
        sessions = list_response.json()["data"]["sessions"]
        self.assertEqual([session["session_id"] for session in sessions], ["session-revived"])
        self.assertIsNone(sessions[0]["archived_at"])
        self.assertEqual(messages_response.status_code, 200, messages_response.text)
        history = messages_response.json()["history"]
        self.assertEqual([message["role"] for message in history], ["user", "assistant", "user", "assistant"])
        self.assertEqual(history[-2]["content"], "second")
        self.assertEqual(history[-1]["content"], "second answer")

    def test_chat_stream_persistence_failure_does_not_interrupt_sse(self):
        class FailingAppendRepository(InMemoryChatSessionRepository):
            def append_message(self, *_args, **_kwargs):
                raise RuntimeError("sqlite locked")

        gateway, sink = build_enterprise_test_gateway()
        chat_api.chat_adapter.gateway = gateway
        chat_api.session_access = SessionAccess(
            repository=FailingAppendRepository(),
            audit_service=gateway.audit_service,
        )

        async def fake_query_stream(*_args, **_kwargs):
            yield {"type": "content", "data": "still answers"}
            yield {"type": "complete", "data": {"answer": "still answers"}}

        client = TestClient(build_route_app())
        with patch.object(chat_api.rag_agent_service, "query_stream", fake_query_stream):
            response = client.post(
                "/api/chat_stream",
                json={"Id": "session-degraded-history", "Question": "hello"},
                headers=self._auth_headers(client, username="demo_user_dept1"),
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("still answers", response.text)
        self.assertTrue(
            any(
                event.event_type == "chat_session_persistence_degraded"
                and event.decision == "degraded"
                for event in sink.events
            )
        )

    def test_aiops_uses_persistent_session_owner_guard_after_reopen(self):
        async def fake_diagnose(**_kwargs):
            yield {"type": "report", "stage": "final_report", "report": "root cause"}
            yield {"type": "complete", "stage": "done", "message": "ok"}

        gateway, sink = build_enterprise_test_gateway()
        aiops_api.aiops_adapter.gateway = gateway

        with tempfile.TemporaryDirectory() as tmpdir:
            repository_path = Path(tmpdir) / "chat_sessions.sqlite"
            aiops_api.session_access = SessionAccess(
                repository=SQLiteChatSessionRepository(repository_path),
                audit_service=gateway.audit_service,
            )
            client = TestClient(build_route_app())
            owner_headers = self._auth_headers(client, username="demo_user_dept1")
            with patch.object(aiops_api.aiops_service, "diagnose", fake_diagnose):
                response = client.post(
                    "/api/aiops",
                    json={"session_id": "aiops:persistent"},
                    headers=owner_headers,
                )
            messages = aiops_api.session_access.repository.get_messages(
                "aiops:persistent",
                "user_demo_dept1",
            )

            aiops_api.session_access = SessionAccess(
                repository=SQLiteChatSessionRepository(repository_path),
                audit_service=gateway.audit_service,
            )
            other_user_response = client.post(
                "/api/aiops",
                json={"session_id": "aiops:persistent"},
                headers=self._auth_headers(client, username="admin"),
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([message.role for message in messages], ["user", "assistant"])
        self.assertEqual(messages[-1].content, "root cause")
        self.assertEqual(other_user_response.status_code, 403, other_user_response.text)
        self.assertTrue(
            any(
                event.event_type == "permission_checked"
                and event.route == "aiops"
                and event.metadata.get("denial_reason") == "session_owner_mismatch"
                for event in sink.events
            )
        )


async def _async_tools(tools):
    return tools


if __name__ == "__main__":
    unittest.main()
