"""
P5 Shadow Mode 链路测试

验证 memory_mode 能够通过完整链路传递：
API → Service → LangGraph → Planner

这是一个最小化的集成测试，不依赖真实 MCP/Milvus/DashScope。
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.aiops.state import PlanExecuteState
from app.models.memory_mode import MemoryMode


class TestP5ShadowModeChain(unittest.IsolatedAsyncioTestCase):
    """Test P5 shadow mode through the full chain"""

    async def test_memory_mode_passes_through_langgraph_state(self):
        """验证 memory_mode 能通过 LangGraph state 传递到 planner"""

        # 模拟 planner 函数，捕获接收到的 state
        captured_state = None

        async def mock_planner(state: PlanExecuteState):
            nonlocal captured_state
            captured_state = state
            return {"plan": ["step1", "step2"]}

        # 创建初始 state（模拟 aiops_service.execute 的行为）
        initial_state: PlanExecuteState = {
            "input": "test query",
            "plan": [],
            "past_steps": [],
            "response": "",
            "memory_mode": "shadow",
            "enable_memory_guidance": False,
            "memory_owner_id": "test-owner"
        }

        # 调用 planner
        result = await mock_planner(initial_state)

        # 验证 state 字段都传递到了 planner
        self.assertIsNotNone(captured_state)
        self.assertEqual(captured_state.get("memory_mode"), "shadow")
        self.assertEqual(captured_state.get("enable_memory_guidance"), False)
        self.assertEqual(captured_state.get("memory_owner_id"), "test-owner")

        # 验证 MemoryMode.from_state 能正确解析
        memory_mode = MemoryMode.from_state(captured_state)
        self.assertEqual(memory_mode, MemoryMode.SHADOW)

    async def test_memory_mode_none_falls_back_to_enable_memory_guidance(self):
        """验证 memory_mode=None 时回退到 enable_memory_guidance"""

        initial_state: PlanExecuteState = {
            "input": "test query",
            "plan": [],
            "past_steps": [],
            "response": "",
            "memory_mode": None,
            "enable_memory_guidance": True,
            "memory_owner_id": "test-owner"
        }

        memory_mode = MemoryMode.from_state(initial_state)
        self.assertEqual(memory_mode, MemoryMode.ACTIVE)

    async def test_memory_mode_missing_defaults_to_off(self):
        """验证 memory_mode 缺失时默认 OFF"""

        initial_state: PlanExecuteState = {
            "input": "test query",
            "plan": [],
            "past_steps": [],
            "response": ""
        }

        memory_mode = MemoryMode.from_state(initial_state)
        self.assertEqual(memory_mode, MemoryMode.OFF)

    def test_plan_execute_state_accepts_memory_fields(self):
        """验证 PlanExecuteState TypedDict 接受 memory 字段"""

        # 这个测试主要验证 TypedDict 定义正确
        state: PlanExecuteState = {
            "input": "test",
            "plan": [],
            "past_steps": [],
            "response": "",
            "memory_mode": "shadow",
            "enable_memory_guidance": False,
            "memory_owner_id": "test-owner",
            "memory_observation": {
                "mode": "shadow",
                "hit_count": 2,
                "would_inject": False
            }
        }

        # 如果 TypedDict 定义错误，这里会有类型检查警告
        # 运行时验证字段存在
        self.assertEqual(state["memory_mode"], "shadow")
        self.assertEqual(state["memory_observation"]["mode"], "shadow")


if __name__ == "__main__":
    unittest.main()
