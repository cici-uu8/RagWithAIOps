# 企业助手开发统一计划

日期：2026-05-30

状态：总控计划，执行中（E0 架构基线与依赖可复现已完成）

关联文件：

- `docs/superpowers/specs/2026-05-26-enterprise-agent-gateway-v1-design.md`
- `docs/database_operation_capability_plan.md`
- `docs/项目与成熟项目做法差距.md`
- `docs/enterprise_capability_development_record.md`
- `/Users/cici/oncall agent/reference_repos/README.md`

## 1. 计划目的

本计划是企业助手方向的统一入口，解决三个问题：

1. 把 Gateway、数据库能力、成熟项目差距三个计划串成一条可执行主线。
2. 明确项目的分层架构思想：每层有清晰模块，每个模块有可替换接口，每次失败可以定位到具体层和模块。
3. 给每一步写清验收标准，避免“实现了很多东西，但不知道哪个能力真正可用”。

本计划不替代三个子计划。子计划仍负责细节：

| 子计划 | 负责内容 | 本计划中的位置 |
|---|---|---|
| Enterprise Agent Gateway V1 | 登录、权限、RequestGateway、ToolGateway、ModelGateway、审计 | L1-L4 主线 |
| 数据库操作能力实施计划 | sandbox DB、safe SQL kernel、真实只读库、写操作审批 | L5 数据库能力 |
| 项目与成熟项目做法差距 | AIOps/RAG/Runtime 成熟化 backlog | L6/L7 可观测与成熟化 |

## 2. 架构原则

### 2.1 分层

企业助手必须分层，不能让业务 Agent 直接调用所有基础设施。

目标分层：

```text
L0 Runtime / Dependency / Config
  -> L1 Identity / RequestContext
  -> L2 RequestGateway / Governance
  -> L3 Permission / Registry
  -> L4 Capability Gateways
  -> L5 Domain Capabilities
  -> L6 Observability / Eval
  -> L7 Production Readiness Backlog
  -> L8 Execution Visualization
```

每一层只依赖下层的稳定接口，不跨层直接访问具体实现。

### 2.2 模块可插拔

每层模块必须能替换实现：

| 能力 | 初始实现 | 后续替换 |
|---|---|---|
| AuthProvider | local username/password + JWT | CAS / LDAP / OIDC |
| PolicyEngine | grant table / allowlist | pycasbin / 企业权限中心 |
| ToolProvider | MCP tools + local tools | MCP gateway / 企业工具平台 |
| ModelProvider | DashScope direct client | LiteLLM / 企业 AI Gateway |
| AuditSink | local SQLite/JSONL 或 MySQL table | ELK / Langfuse / OpenTelemetry |
| StorageBackend | LocalStorageService | NAS / MinIO / S3 |
| DatabaseConnector | SQLite sandbox | MySQL / PostgreSQL / Oracle / 达梦 |
| Reranker | local lexical baseline | cross-encoder / API reranker |
| Checkpointer | MemorySaver | SQLite / Postgres checkpointer |

### 2.3 可定位问题

每个请求必须能通过 trace 判断失败位置：

```text
auth_failed              -> L1 Identity
request_blocked          -> L2 RequestGateway / Guardrail
permission_denied        -> L3 Permission
tool_not_visible         -> L4 ToolGateway
tool_execution_failed    -> L5 Tool / Domain Capability
model_fallback_used      -> L4 ModelGateway
retrieval_low_quality    -> L5 RAG
sql_blocked              -> L5 Database Safe SQL Kernel
audit_write_failed       -> L6 Observability
session_resume_failed    -> L7 Runtime Readiness
event_contract_missing   -> L6 Observability / E11 blocker
```

验收时不能只看最终回答，要能看 trace 里的 layer、module、decision、reason。涉及流式执行的接口还必须能用同一套 SSE 事件协议解释阶段、工具、内容、错误和完成状态。

### 2.4 不做过度前置重构

企业助手要形成新分层，但不要求先把旧系统整体重构。

明确不做：

- 不在 Gateway-MVP 前全量重组 `app/services/`。
- 不先抽全局 Repository 层再开始 Gateway。
- 不批量替换旧模块的模块级单例。
- 不为了“目录看起来更干净”移动旧 RAG / AIOps / Memory 代码。

原因：

- 全量搬迁会改大量 import 和测试路径，风险高。
- 这类重构未必立刻产生企业助手能力。
- 当前更稳的路径是“新企业能力走新分层，旧服务通过 adapter 包裹”。

允许做：

- 新企业能力放入 `app/enterprise/*`。
- 新治理数据使用新 repository/provider 边界。
- 新企业模块使用 container/provider 风格，避免新增模块级单例。
- 旧服务只有在 Gateway 接入点真正需要时才做局部修改。
- Adapter 在 E0-E9 期间是正式接入边界，不预设“马上删掉”或“必须永久保留”；是否收敛到后续任务，由 E9 后的厚度和验收结果决定。

### 2.5 参考优先原则

企业助手开发时，代码实现优先参考成熟项目，而不是让 AI 从零决定写法。

原则：

- 先查本地 `reference_repos/`，再写代码。
- 能从成熟项目借鉴模块边界、数据模型、测试方式、错误处理和配置组织时，优先借鉴。
- 只有在没有合适参考源，或参考源与当前技术栈 / 许可证不匹配时，才允许 AI 自主设计。
- 可复制的是“小段、明确、许可证兼容、直接贴合当前任务”的代码形态，不是整仓库搬运。
- 不复制 `ee/`、品牌受限、许可证不兼容、或与当前任务无直接对应关系的代码。
- 参考和复制都必须在 development record 里写清楚：参考了哪个仓库、哪个文件、借了什么、没借什么、为什么这么借。

通用顺序：

1. 先看 `reference_repos/README.md` 的阶段映射。
2. 再看对应仓库的实现和测试。
3. 先适配成熟形态，再写本项目实现。
4. 如果需要复制代码，只复制最小必要片段，并保留来源说明。

### 2.6 Git 阶段收口原则

Git 管理是每个 E 阶段的验收组成部分，不是额外的收尾建议。

每个 E 阶段完成前必须：

1. 确认当前分支是 `enterprise`，或明确记录为什么在短支线开发。
2. 运行该阶段要求的 targeted tests / smoke / compile / safety checks。
3. 更新 `PROJECT_STATE.md`、`progress.md`、`findings.md` 和 `docs/enterprise_capability_development_record.md`。
4. 只 stage 本阶段需要的源码、测试、配置和文档。
5. 重新检查暂存区不包含 `.env`、虚拟环境、日志、uploads、traces、volumes、DB/sqlite、zip、eval reports/probe/dump 或参考仓库。
6. 创建阶段 commit，commit message 使用 `enterprise(eX): ...` 或等价可读格式。
7. 把 commit hash 写入 `docs/enterprise_capability_development_record.md`。

如果阶段较大，可以拆多个小 commit，但阶段状态不能标为 complete，直到最后一个阶段收口 commit 存在并记录。

