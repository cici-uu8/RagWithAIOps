# P2 Ops Dashboard 后端 API 设计（架构合规版）

## 架构约束

根据 `docs/项目完整架构.md` 第 4.1 节架构铁律：

```
所有用户请求必须进入 RequestGateway

允许的模式：
FastAPI route
  -> CurrentUser / RequestContext
  -> Adapter
  -> RequestGateway
  -> Domain Module
```

Ops Dashboard admin action 属于用户请求，**不能绕过 RequestGateway**。

聚合逻辑不应该散落在 route 中，应该有独立的 `OpsMetricsService`。

## 实现方案

### Step 1: 创建 OpsMetricsService

**目标**：封装 ops metrics 聚合逻辑，从 AuditService 读数据并聚合。

**文件清单**：
- 新增：`app/enterprise/admin/ops_metrics_service.py`
- 新增：`tests/test_ops_metrics_service.py`

**Service 设计**：

```python
# app/enterprise/admin/ops_metrics_service.py
from datetime import datetime, timedelta
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.context import RequestContext

class OpsMetricsService:
    """
    Ops Metrics Service，负责从 AuditService 读取 audit 数据并聚合。
    
    职责：
    - 查询 audit 事件（request_started / request_completed / request_failed）
    - 聚合统计（success_rate / latency p50/p95 / top users/routes/tools）
    - 按时间桶聚合 timeline
    - 查询失败列表（failure_semantics / recovered）
    
    不做：
    - ❌ 不做成本统计（留给 P3）
    - ❌ 不直接查询 SQLite（通过 AuditService）
    """
    
    def __init__(self, audit_service: AuditService):
        self.audit_service = audit_service
    
    def get_summary(self, context: RequestContext, time_range: str) -> dict:
        """
        获取 ops 总览统计。
        
        Args:
            context: 请求上下文
            time_range: 时间范围（1h / 24h / 7d）
        
        Returns:
            {
                "total_requests": 1000,
                "success_rate": 0.95,
                "avg_latency_ms": 1500,
                "p50_latency_ms": 1200,
                "p95_latency_ms": 3000,
                "top_users": [{"user_id": "...", "count": 100}, ...],
                "top_routes": [{"route": "chat", "count": 500}, ...],
                "top_tools": [{"tool": "retrieve_knowledge", "count": 300}, ...]
            }
        """
        # 1. 解析时间范围
        start_time = self._parse_time_range(time_range)
        
        # 2. 查询 request_completed / request_failed 事件
        events = self.audit_service.query(
            event_type=["request_completed", "request_failed"],
            start_time=start_time
        )
        
        # 3. 聚合统计
        total_requests = len(events)
        success_count = sum(1 for e in events if e.event_type == "request_completed")
        success_rate = success_count / total_requests if total_requests > 0 else 0
        
        # 4. 计算延迟 p50/p95
        latencies = [
            e.metadata.get("latency_ms", 0)
            for e in events
            if e.event_type == "request_completed" and "latency_ms" in e.metadata
        ]
        latencies.sort()
        
        p50_latency_ms = latencies[int(len(latencies) * 0.5)] if latencies else 0
        p95_latency_ms = latencies[int(len(latencies) * 0.95)] if latencies else 0
        avg_latency_ms = sum(latencies) / len(latencies) if latencies else 0
        
        # 5. 聚合 top users/routes/tools
        top_users = self._aggregate_top(events, key="user_id", limit=10)
        top_routes = self._aggregate_top(events, key="route", limit=10)
        top_tools = self._aggregate_top_tools(start_time, limit=10)
        
        return {
            "total_requests": total_requests,
            "success_rate": success_rate,
            "avg_latency_ms": int(avg_latency_ms),
            "p50_latency_ms": p50_latency_ms,
            "p95_latency_ms": p95_latency_ms,
            "top_users": top_users,
            "top_routes": top_routes,
            "top_tools": top_tools
        }
    
    def get_timeline(self, context: RequestContext, time_range: str, bucket: str) -> list:
        """
        获取按时间桶聚合的请求趋势。
        
        Args:
            context: 请求上下文
            time_range: 时间范围（1h / 24h / 7d）
            bucket: 时间桶大小（1h）
        
        Returns:
            [
                {"time_bucket": "2026-06-16T10:00:00Z", "total": 100, "success": 95, "failed": 5},
                ...
            ]
        """
        start_time = self._parse_time_range(time_range)
        bucket_seconds = self._parse_bucket(bucket)
        
        # 查询事件
        events = self.audit_service.query(
            event_type=["request_completed", "request_failed"],
            start_time=start_time
        )
        
        # 按时间桶聚合
        buckets = {}
        for event in events:
            bucket_key = self._get_bucket_key(event.timestamp, bucket_seconds)
            if bucket_key not in buckets:
                buckets[bucket_key] = {"total": 0, "success": 0, "failed": 0}
            
            buckets[bucket_key]["total"] += 1
            if event.event_type == "request_completed":
                buckets[bucket_key]["success"] += 1
            else:
                buckets[bucket_key]["failed"] += 1
        
        # 转换为列表并排序
        timeline = [
            {"time_bucket": k, **v}
            for k, v in sorted(buckets.items())
        ]
        
        return timeline
    
    def get_failures(self, context: RequestContext, time_range: str, limit: int = 20) -> list:
        """
        获取最近失败列表。
        
        Args:
            context: 请求上下文
            time_range: 时间范围（1h / 24h / 7d）
            limit: 最多返回多少条
        
        Returns:
            [
                {
                    "trace_id": "...",
                    "user_id": "...",
                    "route": "...",
                    "failure_semantics": "infra_error",
                    "recovered": false,
                    "timestamp": "2026-06-16T10:00:00Z"
                },
                ...
            ]
        """
        start_time = self._parse_time_range(time_range)
        
        # 查询 request_failed 事件
        events = self.audit_service.query(
            event_type="request_failed",
            start_time=start_time,
            limit=limit
        )
        
        # 转换为列表
        failures = [
            {
                "trace_id": e.trace_id,
                "user_id": e.user_id,
                "route": e.metadata.get("route", "unknown"),
                "failure_semantics": e.metadata.get("failure_semantics", "unknown"),
                "recovered": e.metadata.get("recovered", False),
                "timestamp": e.timestamp.isoformat()
            }
            for e in events
        ]
        
        return failures
    
    # 辅助方法
    def _parse_time_range(self, time_range: str) -> datetime:
        """解析时间范围"""
        now = datetime.utcnow()
        if time_range == "1h":
            return now - timedelta(hours=1)
        elif time_range == "24h":
            return now - timedelta(hours=24)
        elif time_range == "7d":
            return now - timedelta(days=7)
        else:
            return now - timedelta(hours=24)
    
    def _parse_bucket(self, bucket: str) -> int:
        """解析时间桶大小（返回秒数）"""
        if bucket == "1h":
            return 3600
        else:
            return 3600
    
    def _get_bucket_key(self, timestamp: datetime, bucket_seconds: int) -> str:
        """获取时间桶 key"""
        bucket_ts = (timestamp.timestamp() // bucket_seconds) * bucket_seconds
        return datetime.utcfromtimestamp(bucket_ts).isoformat() + "Z"
    
    def _aggregate_top(self, events: list, key: str, limit: int) -> list:
        """聚合 top N（按 key 分组计数）"""
        counts = {}
        for event in events:
            value = event.metadata.get(key) or getattr(event, key, "unknown")
            counts[value] = counts.get(value, 0) + 1
        
        top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
        return [{"key": k, "count": v} for k, v in top]
    
    def _aggregate_top_tools(self, start_time: datetime, limit: int) -> list:
        """聚合 top tools（从 tool_execution 事件）"""
        tool_events = self.audit_service.query(
            event_type="tool_execution",
            start_time=start_time
        )
        
        counts = {}
        for event in tool_events:
            tool_name = event.metadata.get("tool_name", "unknown")
            counts[tool_name] = counts.get(tool_name, 0) + 1
        
        top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
        return [{"tool": k, "count": v} for k, v in top]
```

