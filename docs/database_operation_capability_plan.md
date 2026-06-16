# 数据库操作能力实施计划

日期：2026-05-30

项目：SuperBizAgent（`super_biz_agent_py-release-2026-03-21`）

状态：DB-P0a/P0b 与 DB-P1 已完成；DB-P2 及写操作阶段仍暂缓

## 1. 结论摘要

数据库操作能力方向成立，但它不是普通工具接入，而是高风险企业工具能力。

本项目现在已经具备 E1-E7 的最小治理底座：`RequestContext`、`RequestGateway`、`ToolGateway`、`PermissionService`、本地 audit service、sandbox `SafeSqlKernel` 和 DB-P1 权限级数据库工具过滤。但当前 AIOps executor 仍会把默认 MCP servers 暴露出的工具合并进 `all_tools`，因此仍不能把数据库 MCP server 直接加入全局 `app/config.py::mcp_servers`。

修正后的执行原则：

1. 第一阶段只做 sandbox read-only proof，不接真实业务库。
2. 数据库工具默认关闭，不进入全局 MCP tool pool。
3. 第一版只暴露 `list_tables`、`describe_table`、`safe_select`。
4. `safe_select` 必须经过 SQL AST / allowlist 校验、强制 LIMIT、超时、最大结果、脱敏和本地审计。
5. 企业真实库接入必须在 DB-P1 之后，等只读业务库、只读账号、数据 owner、权限 owner 和安全 smoke 都明确后再做。
6. 写操作必须放到后续阶段，依赖审批、dry-run、影响行预览、before/after diff、事务和回滚。

## 2. 外部成熟做法对齐

### 2.1 MCP tools 是 model-controlled 能力

MCP 官方 tools 规范把 tools 定义为模型可发现和调用的能力。成熟落地要求 server 做输入校验、访问控制、限流、输出清洗，client 对敏感操作做确认、超时和审计。

对本项目的含义：

- 数据库工具不能默认暴露给所有 Agent。
- 数据库工具必须通过工具网关或显式 demo session 控制可见性。
- `notifications/tools/list_changed` 是后续工具列表变更同步机制，不是 P0 必须项。

### 2.2 SQL Agent 的成熟边界是 least privilege 和 human review

LangChain SQL Agent 文档明确提示 model-generated SQL 有固有风险，应使用权限尽量窄的数据库连接，并把 human-in-the-loop review 放在执行敏感查询之前。示例也强调限制结果数量、不做 DML、不查询所有列。

对本项目的含义：

- P0 只能使用只读账号。
- 写操作不能靠一句“用户确认”上线。
- 结果行数、列、token 和超时必须被系统强制约束。

### 2.3 SQL 注入防护不能只靠参数化查询

OWASP SQL Injection Prevention Cheat Sheet 将 prepared statements、stored procedures、allow-list input validation 列为主要防御方式。对 LLM 生成整段 SQL 的场景，参数化查询只能保护值参数，不能证明整段 SQL 的结构安全。

对本项目的含义：

- P0b 必须有 SQL AST / allowlist 校验。
- 不允许多语句。
- 不允许 DDL / DML。
- 只允许单条 `SELECT`。
- 表、列、函数都应进入 allowlist。

### 2.4 数据库 MCP 的成熟方向更接近“受控查询接口”，不是裸 SQL 执行器

Microsoft Data API Builder 的 SQL database MCP 能力把数据库以实体/关系方式暴露给 Agent，并带有权限、配置和遥测边界。这说明成熟做法不是把任意 SQL 扔给模型直接执行，而是通过受控资源、受控 schema、受控工具面向 Agent 暴露数据能力。

对本项目的含义：

- P0 的 `safe_select` 应是受控查询内核，不是通用 SQL shell。
- 后续可以演进到 entity/query intent 接口，但 P0 先做最小可验证能力。

### 2.5 工具治理和 RBAC 是数据库能力的前置依赖