### 2.7 可视化事件契约先行

执行过程可视化不在主线早期重写前端，但事件契约必须在 E2-E9 期间逐步固化。

原则：

- FastAPI + SSE 是后端主线能力的一部分；Vue3 是 E11 的展示层升级，不应反向驱动后端协议大改。
- `/api/chat_stream`、`/api/aiops` 以及后续 gateway/tool/model/retrieval 事件必须收敛到同一套 envelope。
- 当前 `static/app.js` 是第一版消费者；E11 Vue3 只能消费既有协议，不在 E11 顺手调整后端业务语义。
- 如果 E9 发现事件协议不完整，不能把 E11 标为低风险前端任务，必须先补齐协议和测试。

推荐 SSE envelope：

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

允许的顶层 `type` 初始集合：

- `stage`：阶段切换或阶段状态更新。
- `tool_call`：工具可见性、调用开始、调用完成或阻断。
- `content`：模型或报告正文流。
- `error`：异常、阻断、超时或协议错误。
- `done`：请求完成，包含最终 trace 摘要。

旧字段如 `plan`、`step_complete`、`report` 可以在迁移期保留，但必须能映射到上述 envelope，不能再新增第三套事件形态。

## 3. 三个现有计划的架构审视

### 3.1 Enterprise Agent Gateway V1

判断：方向符合架构思想，但必须按 MVP 切开执行。

符合点：

- 已有身份、请求网关、权限、工具网关、模型网关、审计的分层意识。
- 强调包裹现有 RAG / AIOps / MCP 链路，而不是重写业务主链路。
- 模型、工具、存储、审计都预留了可替换边界。

不足点：

- 原设计范围大，容易一次性展开 12 个阶段。
- 需要先落最小可验证骨架，否则后续数据库和权限过滤没有可挂载点。
- 需要明确每个 Gateway 模块的输入/输出和 trace 字段，避免只是服务类堆叠。

结论：

- 可以作为治理底座设计。
- 执行顺序必须从 Gateway-MVP 开始。

### 3.2 数据库操作能力实施计划

判断：修正版符合架构思想，原始“直接注册 database MCP server”路径已被否决。

符合点：

- 已明确数据库工具是高风险能力。
- 已禁止进入全局默认 MCP tool pool。
- 已拆成 sandbox read-only、safe SQL kernel、Gateway 集成、企业只读库、写操作审批。
- 已明确 Schema Registry、脱敏、强制 LIMIT、审计。

不足点：

- DB-P0a/P0b 可以先独立做 demo，但 DB-P1 以后必须依赖 Gateway-MVP。
- `safe_select` 必须作为独立模块验收，不能藏在 MCP server handler 里。
- 审计先本地，后续接 Gateway AuditService 时要保留同一 audit event schema。

结论：

- 可以执行修正版 DB-P0a/P0b。
- 真实库和写操作必须等待治理底座。

### 3.3 项目与成熟项目做法差距

判断：符合“成熟化 backlog”定位，但它不是企业助手主实施计划。

符合点：

- AIOps、RAG、Runtime 分开，不混排。
- 每项都有触发条件，避免看到成熟项目做法就直接改默认行为。
- 强调 shadow/eval/benchmark 先行。

不足点：

- 它是成熟度补强清单，不负责企业助手主链路。
- RAG/Runtime 项只有在对应触发条件成立时才进入实施。

结论：

- 保持为 L7 backlog。
- 不作为 Gateway/DB 开发的前置阻塞项。

## 4. 目标架构

### L0 Runtime / Dependency / Config

职责：

- 依赖可复现。
- 配置入口统一。
- feature flag 默认安全。
- 本地依赖服务可启动和健康检查。

模块：

- Dependency lock：`uv.lock`
- Config：`app/config.py`
- Feature flags：新增或扩展配置项
- Preflight checks：现有 eval / smoke preflight

可插拔点：

- 依赖安装工具可以是 uv 或 pip，但锁源必须唯一。
- 外部依赖服务可以是 Docker 本地模拟或企业环境。

### L1 Identity / RequestContext

职责：

- 识别当前用户。
- 生成 request_id / trace_id。
- 把用户、部门、角色、session、request scope 传给上层。

模块：

- AuthService
- current_user dependency
- RequestContext model
- local user seed

可插拔点：

- LocalAuthProvider -> CAS/OIDC/LDAP。
- JWT 黑名单 -> 企业 session/token 服务。

### L2 RequestGateway / Governance

职责：

- 所有 chat / aiops / upload 请求进入统一网关。
- 输入 guardrail。
- 限流。
- 请求审计壳。
- 输出 guardrail。

模块：

- RequestGateway
- GuardrailService
- RateLimitService
- AuditService shell

可插拔点：

- RulesGuardrailProvider -> 企业 DLP/content safety API。
- LocalRateLimiter -> Redis / Gateway rate limiter。
- LocalAuditSink -> MySQL / ELK / Langfuse / OpenTelemetry。

### L3 Permission / Registry

职责：

- 计算用户能访问哪些文档、工具、数据库、模型。
- 维护资源注册表。
- 对权限变更做缓存失效。

模块：

- PermissionService
- GrantRepository
- ToolRegistry
- ModelEndpointRegistry
- DocumentAccessRegistry
- DatabaseSchemaRegistry

可插拔点：

- GrantTablePolicy -> pycasbin / 企业权限中心。
- Local registry -> 管理台 / 企业 CMDB。

### L4 Capability Gateways

职责：

- 把底层能力包装成受控、可审计、可替换的 gateway。
- 防止业务 Agent 直接访问高风险工具或模型。

模块：

- ToolGateway
- ModelGateway
- StorageService
- RetrievalGateway 或 retrieval permission wrapper

可插拔点：

- MCP ToolProvider -> 企业工具平台。
- DashScopeModelProvider -> LiteLLM / 企业 AI Gateway。
- LocalStorageBackend -> NAS / MinIO / S3。
- Current RetrievalService -> 权限过滤后的 enterprise retrieval。

### L5 Domain Capabilities

职责：

- 真实业务能力，但必须通过 L1-L4 治理后调用。

模块：

- RAG / Knowledge Base
- AIOps diagnosis
- Database sandbox / safe SQL
- Upload / ingestion
- Memory sidecar（保持冻结，非当前主线）

可插拔点：

- RAG reranker。
- AIOps tool source。
- Database connector。
- Parser / storage backend。

### L6 Observability / Eval

职责：

- 每层输出 trace、metrics、audit。
- 每个能力有 targeted tests 和 smoke/eval。
- 失败能定位到层和模块。

模块：

- AuditService
- TraceService
- Metrics collector
- Eval reports
- Development records

可插拔点：

- Local JSON/SQLite/MySQL -> Langfuse / ELK / Prometheus / OpenTelemetry。

### L7 Production Readiness Backlog

职责：

- 不在主链路未稳定前提前实现的成熟化工作。

模块：

- AIOps MCP metrics / replanner timeout
- RAG reranker shadow/eval
- Query embedding cache
- Milvus benchmark
- Runtime checkpointer decision

