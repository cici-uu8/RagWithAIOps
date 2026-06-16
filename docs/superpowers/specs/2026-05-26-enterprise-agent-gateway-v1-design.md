# 企业级 Agent Gateway V1 设计

日期：2026-05-26

项目：SuperBizAgent（`super_biz_agent_py-release-2026-03-21`）

状态：待用户审阅的设计稿

## 0. 企业使用架构与本项目本地架构对比

本项目 V1 的目标不是把公司真实基础设施全部接进来，而是在本地把企业 Agent 平台最关键的治理链路跑通。真实企业架构负责生产级统一接入、统一认证、统一监控和统一安全；本项目架构负责在 Python 项目内复现这些边界，让 demo 能清楚展示“谁能访问什么、请求怎么被治理、模型怎么被路由、工具怎么被授权、审计怎么追踪”。

### 0.1 企业常见使用架构

```text
企业用户浏览器
  -> 企业门户 / CAS / LDAP
  -> Nginx / Spring Cloud Gateway
  -> 业务系统 API
  -> 企业 DLP / 内容安全服务
  -> 企业 AI Gateway / 统一 AI 平台
  -> MCP / 内部工具平台
  -> 知识库 / NAS / SharePoint / 对象存储
  -> ELK / Prometheus / Grafana / SkyWalking
```

### 0.2 本项目 V1 本地架构

```text
本地浏览器
  -> FastAPI 登录 / JWT
  -> Python RequestGateway
  -> GuardrailService / PermissionService
  -> ModelGateway / ToolGateway / StorageService
  -> MySQL / Redis / Milvus / 本地 uploads-artifacts
  -> 本地 admin 控制台 / trace-audit 页面
```

### 0.3 对比表

| 能力层 | 企业真实架构 | 本项目 V1 本地架构 | V1 设计目的 |
|---|---|---|---|
| 身份认证 | CAS / LDAP / 统一身份认证 | 本地账号、密码哈希、JWT、`auth_provider = local_cas_mock` | 模拟企业登录后的用户身份、部门、角色 |
| 业务网关 | Nginx + Spring Cloud Gateway | FastAPI 内部 `RequestGateway` | 统一包裹 `chat`、`chat_stream`、`aiops`、`upload` |
| 权限模型 | RBAC + 部门/岗位数据权限 | `user` / `dept_admin` / `admin` + 部门 + KB/文档/工具授权 | 本地展示企业权限治理 |
| 关系数据库 | MySQL / Oracle / 达梦等 | Docker MySQL 8.0 作为治理数据库 | 存用户、部门、权限、trace、audit、usage |
| 运行时状态 | Redis / 分布式限流组件 | Redis：限流、JWT 黑名单、模型并发计数、轻量运行时状态 | 模拟并发、吊销、限流等企业运行时能力 |
| 模型入口 | 公司统一 AI 平台 / AI Gateway | `ModelGateway` | 支持 endpoint 配置、权重、fallback、usage、成本 |
| 工具入口 | 内部工具平台 / MCP Gateway | `ToolGateway` | 只暴露授权工具，并阻断未授权调用 |
| 内容安全 | DLP / 敏感词审核接口 | 规则型 `GuardrailService` | 后台配置关键词/正则，执行 block/warn |
| 文件存储 | NAS / SharePoint / 对象存储 | `LocalStorageService` + storage URI | 本地模拟 NAS/对象存储，保留未来替换口 |
| 知识检索 | 企业知识库 / 向量库 | 现有 RAG + Milvus + 权限过滤 | 保留现有检索能力，增加可见范围控制 |
| 可观测 | ELK / Prometheus / Grafana / SkyWalking | MySQL trace/audit 表 + 结构化日志字段 | 本地可查 trace，未来可导出到企业平台 |
| 部署 | K8s / PaaS / 内网环境 | 本地 Python 服务 + Docker Compose 依赖服务 | 保持本地可演示，同时贴近企业技术栈 |

因此，V1 的判断标准不是“是否已经接入真实企业平台”，而是“本地是否已经能展示企业 Agent 请求治理能力”。真实 CAS、真实 Spring Cloud Gateway、真实 DLP、真实 NAS、真实 ELK/SkyWalking 都属于后续集成工程。

## 1. 目标

本设计的目标，是把 SuperBizAgent 从一个本地 RAG / AIOps Agent Demo，升级成一个“本地可运行的企业级 Agent 平台基础版”。

这里的重点不是现在就接入真实企业基础设施，而是在本地复现企业智能 Agent 平台最关键的治理能力：

- 用户登录后才能使用系统；
- 部门、角色、文档可见范围、工具权限会影响 Agent 能做什么；
- Chat、AIOps、Upload 请求统一经过业务网关；
- 模型调用统一经过内部模型网关，支持多 endpoint、并发控制、fallback 和 usage 记录；
- 内容安全规则可以对风险输入/输出执行阻断或告警；
- 管理员可以在控制台查看用户、文档、模型、工具、Guardrail、trace 和审计记录。

V1 实现必须尽量保留现有 RAG、AIOps、MCP、文档入库、memory shadow 等能力。改造方式应该是“包裹和治理现有链路”，而不是重写现有业务链路。

## 2. 参考对齐

### 2.1 与原始流程图的对应关系

用户最初给出的流程图表达的是一次企业 AI 请求的完整旅程：

```text
业务用户
  -> Portal
  -> APIs / 流量治理
  -> Guardrails
  -> AI Gateway
  -> MCP Gateway
  -> AIO 全链路可观测
  -> 响应结果
```

V1 在本项目中的对应关系如下：

| 原始流程图阶段 | V1 设计对应 |
|---|---|
| 业务用户 | 本地登录用户，带部门和角色 |
| Portal | `/login`、`/app`、`/admin/*` 页面 |
| APIs | 现有 `chat`、`chat_stream`、`aiops`、`upload` 接口 |
| API 流量治理 | `RequestGateway`：身份、限流、审计、请求 trace |
| Guardrails | 规则型 `GuardrailService`：关键词/正则，支持 `block` 和 `warn` |
| AI Gateway | `ModelGateway`：模型 endpoint、权重、并发上限、fallback、usage 记录 |
| MCP Gateway | `ToolGateway`：工具注册、部门/用户授权、未授权调用阻断 |
| AIO 全链路可观测 | gateway trace、model usage、tool call、guardrail event、upload audit |
| Console | 用户、文档、trace、工具、模型、Guardrail 管理页面 |

