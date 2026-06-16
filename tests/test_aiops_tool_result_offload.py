import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.agent.aiops.executor import executor
from app.services.session_memory_store import SessionToolResultOffloadStore


class _NoToolResponse:
    tool_calls = []

    def __init__(self, content: str):
        self.content = content


class _ToolCallResponse:
    content = ""
    tool_calls = [{"name": "fake_tool", "args": {}, "id": "call-1"}]


class _BoundLLM:
    def __init__(self, responses):
        self.responses = list(responses)

    async def ainvoke(self, _messages):
        return self.responses.pop(0)


class _FakeLLM:
    def __init__(self, responses):
        self.bound = _BoundLLM(responses)

    def __call__(self, **_kwargs):
        return self

    def bind_tools(self, _tools):
        return self.bound


class _FakeToolNode:
    def __init__(self, _tools):
        pass

    async def ainvoke(self, _payload):
        return {"messages": []}


def _extract_result_ref(text: str) -> str:
    match = re.search(r"tool_result:[0-9a-f]+", text)
    if not match:
        raise AssertionError(f"result_ref not found in {text!r}")
    return match.group(0)


class AIOpsToolResultOffloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_offload_disabled_keeps_long_result_inline(self):
        long_result = "log line\n" * 80
        fake_llm = _FakeLLM([_NoToolResponse(long_result)])

        with (
            patch("app.agent.aiops.executor.ChatQwen", fake_llm),
            patch(
                "app.agent.aiops.executor.get_mcp_tools_with_retry",
                new=AsyncMock(return_value=[]),
            ),
            patch("app.agent.aiops.executor.config.tool_result_offload_enabled", False),
        ):
            result = await executor({"plan": ["查询日志"], "past_steps": []})

        self.assertEqual(result["past_steps"][0][1], long_result)
        self.assertIsInstance(result["past_steps"][0][1], str)

    async def test_offload_long_result_preserves_full_content_by_owner(self):
        long_result = "service log line\n" * 80
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "sessions.sqlite")
            fake_llm = _FakeLLM([_NoToolResponse(long_result)])

            with (
                patch("app.agent.aiops.executor.ChatQwen", fake_llm),
                patch(
                    "app.agent.aiops.executor.get_mcp_tools_with_retry",
                    new=AsyncMock(return_value=[]),
                ),
                patch("app.agent.aiops.executor.config.tool_result_offload_enabled", True),
                patch("app.agent.aiops.executor.config.tool_result_offload_threshold", 20),
                patch("app.agent.aiops.executor.config.tool_result_offload_max_bytes", 10000),
            ):
                result = await executor(
                    {
                        "plan": ["查询日志"],
                        "past_steps": [],
                        "session_id": "session-1",
                        "memory_owner_id": "owner-1",
                        "memory_store_path": db_path,
                    }
                )

            step_result = result["past_steps"][0][1]
            result_ref = _extract_result_ref(step_result)
            store = SessionToolResultOffloadStore(db_path)

            self.assertIsInstance(step_result, str)
            self.assertIn("完整工具结果已 offload", step_result)
            self.assertNotEqual(step_result, long_result)
            self.assertEqual(
                store.get_result(result_ref, owner_id="owner-1").content,
                long_result,
            )
            self.assertIsNone(store.get_result(result_ref, owner_id="owner-2"))

    async def test_offload_write_failure_keeps_original_result(self):
        long_result = "failure-safe line\n" * 80
        fake_llm = _FakeLLM([_NoToolResponse(long_result)])

        with (
            patch("app.agent.aiops.executor.ChatQwen", fake_llm),
            patch(
                "app.agent.aiops.executor.get_mcp_tools_with_retry",
                new=AsyncMock(return_value=[]),
            ),
            patch("app.agent.aiops.executor.config.tool_result_offload_enabled", True),
            patch("app.agent.aiops.executor.config.tool_result_offload_threshold", 20),
            patch(
                "app.agent.aiops.executor.SessionToolResultOffloadStore.offload_result",
                side_effect=RuntimeError("db is unavailable"),
            ),
        ):
            result = await executor(
                {
                    "plan": ["查询日志"],
                    "past_steps": [],
                    "session_id": "session-1",
                    "memory_owner_id": "owner-1",
                }
            )

        self.assertEqual(result["past_steps"][0][1], long_result)

    async def test_over_max_bytes_keeps_original_result(self):
        long_result = "oversize line\n" * 80
        fake_llm = _FakeLLM([_NoToolResponse(long_result)])

        with (
            patch("app.agent.aiops.executor.ChatQwen", fake_llm),
            patch(
                "app.agent.aiops.executor.get_mcp_tools_with_retry",
                new=AsyncMock(return_value=[]),
            ),
            patch("app.agent.aiops.executor.config.tool_result_offload_enabled", True),
            patch("app.agent.aiops.executor.config.tool_result_offload_threshold", 20),
            patch("app.agent.aiops.executor.config.tool_result_offload_max_bytes", 10),
        ):
            result = await executor(
                {
                    "plan": ["查询日志"],
                    "past_steps": [],
                    "session_id": "session-1",
                    "memory_owner_id": "owner-1",
                }
            )

        self.assertEqual(result["past_steps"][0][1], long_result)

    async def test_required_tool_coverage_survives_offload(self):
        long_result = "root cause evidence\n" * 80
        fake_llm = _FakeLLM([_ToolCallResponse(), _NoToolResponse(long_result)])

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("app.agent.aiops.executor.ChatQwen", fake_llm),
                patch("app.agent.aiops.executor.ToolNode", _FakeToolNode),
                patch(
                    "app.agent.aiops.executor.get_mcp_tools_with_retry",
                    new=AsyncMock(return_value=[]),
                ),
                patch("app.agent.aiops.executor.config.tool_result_offload_enabled", True),
                patch("app.agent.aiops.executor.config.tool_result_offload_threshold", 20),
                patch("app.agent.aiops.executor.config.tool_result_offload_max_bytes", 10000),
            ):
                result = await executor(
                    {
                        "plan": ["调用 fake_tool 查询证据"],
                        "past_steps": [],
                        "session_id": "session-1",
                        "memory_owner_id": "owner-1",
                        "memory_store_path": str(Path(tmpdir) / "sessions.sqlite"),
                    }
                )

        self.assertEqual(result["aiops_executed_tools"], ["fake_tool"])
        self.assertIsInstance(result["past_steps"][0][1], str)
        self.assertIn("tool_result:", result["past_steps"][0][1])


if __name__ == "__main__":
    unittest.main()
