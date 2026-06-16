import unittest

from app.enterprise.context import RequestContext
from app.enterprise.models.gateway import ModelAccessDenied, ModelGateway, ModelGatewayError
from app.enterprise.models.models import ModelEndpoint, ModelRequest, ModelResponse
from app.enterprise.models.providers import StaticModelProvider
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService


class EnterpriseModelGatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sink = InMemoryAuditSink()
        self.audit_service = AuditService(sinks=[self.sink])
        self.permission_service = PermissionService(
            repository=InMemoryGovernanceRepository(),
            audit_service=self.audit_service,
        )
        self.context = RequestContext(
            request_id="request-model",
            trace_id="trace-model",
            user_id="user_demo_dept1",
            username="demo_user_dept1",
            department_id="dept_1",
            department_name="Department 1",
            roles=["user"],
        )

    def grant_model(self, endpoint_id: str):
        self.permission_service.grant_access(
            ResourceGrant(
                resource_type="model_endpoint",
                resource_id=endpoint_id,
                action="use",
                principal_type=PrincipalType.USER,
                principal_id="user_demo_dept1",
                effect=GrantEffect.ALLOW,
            )
        )

    async def test_model_success_records_latency_usage_and_status(self):
        self.grant_model("primary-qwen")
        gateway = ModelGateway(
            endpoints=[
                ModelEndpoint(
                    endpoint_id="primary-qwen",
                    model_name="qwen-max",
                    provider_name="dashscope",
                )
            ],
            providers={
                "dashscope": StaticModelProvider(
                    response=ModelResponse(
                        content="ok",
                        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    )
                )
            },
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )

        response = await gateway.generate(
            self.context,
            ModelRequest(messages=[{"role": "user", "content": "hello"}]),
        )

        self.assertEqual(response.content, "ok")
        self.assertEqual(response.endpoint_id, "primary-qwen")
        self.assertFalse(response.fallback_used)
        audit = self.sink.events[-1]
        self.assertEqual(audit.event_type, "model_call")
        self.assertEqual(audit.decision, "allowed")
        self.assertEqual(audit.metadata["model_name"], "qwen-max")
        self.assertEqual(audit.metadata["status"], "success")
        self.assertFalse(audit.metadata["fallback_used"])
        self.assertEqual(audit.metadata["usage"]["total_tokens"], 2)
        self.assertIsNotNone(audit.latency_ms)

    async def test_model_fallback_records_failed_primary_and_fallback_used(self):
        self.grant_model("primary-qwen")
        self.grant_model("fallback-qwen")
        gateway = ModelGateway(
            endpoints=[
                ModelEndpoint(
                    endpoint_id="primary-qwen",
                    model_name="qwen-max",
                    provider_name="primary",
                    priority=0,
                ),
                ModelEndpoint(
                    endpoint_id="fallback-qwen",
                    model_name="qwen-plus",
                    provider_name="fallback",
                    priority=10,
                ),
            ],
            providers={
                "primary": StaticModelProvider(error=RuntimeError("primary down")),
                "fallback": StaticModelProvider(response=ModelResponse(content="fallback ok")),
            },
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )

        response = await gateway.generate(self.context, ModelRequest(messages=[]))

        self.assertEqual(response.content, "fallback ok")
        self.assertEqual(response.endpoint_id, "fallback-qwen")
        self.assertTrue(response.fallback_used)
        audit = self.sink.events[-1]
        self.assertEqual(audit.event_type, "model_call")
        self.assertEqual(audit.decision, "degraded")
        self.assertEqual(audit.error_class, "model_unavailable")
        self.assertEqual(audit.metadata["model_name"], "qwen-plus")
        self.assertEqual(audit.metadata["status"], "success")
        self.assertTrue(audit.metadata["fallback_used"])
        self.assertEqual(audit.metadata["failed_endpoint_ids"], ["primary-qwen"])
        self.assertEqual(audit.metadata["recovery_decision"], "fallback")
        self.assertEqual(audit.metadata["source_error_classes"], ["RuntimeError"])

    async def test_model_failure_records_structured_failure(self):
        self.grant_model("primary-qwen")
        self.grant_model("fallback-qwen")
        gateway = ModelGateway(
            endpoints=[
                ModelEndpoint(
                    endpoint_id="primary-qwen",
                    model_name="qwen-max",
                    provider_name="primary",
                ),
                ModelEndpoint(
                    endpoint_id="fallback-qwen",
                    model_name="qwen-plus",
                    provider_name="fallback",
                    priority=10,
                ),
            ],
            providers={
                "primary": StaticModelProvider(error=RuntimeError("primary down")),
                "fallback": StaticModelProvider(error=ValueError("fallback down")),
            },
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )

        with self.assertRaises(ModelGatewayError):
            await gateway.generate(self.context, ModelRequest(messages=[]))

        audit = self.sink.events[-1]
        self.assertEqual(audit.event_type, "model_call")
        self.assertEqual(audit.decision, "failed")
        self.assertEqual(audit.error_class, "model_unavailable")
        self.assertEqual(audit.metadata["status"], "failed")
        self.assertTrue(audit.metadata["fallback_used"])
        self.assertEqual(audit.metadata["failed_endpoint_ids"], ["primary-qwen", "fallback-qwen"])
        self.assertEqual(audit.metadata["recovery_decision"], "abort")
        self.assertEqual(audit.metadata["source_error_classes"], ["RuntimeError", "ValueError"])

    async def test_denied_model_endpoint_is_not_selected(self):
        gateway = ModelGateway(
            endpoints=[
                ModelEndpoint(
                    endpoint_id="primary-qwen",
                    model_name="qwen-max",
                    provider_name="dashscope",
                )
            ],
            providers={"dashscope": StaticModelProvider(response=ModelResponse(content="ok"))},
            permission_service=self.permission_service,
            audit_service=self.audit_service,
        )

        with self.assertRaises(ModelAccessDenied):
            await gateway.generate(self.context, ModelRequest(messages=[]))

        audit = self.sink.events[-1]
        self.assertEqual(audit.event_type, "model_call")
        self.assertEqual(audit.decision, "denied")
        self.assertEqual(audit.reason, "no_allowed_model_endpoint")


if __name__ == "__main__":
    unittest.main()
