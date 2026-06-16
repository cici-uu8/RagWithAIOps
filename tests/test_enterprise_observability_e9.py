import json
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.aiops as aiops_api
import app.api.auth as auth_api
import app.api.chat as chat_api
from app.enterprise.auth.service import auth_service
from app.enterprise.gateway.guardrail_providers import NoOpGuardrailProvider
from app.enterprise.gateway.guardrail_service import GuardrailService
from app.enterprise.gateway.rate_limit_service import NoOpRateLimitService
from app.enterprise.gateway.request_gateway import RequestGateway
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.observability.models import AuditEvent
from app.enterprise.observability.sse_contract import (
    REQUIRED_SSE_FIELDS,
    check_sse_contract,
    normalize_sse_event,
)
from app.enterprise.observability.trace_eval import (
    REQUIRED_TRACE_OBSERVATION_FIELDS,
    build_e9_observability_report,
    check_trace_completeness,
    localize_failure,
)
from app.enterprise.session_ownership import session_ownership_service


def build_enterprise_test_gateway():
    sink = InMemoryAuditSink()
    gateway = RequestGateway(
        audit_service=AuditService(sinks=[sink]),
        guardrail_service=GuardrailService(providers=[NoOpGuardrailProvider()]),
        rate_limit_service=NoOpRateLimitService(),
    )
    return gateway, sink


def build_route_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    app.include_router(chat_api.router, prefix="/api")
    app.include_router(aiops_api.router, prefix="/api")
    return app


def parse_sse_payloads(response_text: str) -> list[dict]:
    payloads: list[dict] = []
    for line in response_text.splitlines():
        if line.startswith("data: "):
            payloads.append(json.loads(line.removeprefix("data: ").strip()))
    return payloads


def audit_event(
    event_type: str,
    *,
    trace_id: str = "trace-e9",
    request_id: str = "request-e9",
    route: str = "chat",
    decision: str | None = "allowed",
    reason: str | None = None,
    error_class: str | None = None,
    latency_ms: float | None = None,
    metadata: dict | None = None,
) -> AuditEvent:
    return AuditEvent(
        event_type=event_type,
        route=route,
        trace_id=trace_id,
        request_id=request_id,
        user_id="user_e9",
        timestamp=datetime(2026, 5, 30, tzinfo=UTC),
        decision=decision,
        reason=reason,
        error_class=error_class,
        latency_ms=latency_ms,
        metadata=metadata or {},
    )