可插拔点：

- 按 `docs/项目与成熟项目做法差距.md` 的触发条件执行。

### L8 Execution Visualization

职责：

- 在后端事件协议稳定后，把执行过程展示成可检查的实时 UI。
- 只消费 L6 已固化的 trace / SSE 事件，不反向修改 L1-L5 业务语义。

模块：

- Vue3 execution dashboard
- Trace timeline
- Stage / tool / content / error / done views

可插拔点：

- 当前 `static/app.js` SSE consumer -> Vue3 / Vite 前端。
- 浏览器 smoke -> Playwright / 后续视觉回归检查。

## 5. 推荐执行顺序

```text
E0 架构基线与依赖可复现
  -> E1 Gateway-MVP: Identity + RequestContext + trace_id
  -> E2 RequestGateway + Audit shell
  -> Branch A: E3 PermissionService + Registry MVP
              -> E4 ToolGateway + ModelGateway MVP
              -> E5 RAG/Upload 权限过滤和 StorageService 边界
  -> Branch B: E6 DB-P0a/P0b sandbox read-only + safe SQL kernel
  -> E7 DB-P1 Gateway 集成
  -> E8 Admin/API 最小管理面
  -> E9 Observability/Eval 总验收
  -> E10 Runtime/RAG/AIOps 成熟化 backlog 按触发条件执行
  -> E11 Vue3 执行过程可视化升级
```

E3-E5 是治理主干分支，E6 是可并行的数据库 sandbox 分支。E6 只依赖 E0-E2，可以和 E3-E5 并行推进；E7 依赖 E3/E4，E8 依赖治理底座稳定，E9 依赖前面的正向和负向路径都能跑通。E11 只能在 E9 确认 SSE 事件协议完整可用后启动，且定位为展示层升级。

### 5.1 参考顺序

每个阶段在编码前，先查对应成熟项目：

| 阶段 | 先参考什么 | 主要用途 |
|---|---|---|
| E0 | 当前仓库 `Makefile`、`pyproject.toml`、`uv.lock`；必要时看 `full-stack-fastapi-template` 的项目脚手架 | 安装、依赖、环境可复现 |
| E1 | `fastapi-users`、`full-stack-fastapi-template` | 本地 AuthService、JWT、current_user、seed 用户 |
| E2 | `langfuse`、`open-webui` | RequestGateway、audit event、guardrail、request trace |
| E3 | `pycasbin`、`open-webui` | 权限模型、domain grant、resource allow/deny |
| E4 | `litellm`、`bifrost`、`modelcontextprotocol-python-sdk` | ToolGateway、ModelGateway、fallback、provider 形态 |
| E5 | `WeKnora`、`dify`、`full-stack-fastapi-template` | RAG/Upload 权限过滤、StorageService、文档生命周期 |
| E6 | `modelcontextprotocol-servers`、`sqlglot`、`data-api-builder` | sandbox DB、safe SQL kernel、受控查询接口 |
| E7 | `data-api-builder`、`pycasbin`、`open-webui` | DB Gateway 集成、schema registry、权限过滤、审计 |
| E8 | `full-stack-fastapi-template`、`fastapi-users`、`open-webui` | 管理 API 组织方式、最小 admin 面、资源管理 |
| E9 | `langfuse`、当前 repo 的 eval / trace 代码 | 端到端 trace、observability、验收报告 |
| E10 | `docs/项目与成熟项目做法差距.md` 的触发项对应参考源 | 触发后再定向参考，不提前展开 |
| E11 | 当前 `static/app.js`、Vue3 / Vite 文档、Playwright 验证方式 | 消费既有 SSE 协议，实现 trace / 阶段看板，不重写后端业务 |

参考规则：

- 优先看仓库里的测试、fixture、service 边界和配置入口。
- 先学结构，再学实现，再决定是否复制小段代码。
- 只要存在合适成熟实现，就先按其边界写本项目代码，不先造新抽象。
- 如果要复制，必须先确认 license 和复制范围。

### 5.2 阶段任务参考矩阵

下面是每个阶段内具体任务的默认参考源。编码前至少打开对应仓库的相关实现或测试；如果决定不采用，必须在 `docs/enterprise_capability_development_record.md` 写明原因。

| 阶段 | 任务 | 必看参考源 | 参考重点 |
|---|---|---|---|
| E0 | install / deps-check / lock policy | 当前仓库；`full-stack-fastapi-template` | Makefile、依赖锁、环境入口、README 说明形态 |
| E1 | AuthService / JWT / current_user / seed users | `fastapi-users`；`full-stack-fastapi-template` | auth routes、token 解析、依赖注入、测试组织 |
| E2 | RequestGateway / audit shell / guardrail | `langfuse`；`open-webui` | trace / observation schema、request 事件、guardrail 组织 |
| E3 | PermissionService / grants / registries / cache invalidation | `pycasbin`；`open-webui` | RBAC/domain model、deny-overrides、工具/资源授权 |
| E4 | ToolGateway / MCP tool registry / ModelGateway / fallback | `modelcontextprotocol-python-sdk`；`litellm`；`bifrost` | MCP server/client 边界、模型路由、fallback 和 provider 配置 |
| E5 | RAG permission filter / upload governance / StorageService / adapters | `WeKnora`；`dify`；当前旧 RAG/AIOps services | retrieval / artifact 边界、dataset/document lifecycle、adapter 接入点 |
| E6 | sandbox DB / database-demo provider / SafeSqlKernel / Schema Registry / audit sink / DB tests | `modelcontextprotocol-servers`；`sqlglot`；`data-api-builder` | read-only DB tool 形态、SQL AST allowlist、受控表列暴露、安全测试 |
| E7 | DB ToolGateway integration / table-column permissions / DB audit query | `data-api-builder`；`pycasbin`；`open-webui` | DB resource 权限、schema registry、审计和可见性过滤 |
| E8 | admin API / user-role-grant management / audit review | `full-stack-fastapi-template`；`fastapi-users`；`open-webui` | admin route 组织、权限保护、管理操作审计 |
| E9 | smoke / negative tests / trace completeness | `langfuse`；当前 repo eval/trace 代码 | e2e trace 字段、eval 输出、失败定位报告 |
| E10 | backlog trigger implementation | 对应触发项指定仓库 | 先验证触发条件，再选择成熟项目参考，不提前实现 |
| E11 | Vue3 execution visualizer / trace panel / SSE consumer | 当前 `static/app.js`；Vue3 / Vite；Playwright | 保持后端协议不变，组件化展示阶段、工具、内容、错误和完成状态 |

### 5.3 中间里程碑

里程碑不是额外范围，而是每个阶段分支结束时的可演示检查点。