### 2.2 与成熟项目/产品的对应关系

V1 不是照抄某一个成熟系统，而是参考成熟系统的边界设计，再裁剪到当前 Python 项目里。

| 参考对象 | V1 借鉴的部分 | V1 不复制的部分 |
|---|---|---|
| Dify | 企业 Agent 平台形态：应用、Agent/Workflow、知识库、工具、模型供应商、日志运营 | 完整平台重写、插件市场、完整工作流搭建器 |
| LiteLLM Proxy | 模型网关思想：endpoint 路由、fallback、usage 统计、provider 抽象 | V1 不部署外部 LiteLLM Proxy |
| Kong AI Gateway | 企业网关治理形态：请求治理、Guardrail、观测、插件式策略边界 | V1 不部署 Kong，也不开发 Kong 插件 |
| Apereo CAS | 企业 SSO 形态：统一登录后把用户身份交给业务系统 | V1 不接真实 CAS Server / CAS Client |
| 用户调研到的企业技术栈 | MySQL、Redis、网关、DLP 类内容审核、trace/audit、NAS/对象存储形态 | V1 不接真实公司 CAS、LDAP、Spring Cloud Gateway、DLP、NAS、ELK、Prometheus、SkyWalking |

### 2.3 代码复用原则

实现时应优先复用成熟项目设计和本项目已有代码，不要重新发明已经成熟的东西。

复用包括：

- 研究 Dify / LiteLLM / Apereo CAS / Kong 或类似网关项目的模块边界、数据结构和运行方式；
- 优先复用本项目现有服务，例如 RAG、AIOps、MCP、文档解析、retrieval artifact；
- 如果复制成熟项目的小段代码，必须先确认 license 兼容，并记录来源、license 和复制原因；
- 不把大型无关子系统直接搬进本仓库；
- 不引入第二套 RAG 链路、第二套 MCP 栈、第二套文档入库约定。

直接复制代码不是 V1 的硬性要求。V1 更重要的是复用成熟设计边界和已有项目能力。

### 2.4 成熟开源项目代码复用清单

本轮已把候选成熟项目 clone 到本地独立目录，供后续实现时阅读、少量复制或参考：

```text
/Users/cici/oncall agent/reference_repos/litellm
/Users/cici/oncall agent/reference_repos/fastapi-users
/Users/cici/oncall agent/reference_repos/pycasbin
/Users/cici/oncall agent/reference_repos/langfuse
/Users/cici/oncall agent/reference_repos/dify
/Users/cici/oncall agent/reference_repos/open-webui
/Users/cici/oncall agent/reference_repos/bifrost
```

复用分级：

| 级别 | 含义 |
|---|---|
| 可复制 | license 允许，且技术栈/代码粒度适合；复制时必须保留来源说明和必要 copyright/license 记录 |
| 可参考 | 参考数据模型、边界、流程、测试思路；不直接复制实现代码 |
| 不采用 | 与 V1 技术栈或范围不匹配，不进入主线 |

#### 2.4.1 功能到参考仓库映射

| 本项目功能 | 主要参考/复制对象 | 本地参考文件 | 复用方式 | 说明 |
|---|---|---|---|---|
| ModelGateway：模型路由、fallback、max fallback、timeout、并发策略、成本/usage | LiteLLM | `reference_repos/litellm/litellm/router.py`、`reference_repos/litellm/litellm/router_strategy/*`、`reference_repos/litellm/model_prices_and_context_window.json`、`reference_repos/litellm/tests/local_testing/test_router_with_fallbacks.py`、`reference_repos/litellm/tests/local_testing/test_router_max_parallel_requests.py` | 可复制 OSS 非 enterprise 目录的小段算法；主要参考 | LiteLLM 是 Python 模型网关，和本项目技术栈最贴近。V1 的 `max_fallbacks`、endpoint fallback、weighted route、usage/cost 字段优先按 LiteLLM 的设计裁剪实现。不要复制 `enterprise/` 目录代码。 |
| 本地登录、JWT、current user、SQLAlchemy 用户模型 | FastAPI Users | `reference_repos/fastapi-users/examples/sqlalchemy/app/users.py`、`reference_repos/fastapi-users/fastapi_users/authentication/strategy/jwt.py`、`reference_repos/fastapi-users/docs/configuration/authentication/strategies/redis.md` | 可复制示例结构；优先直接参考/依赖 | FastAPI Users 的 SQLAlchemy + Bearer + JWT 示例可作为 `auth_service.py`、`current_user` dependency、登录/登出路由的模板。JWT 本身不能服务端吊销，因此 V1 在其基础上增加 Redis token blacklist。 |
| 权限模型：RBAC、部门域、deny override、后续复杂策略 | pycasbin | `reference_repos/pycasbin/examples/rbac_with_domains_model.conf`、`reference_repos/pycasbin/examples/rbac_with_deny_model.conf`、`reference_repos/pycasbin/README.md` | 可复制策略配置；可作为依赖 | V1 先用 MySQL grant 表显式实现 KB/文档/工具权限。如果权限规则继续膨胀，可引入 pycasbin，把部门视为 domain，把 user/role/resource/action 映射为统一策略。 |
| Trace/Observation：trace、span、tool、retriever、guardrail、usage/cost 字段 | Langfuse | `reference_repos/langfuse/packages/shared/src/domain/traces.ts`、`reference_repos/langfuse/packages/shared/src/domain/observations.ts`、`reference_repos/langfuse/worker/src/services/IngestionService/index.ts` | 可参考；非 EE 部分可少量复制思路，不复制 TypeScript 实现 | Langfuse 的 trace/observation 分层非常适合本项目的 `gateway_traces`、`tool_call_records`、`guardrail_events`、`model_usage_records`。V1 只参考字段结构和 usage/cost enrichment 思路。不要复制 `ee/`、`web/src/ee/`、`worker/src/ee/`。 |
| 知识库/文档生命周期、dataset/document/segment/status、tenant/role 形态 | Dify | `reference_repos/dify/api/models/dataset.py`、`reference_repos/dify/api/models/account.py`、`reference_repos/dify/api/models/provider.py`、`reference_repos/dify/api/services/dataset_service.py` | 只参考，不复制代码 | Dify 的 license 有附加限制。V1 只参考 dataset/document/segment 的生命周期字段、workspace/tenant/role 思路、provider 配置思路，不直接复制代码。 |
| 工具/资源授权表、用户/组/资源 grant 模型、管理台权限形态 | Open WebUI | `reference_repos/open-webui/backend/open_webui/models/access_grants.py`、`reference_repos/open-webui/backend/open_webui/models/tools.py`、`reference_repos/open-webui/backend/open_webui/models/groups.py`、`reference_repos/open-webui/backend/open_webui/models/users.py` | 只参考，不复制代码 | Open WebUI 的 license 对品牌有附加限制。V1 可参考 `resource_type/resource_id/principal_type/principal_id/permission` 这种扁平 grant 模型，但实现为本项目自己的 MySQL 表。 |
| MCP 工具网关、virtual key、provider configs、routing rules、工具 allowlist | Bifrost | `reference_repos/bifrost/examples/configs/withpostgresmcpclientsinconfig/config.json`、`reference_repos/bifrost/examples/configs/withvirtualkeys/config.json`、`reference_repos/bifrost/examples/configs/withroutingrules/config.json` | 可参考；配置结构可少量借鉴 | Bifrost 是 Go 项目，代码不直接搬到 Python。V1 参考它的 virtual key / provider_configs / mcp_configs / tools_to_execute / routing_rules 形态，用于完善 `ToolGateway` 和 `ModelGateway` 的配置模型。 |

