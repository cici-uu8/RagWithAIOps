# 清单 2.1 快速导航

## 一句话总结

清单 2 覆盖清单 1 之后的核心增强能力：评测护栏、记忆集成、AIOps offload、PDF 工具、路由 shadow 诊断，以及条件触发的 query rewrite。G0 已完成；E1 第一切片、permission-isolation 语义修复、C4 default-off RAG session memory 接入、C5 default-off AIOps tool-result offload、B4 default-off PDF Agent 工具链和 D1 routing shadow 诊断字段已完成，但 active 能力仍保持生产禁用。

## 优先级排序

| 章节 | 名称 | 优先级 | 工作量 | 必做/可选 |
|---|---|---|---|---|
| **G0** | 固化清单 1 工作 | P0 | 已完成 | 审计记录 |
| **E1** | 评测体系扩展 | P2 | 第一切片已完成 | permission/citation 绿，scope 仍有 1 个内容问题 |
| **C4** | memory -> RAG prompt | P0 | 已完成 | 默认 off，active 禁止生产启用 |
| **C5** | memory -> AIOps offload | P1 | 已完成 | 默认关闭，保留完整原文证据 |
| **B4** | PDF Agent 工具 | P1 | 已完成 | 默认关闭，权限 no-leak 测试通过 |
| **D1** | routing shadow 诊断 | P2 | 已完成 | shadow-only，不改真实 route |
| **A3** | query rewrite shadow | P2 | 2-3 天 | 条件触发，当前暂缓 |

## 关键决策点

### G0 已完成

清单 1 的工作已经固化到提交链：

```text
27f4765 -> 01d686c -> df9e13a -> 868d02d -> e56567d -> 4d9cde9
```

清单 2 不再以历史 dirty workspace 为前提。每个新章节应单独分支或单独提交。

### E1 可以提前

memory active、PDF 工具、offload 都会影响权限、scope、citation 或 prompt 行为。E1 评测护栏可以先做，也可以和 C4 并行，避免后续只靠人工 smoke 判断安全性。

当前 E1 baseline：

| evalset | 结果 | 含义 |
|---|---:|---|
| permission_isolation_10q | 10/10 passed | 跨权限意图当前会被过滤，不再从无关 allowed KB 回答 |
| scope_lock_10q | 9/10 passed | 未发现跨库串库，但仍有内容匹配缺口 |
| citation_accuracy_10q | 10/10 passed | 当前小样本 source_ref 回查可解析 |

E1 小样本变绿不等于可以生产开启 C4/C5/B4。memory TTL/清理、stale summary、offload 原文审计、PDF 权限 no-leak、配置回滚记录仍是各自章节的 active 前置门。

### C4 接入点在请求级 prompt

不要在 `RagAgentService._initialize_agent()` 恢复 session memory。它是全局 agent 初始化，不知道当前 `session_id` / `owner_id`。正确接入点是 `query()` / `query_stream()` 调 `_build_runtime_system_prompt()` 时，结合当前 `RequestContext` 和 `session_id` 注入。

当前 C4 已实现为 default-off：
- `off`：不读、不注入、不写 live tail。
- `shadow`：可读取并记录 live tail，但不改 prompt。
- `active`：仅在 TTL / cleanup / stale / 长度上限门禁满足时注入 bounded memory context。

这仍不是生产 active。生产启用还需要更大样本 eval、shadow 观察和回滚记录。

### C5 先截断展示，不改证据结构

AIOps 的 `past_steps` 当前是普通 tuple 文本结果。第一版只能把长结果替换成“摘要 + result_ref”字符串，完整原文写入 offload store；不能把 `ToolResultRef` Python 对象塞进 LangGraph state、SSE、audit 或 eval matcher。

当前 C5 已实现为 default-off：
- `tool_result_offload_enabled=False` 时旧行为不变。
- 显式启用后，长 result 写入 `SessionToolResultOffloadStore`，`past_steps` 仍是字符串。
- 写入失败、缺 session/owner、超过 max bytes 时保留原文，禁止 summary-only。
- 完整原文按 owner 回查；offload 后 `aiops_executed_tools` 仍保留 required-tool 覆盖证据。

这仍不是生产 active。生产启用还需要真实 AIOps 长日志 smoke、阈值校准、eval 复跑和回滚记录。

### B4 工具参数不能暴露 context