| 里程碑 | 覆盖阶段 | 可演示内容 | 最小验收 |
|---|---|---|---|
| M1 | E0-E2 | 登录后请求通过 RequestGateway，并写审计 | 未登录返回 401；trace_id 完整；audit 有 request_started / completed / failed |
| M2 | E0-E4 | 不同用户看到不同工具和模型能力 | 权限决定可见工具；ToolGateway / ModelGateway 可观测 |
| M3 | E0-E6 | sandbox DB 安全查询 | 只有显式 demo session 可见 database tools；safe_select 受控 |
| M4 | E0-E9 | 企业助手端到端闭环 | 三条 smoke + 三条负例通过；trace 可定位到层 / 模块 |
| M5 | E11 | Vue3 执行过程看板 | 同一条 SSE trace 可在 Vue3 UI 中实时展示阶段、工具、内容、错误和完成状态 |

## 6. 分阶段计划与验收

### 阶段工作量估算

这些估算用于排期，不作为验收标准。每阶段仍以本节的验收项为准。

| 阶段 | 预计工作量 | 关键风险 |
|---|---:|---|
| E0 架构基线与依赖可复现 | 2-3 小时 | 依赖约束变更后锁文件解析冲突 |
| E1 Identity / RequestContext | 2-3 天 | JWT 黑名单、seed 用户、current_user 接入点 |
| E2 RequestGateway + Audit shell | 3-4 天 | 入口包裹范围不清、audit schema 过早膨胀 |
| E3 PermissionService + Registry MVP | 4-5 天 | 权限模型过复杂、缓存撤权不及时 |
| E4 ToolGateway + ModelGateway MVP | 5-7 天 | 工具过滤误伤、模型 fallback 行为不透明 |
| E5 RAG / Upload 权限过滤与 StorageService | 3-4 天 | RAG citation 泄露未授权 source、旧文件兼容 |
| E6 DB-P0a/P0b sandbox + safe SQL | 3-4 天 | SQL AST 校验不完整、database tool 误进默认工具池 |
| E7 DB-P1 Gateway 集成 | 2-3 天 | DB 权限和 ToolGateway 权限重复或冲突 |
| E8 Admin/API 最小管理面 | 5-7 天 | 管理 API 权限绕过、审计遗漏 |
| E9 Observability / Eval 总验收 | 2-3 天 | trace 不完整导致无法定位失败层 |
| E10 Production Readiness Backlog | 按触发项单独估算 | 没有触发条件就改默认行为 |
| E11 Vue3 执行过程可视化升级 | 3-5 天 | E9 未固化事件协议导致前后端联动大改 |

### 跨阶段要求：SSE 事件协议准备（E2-E9）

目标：让 E11 成为低风险前端展示层升级，而不是 E9 后再回头重写后端流式协议。

范围：

- E2 起，RequestGateway / audit / blocked / failed 相关流式事件必须带 `trace_id` 和 `request_id`。
- E3-E5 增加权限、工具、模型、RAG/Upload 事件时，必须使用 `type/stage/status/message/data` envelope 或提供到该 envelope 的明确映射。
- E6-E7 增加 DB sandbox / DB Gateway 事件时，必须能通过同一 `trace_id` 串联 request、tool、sql、result、blocked/error。
- E8 管理 API 如果暴露 trace/audit 查询，也要按同一事件字段返回，不创建单独 UI-only 字段体系。
- E9 必须检查 `/api/chat_stream` 和 `/api/aiops` 的事件协议一致性，并把协议文档作为验收产物。

验收：

- 有 `docs/enterprise_sse_event_contract.md` 或等价文档，列出事件 envelope、允许的 `type`、阶段枚举、错误字段和示例。
- `/api/chat_stream` 和 `/api/aiops` 都能输出或映射到同一事件 envelope。
- blocked / audit / trace / tool / model / retrieval / report / done 事件可以通过同一个 `trace_id` 串联。
- 当前 `static/app.js` 仍可作为兼容消费者，不要求 E2-E9 期间改成 Vue3。

失败定位：

- 事件缺 `trace_id` / `request_id`：L1/L2 context 或 adapter 传递。
- 事件类型不统一：L6 Observability event contract。
- 前端必须理解多个互斥协议：E11 前置条件未满足。

### E0：架构基线与依赖可复现

目标：先保证后续开发环境可复现，并冻结“分层开发规则”。

编码参考：当前仓库 `Makefile` / `pyproject.toml` / `uv.lock`，必要时参考 `full-stack-fastapi-template` 的环境入口和 README 组织方式。

范围：

- 明确 `uv.lock` 是唯一锁源。
- 修正安装命令，避免绕过锁文件。
- 给高风险依赖增加主版本上限。
- 在本计划和 record 中确认分层边界。

具体执行清单：

1. 确认 `uv.lock` 存在且可被校验。

   ```bash
   ls -lh uv.lock
   uv lock --check
   ```

   预期：`uv.lock` 存在，`uv lock --check` 不要求重写锁文件。

2. 修改 `Makefile` 安装入口，强制使用锁文件。

   当前风险形态：

   ```makefile
   install:
   	pip install -r requirements.txt 2>/dev/null || pip install -e .

   install-dev:
   	pip install -e ".[dev]" 2>/dev/null || pip install -e .
   ```

   目标形态：

   ```makefile
   install:
   	uv sync --frozen

   install-dev:
   	uv sync --frozen --all-extras
   ```

   说明：如果后续部署平台只能使用 pip，必须另开 deployment-specific 方案，不能让 `requirements.lock.txt` 和 `uv.lock` 成为两个长期锁源。

3. 给高风险依赖增加主版本上限。

   第一批优先处理：

   ```toml
   "pymilvus>=2.3.5,<3.0.0"
   "redis>=5.0.0,<8.0.0"
   "openai>=1.10.0,<3.0.0"
   ```

   LangChain / LangGraph 系列需要先按当前 `uv.lock` 的实际解析版本决定上限，不直接套用旧版本范围。执行前应读取 `uv.lock` 中当前锁定的 `langchain`、`langchain-core`、`langchain-openai`、`langgraph` 版本，再设置同一主版本或同一兼容窗口。

4. 重新解析锁文件。

   ```bash
   uv lock
   uv lock --check
   ```

   预期：`uv.lock` 更新后再次 check 通过。

5. 验证安装和依赖一致性。

   ```bash
   make clean
   make install
   make install-dev
   pip check
   python -c "import app; print('OK')"
   ```

   预期：生产安装和开发安装都成功，`pip check` 无冲突，`import app` 成功。

6. 增加依赖检查入口。

   目标形态：

   ```makefile
   deps-check:
   	uv lock --check
   	pip check
   ```

7. 同步文档。

   必须更新：

   - `PROJECT_STATE.md`：记录 `uv.lock` 是唯一锁源。
   - `task_plan.md`：记录 E0 完成状态和验证命令。
   - `progress.md` / `findings.md`：记录依赖可复现性结论。
   - `docs/enterprise_capability_development_record.md`：记录执行过程、风险和验证结果。
   - `reference_repos/README.md`：如果新增或调整参考仓库，也要同步索引。

验收：

- `uv.lock` 保持存在且作为安装基线。
- 安装命令不再默认绕过锁文件。
- `pyproject.toml` 对高风险集成依赖有主版本上限。
- `pip check` 或等价依赖一致性检查通过。
- `PROJECT_STATE.md` 记录依赖策略。

