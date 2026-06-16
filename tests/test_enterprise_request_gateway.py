import unittest

from app.enterprise.gateway.guardrail_providers import NoOpGuardrailProvider, RuleGuardrailProvider
from app.enterprise.gateway.guardrail_service import GuardrailService
from app.enterprise.gateway.models import GatewayRequest
from app.enterprise.gateway.rate_limit_service import NoOpRateLimitService
from app.enterprise.gateway.request_gateway import RequestBlocked, RequestGateway
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink


class EnterpriseRequestGatewayTests(unittest.IsolatedAsyncioTestCase):
    def _build_gateway(self, guardrail_provider=None):
        sink = InMemoryAuditSink()
        gateway = RequestGateway(
            audit_service=AuditService(sinks=[sink]),
            guardrail_service=GuardrailService(
                providers=[guardrail_provider or NoOpGuardrailProvider()]
            ),
            rate_limit_service=NoOpRateLimitService(),
        )
        return gateway, sink

    async def test_success_request_writes_started_and_completed_audit(self):
        gateway, sink = self._build_gateway()
        request = GatewayRequest(
            route="chat",
            payload={"Question": "hello"},
            trace_id="trace-success",
        )

        async def handler(context):
            return {"trace_id": context.trace_id, "answer": "ok"}

        result = await gateway.execute(request, handler)

        self.assertEqual(result["trace_id"], "trace-success")
        self.assertEqual([event.event_type for event in sink.events], [
            "request_started",
            "request_completed",
        ])
        self.assertTrue(all(event.trace_id == "trace-success" for event in sink.events))

    async def test_rule_guardrail_blocks_request_and_writes_failed_audit(self):
        gateway, sink = self._build_gateway(
            RuleGuardrailProvider.from_keywords(
                ["删除日志"],
                reason="禁止删除日志操作",
            )
        )
        request = GatewayRequest(
            route="chat",
            payload={"Question": "请删除日志"},
            trace_id="trace-blocked",
        )
        called = False

        async def handler(_context):
            nonlocal called
            called = True
            return {"answer": "should not happen"}

        with self.assertRaises(RequestBlocked):
            await gateway.execute(request, handler)

        self.assertFalse(called)
        self.assertEqual([event.event_type for event in sink.events], [
            "request_started",
            "request_failed",
        ])
        failed = sink.events[-1]
        self.assertEqual(failed.error_class, "guardrail_blocked")
        self.assertEqual(failed.decision, "blocked")
        self.assertEqual(failed.reason, "禁止删除日志操作")
        self.assertEqual(failed.metadata["recovery_decision"], "abort")
        self.assertEqual(failed.metadata["source_error_class"], "RequestBlocked")

    async def test_failed_request_writes_sanitized_failed_audit(self):
        gateway, sink = self._build_gateway()
        request = GatewayRequest(
            route="upload",
            payload={"filename": "bad.txt"},
            trace_id="trace-failed",
        )

        async def handler(_context):
            raise RuntimeError("boom with /secret/token")

        with self.assertRaises(RuntimeError):
            await gateway.execute(request, handler)

        failed = sink.events[-1]
        self.assertEqual(failed.event_type, "request_failed")
        self.assertEqual(failed.error_class, "tool_failed")
        self.assertEqual(failed.metadata["source_error_class"], "RuntimeError")
        self.assertEqual(failed.metadata["recovery_decision"], "abort")
        self.assertIsNone(failed.error_message)
        self.assertNotIn("traceback", failed.metadata)


if __name__ == "__main__":
    unittest.main()
