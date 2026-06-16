import tempfile
import unittest
from pathlib import Path

from app.enterprise.context import RequestContext
from app.enterprise.database.registry import build_default_sandbox_registry
from app.enterprise.database.safe_sql import SafeSqlBlocked, SafeSqlKernel
from app.enterprise.database.sandbox import create_sandbox_database
from app.enterprise.errors.mapper import build_error_event
from app.enterprise.errors.models import ErrorClass, ErrorContext, RecoveryDecision
from app.enterprise.errors.recovery import RecoveryStrategy
from app.enterprise.gateway.guardrail_providers import RuleGuardrailProvider
from app.enterprise.gateway.guardrail_service import GuardrailService
from app.enterprise.gateway.models import GatewayRequest
from app.enterprise.gateway.rate_limit_service import NoOpRateLimitService
from app.enterprise.gateway.request_gateway import RequestBlocked, RequestGateway
from app.enterprise.models.gateway import ModelGateway, ModelGatewayError
from app.enterprise.models.models import ModelEndpoint, ModelRequest, ModelResponse
from app.enterprise.models.providers import StaticModelProvider
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.observability.sse_contract import check_sse_contract
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService
from app.enterprise.tools.gateway import ToolExecutionError, ToolGateway
from app.enterprise.tools.models import ToolDefinition
from app.enterprise.tools.providers import StaticToolProvider


class EnterpriseErrorRecoveryStrategyTests(unittest.TestCase):
    def test_every_error_class_returns_frontend_and_audit_fields(self):
        for error_class in ErrorClass:
            with self.subTest(error_class=error_class.value):
                decision = RecoveryStrategy().decide(
                    ErrorContext(error_class=error_class, stage="test_stage")
                )

                self.assertEqual(decision.error_class, error_class)
                self.assertEqual(decision.stage, "test_stage")
                self.assertTrue(decision.decision)
                self.assertTrue(decision.status)
                self.assertTrue(decision.user_message)
                self.assertIn(decision.audit_category, {"security_blocking", "system_failure", "degradation"})

    def test_security_blocking_classes_never_retry_or_fallback(self):
        strategy = RecoveryStrategy()

        for error_class in (
            ErrorClass.AUTH_FAILED,
            ErrorClass.PERMISSION_DENIED,
            ErrorClass.GUARDRAIL_BLOCKED,
            ErrorClass.SQL_BLOCKED,
        ):
            with self.subTest(error_class=error_class.value):
                decision = strategy.decide(ErrorContext(error_class=error_class, stage="security"))

                self.assertEqual(decision.decision, RecoveryDecision.ABORT)
                self.assertFalse(decision.retryable)
                self.assertFalse(decision.fallback_allowed)
                self.assertFalse(decision.recoverable)
                self.assertIn(decision.status, {"blocked", "failed"})

    def test_model_failure_distinguishes_fallback_and_abort(self):
        strategy = RecoveryStrategy()

        fallback = strategy.decide(
            ErrorContext(
                error_class=ErrorClass.MODEL_UNAVAILABLE,
                stage="model_call",
                metadata={"fallback_available": True},
            )
        )
        abort = strategy.decide(
            ErrorContext(
                error_class=ErrorClass.MODEL_UNAVAILABLE,
                stage="model_call",
                metadata={"fallback_available": False},
            )
        )

        self.assertEqual(fallback.decision, RecoveryDecision.FALLBACK)
        self.assertEqual(fallback.status, "degraded")
        self.assertTrue(fallback.recoverable)
        self.assertTrue(fallback.fallback_allowed)
        self.assertEqual(abort.decision, RecoveryDecision.ABORT)
        self.assertEqual(abort.status, "failed")
        self.assertFalse(abort.fallback_allowed)

    def test_build_error_event_has_stable_frontend_envelope(self):
        event = build_error_event(
            ErrorContext(
                error_class=ErrorClass.MODEL_UNAVAILABLE,
                stage="model_call",
                metadata={"fallback_available": True},
            ),
            trace_id="trace-f5-sse",
            request_id="request-f5-sse",
        )

        self.assertTrue(check_sse_contract([event], source="f5-error").passed)
        self.assertEqual(event["type"], "error")
        self.assertEqual(event["trace_id"], "trace-f5-sse")
        self.assertEqual(event["request_id"], "request-f5-sse")
        self.assertEqual(event["stage"], "model_call")
        self.assertEqual(event["status"], "degraded")
        self.assertEqual(event["error_class"], "model_unavailable")
        self.assertEqual(event["decision"], "fallback")
        self.assertEqual(event["data"]["error_class"], "model_unavailable")
        self.assertEqual(event["data"]["decision"], "fallback")
        self.assertTrue(event["data"]["recoverable"])
        self.assertTrue(event["data"]["user_message"])


class EnterpriseErrorRecoveryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sink = InMemoryAuditSink()
        self.audit_service = AuditService(sinks=[self.sink])
        self.context = RequestContext(
            request_id="request-f5",
            trace_id="trace-f5",
            user_id="user_f5",
            username="f5_user",
            department_id="dept_f5",
            department_name="F5",
            roles=["user"],
        )

    def _permission_service(self) -> PermissionService:
        return PermissionService(
            repository=InMemoryGovernanceRepository(),
            audit_service=self.audit_service,
        )

    def _grant(self, service: PermissionService, resource_type: str, resource_id: str, action: str = "use"):
        service.grant_access(
            ResourceGrant(
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                principal_type=PrincipalType.USER,
                principal_id="user_f5",
                effect=GrantEffect.ALLOW,
            )
        )

    async def test_guardrail_blocked_audit_uses_structured_security_decision(self):
        gateway = RequestGateway(
            audit_service=self.audit_service,
            guardrail_service=GuardrailService(
                providers=[RuleGuardrailProvider.from_keywords(["删除日志"], reason="禁止删除日志操作")]
            ),
            rate_limit_service=NoOpRateLimitService(),
        )
        request = GatewayRequest(
            route="chat",
            payload={"Question": "请删除日志"},
            trace_id="trace-f5-guardrail",
            request_id="request-f5-guardrail",
            user_id="user_f5",
        )

        with self.assertRaises(RequestBlocked):
            await gateway.execute(request, lambda _context: None)

        failed = self.sink.events[-1]
        self.assertEqual(failed.event_type, "request_failed")
        self.assertEqual(failed.error_class, "guardrail_blocked")
        self.assertEqual(failed.decision, "blocked")
        self.assertEqual(failed.metadata["recovery_decision"], "abort")
        self.assertEqual(failed.metadata["audit_category"], "security_blocking")
        self.assertFalse(failed.metadata["retryable"])
        self.assertFalse(failed.metadata["fallback_allowed"])
        self.assertTrue(failed.metadata["user_message"])

    async def test_model_fallback_and_failure_use_model_unavailable_decisions(self):
        permissions = self._permission_service()
        self._grant(permissions, "model_endpoint", "primary")
        self._grant(permissions, "model_endpoint", "fallback")
        fallback_gateway = ModelGateway(
            endpoints=[
                ModelEndpoint(endpoint_id="primary", model_name="qwen-max", provider_name="primary"),
                ModelEndpoint(
                    endpoint_id="fallback",
                    model_name="qwen-plus",
                    provider_name="fallback",
                    priority=10,
                ),
            ],
            providers={
                "primary": StaticModelProvider(error=RuntimeError("primary down")),
                "fallback": StaticModelProvider(response=ModelResponse(content="fallback ok")),
            },
            permission_service=permissions,
            audit_service=self.audit_service,
        )

        response = await fallback_gateway.generate(self.context, ModelRequest(messages=[]))

        self.assertTrue(response.fallback_used)
        fallback_audit = self.sink.events[-1]
        self.assertEqual(fallback_audit.error_class, "model_unavailable")
        self.assertEqual(fallback_audit.decision, "degraded")
        self.assertEqual(fallback_audit.metadata["recovery_decision"], "fallback")
        self.assertEqual(fallback_audit.metadata["audit_category"], "degradation")
        self.assertEqual(fallback_audit.metadata["source_error_classes"], ["RuntimeError"])
        self.assertTrue(fallback_audit.metadata["user_message"])

        failing_gateway = ModelGateway(
            endpoints=[
                ModelEndpoint(endpoint_id="primary", model_name="qwen-max", provider_name="primary"),
                ModelEndpoint(
                    endpoint_id="fallback",
                    model_name="qwen-plus",
                    provider_name="fallback",
                    priority=10,
                ),
            ],
            providers={
                "primary": StaticModelProvider(error=RuntimeError("primary down")),
                "fallback": StaticModelProvider(error=ValueError("fallback down")),
            },
            permission_service=permissions,
            audit_service=self.audit_service,
        )

        with self.assertRaises(ModelGatewayError):
            await failing_gateway.generate(self.context, ModelRequest(messages=[]))

        failed_audit = self.sink.events[-1]
        self.assertEqual(failed_audit.error_class, "model_unavailable")
        self.assertEqual(failed_audit.decision, "failed")
        self.assertEqual(failed_audit.metadata["recovery_decision"], "abort")
        self.assertEqual(failed_audit.metadata["source_error_classes"], ["RuntimeError", "ValueError"])

    async def test_tool_failure_uses_user_safe_tool_failed_metadata(self):
        permissions = self._permission_service()
        self._grant(permissions, "tool", "failing_tool")

        async def failing_handler(_arguments):
            raise RuntimeError("backend exploded with secret")

        gateway = ToolGateway(
            providers=[
                StaticToolProvider(
                    [
                        ToolDefinition(
                            resource_id="failing_tool",
                            name="failing",
                            source="local",
                            handler=failing_handler,
                        )
                    ]
                )
            ],
            permission_service=permissions,
            audit_service=self.audit_service,
        )

        with self.assertRaises(ToolExecutionError):
            await gateway.execute(self.context, "failing_tool", {"text": "boom"})

        audit = self.sink.events[-1]
        self.assertEqual(audit.event_type, "tool_failure")
        self.assertEqual(audit.error_class, "tool_failed")
        self.assertEqual(audit.metadata["source_error_class"], "RuntimeError")
        self.assertEqual(audit.metadata["recovery_decision"], "abort")
        self.assertTrue(audit.metadata["user_message"])
        self.assertNotIn("secret", audit.metadata["user_message"])

    def test_sql_blocked_audit_uses_sql_blocked_error_class(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sandbox.sqlite3"
            create_sandbox_database(db_path)
            registry = build_default_sandbox_registry()
            kernel = SafeSqlKernel(
                database_path=db_path,
                registry=registry,
                audit_service=self.audit_service,
            )

            with self.assertRaises(SafeSqlBlocked):
                kernel.safe_select(self.context, "drop table factory_access_events")

        audit = self.sink.events[-1]
        self.assertEqual(audit.event_type, "database_query")
        self.assertEqual(audit.decision, "denied")
        self.assertEqual(audit.error_class, "sql_blocked")
        self.assertEqual(audit.metadata["recovery_decision"], "abort")
        self.assertEqual(audit.metadata["audit_category"], "security_blocking")
        self.assertTrue(audit.metadata["user_message"])


if __name__ == "__main__":
    unittest.main()