失败定位：

- 安装失败：L0 Dependency。
- 配置缺失：L0 Config。

本节验收标准：E0 只有在 `uv.lock` 可校验、安装入口不绕过锁文件、依赖一致性检查通过、`import app` 成功、状态文档同步，并完成阶段 Git 收口 commit 后才算完成。

### E1：Gateway-MVP Identity / RequestContext

目标：所有企业请求都有用户身份和 trace 上下文。

编码参考：`fastapi-users` 的 JWT / current_user 示例和测试，`full-stack-fastapi-template` 的 auth route / settings / seed 组织方式。

范围：

- 在 `app/enterprise/auth/` 增加本地 AuthService。
- 在 `app/enterprise/auth/` 增加 current_user dependency。
- 在 `app/enterprise/gateway/` 或 `app/enterprise/context.py` 增加 RequestContext model。
- seed 本地 demo 用户、部门、角色。
- 不接真实 CAS/LDAP。
- 不移动旧 RAG / AIOps 服务。

验收：

- 未登录请求访问受保护 API 返回 401。
- 登录成功返回 access token 和用户 profile。
- 受保护请求可以拿到 `user_id`、`department_id`、`roles`、`trace_id`。
- 登出后 token 黑名单生效。
- Auth 单测覆盖登录成功、密码错误、token 过期、黑名单命中。
- 不影响现有未启用 Gateway 的 RAG/AIOps 测试。

失败定位：

- token 无法解析：L1 AuthService。
- trace_id 缺失：L1 RequestContext。
- 用户角色错误：L1 seed/profile。

本节验收标准：E1 只有在本地身份、current_user、RequestContext 和 trace_id 可通过 targeted tests 证明，未启用 Gateway 的旧 RAG/AIOps 路径不回归，并完成阶段 Git 收口 commit 后才算完成。

### E2：RequestGateway + Audit Shell

目标：chat / aiops / upload 请求先经过统一请求网关，并形成最小审计事件。

编码参考：`langfuse` 的 trace / observation / event schema，`open-webui` 的 guardrail / server-side request governance 形态。

范围：

- 在 `app/enterprise/gateway/` 增加 RequestGateway。
- 在 `app/enterprise/observability/` 增加 AuditService shell。
- 通过薄 adapter 包裹 chat、aiops、upload 的入口。
- 记录 request_started / request_completed / request_failed。
- 为流式接口预留统一 SSE envelope，blocked / failed / trace 事件不得脱离后续可视化协议。
- Guardrail 先实现 no-op provider 和规则 provider。
- RateLimit 可先 no-op，但接口必须存在。
- 不把旧 API 路由和旧 service 做目录级重构。

验收：

- chat / aiops / upload 请求都有同一个 trace_id。
- 成功请求写 request audit。
- 失败请求写 failed audit，包含 error_class，不泄露敏感栈。
- no-op Guardrail 不改变原行为。
- rule Guardrail 命中时返回 blocked，并写 audit。
- targeted tests 覆盖 success / blocked / failed 三种路径。
- `/api/aiops` 和后续接入的 `/api/chat_stream` 必须能把 blocked / failed 事件映射到统一 SSE envelope。

失败定位：

- 请求未进入网关：L2 RequestGateway。
- 阻断错误：L2 GuardrailService。
- 审计缺失：L2 AuditService shell。

本节验收标准：E2 只有在 chat、aiops、upload 的 success / blocked / failed 路径都经过 RequestGateway，写出可追踪 audit，并完成阶段 Git 收口 commit 后才算完成。

### E3：PermissionService + Registry MVP

目标：权限判断从业务代码中抽离，所有资源访问都经过同一权限服务。

编码参考：`pycasbin` 的 RBAC/domain/deny-overrides 模型，`open-webui` 的角色、工具和资源治理边界。

范围：

- 在 `app/enterprise/permissions/` 增加 PermissionService。
- 在 `app/enterprise/permissions/` 增加新治理数据 repository，只覆盖企业治理表。
- 增加资源 grant model。
- 增加 ToolRegistry、DocumentAccessRegistry、ModelEndpointRegistry 的最小版本。
- 增加权限缓存和显式失效接口。
- 默认 deny，显式 allow。
- 不抽全局 Repository 层，不改造旧 SQLite/RAG/Memory 数据访问。

验收：

- 普通用户只能看到授权资源。
- 未授权文档不会出现在 retrieval 输入、标题、source ref 中。
- 未授权工具不会出现在 ToolGateway 返回列表中。
- 权限变更后缓存失效。
- deny 优先于 allow 的规则有单测。
- 权限 audit 记录 allow/deny decision 和 reason。

失败定位：

- 用户看不到应该看到的资源：L3 PermissionService / grant data。
- 用户看到不该看到的资源：L3 PermissionService / Registry。
- 缓存撤权不生效：L3 permission cache invalidation。

本节验收标准：E3 只有在默认 deny、显式 allow、deny 优先、授权可见性、未授权不可见性和撤权缓存失效都有单测或 targeted tests，并完成阶段 Git 收口 commit 后才算完成。

### E4：ToolGateway + ModelGateway MVP

目标：模型和工具不再由业务链路直接裸调用，而是通过可观测 gateway。

编码参考：`modelcontextprotocol-python-sdk` 的 MCP server/client 边界，`litellm` 的模型路由/fallback，`bifrost` 的 provider 配置形态。

范围：

- 在 `app/enterprise/tools/` 增加 ToolGateway 和 ToolRegistry。
- 在 `app/enterprise/models/` 增加 ModelGateway 和 ModelProvider。
- ToolGateway 过滤 MCP/local tools。
- ToolGateway 记录 visible / blocked / executed tool events。
- ModelGateway 封装模型 endpoint 选择、fallback、latency、usage。
- 保留现有 DashScope 调用作为默认 provider。
- 不改变 AIOps/RAG 业务语义。
- 不批量替换旧 agent 里的所有 LLM 调用；先在 Gateway 接入路径使用 ModelGateway。

验收：

- 默认工具列表仍不包含 database tools。
- 未授权工具不会绑定给 LLM。
- 授权工具调用成功时写 tool_call audit。
- 工具调用失败时写 failure event。
- ModelGateway 记录 model_name、latency_ms、status、fallback_used。
- 模型主 endpoint 失败时 fallback 生效或给出结构化失败。
- targeted tests 覆盖 tool allow、tool deny、model success、model fallback、model failure。

失败定位：

- 工具不该出现却出现：L4 ToolGateway。
- 工具执行失败：L5 tool provider 或 L4 ToolGateway execution wrapper。
- 模型调用慢/失败：L4 ModelGateway。

本节验收标准：E4 只有在工具 allow/deny、database tool 默认不可见、工具审计、模型成功/失败/fallback 和 latency/usage 记录都可验证，并完成阶段 Git 收口 commit 后才算完成。

### E5：RAG / Upload 权限过滤与 StorageService 边界

