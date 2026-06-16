# P0a Memory Operator 后端 API 设计（架构合规版）

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

Memory Operator admin action 属于用户请求，**不能绕过 RequestGateway**。

## 实现方案

### Step 1: 创建 MemoryOperatorAdapter

**目标**：包装现有 Memory 服务，提供 RequestContext-aware 接口。

**文件清单**：
- 新增：`app/enterprise/admin/memory_operator_adapter.py`
- 新增：`tests/test_memory_operator_adapter.py`

**Adapter 设计**：

```python
# app/enterprise/admin/memory_operator_adapter.py
from app.enterprise.context import RequestContext
from app.services.memory_review_service import MemoryReviewService
from app.services.memory_store import MemoryStore
from app.enterprise.observability.audit_service import AuditService

class MemoryOperatorAdapter:
    """
    Memory Operator Adapter，包装现有 Memory 服务。
    
    职责：
    - 接受 RequestContext，不依赖全局 current_user
    - 调用既有 MemoryReviewService / MemoryStore
    - 写领域审计（memory_review / memory_cleanup），不写请求审计（由 RequestGateway 负责）
    """
    
    def __init__(
        self,
        memory_review_service: MemoryReviewService,
        memory_store: MemoryStore,
        audit_service: AuditService
    ):
        self.memory_review_service = memory_review_service
        self.memory_store = memory_store
        self.audit_service = audit_service
    
    def get_review_queue(self, context: RequestContext, limit: int = 20) -> list:
        """
        查询 review queue（需要审批的 candidate/conflict）。
        
        Args:
            context: 请求上下文（包含 user_id/trace_id）
            limit: 最多返回多少条
        
        Returns:
            [{"memory_id": "...", "memory_type": "...", "status": "candidate", ...}, ...]
        """
        # 调用既有 service
        return self.memory_review_service.get_review_queue(
            reviewer_id=context.user_id,  # 使用 context.user_id，不是 body 传的 "current_admin"
            limit=limit
        )
    
    def approve_memory(self, context: RequestContext, memory_id: str, decision_note: str):
        """
        审批通过 memory。
        
        Args:
            context: 请求上下文
            memory_id: memory ID
            decision_note: 审批意见
        """
        # 调用既有 service
        self.memory_review_service.approve(
            memory_id=memory_id,
            reviewer_id=context.user_id,  # 使用 context.user_id
            decision_note=decision_note
        )
        
        # 写领域审计（memory_review）
        self.audit_service.record(
            event_type="memory_review",
            user_id=context.user_id,
            trace_id=context.trace_id,
            metadata={
                "memory_id": memory_id,
                "decision": "approved",
                "decision_note": decision_note
            }
        )
    
    def reject_memory(self, context: RequestContext, memory_id: str, decision_note: str):
        """拒绝 memory"""
        self.memory_review_service.reject(
            memory_id=memory_id,
            reviewer_id=context.user_id,
            decision_note=decision_note
        )
        
        self.audit_service.record(
            event_type="memory_review",
            user_id=context.user_id,
            trace_id=context.trace_id,
            metadata={
                "memory_id": memory_id,
                "decision": "rejected",
                "decision_note": decision_note
            }
        )
    
    def deprecate_memory(self, context: RequestContext, memory_id: str, decision_note: str):
        """废弃 memory"""
        self.memory_review_service.deprecate(
            memory_id=memory_id,
            reviewer_id=context.user_id,
            decision_note=decision_note
        )
        
        self.audit_service.record(
            event_type="memory_review",
            user_id=context.user_id,
            trace_id=context.trace_id,
            metadata={
                "memory_id": memory_id,
                "decision": "deprecated",
                "decision_note": decision_note
            }
        )
    
    def get_validation_status(self, context: RequestContext, owner_id: str) -> dict:
        """查询 validation status（Gate A.2 计数器）"""
        return self.memory_store.get_validation_policy_status(owner_id)
    
    def preview_deprecation(self, context: RequestContext, owner_id: str, ttl_days: int) -> dict:
        """
        预览 deprecation plan（不执行）。
        
        Returns:
            {"expired_count": 10, "expired_ids": ["mem_001", ...]}
        """
        plan = self.memory_review_service.build_owner_deprecation_plan(
            owner_id=owner_id,
            ttl_days=ttl_days
        )
        return {
            "expired_count": len(plan.expired_ids),
            "expired_ids": plan.expired_ids
        }
```