模型可见工具参数只能有 `doc_id`、`page`、`table_id` 这类业务字段。`RequestContext` 必须由 `ToolGateway` / provider 后端注入，并在后端做 `DocumentAccessService` 权限校验。

当前 B4 已实现为 default-off：
- `pdf_agent_tools_enabled=False` 时 PDF 工具不注册，旧 RAG 工具列表不变。
- 显式启用后，`PdfDocumentToolProvider` 通过 `ToolGateway.execute(context, ...)` 后端注入 `RequestContext`。
- `read_document_page` 先做 `DocumentAccessService.can_read_document()`，再读 `blocks.json`。
- `extract_document_table` 先做相同权限校验，再读 `tables.json`。
- 无权限响应不泄露标题、正文、表格值或 artifact path。

这仍不是生产 active。生产启用还需要真实 indexed PDF smoke、E1 复跑、PDF page/table eval 复跑和回滚记录。

### D1 只写 metadata

当前 `RoutingDecision` 是 Pydantic `BaseModel`，不是标准库数据类。D1 优先把 `domain/intent/approval_required/execution_mode` 放进 `metadata.routing_diagnostics`，保持 shadow-only，不改真实 route schema 和执行路径。

当前 D1 已实现：
- `StrategyRouter.evaluate(...)` 返回前补 `metadata.routing_diagnostics`。
- `record_shadow_decision(...)` 的 audit metadata 自动包含这些字段。
- `RoutingDecision.route`、provider 顺序、chat/aiops 真实执行路径不变。

### A3 当前不做

18/18 current-scope 通过，没有检索表达问题的证据。只有后续 eval 显示召回不足且归因于 query 表达时，才触发 A3。

## 每节验收要点

| 章节 | 核心验收标准 | 失败分类举例 |
|---|---|---|
| G0 | 提交链和文档记录可追溯 | `stale_plan_state` / `untracked_orphan` |
| E1 | 新 evalset 能检出 wrong_scope / citation 硬失败 | `wrong_scope_not_detected` / `citation_check_too_loose` |
| C4 | session 重启后 active 模式能恢复 bounded summary，off 不读不注入，shadow 不改 prompt | `snapshot_not_restored` / `prompt_pollution` / `stale_summary_injected` |
| C5 | 长 tool result 可 offload，`past_steps` 仍是字符串，完整原文 owner-checked 可回查 | `state_serialization_break` / `evidence_lost` / `summary_only_offload` |
| B4 | Agent 能按页读、按表抽，权限隔离不破 | `permission_bypass` / `page_number_mismatch` |
| D1 | routing diagnostics 进入 metadata，不改真实 route | `diagnostics_missing` / `regression_route_changed` |

## 风险控制原则

1. 每节独立分支开发，验收通过再合并。
2. 所有新配置默认 off/shadow，不改现有行为。
3. 集成步骤必须有 degraded fallback，失败不能让主流程挂。
4. 每节改动不超过 3 个核心模块，降低回归风险。
5. 任何 prompt 注入都必须明确“不是资料引用”，不能伪装成 SourceRef / citation。

## 长期运行注意事项

- **memory/offload 数据增长**：需要 TTL、容量上限、owner 级清理、DB size 统计；未实现前不能 active。
- **summary 过期**：memory summary 需要 stale 判断；过期 summary 不进 active prompt。
- **prompt 污染**：注入必须可关闭、长度有上限、明确不是 citation / SourceRef。
- **审计证据**：tool offload 只能摘要化 prompt 展示，完整原文必须 owner-checked 可回查；summary-only 不能验收。
- **权限泄露**：PDF 工具和 offload 回查必须后端校验 owner/context；拒绝响应不能泄露正文、标题、表格或 artifact path。
- **配置误开**：生产启用前必须有 eval 证据、`PROJECT_STATE.md` 记录和回滚记录；默认仍是 off/False/shadow。
- **eval 过期**：18/18 和 E1 当前 30q 都是小样本，不能代表长期充分；新增能力后必须扩展并复跑。

## 预期完成时间

- 最小集：E1 权限语义修复 + C4 + C5 = 约 5-7 天
- 推荐集：最小集 + B4 + D1（已完成）
- 完整集：A3 仍为条件触发；D2/D3 属于独立共享边界收口任务

---

详见 `记忆_ragpdf_并行开发_执行步骤清单2.md` 完整内容。
