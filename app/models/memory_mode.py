"""
Memory Mode Enum for P5 Shadow Mode

定义 memory 在 planner 中的三种模式：
- OFF: 不召回 memory（默认）
- SHADOW: 召回 + 格式化 + 记录，但不进 prompt
- ACTIVE: 召回 + 格式化 + 进 prompt
"""

from enum import Enum


class MemoryMode(str, Enum):
    """Memory 模式枚举"""

    OFF = "off"          # 默认，不召回 memory
    SHADOW = "shadow"    # 召回 + 格式化 + 记录，不进 prompt
    ACTIVE = "active"    # 召回 + 格式化 + 进 prompt

    @classmethod
    def from_state(cls, state: dict) -> "MemoryMode":
        """
        从 state 中解析 memory_mode

        兼容旧的 enable_memory_guidance flag：
        - enable_memory_guidance=True → ACTIVE
        - enable_memory_guidance=False 或未设置 → OFF
        - memory_mode 显式设置时优先使用

        Args:
            state: planner state

        Returns:
            MemoryMode 枚举值
        """
        # 优先使用新的 memory_mode。
        # 但如果显式传入 None，视为“未设置”，回退到旧的 enable_memory_guidance 兼容逻辑。
        mode_value = state.get("memory_mode", None)
        if mode_value is not None:
            try:
                return cls(mode_value)
            except ValueError:
                # 无效值，fallback 到 OFF
                return cls.OFF

        # 兼容旧的 enable_memory_guidance
        if state.get("enable_memory_guidance", False):
            return cls.ACTIVE

        return cls.OFF

    @classmethod
    def from_config(cls, value: str | None) -> "MemoryMode":
        """Parse memory mode from config, falling back to OFF for invalid values."""
        if value is None:
            return cls.OFF
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.OFF