---

### Step 2: 创建 FastAPI Routes（走 RequestGateway）

**目标**：HTTP route 只做 auth + request 映射，业务逻辑在 Adapter。

**文件清单**：
- 新增：`app/enterprise/admin/memory_operator_routes.py`
- 修改：`app/main.py`（挂载 router）

**Routes 设计**：

```python
# app/enterprise/admin/memory_operator_routes.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.enterprise.auth.dependencies import get_current_user, CurrentUser
from app.enterprise.context import RequestContext, create_request_context
from app.enterprise.gateway.request_gateway import RequestGateway, GatewayRequest
from app.enterprise.admin.memory_operator_adapter import MemoryOperatorAdapter

router = APIRouter(prefix="/api/admin/memory-operator", tags=["memory-operator"])

# 依赖注入（从 app state 获取）
def get_memory_operator_adapter() -> MemoryOperatorAdapter:
    """从 app state 获取 adapter"""
    from app.dependencies import get_memory_operator_adapter as _get
    return _get()

def get_request_gateway() -> RequestGateway:
    """从 app state 获取 gateway"""
    from app.dependencies import get_request_gateway as _get
    return _get()


# Request/Response 模型
class ApproveRequest(BaseModel):
    decision_note: str

class RejectRequest(BaseModel):
    decision_note: str

class DeprecateRequest(BaseModel):
    decision_note: str

class DeprecationPreviewRequest(BaseModel):
    owner_id: str
    ttl_days: int = 180


# Routes
@router.get("/review-queue")
async def get_review_queue(
    limit: int = 20,
    current_user: CurrentUser = Depends(get_current_user),
    adapter: MemoryOperatorAdapter = Depends(get_memory_operator_adapter),
    gateway: RequestGateway = Depends(get_request_gateway)
):
    """
    查询 review queue。
    
    架构路径：
    route -> RequestGateway.execute -> MemoryOperatorAdapter -> MemoryReviewService
    """
    # 创建 RequestContext
    context = create_request_context(current_user)
    
    # 创建 GatewayRequest
    gateway_request = GatewayRequest(
        context=context,
        operation_name="memory_operator_review_queue",
        handler=lambda ctx: adapter.get_review_queue(ctx, limit=limit)
    )
    
    # 走 RequestGateway（自动写 request_started/completed/failed audit）
    return await gateway.execute(gateway_request)


@router.post("/atoms/{memory_id}/approve")
async def approve_memory(
    memory_id: str,
    request: ApproveRequest,
    current_user: CurrentUser = Depends(get_current_user),
    adapter: MemoryOperatorAdapter = Depends(get_memory_operator_adapter),
    gateway: RequestGateway = Depends(get_request_gateway)
):
    """
    审批通过 memory。
    
    注意：reviewer_id 从 RequestContext.user_id 取，不是 body 传的 "current_admin"。
    """
    context = create_request_context(current_user)
    
    gateway_request = GatewayRequest(
        context=context,
        operation_name="memory_operator_approve",
        handler=lambda ctx: adapter.approve_memory(
            ctx,
            memory_id=memory_id,
            decision_note=request.decision_note
        )
    )
    
    await gateway.execute(gateway_request)
    return {"status": "approved"}


@router.post("/atoms/{memory_id}/reject")
async def reject_memory(
    memory_id: str,
    request: RejectRequest,
    current_user: CurrentUser = Depends(get_current_user),
    adapter: MemoryOperatorAdapter = Depends(get_memory_operator_adapter),
    gateway: RequestGateway = Depends(get_request_gateway)
):
    """拒绝 memory"""
    context = create_request_context(current_user)
    
    gateway_request = GatewayRequest(
        context=context,
        operation_name="memory_operator_reject",
        handler=lambda ctx: adapter.reject_memory(
            ctx,
            memory_id=memory_id,
            decision_note=request.decision_note
        )
    )
    
    await gateway.execute(gateway_request)
    return {"status": "rejected"}


@router.post("/atoms/{memory_id}/deprecate")
async def deprecate_memory(
    memory_id: str,
    request: DeprecateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    adapter: MemoryOperatorAdapter = Depends(get_memory_operator_adapter),
    gateway: RequestGateway = Depends(get_request_gateway)
):
    """废弃 memory"""
    context = create_request_context(current_user)
    
    gateway_request = GatewayRequest(
        context=context,
        operation_name="memory_operator_deprecate",
        handler=lambda ctx: adapter.deprecate_memory(
            ctx,
            memory_id=memory_id,
            decision_note=request.decision_note
        )
    )
    
    await gateway.execute(gateway_request)
    return {"status": "deprecated"}


@router.get("/validation-status")
async def get_validation_status(
    owner_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    adapter: MemoryOperatorAdapter = Depends(get_memory_operator_adapter),
    gateway: RequestGateway = Depends(get_request_gateway)
):
    """查询 validation status（Gate A.2 计数器）"""
    context = create_request_context(current_user)
    
    gateway_request = GatewayRequest(
        context=context,
        operation_name="memory_operator_validation_status",
        handler=lambda ctx: adapter.get_validation_status(ctx, owner_id=owner_id)
    )
    
    return await gateway.execute(gateway_request)


@router.post("/deprecation-preview")
async def preview_deprecation(
    request: DeprecationPreviewRequest,
    current_user: CurrentUser = Depends(get_current_user),
    adapter: MemoryOperatorAdapter = Depends(get_memory_operator_adapter),
    gateway: RequestGateway = Depends(get_request_gateway)
):
    """
    预览 deprecation plan（不执行）。
    
    Returns:
        {"expired_count": 10, "expired_ids": ["mem_001", ...]}
    """
    context = create_request_context(current_user)
    
    gateway_request = GatewayRequest(
        context=context,
        operation_name="memory_operator_deprecation_preview",
        handler=lambda ctx: adapter.preview_deprecation(
            ctx,
            owner_id=request.owner_id,
            ttl_days=request.ttl_days
        )
    )
    
    return await gateway.execute(gateway_request)
```