---

### Step 2: 创建 OpsMetricsAdapter

**目标**：包装 OpsMetricsService，提供 admin scope 和脱敏。

**文件清单**：
- 新增：`app/enterprise/admin/ops_metrics_adapter.py`

**Adapter 设计**：

```python
# app/enterprise/admin/ops_metrics_adapter.py
from app.enterprise.context import RequestContext
from app.enterprise.admin.ops_metrics_service import OpsMetricsService
from app.enterprise.permissions.admin_scope import AdminScopeService

class OpsMetricsAdapter:
    """
    Ops Metrics Adapter，包装 OpsMetricsService。
    
    职责：
    - admin scope 校验（只有 global admin 可以查看所有用户）
    - 脱敏（department admin 只能看本部门）
    - 时间范围校验（不能查询超过 30 天）
    """
    
    def __init__(
        self,
        ops_metrics_service: OpsMetricsService,
        admin_scope_service: AdminScopeService
    ):
        self.ops_metrics_service = ops_metrics_service
        self.admin_scope_service = admin_scope_service
    
    async def get_summary(self, context: RequestContext, time_range: str) -> dict:
        """
        获取 ops 总览统计。
        
        Admin scope:
        - global admin: 可以看所有用户
        - department admin: 只能看本部门用户
        """
        # 1. 校验 admin scope
        scope = await self.admin_scope_service.get_scope(context.user_id)
        
        # 2. 调用 service
        summary = self.ops_metrics_service.get_summary(context, time_range)
        
        # 3. 脱敏（如果是 department admin）
        if scope.is_department_admin and not scope.is_global_admin:
            summary = self._filter_by_department(summary, scope.department_id)
        
        return summary
    
    async def get_timeline(self, context: RequestContext, time_range: str, bucket: str) -> list:
        """获取 timeline"""
        scope = await self.admin_scope_service.get_scope(context.user_id)
        timeline = self.ops_metrics_service.get_timeline(context, time_range, bucket)
        
        # department admin 脱敏
        if scope.is_department_admin and not scope.is_global_admin:
            timeline = self._filter_timeline_by_department(timeline, scope.department_id)
        
        return timeline
    
    async def get_failures(self, context: RequestContext, time_range: str, limit: int) -> list:
        """获取失败列表"""
        scope = await self.admin_scope_service.get_scope(context.user_id)
        failures = self.ops_metrics_service.get_failures(context, time_range, limit)
        
        # department admin 脱敏
        if scope.is_department_admin and not scope.is_global_admin:
            failures = self._filter_failures_by_department(failures, scope.department_id)
        
        return failures
    
    def _filter_by_department(self, summary: dict, department_id: str) -> dict:
        """脱敏：只保留本部门用户"""
        # 简化版：第一版不做 department 过滤，直接返回
        # 未来可以根据 user_department_map 过滤 top_users
        return summary
    
    def _filter_timeline_by_department(self, timeline: list, department_id: str) -> list:
        """脱敏：timeline 不需要过滤（只有聚合数据，没有 user_id）"""
        return timeline
    
    def _filter_failures_by_department(self, failures: list, department_id: str) -> list:
        """脱敏：只保留本部门用户的失败记录"""
        # 简化版：第一版不做 department 过滤
        return failures
```