Open WebUI 的 RBAC / hardening 文档将 roles、permissions、groups/ACL、tools/functions 创建权限拆开处理，并强调服务器侧工具代码和权限要谨慎治理。

对本项目的含义：

- 数据库工具必须等价视为高风险 server-side tool。
- 未有 ToolGateway 前，不能进入默认全局工具列表。
- 未有 PermissionService 前，不能接真实企业数据库。

## 3. 当前项目事实

### 3.1 当前默认 MCP server

当前 `app/config.py::mcp_servers` 只有：

```text
cls
monitor
```

### 3.2 当前 AIOps 工具暴露路径

`app/agent/aiops/executor.py::executor()` 当前逻辑：

```text
local_tools = [get_current_time, retrieve_knowledge]
mcp_tools = await get_mcp_tools_with_retry()
all_tools = local_tools + mcp_tools
llm_with_tools = llm.bind_tools(all_tools)
tool_node = ToolNode(all_tools)
```

因此，如果把 `database` 加进全局 `mcp_servers`，AIOps executor 默认就会看到数据库工具。这在没有 ToolGateway / PermissionService / 审计的情况下不可接受。

### 3.3 E7 后当前底座

当前已经实现：

- 登录用户、`current_user` 和 `RequestContext`。
- `RequestGateway` audit shell。
- `ToolGateway` 可见性过滤和执行审计。
- `PermissionService` 默认 deny / 显式 allow / deny 优先语义。
- `database_table` / `database_column` 两层 sandbox 数据库资源授权。
- 本地 `database_query` audit event 和按 trace/user/table 查询的 `DatabaseAuditQueryService`。

仍未实现或未批准：

- 真实企业只读数据库、只读账号和连接池。
- 真实业务表/列 owner 和脱敏规则 owner。
- 管理员授权控制台。
- 生产级审计查询 API 和远端审计存储。

这些缺口决定了 E7 / DB-P1 只能完成 sandbox gateway integration，仍不能接真实业务库。

## 4. 非目标

当前计划不做：

- 不把 database MCP server 加入全局 `config.mcp_servers`。
- 不接真实企业业务数据库。
- 不支持写操作。
- 不支持跨库查询。
- 不做自然语言到任意 SQL 的通用能力。
- 不把官方/reference MCP database server 当生产实现。
- 不绕过 Gateway 去实现真实权限系统。
- 不把数据库审计直接假设写入 Gateway MySQL，P0 用本地 SQLite 或 JSONL。

## 5. 实施阶段

### DB-P0a：Sandbox Read-only DB MCP

状态：已完成

目标：证明 Agent 可以在受控 sandbox 中读取数据库，同时不影响现有 AIOps/RAG 默认链路。

范围：

- [x] 建立本地 sandbox 数据库，可以是 SQLite fixture 或 Docker test DB。
- [x] 使用只读数据库账号或只读连接模式。
- [x] 自实现极小 Python MCP database server，或把参考 server 仅用于本地实验。
- [x] 只暴露三个工具：
  - `list_tables`
  - `describe_table`
  - `safe_select`
- [x] Feature flag 默认关闭，例如 `ENABLE_DATABASE_DEMO_TOOLS=false`。
- [x] 不修改全局 `config.mcp_servers` 默认返回值。
- [x] 只在显式 `database-demo` session / eval / manual smoke test 中传入 database server 配置。
- [x] 审计先写本地 SQLite 或 JSONL。
- [x] 增加 targeted tests，验证默认路径没有 database tools。

验证标准：

- 默认 AIOps executor 获取的 MCP 工具仍只有现有 cls/monitor 工具。
- 显式 database-demo session 能列表、查看 schema、执行安全 SELECT。
- `DROP`、`UPDATE`、`DELETE`、多语句 SQL、无 LIMIT 大查询全部被阻断。
- 审计文件记录 query hash、user/session、表名、行数、耗时、status。

不做：