#### 2.4.2 License 边界

| 仓库 | 当前 license 判断 | V1 处理方式 |
|---|---|---|
| LiteLLM | 根 license 表示非 `enterprise/` 目录为 MIT，`enterprise/` 目录另有 license | 允许复制非 enterprise 目录小段代码或测试思路；复制时记录文件来源 |
| FastAPI Users | MIT | 允许复制官方 example 结构；也可作为依赖使用 |
| pycasbin | Apache-2.0 | 允许复制策略配置或引入依赖 |
| Langfuse | 非 EE 部分 MIT，`ee/`、`web/src/ee/`、`worker/src/ee/` 另有 license | 只参考 OSS 域模型；不复制 EE 目录 |
| Bifrost | Apache-2.0 | 允许参考配置模型；Go 实现不直接复制 |
| Dify | 修改版 Apache-2.0，带多租户和前端品牌等附加条件 | 只参考架构和数据模型，不复制代码 |
| Open WebUI | 自定义 license，带品牌限制 | 只参考 grant/管理台形态，不复制代码 |

#### 2.4.3 实施时的强制规则

- 后续写 `ModelGateway` 前，先阅读 LiteLLM `router.py` 和相关 router tests，再实现本项目裁剪版；
- 后续写 `AuthService` 前，先阅读 FastAPI Users SQLAlchemy + JWT 示例，再实现本项目本地账号/JWT/Redis 黑名单；
- 后续写 `PermissionService` 前，先确认显式 MySQL grant 表是否足够；如果规则过多，再引入 pycasbin，不要自己写复杂策略引擎；
- 后续写 `ToolGateway` 前，参考 Open WebUI 的 access grant 表形态和 Bifrost 的 MCP `tools_to_execute` 配置形态；
- 后续写 `AuditService` / trace 表前，参考 Langfuse 的 trace/observation/usage/cost 字段，不照搬其 ClickHouse/worker 架构；
- Dify 和 Open WebUI 只作为架构参考，不允许直接复制代码到本项目；
- 所有复制来的非本项目代码，都要在实现记录中写明仓库、文件、license、复制/改写范围。

## 3. V1 范围

### 3.1 V1 包含内容

V1 包含：

- 本地账号系统：用户名/密码 + JWT；
- MySQL 作为主要治理数据存储，推荐用 Docker MySQL 8.0 本地启动；
- Redis 用于限流、JWT 黑名单、模型 endpoint 并发计数、轻量运行时状态；
- 5 个 seed 部门：`dept_1` 到 `dept_5`；
- 3 类角色：`user`、`dept_admin`、`admin`；
- 登录页、普通用户应用页、基础管理员页面；
- `RequestGateway` 包裹 `chat`、`chat_stream`、`aiops`、`upload`；
- 部门/用户级文档权限；
- 文档级密级和可见范围；
- 部门管理员/系统管理员上传正式知识库文件；
- `StorageService` 抽象和本地文件系统实现；
- `ToolGateway` 管理 MCP 工具授权并阻断未授权调用；
- `ModelGateway` 支持多 endpoint、权重选择、并发上限、fallback、latency 和 usage 记录；
- 输入/输出规则型 Guardrail；
- gateway trace 和 audit 记录；
- 管理员 trace 检索。

### 3.2 V1 后续可能补充内容

V1 后续可能继续做：

- 真实 CAS / LDAP 接入；
- refresh token 机制；
- 真实企业统一权限平台同步；
- 外部 Nginx + Spring Cloud Gateway 接入；
- 真实 DLP / 敏感词审核接口接入；
- 真实公司统一 AI 平台接入；
- MinIO / 对象存储 PoC；
- NAS 存储后端；
- Vue + Element Plus 管理端；
- ModelGateway circuit breaker / endpoint 健康探测；
- 权限计算缓存和权限变更主动失效；
- MCP 工具定时同步和差异告警；
- MySQL trace 分区表或归档到对象存储；
- Prometheus metrics endpoint；
- ELK 日志投递；
- SkyWalking / OpenTelemetry 链路追踪；
- 无权限命中聚合和文档开放建议；
- 文档访问审批流；
- 临时授权 / 授权过期；
- 用户组；
- 复杂组织树；
- K8s 或公司 PaaS 部署。

### 3.3 V1 不做内容

V1 不做：

- 把 FastAPI 改成 Java Spring Boot；
- 运行真实 Spring Cloud Gateway；
- 运行真实 CAS Server；
- 实现完整 SSO；
- 允许普通用户上传正式知识库文件；
- 自动推荐哪些文件应该开放；
- 生产级跨集群限流、熔断和多机房治理；
- 生产级 MySQL 分区/归档平台；
- 真实接入公司内部系统。

## 4. 企业技术栈模拟边界

V1 要在本地模拟企业基础设施的行为，但通过可替换 adapter 保持边界清楚。

