# 数据库 Stage 3 Context Tool 设计与验收记录

日期: 2026-06-17

状态: 第一版已完成。该版本只面向 RAG/local-agent 查询链路，不扩展到 AIOps。

## 目标

在不放宽 SQL 执行边界的前提下，让 Agent 在生成 SQL 前拿到当前用户可见的数据库上下文:

- 可见表和授权列。
- 与问题相关的 Q-SQL 示例。
- 明确的安全限制。
- 可直接放入模型上下文的 `context_text`。

该工具不执行 SQL，不读取 sample rows，不替代 `database_demo.safe_select`。

## 接入方式

本阶段复用现有企业工具链路:

```text
RAG Agent
  -> ToolExecutionFacade.get_bindable_tools(context, capability="rag")
  -> ToolGateway.execute(context, "database_demo.retrieve_context", ...)
  -> LocalAgentToolProvider
  -> app.tools.database_tool.retrieve_database_context
  -> DatabaseContextBuilder
```

关键约束:

- 不新增并行 `DatabaseContextToolProvider`。
- 不假设 `ToolGateway.register_provider()`，当前代码没有这个接口。
- 不直接把工具塞进 `RagAgentService.tools`。
- 不新增 HTTP route。

## Resource ID

治理资源 ID 固定为:

```text
database_demo.retrieve_context
```

模型可绑定工具名为:

```text
retrieve_database_context
```

这样权限、资源目录、审计事件和 `database_demo.safe_select` 保持同一命名体系。

## 代码落点

- `app/enterprise/database/qsql_examples.py`
  - 将 Stage 2 文档中的 15 条门禁 Q-SQL 示例代码化。
  - `QSqlExampleRegistry.search(...)` 使用轻量标签/关键词匹配。
- `app/enterprise/database/context_builder.py`
  - `DatabaseContextBuilder.build_context(...)` 组合 registry、permission filter 和示例。
  - 普通用户必须有 table read 和 column read 授权。
  - admin 仅能看到 registry-visible columns，仍不会看到 `allowed=False` 字段。
- `app/tools/database_tool.py`
  - 新增 `retrieve_database_context(query, database_id="sandbox_sales")`。
  - 使用当前 `RequestContext` 和 database gateway 的 `permission_service`。
- `app/enterprise/tools/local_provider.py`
  - 注册 `ToolDefinition(resource_id="database_demo.retrieve_context", name="retrieve_database_context", capability="rag")`。
- `app/enterprise/admin/resources.py`
  - 将 `database_demo.retrieve_context` 加入 tool resource catalog。

## 权限与输出边界

`DatabaseContextBuilder` 对输出做两层过滤:

- 表和列: 通过 `DatabasePermissionFilter` 返回当前用户可见的表和授权列。
- 示例: 只返回可见表的示例；如果示例 SQL 需要未授权列，则返回示例问题和解释，但 `sql=None`，并设置 `sql_unavailable_reason="requires_ungranted_columns"`。

无表权限时，结构化 `relevant_examples` 为空，`context_text` 只说明当前用户没有可见的相关数据库表。

## Sample Rows 决策

第一版 context tool 不取 sample rows。

原因:

- sample rows 本质是数据库查询，必须继续走 `ToolGateway -> database_demo.safe_select -> SafeSqlKernel`。
- 内部自动取样会增加工具调用成本和 `database_query` audit 噪声。
- P1 Database Catalog Browser 已经提供受控 sample rows 路径，可复用但不应隐式嵌入 context tool。

后续如需在上下文中展示样例行，应作为显式参数或独立调用，并继续使用 `database_demo.safe_select`。

## AIOps 决策

第一版不接入 AIOps。

理由:

- 当前需求来自 RAG/普通 Agent 的数据库问答上下文增强。
- AIOps 是否需要门禁数据库上下文，应由真实诊断场景触发。
- 过早接入会扩大 tool catalog、prompt、权限和验收范围。

## 验收口径

硬验收只覆盖稳定治理链路:

- 工具在 `LocalAgentToolProvider` 可见。
- `ToolExecutionFacade` 能按 `capability="rag"` 绑定。
- 未授权时不会进入可绑定工具列表，执行会被 `ToolGateway` 拒绝并记录 `tool_blocked`。
- 授权后可通过 `ToolGateway.execute(...)` 成功调用，并记录 `tool_call`。
- `ResourceCatalogService` 能列出 `database_demo.retrieve_context`。
- 上下文只包含授权表列，不泄露 `raw_device_payload` 或未授权表示例。

LLM 端到端生成 SQL、浏览器操作和 AIOps 诊断不是第一版硬验收。

## 验证

已通过:

```bash
uv run pytest tests/test_qsql_examples.py tests/test_database_context_builder.py tests/test_tool_execution_facade.py tests/test_rag_database_tools.py tests/test_enterprise_database_e7.py tests/test_enterprise_admin_e8.py -q --no-cov
```

结果: 46 passed。仅出现既有 Pydantic deprecation warning。

最终 closeout 还应运行 targeted ruff、compileall 和 `git diff --check`。
