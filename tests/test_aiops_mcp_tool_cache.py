import unittest
from unittest.mock import AsyncMock, patch

from app.agent import mcp_client


class FakeMCPClient:
    def __init__(self, tools):
        self.tools = tools
        self.get_tools = AsyncMock(return_value=tools)


class AIOpsMCPToolCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        if hasattr(mcp_client, "_clear_mcp_tools_cache"):
            mcp_client._clear_mcp_tools_cache()
        if hasattr(mcp_client, "_reset_mcp_tools_metrics"):
            mcp_client._reset_mcp_tools_metrics()

    def tearDown(self):
        if hasattr(mcp_client, "_clear_mcp_tools_cache"):
            mcp_client._clear_mcp_tools_cache()
        if hasattr(mcp_client, "_reset_mcp_tools_metrics"):
            mcp_client._reset_mcp_tools_metrics()

    async def test_default_mcp_tools_are_reused_within_ttl(self):
        fake_client = FakeMCPClient(tools=["tool-a", "tool-b"])

        with patch(
            "app.agent.mcp_client.get_mcp_client_with_retry",
            new=AsyncMock(return_value=fake_client),
        ):
            first = await mcp_client.get_mcp_tools_with_retry()
            second = await mcp_client.get_mcp_tools_with_retry()

        self.assertEqual(first, ["tool-a", "tool-b"])
        self.assertEqual(second, ["tool-a", "tool-b"])
        self.assertEqual(fake_client.get_tools.await_count, 1)

    async def test_default_path_records_cache_hit_miss_and_latency_metrics(self):
        fake_client = FakeMCPClient(tools=["tool-a", "tool-b"])

        with patch(
            "app.agent.mcp_client.get_mcp_client_with_retry",
            new=AsyncMock(return_value=fake_client),
        ), patch(
            "app.agent.mcp_client.time.perf_counter",
            side_effect=[10.0, 10.025],
        ):
            await mcp_client.get_mcp_tools_with_retry()
            await mcp_client.get_mcp_tools_with_retry()

        metrics = mcp_client.get_mcp_tools_metrics()
        self.assertEqual(metrics["cache_hits"], 1)
        self.assertEqual(metrics["cache_misses"], 1)
        self.assertEqual(metrics["get_tools_attempts"], 1)
        self.assertEqual(metrics["get_tools_successes"], 1)
        self.assertEqual(metrics["get_tools_failures"], 0)
        self.assertEqual(metrics["fresh_retries"], 0)
        self.assertEqual(metrics["last_tool_count"], 2)
        self.assertEqual(metrics["get_tools_latency_ms"]["count"], 1)
        self.assertAlmostEqual(metrics["get_tools_latency_ms"]["last"], 25.0)
        self.assertAlmostEqual(metrics["get_tools_latency_ms"]["avg"], 25.0)

    async def test_mcp_tools_cache_refreshes_after_ttl(self):
        first_client = FakeMCPClient(tools=["old-tool"])
        second_client = FakeMCPClient(tools=["new-tool"])

        with patch(
            "app.agent.mcp_client.get_mcp_client_with_retry",
            new=AsyncMock(side_effect=[first_client, second_client]),
        ), patch(
            "app.agent.mcp_client._MCP_TOOLS_CACHE_TTL_SECONDS",
            1.0,
        ), patch(
            "app.agent.mcp_client.time.monotonic",
            side_effect=[100.0, 102.5, 102.5],
        ):
            first = await mcp_client.get_mcp_tools_with_retry()
            second = await mcp_client.get_mcp_tools_with_retry()

        self.assertEqual(first, ["old-tool"])
        self.assertEqual(second, ["new-tool"])
        self.assertEqual(first_client.get_tools.await_count, 1)
        self.assertEqual(second_client.get_tools.await_count, 1)

    async def test_fresh_retry_success_is_cached(self):
        broken_client = FakeMCPClient(tools=[])
        broken_client.get_tools = AsyncMock(side_effect=RuntimeError("stale client"))
        fresh_client = FakeMCPClient(tools=["fresh-tool"])

        with patch(
            "app.agent.mcp_client.get_mcp_client_with_retry",
            new=AsyncMock(side_effect=[broken_client, fresh_client]),
        ):
            first = await mcp_client.get_mcp_tools_with_retry()
            second = await mcp_client.get_mcp_tools_with_retry()

        self.assertEqual(first, ["fresh-tool"])
        self.assertEqual(second, ["fresh-tool"])
        self.assertEqual(broken_client.get_tools.await_count, 1)
        self.assertEqual(fresh_client.get_tools.await_count, 1)

        metrics = mcp_client.get_mcp_tools_metrics()
        self.assertEqual(metrics["cache_hits"], 1)
        self.assertEqual(metrics["cache_misses"], 1)
        self.assertEqual(metrics["get_tools_attempts"], 2)
        self.assertEqual(metrics["get_tools_successes"], 1)
        self.assertEqual(metrics["get_tools_failures"], 1)
        self.assertEqual(metrics["fresh_retries"], 1)
        self.assertEqual(metrics["fresh_retry_successes"], 1)
        self.assertEqual(metrics["fresh_retry_failures"], 0)
        self.assertEqual(metrics["last_tool_count"], 1)

    async def test_fresh_retry_failure_records_metrics_before_raising(self):
        broken_client = FakeMCPClient(tools=[])
        broken_client.get_tools = AsyncMock(side_effect=RuntimeError("stale client"))
        still_broken_client = FakeMCPClient(tools=[])
        still_broken_client.get_tools = AsyncMock(side_effect=RuntimeError("fresh failed"))

        with patch(
            "app.agent.mcp_client.get_mcp_client_with_retry",
            new=AsyncMock(side_effect=[broken_client, still_broken_client]),
        ):
            with self.assertRaisesRegex(RuntimeError, "fresh failed"):
                await mcp_client.get_mcp_tools_with_retry()

        metrics = mcp_client.get_mcp_tools_metrics()
        self.assertEqual(metrics["cache_hits"], 0)
        self.assertEqual(metrics["cache_misses"], 1)
        self.assertEqual(metrics["get_tools_attempts"], 2)
        self.assertEqual(metrics["get_tools_successes"], 0)
        self.assertEqual(metrics["get_tools_failures"], 2)
        self.assertEqual(metrics["fresh_retries"], 1)
        self.assertEqual(metrics["fresh_retry_successes"], 0)
        self.assertEqual(metrics["fresh_retry_failures"], 1)
        self.assertIn("RuntimeError: fresh failed", metrics["last_error"])


if __name__ == "__main__":
    unittest.main()
