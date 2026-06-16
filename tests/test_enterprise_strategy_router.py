import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.aiops as aiops_api
import app.api.auth as auth_api
import app.api.chat as chat_api
from app.enterprise.auth.service import auth_service
from app.enterprise.context import RequestContext
from app.enterprise.gateway.guardrail_providers import NoOpGuardrailProvider
from app.enterprise.gateway.guardrail_service import GuardrailService
from app.enterprise.gateway.rate_limit_service import NoOpRateLimitService
from app.enterprise.gateway.request_gateway import RequestGateway
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.routing.providers import (
    KeywordRoutingProvider,
    LlmShadowRoutingProvider,
    RuleRoutingProvider,
)
from app.enterprise.routing.router import StrategyRouter, build_routing_comparison_report
from app.enterprise.session_ownership import session_ownership_service


def build_route_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    app.include_router(chat_api.router, prefix="/api")
    app.include_router(aiops_api.router, prefix="/api")
    return app


class FakeAIOpsService:
    def __init__(self):
        self.calls: list[dict] = []

    async def diagnose(self, **kwargs):
        self.calls.append(kwargs)
        yield {
            "type": "complete",
            "stage": "diagnosis_complete",
            "message": "done",
            "diagnosis": {"status": "completed", "report": "ok"},
        }