| 企业概念 | V1 本地模拟 | 后续真实替换 |
|---|---|---|
| CAS / LDAP | 本地账号登录 + JWT；用户 profile 包含 `auth_provider = local_cas_mock` | 真实 CAS Client 校验 ticket 并映射用户属性 |
| Spring Cloud Gateway | FastAPI 内部的 Python `RequestGateway` | Python 服务外部接 Nginx + Spring Cloud Gateway |
| MySQL / 关系型数据库 | Docker MySQL 8.0 存治理数据 | 企业 MySQL 集群、Oracle、达梦或 RDS |
| Redis | 本地 Redis 存限流、JWT 黑名单、并发计数等运行时状态 | 企业 Redis 集群 |
| NAS / 对象存储 | `LocalStorageService` 写本地 uploads/artifact，并保存 storage URI | `NasStorageService`、`MinioStorageService` 或云对象存储 backend |
| DLP / 敏感词服务 | 规则型 `GuardrailService` | 企业 DLP / 内容审核 API adapter |
| 统一 AI 平台 | 内部 `ModelGateway` 调用配置的模型 endpoint | 公司 AI 平台 adapter、LiteLLM 或 Kong 上游 |
| ELK / Prometheus / SkyWalking | MySQL trace/audit 表 + 结构化日志字段 | 日志投递、metrics exporter、OpenTelemetry/SkyWalking 集成 |

这样 V1 的重点会落在企业 Agent 治理能力，而不是企业基础设施集成工程。

## 5. 架构

### 5.1 高层运行流程

```text
浏览器
  -> FastAPI route
  -> Auth dependency 从 JWT 解析当前用户
  -> RequestGateway
       -> 创建 request_id / trace_id
       -> 执行限流
       -> 执行输入 Guardrail
       -> 计算知识/工具/模型权限
       -> 调用现有 chat / stream / aiops / upload 链路
       -> 记录 retrieval / tool / model / upload 事件
       -> 对有文本结果的请求执行输出 Guardrail
       -> 写入 gateway trace 和 audit
  -> 响应
```

### 5.2 主要组件

```text
app/api/auth.py
  登录、登出和当前用户 profile。V1 登出写入 Redis token 黑名单，并记录 audit。

app/api/admin_users.py
  管理员用户和部门管理。

app/api/admin_documents.py
  管理员文档上传、权限修改、解析/索引状态。

app/api/admin_traces.py
  trace 检索和 trace 详情。

app/api/admin_tools.py
  工具注册表和工具权限管理。

app/api/admin_models.py
  模型 endpoint 配置和用量查看。

app/api/admin_guardrails.py
  Guardrail 规则管理。

app/services/request_gateway.py
  统一包裹 chat、aiops、upload 的业务网关。

app/services/auth_service.py
  本地登录、密码哈希、JWT 签发/校验。

app/services/permission_service.py
  计算当前用户的文档、KB、工具权限。

app/services/storage_service.py
  可替换存储抽象。

app/services/tool_gateway.py
  按权限过滤和阻断 MCP/local tools。

app/services/model_gateway.py
  加权 endpoint 选择、并发保护、fallback、usage 记录。

app/services/guardrail_service.py
  规则型输入/输出 block 和 warn 检查。

app/services/audit_service.py
  trace、audit、model usage、tool call、guardrail event 持久化。
```

## 6. 身份与角色

### 6.1 登录

V1 使用本地用户名/密码登录和 JWT。

登录流程：

```text
POST /api/auth/login
  -> 在 MySQL 中校验 username/password
  -> 签发 JWT access token
  -> 返回用户 profile
```

JWT 是本地登录后的通行证，不是账号系统本身。

V1 JWT 策略：

- access token 有较短过期时间，默认建议 2 小时，具体时长通过配置控制；
- 每个受保护请求都检查 Redis token 黑名单；
- 用户登出时，把 token hash 写入 Redis 黑名单，TTL 按 token 剩余有效期计算，并设置最小 TTL 防止时钟偏差导致负数；
- 登出、黑名单命中、异常鉴权都写入 MySQL audit；
- refresh token 机制延期，不作为 V1 必需项。

黑名单 TTL 计算规则：

```text
ttl = max(exp - now, jwt_blacklist_min_ttl_seconds)
```

V1 默认 `jwt_blacklist_min_ttl_seconds = 60`。如果 token 已明显过期，可以直接返回登出成功并记录 audit，不需要写入黑名单。

返回的用户 profile 模拟企业身份字段：

```json
{
  "user_id": "u001",
  "username": "demo_user",
  "display_name": "Demo User",
  "department_id": "dept_1",
  "department_name": "Department 1",
  "roles": ["user"],
  "job_title": "Engineer",
  "auth_provider": "local_cas_mock"
}
```

### 6.2 角色

| 角色 | 权限 |
|---|---|
| `user` | 使用 `/app`；发起 chat / AIOps；查看允许范围内自己的历史和 trace |
| `dept_admin` | 拥有普通用户权限；管理本部门文档上传和授权；查看本部门 trace 和用量；可把 admin 预批准的低风险工具分配给本部门用户 |
| `admin` | 本地平台全局管理；管理模型 endpoint、工具风险等级、Guardrail、所有用户/部门/文档授权；访问机密文档时必须审计 |

### 6.3 Seed 数据

V1 初始化：

- `dept_1` 到 `dept_5`；
- 一个系统管理员；
- 每个部门一个部门管理员；
- 每个部门若干普通用户；
- 每个部门一个默认知识库。

V1 使用通用部门名，不需要使用真实组织名称。

Seed 用户密码策略：

- 初始化脚本生成随机 admin 初始密码，并输出到本地控制台；
- 测试用户可以使用固定演示密码，但必须只用于本地 demo，并在 seed 说明中标注；
- 支持 `must_change_password` 字段，管理员或重要测试账号首次登录后可要求修改密码；
- 不把真实密码、公司密码或长期有效凭据写入仓库。

## 7. 知识库与文档权限

### 7.1 概念

知识库是容器，文档是权限边界。

```text
KnowledgeBase
  -> 包含多个 Document

Document
  -> 有 confidentiality_level
  -> 有 visibility_scope
  -> 产生 chunks
```

### 7.2 文档密级

V1 文档密级：

| 密级 | 含义 |
|---|---|
| `public` | 低敏感度，可较广泛共享 |
| `internal` | 内部业务资料，默认部门范围 |
| `confidential` | 机密资料；业务用户只能通过用户级显式授权访问，不能授权给整个公司或整个部门 |

### 7.3 可见范围

