import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.admin_reviews as admin_reviews_api
import app.api.auth as auth_api
from app.enterprise.adapters.aiops_adapter import AIOpsAdapter
from app.enterprise.auth.service import auth_service
from app.enterprise.context import RequestContext
from app.enterprise.gateway.guardrail_providers import NoOpGuardrailProvider
from app.enterprise.gateway.guardrail_service import GuardrailService
from app.enterprise.gateway.rate_limit_service import NoOpRateLimitService
from app.enterprise.gateway.request_gateway import RequestGateway
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService
from app.enterprise.reviews.repository import InMemoryHumanReviewRepository
from app.enterprise.reviews.service import HumanReviewService
from app.enterprise.tasks.models import RiskLevel, TaskContractCreate, TaskScope
from app.enterprise.tasks.repository import InMemoryTaskContractRepository
from app.enterprise.tasks.service import TaskContractService
from app.enterprise.tasks.validator import ContractValidator
from app.models.aiops import AIOpsRequest


def build_review_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    app.include_router(admin_reviews_api.router, prefix="/api")
    return app


def grant(resource_type: str, resource_id: str, action: str) -> ResourceGrant:
    return ResourceGrant(
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        principal_type=PrincipalType.USER,
        principal_id="user_f6",
        effect=GrantEffect.ALLOW,
        reason="test_allow",
    )


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


