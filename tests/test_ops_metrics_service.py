import unittest
from datetime import UTC, datetime, timedelta

from app.enterprise.context import RequestContext
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.observability.models import AuditEvent


def _context() -> RequestContext:
    return RequestContext(
        request_id="request-ops-service",
        trace_id="trace-ops-service",
        user_id="user_admin",
        username="admin",
        department_id="system",
        department_name="System",
        roles=["admin"],
    )


class OpsMetricsServiceTests(unittest.TestCase):
    def setUp(self):
        from app.enterprise.admin.ops_metrics_service import OpsMetricsService

        self.now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        self.sink = InMemoryAuditSink()
        self.audit_service = AuditService(sinks=[self.sink])
        self.service = OpsMetricsService(
            audit_service=self.audit_service,
            now_provider=lambda: self.now,
        )
        self.context = _context()

    def _record(
        self,
        *,
        event_type: str,
        route: str,
        user_id: str,
        minutes_ago: int,
        latency_ms: float | None = None,
        trace_id: str = "trace-ops-event",
        request_id: str = "request-ops-event",
        decision: str = "allowed",
        reason: str | None = None,
        error_class: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.audit_service.record(
            AuditEvent(
                event_type=event_type,
                route=route,
                trace_id=trace_id,
                request_id=request_id,
                user_id=user_id,
                timestamp=self.now - timedelta(minutes=minutes_ago),
                decision=decision,
                reason=reason,
                error_class=error_class,
                latency_ms=latency_ms,
                metadata=metadata or {},
            )
        )

    def test_summary_aggregates_request_latency_top_lists_and_excludes_cost(self):
        self._record(
            event_type="request_completed",
            route="chat",
            user_id="user_a",
            minutes_ago=10,
            latency_ms=100,
        )
        self._record(
            event_type="request_completed",
            route="chat",
            user_id="user_a",
            minutes_ago=8,
            latency_ms=200,
        )
        self._record(
            event_type="request_completed",
            route="aiops",
            user_id="user_b",
            minutes_ago=6,
            latency_ms=900,
        )
        self._record(
            event_type="request_failed",
            route="database",
            user_id="user_b",
            minutes_ago=4,
            decision="failed",
            error_class="tool_failed",
        )
        self._record(
            event_type="tool_call",
            route="tool_gateway",
            user_id="user_a",
            minutes_ago=3,
            metadata={"tool_id": "retrieve_knowledge"},
        )
        self._record(
            event_type="database_query",
            route="database_demo",
            user_id="user_b",
            minutes_ago=2,
            metadata={"tool_name": "database_demo.safe_select"},
        )
        self._record(
            event_type="model_call",
            route="model_gateway",
            user_id="user_b",
            minutes_ago=1,
            metadata={"usage": {"total_tokens": 999}, "total_cost": 123.45},
        )

        summary = self.service.get_summary(self.context, "24h")

        self.assertEqual(summary["total_requests"], 4)
        self.assertEqual(summary["success_count"], 3)
        self.assertEqual(summary["failed_count"], 1)
        self.assertAlmostEqual(summary["success_rate"], 0.75)
        self.assertEqual(summary["p50_latency_ms"], 200)
        self.assertEqual(summary["p95_latency_ms"], 900)
        self.assertEqual(summary["avg_latency_ms"], 400)
        self.assertEqual(summary["top_users"][0], {"user_id": "user_a", "count": 2})
        self.assertEqual(summary["top_routes"][0], {"route": "chat", "count": 2})
        self.assertEqual(
            summary["top_tools"],
            [
                {"tool": "retrieve_knowledge", "count": 1},
                {"tool": "database_demo.safe_select", "count": 1},
            ],
        )
        self.assertNotIn("total_cost", summary)
        self.assertNotIn("cost_by_user", summary)
        self.assertNotIn("cost_by_model", summary)

    def test_timeline_groups_requests_by_bucket(self):
        self._record(
            event_type="request_completed",
            route="chat",
            user_id="user_a",
            minutes_ago=70,
            latency_ms=100,
        )
        self._record(
            event_type="request_failed",
            route="chat",
            user_id="user_a",
            minutes_ago=65,
            decision="failed",
            error_class="tool_failed",
        )
        self._record(
            event_type="request_completed",
            route="aiops",
            user_id="user_b",
            minutes_ago=5,
            latency_ms=200,
        )

        timeline = self.service.get_timeline(self.context, "24h", "1h")

        self.assertEqual(
            timeline,
            [
                {
                    "time_bucket": "2026-06-16T10:00:00+00:00",
                    "total": 2,
                    "success": 1,
                    "failed": 1,
                    "success_rate": 0.5,
                },
                {
                    "time_bucket": "2026-06-16T11:00:00+00:00",
                    "total": 1,
                    "success": 1,
                    "failed": 0,
                    "success_rate": 1.0,
                },
            ],
        )

    def test_failures_include_failure_semantics_and_recovered_status(self):
        self._record(
            event_type="request_failed",
            route="aiops",
            user_id="user_b",
            minutes_ago=20,
            trace_id="trace-failed-old",
            request_id="request-failed-old",
            decision="failed",
            reason="structured output failed",
            error_class="tool_failed",
            metadata={"failure_semantics": "structured_output_failed", "recovered": False},
        )
        self._record(
            event_type="request_failed",
            route="chat",
            user_id="user_a",
            minutes_ago=10,
            trace_id="trace-failed-new",
            request_id="request-failed-new",
            decision="failed",
            reason="guardrail blocked",
            error_class="guardrail_blocked",
            metadata={"failure_semantics": "guardrail_blocked", "recovered": True},
        )

        failures = self.service.get_failures(self.context, "24h", limit=1)

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["trace_id"], "trace-failed-new")
        self.assertEqual(failures[0]["request_id"], "request-failed-new")
        self.assertEqual(failures[0]["route"], "chat")
        self.assertEqual(failures[0]["failure_semantics"], "guardrail_blocked")
        self.assertTrue(failures[0]["recovered"])
        self.assertEqual(failures[0]["error_class"], "guardrail_blocked")


if __name__ == "__main__":
    unittest.main()