---

### Step 3: 审计分层

**两层审计**：

1. **RequestGateway 写请求审计**（自动）：
   - `request_started`（operation_name="memory_operator_review_queue"）
   - `request_completed`（latency_ms / status）
   - `request_failed`（error_type / error_message）

2. **Adapter/Service 写领域审计**（手动）：
   - `memory_review`（memory_id / decision / decision_note）
   - `memory_cleanup`（owner_id / expired_count）

**不冲突**：
- RequestGateway 审计：**所有 HTTP 请求都有**（统一治理）
- 领域审计：**只有 Memory 相关操作有**（业务语义）

---

### Step 4: 依赖注入

**文件清单**：
- 修改：`app/dependencies.py`（或创建新文件）
- 修改：`app/main.py`（在 startup 中初始化）

**依赖注入设计**：

```python
# app/dependencies.py
from functools import lru_cache
from app.enterprise.admin.memory_operator_adapter import MemoryOperatorAdapter
from app.services.memory_review_service import MemoryReviewService
from app.services.memory_store import MemoryStore
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.gateway.request_gateway import RequestGateway

@lru_cache()
def get_memory_operator_adapter() -> MemoryOperatorAdapter:
    """单例 MemoryOperatorAdapter"""
    memory_review_service = MemoryReviewService()
    memory_store = MemoryStore()
    audit_service = get_audit_service()
    
    return MemoryOperatorAdapter(
        memory_review_service=memory_review_service,
        memory_store=memory_store,
        audit_service=audit_service
    )

@lru_cache()
def get_request_gateway() -> RequestGateway:
    """单例 RequestGateway"""
    # 返回现有 RequestGateway 实例
    pass
```

---

## 验收标准

1. ✅ 所有 HTTP route 都走 `RequestGateway.execute(...)`
2. ✅ `RequestGateway` 自动写 `request_started` / `request_completed` / `request_failed` audit
3. ✅ `MemoryOperatorAdapter` 写 `memory_review` 领域审计
4. ✅ `reviewer_id` 从 `RequestContext.user_id` 取，不是 body 传的
5. ✅ 所有操作都有 `trace_id` / `request_id`
6. ✅ admin 权限检查在 `CurrentUser` 依赖中完成
7. ✅ 非 admin 用户 403
8. ✅ approve/reject/deprecate 都有领域审计

**测试覆盖**：
```bash
uv run pytest tests/test_memory_operator_adapter.py -q --no-cov
uv run pytest tests/test_memory_operator_routes.py -q --no-cov

# 测试覆盖：
# - Adapter 单测：调用 service、写领域审计
# - Route 单测：走 RequestGateway、admin 权限检查、请求审计
# - 集成测试：完整链路（route -> gateway -> adapter -> service）
```