目标：企业知识库能力接入权限治理，但不重写现有 RAG。

编码参考：`WeKnora` 的 RAG / artifact / ingestion 边界，`dify` 的 dataset/document lifecycle，当前旧 `RagAgentService` / `AIOpsService` 的真实调用签名。

范围：

- retrieval 前按 PermissionService 过滤可见 KB / document。
- upload 走 RequestGateway audit。
- StorageService 抽象新上传文件和 artifact。
- 旧文件保留 legacy path fallback。
- 不做 RAG reranker 默认开启。
- 新增 adapter 包裹旧服务，例如：
  - `app/enterprise/adapters/rag_adapter.py`
  - `app/enterprise/adapters/aiops_adapter.py`
- Adapter 负责注入 RequestContext、权限结果、trace_id。
- Adapter 不搬迁 `app/services/rag_agent_service.py` / `app/services/aiops_service.py`。

验收：

- 用户检索不到未授权文档内容、标题、chunk、source ref。
- 授权文档检索和 citation 仍保持现有契约。
- 上传事件写入 trace/audit，包含 user、department、kb_id、doc_id、storage_uri。
- 新上传文件通过 StorageService 保存。
- 旧文件仍可读取。
- RAG 现有关键测试不回归。

失败定位：

- 检索质量下降：L5 RAG。
- 权限泄露：L3 PermissionService 或 L4 RetrievalGateway。
- 文件丢失：L4 StorageService / L5 upload。

本节验收标准：E5 只有在未授权文档不会进入检索内容或 citation、授权 citation 契约不变、上传审计和 StorageService 路径可验证、旧文件兼容，并完成阶段 Git 收口 commit 后才算完成。

### E6：DB-P0a/P0b Sandbox Read-only + Safe SQL Kernel

目标：在不进入默认工具池、不接真实库的前提下，证明数据库查询能力可控。

编码参考：

- sandbox DB / demo provider：先看 `modelcontextprotocol-servers` 的 database server 形态和只读边界。
- SafeSqlKernel：先看 `sqlglot` 的 AST parse、normalize、statement type 和 expression traversal 测试。
- Schema Registry / 受控资源暴露：先看 `data-api-builder` 的 database resource / table-column exposure 边界。
- audit sink：复用本项目本地 SQLite/JSONL 习惯，并参考 `langfuse` 的 trace event 字段，不引入远端观测依赖。

范围：

- 建立 sandbox DB。
- 增加 database-demo MCP server 或显式 demo tool provider。
- 增加 SafeSqlKernel。
- 增加 Schema Registry。
- 增加本地 SQLite/JSONL audit sink。
- 只允许 `list_tables`、`describe_table`、`safe_select`。

验收：

- 默认 AIOps/RAG 工具池不包含 database tools。
- 只有显式 database-demo session 能看到 database tools。
- 合法 SELECT 能返回正确结果。
- DML、DDL、多语句、未授权表、未授权列全部阻断。
- 无 LIMIT 查询被自动加安全 LIMIT 或被阻断。
- 敏感字段脱敏。
- 所有成功/阻断/失败查询都写 audit。
- DB targeted tests 覆盖安全规则。

失败定位：

- database tool 默认可见：L4 ToolGateway / L0 config。
- SQL 放行错误：L5 SafeSqlKernel。
- 表列权限错误：L3 DatabaseSchemaRegistry。
- 查询执行错误：L5 DatabaseConnector。
- audit 缺失：L6 AuditSink。

本节验收标准：E6 只有在 database tools 默认不可见、显式 demo session 才可见、合法 SELECT 可执行、危险 SQL / 未授权表列被阻断、脱敏和 audit 都通过 targeted tests，并完成阶段 Git 收口 commit 后才算完成。

### E7：DB-P1 Gateway 集成

目标：数据库能力接入企业治理底座。

编码参考：`data-api-builder` 的 database resource 边界，`pycasbin` 的表/列授权模型，`open-webui` 的 server-side tool 可见性过滤。

范围：

- database tools 通过 ToolGateway 暴露。
- database/table/column 权限走 PermissionService。
- DB audit 接入 AuditService。
- trace 串联 request、tool、sql、result。
- 仍只支持只读查询。

验收：

- 未授权用户看不到 database tools。
- 授权用户只能查授权表/列。
- DB audit 可以按 trace_id / user_id / database_id 检索。
- Gateway trace 能解释数据库查询为什么允许或阻断。
- 默认不接真实企业库。
- 写操作仍被阻断。

失败定位：

- 工具授权错误：L4 ToolGateway / L3 PermissionService。
- SQL 权限错误：L3 DatabaseSchemaRegistry。
- trace 不完整：L6 Trace/Audit。

本节验收标准：E7 只有在 database tool 通过 ToolGateway 暴露、表列权限走 PermissionService、DB audit 可按 trace/user 检索、写操作仍被阻断，并完成阶段 Git 收口 commit 后才算完成。

### E8：Admin/API 最小管理面

目标：管理员能配置和审计核心治理对象，但不做复杂前端。

编码参考：`full-stack-fastapi-template` 的 admin/API 组织，`fastapi-users` 的用户管理边界，`open-webui` 的角色/权限管理形态。

范围：

- 管理用户/部门/角色。
- 管理 resource grants。
- 管理 tool allowlist。
- 管理 model endpoints。
- 查看 audit/trace。
- 管理 database schema registry。

验收：

- admin 可以创建/禁用用户。
- admin 可以授予/撤销文档、工具、数据库权限。
- 撤权后权限缓存失效。
- admin 可以查看 trace 详情。
- 非 admin 访问管理 API 返回 403。
- 所有管理操作写 audit。

失败定位：

- 管理 API 权限错误：L3 PermissionService。
- 管理操作未生效：L3 Registry / repository。
- 审计缺失：L6 AuditService。

本节验收标准：E8 只有在 admin 能管理用户/授权/工具/模型/DB registry，非 admin 被 403 阻断，撤权立即生效，所有管理操作写 audit，并完成阶段 Git 收口 commit 后才算完成。

### E9：Observability / Eval 总验收

目标：企业助手核心链路可以通过自动化检查证明可用，并能定位失败层。

编码参考：`langfuse` 的 trace / observation 字段，当前 repo 的 eval scripts、trace 写入和 report 组织方式。

范围：

- 端到端 smoke：login -> chat -> retrieval -> response。
- 端到端 smoke：login -> aiops -> tool call -> report。
- 端到端 smoke：login -> database-demo -> safe_select。
- 权限泄露负例。
- 工具阻断负例。
- 模型 fallback 负例。
- trace completeness check。
- SSE event contract completeness check。

验收：

- 三条正向 smoke 全通过。
- 未授权文档、未授权工具、危险 SQL 三类负例全部阻断。
- 每个 smoke 都生成完整 trace。
- trace 至少包含 layer、module、decision、reason、latency_ms、status。
- `/api/chat_stream` 和 `/api/aiops` 的事件协议已固化并有文档，Vue3 可作为纯消费者接入。
- `compileall` 通过。
- 相关 targeted tests 通过。
- 文档和 development record 同步。