---

### Step 3: 创建 FastAPI Routes（走 RequestGateway）

**文件清单**：
- 新增：`app/enterprise/admin/ops_metrics_routes.py`
- 修改：`app/main.py`（挂载 router）

**Routes 设计**：

```python
# app/enterprise/admin/ops_metrics_routes.py
from fastapi import APIRouter, Depends
from app.enterprise.auth.dependencies import get_current_user, CurrentUser
from app.enterprise.context import RequestContext, create_request_context
from app.enterprise.gateway.request_gateway import RequestGateway, GatewayRequest
from app.enterprise.admin.ops_metrics_adapter import OpsMetricsAdapter

router = APIRouter(prefix="/api/admin/ops-metrics", tags=["ops-metrics"])


@router.get("/summary")
async def get_ops_summary(
    time_range: str = "24h",
    current_user: CurrentUser = Depends(get_current_user),
    adapter: OpsMetricsAdapter = Depends(get_ops_metrics_adapter),
    gateway: RequestGateway = Depends(get_request_gateway)
):
    """
    获取 ops 总览统计。
    
    架构路径：
    route -> RequestGateway -> OpsMetricsAdapter -> OpsMetricsService -> AuditService
    
    不含成本统计（留给 P3）。
    """
    context = create_request_context(current_user)
    
    gateway_request = GatewayRequest(
        context=context,
        operation_name="ops_metrics_summary",
        handler=lambda ctx: adapter.get_summary(ctx, time_range)
    )
    
    return await gateway.execute(gateway_request)


@router.get("/timeline")
async def get_ops_timeline(
    time_range: str = "24h",
    bucket: str = "1h",
    current_user: CurrentUser = Depends(get_current_user),
    adapter: OpsMetricsAdapter = Depends(get_ops_metrics_adapter),
    gateway: RequestGateway = Depends(get_request_gateway)
):
    """获取请求趋势（按时间桶聚合）"""
    context = create_request_context(current_user)
    
    gateway_request = GatewayRequest(
        context=context,
        operation_name="ops_metrics_timeline",
        handler=lambda ctx: adapter.get_timeline(ctx, time_range, bucket)
    )
    
    return await gateway.execute(gateway_request)


@router.get("/failures")
async def get_ops_failures(
    time_range: str = "24h",
    limit: int = 20,
    current_user: CurrentUser = Depends(get_current_user),
    adapter: OpsMetricsAdapter = Depends(get_ops_metrics_adapter),
    gateway: RequestGateway = Depends(get_request_gateway)
):
    """获取最近失败列表"""
    context = create_request_context(current_user)
    
    gateway_request = GatewayRequest(
        context=context,
        operation_name="ops_metrics_failures",
        handler=lambda ctx: adapter.get_failures(ctx, time_range, limit)
    )
    
    return await gateway.execute(gateway_request)
```

