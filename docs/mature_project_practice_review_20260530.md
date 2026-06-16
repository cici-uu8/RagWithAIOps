# 成熟项目做法外部审视报告

日期: 2026-05-30

范围:

1. `docs/database_operation_capability_plan.md`
2. `docs/项目与成熟项目做法差距.md`
3. `docs/superpowers/specs/2026-05-26-enterprise-agent-gateway-v1-design.md`

## 1. 结论摘要

三个待办方向都成立，但成熟做法要求它们按不同风险等级执行:

- 数据库操作能力是高风险工具能力，不能作为普通 MCP server 直接加入默认工具池。正确方式是 sandbox、只读、默认关闭、安全查询内核先行。
- 项目与成熟项目差距 backlog 的“观测 / shadow / eval / benchmark 先行”符合成熟工程做法，不应直接开 reranker、加简单 cache 或改 Milvus 参数。
- Enterprise Agent Gateway V1 的认证、RBAC、ToolGateway、ModelGateway、trace/audit 方向符合成熟项目形态，但应按最小骨架分阶段落地。

## 2. 关键来源

### MCP Tools 官方规范

URL: https://modelcontextprotocol.io/specification/2025-06-18/server/tools

关键事实:

- MCP tools 是 model-controlled，模型可以自动发现和调用工具。
- 规范要求 tool server 校验输入、实现访问控制、限流、清洗输出；client 应在敏感操作前提示用户确认、展示工具输入、验证结果、设置 timeout、记录审计。
- `notifications/tools/list_changed` 是工具列表变更通知机制。

对本项目的含义:

- database tool 不能直接进入默认 MCP tool pool。
- 高风险工具必须有访问控制、输出清洗、timeout 和审计。
- 当前 MCP cache + 后续 metrics/list_changed 的方向正确。

### MCP reference servers README

URL: https://github.com/modelcontextprotocol/servers

关键事实:

- `modelcontextprotocol/servers` 说明 reference servers 是教育/参考实现，不是 production-ready。
- PostgreSQL reference server 已归档，定位是 read-only database access with schema inspection。

对本项目的含义:

- 官方 Postgres server 可用于理解模式，但不能直接作为生产实现。
- 数据库 P0a 应该自实现极小 sandbox server，或者只把官方 server 当调研对象。

### LangChain SQL Agent 文档

URL: https://docs.langchain.com/oss/python/langchain/sql-agent

关键事实:

- SQL agent 流程包括列表、schema、生成查询、查询检查、执行、根据错误修正。
- 文档明确提示 model-generated SQL 有固有风险，数据库连接权限应尽量缩窄。
- SQL agent 示例要求限制结果数量、不查询所有列、不做 DML。
- 对 `sql_db_query` 支持 human-in-the-loop review。

对本项目的含义:

- DB P0a/P0b 的 read-only、LIMIT、显式列、安全 query checker、人工审批方向是必要的。
- 写操作应放到很后面，不能只靠“用户确认”。

### OWASP SQL Injection Prevention Cheat Sheet

URL: https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html

关键事实:

- 主要防御包括 prepared statements、proper stored procedures、allow-list input validation。
- 仅靠 escaping 是强烈不推荐的方式。

对本项目的含义:

- 对普通参数输入，参数化查询是底线。
- 对 LLM 生成整段 SQL，必须额外做 SQL AST / allowlist 校验；不能只写“参数化查询”。

### Open WebUI RBAC 与 Hardening 文档

URL:

- https://docs.openwebui.com/features/authentication-access/rbac/
- https://docs.openwebui.com/getting-started/advanced-topics/hardening/

关键事实:

- Open WebUI 的权限模型拆成 roles、permissions、groups/ACL。
- RBAC 不能替代外部 provider 的 least-privilege credentials。
- Tools/Functions 会在服务器侧执行代码，默认应限制为管理员创建/导入，并审查工具代码。
- 默认 workspace tools access 等权限应谨慎关闭，由 group-level overrides 精准开启。

对本项目的含义:

- Agent Gateway V1 的 RBAC + ToolGateway + resource grants 方向正确。
- database tool 必须被视作高风险 server-side tool，不应默认暴露给普通用户。

### LiteLLM Proxy 文档

URL: https://docs.litellm.ai/

关键事实:

- LiteLLM proxy 提供 auth hooks、logging hooks、cost tracking、rate limiting、retry/fallback。

对本项目的含义:

- Enterprise Agent Gateway V1 里的 ModelGateway、usage/cost、fallback、rate limit 是成熟项目常见边界。
- 但应先做最小骨架，不要一次性实现完整企业 AI Gateway。

### LangGraph Persistence 文档

URL: https://docs.langchain.com/oss/python/langgraph/persistence

关键事实:

- checkpointer 使用 thread_id 保存和恢复状态。
- In-memory store 适合开发/测试；生产建议使用 Postgres、MongoDB、Redis 等持久 store。

对本项目的含义:

- `MemorySaver` 持久化决策属于 Runtime readiness。
- 是否替换取决于重启恢复、长会话、HITL、多副本，不应和 RAG/AIOps 质量优化混排。

### LangChain Cross Encoder Reranker 文档

URL: https://docs.langchain.com/oss/python/integrations/document_transformers/cross_encoder_reranker

关键事实:

- Cross-encoder reranker 是成熟 RAG 常用重排方式。
- 典型模式是先用 vector search 召回较大 top-k，再 rerank 到较小 top-n。

对本项目的含义:

- RAG-1 reranker shadow/eval 方向正确。
- 当前 `local_lexical_v1` 不等于 cross-encoder；不能直接默认开启。

### Milvus Performance FAQ

URL: https://milvus.io/docs/performance_faq.md

关键事实:

- `nprobe` 是数据集和场景相关参数，需要在准确率和性能之间权衡。
- 官方建议通过反复实验找到合适值。

对本项目的含义:

- RAG-3 benchmark 方向正确。
- 不应直接把 `nprobe` 或 index type 改成外部推荐值。

## 3. 三个待办逐项审视

### 3.1 数据库操作能力实施计划

符合成熟做法的部分:

- 选择 MCP 作为工具能力接入边界，与项目现有架构一致。
- 默认只读、写操作审批、审计日志、权限管理方向正确。
- 识别 SQL 注入、危险操作、敏感数据泄露和连接泄露风险。

需要修正的部分:

- 不能把 database MCP server 直接加入全局 `config.mcp_servers`。
- 不能把官方 Postgres MCP server 当作生产实现；官方 reference servers 本身声明不是 production-ready。
- P0 必须改为 sandbox read-only proof，而不是“上线数据库能力”。
- SQL 注入防护不能只写参数化查询；LLM 生成整段 SQL 时必须做 AST / allowlist 校验。
- 审计 MySQL 依赖 Gateway 治理库，P0 应先落本地 SQLite/JSONL。
- 写操作应推迟到 Gateway、权限、审批、dry-run、diff、rollback 完成之后。

建议状态:

- 保留，但必须重写 P0/P1 边界。

推荐第一阶段:

```text
DB-P0a: sandbox read-only DB MCP
- 不进全局工具池
- feature flag 默认关闭
- 本地 sandbox DB
- 只读 DB user
- 工具仅 list_tables / describe_table / safe_select
```

```text
DB-P0b: safe SQL kernel
- SQL AST allowlist
- 单条 SELECT
- 表/列 allowlist
- 强制 LIMIT / timeout / max result size
- 脱敏
- 本地 audit
```

### 3.2 项目与成熟项目做法差距

符合成熟做法的部分:

- AIOps/RAG/Runtime 拆分合理。
- AIOps MCP cache 后补 metrics，符合工具发现缓存和可观测原则。
- RAG reranker 先 shadow/eval，符合 cross-encoder reranker 的成熟落地方式。
- Milvus 先 benchmark，不直接改参数，符合 Milvus 官方性能调参建议。
- MemorySaver 持久化按部署形态触发，符合 LangGraph persistence 方向。

需要补强的部分:

- 如果未来执行 RAG-1，应明确 `local_lexical_v1` 只是 baseline，不是成熟 reranker。
- 如果未来执行 AIOps-1，应把 MCP metrics 放进 eval/report，而不是只写日志。
- 如果未来执行 Runtime-1，应提前定义重启恢复 smoke test。

建议状态:

- 基本符合成熟项目做法，可作为执行清单。

### 3.3 Enterprise Agent Gateway V1

符合成熟做法的部分:

- 认证、RBAC、部门/资源授权、ToolGateway、ModelGateway、RequestGateway、trace/audit 的拆分合理。
- 与 Open WebUI 的 roles/permissions/groups/ACL 结构、LiteLLM 的 proxy/gateway 能力方向一致。
- 对 tools 的授权过滤和调用前阻断是必要的，尤其是数据库这类 server-side 高风险工具。
- 不强行迁移现有 memory SQLite，也符合渐进式治理落地。

需要注意的部分:

- 12 个阶段不能一次性开做，应先做最小治理骨架。
- ToolGateway 应优先支持 allowlist/filter/audit，而不是先做完整管理台。
- RequestGateway 应先覆盖 trace_id、current_user、审计壳，再逐步加限流/guardrail。
- 数据库能力的 P1 应依赖 Gateway 骨架，而不是和 Gateway 并行假设已存在。

建议状态:

- 方向符合成熟做法，但实施要拆成 Gateway-MVP。

推荐 Gateway-MVP:

