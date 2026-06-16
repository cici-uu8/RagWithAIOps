"""
P5 Shadow Mode 监控指标

提供 shadow mode 运行时的可观测性指标。
"""

from typing import Dict, Any, Optional
from datetime import datetime
from loguru import logger


class ShadowModeMetrics:
    """Shadow mode 监控指标收集器"""

    def __init__(self):
        """初始化指标收集器"""
        self._metrics: Dict[str, Any] = {
            "requests_total": 0,
            "requests_shadow_enabled": 0,
            "requests_shadow_disabled": 0,
            "allowlist_hits": 0,
            "sampling_hits": 0,
            "memory_recalls": 0,
            "memory_recall_errors": 0,
            "trace_writes": 0,
            "trace_write_errors": 0,
            "last_reset": datetime.now().isoformat()
        }
        self._latency_samples: list[float] = []

    def record_request(
        self,
        memory_mode: str,
        owner_id: str,
        hit_allowlist: bool = False,
        hit_sampling: bool = False
    ):
        """
        记录一次请求

        Args:
            memory_mode: 最终的 memory_mode
            owner_id: Memory owner ID
            hit_allowlist: 是否命中白名单
            hit_sampling: 是否命中采样
        """
        self._metrics["requests_total"] += 1

        if memory_mode == "shadow":
            self._metrics["requests_shadow_enabled"] += 1
            if hit_allowlist:
                self._metrics["allowlist_hits"] += 1
            elif hit_sampling:
                self._metrics["sampling_hits"] += 1
        else:
            self._metrics["requests_shadow_disabled"] += 1

        logger.debug(
            f"[SHADOW-METRICS] request recorded: mode={memory_mode}, "
            f"owner={owner_id}, allowlist={hit_allowlist}, sampling={hit_sampling}"
        )

    def record_memory_recall(self, success: bool, latency_ms: Optional[float] = None):
        """
        记录一次 memory recall

        Args:
            success: 是否成功
            latency_ms: 延迟（毫秒）
        """
        if success:
            self._metrics["memory_recalls"] += 1
        else:
            self._metrics["memory_recall_errors"] += 1

        if latency_ms is not None:
            self._latency_samples.append(latency_ms)

        logger.debug(f"[SHADOW-METRICS] memory recall: success={success}, latency={latency_ms}ms")

    def record_trace_write(self, success: bool):
        """
        记录一次 trace 写入

        Args:
            success: 是否成功
        """
        if success:
            self._metrics["trace_writes"] += 1
        else:
            self._metrics["trace_write_errors"] += 1

        logger.debug(f"[SHADOW-METRICS] trace write: success={success}")

    def get_metrics(self) -> Dict[str, Any]:
        """
        获取当前指标快照

        Returns:
            指标字典
        """
        metrics = self._metrics.copy()

        # 计算延迟统计
        if self._latency_samples:
            metrics["memory_recall_latency_p50"] = self._percentile(self._latency_samples, 0.5)
            metrics["memory_recall_latency_p95"] = self._percentile(self._latency_samples, 0.95)
            metrics["memory_recall_latency_p99"] = self._percentile(self._latency_samples, 0.99)
        else:
            metrics["memory_recall_latency_p50"] = None
            metrics["memory_recall_latency_p95"] = None
            metrics["memory_recall_latency_p99"] = None

        return metrics

    def reset(self):
        """重置所有指标"""
        self._metrics = {
            "requests_total": 0,
            "requests_shadow_enabled": 0,
            "requests_shadow_disabled": 0,
            "allowlist_hits": 0,
            "sampling_hits": 0,
            "memory_recalls": 0,
            "memory_recall_errors": 0,
            "trace_writes": 0,
            "trace_write_errors": 0,
            "last_reset": datetime.now().isoformat()
        }
        self._latency_samples = []
        logger.info("[SHADOW-METRICS] metrics reset")

    @staticmethod
    def _percentile(samples: list[float], p: float) -> float:
        """计算百分位数"""
        sorted_samples = sorted(samples)
        index = int(len(sorted_samples) * p)
        return sorted_samples[min(index, len(sorted_samples) - 1)]


# 全局指标实例
shadow_metrics = ShadowModeMetrics()