- 不接真实业务库。
- 不接 Gateway 权限表。
- 不支持写操作。
- 不进入默认工具池。

### DB-P0b：Safe SQL Kernel

状态：已完成，依赖 DB-P0a

目标：把 `safe_select` 从“字符串过滤”提升为可测试的安全查询内核。

范围：

- [x] 选择 SQL parser，优先评估 `sqlglot`，备选 `sqlparse`。
- [x] 校验 SQL AST，只允许单条 `SELECT`。
- [x] 禁止：
  - 多语句。
  - DDL：`CREATE` / `ALTER` / `DROP` / `TRUNCATE`。
  - DML：`INSERT` / `UPDATE` / `DELETE` / `MERGE`。
  - 权限操作：`GRANT` / `REVOKE`。
  - 危险函数或副作用函数。
  - 未授权 schema/table/column。
- [x] 强制 LIMIT，默认最大 100 行。
- [x] 强制 query timeout，默认 5 到 10 秒。
- [x] 强制结果大小上限，例如最大行数、最大字节数、最大 token 估算。
- [x] 支持字段脱敏：
  - password/secret/token/key 完全隐藏。
  - phone/id_card/email 等按规则脱敏。
- [x] 使用 read-only transaction 或数据库只读连接。
- [x] 审计记录原 SQL hash、脱敏 SQL、阻断原因和执行指标。

验证标准：

- SQL AST 单测覆盖合法 SELECT、无 LIMIT、SELECT *、多语句、DML、DDL、未授权表、未授权列、敏感列脱敏。
- `safe_select` 不依赖 LLM 自律。
- 安全失败返回结构化错误，不把数据库异常原样暴露给用户。

不做：

- 不实现复杂 SQL 方言兼容。
- 不支持跨库 join。
- 不支持写操作。
- 不支持任意函数。

### DB-P0c：Demo Eval / Smoke

状态：待执行，依赖 DB-P0a/P0b

目标：给“Agent 能查数据库”一个可重复演示的验证闭环。

范围：

- [ ] 准备 3 到 5 个 sandbox 查询样本。
- [ ] 覆盖聚合、过滤、排序、top-k。
- [ ] 覆盖 2 到 3 个阻断样本。
- [ ] 输出 demo report，记录 query、工具调用、结果、审计路径。

验证标准：

- sandbox 正常查询全部通过。
- 危险查询全部被阻断。
- 默认 AIOps/RAG 工具池未变化。

### DB-P1：Gateway 集成

状态：已完成（E7，仍限制在 sandbox / database-demo）

触发条件：

- [x] Gateway-MVP 已实现 `current_user`、trace_id、RequestGateway audit shell、ToolGateway allowlist/filter。
- [x] PermissionService 至少支持用户/部门/工具授权。
- [x] 审计服务可以持久化工具调用事件。

范围：

- [x] 数据库工具通过 ToolGateway 过滤后才暴露。
- [x] PermissionService 检查 sandbox database/table/column 权限。
- [x] Schema Registry 记录可见表/列、敏感字段、业务含义。
- [x] AuditService 统一记录数据库工具调用。
- [x] Gateway trace 串联 request/tool/database event；chat/aiops 全链路展示仍留给后续前端/协议阶段。

验证标准：

- 未授权用户看不到 database tools。
- 授权用户只能访问 allowlist 内表/列。
- 权限变更后缓存失效。
- 审计可按 trace_id / user_id / table_name 检索。

验证结果：

- `tests/test_enterprise_database_e7.py` 覆盖 permission-gated DB tool 可见性、table/column 授权过滤、DB audit 查询和写操作继续阻断。
- `tests/test_enterprise_database_e6.py`、`tests/test_enterprise_database_e7.py`、`tests/test_enterprise_tool_gateway.py`、`tests/test_enterprise_permissions.py` 31/31 通过；E1-E7 targeted bundle 55/55 通过。
- targeted `ruff check`、`compileall`、`make deps-check` 和 `git diff --check` 通过。
- E7 实现提交：`2554343ac123fe5bcea65cb9604d49aaa3c2d708`。

