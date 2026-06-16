# E9 Observability / Eval Acceptance Report

日期：2026-05-30

状态：E9 closeout report

## 1. 范围

E9 不引入新的外部观测服务，也不做性能压测。本阶段把 E0-E8 已落地的治理事件收敛成可自动检查的验收面：

- 正向 smoke trace：chat / aiops / database-demo 三类路径都能归一为完整 trace。
- 负向路径定位：guardrail、permission、tool/model、database SQL 阻断都能映射到分层架构。
- SSE contract：`/api/chat_stream` 和 `/api/aiops` 输出同一套 envelope 字段，Vue3 可作为纯消费者接入。
- 报告形态：E9 report 汇总 positive smoke、negative failure localization 和 SSE contract check。

## 2. 验收矩阵

| 验收项 | 状态 | 证据 |
|---|---|---|
| 三条正向 smoke trace | PASS | `tests/test_enterprise_observability_e9.py::test_positive_smoke_traces_normalize_required_observability_fields` 覆盖 chat / aiops / database traces |
| 未授权文档、未授权工具、危险 SQL 阻断 | PASS | E5/E7 既有 targeted tests 覆盖文档和 SQL；E9 新增 failure localization 覆盖 permission/tool/database 阻断层 |
| 每个 smoke 生成完整 trace | PASS | `check_trace_completeness()` 要求 `request_started` 和 `request_completed` / `request_failed` |
| trace 字段完整 | PASS | `TraceObservation` 固化 `layer/module/decision/reason/latency_ms/status` |
| `/api/chat_stream` 和 `/api/aiops` 事件协议冻结 | PASS | `normalize_sse_event()` + route smoke 校验 `type/trace_id/request_id/stage/status/message/data` |
| 失败定位报告 | PASS | `localize_failure()` 映射 L1-L6，`build_e9_observability_report()` 汇总失败层 |
| compileall | PASS | `.venv/bin/python -m compileall -q app tests` |
| E1-E9 targeted tests | PASS | 67/67 passed |

## 3. Trace 字段

E9 trace report 不要求修改历史 `AuditEvent` schema，而是在验收层归一出 `TraceObservation`：

| 字段 | 来源 |
|---|---|
| `event_type` | `AuditEvent.event_type` |
| `trace_id` | `AuditEvent.trace_id` |
| `request_id` | `AuditEvent.request_id` |
| `layer` | 按 event type / route 映射到 L1-L6 |
| `module` | route、gateway 名称或 metadata module |
| `decision` | audit decision，缺省为 `observed` |
| `reason` | audit reason / blocked_reason / error_class / decision |
| `latency_ms` | audit latency，缺省为 `0.0`，保证报告字段稳定 |
| `status` | metadata status、request lifecycle 或 decision 推导 |

## 4. 失败定位

| 场景 | 定位层 |
|---|---|
| auth failure | L1 Auth |
| guardrail block / request blocked | L2 RequestGateway / Guardrail |
| permission denied | L3 Permission |
| tool blocked / tool failure / model failure | L4 Tool/Model |
| retrieval / upload domain failure | L5 RAG/Domain |
| database_query blocked / failed | L6 DB |
| missing trace fields / SSE contract fields | L6 Observability / Event Contract |

## 5. SSE Contract

冻结后的最小 envelope：

```json
{
  "type": "content",
  "trace_id": "trace-xxx",
  "request_id": "request-xxx",
  "stage": "content",
  "status": "running",
  "message": "Streaming content",
  "data": {}
}
```

`/api/chat_stream` 和 `/api/aiops` 保留 legacy `type`，但服务端统一补齐 envelope 字段。前端不需要再根据 route 猜测 `stage/status/message/data` 是否存在。

## 6. 验证命令

```text
.venv/bin/python -m pytest -q tests/test_enterprise_observability_e9.py
.venv/bin/python -m pytest -q tests/test_enterprise_auth.py tests/test_enterprise_request_context.py tests/test_enterprise_request_gateway.py tests/test_enterprise_gateway_routes.py tests/test_enterprise_permissions.py tests/test_enterprise_tool_gateway.py tests/test_enterprise_model_gateway.py tests/test_enterprise_rag_upload_e5.py tests/test_enterprise_database_e6.py tests/test_enterprise_database_e7.py tests/test_enterprise_admin_e8.py tests/test_enterprise_observability_e9.py
.venv/bin/python -m ruff check app/enterprise/observability app/api/chat.py app/api/aiops.py tests/test_enterprise_observability_e9.py
.venv/bin/python -m compileall -q app tests
make deps-check
```

当前结果：

- E9 targeted tests：6/6 passed。
- E1-E9 targeted bundle：67/67 passed。
- Targeted ruff：passed，仅有既有 top-level ruff config deprecation warning。
- Compileall：passed。
- Dependency check：passed。

## 7. 边界

- E9 不接 Langfuse 服务端，只参考 trace / observation 字段组织。
- E9 不重写旧 RAG/AIOps 业务流程，只在 SSE 序列化层补齐 envelope。
- E9 不把数据库工具加入默认 AIOps/RAG 工具池；DB 能力仍由 explicit database-demo provider + PermissionService table/column grants 控制。