V1 可见范围：

| 范围 | 含义 |
|---|---|
| `company` | 所有已登录用户可见 |
| `departments` | 仅授权部门可见 |
| `users` | 仅授权用户可见 |

安全规则：

```text
confidential 文档不能设置 visibility_scope = company。
confidential 文档不能设置 visibility_scope = departments。
confidential 文档只能使用 visibility_scope = users。
```

### 7.4 上传默认可见范围

部门管理员上传时：

| 密级 | 默认范围 |
|---|---|
| `public` | `departments`，上传者所在部门 |
| `internal` | `departments`，上传者所在部门 |
| `confidential` | `users`，上传者 |

管理员可在上传后调整授权。`admin` 是平台超级管理员，可以访问所有文档以完成管理和审计职责，但访问 `confidential` 文档时必须写入 audit；`dept_admin` 不是全局超级管理员，不能默认访问其他部门机密文档。

### 7.5 查询时过滤

Chat 和 AIOps 检索只能使用当前用户可见文档。

权限判断：

```text
文档可见，如果：
  用户是 admin
  OR scope = company
  OR scope = departments 且用户部门被授权
  OR scope = users 且用户被授权
```

其中，`admin` 对 `confidential` 的可见性属于平台管理能力，不等同于业务授权。所有 `admin` 查看、下载、修改 `confidential` 文档权限的行为，都必须记录 audit event。

检索层不能泄露不可见文档的标题、片段、chunk 或 source reference。

### 7.6 权限变更实时性和缓存失效

V1 可以缓存用户可见 KB / 文档 / 工具权限，但权限变更必须主动失效相关缓存。

权限变更包括：

- 用户部门变更；
- 用户角色变更；
- KB 绑定部门变更；
- 文档 `visibility_scope` 或 `confidentiality_level` 变更；
- `document_department_grants` / `document_user_grants` 增删改；
- 工具授权增删改。

缓存策略：

```text
user:permissions:{user_id}
department:permissions:{department_id}
permissions:version
```

实施规则：

- 权限变更写入 MySQL 后，必须删除受影响用户/部门权限缓存；
- 对影响范围难以精确计算的变更，递增 `permissions:version`，让旧缓存自然失效；
- 权限缓存 TTL 建议 5 分钟以内；
- `confidential` 文档撤权必须立即失效对应用户缓存，并写 audit；
- 如果缓存失效失败，权限修改 API 应返回失败或进入补偿状态，不能让“撤权已成功但缓存仍放行”静默发生。

## 8. 上传治理

V1 中普通用户不能上传正式知识库文档。

部门管理员：

- 只能上传到本部门拥有的 KB；
- 选择文档密级和可见范围；
- 可以把 `public` / `internal` 文档授权给部门；
- 可以把 `confidential` 文档授权给本部门具体用户；
- 不能管理其他部门 KB。

系统管理员：

- 可以上传/管理所有 KB 和所有文档授权。

上传 trace 需要记录：

- 上传用户和部门；
- 目标 KB；
- 文件名、大小、内容类型；
- parser engine；
- storage URI；
- 异步队列/job 状态；
- 解析/索引状态；
- 失败原因。

异步队列状态分工：

- Redis / RQ 负责运行时排队、执行和 worker 状态；
- MySQL `upload_status_events` 负责审计级状态记录；
- worker 在 `submitted`、`processing`、`completed`、`failed` 等关键状态变化时写入 MySQL；
- 如果队列失败重试，每次失败原因和最终状态都应形成可检索事件。

Job 重试记录策略：

- `upload_status_events` 必须包含 `job_id`、`attempt_number`、`status`、`worker_id`、`error_code`、`error_message`、`created_at`；
- 同一个 `job_id` 可以有多次 `processing`，但必须用 `attempt_number` 区分；
- `document_records` 或 `upload_jobs` 上保留当前最终状态，用于列表页快速展示；
- event 表保留完整历史，用于失败审计；
- worker 重启、OOM、任务重试不应覆盖历史 event，只能追加新 attempt event 或更新 job 当前状态。

## 9. StorageService

### 9.1 为什么需要存储抽象

当前项目把上传文件和解析产物存在本地。V1 要保持现有能力可用，同时避免业务代码到处硬编码本地路径。

正式上传文件和 artifact 存储都应该通过 `StorageService`。

### 9.2 接口形态

预期方法：

```python
save_original_file(...)
save_artifact(...)
open_file(...)
exists(...)
get_storage_uri(...)
materialize_to_local_path(...)
```

### 9.3 V1 后端

V1 实现 `LocalStorageService`。

示例 URI：

```text
local-nas://dept_1/kb_dept_1_default/doc_123/original.pdf
```

真实本地路径可以继续落在项目 uploads/artifact 根目录下。

`document_records.storage_uri` 在迁移期允许为空。新上传文件必须写入 `storage_uri`；旧文件如果没有 `storage_uri`，通过 legacy path fallback 读取，避免一次性迁移破坏现有文档链路。

### 9.4 未来后端

未来可替换后端：

- `NasStorageService`：公司 NAS 挂载目录；
- `MinioStorageService`：本地/云对象存储演示；
- `ObjectStorageService`：OSS/COS/S3 类云对象存储。

业务代码必须依赖 `StorageService`，不能直接依赖本地文件系统路径。

### 9.5 迁移策略

为了兼容现有 uploads/artifact 文件，V1 采用渐进迁移：

1. 在 `document_records` 增加 nullable `storage_uri` 和必要的 legacy path 字段映射。
2. 新上传文档统一通过 `StorageService` 保存，并写入 `storage_uri`。
3. 旧文档读取时，如果 `storage_uri` 为空，则走 legacy path fallback。
4. 提供迁移脚本，为旧文件批量生成 `local-nas://...` URI，并更新 MySQL。
5. 迁移脚本只补元数据，不移动真实文件，降低破坏风险。

## 10. RequestGateway

### 10.1 覆盖接口

V1 包裹：

- `/api/chat`；
- `/api/chat_stream`；
- `/api/aiops`；
- `/api/upload`。

### 10.2 职责

`RequestGateway` 职责：

- 生成 `request_id` 和 `trace_id`；
- 挂载用户、部门、角色上下文；
- 执行限流；
- 执行输入 Guardrail；
- 计算有效文档/工具/模型权限；
- 调用底层现有服务；
- 收集 model/tool/retrieval/upload 事件；
- 对有文本响应的请求执行输出 Guardrail；
- 持久化 trace 和 audit。