不做：

- 不支持写操作。
- 不接未经授权的真实库。

### DB-P2：企业只读数据库接入

状态：暂缓，依赖 DB-P1 之后的真实库 owner / 只读账号 / 脱敏规则准备

触发条件：

- Gateway-MVP 和 DB-P1 完成。
- 有明确的只读业务库、只读账号和数据脱敏规则。
- 有用户/部门权限 owner。

范围：

- [ ] 接入一个真实只读数据源。
- [ ] 使用专用只读账号。
- [ ] 使用最小表/列 allowlist。
- [ ] 配置查询并发、超时、慢查询审计。
- [ ] 完成安全 smoke test 和权限绕过测试。

验证标准：

- 真实库只读查询通过。
- 写操作在数据库权限层和应用层都无法执行。
- 敏感字段不泄露。
- 审计完整。

### DB-P3：写操作审批

状态：未来工作，依赖 DB-P2 稳定运行

触发条件：

- 有明确业务场景要求写操作。
- 有审批 owner。
- 有可回滚的业务流程。

范围：

- [ ] 只支持白名单写操作模板，不开放任意 DML。
- [ ] Dry-run。
- [ ] Affected rows preview。
- [ ] Before/after diff。
- [ ] Approval token。
- [ ] 操作人与审批人分离。
- [ ] Transaction + rollback。
- [ ] 写操作限流和二次确认。

验证标准：

- 未审批写操作全部被阻断。
- 审批 token 过期或不匹配时阻断。
- 影响行超阈值时阻断或升级审批。
- 写失败可回滚。

不做：

- 不开放任意 SQL 写入。
- 不允许无 WHERE 的 update/delete。
- 不允许 DDL。

### DB-P4：多数据源和高级功能

状态：未来工作

候选能力：

- 多数据源。
- 连接池和健康检查。
- 查询结果导出。
- 大结果分页或 artifact 输出。
- 定时报表。
- 数据可视化。

触发条件：

- DB-P2 真实只读能力稳定。
- 有真实用户使用数据库查询。
- 单一数据源不足以支撑业务场景。

## 6. Schema Registry

P0b 开始需要一个最小 Schema Registry，即使先用本地 YAML/JSON 文件。

示例：

```json
{
  "database_id": "sandbox_sales",
  "tables": {
    "orders": {
      "allowed": true,
      "description": "订单表",
      "max_rows": 100,
      "columns": {
        "order_id": {"allowed": true, "sensitive": false},
        "customer_name": {"allowed": true, "sensitive": false},
        "phone": {"allowed": true, "sensitive": true, "mask": "phone"},
        "total_amount": {"allowed": true, "sensitive": false},
        "internal_note": {"allowed": false, "sensitive": true}
      }
    }
  }
}
```

规则：

- 默认 deny。
- 表必须显式 allow。
- 列必须显式 allow。
- 敏感列必须声明 mask。
- 未登记表/列一律不可查。

## 7. 审计模型

P0 本地审计字段：

```text
event_id
created_at
session_id
trace_id
actor_id
database_id
tool_name
operation_type
target_tables
sql_hash
sanitized_sql
rows_returned
result_size_bytes
execution_time_ms
status
blocked_reason
error_class
```

P0 存储：

- 首选 SQLite。
- JSONL 可作为最小 fallback。

P1 后迁移到 Gateway AuditService / MySQL。

## 8. 测试计划

### 8.1 默认工具池隔离

- [x] 默认 `get_mcp_tools_with_retry()` 不包含 database tools。
- [x] 只有显式 database-demo provider + `tool` grant 才能看到 database tools。
- [x] AIOps executor 默认路径不变。

### 8.2 SQL 安全

