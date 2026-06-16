import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.auth as auth_api
import app.enterprise.admin.memory_operator_routes as memory_operator_routes
from app.enterprise.admin.memory_operator_adapter import MemoryOperatorAdapter
from app.enterprise.auth.service import auth_service
from app.enterprise.gateway.guardrail_providers import NoOpGuardrailProvider
from app.enterprise.gateway.guardrail_service import GuardrailService
from app.enterprise.gateway.rate_limit_service import NoOpRateLimitService
from app.enterprise.gateway.request_gateway import RequestGateway
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.models.memory import MemoryRecord, MemoryStatus, MemoryType, PlanTemplatePayload
from app.services.memory_review_service import MemoryReviewService
from app.services.memory_store import MemoryStore


def build_memory_operator_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    app.include_router(memory_operator_routes.router, prefix="/api")
    return app


class MemoryOperatorRouteTests(unittest.TestCase):
    def setUp(self):
        auth_service.reset_users()
        auth_service.clear_blacklist()
        self._old_adapter = memory_operator_routes.memory_operator_adapter
        self._old_gateway = memory_operator_routes.gateway

    def tearDown(self):
        memory_operator_routes.memory_operator_adapter = self._old_adapter
        memory_operator_routes.gateway = self._old_gateway
        auth_service.reset_users()
        auth_service.clear_blacklist()

    def _auth_headers(
        self,
        client: TestClient,
        *,
        username: str = "admin",
        trace_id: str = "trace-memory-route",
        request_id: str = "request-memory-route",
    ) -> dict[str, str]:
        password = "Admin123!" if username == "admin" else "Demo123!"
        response = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {
            "Authorization": f"Bearer {response.json()['data']['access_token']}",
            "X-Trace-Id": trace_id,
            "X-Request-Id": request_id,
        }

    def _install_test_operator(self, tmpdir: str):
        store = MemoryStore(Path(tmpdir) / "memory.sqlite3")
        review_service = MemoryReviewService(store=store)
        sink = InMemoryAuditSink()
        audit_service = AuditService(sinks=[sink])
        memory_operator_routes.memory_operator_adapter = MemoryOperatorAdapter(
            review_service=review_service,
            store=store,
            audit_service=audit_service,
        )
        memory_operator_routes.gateway = RequestGateway(
            audit_service=audit_service,
            guardrail_service=GuardrailService(providers=[NoOpGuardrailProvider()]),
            rate_limit_service=NoOpRateLimitService(),
        )
        return store, sink

    def test_non_admin_cannot_access_review_queue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._install_test_operator(tmpdir)
            client = TestClient(build_memory_operator_app())

            response = client.get(
                "/api/admin/memory-operator/review-queue",
                headers=self._auth_headers(client, username="demo_user_dept1"),
            )

            self.assertEqual(response.status_code, 403)

    def test_admin_review_queue_uses_gateway_and_writes_request_audit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store, sink = self._install_test_operator(tmpdir)
            store.upsert(self._plan_record("mem_candidate", MemoryStatus.CANDIDATE))
            client = TestClient(build_memory_operator_app())

            response = client.get(
                "/api/admin/memory-operator/review-queue",
                params={"owner_id": "default", "limit": 20},
                headers=self._auth_headers(client),
            )

            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()["data"]
            self.assertEqual(payload["items"][0]["memory_id"], "mem_candidate")
            self.assertEqual(payload["total"], 1)
            request_events = [
                event
                for event in sink.events
                if event.route == "memory_operator_review_queue"
            ]
            self.assertEqual(
                [event.event_type for event in request_events],
                ["request_started", "request_completed"],
            )
            self.assertTrue(
                all(event.trace_id == "trace-memory-route" for event in request_events)
            )

    def test_approve_ignores_spoofed_reviewer_and_uses_context_user(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store, sink = self._install_test_operator(tmpdir)
            store.upsert(self._plan_record("mem_candidate", MemoryStatus.CANDIDATE))
            client = TestClient(build_memory_operator_app())

            response = client.post(
                "/api/admin/memory-operator/atoms/mem_candidate/approve",
                json={
                    "decision_note": "validated by operator",
                    "reviewer_id": "spoofed-user",
                },
                headers=self._auth_headers(client),
            )

            self.assertEqual(response.status_code, 200, response.text)
            reviewed = store.get("mem_candidate")
            self.assertEqual(reviewed.review.reviewer_id, "user_admin")
            self.assertEqual(response.json()["data"]["record"]["review"]["reviewer_id"], "user_admin")
            self.assertEqual(
                [event.event_type for event in sink.events if event.route == "memory_operator_approve"],
                ["request_started", "request_completed"],
            )
            self.assertTrue(
                any(
                    event.event_type == "memory_review"
                    and event.route == "memory_operator"
                    and event.decision == "approved"
                    for event in sink.events
                )
            )

    def test_deprecation_preview_is_non_mutating_and_deprecate_requires_confirm(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store, sink = self._install_test_operator(tmpdir)
            store.upsert(self._plan_record("mem_active", MemoryStatus.ACTIVE, owner_id="ops-team"))
            store.upsert(self._plan_record("mem_other", MemoryStatus.ACTIVE, owner_id="other-team"))
            client = TestClient(build_memory_operator_app())
            headers = self._auth_headers(client)

            preview_response = client.post(
                "/api/admin/memory-operator/deprecation-preview",
                json={"owner_id": "ops-team"},
                headers=headers,
            )
            self.assertEqual(preview_response.status_code, 200, preview_response.text)
            self.assertEqual(preview_response.json()["data"]["plan"]["records_to_deprecate"], 1)
            self.assertEqual(store.get("mem_active").status, MemoryStatus.ACTIVE)
            self.assertEqual(store.get("mem_other").status, MemoryStatus.ACTIVE)

            bad_confirm_response = client.post(
                "/api/admin/memory-operator/deprecate-owner",
                json={
                    "owner_id": "ops-team",
                    "confirm_owner_id": "wrong-team",
                    "decision_note": "retire owner memories",
                },
                headers=headers,
            )
            confirm_response = client.post(
                "/api/admin/memory-operator/deprecate-owner",
                json={
                    "owner_id": "ops-team",
                    "confirm_owner_id": "ops-team",
                    "decision_note": "retire owner memories",
                },
                headers=headers,
            )

            self.assertEqual(bad_confirm_response.status_code, 400)
            self.assertEqual(confirm_response.status_code, 200, confirm_response.text)
            self.assertEqual(store.get("mem_active").status, MemoryStatus.DEPRECATED)
            self.assertEqual(store.get("mem_other").status, MemoryStatus.ACTIVE)
            self.assertTrue(any(event.event_type == "request_failed" for event in sink.events))
            self.assertTrue(
                any(
                    event.event_type == "memory_review" and event.decision == "deprecated"
                    for event in sink.events
                )
            )

    def _plan_record(
        self,
        memory_id: str,
        status: MemoryStatus,
        *,
        owner_id: str = "default",
    ) -> MemoryRecord:
        return MemoryRecord(
            memory_id=memory_id,
            owner_id=owner_id,
            namespace="memory://oncall/plan-templates",
            memory_type=MemoryType.PLAN_TEMPLATE,
            content="CPUHigh diagnosis should check CPU metrics and recent rollout.",
            summary=f"{memory_id} CPUHigh metrics rollout",
            payload=PlanTemplatePayload(
                alert_type="CPUHigh",
                plan_steps=["Check CPU metrics", "Check recent rollout"],
                evidence_refs=[
                    {
                        "evidence_type": "session_candidate",
                        "session_id": "session-aiops-1",
                    }
                ],
            ),
            source="session-candidate, NOT reviewed active memory",
            evidence={
                "evidence_type": "session_candidate",
                "session_id": "session-aiops-1",
                "source_type": "aiops_diagnosis",
            },
            status=status,
        )


if __name__ == "__main__":
    unittest.main()