### 10.3 限流

V1 使用 Redis 做本地限流，并把严重违规写入 MySQL audit。

初始策略：

```text
每用户每分钟请求上限
每部门每分钟请求上限
admin 在本地演示中可按需绕过
```

限流命中需要写入 trace/audit。

Redis 限流 key 使用短 TTL 计数。Redis 是否启用 RDB/AOF 可以由本地环境决定；V1 的合规证据不依赖 Redis 持久化，而是依赖 MySQL audit。

### 10.4 失败和降级策略

`RequestGateway` 区分关键路径和非关键路径：

| 环节 | V1 策略 |
|---|---|
| JWT 鉴权失败 | 拒绝请求 |
| 权限计算失败 | 拒绝请求 |
| 输入 Guardrail 检查失败 | 保守拒绝请求 |
| 输入 Guardrail 命中 block | 不调用模型，返回合规提示 |
| Redis 限流不可用 | 降级允许普通请求通过，写结构化告警日志，并在 trace 中标记 `rate_limit_degraded = true` |
| 模型调用失败 | 交给 `ModelGateway` fallback |
| trace/audit 写入失败 | 不阻断已完成的普通响应，但写结构化错误日志，后续可补偿 |
| output warn 写入失败 | 不阻断响应，但写结构化错误日志 |

安全相关阻断事件即使 audit 写入失败，也必须优先阻断请求；审计失败本身应产生错误日志，供管理员在本地运行时排查。

限流是保护系统的非安全核心能力。Redis 短时不可用时，V1 优先保证本地 demo 可用性，不因为限流组件故障导致所有 chat/AIOps 请求不可用。但必须暴露明显告警，方便管理员看到系统处于降级状态。

## 11. ToolGateway

### 11.1 工具注册表

在 MySQL 注册 local 和 MCP 工具：

```text
tool_name
server_name
description
risk_level: low | medium | high
enabled
source: local | mcp
last_seen_at
```

MCP 工具采用“自动发现 + 管理员补元数据”的方式：

- 服务启动时从 MCP server 拉取实际工具列表；
- 新工具不存在时自动写入 `tool_registry`，默认 `enabled = false` 或低权限待审核；
- 已存在工具更新 `last_seen_at`，保留管理员配置的 `risk_level` 和 `enabled`；
- 工具消失时不直接删除，标记为未发现，方便审计和回滚；
- `admin` 在控制台调整工具描述、风险等级和启用状态。

### 11.2 授权

工具授权：

```text
tool_department_grants
tool_user_grants
```

有效工具：

```text
enabled tools
  AND (部门授权 OR 用户授权 OR admin 角色)
```

授权边界：

- `admin` 可以管理所有工具授权和风险等级；
- `dept_admin` 不能修改工具风险等级，也不能启用新工具；
- `dept_admin` 只能把 `admin` 已启用且标记为 `low` 风险的工具，分配给本部门或本部门用户；
- `medium` / `high` 风险工具只能由 `admin` 授权。

### 11.3 阻断

V1 必须阻断未授权工具调用。

两层防线：

1. 绑定工具给 LLM 前，只传 allowed tools。
2. 真正调用工具前，再检查一次权限。

未授权工具调用返回 blocked tool result，并创建 audit event。

## 12. ModelGateway

### 12.1 目的

`ModelGateway` 在本地模拟公司统一 AI 平台或 AI Gateway。

它负责治理模型调用，避免每个服务直接调用 DashScope。

### 12.2 Endpoint 模型

```text
model_endpoint
- id
- provider
- model_name
- api_base
- api_key_ref
- weight
- status: active/degraded/disabled
- max_concurrency
- timeout_ms
- fallback_order
```

只有 `admin` 能管理 endpoint。

`dept_admin` 可以查看本部门用量，但不能修改 endpoint。

`user` 看不到模型配置。

### 12.3 路由行为

V1 路由：

- 按配置路线选择 active endpoints；
- 使用加权随机选择；
- 跳过超过 `max_concurrency` 的 endpoint；
- timeout/error 时 fallback；
- 记录选中的 endpoint、fallback 事件、latency、token usage、error。

V1 endpoint 并发计数使用 Redis，而不是单进程内存：

```text
model:request:{endpoint_id}:{request_id}
```

并发统计采用“活跃请求标记”而不是单纯 `incr/decr`：

1. 为每次模型调用生成 `request_id`。
2. 选中 endpoint 前统计该 endpoint 下未过期活跃请求数。
3. 如果达到 `max_concurrency`，跳过该 endpoint。
4. 选中后写入 `model:request:{endpoint_id}:{request_id}`，TTL 默认 5 分钟。
5. 请求完成后删除该请求标记。
6. 如果进程异常退出或 Redis delete 失败，TTL 会自动清理残留标记。

如果需要更高性能，后续可以把活跃请求集合改为 Redis sorted set，并按 timestamp 清理过期成员。V1 以清晰可靠为先。

加权随机算法：

```text
total_weight = sum(endpoint.weight)
r = random(0, total_weight)
按 endpoint 顺序累计 weight，累计值第一次 >= r 的 endpoint 被选中
```

Fallback 约束：

- 每次请求设置最大 fallback 次数，例如 3 次；
- 已经失败的 endpoint 在同一请求内不重复尝试；
- 所有候选 endpoint 都不可用时，快速返回模型不可用错误；
- circuit breaker 和主动健康探测作为后续增强。

### 12.4 Usage 与成本

如果模型响应包含 usage，记录：

- prompt tokens；
- completion tokens；
- total tokens；
- model；
- endpoint；
- user；
- department；
- route；
- 如果已配置单价，则记录估算成本。

如果 provider 没返回 usage，V1 存 `null`，不编造 token 数。

## 13. Guardrails

### 13.1 V1 Guardrail 类型

V1 使用可配置规则：

```text
pattern_type: keyword | regex
scope: input | output | both
action: block | warn
reason
enabled
```

正则安全约束：

- 后台保存 regex 规则前必须做编译校验；
- regex 规则长度、数量和单次匹配耗时必须有限制；
- 单条 regex 匹配建议设置 100ms 以内超时；
- 禁止或告警明显存在灾难性回溯风险的表达式；
- 如果后续依赖允许，优先使用 RE2 类线性时间正则引擎；
- regex 检查异常时按该规则不通过处理，并写 guardrail policy error event，不能让异常中断整个请求链路。