class EnterpriseSseContractE9Tests(unittest.TestCase):
    def setUp(self):
        auth_service.reset_users()
        auth_service.clear_blacklist()
        session_ownership_service.clear()

    def tearDown(self):
        gateway, _sink = build_enterprise_test_gateway()
        chat_api.chat_adapter.gateway = gateway
        aiops_api.aiops_adapter.gateway = gateway
        session_ownership_service.clear()

    def _auth_headers(
        self,
        client: TestClient,
        *,
        trace_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, str]:
        response = client.post(
            "/api/auth/login",
            json={"username": "demo_user_dept1", "password": "Demo123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        headers = {"Authorization": f"Bearer {response.json()['data']['access_token']}"}
        if trace_id:
            headers["X-Trace-Id"] = trace_id
        if request_id:
            headers["X-Request-Id"] = request_id
        return headers

    def test_normalizes_legacy_chat_and_aiops_events_to_complete_envelope(self):
        events = [
            normalize_sse_event(
                {
                    "type": "content",
                    "data": "hello",
                    "trace_id": "trace-e9-sse",
                    "request_id": "request-e9-sse",
                }
            ),
            normalize_sse_event(
                {
                    "type": "complete",
                    "data": {"answer": "done"},
                    "trace_id": "trace-e9-sse",
                    "request_id": "request-e9-sse",
                }
            ),
            normalize_sse_event(
                {
                    "type": "plan",
                    "stage": "plan_created",
                    "message": "plan ready",
                    "plan": ["check alerts"],
                    "trace_id": "trace-e9-aiops",
                    "request_id": "request-e9-aiops",
                }
            ),
        ]

        result = check_sse_contract(events, source="/api/e9-test")

        self.assertTrue(result.passed, result.issues)
        for event in events:
            self.assertTrue(REQUIRED_SSE_FIELDS.issubset(event))
            self.assertTrue(event["trace_id"])
            self.assertTrue(event["request_id"])
            self.assertTrue(event["stage"])
            self.assertTrue(event["status"])
            self.assertTrue(event["message"])
            self.assertIn("data", event)
        self.assertEqual(events[0]["stage"], "content")
        self.assertEqual(events[0]["status"], "running")
        self.assertEqual(events[1]["stage"], "done")
        self.assertEqual(events[1]["status"], "completed")
        self.assertEqual(events[2]["status"], "completed")

    def test_chat_stream_and_aiops_routes_emit_frozen_sse_contract_fields(self):
        gateway, _sink = build_enterprise_test_gateway()
        chat_api.chat_adapter.gateway = gateway
        aiops_api.aiops_adapter.gateway = gateway

        async def fake_query_stream(*_args, **_kwargs):
            yield {"type": "content", "data": "hello"}
            yield {"type": "complete", "data": {"answer": "hello"}}

        async def fake_diagnose(**_kwargs):
            yield {
                "type": "plan",
                "stage": "plan_created",
                "message": "plan ready",
                "plan": ["check alert"],
            }
            yield {
                "type": "report",
                "stage": "final_report",
                "message": "report ready",
                "report": "# report",
            }

        with patch.object(chat_api.rag_agent_service, "query_stream", fake_query_stream), patch.object(
            aiops_api.aiops_service,
            "diagnose",
            fake_diagnose,
        ):
            client = TestClient(build_route_app())
            headers = self._auth_headers(
                client,
                trace_id="trace-e9-routes",
                request_id="request-e9-routes",
            )
            chat_response = client.post(
                "/api/chat_stream",
                json={"Id": "session-e9-chat", "Question": "hello"},
                headers=headers,
            )
            aiops_response = client.post(
                "/api/aiops",
                json={"session_id": "session-e9-aiops"},
                headers=headers,
            )

        self.assertEqual(chat_response.status_code, 200, chat_response.text)
        self.assertEqual(aiops_response.status_code, 200, aiops_response.text)
        chat_events = parse_sse_payloads(chat_response.text)
        aiops_events = parse_sse_payloads(aiops_response.text)

        self.assertGreaterEqual(len(chat_events), 2)
        self.assertGreaterEqual(len(aiops_events), 2)
        self.assertTrue(check_sse_contract(chat_events, source="/api/chat_stream").passed)
        self.assertTrue(check_sse_contract(aiops_events, source="/api/aiops").passed)
        self.assertEqual(chat_events[-1]["stage"], "done")
        self.assertEqual(chat_events[-1]["status"], "completed")
        self.assertEqual(aiops_events[0]["data"]["plan"], ["check alert"])


class EnterpriseTraceEvalE9Tests(unittest.TestCase):
    def test_positive_smoke_traces_normalize_required_observability_fields(self):
        traces = {
            "chat": [
                audit_event("request_started", route="chat"),
                audit_event(
                    "permission_checked",
                    route="permission",
                    metadata={
                        "resource_type": "document",
                        "resource_id": "doc_a",
                        "action": "read",
                    },
                ),
                audit_event(
                    "rag_retrieval",
                    route="rag",
                    metadata={"result_count": 1, "status": "success"},
                ),
                audit_event(
                    "model_call",
                    route="model_gateway",
                    latency_ms=12.5,
                    metadata={"endpoint_id": "qwen-max", "status": "success"},
                ),
                audit_event("request_completed", route="chat", latency_ms=20.0),
            ],
            "aiops": [
                audit_event("request_started", trace_id="trace-aiops", request_id="request-aiops", route="aiops"),
                audit_event(
                    "tool_call",
                    trace_id="trace-aiops",
                    request_id="request-aiops",
                    route="tool_gateway",
                    latency_ms=3.0,
                    metadata={"tool_id": "aiops.search_logs", "status": "success"},
                ),
                audit_event(
                    "request_completed",
                    trace_id="trace-aiops",
                    request_id="request-aiops",
                    route="aiops",
                    latency_ms=30.0,
                ),
            ],
            "database": [
                audit_event("request_started", trace_id="trace-db", request_id="request-db", route="database_demo"),
                audit_event(
                    "database_query",
                    trace_id="trace-db",
                    request_id="request-db",
                    route="database_demo",
                    latency_ms=5.0,
                    metadata={"target_tables": ["orders"], "status": "success"},
                ),
                audit_event(
                    "request_completed",
                    trace_id="trace-db",
                    request_id="request-db",
                    route="database_demo",
                    latency_ms=8.0,
                ),
            ],
        }

        for smoke_name, events in traces.items():
            result = check_trace_completeness(events, trace_id=events[0].trace_id, smoke_name=smoke_name)
            self.assertTrue(result.passed, result.issues)
            self.assertGreaterEqual(len(result.observations), 2)
            for observation in result.observations:
                payload = observation.model_dump()
                self.assertTrue(REQUIRED_TRACE_OBSERVATION_FIELDS.issubset(payload))
                self.assertTrue(payload["layer"])
                self.assertTrue(payload["module"])
                self.assertTrue(payload["decision"])
                self.assertTrue(payload["reason"])
                self.assertIsInstance(payload["latency_ms"], float)
                self.assertTrue(payload["status"])

    def test_trace_completeness_reports_missing_terminal_event(self):
        result = check_trace_completeness(
            [
                audit_event("request_started"),
                audit_event("rag_retrieval", route="rag"),
            ],
            trace_id="trace-e9",
            smoke_name="chat",
        )

        self.assertFalse(result.passed)
        self.assertIn("missing_terminal_event", [issue.code for issue in result.issues])

    def test_negative_paths_localize_failure_layers(self):
        cases = [
            (
                audit_event(
                    "request_failed",
                    decision="blocked",
                    error_class="GuardrailBlocked",
                    reason="matched rule",
                ),
                "L2 RequestGateway / Guardrail",
            ),
            (
                audit_event(
                    "permission_checked",
                    decision="denied",
                    reason="no_matching_grant",
                    metadata={"resource_type": "document", "resource_id": "doc_secret"},
                ),
                "L3 Permission",
            ),
            (
                audit_event(
                    "tool_blocked",
                    route="tool_gateway",
                    decision="denied",
                    reason="tool_not_visible",
                    metadata={"tool_id": "forbidden.tool"},
                ),
                "L4 Tool/Model",
            ),
            (
                audit_event(
                    "model_call",
                    route="model_gateway",
                    decision="failed",
                    reason="model_provider_failed",
                    error_class="RuntimeError",
                    metadata={"status": "failed"},
                ),
                "L4 Tool/Model",
            ),
            (
                audit_event(
                    "database_query",
                    route="database_demo",
                    decision="denied",
                    reason="dangerous_sql",
                    metadata={"status": "blocked"},
                ),
                "L6 DB",
            ),
        ]

        for event, expected_layer in cases:
            localized = localize_failure(event)
            self.assertEqual(localized.layer, expected_layer)
            self.assertTrue(localized.module)
            self.assertTrue(localized.reason)

    def test_e9_report_fails_when_sse_contract_has_missing_field(self):
        complete_trace = check_trace_completeness(
            [
                audit_event("request_started"),
                audit_event("request_completed", latency_ms=1.0),
            ],
            trace_id="trace-e9",
            smoke_name="chat",
        )
        bad_sse = check_sse_contract(
            [{"type": "content", "trace_id": "trace-e9", "request_id": "request-e9"}],
            source="/api/chat_stream",
        )

        report = build_e9_observability_report(
            positive_smokes={"chat": complete_trace},
            negative_failures=[localize_failure(audit_event("tool_blocked", decision="denied", reason="denied"))],
            sse_contract_checks=[bad_sse],
        )

        self.assertFalse(report.passed)
        self.assertEqual(report.failure_layer, "L6 Observability / Event Contract")
        self.assertEqual(report.summary["positive_smokes_passed"], 1)
        self.assertEqual(report.summary["sse_contracts_passed"], 0)


if __name__ == "__main__":
    unittest.main()
