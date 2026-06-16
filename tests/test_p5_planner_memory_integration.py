"""
P5 planner memory integration tests

验证:
- memory guidance 默认关闭
- enable_memory_guidance=True 时才查询 memory
- memory guidance 和 document context 正确合并
- memory 召回失败不影响主流程
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.aiops.planner import planner, Plan
from app.models.memory_mode import MemoryMode
from app.services.memory_guidance_provider import MemoryGuidanceResult


class TestP5PlannerMemoryIntegration(unittest.IsolatedAsyncioTestCase):
    """Test P5 planner memory integration"""

    async def test_memory_guidance_disabled_by_default(self):
        """P5 memory guidance 默认关闭"""
        state = {
            "input": "CPUHigh alert on service-a",
            # enable_memory_guidance 未设置，默认 False
        }

        with patch("app.agent.aiops.planner.retrieve_knowledge") as mock_retrieve, \
             patch("app.agent.aiops.planner.get_mcp_tools_with_retry") as mock_mcp, \
             patch("app.agent.aiops.planner.planner_prompt") as mock_prompt, \
             patch("app.agent.aiops.planner.ChatQwen") as mock_chat, \
             patch("app.agent.aiops.planner.memory_guidance_provider") as mock_provider:

            # Mock retrieve_knowledge
            mock_retrieve.ainvoke = AsyncMock(return_value="")

            # Mock MCP client
            mock_mcp.return_value = []
            mock_llm = MagicMock()
            mock_llm.with_structured_output.return_value = MagicMock()
            mock_chat.return_value = mock_llm

            # Mock planner_prompt pipe chain
            mock_chain = MagicMock()
            mock_chain.ainvoke = AsyncMock(return_value=Plan(steps=["step1", "step2"]))
            mock_prompt.__or__ = MagicMock(return_value=mock_chain)
            mock_provider.build.return_value = MemoryGuidanceResult(
                guidance_text="",
                observation=None,
                mode=MemoryMode.OFF,
            )

            result = await planner(state)

            # planner 只调用 provider；off 模式下 provider 返回空 guidance
            mock_provider.build.assert_called_once_with(state)

            # 验证返回了计划
            self.assertIn("plan", result)
            self.assertIsInstance(result["plan"], list)
            self.assertEqual(result["plan"], ["step1", "step2"])

    async def test_memory_guidance_enabled_queries_memory(self):
        """enable_memory_guidance=True 时查询 memory"""
        state = {
            "input": "CPUHigh alert on service-a",
            "enable_memory_guidance": True,
            "memory_owner_id": "test-owner",
        }

        with patch("app.agent.aiops.planner.retrieve_knowledge") as mock_retrieve, \
             patch("app.agent.aiops.planner.get_mcp_tools_with_retry") as mock_mcp, \
             patch("app.agent.aiops.planner.planner_prompt") as mock_prompt, \
             patch("app.agent.aiops.planner.ChatQwen") as mock_chat, \
             patch("app.agent.aiops.planner.memory_guidance_provider") as mock_provider:

            # Mock retrieve_knowledge
            mock_retrieve.ainvoke = AsyncMock(return_value="")

            # Mock MCP client
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

            # Mock planner_prompt pipe chain
            mock_chain = MagicMock()
            mock_chain.ainvoke = AsyncMock(return_value=Plan(steps=["step1", "step2"]))
            mock_prompt.__or__ = MagicMock(return_value=mock_chain)

            result = await planner(state)

            # 检索细节由 MemoryGuidanceProvider 测试覆盖；planner 只负责消费结果
            mock_provider.build.assert_called_once_with(state)

            # 验证返回了计划
            self.assertIn("plan", result)
            self.assertEqual(result["plan"], ["step1", "step2"])
            self.assertEqual(result["memory_observation"]["memory_ids"], ["mem_001"])

    async def test_memory_guidance_failure_does_not_break_planner(self):
        """memory 召回失败不影响主流程"""
        state = {
            "input": "CPUHigh alert",
            "enable_memory_guidance": True,
        }

        with patch("app.agent.aiops.planner.retrieve_knowledge") as mock_retrieve, \
             patch("app.agent.aiops.planner.get_mcp_tools_with_retry") as mock_mcp, \
             patch("app.agent.aiops.planner.planner_prompt") as mock_prompt, \
             patch("app.agent.aiops.planner.ChatQwen") as mock_chat, \
             patch("app.agent.aiops.planner.memory_guidance_provider") as mock_provider:

            # Mock retrieve_knowledge
            mock_retrieve.ainvoke = AsyncMock(return_value="doc context")

            # Mock MCP client
            mock_mcp.return_value = []
            mock_llm = MagicMock()
            mock_llm.with_structured_output.return_value = MagicMock()
            mock_chat.return_value = mock_llm

            # Mock provider to raise exception
            mock_provider.build.side_effect = Exception("memory store unavailable")

            # Mock planner_prompt pipe chain
            mock_chain = MagicMock()
            mock_chain.ainvoke = AsyncMock(return_value=Plan(steps=["step1"]))
            mock_prompt.__or__ = MagicMock(return_value=mock_chain)

            # 应该不抛异常
            result = await planner(state)

            # 验证仍然返回了计划
            self.assertIn("plan", result)
            self.assertIsInstance(result["plan"], list)
            self.assertGreater(len(result["plan"]), 0)
            self.assertEqual(result["plan"], ["step1"])

    async def test_memory_guidance_combined_with_document_context(self):
        """memory guidance 和 document context 正确合并"""
        state = {
            "input": "DiskHigh alert",
            "enable_memory_guidance": True,
        }

        captured_context = None

        with patch("app.agent.aiops.planner.retrieve_knowledge") as mock_retrieve, \
             patch("app.agent.aiops.planner.get_mcp_tools_with_retry") as mock_mcp, \
             patch("app.agent.aiops.planner.planner_prompt") as mock_prompt, \
             patch("app.agent.aiops.planner.ChatQwen") as mock_chat, \
             patch("app.agent.aiops.planner.memory_guidance_provider") as mock_provider:

            # Mock retrieve_knowledge 返回文档上下文
            mock_retrieve.ainvoke = AsyncMock(return_value="Document: check disk usage")

            # Mock MCP client
            mock_mcp.return_value = []
            mock_llm = MagicMock()
            mock_llm.with_structured_output.return_value = MagicMock()
            mock_chat.return_value = mock_llm

            # Mock provider 返回 memory guidance
            mock_provider.build.return_value = MemoryGuidanceResult(
                guidance_text="## 运行时记忆指导\n\nDisk alert plan",
                observation={
                    "mode": "active",
                    "trace_id": "mem_trace_test",
                    "hit_count": 1,
                    "memory_ids": ["mem_plan_001"],
                    "would_inject": True,
                },
                mode=MemoryMode.ACTIVE,
            )

            # Mock planner_prompt pipe chain，捕获传入的 experience_context
            mock_chain = MagicMock()

            async def capture_ainvoke(args):
                nonlocal captured_context
                captured_context = args.get("experience_context", "")
                return Plan(steps=["step1"])

            mock_chain.ainvoke = capture_ainvoke
            mock_prompt.__or__ = MagicMock(return_value=mock_chain)

            result = await planner(state)

            # 验证 experience_context 包含 memory guidance 和 document context
            self.assertIsNotNone(captured_context)
            self.assertIn("运行时记忆指导", captured_context)  # memory guidance
            self.assertIn("相关经验文档", captured_context)  # document context
            self.assertIn("check disk usage", captured_context)  # document content

            # 验证 memory 在 document 之前
            memory_pos = captured_context.find("运行时记忆指导")
            doc_pos = captured_context.find("相关经验文档")
            self.assertLess(memory_pos, doc_pos)


if __name__ == "__main__":
    unittest.main()
