# Memory Operator API Design

日期: 2026-06-16

状态: P0a 后端控制面已实现；P0b admin-console UI 已实现。Memory 仍默认 off。

## 目标

把现有 durable memory review 能力暴露为最小 admin HTTP 控制面，用于 operator 查询 review queue、approve/reject candidate、查看 validation status，以及执行 owner-scoped deprecation preview/deprecate。

该 API 不代表 Memory 已进入主链路或产品化完成；它只是治理入口。

## 架构路径

所有 HTTP 请求走统一治理路径:

```text
FastAPI route
  -> CurrentUser / admin role check
  -> GatewayRequest.from_headers(...)
  -> RequestGateway.execute(...)
  -> MemoryOperatorAdapter
  -> MemoryReviewService / MemoryStore
```

请求级 audit 由 `RequestGateway` 写入 `request_started` / `request_completed` / `request_failed`。Memory review 领域事件由 `MemoryOperatorAdapter` 写入 `memory_review`。

## 路由

挂载点: `app/main.py` 将 `app/enterprise/admin/memory_operator_routes.py` 挂到 `/api`。

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/admin/memory-operator/review-queue?owner_id=default&limit=20` | 查询 candidate / conflict review queue |
| GET | `/api/admin/memory-operator/validation-status?owner_id=default` | 查询 Gate A.2 validation status |
| POST | `/api/admin/memory-operator/atoms/{memory_id}/approve` | 审批通过 candidate |
| POST | `/api/admin/memory-operator/atoms/{memory_id}/reject` | 拒绝 candidate |
| POST | `/api/admin/memory-operator/deprecation-preview` | 预览 owner-scoped deprecation plan，不修改数据 |
| POST | `/api/admin/memory-operator/deprecate-owner` | 二次确认 owner 后标记 deprecated，不物理删除 |

## 请求体

Approve / reject:

```json
{
  "decision_note": "validated by operator"
}
```

Deprecation preview:

```json
{
  "owner_id": "ops-team"
}
```

Deprecate owner:

```json
{
  "owner_id": "ops-team",
  "confirm_owner_id": "ops-team",
  "decision_note": "retire owner records"
}
```

`reviewer_id` 不接受前端传入，必须来自 `RequestContext.user_id`。测试覆盖了 body 中伪造 `reviewer_id` 时仍使用 admin token 对应的 `user_admin`。

## 边界

- 不做 L0/L1/L2 全量 Explorer。
- 不做 Memory 自动 promotion。
- 不把 durable memory 默认注入 RAG/AIOps 主 prompt。
- 不物理删除 durable memory；owner deprecate 只标记 `deprecated`。
- L0 evidence TTL cleanup 不属于本 P0a API。
- 非 admin 访问返回 403。

## 代码与测试

实现文件:

- `app/enterprise/admin/memory_operator_adapter.py`
- `app/enterprise/admin/memory_operator_routes.py`
- `app/main.py`

测试文件:

- `tests/test_memory_operator_adapter.py`
- `tests/test_memory_operator_routes.py`

验证命令:

```bash
uv run pytest tests/test_memory_operator_adapter.py tests/test_memory_operator_routes.py -q --no-cov
uv run ruff check --select F,E9,I app/enterprise/admin/memory_operator_adapter.py app/enterprise/admin/memory_operator_routes.py tests/test_memory_operator_adapter.py tests/test_memory_operator_routes.py
```
