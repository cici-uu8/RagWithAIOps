"""
P5 Shadow Mode 流量控制

提供白名单和采样率控制，决定哪些请求进入 shadow mode。
这是外层控制逻辑，不侵入 planner 内部。
"""

import random
from typing import Optional
from loguru import logger


class ShadowModeController:
    """Shadow mode 流量控制器"""

    def __init__(
        self,
        allowlist: Optional[list[str]] = None,
        sampling_rate: float = 0.0
    ):
        """
        初始化流量控制器

        Args:
            allowlist: owner_id 白名单，优先级最高
            sampling_rate: 采样率 (0.0 - 1.0)，白名单外的流量按此比例进入 shadow
        """
        self.allowlist = set(allowlist or [])
        self.sampling_rate = max(0.0, min(1.0, sampling_rate))

    def should_enable_shadow(self, owner_id: str) -> bool:
        """
        判断是否应该为该 owner 启用 shadow mode

        Args:
            owner_id: Memory owner ID

        Returns:
            True if shadow mode should be enabled
        """
        # 白名单优先
        if owner_id in self.allowlist:
            logger.info(f"[SHADOW-CONTROL] owner={owner_id} in allowlist, enable shadow")
            return True

        # 采样率
        if random.random() < self.sampling_rate:
            logger.info(f"[SHADOW-CONTROL] owner={owner_id} sampled in (rate={self.sampling_rate}), enable shadow")
            return True

        logger.debug(f"[SHADOW-CONTROL] owner={owner_id} not in allowlist and sampled out, skip shadow")
        return False

    def resolve_memory_mode(
        self,
        requested_mode: Optional[str],
        owner_id: str,
        enable_memory_guidance: bool = False
    ) -> str:
        """
        解析最终的 memory_mode

        优先级：
        1. 如果 requested_mode 显式指定，直接使用（允许强制 off/active）
        2. 如果 requested_mode 是 "shadow"，检查流量控制
        3. 如果 requested_mode 未指定，回退到 enable_memory_guidance 兼容逻辑

        Args:
            requested_mode: 请求中的 memory_mode
            owner_id: Memory owner ID
            enable_memory_guidance: 旧 API 兼容 flag

        Returns:
            最终的 memory_mode: "off" | "shadow" | "active"
        """
        # 显式指定 off 或 active，直接使用
        if requested_mode in ["off", "active"]:
            logger.info(f"[SHADOW-CONTROL] explicit mode={requested_mode}, use as-is")
            return requested_mode

        # 显式指定 shadow，检查流量控制
        if requested_mode == "shadow":
            if self.should_enable_shadow(owner_id):
                return "shadow"
            else:
                logger.info(f"[SHADOW-CONTROL] shadow requested but not allowed, fallback to off")
                return "off"

        # 未指定 memory_mode，回退到旧 flag
        if enable_memory_guidance:
            logger.info(f"[SHADOW-CONTROL] no memory_mode, enable_memory_guidance=True, use active")
            return "active"

        logger.debug(f"[SHADOW-CONTROL] no memory_mode, enable_memory_guidance=False, use off")
        return "off"