失败定位：

- smoke 正向失败：按 trace 定位到 L1-L5。
- 负例未阻断：L2/L3/L4/L5 安全边界。
- trace 缺字段：L6 Observability。
- SSE 协议缺字段或多套互斥事件格式：L6 Event Contract，阻塞 E11。

本节验收标准：E9 只有在三条正向 smoke、三条安全负例、trace completeness、SSE event contract completeness、`compileall` 和相关 targeted tests 全部通过，同步文档，并完成阶段 Git 收口 commit 后才算完成。

### E10：Production Readiness Backlog

目标：只在触发条件成立时进入成熟化补强，不抢主线。

编码参考：先用 `docs/项目与成熟项目做法差距.md` 判断触发项，再按触发项选择对应成熟仓库；未触发时不预先写代码。

范围：

- AIOps MCP metrics。
- Replanner timeout analysis。
- RAG reranker shadow/eval。
- Query embedding cache。
- Milvus benchmark。
- Runtime checkpointer。

验收：

- 每项执行前能指出触发条件。
- 每项先有 shadow/eval/benchmark 或 sample-level diff。
- 默认行为改变必须有不回归证据。
- 完成后同步对应 record。

失败定位：

- 诊断链路问题：AIOps backlog。
- 检索质量问题：RAG backlog。
- 部署恢复问题：Runtime backlog。

本节验收标准：E10 只有在每个 backlog 项都有明确触发条件、前置 shadow/eval/benchmark 或 sample-level diff、不回归证据、对应 development record，并完成阶段 Git 收口 commit 后才算完成。

### E11：Vue3 执行过程可视化升级

目标：把当前静态前端的流式渲染升级为 Vue3 执行过程看板，只消费 E2-E9 已固化的 SSE 事件协议。

编码参考：当前 `static/app.js` 的 SSE 消费逻辑、Vue3 / Vite 官方形态、Playwright 本地 UI 验证方式。E11 不参考后端网关实现来重新定义协议。

前置条件：

- E9 已完成 SSE event contract completeness check。
- `/api/chat_stream` 和 `/api/aiops` 都遵守同一事件 envelope，或有明确兼容映射。
- `trace_id` 可以串联 audit / gateway / permission / tool / model / retrieval / report / done 事件。
- 协议文档已存在，且 E11 不需要新增后端字段才能展示核心流程。

范围：

- 新增 Vue3 前端工程或在现有静态入口旁并行挂载 Vue3 UI。
- 实现实时 trace 面板：阶段状态、工具调用、内容流、错误、完成摘要。
- 实现基础历史/详情查看：按 `trace_id` 展开同一次请求的关键事件。
- 保持当前静态前端可回退，直到 Vue3 smoke 通过。
- 不修改后端业务逻辑，不改变 SSE 事件语义，不顺手重写 RequestGateway / ToolGateway / AIOps 流程。

验收：

- Vue3 UI 能消费 `/api/chat_stream` 和 `/api/aiops` 的既有 SSE 事件。
- 同一条 trace 的 stage / tool_call / content / error / done 能实时显示。
- blocked、error、done 三类终态都有明确 UI 状态。
- Playwright 或等价浏览器 smoke 覆盖 chat_stream 和 aiops 两条流式路径。
- 后端协议文件无 E11 期间的语义性变更；如必须变更，退回 E9/E10 补协议，不把 E11 标为纯前端完成。

失败定位：

- UI 收不到事件：E11 SSE consumer 或路由挂载。
- UI 必须猜测字段：E9 event contract 不完整。
- 后端为 UI 临时新增业务语义字段：E11 范围失控。

本节验收标准：E11 只有在 Vue3 UI 作为既有 SSE 协议的纯消费者通过 chat_stream / aiops 浏览器 smoke，且没有后端协议语义性变更，并完成阶段 Git 收口 commit 后才算完成。

### 6.2 开发风险与缓解

| 风险 | 主要阶段 | 缓解 |
|---|---|---|
| 权限模型设计错误 | E3 | 先做 design review；参考 `pycasbin` / `open-webui`；准备 10-20 个权限场景单测；保持 policy engine 可替换 |
| RequestContext 在异步链路中丢失 | E1-E9 | 使用 `contextvars`；异步任务显式传 `trace_id`；每个 Gateway 做上下文完整性测试 |
| E11 才发现事件协议不统一 | Vue3 升级变成前后端大改 | E2-E9 固化 SSE envelope；E9 增加 event contract completeness check；E11 禁止顺手改后端语义 |
| 权限缓存或工具过滤性能问题 | E3-E4 | 设 TTL + 显式失效；把命中率和查询延迟纳入 smoke / benchmark |
| MySQL 治理库和现有 SQLite 边界混淆 | E3 / E7 | MySQL 只承载治理数据；旧 SQLite 继续服务现有业务；不做全量迁移 |
| Adapter 接口不匹配 | E5 | 先读旧 service 签名；必要时只加最小可选参数；不为示例重写旧服务 |
| SQL parser 选型错误 | E6 | 先用 sample corpus 评估 `sqlglot` / `sqlparse`；parser 保持可替换；校验失败默认拒绝 |

### 6.3 长期运行问题与解决方案

| 问题 | 风险 | 处理 |
|---|---|---|
| 权限缓存撤权不及时 | 越权访问 | 撤权必须主动失效缓存；敏感资源可禁用缓存；失效失败时 admin 操作返回失败 |
| 关键 audit 写入失败 | 无法追溯 | 关键 audit 失败必须阻断请求；非关键 audit 可 best-effort；必要时可从 trace 补偿 |
| ModelGateway 并发计数漂移 | 过载或全拒绝 | 缩短 TTL；增加后台清理和告警；必要时换更稳的计数结构 |
| ToolRegistry 不同步 | 新工具不可见 | 优先 `tools/list_changed`；否则定期同步 + 告警 |
| Schema Registry 过时 | 新表不可见 | 新表默认不可见，管理员审核后开放；必要时加自动发现 |
| 异步 trace_id 丢失 | 审计链路断裂 | `contextvars` + 任务参数双保险，异步任务启动时显式传递 |

## 7. 模块边界建议

后续实现时不要继续把所有新能力堆到 `app/services` 根目录。建议新增企业能力包，逐步形成清晰边界，不迁移旧代码。

建议结构：

```text
app/enterprise/
  context.py
  ports.py
  container.py
  auth/
  gateway/
  permissions/
  tools/
  models/
  storage/
  database/
  observability/
  adapters/
```

约束：

- 新企业能力优先放入 `app/enterprise/*`。
- 旧 RAG / AIOps 服务先不搬家。
- 通过 adapter 包裹旧服务，不直接重写旧链路。
- 如果必须修改旧服务，只改接入点，不做目录级重构。
- 新企业模块可以使用 `container.py` 或 provider 工厂管理依赖；旧模块级单例不批量替换。
- 新治理数据可以有 repository；旧 RAG / AIOps / Memory 存储访问不做全局 repository 改造。

