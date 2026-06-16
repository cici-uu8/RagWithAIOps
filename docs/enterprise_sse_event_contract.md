# Enterprise SSE Event Contract

日期：2026-05-31

状态：Frozen - E9 baseline，F5 补充统一失败 envelope，F6 补充人工审批 pending event，E11 Vue3 consumer 必须按本协议消费，不反向修改后端业务语义。

## 1. 目的

本文件定义企业助手流式事件的最小协议基线，避免 `/api/chat_stream`、`/api/aiops` 和后续工具 / 模型 / DB 事件各自形成互不兼容的格式。

E2 阶段只要求做到：

- 每个流式事件都能携带 `trace_id`。
- 每个流式事件都能携带 `request_id`。
- 当前旧事件类型能映射到统一 envelope。
- blocked / failed 事件必须可被 audit trace 串联。

完整协议已在 E9 验收中冻结；后续 E11 只能作为消费者展示这些字段。

F5 额外补充：

- 所有失败事件必须额外带上 `error_class`、`decision`、`user_message`。
- 安全阻断类错误必须落到 `blocked` 决策，不得自动进入 retry / fallback。
- 模型 / 工具 / 检索类失败可表达 `degraded`、`retrying`、`failed`。

F6 额外补充：

- 高风险任务进入人工审批时返回 `type=pending_approval`。
- `pending_approval` 必须携带 `stage=human_review`、`status=pending`、`review_id`、`task_contract_id` 和 `data.review_id` / `data.task_contract_id`。
- 被拒绝的审批重提任务返回 `type=error`、`stage=human_review`、`status=rejected`，并保持 F5 error envelope 字段。

## 2. 推荐 Envelope

```json
{
  "type": "stage",
  "trace_id": "trace-xxx",
  "request_id": "request-xxx",
  "stage": "retrieval",
  "status": "running",
  "message": "正在检索知识库",
  "data": {}
}
```

字段说明：

| 字段 | E2 要求 | 说明 |
|---|---|---|
| `type` | 必填 | 事件类型。E9 后继续保留 legacy type，避免破坏现有消费者。 |
| `trace_id` | 必填 | 串联 gateway、audit、tool、model、retrieval、DB 事件。 |
| `request_id` | 必填 | 单次请求实例 ID。客户端或网关生成。 |
| `stage` | 必填 | 当前阶段，例如 `content`、`retrieval`、`tool`、`request_blocked`、`done`。 |
| `status` | 必填 | `running`、`completed`、`failed`、`blocked`、`degraded`、`retrying`。 |
| `message` | 必填 | 面向 UI 的短消息。 |
| `data` | 必填 | 事件结构化负载；legacy 顶层字段会被归入 `data`。 |
| `error_class` | 失败事件必填 | F5 结构化失败类别，例如 `model_unavailable`。 |
| `decision` | 失败事件必填 | `abort`、`retry`、`fallback`、`partial`、`request_more_info`、`recoverable_error`。 |
| `user_message` | 失败事件必填 | 可直接展示给用户的短说明。 |

## 3. 当前 E2 映射

### `/api/chat_stream`

当前事件：

- `debug`
- `tool_call`
- `search_results`
- `content`
- `done`
- `error`
- `blocked`

E2 baseline：

- 所有事件必须包含 `trace_id` 和 `request_id`。
- `complete` 从旧 RAG stream 映射为 SSE `done`。
- `blocked` 由 `RequestGateway.execute_stream()` 的 guardrail/rate-limit 阻断产生，不能进入旧 RAG stream。
- `search_results` 是 legacy 类型，E9 前应明确映射到 `stage=retrieval` 或 `type=stage`。

### `/api/aiops`

当前事件由 `AIOpsService.diagnose()` 产生，常见类型包括：

- `plan`
- `step_complete`
- `report`
- `complete`
- `error`
- `blocked`
- `pending_approval`

E2 baseline：

- Adapter 必须为所有 dict event 注入 `trace_id` 和 `request_id`。
- `blocked` 由 RequestGateway guardrail 阻断产生，包含 `stage=request_blocked`。
- `plan`、`step_complete`、`report` 是 legacy 类型，E9 前应映射到统一 `stage/status/message/data` envelope。

## 4. E2 Contract Smoke

E2 通过以下测试锁住最小合同：

- `/api/chat_stream` success SSE 含 `trace_id` 和 `request_id`，并写 `request_completed` audit。
- `/api/chat_stream` rule guardrail blocked SSE 含 `trace_id` 和 `request_id`，并写 `request_failed` audit。
- `/api/aiops` SSE 含 `trace_id` 和 `request_id`，并写 `request_completed` audit。

## 5. E9 冻结结果

E9 新增 `app/enterprise/observability/sse_contract.py`，并在 `/api/chat_stream` 与 `/api/aiops` 的 SSE 序列化层统一调用 `normalize_sse_event()`。

冻结字段：

- `type`
- `trace_id`
- `request_id`
- `stage`
- `status`
- `message`
- `data`

冻结映射：

| type | stage | status |
|---|---|---|
| `debug` | `debug` | `running` |
| `tool_call` | `tool` | `running` |
| `search_results` | `retrieval` | `completed` |
| `content` | `content` | `running` |
| `complete` / `done` | `done` | `completed` |
| `plan` | `plan` | `completed` |
| `step_complete` | `tool` | `completed` |
| `report` | `report` | `completed` |
| `blocked` | `request_blocked` | `blocked` |
| `pending_approval` | `human_review` | `pending` |
| `error` | `error` | `failed` |
| `error` + `error_class=model_unavailable` | `model_call` | `degraded` / `failed` |
| `error` + `error_class=tool_failed` | `tool` | `retrying` / `degraded` / `failed` |
| `error` + `error_class=sql_blocked` | `database` | `blocked` |

`error_class`、`reason`、`decision`、`latency_ms` 可以出现在 SSE payload 中；F5 起失败事件必须提供 `error_class`、`decision`、`user_message`，普通非失败流式事件不要求包含这些字段。

F5 错误事件示例：

```json
{
  "type": "error",
  "trace_id": "trace-xxx",
  "request_id": "request-xxx",
  "stage": "model_call",
  "status": "degraded",
  "message": "主模型暂时不可用，正在使用备用模型。",
  "error_class": "model_unavailable",
  "decision": "fallback",
  "data": {
    "error_class": "model_unavailable",
    "decision": "fallback",
    "recoverable": true,
    "retryable": true,
    "fallback_allowed": true,
    "user_message": "主模型暂时不可用，正在使用备用模型。",
    "audit_category": "degradation"
  }
}
```

## 6. E11 Consumer 规则

- Vue3 只消费本文件定义的 envelope，不新增 UI-only 后端字段。
- 前端可以继续按 legacy `type` 做分支，但不能假设某个 route 缺少 `stage/status/message/data`。
- 如果 E11 发现必须改变事件语义，应退回 E9/E10 补协议和测试，而不是在前端阶段顺手修改后端协议。