- [x] 合法 SELECT 通过。
- [x] 无 LIMIT 被自动加 LIMIT 或阻断。
- [x] DML / DDL / 多语句阻断。
- [x] 未授权表/列阻断。
- [x] 敏感列脱敏。
- [x] 超时和结果大小限制生效。

### 8.3 审计

- [x] 成功查询写审计。
- [x] 阻断查询写审计。
- [x] 失败查询写审计。
- [x] SQL 原值不泄露敏感参数。

### 8.4 Demo smoke

- [ ] sandbox 查询样本通过。
- [ ] sandbox 阻断样本通过。
- [ ] compileall 通过。

### 8.5 DB Gateway 权限

- [x] `tool` grant 控制 database-demo 工具可见性。
- [x] `database_table` grant 控制 list / describe / select 的表可见性。
- [x] `database_column` grant 控制 describe / select 的列可见性。
- [x] DB audit query 可按 `trace_id` / `user_id` / `table_name` 过滤。

## 9. 与 Gateway 的依赖关系

正确依赖顺序：

```text
Gateway-MVP
  -> current_user / trace_id
  -> RequestGateway audit shell
  -> ToolGateway allowlist/filter
  -> PermissionService 基础授权
  -> AuditService
    -> DB-P1 Gateway 集成（已完成）
      -> DB-P2 企业只读数据库
        -> DB-P3 写操作审批
```

例外：

```text
DB-P0a/P0b sandbox demo 可以先做，
但必须默认关闭、不进全局工具池、不接真实库。
```

## 10. 决策记录

| 决策 | 结论 | 原因 |
|---|---|---|
| 数据库能力是否成立 | 成立 | 企业助手需要受控数据查询能力 |
| 是否直接加到全局 `mcp_servers` | 否 | 当前 executor 会默认暴露所有 MCP tools |
| 官方/reference database MCP server 是否可直接生产使用 | 否 | 只能作为参考或 sandbox 实验 |
| P0 是否接真实业务库 | 否 | 缺少 Gateway / 权限 / 审计底座 |
| P0 是否支持写操作 | 否 | 风险高，缺审批和回滚 |
| 第一阶段审计写哪里 | 本地 SQLite/JSONL | Gateway MySQL 尚未落地 |
| SQL 安全是否只靠参数化查询 | 否 | LLM 生成整段 SQL 需要 AST/allowlist |
| database-demo 可见性靠配置隐藏还是权限控制 | 权限控制 | E7 后显式 session 也必须通过 `tool` / table / column grants |

## 11. 下一步行动

DB-P0a/P0b 和 DB-P1 已完成。若继续数据库方向，下一步只允许进入 DB-P2 企业只读数据库接入，且必须先满足：

- 明确真实只读业务库和只读账号。
- 明确业务表/列 owner 和数据脱敏规则。
- 明确用户/部门权限 owner。
- 完成安全 smoke test 和权限绕过测试设计。

推荐后续顺序：

```text
DB-P2 企业只读库
  -> DB-P3 写操作审批
```

如果只是快速展示 Agent 能查数据库，继续使用当前 sandbox / database-demo 路径即可：

```text
DB-P0a/P0b sandbox read-only
  + DB-P1 permission-gated database-demo
```

但必须满足：

- 默认关闭。
- sandbox 数据库。
- 只读。
- 不进全局工具池。
- 不接真实库。
- 不做写操作。

## 12. 参考资料

- MCP tools specification: https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- MCP reference servers: https://github.com/modelcontextprotocol/servers
- OWASP MCP Security Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/MCP_Security_Cheat_Sheet.html
- OWASP SQL Injection Prevention Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html
- LangChain SQL Agent: https://docs.langchain.com/oss/python/langchain/sql-agent
- Microsoft Data API Builder SQL database MCP: https://learn.microsoft.com/en-us/azure/data-api-builder/mcp/overview
- Open WebUI RBAC: https://docs.openwebui.com/features/authentication-access/rbac/
- Open WebUI Hardening: https://docs.openwebui.com/getting-started/advanced-topics/hardening/
