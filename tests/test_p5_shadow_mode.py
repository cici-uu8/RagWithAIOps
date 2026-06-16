"""
P5 Shadow Mode Tests

验证:
- MemoryMode.from_state() 正确解析 state
- memory_mode=off 不召回 memory
- memory_mode=shadow 召回但不注入 prompt
- memory_mode=active 召回且注入 prompt
- shadow mode 生成 trace 文件
- 兼容旧的 enable_memory_guidance flag
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.aiops.planner import planner, Plan
from app.models.memory_mode import MemoryMode
from app.services.memory_guidance_provider import MemoryGuidanceResult


class TestMemoryMode(unittest.TestCase):
    """Test MemoryMode enum"""

    def test_from_state_explicit_off(self):
        """显式设置 memory_mode=off"""
        state = {"memory_mode": "off"}
        mode = MemoryMode.from_state(state)
        self.assertEqual(mode, MemoryMode.OFF)

    def test_from_state_explicit_shadow(self):
        """显式设置 memory_mode=shadow"""
        state = {"memory_mode": "shadow"}
        mode = MemoryMode.from_state(state)
        self.assertEqual(mode, MemoryMode.SHADOW)

    def test_from_state_explicit_active(self):
        """显式设置 memory_mode=active"""
        state = {"memory_mode": "active"}
        mode = MemoryMode.from_state(state)
        self.assertEqual(mode, MemoryMode.ACTIVE)

    def test_from_state_invalid_fallback_to_off(self):
        """无效值 fallback 到 OFF"""
        state = {"memory_mode": "invalid"}
        mode = MemoryMode.from_state(state)
        self.assertEqual(mode, MemoryMode.OFF)

    def test_from_state_legacy_enable_memory_guidance_true(self):
        """兼容旧的 enable_memory_guidance=True"""
        state = {"enable_memory_guidance": True}
        mode = MemoryMode.from_state(state)
        self.assertEqual(mode, MemoryMode.ACTIVE)

    def test_from_state_legacy_enable_memory_guidance_false(self):
        """兼容旧的 enable_memory_guidance=False"""
        state = {"enable_memory_guidance": False}
        mode = MemoryMode.from_state(state)
        self.assertEqual(mode, MemoryMode.OFF)

    def test_from_state_default_off(self):
        """默认 OFF"""
        state = {}
        mode = MemoryMode.from_state(state)
        self.assertEqual(mode, MemoryMode.OFF)

    def test_from_state_explicit_overrides_legacy(self):
        """显式 memory_mode 优先于 enable_memory_guidance"""
        state = {
            "memory_mode": "shadow",
            "enable_memory_guidance": True
        }
        mode = MemoryMode.from_state(state)
        self.assertEqual(mode, MemoryMode.SHADOW)


class TestP5ShadowMode(unittest.IsolatedAsyncioTestCase):
    """Test P5 shadow mode integration"""

    async def test_memory_mode_off_no_retrieval(self):
        """memory_mode=off 不召回 memory"""
        state = {
            "input": "CPUHigh alert on service-a",
            "memory_mode": "off",
        }

        with patch("app.agent.aiops.planner.retrieve_knowledge") as mock_retrieve, \
             patch("app.agent.aiops.planner.get_mcp_tools_with_retry") as mock_mcp, \
             patch("app.agent.aiops.planner.planner_prompt") as mock_prompt, \
             patch("app.agent.aiops.planner.ChatQwen") as mock_chat, \
             patch("app.agent.aiops.planner.memory_guidance_provider") as mock_provider:

            mock_retrieve.ainvoke = AsyncMock(return_value="")
            mock_mcp.return_value = []
            mock_llm = MagicMock()
            mock_llm.with_structured_output.return_value = MagicMock()
            mock_chat.return_value = mock_llm
            mock_provider.build.return_value = MemoryGuidanceResult(
                guidance_text="",
                observation=None,
                mode=MemoryMode.OFF,
            )

            mock_chain = MagicMock()
            mock_chain.ainvoke = AsyncMock(return_value=Plan(steps=["step1"]))
            mock_prompt.__or__ = MagicMock(return_value=mock_chain)

            result = await planner(state)

            # 验证 planner 通过 provider 获取 off 结果
            mock_provider.build.assert_called_once_with(state)

            # 验证返回了计划，但没有 memory_observation
            self.assertIn("plan", result)
            self.assertNotIn("memory_observation", result)

    async def test_memory_mode_shadow_retrieves_but_not_inject(self):
        """memory_mode=shadow 召回但不注入 prompt"""
        state = {
            "input": "CPUHigh alert on service-a",
            "memory_mode": "shadow",
            "memory_owner_id": "test-owner",
        }

        with patch("app.agent.aiops.planner.retrieve_knowledge") as mock_retrieve, \
             patch("app.agent.aiops.planner.get_mcp_tools_with_retry") as mock_mcp, \
             patch("app.agent.aiops.planner.planner_prompt") as mock_prompt, \
             patch("app.agent.aiops.planner.ChatQwen") as mock_chat, \
             patch("app.agent.aiops.planner.memory_guidance_provider") as mock_provider:

            mock_retrieve.ainvoke = AsyncMock(return_value="")
            mock_mcp.return_value = []
            mock_llm = MagicMock()
            mock_llm.with_structured_output.return_value = MagicMock()
            mock_chat.return_value = mock_llm
            mock_provider.build.return_value = MemoryGuidanceResult(
                guidance_text="",
                observation={
                    "mode": "shadow",
                    "trace_id": "mem_trace_test",
                    "hit_count": 1,
                    "memory_ids": ["mem_001"],
                    "would_inject": False,
                    "full_text_path": "traces/memory/mem_trace_test.txt",
                },
                mode=MemoryMode.SHADOW,
            )

            # Mock planner chain - 捕获传入的 experience_context
            captured_context = None

            async def capture_ainvoke(args):
                nonlocal captured_context
                captured_context = args.get("experience_context", "")
                return Plan(steps=["step1"])

            mock_chain = MagicMock()
            mock_chain.ainvoke = AsyncMock(side_effect=capture_ainvoke)
            mock_prompt.__or__ = MagicMock(return_value=mock_chain)

            result = await planner(state)

            # provider 内部负责 memory 召回和 trace 创建
            mock_provider.build.assert_called_once_with(state)

            # 验证返回了 memory_observation
            self.assertIn("memory_observation", result)
            self.assertEqual(result["memory_observation"]["mode"], "shadow")
            self.assertFalse(result["memory_observation"]["would_inject"])

            # 验证 memory guidance 没有注入 prompt
            # captured_context 应该不包含 "运行时记忆指导"
            self.assertNotIn("运行时记忆指导", captured_context)

    async def test_memory_mode_active_retrieves_and_injects(self):
        """memory_mode=active 召回且注入 prompt"""
        state = {
            "input": "CPUHigh alert on service-a",
            "memory_mode": "active",
            "memory_owner_id": "test-owner",
        }

        with patch("app.agent.aiops.planner.retrieve_knowledge") as mock_retrieve, \
             patch("app.agent.aiops.planner.get_mcp_tools_with_retry") as mock_mcp, \
             patch("app.agent.aiops.planner.planner_prompt") as mock_prompt, \
             patch("app.agent.aiops.planner.ChatQwen") as mock_chat, \
             patch("app.agent.aiops.planner.memory_guidance_provider") as mock_provider:

            mock_retrieve.ainvoke = AsyncMock(return_value="")
            mock_mcp.return_value = []
            mock_llm = MagicMock()
            mock_llm.with_structured_output.return_value = MagicMock()
            mock_chat.return_value = mock_llm
            mock_provider.build.return_value = MemoryGuidanceResult(
                guidance_text="## 运行时记忆指导\n\nCPUHigh pattern",
                observation={
                    "mode": "active",
                    "trace_id": "mem_trace_test",
                    "hit_count": 1,
                    "memory_ids": ["mem_001"],
                    "would_inject": True,
                },
                mode=MemoryMode.ACTIVE,
            )

            # Mock planner chain - 捕获传入的 experience_context
            captured_context = None

            async def capture_ainvoke(args):
                nonlocal captured_context
                captured_context = args.get("experience_context", "")
                return Plan(steps=["step1"])

            mock_chain = MagicMock()
            mock_chain.ainvoke = AsyncMock(side_effect=capture_ainvoke)
            mock_prompt.__or__ = MagicMock(return_value=mock_chain)

            result = await planner(state)

            # provider 内部负责 memory 召回和 trace 创建
            mock_provider.build.assert_called_once_with(state)

            # 验证返回了 memory_observation
            self.assertIn("memory_observation", result)
            self.assertEqual(result["memory_observation"]["mode"], "active")
            self.assertTrue(result["memory_observation"]["would_inject"])

            # 验证 memory guidance 注入了 prompt
            # captured_context 应该包含 "运行时记忆指导"
            self.assertIn("运行时记忆指导", captured_context)


if __name__ == "__main__":
    unittest.main()