```text
Gateway-MVP-1: local user/current_user + trace_id
Gateway-MVP-2: ToolGateway allowlist/filter + blocked audit
Gateway-MVP-3: RequestGateway audit shell for chat/aiops
Gateway-MVP-4: ModelGateway minimal usage/latency/fallback record
```

## 4. 综合建议

如果目标是企业级助手展示:

1. 先做 Gateway-MVP。
2. 再做 DB-P0a/P0b sandbox read-only。
3. 再做 RAG/Gateway 权限过滤。
4. 最后考虑真实企业只读 DB 和写操作。

如果目标是快速证明 Agent 能查数据库:

1. 可以先做 DB-P0a/P0b。
2. 但必须 sandbox、只读、默认关闭、不进全局工具池。
3. 不能接真实业务库。
4. 不能做写操作。

如果目标是继续项目成熟度补强:

1. 继续 AIOps: 先做 MCP metrics，再分析 replanner timeout。
2. 重开 RAG: 先做 reranker shadow/eval，再考虑 embedding cache。
3. 进入 Runtime: 先明确部署形态，再决定 MemorySaver 替换。

## 5. 最终判断

三个待办都符合成熟项目方向，但执行成熟度不同:

| 待办 | 当前判断 | 是否可直接执行 |
|---|---|---|
| 数据库操作能力 | 方向正确，但原计划过大；必须改成 sandbox read-only + safe SQL kernel 先行 | 只能执行修正版 P0a/P0b |
| 项目与成熟项目做法差距 | 已符合“按证据触发、先观测/评估”的成熟做法 | 可以作为 backlog 入口 |
| Enterprise Agent Gateway V1 | 方向符合成熟治理形态，但要先做 MVP 骨架 | 可以执行 Gateway-MVP，不应一次性全做 |

当前最稳的下一步:

```text
先修正 docs/database_operation_capability_plan.md，
把 P0 改成 sandbox read-only proof，
并明确它不进入默认 MCP tool pool。
```

## 6. 二次复核记录

日期: 2026-05-30

本次按用户要求再次搜索成熟项目和官方资料后，结论没有反转，但数据库计划需要从“能力建设计划”收紧成“高风险工具 sandbox 计划”。

新增或重点复核来源:

| 来源 | 对本项目的约束 |
|---|---|
| MCP tools specification | tools 是 model-controlled 能力；server/client 都要承担访问控制、输入校验、超时、审计和敏感操作保护 |
| OWASP MCP Security Cheat Sheet | MCP 场景本身需要 tool allowlist、least privilege、human confirmation、audit 和 data exfiltration 防护 |
| OWASP SQL Injection Prevention Cheat Sheet | SQL 防护不能只依赖 escaping；对 LLM 生成 SQL，需要 prepared statements 之外的 allowlist/结构校验 |
| LangChain SQL Agent docs | SQL agent 必须使用窄权限连接，限制查询，不做 DML，并在敏感执行前支持 human-in-the-loop |
| Microsoft Data API Builder SQL database MCP | 成熟数据库 MCP 倾向把数据以受控实体/资源暴露给 Agent，而不是裸 SQL shell |
| Open WebUI RBAC / Hardening | server-side tools/functions 需要角色、权限、组/ACL 和硬化配置；工具不应默认对普通用户开放 |
| LiteLLM Proxy docs | ModelGateway、fallback、rate limit、usage/cost logging 是成熟模型网关边界 |
| Langfuse tracing docs | trace/observation/usage 这类分层记录是成熟 LLM 应用观测边界 |

二次复核后的文件动作:

- `docs/database_operation_capability_plan.md` 已重写为修正版：DB-P0a sandbox read-only、DB-P0b safe SQL kernel、DB-P1 Gateway 集成、DB-P2 企业只读库、DB-P3 写操作审批。
- 明确禁止把 database MCP server 加入默认全局 `app/config.py::mcp_servers`。
- 明确 P0 不接真实业务库、不支持写操作、不依赖 Gateway MySQL 审计。
- `docs/项目与成熟项目做法差距.md` 暂不改动：其按 AIOps/RAG/Runtime 分线、先观测/评估再改默认值的原则仍符合成熟做法。
- `docs/superpowers/specs/2026-05-26-enterprise-agent-gateway-v1-design.md` 暂不大改：方向符合成熟项目，但执行时必须先做 Gateway-MVP，不应一次性实施完整 12 阶段。

二次复核后的建议顺序:

```text
若目标是企业级助手:
Gateway-MVP -> DB-P0a/P0b -> DB-P1 -> DB-P2 -> DB-P3

若目标只是演示 Agent 查数据库:
DB-P0a/P0b sandbox read-only
但必须默认关闭、不进全局工具池、不接真实库、不做写操作
```
