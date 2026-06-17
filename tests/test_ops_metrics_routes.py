import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.auth as auth_api
import app.enterprise.admin.ops_metrics_routes as ops_metrics_routes
from app.enterprise.auth.service import auth_service
from app.enterprise.gateway.guardrail_providers import NoOpGuardrailProvider
from app.enterprise.gateway.guardrail_service import GuardrailService
from app.enterprise.gateway.rate_limit_service import NoOpRateLimitService
from app.enterprise.gateway.request_gateway import RequestGateway
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink


def build_ops_metrics_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    app.include_router(ops_metrics_routes.router, prefix="/api")
    return app


class FakeOpsMetricsAdapter:
    def __init__(self):
        self.calls = []

    async def get_summary(self, context, time_range):
        if time_range == "31d":
            raise ValueError("time_range must be one of 1h, 24h, 7d, 30d")
        self.calls.append(("summary", context.user_id, time_range))
        return {
            "total_requests": 2,
            "success_rate": 0.5,
            "p50_latency_ms": 20,
            "p95_latency_ms": 40,
            "top_users": [],
            "top_routes": [],
            "top_tools": [],
        }

    async def get_timeline(self, context, time_range, bucket):
        self.calls.append(("timeline", context.user_id, time_range, bucket))
        return [{"time_bucket": "2026-06-16T12:00:00+00:00", "total": 2}]

    async def get_failures(self, context, time_range, limit):
        self.calls.append(("failures", context.user_id, time_range, limit))
        return [{"trace_id": "trace-failed", "failure_semantics": "infra_error", "recovered": False}]


class OpsMetricsRouteTests(unittest.TestCase):
    def setUp(self):
        auth_service.reset_users()
        auth_service.clear_blacklist()
        self._old_adapter = ops_metrics_routes.ops_metrics_adapter
        self._old_gateway = ops_metrics_routes.gateway
        self.adapter = FakeOpsMetricsAdapter()
        self.sink = InMemoryAuditSink()
        audit_service = AuditService(sinks=[self.sink])
        ops_metrics_routes.ops_metrics_adapter = self.adapter
        ops_metrics_routes.gateway = RequestGateway(
            audit_service=audit_service,
            guardrail_service=GuardrailService(providers=[NoOpGuardrailProvider()]),
            rate_limit_service=NoOpRateLimitService(),
        )
        self.client = TestClient(build_ops_metrics_app())

    def tearDown(self):
        ops_metrics_routes.ops_metrics_adapter = self._old_adapter
        ops_metrics_routes.gateway = self._old_gateway
        auth_service.reset_users()
        auth_service.clear_blacklist()

    def _headers(self, username="admin") -> dict[str, str]:
        password = "Admin123!" if username == "admin" else "Demo123!"
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {
            "Authorization": f"Bearer {response.json()['data']['access_token']}",
            "X-Trace-Id": "trace-ops-route",
            "X-Request-Id": "request-ops-route",
        }

    def test_non_admin_cannot_access_ops_metrics(self):
        response = self.client.get(
            "/api/admin/ops-metrics/summary",
            headers=self._headers(username="demo_user_dept1"),
        )

        self.assertEqual(response.status_code, 403)

    def test_summary_route_uses_request_gateway_and_adapter(self):
        response = self.client.get(
            "/api/admin/ops-metrics/summary",
            params={"time_range": "24h"},
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["total_requests"], 2)
        self.assertNotIn("total_cost", data)
        self.assertEqual(self.adapter.calls, [("summary", "user_admin", "24h")])
        request_events = [
            event for event in self.sink.events if event.route == "ops_metrics_summary"
        ]
        self.assertEqual(
            [event.event_type for event in request_events],
            ["request_started", "request_completed"],
        )

    def test_timeline_and_failures_routes_use_gateway(self):
        timeline_response = self.client.get(
            "/api/admin/ops-metrics/timeline",
            params={"time_range": "7d", "bucket": "1h"},
            headers=self._headers(),
        )
        failures_response = self.client.get(
            "/api/admin/ops-metrics/failures",
            params={"time_range": "7d", "limit": 5},
            headers=self._headers(),
        )

        self.assertEqual(timeline_response.status_code, 200, timeline_response.text)
        self.assertEqual(failures_response.status_code, 200, failures_response.text)
        self.assertEqual(timeline_response.json()["data"]["timeline"][0]["total"], 2)
        self.assertEqual(failures_response.json()["data"]["failures"][0]["failure_semantics"], "infra_error")
        self.assertIn(("timeline", "user_admin", "7d", "1h"), self.adapter.calls)
        self.assertIn(("failures", "user_admin", "7d", 5), self.adapter.calls)
        event_routes = [event.route for event in self.sink.events]
        self.assertIn("ops_metrics_timeline", event_routes)
        self.assertIn("ops_metrics_failures", event_routes)

    def test_validation_errors_return_400_and_request_failed_audit(self):
        response = self.client.get(
            "/api/admin/ops-metrics/summary",
            params={"time_range": "31d"},
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 400)
        request_events = [
            event for event in self.sink.events if event.route == "ops_metrics_summary"
        ]
        self.assertEqual(request_events[-1].event_type, "request_failed")


if __name__ == "__main__":
    unittest.main()