### 13.2 示例规则

示例：

```text
内网.*外网
数据.*带出
绕过.*审计
删除.*日志
规避.*权限
导出.*客户数据
```

### 13.3 行为

Input `block`：

- 不调用模型；
- 返回合规提示；
- 写入 trace/audit/guardrail event。

Input `warn`：

- 继续请求；
- 写入 warning event。

Output `block`：

- 用合规提示替换生成答案；
- 写入 event。

Output `warn`：

- 返回生成答案；
- 写入 warning event。

流式输出策略：

- 非流式响应：模型生成完整答案后执行 output Guardrail；
- `chat_stream`：服务端累积最近若干 chunk 做滚动检查；
- 如果流式输出命中 `block`，立即停止继续向用户发送模型内容，发送合规提示，并写入 guardrail event；
- 输入 Guardrail 是主要防线，输出 Guardrail 在流式场景中属于尽力阻断，不能替代输入侧风险识别。

## 14. 管理控制台

V1 管理 UI 以基础可用为目标，不追求完整精致。

页面：

```text
/login
/app
/admin/users
/admin/documents
/admin/traces
/admin/tools
/admin/models
/admin/guardrails
```

权限：

| 页面 | user | dept_admin | admin |
|---|---:|---:|---:|
| `/app` | 可以 | 可以 | 可以 |
| `/admin/users` | 不可 | 本部门用户的有限管理/查看 | 所有用户 |
| `/admin/documents` | 不可 | 本部门 | 所有部门 |
| `/admin/traces` | 可隐藏或只看自己的 trace | 本部门 | 所有部门 |
| `/admin/tools` | 不可 | 只能分配 admin 预批准的 low 风险工具 | 所有工具 |
| `/admin/models` | 不可 | 只能查看本部门用量 | 配置和用量 |
| `/admin/guardrails` | 不可 | 只读或不可见 | 全部配置 |

前端实现优先选择与现有项目兼容的最小方案。V1 可以扩展当前 static 前端。Vue + Element Plus 改造延期，除非用户单独批准为新范围。

## 15. 可观测与审计

### 15.1 本地可观测目标

V1 必须让每次请求都能解释清楚：

```text
谁调用的
走了哪个 route
哪些知识可见
选中了哪个模型 endpoint
暴露/调用/阻断了哪些工具
命中了哪些 Guardrail
主要步骤各自耗时多久
upload 解析/索引是否成功或失败
```

### 15.2 核心记录

记录：

```text
gateway_traces
audit_logs
model_usage_records
tool_call_records
guardrail_events
upload_status_events
```

### 15.3 通用 Trace 字段

使用一致字段：

```text
request_id
trace_id
span_id
route
user_id
department_id
role
status
latency_ms
error_code
created_at
```

这些字段方便未来导出到 ELK、Prometheus、SkyWalking 或 OpenTelemetry，而不需要重新设计本地 trace 模型。

V1 不需要运行 ELK、Prometheus 或 SkyWalking。

### 15.4 Trace 保留和清理

V1 默认按 180 天保留 trace/audit，以贴近企业日志保留要求。为了避免长期运行导致 MySQL 表无限增长：

- trace/audit 表必须有 `created_at` 索引；
- gateway trace 建议建立 `(user_id, created_at)`、`(department_id, created_at)`、`(route, created_at)` 复合索引；
- model usage 建议建立 `(department_id, created_at)`、`(model, created_at)`、`(endpoint_id, created_at)` 复合索引；
- tool/guardrail/upload event 建议建立 `(trace_id)`、`(created_at)` 和业务查询字段复合索引；
- 提供按时间清理的本地管理脚本；
- 管理台检索默认限制时间范围和分页大小；
- trace 列表使用 cursor-based pagination，避免大 offset 分页；
- MySQL 分区表、归档表、归档到对象存储属于后续生产化增强。

## 16. 建议数据模型

V1 MySQL 表，实施时可细化：

```text
departments
users
roles 或 user_roles
knowledge_bases
document_records
document_department_grants
document_user_grants
tool_registry
tool_department_grants
tool_user_grants
model_endpoints
model_usage_records
guardrail_policies
guardrail_events
gateway_traces
audit_logs
upload_status_events
```

关键字段约定：

- `document_records.storage_uri` 允许 nullable，用于兼容旧文件；
- `document_records.legacy_path` 或等价映射只用于迁移期 fallback；
- `gateway_traces`、`audit_logs`、`model_usage_records`、`guardrail_events`、`upload_status_events` 必须有 `created_at` 索引；
- `upload_status_events` 必须包含 `job_id` 和 `attempt_number`；
- token 黑名单、限流计数、模型并发计数放 Redis，不放 MySQL 主表；
- 严重安全事件、登出事件、黑名单命中事件写 MySQL audit。

现有 metadata store 需要谨慎接入。不要在没有清晰迁移或桥接策略时重复保存文档/chunk 状态。

Memory store 策略：

- V1 阶段，现有 memory records 可以继续使用独立 SQLite；
- 新增企业治理数据统一进入 MySQL；
- 不为了“数据库统一”强行迁移已经稳定的 memory 子系统；
- 后续如果要迁移 memory store 到 MySQL，需要单独评估性能、兼容性和回滚方案。

## 17. 与现有项目集成

### 17.1 保留现有行为

尽量保留：

- `RagAgentService` 行为，除用户上下文和 allowed tools 外不大改；
- `AIOpsService` 图执行行为，除用户工具/模型上下文外不大改；
- `retrieve_knowledge` 的 content/artifact contract；
- 现有 MCP client 行为，除 allowed-tool 过滤和调用前阻断外不重写；
- 现有 parser 和文档入库链路；
- 现有 memory-shadow 默认关闭语义。

### 17.2 入口预期变化

API route 应成为薄入口：

```text
route -> current_user -> RequestGateway -> existing service
```

### 17.3 Retrieval 权限集成

检索必须按可见文档/chunk 过滤。

优先方向：

- 在 Milvus / 向量检索层增加权限元数据预过滤；
- 在 retrieval 层增加 MySQL 精确权限二次校验；
- 避免等 LLM context 拼好后才做后置过滤；
- 保留 `source_ref`、`citation_text`、artifact 语义。

