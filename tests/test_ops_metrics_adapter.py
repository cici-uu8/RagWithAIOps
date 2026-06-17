import unittest
from datetime import UTC, datetime

from app.enterprise.admin.ops_metrics_adapter import OpsMetricsAdapter
from app.enterprise.context import RequestContext


class FakeOpsMetricsService:
    def __init__(self):
        self.calls = []

    def get_summary(self, context, time_range):
        self.calls.append(("summary", context.user_id, time_range))
        return {
            "total_requests": 1,
            "success_rate": 1.0,
            "p50_latency_ms": 10,
            "p95_latency_ms": 10,
            "top_users": [{"user_id": "user_demo_dept1", "count": 1}],
            "top_routes": [{"route": "chat", "count": 1}],
            "top_tools": [],
        }

    def get_timeline(self, context, time_range, bucket):
        self.calls.append(("timeline", context.user_id, time_range, bucket))
        return [{"time_bucket": datetime(2026, 6, 16, tzinfo=UTC).isoformat(), "total": 1}]

    def get_failures(self, context, time_range, limit):
        self.calls.append(("failures", context.user_id, time_range, limit))
        return [{"trace_id": "trace-failed", "user_id": "user_demo_dept1"}]


def _context(roles=None):
    return RequestContext(
        request_id="request-ops-adapter",
        trace_id="trace-ops-adapter",
        user_id="user_admin",
        username="admin",
        department_id="system",
        department_name="System",
        roles=roles or ["admin"],
    )


class OpsMetricsAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_adapter_delegates_metrics_for_admin_context(self):
        service = FakeOpsMetricsService()
        adapter = OpsMetricsAdapter(service=service)
        context = _context()

        summary = await adapter.get_summary(context, "24h")
        timeline = await adapter.get_timeline(context, "24h", "1h")
        failures = await adapter.get_failures(context, "24h", 20)

        self.assertEqual(summary["total_requests"], 1)
        self.assertEqual(timeline[0]["total"], 1)
        self.assertEqual(failures[0]["trace_id"], "trace-failed")
        self.assertEqual(
            service.calls,
            [
                ("summary", "user_admin", "24h"),
                ("timeline", "user_admin", "24h", "1h"),
                ("failures", "user_admin", "24h", 20),
            ],
        )

    async def test_adapter_validates_time_range_bucket_and_limit(self):
        adapter = OpsMetricsAdapter(service=FakeOpsMetricsService())
        context = _context()

        for bad_range in ("31d", "48h", "yesterday", ""):
            with self.subTest(time_range=bad_range):
                with self.assertRaises(ValueError):
                    await adapter.get_summary(context, bad_range)

        with self.assertRaises(ValueError):
            await adapter.get_timeline(context, "24h", "15m")

        with self.assertRaises(ValueError):
            await adapter.get_failures(context, "24h", 101)

    async def test_adapter_rejects_non_admin_context(self):
        adapter = OpsMetricsAdapter(service=FakeOpsMetricsService())

        with self.assertRaises(PermissionError):
            await adapter.get_summary(_context(roles=["user"]), "24h")


if __name__ == "__main__":
    unittest.main()
