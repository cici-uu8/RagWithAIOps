"""
Shadow Mode 监控指标 API
"""

from fastapi import APIRouter
from app.services.shadow_mode_metrics import shadow_metrics

router = APIRouter()


@router.get("/shadow-metrics")
async def get_shadow_metrics():
    """
    获取 shadow mode 监控指标

    **返回示例：**
    ```json
    {
      "requests_total": 1250,
      "requests_shadow_enabled": 125,
      "requests_shadow_disabled": 1125,
      "allowlist_hits": 100,
      "sampling_hits": 25,
      "memory_recalls": 125,
      "memory_recall_errors": 2,
      "trace_writes": 125,
      "trace_write_errors": 0,
      "memory_recall_latency_p50": 45.2,
      "memory_recall_latency_p95": 120.5,
      "memory_recall_latency_p99": 180.3,
      "last_reset": "2026-05-26T10:30:00"
    }
    ```

    **使用示例：**
    ```bash
    curl http://localhost:9900/api/shadow-metrics
    ```

    Returns:
        当前指标快照
    """
    return shadow_metrics.get_metrics()


@router.post("/shadow-metrics/reset")
async def reset_shadow_metrics():
    """
    重置 shadow mode 监控指标

    **使用示例：**
    ```bash
    curl -X POST http://localhost:9900/api/shadow-metrics/reset
    ```

    Returns:
        操作结果
    """
    shadow_metrics.reset()
    return {"status": "ok", "message": "Shadow mode metrics reset"}