Milvus chunk 元数据至少包含：

```text
chunk_id
doc_id
kb_id
owner_department_id
visibility_scope: company | departments | users
confidentiality_level: public | internal | confidential
allowed_department_ids: array<string> 或可过滤等价字段
is_confidential: bool
```

查询策略：

1. `public + company` 文档可在 Milvus 中直接放行。
2. `public/internal + departments` 文档用 `allowed_department_ids` 或等价字段做 Milvus filter expression。
3. `confidential` 文档不做粗放部门过滤，必须走 MySQL `document_user_grants` 精确校验。
4. Milvus 过滤只作为粗粒度预过滤，最终拼入 LLM context 前，必须再按 MySQL 权限规则确认 `doc_id` 可见。
5. 如果 Milvus 表达式能力不足以表达数组权限，V1 可以退化为“扩大 top_k + MySQL 精确过滤”，但必须在 trace 中记录 `permission_filter_mode = degraded_post_filter`。

示例逻辑：

```text
普通用户：
  (visibility_scope = company AND confidentiality_level in [public, internal])
  OR (visibility_scope = departments AND user.department_id in allowed_department_ids AND confidentiality_level in [public, internal])
  OR doc_id in user's confidential_doc_ids

dept_admin：
  同普通用户；额外管理权限不自动变成检索可见权限

admin：
  可检索全部文档；访问 confidential 结果时记录 audit
```

性能原则：

- 默认 top_k 不应无限扩大；
- 如果预过滤后结果不足，最多进行有限次数补查；
- 对用户可见的 `confidential_doc_ids` 可短 TTL 缓存，但撤权必须主动失效；
- 不允许在 LLM prompt 组装后才剔除无权限内容。

### 17.4 现有运行时状态桥接

V1 不要求把现有 Redis/RQ、metadata store、memory store 一次性改造成 MySQL 驱动：

- Redis/RQ 继续负责文档处理的运行时队列；
- MySQL 记录 upload 状态事件和审计事实；
- 现有文档/chunk/artifact 语义继续保留，MySQL 只增加治理元数据；
- MCP client 继续负责实际连接 MCP server，`ToolGateway` 只增加授权过滤和调用前阻断；
- `StorageService` 先包裹新上传路径，再通过 fallback 支持旧文件。

## 18. 测试与验证

V1 验证应覆盖：

- 登录成功/失败；
- JWT 保护接口拒绝匿名请求；
- 登出后 token 黑名单生效；
- 黑名单 TTL 对已过期 token 和时钟偏差安全；
- 角色级 admin 页面/API 访问；
- 部门管理员不能管理其他部门文档；
- company 可见 public 文档对所有用户可见；
- internal 部门文档只对授权部门可见；
- confidential 文档只对授权用户和审计中的 admin 可见；
- 文档权限撤销后，用户权限缓存立即失效；
- Milvus 权限预过滤和 MySQL 二次校验共同阻断未授权 chunk；
- 未授权检索不泄露不可见 source ref；
- 未授权 MCP 工具不绑定给模型，且被调用时会阻断；
- dept_admin 只能分配 admin 预批准的 low 风险工具；
- 模型 endpoint 模拟失败后发生 fallback；
- Redis max concurrency 跳过行为；
- 模型并发请求标记在异常退出后可被 TTL 清理；
- 所有 endpoint 不可用时快速返回错误；
- Redis 限流不可用时请求降级通过并产生告警标记；
- Guardrail block 会阻止模型调用；
- Guardrail regex 异常或超时不会拖垮请求；
- `chat_stream` 输出命中 block 时截断并返回合规提示；
- upload 记录 parser engine、队列状态、失败审计；
- upload job 重试时用 `attempt_number` 区分状态事件；
- 旧文件没有 `storage_uri` 时仍能通过 fallback 读取；
- gateway trace 包含 request、user、model、tool、guardrail、latency 字段。

## 19. 设计层面的实施顺序

实施建议分阶段：

1. Docker Compose 依赖服务：MySQL、Redis、Milvus。
2. MySQL 数据模型、迁移和 seed 数据。
3. Auth/JWT、Redis 黑名单和 current-user dependency。
4. RequestGateway trace shell 包裹 chat/aiops/upload。
5. StorageService 和旧文件 fallback。
6. 文档权限模型和 upload governance。
7. 权限感知 retrieval。
8. ToolGateway allowed-tool 过滤和阻断。
9. ModelGateway endpoint 选择、Redis 并发、fallback、usage。
10. Guardrail service 和 admin policies。
11. 管理 UI 页面。
12. 端到端 demo 场景和文档。

每一阶段都要先做 targeted tests，再跑更宽的回归。

## 20. 实施前仍需确认的问题

本设计已经足够进入实施计划，但编码前仍建议确认：

- V1 前端继续扩展 static，还是启动 Vue + Element Plus 迁移；
- JWT access token 默认过期时间是否采用 2 小时；
- JWT 黑名单最小 TTL 是否采用 60 秒；
- Redis 限流默认值；
- V1 是否配置模型单价并估算成本，还是只记录 token；
- admin trace 搜索是否暴露请求内容片段，还是只暴露 metadata。

## 21. 本地开发环境

### 21.1 依赖服务

V1 推荐使用 Docker Compose 启动本地依赖：

```text
MySQL 8.0：治理数据库
Redis 7：限流、JWT 黑名单、模型并发计数、运行时状态
Milvus 2.x：现有向量检索
```

### 21.2 快速启动预期

```bash
docker-compose up -d
python scripts/init_governance_db.py
python main.py
```

实际命令以项目后续实现为准。设计要求是：新增 MySQL 不应该让本地演示变成手工搭环境；应提供一键启动依赖服务、初始化表结构和 seed 数据的脚本。

### 21.3 MySQL 与 SQLite 的边界

V1 使用 MySQL 承载企业治理数据，但不强制迁移现有 SQLite memory store：

| 数据类型 | V1 存储 |
|---|---|
| 用户、部门、角色 | MySQL |
| KB、文档授权、工具授权 | MySQL |
| 模型 endpoint、usage、成本 | MySQL |
| trace、audit、guardrail event、upload event | MySQL |
| JWT 黑名单、限流、并发计数 | Redis |
| 现有 memory records | 暂时保留 SQLite |

这样既能模拟企业 MySQL 治理数据库，又不会为了数据库统一破坏现有 memory 子系统。