### 7.1 旧服务重构触发条件

旧 `app/services` 只在触发条件成立时局部整理。

触发条件：

- 出现 import 循环依赖。
- 单元测试因为全局单例或目录耦合难以编写。
- 多人协作频繁冲突在同一服务目录或同一大文件。
- 新人 onboarding 明确卡在服务定位上。
- 某个旧服务被 Gateway adapter 接入后，边界不清导致功能无法验收。

不触发：

- 只是目录看起来不够整齐。
- 旧服务运行稳定。
- 没有正在接入 Gateway 的调用点。
- 没有测试或协作证据表明当前结构阻碍开发。

### 7.2 不同目标下的架构处理

| 当前目标 | 立即做 | 暂缓 |
|---|---|---|
| 继续 AIOps/RAG 质量优化 | E0 依赖可复现性 | Gateway 新分层、旧服务重组、Repository 抽象 |
| 准备做 Gateway V1 | E0，随后 E1-E4 新企业分层 | 旧 `app/services` 全量重组、旧模块单例批量替换 |
| 快速展示数据库能力 | E0，随后 DB-P0a/P0b sandbox | DB-P1 真实 Gateway 集成、真实库、写操作、旧服务重组 |
| 进入真实企业助手 | E0-E9 按顺序推进 | L7 backlog 中未触发的成熟化优化 |

### 7.3 Adapter 模式示例

Adapter 的职责是把企业上下文注入旧服务调用，不负责搬迁旧服务，也不负责把旧服务改造成企业模块。

示例形态：

```python
# app/enterprise/adapters/rag_adapter.py

from dataclasses import dataclass
from typing import Any, Sequence

from app.enterprise.context import RequestContext
from app.services.rag_agent_service import RagAgentService


@dataclass(frozen=True)
class EnterpriseChatRequest:
    query: str
    session_id: str | None = None


@dataclass(frozen=True)
class EnterpriseChatResponse:
    answer: str
    raw_response: Any


class RagAdapter:
    """Wrap legacy RAG service with enterprise context."""

    def __init__(self, rag_service: RagAgentService) -> None:
        self._rag_service = rag_service

    async def chat(
        self,
        request: EnterpriseChatRequest,
        context: RequestContext,
    ) -> EnterpriseChatResponse:
        allowed_document_ids: Sequence[str] = (
            await context.permission_service.get_allowed_document_ids(
                user_id=context.user_id,
                department_id=context.department_id,
            )
        )

        allowed_tools = await context.tool_gateway.get_allowed_tools(
            user_id=context.user_id,
            department_id=context.department_id,
        )

        await context.audit_service.log_event(
            trace_id=context.trace_id,
            user_id=context.user_id,
            event_type="rag_chat_started",
            payload={
                "allowed_document_count": len(allowed_document_ids),
                "allowed_tool_count": len(allowed_tools),
            },
        )

        raw_response = await self._rag_service.chat(
            query=request.query,
            session_id=request.session_id,
            allowed_document_ids=list(allowed_document_ids),
            allowed_tools=allowed_tools,
            trace_id=context.trace_id,
        )

        await context.audit_service.log_event(
            trace_id=context.trace_id,
            user_id=context.user_id,
            event_type="rag_chat_completed",
            payload={
                "status": "success",
            },
        )

        return EnterpriseChatResponse(
            answer=getattr(raw_response, "answer", str(raw_response)),
            raw_response=raw_response,
        )
```

实现时允许根据旧 `RagAgentService` 的真实方法签名调整参数，但必须保持这个边界：

- Adapter 接收 `RequestContext`。
- Adapter 调用 `PermissionService` / `ToolGateway` / `AuditService`。
- Adapter 调用旧服务。
- 旧服务不反向依赖 `app/enterprise/*`。
- 如果旧服务暂时不支持 `allowed_document_ids` 或 `trace_id`，先在 adapter 层记录缺口，不为了示例一次性重写旧服务。
- Adapter 是 MVP 阶段的正式边界；如果 E9 后发现它变厚、隐藏业务逻辑或阻碍验收，再单独开收敛任务处理，不在没有证据时提前重写旧服务。

## 8. 验收总表

| 阶段 | 最小验收 | 不允许通过的情况 |
|---|---|---|
| E0 | 锁文件和安装路径一致 | 仍绕过锁文件安装 |
| E1 | current_user + trace_id 可用 | 受保护 API 无身份也可访问 |
| E2 | 请求统一写 audit | chat/aiops/upload 绕过 RequestGateway |
| E3 | 默认 deny 权限生效 | 未授权资源可见 |
| E4 | Tool/Model Gateway 可观测 | 未授权工具绑定给 LLM |
| E5 | RAG 权限过滤不泄露 source | 未授权文档出现在 citation |
| E6 | sandbox DB 安全查询可用 | DB tool 默认进入全局工具池 |
| E7 | DB 接入 Gateway 权限和审计 | 真实库绕过 ToolGateway |
| E8 | admin API 可管理权限并审计 | 非 admin 可改授权 |
| E9 | 三条 e2e smoke + 三条负例通过；SSE event contract 完整 | trace 无法定位失败层；事件协议不能支撑 E11 |
| E10 | backlog 按触发条件执行 | 因“成熟项目都这么做”直接改默认 |
| E11 | Vue3 作为既有 SSE 协议消费者展示执行过程 | 为了 UI 临时重写后端协议或业务流程 |
| 结构治理 | 新企业能力有独立边界 | 为了目录整齐而批量搬迁旧服务 |

## 9. 当前推荐下一步

当前最合理的下一步是 E0，然后 E1。

原因：

- E0 解决依赖和配置可复现，是后续开发的地基。
- E1 产出 `current_user` 和 `trace_id`，是 RequestGateway、ToolGateway、PermissionService、DB-P1 的共同前置。
- 直接做数据库真实能力或完整管理台都会绕过治理底座。

不建议现在做：

- 不直接接真实数据库。
- 不把 database MCP server 加入默认 `config.mcp_servers`。
- 不一次性实现完整 Gateway V1。
- 不现在重写 Vue3 前端；只在 E2-E9 固化后端事件契约，为 E11 做准备。
- 不为了成熟化去重构全部 `app/services`。
- 不先做全局 Repository 抽象。
- 不批量替换旧模块级单例。
- 不在没有触发条件时开启 RAG reranker、embedding cache 或 Runtime checkpointer。

## 10. 文档同步规则

每完成一个阶段，必须同步：

- `docs/enterprise_capability_development_record.md`
- `PROJECT_STATE.md`
- `task_plan.md`
- `progress.md`
- `findings.md`

如果阶段涉及 RAG：

- 同步 `docs/rag_fusion_development_record.md`

如果阶段涉及 AIOps：

- 同步 `docs/aiops_mainline_development_record.md`

如果阶段涉及 Memory：

- 只有用户明确重开 Memory 时才同步 `docs/memory_fusion_development_record.md`。