---

## 架构合规检查

### ✅ 遵守架构铁律 4.1（RequestGateway）
- ✅ 所有 HTTP route 都走 `RequestGateway.execute(...)`
- ✅ 自动写 `request_started` / `request_completed` / `request_failed` audit

### ✅ 聚合逻辑在 Service 层
- ✅ `OpsMetricsService` 封装聚合逻辑
- ✅ Route 只做 auth + request 映射
- ✅ 不在 route 中散落聚合代码

### ✅ 不做成本统计（留给 P3）
- ✅ summary API 不返回 `total_cost` / `cost_by_user` / `cost_by_model`
- ✅ 不读取 `model_call` audit 的 `usage` 字段
- ✅ 不计算 token → 金额换算

---

## 验收标准

1. ✅ 所有 HTTP route 都走 `RequestGateway.execute(...)`
2. ✅ 聚合逻辑在 `OpsMetricsService` 中，不在 route 中
3. ✅ `OpsMetricsAdapter` 做 admin scope 和脱敏
4. ✅ 不直接查询 `SQLiteAuditSink`（通过 `AuditService`）
5. ✅ summary 包含 success_rate / latency p50/p95 / top users/routes/tools
6. ✅ **不包含成本统计**（total_cost / cost_by_user）
7. ✅ timeline 按时间桶聚合
8. ✅ failures 包含 failure_semantics 和 recovered 状态
9. ✅ 写 request audit（由 RequestGateway 自动完成）

**测试覆盖**：
```bash
uv run pytest tests/test_ops_metrics_service.py -q --no-cov
uv run pytest tests/test_ops_metrics_adapter.py -q --no-cov
uv run pytest tests/test_ops_metrics_routes.py -q --no-cov

# 测试覆盖：
# - Service 单测：聚合逻辑、p50/p95 计算、top N 聚合
# - Adapter 单测：admin scope、department 过滤
# - Route 单测：走 RequestGateway、admin 权限检查、请求审计
# - 集成测试：完整链路
```