class EnterpriseStrategyRouterTests(unittest.TestCase):
    def setUp(self):
        auth_service.reset_users()
        auth_service.clear_blacklist()
        session_ownership_service.clear()
        self.sink = InMemoryAuditSink()
        self.audit_service = AuditService(sinks=[self.sink])
        self.routing_service = StrategyRouter(
            providers=[
                RuleRoutingProvider(),
                KeywordRoutingProvider(),
                LlmShadowRoutingProvider(),
            ]
        )
        self.gateway = RequestGateway(
            audit_service=self.audit_service,
            guardrail_service=GuardrailService(providers=[NoOpGuardrailProvider()]),
            rate_limit_service=NoOpRateLimitService(),
        )
        self.original_chat_gateway = chat_api.chat_adapter.gateway
        self.original_chat_router = chat_api.chat_adapter.routing_service
        self.original_aiops_gateway = aiops_api.aiops_adapter.gateway
        self.original_aiops_router = aiops_api.aiops_adapter.routing_service
        self.original_aiops_service = aiops_api.aiops_adapter.aiops_service
        chat_api.chat_adapter.gateway = self.gateway
        chat_api.chat_adapter.routing_service = self.routing_service
        aiops_api.aiops_adapter.gateway = self.gateway
        aiops_api.aiops_adapter.routing_service = self.routing_service

    def tearDown(self):
        chat_api.chat_adapter.gateway = self.original_chat_gateway
        chat_api.chat_adapter.routing_service = self.original_chat_router
        aiops_api.aiops_adapter.gateway = self.original_aiops_gateway
        aiops_api.aiops_adapter.routing_service = self.original_aiops_router
        aiops_api.aiops_adapter.aiops_service = self.original_aiops_service
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

    def _context(self, route: str = "chat") -> RequestContext:
        return RequestContext(
            request_id="request-f3",
            trace_id="trace-f3",
            user_id="user_f3",
            username="user_f3",
            department_id="ops",
            department_name="Operations",
            roles=["operator"],
        )

    def test_rule_provider_routes_chat_database_aiops_admin_and_human_review(self):
        simple_chat = self.routing_service.evaluate(
            self._context("chat"),
            route="chat",
            payload={"Question": "hello there"},
        )
        knowledge = self.routing_service.evaluate(
            self._context("chat"),
            route="chat",
            payload={"Question": "How do I reset the password from the runbook?"},
        )
        database = self.routing_service.evaluate(
            self._context("chat"),
            route="chat",
            payload={"Question": "Please select customer database rows."},
        )
        aiops = self.routing_service.evaluate(
            self._context("aiops"),
            route="aiops",
            payload={"query": "diagnose alert", "session_id": "session-f3"},
        )
        human_review = self.routing_service.evaluate(
            self._context("aiops"),
            route="aiops",
            payload={
                "query": "diagnose alert",
                "task_contract": {
                    "user_goal": "restart the service",
                    "risk_level": "high",
                    "requires_human_approval": True,
                },
            },
        )
        admin = self.routing_service.evaluate(
            self._context("chat"),
            route="admin",
            payload={},
        )

        self.assertEqual(simple_chat.route, "chat")
        self.assertEqual(knowledge.route, "rag")
        self.assertEqual(database.route, "database")
        self.assertEqual(aiops.route, "aiops")
        self.assertEqual(human_review.route, "human_review")
        self.assertEqual(admin.route, "admin")
        self.assertEqual(simple_chat.provider, "rules")
        self.assertGreaterEqual(database.confidence, 0.7)
        self.assertEqual(
            knowledge.metadata["routing_diagnostics"],
            {
                "domain": "knowledge",
                "intent": "knowledge_retrieval",
                "approval_required": False,
                "execution_mode": "retrieval",
                "actual_route": "chat",
                "shadow_only": True,
            },
        )
        self.assertEqual(
            human_review.metadata["routing_diagnostics"]["execution_mode"],
            "approval_gate",
        )
        self.assertTrue(
            human_review.metadata["routing_diagnostics"]["approval_required"],
        )

    def test_shadow_decision_audit_and_comparison_report(self):
        decision = self.routing_service.record_shadow_decision(
            audit_service=self.audit_service,
            context=self._context("chat"),
            actual_route="chat",
            payload={"Question": "diagnose alert"},
        )

        self.assertIsNotNone(decision)
        self.assertEqual(self.sink.events[-1].event_type, "routing_decision")
        self.assertEqual(self.sink.events[-1].decision, "shadow")
        self.assertEqual(self.sink.events[-1].metadata["actual_route"], "chat")
        self.assertEqual(self.sink.events[-1].metadata["suggested_route"], "aiops")
        self.assertEqual(self.sink.events[-1].metadata["trace_id"], "trace-f3")
        diagnostics = self.sink.events[-1].metadata["routing_diagnostics"]
        self.assertEqual(diagnostics["domain"], "aiops")
        self.assertEqual(diagnostics["intent"], "incident_diagnosis")
        self.assertEqual(diagnostics["execution_mode"], "agent_workflow")
        self.assertEqual(diagnostics["actual_route"], "chat")
        self.assertTrue(diagnostics["shadow_only"])
        report = build_routing_comparison_report(self.sink.events)
        self.assertEqual(report.total_decisions, 1)
        self.assertEqual(report.match_rate, 0.0)
        self.assertEqual(report.confusion_cases[0].suggested_route, "aiops")

    def test_chat_route_records_shadow_decision_without_changing_response(self):
        with patch.object(
            chat_api.rag_agent_service,
            "query",
            new=AsyncMock(return_value="chat ok"),
        ):
            client = TestClient(build_route_app())
            response = client.post(
                "/api/chat",
                json={"Id": "session-f3", "Question": "hello"},
                headers=self._auth_headers(
                    client,
                    trace_id="trace-f3-chat",
                    request_id="request-f3-chat",
                ),
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"]["answer"], "chat ok")
        routing_events = [
            event
            for event in self.sink.events
            if event.event_type == "routing_decision"
        ]
        self.assertEqual(len(routing_events), 1)
        self.assertEqual(routing_events[0].metadata["actual_route"], "chat")
        self.assertEqual(routing_events[0].metadata["suggested_route"], "chat")
        self.assertEqual(routing_events[0].metadata["provider"], "rules")
        self.assertEqual(
            routing_events[0].metadata["routing_diagnostics"]["execution_mode"],
            "direct_response",
        )

    def test_aiops_route_records_shadow_decision_without_changing_stream(self):
        fake_aiops = FakeAIOpsService()
        with patch.object(aiops_api.aiops_adapter, "aiops_service", fake_aiops):
            client = TestClient(build_route_app())

            response = client.post(
                "/api/aiops",
                json={"session_id": "session-f3-aiops", "query": "diagnose alert"},
                headers=self._auth_headers(
                    client,
                    trace_id="trace-f3-aiops",
                    request_id="request-f3-aiops",
                ),
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(fake_aiops.calls), 1)
        self.assertEqual(fake_aiops.calls[0]["task_contract_id"], None)
        self.assertIn("trace-f3-aiops", response.text)
        routing_events = [
            event
            for event in self.sink.events
            if event.event_type == "routing_decision"
        ]
        self.assertEqual(len(routing_events), 1)
        self.assertEqual(routing_events[0].metadata["actual_route"], "aiops")
        self.assertEqual(routing_events[0].metadata["suggested_route"], "aiops")
        self.assertEqual(routing_events[0].metadata["provider"], "rules")
        self.assertEqual(
            routing_events[0].metadata["routing_diagnostics"]["actual_route"],
            "aiops",
        )


if __name__ == "__main__":
    unittest.main()
