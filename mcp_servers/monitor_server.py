"""智能运维监控 MCP Server

本地实现的监控服务 MCP Server，提供：
- 监控数据查询（CPU、内存、磁盘、网络等）
- 进程信息查询
- 历史工单查询
- 服务信息查询

用于支持运维 Agent 的故障排查场景。
"""

import functools
import json
import logging
import os
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx
from fastmcp import FastMCP

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Monitor_MCP_Server")

mcp = FastMCP("Monitor")

DEFAULT_ALERTMANAGER_URL = "http://localhost:9093"
DEFAULT_PROMETHEUS_URL = "http://localhost:9090"
DEFAULT_CMDB_SQLITE_PATH = "aiops_lab/cmdb/aiops_context.db"
SEVERITY_ORDER = {
    "critical": 0,
    "high": 0,
    "warning": 1,
    "warn": 1,
    "medium": 1,
    "info": 2,
    "low": 3,
}


def log_tool_call(func):
    """装饰器：记录工具调用的日志，包括方法名、参数和返回状态"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        method_name = func.__name__

        # 记录调用信息
        logger.info("=" * 80)
        logger.info(f"调用方法: {method_name}")

        # 记录参数（排除self等）
        if kwargs:
            # 使用 json.dumps 格式化参数，处理可能的序列化错误
            try:
                params_str = json.dumps(kwargs, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                params_str = str(kwargs)
            logger.info(f"参数信息:\n{params_str}")
        else:
            logger.info("参数信息: 无")

        # 执行方法
        try:
            result = func(*args, **kwargs)

            # 记录返回状态
            logger.info("返回状态: SUCCESS")

            # 记录返回结果摘要（避免日志过长）
            if isinstance(result, dict):
                summary = {k: v if not isinstance(v, (list, dict)) else f"<{type(v).__name__} with {len(v)} items>"
                          for k, v in list(result.items())[:5]}
                logger.info(f"返回结果摘要: {json.dumps(summary, ensure_ascii=False)}")
            else:
                logger.info(f"返回结果: {result}")

            logger.info("=" * 80)
            return result

        except Exception as e:
            # 记录错误状态
            logger.error("返回状态: ERROR")
            logger.error(f"错误信息: {str(e)}")
            logger.error("=" * 80)
            raise

    return wrapper


# ============================================================
# 辅助函数
# ============================================================

def parse_time_or_default(time_str: Optional[str], default_offset_hours: int = 0) -> datetime:
    """解析时间字符串或返回默认时间。

    Args:
        time_str: 时间字符串（格式：YYYY-MM-DD HH:MM:SS）
        default_offset_hours: 默认时间偏移（小时）

    Returns:
        datetime: 解析后的时间对象
    """
    if time_str:
        try:
            return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    # 返回默认时间（当前时间 + 偏移）
    return datetime.now() + timedelta(hours=default_offset_hours)


def generate_time_series(base_time: datetime, minutes_offset: int, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """生成时间序列字符串。

    Args:
        base_time: 基准时间
        minutes_offset: 分钟偏移量
        format_str: 时间格式字符串

    Returns:
        str: 格式化的时间字符串
    """
    result_time = base_time + timedelta(minutes=minutes_offset)
    return result_time.strftime(format_str)


def _configured_alertmanager_url() -> str:
    return os.getenv("AIOPS_ALERTMANAGER_URL", DEFAULT_ALERTMANAGER_URL)


def _configured_prometheus_url() -> str:
    return os.getenv("AIOPS_PROMETHEUS_URL", DEFAULT_PROMETHEUS_URL)


def _configured_cmdb_sqlite_path() -> str:
    return os.getenv("AIOPS_CMDB_SQLITE_PATH", DEFAULT_CMDB_SQLITE_PATH)


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _parse_time_to_datetime(value: Any, default_offset_minutes: int = 0) -> datetime:
    if value is None or value == "":
        return datetime.now(timezone.utc) + timedelta(minutes=default_offset_minutes)
    if isinstance(value, bool):
        raise ValueError("time value must not be bool")
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000.0
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            try:
                parsed = datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")
                return parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return datetime.now(timezone.utc) + timedelta(minutes=default_offset_minutes)


def _parse_time_to_epoch_seconds(value: Any, default_offset_minutes: int = 0) -> float:
    return _parse_time_to_datetime(value, default_offset_minutes).timestamp()


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _summarize_values(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    sorted_values = sorted(values)
    p95_index = min(len(sorted_values) - 1, int(len(sorted_values) * 0.95))
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "avg": round(sum(values) / len(values), 4),
        "p95": round(sorted_values[p95_index], 4),
    }


def _alert_severity_rank(severity: Any) -> int:
    return SEVERITY_ORDER.get(str(severity or "").lower(), 99)


def _alert_sort_time(alert: dict[str, Any]) -> float:
    value = alert.get("updated_at") or alert.get("starts_at")
    if not value:
        return 0.0
    return _parse_time_to_datetime(value).timestamp()


def _query_active_alerts(
    alertmanager_url: str | None = None,
    http_get=httpx.get,
) -> dict[str, Any]:
    base_url = alertmanager_url or _configured_alertmanager_url()
    url = _join_url(base_url, "/api/v2/alerts")
    params = {"active": "true", "silenced": "false", "inhibited": "false"}
    response = http_get(url, params=params, timeout=10.0)
    response.raise_for_status()
    payload = response.json()
    raw_alerts = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_alerts, list):
        raw_alerts = []

    alerts = []
    for item in raw_alerts:
        if not isinstance(item, dict):
            continue
        labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
        annotations = item.get("annotations") if isinstance(item.get("annotations"), dict) else {}
        status = item.get("status") if isinstance(item.get("status"), dict) else {}
        alerts.append(
            {
                "alert_name": labels.get("alertname") or labels.get("alert_name") or "unknown",
                "service_name": (
                    labels.get("service_name")
                    or labels.get("service")
                    or labels.get("job")
                    or labels.get("instance")
                    or "unknown"
                ),
                "severity": labels.get("severity", "unknown"),
                "state": status.get("state", "active"),
                "starts_at": item.get("startsAt"),
                "updated_at": item.get("updatedAt"),
                "ends_at": item.get("endsAt"),
                "summary": annotations.get("summary") or annotations.get("description") or "",
                "labels": labels,
                "annotations": annotations,
            }
        )

    alerts.sort(key=_alert_sort_time, reverse=True)
    alerts.sort(key=lambda alert: _alert_severity_rank(alert.get("severity")))
    return {
        "source": "alertmanager",
        "alertmanager_url": base_url,
        "total": len(alerts),
        "alerts": alerts,
    }


def _query_metric_series(
    service_name: str,
    metric_name: str,
    start_time: Any = None,
    end_time: Any = None,
    step: str = "30s",
    prometheus_url: str | None = None,
    http_get=httpx.get,
) -> dict[str, Any]:
    base_url = prometheus_url or _configured_prometheus_url()
    url = _join_url(base_url, "/api/v1/query_range")
    start_ts = _parse_time_to_epoch_seconds(start_time, default_offset_minutes=-15)
    end_ts = _parse_time_to_epoch_seconds(end_time, default_offset_minutes=0)
    if start_ts > end_ts:
        start_ts, end_ts = end_ts, start_ts

    query = f'{metric_name}{{service_name="{service_name}"}}'
    params = {
        "query": query,
        "start": start_ts,
        "end": end_ts,
        "step": step,
    }
    response = http_get(url, params=params, timeout=10.0)
    response.raise_for_status()
    payload = response.json()
    result = payload.get("data", {}).get("result", []) if isinstance(payload, dict) else []

    data_points = []
    for series in result:
        for timestamp, value in series.get("values", []):
            numeric_value = _safe_float(value)
            if numeric_value is None:
                continue
            data_points.append(
                {
                    "timestamp": datetime.fromtimestamp(float(timestamp), tz=timezone.utc).isoformat(),
                    "value": numeric_value,
                }
            )

    values = [point["value"] for point in data_points]
    return {
        "source": "prometheus",
        "prometheus_url": base_url,
        "service_name": service_name,
        "metric_name": metric_name,
        "query": query,
        "step": step,
        "data_points": data_points,
        "statistics": _summarize_values(values),
    }


def _connect_cmdb(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _json_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return [part.strip() for part in str(value).split(",") if part.strip()]
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return []


def _get_service_info_from_db(db_path: str, service_name: str) -> dict[str, Any]:
    if not os.path.exists(db_path):
        return {"service_name": service_name, "found": False, "error": f"CMDB not found: {db_path}"}
    with _connect_cmdb(db_path) as conn:
        row = conn.execute(
            """
            SELECT service_name, owner_team, owner_user, environment, dependencies, runbook_url
            FROM services
            WHERE service_name = ?
            """,
            (service_name,),
        ).fetchone()
    service = _row_to_dict(row)
    if service is None:
        return {"service_name": service_name, "found": False}
    service["found"] = True
    service["dependencies"] = _json_list(service.get("dependencies"))
    return service


def _get_recent_deployments_from_db(db_path: str, service_name: str, limit: int = 5) -> dict[str, Any]:
    if not os.path.exists(db_path):
        return {"service_name": service_name, "deployments": [], "error": f"CMDB not found: {db_path}"}
    with _connect_cmdb(db_path) as conn:
        rows = conn.execute(
            """
            SELECT deployment_id, service_name, version, deployed_at, operator, change_summary
            FROM deployments
            WHERE service_name = ?
            ORDER BY deployed_at DESC
            LIMIT ?
            """,
            (service_name, max(1, min(limit, 50))),
        ).fetchall()
    return {
        "service_name": service_name,
        "deployments": [dict(row) for row in rows],
    }


def _search_historical_tickets_from_db(
    db_path: str,
    service_name: str,
    alert_name: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    if not os.path.exists(db_path):
        return {"service_name": service_name, "tickets": [], "error": f"CMDB not found: {db_path}"}
    where = "service_name = ?"
    params: list[Any] = [service_name]
    if alert_name:
        where += " AND alert_name = ?"
        params.append(alert_name)
    params.append(max(1, min(limit, 50)))
    with _connect_cmdb(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT ticket_id, service_name, alert_name, root_cause, resolution, created_at
            FROM tickets
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return {
        "service_name": service_name,
        "alert_name": alert_name,
        "tickets": [dict(row) for row in rows],
    }


def _list_service_dependencies_from_db(db_path: str, service_name: str) -> dict[str, Any]:
    service = _get_service_info_from_db(db_path, service_name)
    return {
        "service_name": service_name,
        "dependencies": service.get("dependencies", []),
        "found": service.get("found", False),
    }


@mcp.tool()
@log_tool_call
def query_active_alerts() -> Dict[str, Any]:
    """查询 Alertmanager 当前活跃告警。

    地址由 `AIOPS_ALERTMANAGER_URL` 配置，默认 `http://localhost:9093`。
    """
    return _query_active_alerts()


@mcp.tool()
@log_tool_call
def query_metric_series(
    service_name: str,
    metric_name: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    step: str = "30s",
) -> Dict[str, Any]:
    """查询 Prometheus 指标时序并返回数据点和统计摘要。"""
    return _query_metric_series(
        service_name=service_name,
        metric_name=metric_name,
        start_time=start_time,
        end_time=end_time,
        step=step,
    )


@mcp.tool()
@log_tool_call
def get_service_health(service_name: str) -> Dict[str, Any]:
    """汇总服务活跃告警和关键指标健康状态。"""
    alerts_result = _query_active_alerts()
    service_alerts = [
        alert for alert in alerts_result["alerts"] if alert.get("service_name") == service_name
    ]
    metrics: dict[str, Any] = {}
    for metric_name in [
        "service_cpu_percent",
        "mysql_query_latency_seconds",
        "redis_queue_length",
    ]:
        try:
            metrics[metric_name] = _query_metric_series(
                service_name=service_name,
                metric_name=metric_name,
            )
        except Exception as exc:
            metrics[metric_name] = {"error": str(exc)}
    return {
        "service_name": service_name,
        "status": "degraded" if service_alerts else "healthy",
        "active_alerts": service_alerts,
        "metrics": metrics,
    }


@mcp.tool()
@log_tool_call
def get_service_info(service_name: str) -> Dict[str, Any]:
    """查询本地 CMDB 中的服务负责人、环境、依赖和 runbook。"""
    return _get_service_info_from_db(_configured_cmdb_sqlite_path(), service_name)


@mcp.tool()
@log_tool_call
def get_recent_deployments(service_name: str, limit: int = 5) -> Dict[str, Any]:
    """查询服务最近发布记录。"""
    return _get_recent_deployments_from_db(_configured_cmdb_sqlite_path(), service_name, limit)


@mcp.tool()
@log_tool_call
def search_historical_tickets(
    service_name: str,
    alert_name: Optional[str] = None,
    limit: int = 5,
) -> Dict[str, Any]:
    """查询服务相关历史工单，可按告警名过滤。"""
    return _search_historical_tickets_from_db(
        _configured_cmdb_sqlite_path(),
        service_name,
        alert_name=alert_name,
        limit=limit,
    )


@mcp.tool()
@log_tool_call
def list_service_dependencies(service_name: str) -> Dict[str, Any]:
    """查询服务依赖关系。"""
    return _list_service_dependencies_from_db(_configured_cmdb_sqlite_path(), service_name)





# ============================================================
# 监控数据查询工具
# ============================================================

@mcp.tool()
@log_tool_call
def query_cpu_metrics(
    service_name: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    interval: str = "1m"
) -> Dict[str, Any]:
    """查询服务的 CPU 使用率监控数据。

    Args:
        service_name: 服务名称（必填）
            示例: "data-sync-service"
        
        start_time: 开始时间（可选，字符串类型）
            格式: "YYYY-MM-DD HH:MM:SS"
            示例: "2026-02-14 10:00:00"
            默认值: 如果不传，默认为当前时间的1小时前
            注意: 必须使用字符串格式，而非时间戳
        
        end_time: 结束时间（可选，字符串类型）
            格式: "YYYY-MM-DD HH:MM:SS"
            示例: "2026-02-14 11:00:00"
            默认值: 如果不传，默认为当前时间
            注意: 必须使用字符串格式，而非时间戳
        
        interval: 数据聚合间隔（可选）
            可选值: "1m" (1分钟), "5m" (5分钟), "1h" (1小时)
            默认值: "1m"
            说明: 控制数据点的时间间隔

    Returns:
        Dict: CPU 监控数据
            - service_name: 服务名称
            - metric_name: 指标名称 (cpu_usage_percent)
            - interval: 数据聚合间隔
            - data_points: 数据点列表，每个点包含:
                * timestamp: 时间点（格式: HH:MM）
                * value: CPU 使用率百分比
            - statistics: 统计信息
                * average: 平均值
                * max: 最大值
                * min: 最小值
            - alert: 告警信息（如有）
                * triggered: 是否触发告警
                * threshold: 告警阈值
                * message: 告警消息
    
    使用示例:
        # 示例1: 使用默认时间（最近1小时）
        query_cpu_metrics(service_name="data-sync-service")
        
        # 示例2: 指定时间范围
        query_cpu_metrics(
            service_name="data-sync-service",
            start_time="2026-02-14 10:00:00",
            end_time="2026-02-14 11:00:00",
            interval="5m"
        )
        
        # 示例3: 只指定开始时间（结束时间自动为当前时间）
        query_cpu_metrics(
            service_name="data-sync-service",
            start_time="2026-02-14 10:00:00"
        )
    """
    # 解析时间参数
    start_dt = parse_time_or_default(start_time, default_offset_hours=-1)
    end_dt = parse_time_or_default(end_time, default_offset_hours=0)
    
    # 解析间隔时间（interval: 1m, 5m, 1h 等）
    interval_minutes = 1  # 默认 1 分钟
    if interval.endswith('m'):
        interval_minutes = int(interval[:-1])
    elif interval.endswith('h'):
        interval_minutes = int(interval[:-1]) * 60

    # 动态生成 CPU 使用率数据：从低到高逐渐增长
    data_points = []
    current_time = start_dt
    time_index = 0

    # 初始 CPU 使用率（10%）
    base_cpu = 10.0

    while current_time <= end_dt:
        # CPU 使用率逐渐升高的算法：
        # - 前几个数据点保持在 10% 左右
        # - 然后开始快速上升
        # - 最终达到 95% 左右

        if time_index < 3:
            # 初始阶段：10% 左右波动
            cpu_value = base_cpu + (time_index * 0.5)
        else:
            # 上升阶段：使用指数增长模型
            growth_factor = (time_index - 2) * 8.5
            cpu_value = min(base_cpu + growth_factor, 96.0)

        # 添加一些随机波动（±2%）
        cpu_value = round(cpu_value + random.uniform(-2, 2), 1)
        cpu_value = max(0, min(100, cpu_value))  # 确保在 0-100 范围内

        data_point = {
            "timestamp": current_time.strftime("%H:%M"),
            "value": cpu_value,
            "process_id": "pid-12345"
        }

        data_points.append(data_point)

        # 下一个时间点
        current_time += timedelta(minutes=interval_minutes)
        time_index += 1

    # 计算统计信息
    if data_points:
        values = [d["value"] for d in data_points]
        avg_value = round(sum(values) / len(values), 2)
        max_value = max(values)
        min_value = min(values)

        # 检测是否有 CPU 突增（超过 80%）
        spike_detected = max_value > 80.0

        return {
            "service_name": service_name,
            "metric_name": "cpu_usage_percent",
            "interval": interval,
            "data_points": data_points,
            "statistics": {
                "avg": avg_value,
                "max": max_value,
                "min": min_value,
                "p95": round(sorted(values)[int(len(values) * 0.95)] if len(values) > 1 else max_value, 2),
                "spike_detected": spike_detected
            },
            "alert_info": {
                "triggered": spike_detected,
                "threshold": 80.0,
                "message": "CPU 使用率持续超过 80% 阈值" if spike_detected else "CPU 使用率正常"
            }
        }
    else:
        return {
            "service_name": service_name,
            "metric_name": "cpu_usage_percent",
            "interval": interval,
            "data_points": [],
            "statistics": {},
        }


@mcp.tool()
@log_tool_call
def query_memory_metrics(
    service_name: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    interval: str = "1m"
) -> Dict[str, Any]:
    """查询服务的内存使用监控数据。

    Args:
        service_name: 服务名称（必填）
            示例: "data-sync-service"
        
        start_time: 开始时间（可选，字符串类型）
            格式: "YYYY-MM-DD HH:MM:SS"
            示例: "2026-02-14 10:00:00"
            默认值: 如果不传，默认为当前时间的1小时前
            注意: 必须使用字符串格式，而非时间戳
        
        end_time: 结束时间（可选，字符串类型）
            格式: "YYYY-MM-DD HH:MM:SS"
            示例: "2026-02-14 11:00:00"
            默认值: 如果不传，默认为当前时间
            注意: 必须使用字符串格式，而非时间戳
        
        interval: 数据聚合间隔（可选）
            可选值: "1m" (1分钟), "5m" (5分钟), "1h" (1小时)
            默认值: "1m"

    Returns:
        Dict: 内存监控数据
            - service_name: 服务名称
            - metric_name: 指标名称 (memory_usage_percent)
            - interval: 数据聚合间隔
            - data_points: 数据点列表，每个点包含:
                * timestamp: 时间点（格式: HH:MM）
                * value: 内存使用率百分比
                * used_gb: 已使用内存（GB）
                * total_gb: 总内存（GB）
            - statistics: 统计信息
                * average: 平均值
                * max: 最大值
                * min: 最小值
            - alert: 告警信息（如有）
                * triggered: 是否触发告警
                * threshold: 告警阈值
                * message: 告警消息
    
    使用示例:
        # 示例1: 使用默认时间（最近1小时）
        query_memory_metrics(service_name="data-sync-service")
        
        # 示例2: 指定时间范围
        query_memory_metrics(
            service_name="data-sync-service",
            start_time="2026-02-14 10:00:00",
            end_time="2026-02-14 11:00:00",
            interval="5m"
        )
    """
    # 解析时间参数
    start_dt = parse_time_or_default(start_time, default_offset_hours=-1)
    end_dt = parse_time_or_default(end_time, default_offset_hours=0)
    
    # 解析间隔时间（interval: 1m, 5m, 1h 等）
    interval_minutes = 1  # 默认 1 分钟
    if interval.endswith('m'):
        interval_minutes = int(interval[:-1])
    elif interval.endswith('h'):
        interval_minutes = int(interval[:-1]) * 60
    
    # 动态生成内存使用率数据：从低到高逐渐增长
    data_points = []
    current_time = start_dt
    time_index = 0
    
    # 初始内存使用率（30%）
    base_memory = 30.0
    total_gb = 8.0  # 总内存 8GB
    
    while current_time <= end_dt:
        # 内存使用率逐渐升高的算法：
        # - 前几个数据点保持在 30% 左右
        # - 然后开始逐步上升
        # - 最终达到 85% 左右
        
        if time_index < 3:
            # 初始阶段：30% 左右波动
            memory_value = base_memory + (time_index * 1.0)
        else:
            # 上升阶段：使用线性增长模型（内存增长比 CPU 慢）
            growth_factor = (time_index - 2) * 5.5
            memory_value = min(base_memory + growth_factor, 85.0)
        
        # 添加一些随机波动（±1%）
        memory_value = round(memory_value + random.uniform(-1, 1), 1)
        memory_value = max(0, min(100, memory_value))  # 确保在 0-100 范围内
        
        # 计算已使用内存（GB）
        used_gb = round((memory_value / 100.0) * total_gb, 2)
        
        data_point = {
            "timestamp": current_time.strftime("%H:%M"),
            "value": memory_value,
            "used_gb": used_gb,
            "total_gb": total_gb
        }
        
        data_points.append(data_point)
        
        # 下一个时间点
        current_time += timedelta(minutes=interval_minutes)
        time_index += 1
    
    # 计算统计信息
    if data_points:
        values = [d["value"] for d in data_points]
        avg_value = round(sum(values) / len(values), 2)
        max_value = max(values)
        min_value = min(values)
        
        # 检测是否有内存压力（超过 70%）
        memory_pressure = max_value > 70.0
        
        return {
            "service_name": service_name,
            "metric_name": "memory_usage_percent",
            "interval": interval,
            "data_points": data_points,
            "statistics": {
                "avg": avg_value,
                "max": max_value,
                "min": min_value,
                "p95": round(sorted(values)[int(len(values) * 0.95)] if len(values) > 1 else max_value, 2),
                "memory_pressure": memory_pressure
            },
            "alert_info": {
                "triggered": memory_pressure,
                "threshold": 70.0,
                "message": "内存使用率超过 70% 阈值，存在内存压力" if memory_pressure else "内存使用率正常"
            }
        }
    else:
        return {
            "service_name": service_name,
            "metric_name": "memory_usage_percent",
            "interval": interval,
            "data_points": [],
            "statistics": {},
            "error": "时间范围无效或没有生成数据点"
        }




if __name__ == "__main__":
    # 使用 streamable-http 模式，运行在 8004 端口
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8004, path="/mcp")