class EnterpriseHumanReviewF6Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        auth_service.reset_users()
        auth_service.clear_blacklist()
        self.sink = InMemoryAuditSink()
        self.audit_service = AuditService(sinks=[self.sink])
        self.review_repository = InMemoryHumanReviewRepository()
        self.review_service = HumanReviewService(
            repository=self.review_repository,
            audit_service=self.audit_service,
        )
        self.contract_service = self._build_contract_service()
        self.original_review_service = admin_reviews_api.human_review_service
        admin_reviews_api.human_review_service = self.review_service
        self.client = TestClient(build_review_app())

    def tearDown(self):
        admin_reviews_api.human_review_service = self.original_review_service
        auth_service.reset_users()
        auth_service.clear_blacklist()

    def _build_contract_service(self) -> TaskContractService:
        permissions = PermissionService(
            repository=InMemoryGovernanceRepository(
                grants=[
                    grant("document", "kb-prod-runbook", "read"),
                    grant("tool", "retrieve_knowledge", "use"),
                ]
            ),
            audit_service=self.audit_service,
        )
        return TaskContractService(
            repository=InMemoryTaskContractRepository(),
            validator=ContractValidator(permissions),
            audit_service=self.audit_service,
        )

    def _adapter(self, fake_aiops: FakeAIOpsService) -> AIOpsAdapter:
        gateway = RequestGateway(
            audit_service=self.audit_service,
            guardrail_service=GuardrailService(providers=[NoOpGuardrailProvider()]),
            rate_limit_service=NoOpRateLimitService(),
        )
        return AIOpsAdapter(
            fake_aiops,
            gateway=gateway,
            contract_service=self.contract_service,
            human_review_service=self.review_service,
        )

    def _high_risk_request(
        self,
        *,
        query: str = "diagnose alert and recommend production restart",
        **contract_updates,
    ) -> AIOpsRequest:
        contract = {
            "user_goal": "diagnose alert and recommend production restart",
            "scope": {
                "allowed_data_sources": ["kb-prod-runbook"],
                "allowed_tools": ["retrieve_knowledge"],
                "forbidden_actions": ["delete_database"],
            },
            "success_criteria": ["explain symptoms"],
            "risk_level": RiskLevel.HIGH.value,
            "requires_human_approval": True,
            "expected_outputs": ["diagnostic_report"],
        }
        contract.update(contract_updates)
        return AIOpsRequest(
            session_id="session-f6",
            query=query,
            task_contract=contract,
        )

    def _task_contract_create(self) -> TaskContractCreate:
        return TaskContractCreate(
            user_goal="diagnose alert and recommend production restart",
            scope=TaskScope(
                allowed_data_sources=["kb-prod-runbook"],
                allowed_tools=["retrieve_knowledge"],
                forbidden_actions=["delete_database"],
            ),
            success_criteria=["explain symptoms"],
            risk_level=RiskLevel.HIGH,
            requires_human_approval=True,
            expected_outputs=["diagnostic_report"],
        )

    async def test_high_risk_task_registers_pending_review_without_aiops_execution(self):
        fake_aiops = FakeAIOpsService()
        adapter = self._adapter(fake_aiops)

        events = []
        async for event in adapter.diagnose_stream(
            self._high_risk_request(),
            headers={
                "X-Trace-Id": "trace-f6-pending",
                "X-Request-Id": "request-f6-pending",
                "X-User-Id": "user_f6",
            },
            session_id="session-f6",
            memory_mode="off",
        ):
            events.append(event)

        self.assertEqual(fake_aiops.calls, [])
        self.assertEqual(events[-1]["type"], "pending_approval")
        self.assertEqual(events[-1]["stage"], "human_review")
        self.assertEqual(events[-1]["status"], "pending")
        review_id = events[-1]["review_id"]
        task_id = events[-1]["task_contract_id"]
        pending_reviews = self.review_service.list_pending()
        self.assertEqual([review.review_id for review in pending_reviews], [review_id])
        self.assertEqual(pending_reviews[0].task_id, task_id)
        self.assertEqual(
            [
                event.event_type
                for event in self.sink.events
                if event.event_type == "human_review_requested"
            ],
            ["human_review_requested"],
        )

    async def test_database_write_request_requires_review_even_when_contract_is_medium(self):
        fake_aiops = FakeAIOpsService()
        adapter = self._adapter(fake_aiops)

        events = []
        async for event in adapter.diagnose_stream(
            self._high_risk_request(
                query="please update the customer database status field",
                user_goal="update database rows for the incident",
                risk_level=RiskLevel.MEDIUM.value,
                requires_human_approval=False,
                scope={
                    "allowed_data_sources": ["kb-prod-runbook"],
                    "allowed_tools": ["retrieve_knowledge"],
                    "forbidden_actions": [],
                },
            ),
            headers={
                "X-Trace-Id": "trace-f6-db-write",
                "X-Request-Id": "request-f6-db-write",
                "X-User-Id": "user_f6",
            },
            session_id="session-f6",
            memory_mode="off",
        ):
            events.append(event)

        self.assertEqual(fake_aiops.calls, [])
        self.assertEqual(events[-1]["type"], "pending_approval")
        review = self.review_service.list_pending()[0]
        self.assertEqual(review.risk_level, RiskLevel.MEDIUM.value)
        self.assertIn("database_write_request", review.metadata["signals"])

    async def test_approved_review_allows_same_task_to_continue(self):
        fake_aiops = FakeAIOpsService()
        adapter = self._adapter(fake_aiops)
        first_events = []
        async for event in adapter.diagnose_stream(
            self._high_risk_request(),
            headers={
                "X-Trace-Id": "trace-f6-approve",
                "X-Request-Id": "request-f6-approve",
                "X-User-Id": "user_f6",
            },
            session_id="session-f6",
            memory_mode="off",
        ):
            first_events.append(event)
        review_id = first_events[-1]["review_id"]
        task_id = first_events[-1]["task_contract_id"]
        self.review_service.approve(
            RequestContext(
                request_id="request-admin-approve",
                trace_id="trace-admin-approve",
                user_id="user_admin",
                username="admin",
                department_id="system",
                department_name="System",
                roles=["admin"],
            ),
            review_id=review_id,
            reason="approved for test",
        )

        second_events = []
        async for event in adapter.diagnose_stream(
            self._high_risk_request(review_id=review_id, task_id=task_id),
            headers={
                "X-Trace-Id": "trace-f6-resume",
                "X-Request-Id": "request-f6-resume",
                "X-User-Id": "user_f6",
            },
            session_id="session-f6",
            memory_mode="off",
        ):
            second_events.append(event)

        self.assertEqual(len(fake_aiops.calls), 1)
        self.assertEqual(fake_aiops.calls[0]["task_contract_id"], task_id)
        self.assertEqual(second_events[-1]["type"], "complete")
        self.assertEqual(second_events[-1]["task_contract_id"], task_id)

    async def test_rejected_review_blocks_same_task_without_execution(self):
        fake_aiops = FakeAIOpsService()
        adapter = self._adapter(fake_aiops)
        first_events = []
        async for event in adapter.diagnose_stream(
            self._high_risk_request(),
            headers={
                "X-Trace-Id": "trace-f6-reject",
                "X-Request-Id": "request-f6-reject",
                "X-User-Id": "user_f6",
            },
            session_id="session-f6",
            memory_mode="off",
        ):
            first_events.append(event)
        review_id = first_events[-1]["review_id"]
        task_id = first_events[-1]["task_contract_id"]
        self.review_service.reject(
            RequestContext(
                request_id="request-admin-reject",
                trace_id="trace-admin-reject",
                user_id="user_admin",
                username="admin",
                department_id="system",
                department_name="System",
                roles=["admin"],
            ),
            review_id=review_id,
            reason="too risky",
        )

        second_events = []
        async for event in adapter.diagnose_stream(
            self._high_risk_request(review_id=review_id, task_id=task_id),
            headers={
                "X-Trace-Id": "trace-f6-rejected-resume",
                "X-Request-Id": "request-f6-rejected-resume",
                "X-User-Id": "user_f6",
            },
            session_id="session-f6",
            memory_mode="off",
        ):
            second_events.append(event)

        self.assertEqual(fake_aiops.calls, [])
        self.assertEqual(second_events[-1]["type"], "error")
        self.assertEqual(second_events[-1]["stage"], "human_review")
        self.assertEqual(second_events[-1]["status"], "rejected")
        self.assertEqual(second_events[-1]["task_contract_id"], task_id)

    def login(self, username: str = "admin", password: str = "Admin123!") -> str:
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["access_token"]

    def test_admin_review_api_lists_pending_and_audits_decisions(self):
        context = RequestContext(
            request_id="request-f6-api",
            trace_id="trace-f6-api",
            user_id="user_f6",
            username="user_f6",
            department_id="ops",
            department_name="Operations",
            roles=["operator"],
        )
        contract_result = self.contract_service.create_contract(
            context,
            self._task_contract_create(),
        )
        review = self.review_service.register_pending_review(
            context,
            contract_result.contract,
            route="aiops",
            reason="approval_required",
        )
        admin_headers = {
            "Authorization": f"Bearer {self.login()}",
            "X-Trace-Id": "trace-f6-admin",
        }

        pending_response = self.client.get(
            "/api/admin/reviews/pending",
            headers=admin_headers,
        )
        approve_response = self.client.post(
            f"/api/admin/reviews/{review.review_id}/approve",
            headers=admin_headers,
            json={"reason": "approved by admin"},
        )

        self.assertEqual(pending_response.status_code, 200, pending_response.text)
        self.assertEqual(approve_response.status_code, 200, approve_response.text)
        self.assertEqual(
            [item["review_id"] for item in pending_response.json()["data"]["reviews"]],
            [review.review_id],
        )
        self.assertEqual(approve_response.json()["data"]["review"]["status"], "approved")
        self.assertIn(
            "human_review_approved",
            [event.event_type for event in self.sink.events],
        )

    def test_non_admin_cannot_approve_review(self):
        context = RequestContext(
            request_id="request-f6-non-admin",
            trace_id="trace-f6-non-admin",
            user_id="user_f6",
            username="user_f6",
            department_id="ops",
            department_name="Operations",
            roles=["operator"],
        )
        contract_result = self.contract_service.create_contract(
            context,
            self._task_contract_create(),
        )
        review = self.review_service.register_pending_review(
            context,
            contract_result.contract,
            route="aiops",
            reason="approval_required",
        )
        user_headers = {
            "Authorization": f"Bearer {self.login('demo_user_dept1', 'Demo123!')}",
            "X-Trace-Id": "trace-f6-non-admin-api",
        }

        response = self.client.post(
            f"/api/admin/reviews/{review.review_id}/approve",
            headers=user_headers,
            json={"reason": "not allowed"},
        )

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
