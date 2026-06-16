# 企业能力开发记录

日期：2026-05-30

项目：SuperBizAgent（`super_biz_agent_py-release-2026-03-21`）

用途：记录 Gateway、数据库操作能力、成熟项目做法差距等企业化能力相关工作。RAG 仍记录在 `docs/rag_fusion_development_record.md`，Memory 仍记录在 `docs/memory_fusion_development_record.md`，AIOps 主链路仍记录在 `docs/aiops_mainline_development_record.md`。

## 2026-05-31：Enterprise 2.0 F2a 轨迹评估骨架

### 为什么现在做

E0-E11 已经完成，E11 只作为 E9 冻结 SSE envelope 的前端消费者。进入 2.0 后，按 `docs/企业开发计划2.0_详细设计.md` 的顺序，第一步必须先建立轨迹评估底座，再做 F1 任务合同化和后续自检/恢复/审批能力。否则后续能力只能看最终答案，无法自动判断工具路径、权限阻断、SSE 字段或 audit 事件是否合规。

F2a 是基础设施切片：只做离线 trace eval，不改变任何用户请求路径，不修改 RequestGateway、adapter、legacy RAG/AIOps 服务或 agent 节点。

### 实现边界

本轮新增 `evals/enterprise/*`：

- `models.py`：定义 `ExpectedTrajectory`、`ActualTrajectory`、`TrajectoryMismatch`、`TraceEvalResult` 和 `TraceEvalReport`。
- `extractors.py`：`AuditTraceExtractor` 支持从 inline fixture、audit JSONL、SQLite audit sink 中按 `trace_id` / `request_id` 提取事件。
- `matcher.py`：`TrajectoryMatcher` 做确定性比较，覆盖 final status、required audit event、stage 顺序、forbidden tool、SSE envelope 字段。
- `run_trace_eval.py`：提供 `python -m evals.enterprise.run_trace_eval --evalset ...` runner，输出 JSON 和 Markdown report。
- `evalsets/*.jsonl`：新增 chat、AIOps、SSE contract 三份最小 evalset。
- `tests/test_enterprise_trace_eval.py`：覆盖模型校验、JSONL/SQLite extractor、三类负例识别和 report 输出。

`pyproject.toml` 同步把 `evals*` 加入 package discovery / first-party import 配置。原因是 `uv run pytest` 走 editable package 元数据；F2a runner 是可 import 的项目模块，不应依赖测试文件手动插入 `sys.path`。

### 能识别的问题

F2a targeted test 明确覆盖三类计划要求的问题：

- 缺 audit 事件：`missing_audit_event`。
- 错误工具调用：`forbidden_tool_used`，例如 `database_demo.safe_select` 命中 `database-demo` 禁用前缀。
- SSE 缺 trace 字段：`sse_missing_trace_id`，并同时检查 request_id、stage、status、message、data。

### 验证

已运行：

```text
uv run pytest -q tests/test_enterprise_trace_eval.py
uv run python -m evals.enterprise.run_trace_eval --evalset evals/enterprise/evalsets/chat_trace_evalset.jsonl
uv run python -m evals.enterprise.run_trace_eval --evalset evals/enterprise/evalsets/aiops_trace_evalset.jsonl
uv run python -m evals.enterprise.run_trace_eval --evalset evals/enterprise/evalsets/sse_contract_evalset.jsonl
uv run ruff check evals/enterprise tests/test_enterprise_trace_eval.py pyproject.toml
uv run python -m compileall -q evals tests
make deps-check
git diff --check
```

结果：

- F2a targeted tests：5/5 通过。
- chat / AIOps / SSE 三份 bundled evalset 都返回 `total=1 passed=1 failed=0 mismatch_count=0`。
- targeted `ruff check` 通过；只出现 repo 既有的 top-level ruff config deprecation warning。
- `compileall`、`make deps-check`、`git diff --check` 通过。
- 无已知缺口。

### Git 收口

F2a 实现提交：`50c4649 enterprise2(f2a): add trace eval skeleton`。

本节文档、`PROJECT_STATE.md`、`task_plan.md`、`progress.md`、`findings.md` 和详细设计阶段状态将作为 F2a 收口提交进入 `enterprise2` 分支。

## 2026-05-31：Enterprise 2.0 F1 任务合同化 MVP

### 为什么现在做

F2a 已经提供离线 trace 评估骨架。2.0 下一步需要给复杂企业任务增加可验证边界，避免只靠一句 prompt 决定工具、数据源和输出标准。F1 的目标不是重写 AIOps planner/executor/replanner，而是在进入旧流程前建立 task contract，并让 trace/audit 能关联合同、执行事件和最终报告。

F1 第一版只覆盖显式复杂 AIOps 请求，不把普通聊天、普通 RAG 或普通 AIOps smoke 强制合同化。

### 实现边界

本轮新增 `app/enterprise/tasks/*`：

- `models.py`：定义 `RiskLevel`、`TaskStatus`、`TaskScope`、`TaskContractCreate`、`TaskContract`、`ContractValidationIssue`、`ContractValidationResult` 和 `TaskContractCreateResult`。
- `repository.py`：提供 `InMemoryTaskContractRepository` 和 `SQLiteTaskContractRepository`，支持 create/get/update_status/list_by_trace。
- `validator.py`：`ContractValidator` 通过现有 `PermissionService.check(...)` 校验合同内的 `document:read` 和 `tool:use` 资源，检查 forbidden action 冲突，并强制高风险任务进入审批策略。
- `service.py`：`TaskContractService` 创建合同、持久化 running/pending/rejected 状态，并写 `task_contract_created` / `task_contract_rejected` audit。

同时更新：

- `app/config.py`：新增 `enterprise_task_contract_sqlite_path`，默认 `logs/enterprise_task_contracts.sqlite`。
- `app/models/aiops.py`：给 `AIOpsRequest` 增加可选 `query` 和 `task_contract` 输入模型。
- `app/enterprise/adapters/aiops_adapter.py`：只在 `request.task_contract` 存在时创建/验证合同；合同拒绝或待审批时返回 SSE `error`，不进入 planner；合同通过时把 `task_contract_id` 传给 AIOps service。
- `app/services/aiops_service.py` 和 `app/agent/aiops/state.py`：把 `task_contract_id` 作为观测字段透传到 planner/executor/replanner/complete 事件，不改变 graph 路由和节点逻辑。

### 行为和边界

- 简单 AIOps 请求仍走 legacy path，`task_contract_id=None`，stream event 不新增合同字段。
- 合同内未授权 data source 会以 `data_source_permission_denied` 阻断；未授权工具以 `tool_permission_denied` 阻断。
- 高风险且声明需要审批的合同会持久化为 `pending`，返回 `pending_approval`，不会进入执行。
- 被拒绝合同会持久化为 `rejected`，并写 `task_contract_rejected` audit；通过合同持久化为 `running` 并写 `task_contract_created` audit。
- F1 不新增审批 API；人工审批留给 F6。F1 也不把 DB tools 放入默认 AIOps/RAG 工具池。

### 验证

已运行：

```text
uv run pytest -q tests/test_enterprise_task_contract.py
uv run pytest -q tests/test_enterprise_gateway_routes.py tests/test_enterprise_request_gateway.py
uv run ruff check app/enterprise/tasks app/enterprise/adapters/aiops_adapter.py app/models/aiops.py app/services/aiops_service.py app/agent/aiops/state.py tests/test_enterprise_task_contract.py
uv run python -m compileall -q app tests
make deps-check
git diff --check
git diff --cached --check
```

结果：

- F1 targeted tests：6/6 通过。
- gateway/request regression：8/8 通过。
- targeted `ruff check` 通过；只出现 repo 既有的 top-level ruff config deprecation warning。
- `compileall`、`make deps-check`、`git diff --check` 和 staged `git diff --cached --check` 通过。
- 无已知功能缺口；F6 前仍不提供人工审批 API。

### Git 收口

F1 实现提交：`89cea41 enterprise2(f1): add task contract mvp`。

本节文档、`PROJECT_STATE.md`、`task_plan.md`、`progress.md`、`findings.md` 和详细设计阶段状态将作为 F1 收口提交进入 `enterprise2` 分支。下一阶段为 F2b 合同感知轨迹评估。

## 2026-05-31：Enterprise 2.0 F2b 合同感知轨迹评估

### 为什么现在做

F1 已经把复杂任务显式合同化，但还没有把合同当成评估维度。F2b 的目的不是再扩业务能力，而是把 trace eval 升级为“能判断合同是否被遵守”的离线检查层，让后续 F4/F5/F6 的 verifier、恢复和审批能力有可比对的基准。

### 实现边界

本轮继续沿用 `evals/enterprise/*`，不改任何 runtime 请求路径：

- `models.py`：为 `TrajectoryExpectation` 加入 `expected_contract`，并定义 `ExpectedContractScope` / `ExpectedTaskContract` / `ObservedTaskContract` / `TraceSource.task_contract_path` / `TraceSource.task_contracts`。
- `extractors.py`：从 audit、SQLite 合同 repository 和 inline contract fixtures 提取 `task_contract_id`、scope、risk、status，并把 observed data sources / tools / contract snapshot 写入 `ActualTrajectory`。
- `matcher.py`：增加 contract mismatch 分类，覆盖 `contract_missing`、`scope_violation`、`approval_missing` 和 `success_criteria_unchecked`，同时保留 F2a 的 stage/tool/sse/audit 检查。
- `run_trace_eval.py`：在 markdown report 中显式输出 mismatch categories，方便直接从报告看出 contract / stage / tool / sse 类问题。
- `evalsets/*.jsonl`：新增 DB / Admin evalset，并把 AIOps evalset 升级为合同感知版本。
- `tests/test_enterprise_trace_eval.py`：新增合同模型、SQLite 合同仓库提取、contract mismatch、缺失合同回归，以及 bundled evalset runner smoke。

### 行为和边界

- F2a 的旧 eval 仍然可运行，不受 F2b 影响。
- 评估层可以看到合同，但 runtime 仍然只在 F1 的 explicit complex AIOps 路径上创建合同。
- DB / Admin evalset 只是 deterministic trace fixture，不代表 DB 或 Admin 业务面有新 runtime 行为。
- 报告分类已经包含 contract 维度，后续 F4/F5/F6 可以沿用这条分类线。

### 验证

已运行：

```text
uv run pytest -q tests/test_enterprise_trace_eval.py
uv run python -m evals.enterprise.run_trace_eval --evalset evals/enterprise/evalsets/chat_trace_evalset.jsonl --no-write
uv run python -m evals.enterprise.run_trace_eval --evalset evals/enterprise/evalsets/aiops_trace_evalset.jsonl --no-write
uv run python -m evals.enterprise.run_trace_eval --evalset evals/enterprise/evalsets/sse_contract_evalset.jsonl --no-write
uv run python -m evals.enterprise.run_trace_eval --evalset evals/enterprise/evalsets/db_trace_evalset.jsonl --no-write
uv run python -m evals.enterprise.run_trace_eval --evalset evals/enterprise/evalsets/admin_trace_evalset.jsonl --no-write
uv run ruff check evals/enterprise tests/test_enterprise_trace_eval.py
uv run python -m compileall -q app tests evals
make deps-check
git diff --check
```

结果：

- F2b targeted tests：10/10 通过。
- chat / AIOps / SSE / DB / Admin bundled evalset smoke 全部通过。
- targeted `ruff check` 通过；只出现 repo 既有的 top-level ruff config deprecation warning。
- `compileall`、`make deps-check`、`git diff --check` 通过。

### Git 收口

F2b 实现提交：`1b5ec28 enterprise2(f2b): add contract-aware trace eval`。

本节文档、`PROJECT_STATE.md`、`task_plan.md`、`progress.md`、`findings.md` 和详细设计阶段状态将作为 F2b 收口提交进入 `enterprise2` 分支。下一阶段为 F4 结构化自检器 MVP。

## 2026-05-30：Git 分支管理

### 为什么现在做

用户要求企业助手开发开独立支线，分支名为 `enterprise`。由于当前 Git 根是父目录 `/Users/cici/oncall agent`，而不是 `super_biz_agent_py-release-2026-03-21` 子目录，所以分支必须在父仓库创建。

### 执行结果

- 当前父仓库分支已切换为 `enterprise`。
- 分支仍是 unborn branch（父仓库还没有初始 commit）。
- `super_biz_agent_py-release-2026-03-21/` 仍是未跟踪目录；本轮只做分支切换，没有 stage、commit 或 push。

### 验证

```text
git branch --show-current
git status --short --branch
```

结果显示：

```text
enterprise
## No commits yet on enterprise
```

## 2026-05-30：首个提交前 Git 忽略规则与阶段验收标准

### 为什么现在做

用户要求先加 `.gitignore`，再只把 `super_biz_agent_py-release-2026-03-21/` 里需要的源码和文档纳入首个 commit，避免 `.env`、大参考仓库、临时输出和运行产物被误提交。同时用户明确“每一个小章节”指的是 E0/E1 这种阶段章节，不是普通说明小节。

### 变更

- 在父仓库 `/Users/cici/oncall agent/.gitignore` 增加忽略规则。
- 忽略范围覆盖 `.env`、`.claude/`、OpenViking / WeKnora / TencentDB-Agent-Memory 等本地参考仓库、`reference_repos/`、虚拟环境、CodeGraph 索引、日志、pid、uploads、traces、volumes、SQLite/db 文件、zip 包、eval 运行输出和工作区输出目录。
- 在 `docs/enterprise_assistant_development_plan.md` 的 E0-E10 阶段章节末尾补充 `本节验收标准`。
- 首个提交保留 eval 脚本和样本 `.jsonl`，但不纳入 timestamped eval JSON/MD、`reports/`、probe JSON 或 dump TXT。

### 验收口径

- 首个 commit 只能 stage 父仓库 `.gitignore` 和 `super_biz_agent_py-release-2026-03-21/` 里的必要源码、测试、配置、文档、eval 脚本与样本。
- 不 stage `.env`、`.venv`、`.codegraph`、logs、uploads、traces、volumes、zip 包、父目录参考仓库和输出目录。
- E0-E10 每个阶段章节末尾都能看到独立的 `本节验收标准`。
- 首个企业分支基线 commit：`761e6cb chore: initialize enterprise baseline`。

## 2026-05-30：补充阶段 Git 收口和任务级参考源

### 为什么现在补

用户指出 E6 的验收标准里没有写 Git 管理，也没有在计划中清楚看到每个任务写代码前要参考哪个成熟仓库。这个问题不只影响 E6，而是 E0-E10 每个阶段的完成定义。

### 修正动作

已更新 `docs/enterprise_assistant_development_plan.md`：

- 新增 `2.6 Git 阶段收口原则`，规定每个 E 阶段完成前必须在 `enterprise` 分支完成 targeted verification、状态文档同步、暂存区安全检查、阶段 commit，并把 commit hash 写入本开发记录。
- 新增 `5.2 阶段任务参考矩阵`，把 E0-E10 内部任务映射到具体参考仓库和参考重点。
- 在 E0-E10 每个阶段开头补充 `编码参考`。
- 在 E0-E10 每个 `本节验收标准` 中加入“完成阶段 Git 收口 commit”。
- E6 进一步细化为 sandbox DB / demo provider 参考 `modelcontextprotocol-servers`，SafeSqlKernel 参考 `sqlglot`，Schema Registry 参考 `data-api-builder`，audit sink 复用本地 SQLite/JSONL 习惯并参考 `langfuse` 字段。

### 当前结论

后续任何阶段不能只用功能测试宣布完成。阶段完成必须同时满足：

```text
功能/安全验收通过
状态和开发记录已同步
暂存区范围安全
阶段 commit 已创建
commit hash 已记录
```

## 2026-05-30：E6 DB-P0a/P0b Sandbox Read-only + Safe SQL Kernel

### 为什么现在做

E3-E5 治理主干已经闭合，E4 的 `ToolGateway` 已经具备默认过滤 database tools 的安全边界。E6 可以作为并行 DB sandbox 分支推进，但只能证明受控查询能力，不能接真实业务库，也不能把 database tools 放进默认 AIOps/RAG 工具池。

### 参考来源

- sandbox DB / demo provider：参考 `modelcontextprotocol-servers` 的 database server 工具形态和只读边界，只保留 list / describe / read-only query 的最小形状。
- SafeSqlKernel：参考 `sqlglot` 的 AST parse、statement type 和 expression traversal，用 AST allowlist 代替字符串过滤。
- Schema Registry：参考 `data-api-builder` 的 database resource / table-column exposure 边界，把表列暴露做成显式 allowlist。
- audit sink：复用本项目 E2 已有 `AuditService` 的本地 SQLite/JSONL sink，不引入远端观测依赖。

### 代码级变更

- 新增 `app/enterprise/database/sandbox.py`：创建确定性的本地 SQLite sandbox fixture，包含 `orders` / `incidents` 两张表和隐藏列，用于证明 allowlist 阻断。
- 新增 `app/enterprise/database/registry.py`：`DatabaseSchemaRegistry`、`TablePolicy`、`ColumnPolicy`，默认按未知表/列 deny，`customer_email` 标记为敏感字段并按 email mask。
- 新增 `app/enterprise/database/safe_sql.py`：`SafeSqlKernel` 使用 `sqlglot.parse(..., read="sqlite")`，只允许单条单表 `SELECT`，阻断 DML、DDL、多语句、未授权表列、`select *`、函数、join/subquery 和列 alias；无 LIMIT 自动加安全 LIMIT，超出 max LIMIT 阻断；执行时开启 `PRAGMA query_only = ON`，通过 SQLite progress handler 做超时中断，并对结果 JSON 字节数设置上限；所有成功、阻断和失败路径写 `database_query` audit。
- 新增 `app/enterprise/database/service.py` / `provider.py`：只暴露 `database_demo.list_tables`、`database_demo.describe_table`、`database_demo.safe_select` 三个显式 demo 工具。
- 修改 `app/enterprise/tools/gateway.py`：provider 若实现 `execute_tool_with_context(...)`，`ToolGateway` 会把 `RequestContext` 传进去；普通 provider 仍走原 `execute_tool(...)` 路径。
- 修改 `pyproject.toml` / `uv.lock`：新增 `sqlglot>=30.8.0,<31.0.0`。

### 风险和处理

- 风险：database tools 误进入默认工具池。处理：E6 阶段复用 E4 的 `ToolDefinition.is_database_tool` / `ToolGateway.include_database_tools=False` 默认过滤；E7 后显式 database-demo session 改为 `PermissionService` tool/table/column grants 控制可见性，默认 AIOps/RAG 路径仍不挂 DB provider。
- 风险：LLM 生成 SQL 绕过字符串规则。处理：只以 `sqlglot` AST 为准，未知结构默认拒绝；别名选择也阻断，避免敏感列改名后绕过 registry mask / audit。
- 风险：SQLite connection 在异常路径泄漏。处理：`sandbox.py` 和 `safe_sql.py` 均使用 `contextlib.closing(sqlite3.connect(...))` 显式关闭连接。
- 风险：失败路径泄漏原始异常。处理：执行失败包装为 `DatabaseExecutionError`，audit 只记录 `error_class`，不记录 raw exception message。

### 验证

已运行：

```text
.venv/bin/python -m pytest -q tests/test_enterprise_database_e6.py
.venv/bin/python -m pytest -q tests/test_enterprise_database_e6.py tests/test_enterprise_tool_gateway.py
.venv/bin/python -m pytest -q tests/test_enterprise_auth.py tests/test_enterprise_request_context.py tests/test_enterprise_request_gateway.py tests/test_enterprise_gateway_routes.py tests/test_enterprise_permissions.py tests/test_enterprise_tool_gateway.py tests/test_enterprise_model_gateway.py tests/test_enterprise_rag_upload_e5.py tests/test_enterprise_database_e6.py
.venv/bin/python -m ruff check app/enterprise/database app/enterprise/tools tests/test_enterprise_database_e6.py
.venv/bin/python -m compileall -q app tests
make deps-check
git diff --check
```

结果：

- E6 targeted tests 8/8 通过。
- E6 + ToolGateway 回归 19/19 通过。
- E1-E6 enterprise targeted bundle 44/44 通过；仅出现既有 Pydantic v2 class Config deprecation warnings。
- `ruff check` 通过；仅出现既有 top-level ruff config deprecation warning。
- `compileall`、`make deps-check`、`git diff --check` 均通过。

### Git 收口

- E6 实现提交：`92f4176 enterprise(e6): add sandbox safe sql demo`。
- E6 安全硬化提交：`c72f105 enterprise(e6): enforce sql timeout and result cap`。
- 本记录、`PROJECT_STATE.md`、`task_plan.md`、`progress.md`、`findings.md` 和 `docs/database_operation_capability_plan.md` 的状态同步由后续收口提交承载。

### 如何在项目评审中解释

如果被问：“为什么 E6 不直接接真实数据库？”

答：E6 的目标是证明数据库查询能力可控，不是开放企业库访问。真实库接入需要更完整的 DB Gateway、PermissionService 策略、审计查询和运维边界。当前实现只接本地 sandbox SQLite，并且 database tools 默认不进入 AIOps/RAG 工具池。

如果被问：“为什么需要 AST allowlist，而不是正则过滤 SQL？”

答：LLM 会生成整段 SQL，正则很难可靠区分嵌套、别名、函数、join 或多语句。`SafeSqlKernel` 先解析 AST，再限制 statement type、table、column 和 expression 类型；解析失败或结构未知时默认拒绝，这是更适合 server-side tool 的安全边界。

## 2026-05-30：E7 DB Gateway 集成

### 为什么现在做

E6 已经证明 sandbox read-only 数据库查询能力可控，但它仍然是一个显式 demo provider。E7 的目标是把 E6 的三个数据库工具接入 E4 `ToolGateway` 的治理边界，让工具可见性、表权限、列权限和审计查询都由企业权限层控制，同时不改变 `SafeSqlKernel` 的 SQL 安全核心。

本轮仍然不接真实业务库，不支持写操作，也不把 database tools 加进默认 AIOps/RAG MCP 工具池。

### 参考来源

- `data-api-builder`：参考 database resource / field-level exposure 形态，把表、列当成显式资源边界。
- `pycasbin`：参考 resource-level 权限和 deny-overrides 思路；本项目仍复用 E3 的本地 `PermissionService`，不新增 pycasbin runtime。
- `open-webui`：参考 server-side tool 可见性过滤和审计边界，工具是否可见必须在服务端判断。

### 代码级变更

- 新增 `app/enterprise/database/permissions.py`：`DatabasePermissionFilter` 定义 `database_table` / `database_column` 两类资源和 `read` action。表资源 ID 形如 `sandbox_sales.orders`，列资源 ID 形如 `sandbox_sales.orders.order_id`。
- `DatabasePermissionFilter.select_target(...)` 只解析已知 `SELECT` 的目标表列，用于权限判断；未知、复杂或非法 SQL 仍交给 `SafeSqlKernel` 原有安全逻辑阻断。
- 新增 `app/enterprise/database/audit.py`：`DatabaseAuditQueryService` 可按 `trace_id`、`user_id`、`table_name` 查询 `database_query` audit events。
- 修改 `app/enterprise/database/provider.py`：`DatabaseDemoToolProvider` 可选接入 `PermissionService`。接入后：
  - `list_tables` 只返回当前用户有 `database_table` 读权限的表。
  - `describe_table` 要求表权限，并按 `database_column` 权限过滤列。
  - `safe_select` 在进入 `SafeSqlKernel` 前先检查目标表列权限。
  - 表/列拒绝会写 `database_query` audit，然后抛出 `SafeSqlBlocked("database_table_denied")` 或 `SafeSqlBlocked("database_column_denied")`。
- 修改 `app/enterprise/tools/gateway.py` 和 `app/enterprise/tools/registry.py`：不再靠静态 `include_database_tools` 隐藏 database tools；显式 database-demo session 中的 DB tool 可见性改由 `PermissionService` 的 tool grants 和数据库表列 grants 控制。
- 新增 `tests/test_enterprise_database_e7.py`：覆盖权限级 DB tool 可见性、table/column 权限过滤、DB audit 查询，以及授权后 DML 仍由 `SafeSqlKernel` 阻断。

### 风险和处理

- 风险：database tools 因取消 config-level hiding 而进入默认 AIOps/RAG 工具池。处理：默认 AIOps/RAG 路径仍不挂 `DatabaseDemoToolProvider`；显式 database-demo session 即使挂了 provider，也必须有 `tool` grant 才可见。
- 风险：权限层误接管 SQL 安全。处理：权限层只检查已知 SELECT 的表列访问，SQL 结构安全仍由 `SafeSqlKernel` 判断；DML/DDL/多语句等路径没有在权限层放行。
- 风险：审计查询变成新的宽口数据接口。处理：`DatabaseAuditQueryService` 只过滤已存在的 `database_query` 事件，按 trace/user/table 做读路径，不引入新的生产数据库依赖。

### 验证

已运行：

```text
.venv/bin/python -m pytest -q tests/test_enterprise_database_e6.py tests/test_enterprise_database_e7.py tests/test_enterprise_tool_gateway.py tests/test_enterprise_permissions.py
.venv/bin/python -m ruff check app/enterprise/database app/enterprise/tools app/enterprise/permissions tests/test_enterprise_database_e6.py tests/test_enterprise_database_e7.py tests/test_enterprise_tool_gateway.py
.venv/bin/python -m pytest -q tests/test_enterprise_auth.py tests/test_enterprise_request_context.py tests/test_enterprise_request_gateway.py tests/test_enterprise_gateway_routes.py tests/test_enterprise_permissions.py tests/test_enterprise_tool_gateway.py tests/test_enterprise_model_gateway.py tests/test_enterprise_rag_upload_e5.py tests/test_enterprise_database_e6.py tests/test_enterprise_database_e7.py
.venv/bin/python -m compileall -q app tests
make deps-check
git diff --check
```

结果：

- E1/E3/E4/E6/E7 targeted tests 31/31 通过。
- E1-E7 targeted bundle 55/55 通过；仅出现既有 Pydantic v2 class Config deprecation warnings。
- `ruff check` 通过；仅出现既有 top-level ruff config deprecation warning。
- `compileall`、`make deps-check`、`git diff --check` 均通过。

### Git 收口

- E7 实现提交：`2554343ac123fe5bcea65cb9604d49aaa3c2d708` (`enterprise(e7): gate database tools by permissions`)。
- E7 状态收口提交由本记录、`PROJECT_STATE.md`、`task_plan.md`、`progress.md`、`findings.md` 和 `docs/database_operation_capability_plan.md` 承载。

### 如何在项目评审中解释

如果被问：“为什么 E7 要把 database-demo 从配置隐藏改成权限控制？”

答：配置隐藏只能回答“这个 session 有没有挂 DB provider”，不能回答“这个用户能不能看到哪个表、哪几列”。E7 把工具可见性接到 E3 `PermissionService`，再把数据库资源拆成 table/column 两层 grant，这样显式 database-demo session 里也能按用户权限收敛。

如果被问：“E7 会不会削弱 E6 的 SQL 安全？”

答：不会。E7 没有改 `SafeSqlKernel` 核心逻辑，权限层只在进入 kernel 前做表列授权检查。即使用户拥有 tool/table/column grant，DML、DDL、多语句和其它危险结构仍由 `SafeSqlKernel` 按 E6 规则阻断。

## 2026-05-30：E8 Admin/API 最小管理面

### 为什么现在做

E7 已经把 DB demo session、工具可见性、表列权限和 DB audit 查询接到企业权限层。E8 的目标不是再扩权，而是补一个最小管理面：让 admin 能在服务端管理本地用户、角色、grant 和 audit 查询，同时不接 LDAP / CAS / UI，也不把 admin 做成资源权限的隐式 bypass。

本轮继续保持本地实现，不引入外部身份源，不改 E3 `PermissionService` 的默认 deny 语义，也不碰 `docs/enterprise_assistant_development_plan.md` 的阶段定义。

### 参考来源

按计划参考了：

- `full-stack-fastapi-template/backend/app/api/deps.py`
- `full-stack-fastapi-template/backend/app/api/routes/users.py`
- `open-webui/backend/open_webui/utils/auth.py`

结论：

- 用 server-side dependency 做 admin role 保护，比把判断放在前端或路由分支里更稳。
- 用户/角色 CRUD 只需要最小路由面，不需要先接完整 IAM / RBAC UI。
- 管理操作要写 audit，查询也要走明确过滤，不要把管理面变成宽口日志 dump。

### 代码级变更

`app/enterprise/auth/models.py` / `app/enterprise/auth/service.py`：

- `UserProfile` 新增 `is_active`。
- `AuthService` 增加 `reset_users()`、`list_users()`、`create_user()`、`update_user()`、`disable_user()`。
- `authenticate()` 和 `validate_access_token()` 都会拒绝禁用用户。

`app/enterprise/admin/models.py`：

- 新增 `AdminUserCreateRequest`、`AdminUserUpdateRequest`、`RoleRecord`、`RoleCreateRequest`、`RoleUpdateRequest`、`GrantCreateRequest`。
- `success_payload()` 复用项目现有 `code/message/data` 包装方式。

`app/enterprise/admin/service.py` / `app/enterprise/admin/routes.py`：

- 新增 `AdminService` 和 `require_admin_user()`。
- 路由提供用户 list/create/update/disable，角色 list/create/update/delete，grant list/create/revoke，audit query。
- admin 操作统一写 `admin_operation` audit。
- 非 admin 用户进入 `/api/admin/*` 返回 403。

`app/enterprise/observability/audit_service.py` / `app/enterprise/permissions/repository.py`：

- `SQLiteAuditSink.query()` 支持按 `trace_id` / `user_id` / `event_type` / `start_time` / `end_time` 查询默认本地审计库。
- `InMemoryGovernanceRepository.list_all_grants()` 支持 grant 列表过滤。

`app/main.py`：

- 挂载 `/api/admin/*` 到主应用。

`tests/test_enterprise_admin_e8.py`：

- 覆盖非 admin 403。
- 覆盖 admin 的用户、角色、grant CRUD。
- 覆盖禁用用户无法再次登录。
- 覆盖 in-memory 和 SQLite audit query 过滤。

### 验证

已运行：

```text
.venv/bin/python -m pytest -q tests/test_enterprise_admin_e8.py
.venv/bin/python -m pytest -q tests/test_enterprise_auth.py tests/test_enterprise_request_context.py tests/test_enterprise_request_gateway.py tests/test_enterprise_gateway_routes.py tests/test_enterprise_permissions.py tests/test_enterprise_tool_gateway.py tests/test_enterprise_model_gateway.py tests/test_enterprise_rag_upload_e5.py tests/test_enterprise_database_e6.py tests/test_enterprise_database_e7.py tests/test_enterprise_admin_e8.py
.venv/bin/python -m ruff check app/enterprise/admin app/enterprise/auth app/enterprise/permissions app/enterprise/observability tests/test_enterprise_admin_e8.py app/main.py
.venv/bin/python -m compileall -q app tests
make deps-check
git diff --check
```

结果：

- E8 targeted tests：6/6 通过。
- E1-E8 targeted bundle：61/61 通过。
- targeted `ruff check`、`compileall`、`make deps-check` 和 `git diff --check` 通过。

### 风险和处理

- 风险：admin 变成隐式资源 bypass。处理：admin 只保护管理 API，本身不绕过 `PermissionService` 的资源授权。
- 风险：audit query 变成宽口日志接口。处理：`SQLiteAuditSink.query()` 只做明确过滤，不暴露原始库结构。
- 风险：用户禁用后仍可继续用 token。处理：`validate_access_token()` 也检查 `is_active`，不是只挡登录入口。

### 阶段收口

- E8 实现提交：`f9c1f03` (`enterprise(e8): add admin management api`)。
- 本记录、`PROJECT_STATE.md`、`task_plan.md`、`progress.md`、`findings.md` 的状态同步由后续收口提交承载。

### 如何在项目评审中解释

如果被问：“为什么 E8 没有直接接 LDAP / CAS？”

答：E8 是最小管理面，目标是先证明管理 API 的 server-side admin protection、操作审计和本地授权管理形态。真实 LDAP / CAS 会改变身份源和生命周期语义，应在当前管理面稳定后单独接入。

如果被问：“admin 是不是能绕过所有权限？”

答：不是。admin role 只保护 `/api/admin/*` 管理端点；工具、文档、模型和数据库表列资源仍然走 `PermissionService` 的显式 grant。这样可以管理授权，但不会把 admin 变成业务资源的隐式 allow。

## 2026-05-30：E9 Observability / Eval 总验收

### 为什么现在做

E0-E8 已经分别落地身份、RequestGateway、权限、工具/模型网关、RAG/upload 治理、DB sandbox、DB Gateway 和 admin API。E9 的目标不是新增业务能力，而是把这些能力的 trace、SSE contract 和失败层定位做成自动化验收面，防止 E11 前端展示阶段才发现后端事件格式不统一或失败无法归因。

本轮保持最小实现：不接 Langfuse 服务端，不做性能压测，不重写旧 RAG/AIOps 业务链路，只补 observability helper、SSE envelope 归一化和验收报告。

### 参考来源

按计划参考：

- `langfuse` 的 trace / observation 字段组织。
- 当前 repo 的 eval scripts / report 组织方式。
- 现有 `AuditEvent`、`RequestGateway`、`PermissionService`、`ToolGateway`、`ModelGateway`、DB audit 事件。

结论：

- 不需要改 `AuditEvent` schema；E9 可以在验收层归一出 `TraceObservation`。
- SSE 协议应保持 legacy `type` 兼容，同时补齐 `stage/status/message/data`，让 Vue3 后续只做消费者。
- 失败层定位应由 audit event type / route / decision / reason / error_class 推导，而不是要求每个业务模块重复写一套 layer 字段。

### 代码级变更

`app/enterprise/observability/sse_contract.py`：

- 新增 `REQUIRED_SSE_FIELDS`。
- 新增 `normalize_sse_event()`，把 legacy chat / aiops event 归一到 `type/trace_id/request_id/stage/status/message/data`。
- 新增 `check_sse_contract()`，用于 route smoke 和 E9 report。

`app/api/chat.py` / `app/api/aiops.py`：

- SSE 序列化层统一调用 `normalize_sse_event()`。
- 正常事件复用 adapter 注入的 `trace_id` / `request_id`。
- route 层异常事件也补齐 fallback trace / request id，避免 error event 缺 envelope 字段。

`app/enterprise/observability/trace_eval.py`：

- 新增 `TraceObservation`，固化 `layer/module/decision/reason/latency_ms/status`。
- 新增 `check_trace_completeness()`，要求同一 trace 至少有 `request_started` 和 terminal event。
- 新增 `localize_failure()`，把 auth、guardrail、permission、tool/model、RAG/domain、DB 和 event-contract 问题映射到 L1-L6。
- 新增 `build_e9_observability_report()`，汇总 positive smokes、negative localizations 和 SSE contract checks。

`tests/test_enterprise_observability_e9.py`：

- 覆盖 legacy chat / aiops event 归一化。
- 覆盖 `/api/chat_stream` 和 `/api/aiops` route SSE 事件协议完整性。
- 覆盖 chat / aiops / database 三条正向 smoke trace 归一化。
- 覆盖 missing terminal trace issue。
- 覆盖 guardrail、permission、tool、model、database 失败层定位。
- 覆盖 SSE contract 缺字段时 E9 report 定位到 `L6 Observability / Event Contract`。

`docs/enterprise_sse_event_contract.md` / `docs/enterprise_e9_observability_eval_report.md`：

- SSE 协议状态从 E2 draft 更新为 E9 frozen baseline。
- 新增 E9 验收报告，记录 trace 字段、失败层映射、SSE contract 和验证命令。

### 验证

已运行：

```text
.venv/bin/python -m pytest -q tests/test_enterprise_observability_e9.py
.venv/bin/python -m pytest -q tests/test_enterprise_auth.py tests/test_enterprise_request_context.py tests/test_enterprise_request_gateway.py tests/test_enterprise_gateway_routes.py tests/test_enterprise_permissions.py tests/test_enterprise_tool_gateway.py tests/test_enterprise_model_gateway.py tests/test_enterprise_rag_upload_e5.py tests/test_enterprise_database_e6.py tests/test_enterprise_database_e7.py tests/test_enterprise_admin_e8.py tests/test_enterprise_observability_e9.py
.venv/bin/python -m ruff check app/enterprise/observability app/api/chat.py app/api/aiops.py tests/test_enterprise_observability_e9.py
.venv/bin/python -m compileall -q app tests
make deps-check
```

结果：

- E9 targeted tests：6/6 通过。
- E1-E9 targeted bundle：67/67 通过；仅出现既有 Pydantic v2 class Config deprecation warnings。
- targeted `ruff check` 通过；仅有 repo 既有 top-level ruff config deprecation warning。
- `compileall` 通过。
- `make deps-check` 通过。

### 风险和处理

- 风险：为了 E9 把所有 audit event schema 改一遍。处理：保留 `AuditEvent`，只在验收层归一 `TraceObservation`。
- 风险：SSE 改动破坏旧前端。处理：继续保留 legacy `type`，只补齐 envelope 字段。
- 风险：E9 把 DB 工具引入默认工具池。处理：本轮不改 tool provider 挂载；DB 仍由 explicit database-demo + PermissionService grants 控制。

### 阶段收口

- E9 实现提交：`e010f8a` (`enterprise(e9): add observability eval checks`)。
- 本记录、`PROJECT_STATE.md`、`task_plan.md`、`progress.md`、`findings.md` 和 `docs/enterprise_e9_observability_eval_report.md` 共同承载 E9 closeout。

### 如何在项目评审中解释

如果被问：“为什么 E9 不直接接 Langfuse？”

答：E9 的目标是证明本项目已经有可解释 trace 和失败定位，不是引入外部观测平台。当前 `AuditEvent` 已经包含 trace/request/user/decision/reason/error/latency/metadata，E9 在本地归一出 `TraceObservation` 并用 targeted tests 锁住字段。后续如果接 Langfuse，可以把这些字段映射出去，而不是先把运行依赖复杂化。

如果被问：“为什么 SSE 继续保留 legacy type？”

答：现有 `static/app.js` 和 route 测试已经消费 `content`、`done`、`plan`、`report` 等 legacy type。E9 的风险在字段不完整，而不是 type 名字本身。保留 legacy type 并补齐 `stage/status/message/data`，可以兼容旧消费者，也让 Vue3 后续按统一 envelope 展示。

## 2026-05-30：E0 架构基线与依赖可复现

### 为什么现在做

用户要求按 `docs/enterprise_assistant_development_plan.md` 开始推进。该计划把 E0 定为 Gateway / 权限 / DB sandbox 之前的共同底座：先保证依赖可复现、安装入口不绕过锁文件，否则后续 E1-E9 的测试和 smoke 会被环境漂移污染。

本轮只做 E0，不进入 E1 身份、E2 RequestGateway 或 E6 数据库能力。

### 参考来源

已按参考优先原则读取：

- `/Users/cici/oncall agent/reference_repos/README.md` 的 E0 映射。
- `/Users/cici/oncall agent/reference_repos/full-stack-fastapi-template/README.md` 的项目环境 / 配置说明形态。

结论：本轮只借鉴成熟项目的“依赖和环境入口必须明确”的组织原则，不复制代码。

### 代码级变更

`Makefile`：

- `install` 从 `pip install -r requirements.txt 2>/dev/null || pip install -e .` 改为 `uv sync --frozen`。
- `install-dev` 从 `pip install -e ".[dev]" 2>/dev/null || pip install -e .` 改为 `uv sync --frozen --all-extras`。
- `sync` 从 `pip install -e . --upgrade` 改为 `uv sync --frozen --all-extras`。
- `add` / `add-dev` / `remove` 改为 `uv add` / `uv add --optional dev` / `uv remove`，避免依赖管理绕过 `uv.lock`，并保持开发依赖仍写入现有 `dev` optional extra。
- 新增 `deps-check`：`uv lock --check` + `uv run pip check`。
- `check-all` 先运行 `deps-check`，再执行格式化、lint 和测试。

`pyproject.toml`：

- 给 LangChain / LangGraph 系列、DashScope / OpenAI、Milvus、FastMCP、Redis、RQ 增加主版本上限。
- LangChain / LangGraph 上限按当前 `uv.lock` 版本选择：1.x 包使用 `<2.0.0`，0.x 周边包使用 `<1.0.0`。
- `openai` 使用 `<3.0.0`，`pymilvus` 使用 `<3.0.0`，`redis` 使用 `<8.0.0`。
- `rq` 一开始误设为 `<2.0.0`，`uv lock` 立即把 RQ 从 2.x 降到 1.16.2；按“依据当前 lock 主版本”规则修正为 `<3.0.0`，并用 `uv lock --upgrade-package rq` 恢复到 2.x。

`README.md`：

- 安装说明改为 `uv sync --frozen` / `uv sync --frozen --all-extras`。
- 明确 `uv.lock` 是唯一锁源。
- Windows pip 路径保留为无法使用 uv 的兜底路径，不作为默认安装方式。

### 风险和处理

- 风险：过窄上限会引入无关降级。处理：用 `uv.lock` 当前解析版本作为窗口依据；`rq` 误降级被当场修正。
- 风险：`make clean` 会删除本地 `server.log` / MCP 日志 / pid 文件。处理：不运行 `make clean`，改用安装目标、依赖检查和 import smoke 验证 E0。
- 风险：E0 过早进入业务重构。处理：本轮未改 `app/*` 运行时代码，也未创建 `app/enterprise/*`。

### 验证

已运行：

```text
uv lock --check
make deps-check
make install
make install-dev
make deps-check
uv run python -c "import app; print('OK')"
make -n add-dev PKG=pytest-xdist
```

结果：

- `uv lock --check` 通过。
- `uv run pip check` 返回 `No broken requirements found.`。
- `make install` / `make install-dev` 都成功。
- `import app` 返回 `OK`。
- `make -n add-dev PKG=pytest-xdist` 输出 `uv add --optional dev pytest-xdist`，确认开发依赖仍进入现有 optional extra。

未运行：

- `make clean`。原因：会删除本地日志和 pid 文件，和本轮 E0 目标无直接关系。
- 全量业务测试。原因：本轮没有改 Python 运行时代码；后续 E1 开始新增企业模块时再按 targeted tests 执行。

### 如何在项目评审中解释

如果被问：“为什么先改安装和锁文件，而不是直接写 Gateway？”

答：Gateway / Permission / DB 都会引入安全边界和跨模块测试。如果依赖安装仍然允许 pip fallback 或浮动升级，后面任何失败都可能是环境漂移而不是模块设计问题。E0 先把 `uv.lock` 固定成唯一安装基线，并把检查入口放进 `Makefile`，这样 E1 之后的失败才更容易定位到具体层。

如果被问：“为什么 `rq` 设 `<3.0.0` 而不是 `<2.0.0`？”

答：E0 的规则不是凭印象写上限，而是读当前 `uv.lock`。当前锁定的 RQ 是 2.x；写 `<2.0.0` 会造成无关降级，已经被 `uv lock` 暴露并修正。正确做法是保持当前主版本窗口 `<3.0.0`。

## 2026-05-30：成熟项目做法二次复核与数据库计划修正

### 为什么现在做

Memory 和 RAG 已冻结，AIOps MCP tool discovery cache 已完成并通过 P6 full eval rerun。后续候选方向集中到三个待办：

1. 数据库操作能力。
2. 项目与成熟项目做法差距。
3. 企业级 Agent Gateway V1。

用户要求再次搜索成熟项目相关资料，审视这三个待办是否符合成熟工程做法，尤其确认数据库操作能力计划是否安全可执行。

### 复核资料

本轮优先使用官方文档和成熟项目文档：

- MCP tools specification。
- OWASP MCP Security Cheat Sheet。
- OWASP SQL Injection Prevention Cheat Sheet。
- LangChain SQL Agent 文档。
- Microsoft Data API Builder SQL database MCP 文档。
- Open WebUI RBAC / Hardening 文档。
- LiteLLM Proxy 文档。
- Langfuse tracing 文档。
- LangGraph persistence、LangChain CrossEncoderReranker、Milvus Performance FAQ 作为成熟项目差距 backlog 的辅助核验资料。

### 本项目代码事实

当前默认 MCP 配置位于 `app/config.py::mcp_servers`，只包含：

```text
cls
monitor
```

当前 AIOps executor 位于 `app/agent/aiops/executor.py::executor()`，工具暴露路径是：

```text
local_tools = [get_current_time, retrieve_knowledge]
mcp_tools = await get_mcp_tools_with_retry()
all_tools = local_tools + mcp_tools
llm_with_tools = llm.bind_tools(all_tools)
tool_node = ToolNode(all_tools)
```

这意味着只要把 database server 加进默认 `mcp_servers`，AIOps executor 默认就能看到数据库工具。当前项目还没有 `RequestGateway`、`ToolGateway`、`PermissionService` 和企业级审计底座，因此原数据库计划中“在 `app/config.py` 增加 database MCP server”这个路径风险过高。

### 发现的问题

旧版 `docs/database_operation_capability_plan.md` 的主要问题：

- P0 计划直接把 database MCP server 注册到全局 `config.mcp_servers`。
- 把 reference database MCP server 描述得过于接近可直接生产使用。
- SQL 注入防护主要写成参数化查询，没有把 LLM 生成整段 SQL 的 AST / allowlist 校验列为硬要求。
- 审计日志默认落 Gateway MySQL，但 Gateway 治理库尚未实现。
- 写操作阶段推进过早，只写“用户确认”，缺少 dry-run、影响行预览、before/after diff、审批 token、事务和回滚。

### 修正动作

已重写 `docs/database_operation_capability_plan.md`：

- 将 P0 拆成 DB-P0a sandbox read-only DB MCP 和 DB-P0b safe SQL kernel。
- 明确 database tools 默认关闭，不进入全局 MCP tool pool。
- 明确 P0 不接真实业务库、不做写操作、不依赖 Gateway MySQL 审计。
- `safe_select` 必须使用 SQL AST / allowlist 校验，只允许单条 SELECT。
- 增加 Schema Registry、敏感字段脱敏、强制 LIMIT、timeout、最大结果大小、本地审计。
- 将企业真实只读库放到 DB-P2，写操作放到 DB-P3。
- 明确 DB-P1 依赖 Gateway-MVP 的 current_user、trace_id、RequestGateway audit shell、ToolGateway allowlist/filter、PermissionService。

已更新 `docs/mature_project_practice_review_20260530.md`：

- 增加二次复核记录。
- 补充 OWASP MCP Security、Microsoft Data API Builder SQL database MCP、Langfuse tracing 等来源对本项目的约束。
- 明确三个待办的最终判断和执行顺序。

### 三个待办的最终判断

| 待办 | 判断 | 下一步 |
|---|---|---|
| 数据库操作能力 | 方向正确，但必须按高风险工具处理 | 只能执行修正版 DB-P0a/P0b 或先做 Gateway-MVP |
| 项目与成熟项目做法差距 | 符合成熟项目做法 | 保持为 backlog 入口，不改默认行为 |
| Enterprise Agent Gateway V1 | 方向符合成熟治理形态 | 执行时先做 Gateway-MVP，不一次性展开完整大工程 |

### 如何在项目评审中解释

如果被问：“为什么不能直接接一个 Postgres MCP server？”

答：因为本项目当前 executor 会把默认 MCP tools 全部合进 `all_tools` 并绑定给 LLM。一旦把数据库 server 加进全局配置，数据库工具就会被默认暴露给 AIOps executor。成熟项目对 server-side tools 的要求是 least privilege、tool allowlist、权限过滤、审计和敏感操作保护。当前 Gateway/ToolGateway/PermissionService 尚未落地，所以第一步只能做 sandbox read-only，且默认关闭。

如果被问：“为什么参数化查询不够？”

答：参数化查询解决的是值参数注入问题，但 LLM 场景里模型可能生成整段 SQL。整段 SQL 的结构需要 AST / allowlist 校验，至少要确认只有单条 SELECT、目标表/列在 allowlist 内、没有 DML/DDL/权限操作、多语句和危险函数。

如果被问：“为什么不先做写操作？”

答：数据库写操作需要审批、dry-run、影响行预览、before/after diff、审批 token、事务和 rollback，并且要区分操作人和审批人。没有这些治理能力，写操作风险不可控。成熟项目会把这类能力放在只读稳定和治理底座完成之后。

### 验证

本轮是设计文档和计划修正，没有改运行时代码。

已完成的验证：

- 读取本地 `AGENTS.md`。
- 用 CodeGraph 确认 `app/config.py::mcp_servers` 只包含 `cls` / `monitor`。
- 用 CodeGraph 确认 `app/agent/aiops/executor.py::executor()` 会把 `mcp_tools` 合入 `all_tools`。
- 对照外部官方资料复核三个待办计划。

未运行：

- 单元测试。原因：本轮未改 Python 代码。
- P6/RAG eval。原因：本轮只修正文档计划，不改变业务逻辑。

## 2026-05-30：企业助手统一计划与分层架构审视

### 为什么现在做

三个企业助手相关文件已经存在：

1. `docs/superpowers/specs/2026-05-26-enterprise-agent-gateway-v1-design.md`
2. `docs/database_operation_capability_plan.md`
3. `docs/项目与成熟项目做法差距.md`

但它们分别负责 Gateway、数据库能力、成熟化 backlog，缺少一个统一入口来说明：

- 哪一层先做；
- 每层有哪些模块；
- 哪些模块必须可插拔；
- 每一步怎么验收；
- 出问题时如何定位到具体层和模块。

用户明确提出架构思想：项目要分层，每层有模块，模块要可插拔，这样才能验证到底哪个模块或功能出问题。

### 审视结论

`Enterprise Agent Gateway V1` 方向正确，但范围过大，应先做 Gateway-MVP。它符合分层思想，因为它已经拆出 Identity、RequestGateway、PermissionService、ToolGateway、ModelGateway、AuditService 等边界；问题是执行必须小步验证，不能一次性铺开。

`database_operation_capability_plan` 修正版符合分层思想。数据库能力被放在 Domain Capability 层，必须先通过 ToolGateway / PermissionService / AuditService 治理后才能接真实库。DB-P0a/P0b 可以作为 sandbox demo 先做，但必须默认关闭、不进全局工具池。

`项目与成熟项目做法差距` 符合成熟化 backlog 定位，但它不是企业助手主计划。它应放在 Production Readiness Backlog 层，只在触发条件成立时执行。

### 新增文件

新增 `docs/enterprise_assistant_development_plan.md`。

这个文件定义了企业助手统一分层：

```text
L0 Runtime / Dependency / Config
  -> L1 Identity / RequestContext
  -> L2 RequestGateway / Governance
  -> L3 Permission / Registry
  -> L4 Capability Gateways
  -> L5 Domain Capabilities
  -> L6 Observability / Eval
  -> L7 Production Readiness Backlog
```

同时定义了执行阶段：

```text
E0 架构基线与依赖可复现
  -> E1 Gateway-MVP: Identity + RequestContext + trace_id
  -> E2 RequestGateway + Audit shell
  -> E3 PermissionService + Registry MVP
  -> E4 ToolGateway + ModelGateway MVP
  -> E5 RAG/Upload 权限过滤和 StorageService 边界
  -> E6 DB-P0a/P0b sandbox read-only + safe SQL kernel
  -> E7 DB-P1 Gateway 集成
  -> E8 Admin/API 最小管理面
  -> E9 Observability/Eval 总验收
  -> E10 Runtime/RAG/AIOps 成熟化 backlog 按触发条件执行
```

### 关键架构决策

- 企业能力新增代码后续优先放入 `app/enterprise/*`，不继续把新能力堆进 `app/services` 根目录。
- 不迁移旧 RAG/AIOps 服务，先通过 adapter 包裹旧链路，避免目录级重构。
- `ToolGateway`、`ModelGateway`、`StorageService`、`PermissionService`、`AuditService` 必须有可替换 provider/sink/registry 边界。
- 每个阶段都必须能通过 trace 定位失败层，例如 `auth_failed`、`permission_denied`、`tool_not_visible`、`sql_blocked`、`model_fallback_used`。
- 数据库能力真实接入前必须先完成 Gateway-MVP；sandbox DB demo 是唯一例外，但必须默认关闭。

### 验证

本轮是计划文档新增，没有改运行时代码。

已完成：

- 读取三个现有计划。
- 用 CodeGraph 查看当前 `app` 结构，确认现有服务仍主要集中在 `app/services`。
- 新增统一计划并写入每阶段验收标准。

未运行：

- 单元测试。原因：未改 Python 代码。
- E2E smoke。原因：本轮只做计划总控文件。

## 2026-05-30：参考仓库索引与参考优先原则

### 为什么现在做

用户明确要求：开发过程中的代码尽量参考或复制成熟项目怎么写的，不希望 AI 自己完全决定写法。为了让这条规则可执行，需要把可参考仓库整理成一个索引，并把“何时参考、参考什么”写入统一计划。

### 已整理的参考源

`/Users/cici/oncall agent/reference_repos/` 下现有内容：

- `WeKnora` -> symlink
- `TencentDB-Agent-Memory` -> symlink
- `modelcontextprotocol-python-sdk`
- `modelcontextprotocol-servers`
- `sqlglot`
- `full-stack-fastapi-template`
- `fastapi-users`
- `pycasbin`
- `litellm`
- `langfuse`
- `open-webui`
- `bifrost`
- `dify`
- `data-api-builder`

并新增索引文件：

- `/Users/cici/oncall agent/reference_repos/README.md`

### 计划更新

已更新 `docs/enterprise_assistant_development_plan.md`：

- 增加参考优先原则：先查 `reference_repos/`，再写代码。
- 明确允许复制的是小段、许可证兼容、直接贴合任务的代码形态。
- 明确不复制 `ee/`、品牌受限或许可证不兼容代码。
- 增加阶段级参考映射：
  - E1 参考 `fastapi-users` / `full-stack-fastapi-template`
  - E2 参考 `langfuse` / `open-webui`
  - E3 参考 `pycasbin` / `open-webui`
  - E4 参考 `litellm` / `bifrost` / `modelcontextprotocol-python-sdk`
  - E5 参考 `WeKnora` / `dify`
  - E6 参考 `modelcontextprotocol-servers` / `sqlglot` / `data-api-builder`
  - E7 参考 `data-api-builder` / `pycasbin` / `open-webui`

### 开发时的使用方式

后续写任何企业能力代码前，先按阶段打开对应仓库，优先看：

- 模块边界。
- 测试。
- 配置。
- 错误处理。
- 数据模型。

如果要复制代码，必须在 `docs/enterprise_capability_development_record.md` 写明：

- 参考了哪个仓库。
- 参考了哪个文件。
- 复制了哪一小段。
- 没复制什么。
- 为什么这样取舍。

## 2026-05-30：补充不过度前置重构原则

### 为什么现在补

用户进一步确认：新企业能力应该走新分层，旧服务通过 adapter 包裹，不应该在 Gateway V1 前先做全量 `app/services` 目录重组、全局 Repository 抽象或旧模块单例批量替换。

### 修正内容

已更新 `docs/enterprise_assistant_development_plan.md`：

- 增加“不做过度前置重构”原则。
- 明确 E1-E4 新能力放入 `app/enterprise/*`。
- 明确 E5 通过 `app/enterprise/adapters/*` 包裹旧 RAG/AIOps 服务。
- 明确新治理数据可以有 repository，但不改造旧 SQLite/RAG/Memory 数据访问。
- 明确新企业模块可以用 `container.py` / provider 工厂管理依赖，但不批量替换旧模块级单例。
- 增加旧服务局部整理的触发条件：import 循环、测试困难、协作冲突、onboarding 卡住、Gateway adapter 接入后无法验收。

### 当前结论

如果继续企业助手方向，先做：

```text
E0 依赖可复现性
  -> E1-E4 app/enterprise/* 新分层
  -> E5 adapter 包裹旧 RAG/AIOps
```

暂缓：

```text
旧 app/services 全量重组
全局 Repository 抽象
旧模块单例批量替换
```

这些只有在触发条件成立时才做。

## 2026-05-30：补充统一计划执行细节

### 为什么现在补

用户审阅 `docs/enterprise_assistant_development_plan.md` 后确认整体方向可用，但指出三个不足：

1. E0 依赖可复现性的具体执行步骤不够细。
2. E1-E9 缺少工作量估算。
3. Adapter 模式只有目录建议，没有代码形态示例。

### 修正动作

已更新 `docs/enterprise_assistant_development_plan.md`：

- 在第 6 节增加阶段工作量估算表。
- 在 E0 增加 7 步具体执行清单：
  - 校验 `uv.lock`。
  - 修改 `Makefile` 安装入口为 `uv sync --frozen`。
  - 给高风险依赖增加主版本上限。
  - 重新执行 `uv lock`。
  - 运行 `make clean` / `make install-dev` / `pip check` / `python -c "import app"`。
  - 增加 `deps-check`。
  - 同步项目状态文档和 record。
- 在第 7 节增加 `RagAdapter` 示例，展示 `RequestContext`、`PermissionService`、`ToolGateway`、`AuditService` 如何包裹旧 `RagAgentService`。

### 保留边界

本次只增强计划可执行性，不改变总原则：

- 不在 E0 做 Gateway 代码。
- 不在 E0 做旧服务目录重组。
- 不新增 `requirements.lock.txt` 作为第二锁源。
- Adapter 示例是边界示例，不代表立即改旧 `RagAgentService` 签名。

## 2026-05-30：企业助手计划再修订

### 为什么现在做

用户对 `docs/enterprise_assistant_development_plan.md` 的最后一轮审阅指出：

1. E1-E9 的顺序过于线性，应该把治理主干和 DB sandbox 拆成可并行分支。
2. 计划缺少中间里程碑，太晚才能看到可演示结果。
3. Adapter 边界需要明确是 MVP 正式边界，还是临时过渡层。
4. 风险和长期运行问题需要前置写入计划，而不是只放在口头讨论里。

### 修正动作

已更新 `docs/enterprise_assistant_development_plan.md`：

- 把 E0-E2 之后的执行顺序改成治理主干分支（E3-E5）+ DB sandbox 分支（E6）并行。
- 新增 M1-M4 中间里程碑，分别覆盖 login/trace/audit、权限 + gateway、sandbox DB、完整 E2E 闭环。
- 明确 Adapter 在 E0-E9 期间是正式接入边界；是否收敛为后续任务，等 E9 后根据厚度和验收结果判断。
- 新增开发风险与缓解、长期运行问题与解决方案两节，把权限模型、RequestContext、缓存、MySQL/SQLite 边界、Adapter 不匹配、SQL parser 选型、audit 失败、工具同步、Schema 变更和异步 trace 丢失写成可执行条款。

### 当前结论

这次修订没有改变总路线，仍然是：

```text
E0 -> E1 -> E2
   -> Branch A: E3 -> E4 -> E5
   -> Branch B: E6
   -> E7 -> E8 -> E9 -> E10
```

只是把“如何并行、何时演示、长期怎么兜底”写清楚了，避免后续开发时重新口头补规则。

## 2026-05-30：E1 Gateway-MVP Identity / RequestContext

### 为什么现在做

E0 已经把 `uv.lock`、安装入口和依赖检查固定下来。E1 是后续 E2 RequestGateway、E3 PermissionService、E4 ToolGateway、E6/E7 DB 能力共同需要的身份上下文底座：每个企业请求必须能拿到 `user_id`、`department_id`、`roles` 和 `trace_id`，并且未登录访问必须先被阻断。

本轮只做 E1，不接真实 CAS/LDAP，不接 MySQL/Redis，不引入数据库工具，也不移动旧 RAG / AIOps 服务。

### 参考来源

已按 `docs/enterprise_assistant_development_plan.md` 的 E1 参考矩阵读取：

- `/Users/cici/oncall agent/reference_repos/fastapi-users/fastapi_users/jwt.py`
- `/Users/cici/oncall agent/reference_repos/fastapi-users/tests/test_jwt.py`
- `/Users/cici/oncall agent/reference_repos/fastapi-users/docs/usage/current-user.md`
- `/Users/cici/oncall agent/reference_repos/full-stack-fastapi-template/backend/app/api/deps.py`
- `/Users/cici/oncall agent/reference_repos/full-stack-fastapi-template/backend/app/main.py`

借鉴内容：

- `fastapi-users`：JWT payload + `exp` 的最小 encode/decode 形态，以及 current_user 依赖应该创建一次并复用的组织方式。
- `full-stack-fastapi-template`：`OAuth2PasswordBearer`、token dependency、`get_current_user` 里统一解析 token 并抛 HTTP error、主应用 include router 的形态。

没有复制整段业务代码。原因是本项目 E1 只需要 local seed + JWT 的 MVP 身份底座，不需要引入参考项目的数据库 Session、SQLModel 用户表、完整用户管理或多 backend auth 体系。

### TDD 红灯

先新增：

- `tests/test_enterprise_auth.py`
- `tests/test_enterprise_request_context.py`

首次运行：

```text
uv run python -m unittest tests.test_enterprise_auth tests.test_enterprise_request_context -v
```

失败点：

```text
ModuleNotFoundError: No module named 'app.api.auth'
ModuleNotFoundError: No module named 'app.enterprise'
```

这确认测试先锁住了 E1 的公开行为：受保护 API 未登录返回 401、登录成功返回 token/profile、密码错误返回 401、受保护请求能拿到身份和 trace、logout 后 token blacklist 生效、过期 token 被拒绝，以及 `RequestContext` 在异步任务间隔离。

### 代码级变更

`app/enterprise/context.py`：

- 新增 `RequestContext`，字段包括 `request_id`、`trace_id`、`user_id`、`username`、`department_id`、`department_name`、`roles`。
- 使用 `contextvars.ContextVar` 保存当前请求上下文，提供 `set_current_request_context()`、`get_current_request_context()`、`reset_current_request_context()`、`clear_current_request_context()`。

`app/enterprise/auth/models.py`：

- 新增 `LoginRequest`、`UserProfile`、`SeedUser`、`TokenPayload`。
- `SeedUser.to_profile()` 明确把本地 seed 用户转换成不含密码的 profile，避免 API 响应泄露 seed password。

`app/enterprise/auth/seed.py`：

- 新增本地 demo 用户：
  - `admin` / `Admin123!`，`user_id=user_admin`，`department_id=system`，`roles=["admin"]`。
  - `demo_user_dept1` / `Demo123!`，`user_id=user_demo_dept1`，`department_id=dept_1`，`roles=["user"]`。

`app/enterprise/auth/jwt_handler.py`：

- 新增 `JwtHandler`，使用 PyJWT HS256 生成和解析 access token。
- token payload 包含 `sub`、`username`、`department_id`、`department_name`、`roles`、`jti`、`iat`、`exp`。
- `decode_access_token()` 区分过期 token 和无效 token，但 API 层统一映射为 401。

`app/enterprise/auth/service.py`：

- 新增 `AuthService`。
- `authenticate()` 使用 `secrets.compare_digest()` 校验本地 seed 密码。
- `validate_access_token()` 解析 JWT、检查 blacklist、再从 seed 用户表返回当前 profile。
- `blacklist_token()` 按 `jti` 记录 token 到期时间，`clear_blacklist()` 供测试隔离使用。

`app/enterprise/auth/dependencies.py`：

- 新增 `OAuth2PasswordBearer(tokenUrl="/api/auth/login")`。
- 新增 `get_current_user()` yield dependency：验证 token 后生成或透传 `X-Trace-Id` / `X-Request-Id`，写入 `RequestContext`，请求结束时 reset context。

`app/api/auth.py`：

- 新增 `/api/auth/login`、`/api/auth/logout`、`/api/auth/me`、`/api/auth/protected`。
- 响应沿用当前项目常见的 `code/message/data` envelope。
- `/api/auth/protected` 是 E1 验收用的最小受保护 API，用来证明 current_user + RequestContext 能返回 `user_id`、`department_id`、`roles`、`trace_id`。

`app/main.py`：

- 只新增 auth router include：`app.include_router(auth.router, prefix="/api", tags=["企业身份"])`。
- 没有改旧 `chat`、`file`、`aiops`、`shadow_metrics` 路由和旧服务内部。

`app/config.py` / `pyproject.toml` / `uv.lock`：

- 新增 `jwt_secret_key`、`jwt_algorithm`、`jwt_access_token_expire_minutes`。
- 显式声明 `pyjwt>=2.8.0,<3.0.0`，因为 E1 代码直接 `import jwt`；`uv.lock` 只同步 root dependency metadata，PyJWT 本身已在锁文件中。

### 验证

已运行：

```text
uv run python -m unittest tests.test_enterprise_auth tests.test_enterprise_request_context -v
uv run python -m unittest tests.test_retrieval_service tests.test_p5_planner_memory_integration tests.test_memory_ingestion_aiops_hook -v
uv run python -m compileall app tests
make deps-check
uv run ruff check app/enterprise app/api/auth.py tests/test_enterprise_auth.py tests/test_enterprise_request_context.py
uv run python -c "from app.main import app; paths = sorted(route.path for route in app.routes); assert '/api/auth/login' in paths and '/api/auth/protected' in paths; print('auth_routes_ok')"
```

结果：

- E1 auth/context targeted tests：9/9 通过。
- 旧 RAG/AIOps 回归切片：10/10 通过。
- `compileall app tests` 通过。
- `make deps-check` 通过，`uv lock --check` 和 `uv run pip check` 都成功。
- targeted `ruff check` 通过；仅输出当前 repo 既有 top-level ruff config deprecation warning。
- 主应用路由 smoke 输出 `auth_routes_ok`。

### 风险和处理

- 风险：E1 过早引入真实企业身份源会扩大范围。处理：只使用本地 seed 用户，明确不接 CAS/LDAP。
- 风险：logout blacklist 如果接 Redis 会影响部署依赖。处理：E1 使用进程内 blacklist，满足 MVP 验收；多实例/持久化 blacklist 留给后续生产化阶段。
- 风险：默认 JWT secret 太短会触发 PyJWT HMAC key warning。处理：把默认开发 secret 调整到 32 字节以上，并重跑 E1 tests。
- 风险：Gateway 还没接入时误改旧 RAG/AIOps。处理：只挂载 auth router，不移动旧服务，旧 RAG/AIOps 回归切片已通过。

### 阶段收口

阶段提交：`60d56a23eb08dc06536dda77a3712485f3ad125f` (`enterprise(e1): add local identity request context`)。

### 如何在项目评审中解释

如果被问：“为什么 E1 不直接接公司 LDAP 或 CAS？”

答：E1 的目标是证明 Gateway-MVP 的身份上下文契约，而不是完成企业 IdP 集成。后续 RequestGateway、PermissionService、ToolGateway 和 DB Gateway 都只依赖 `current_user` / `RequestContext` 的稳定字段。先用本地 seed + JWT 可以把契约、trace 和保护路由测清楚，避免在身份源、网络、数据库和权限模型之间混合排错。

如果被问：“为什么 blacklist 先放内存？”

答：E1 验收只要求 logout 后当前 token 不能再用，进程内 blacklist 足以证明 `jti` 阻断路径和测试契约。Redis 或数据库持久化会引入额外部署依赖，应等 E8/E9 的生产化和多实例需求明确后再做。

如果被问：“RequestContext 为什么用 contextvars？”

答：FastAPI 的请求处理和后续 Gateway 会进入 async 链路，用全局变量容易串请求。`contextvars` 可以让同一异步任务链读取当前请求上下文，同时不同 async task 互不污染；`tests/test_enterprise_request_context.py` 已覆盖 async task isolation。

## 2026-05-30：E2 RequestGateway + Audit Shell

### 为什么现在做

E1 已经提供本地身份、`RequestContext` 和 `trace_id`。E2 的目标是在不移动旧 RAG / AIOps / upload 服务、不接真实权限中心、不引入数据库工具的前提下，先把企业请求统一包进 RequestGateway，证明 success / blocked / failed 三类路径都能带同一个 trace 并写入 audit。

本轮只做 E2 audit shell 和 guardrail/rate-limit 的最小可替换接口，不做 E3 PermissionService、E4 ToolGateway、E6 DB sandbox，也不把旧服务目录整体重构。

### 参考来源

已按 E2 参考矩阵读取：

- `/Users/cici/oncall agent/reference_repos/langfuse/packages/shared/src/eventsTable.ts`
- `/Users/cici/oncall agent/reference_repos/langfuse/packages/shared/src/observationsTable.ts`
- `/Users/cici/oncall agent/reference_repos/open-webui/backend/open_webui/routers/pipelines.py`
- `/Users/cici/oncall agent/reference_repos/open-webui/backend/open_webui/functions.py`
- `/Users/cici/oncall agent/reference_repos/open-webui/backend/open_webui/main.py`

借鉴内容：

- `langfuse`：trace / observation / event 字段应包含 trace id、时间、名称或类型、状态、用户或 session 线索；本项目只借鉴 audit event 字段组织，不接 Langfuse 服务端。
- `open-webui`：server-side filter / pipeline / middleware 形态说明 guardrail 应在服务端请求边界执行，而不是交给前端或模型自觉遵守；本项目只借鉴边界组织，不复制 pipeline 代码。

未参考 WeKnora 代码。原因是 E2 不是 RAG ingestion / chunking / retrieval / artifact 任务；旧 RAG 与 upload 只通过 thin adapter 包裹，未改变 WeKnora 相关融合边界。

### TDD 红灯

先新增：

- `tests/test_enterprise_request_gateway.py`
- `tests/test_enterprise_gateway_routes.py`

首次运行：

```text
uv run python -m unittest tests.test_enterprise_request_gateway tests.test_enterprise_gateway_routes -v
```

失败点：

```text
ModuleNotFoundError: No module named 'app.enterprise.gateway'
```

这确认测试先锁住了 E2 的公开行为：成功请求写 `request_started` / `request_completed`，rule guardrail 阻断请求并写 `request_failed`，失败请求只记录 `error_class` 不记录敏感 stack/message，chat / upload / aiops route 能复用请求头里的同一个 `X-Trace-Id`。

### 代码级变更

`app/enterprise/gateway/*`：

- 新增 `GatewayRequest`、`GuardrailDecision`、`RateLimitDecision`。
- 新增 `NoOpGuardrailProvider` 和 `RuleGuardrailProvider`。no-op provider 不改变行为；rule provider 支持 keyword / regex 规则，先用于 E2 blocked-path 验收。
- 新增 `GuardrailService` 和 `NoOpRateLimitService`，为 E3/E4 后续替换保留接口，但 E2 不启用真实限流。
- 新增 `RequestGateway.execute()` / `execute_stream()`，统一设置 `RequestContext`，执行 rate-limit / guardrail，记录 `request_started`、`request_completed`、`request_failed`。
- `RequestBlocked` 在 audit 中映射为 `GuardrailBlocked`，便于 trace 里直接看出阻断层。
- `execute_stream()` 对 async generator 关闭时的 `ContextVar` token 跨 context reset 做兜底清理；AIOps SSE route 不再在收到 terminal event 后提前关闭下游 generator，避免 completed audit 丢失。

`app/enterprise/observability/*`：

- 新增 `AuditEvent`，字段包括 `event_id`、`event_type`、`route`、`trace_id`、`request_id`、`user_id`、`timestamp`、`decision`、`reason`、`error_class`、`error_message`、`latency_ms`、`metadata`。
- 新增 `AuditService`，默认写本地 SQLite + JSONL；测试可注入 `InMemoryAuditSink`。
- `AuditService.record()` 对 sink 写入失败只 warning，不阻断主请求，避免 audit 后端短暂问题影响业务路径。
- `SQLiteAuditSink` 使用 `contextlib.closing(sqlite3.connect(...))` 显式关闭连接，避免测试中出现 unclosed database ResourceWarning。

`app/enterprise/adapters/*`：

- 新增 `ChatAdapter`，包裹旧 `rag_agent_service.query()`，保持旧 response envelope，并在 data 里附带 `trace_id`。
- 新增 `UploadAdapter`，包裹旧 `DocumentIngestionService.ingest_upload()`，保留文件大小 / 文件名检查和旧 upload 响应字段，并附带 `trace_id`。
- 新增 `AIOpsAdapter`，包裹旧 `aiops_service.diagnose()` 流式接口，对 SSE dict event 注入 `trace_id`。

`app/api/chat.py` / `app/api/file.py` / `app/api/aiops.py`：

- chat / upload / aiops 入口改为构造 adapter 并传入 request headers。
- blocked path 返回 403 envelope，不调用旧业务 handler。
- failed path 由 Gateway 先写 audit，再让原 API 继续按旧错误风格返回。
- Ruff 要求的 exception chaining 用 `raise ... from e` 补齐，避免本阶段 targeted lint 卡在已触及文件上。

`app/config.py`：

- 新增 `enterprise_audit_sqlite_path` 和 `enterprise_audit_jsonl_path`，默认指向 `logs/enterprise_audit.sqlite` 和 `logs/enterprise_audit.jsonl`。这些是本地运行产物，按 Git ignore 规则不提交。

### 验证

已运行：

```text
uv run ruff check app/enterprise app/api/chat.py app/api/file.py app/api/aiops.py tests/test_enterprise_request_gateway.py tests/test_enterprise_gateway_routes.py
uv run python -m compileall app tests
uv run python -m unittest tests.test_enterprise_request_gateway tests.test_enterprise_gateway_routes -v
uv run python -m unittest tests.test_enterprise_auth tests.test_enterprise_request_context -v
uv run python -m unittest tests.test_retrieval_service tests.test_p5_planner_memory_integration tests.test_memory_ingestion_aiops_hook tests.test_document_ingestion_service tests.test_p1_4_regression -v
uv run python -m unittest tests.test_document_ingestion_service.DocumentIngestionServiceTests.test_upload_api_rejects_unsupported_type_from_ingestion_layer -v
make deps-check
uv run python -c "from app.main import app; paths=sorted(route.path for route in app.routes); assert '/api/chat' in paths and '/api/upload' in paths and '/api/aiops' in paths; print('gateway_routes_ok')"
```

结果：

- Targeted E2 tests：6/6 通过。
- E1 auth/context tests：9/9 通过。
- 旧 RAG / Memory / Upload 回归切片：21/21 通过。
- 触发过 ResourceWarning 的 upload API 单测重跑通过，未再出现 unclosed database warning。
- `compileall app tests` 通过。
- `make deps-check` 通过，`uv lock --check` 和 `uv run pip check` 都成功。
- targeted `ruff check` 通过；仅输出当前 repo 既有 top-level ruff config deprecation warning。
- 主应用路由 smoke 输出 `gateway_routes_ok`。

### 风险和处理

- 风险：E2 借 RequestGateway 之名重构旧服务。处理：只新增 `app/enterprise/*` 和三层 adapter，旧 RAG / AIOps / ingestion 服务内部未搬迁。
- 风险：audit 记录失败时阻断业务请求。处理：`AuditService` 对 sink failure 只 warning，保留业务成功路径；后续 E9 再按生产观测要求升级。
- 风险：failed audit 泄露敏感 stack 或原始异常消息。处理：Gateway 只记录 `error_class`，`error_message` 默认空；测试用 `"boom with secret stack details"` 验证 audit JSON 不含 secret。
- 风险：流式 SSE 提前关闭导致 completed audit 丢失。处理：去掉 route 层 terminal-event break，让 adapter/gateway 自然消费完下游 async generator，并给 `ContextVar` reset 增加跨 context fallback。

### 阶段收口

阶段实现提交：`6a84c47da30b6c60d04e1d46e784e3b243b3ddf2` (`enterprise(e2): add request gateway audit shell`)。

阶段 hash 已在本节补写；补写动作将作为独立收口提交进入 `enterprise` 分支历史。

### 如何在项目评审中解释

如果被问：“为什么先做 no-op Guardrail 和 no-op RateLimit？”

答：E2 的目标不是把所有治理策略一次做完，而是先固定请求治理的插拔点和 audit 事件契约。no-op provider 证明默认不改变旧行为；rule provider 证明同一接口能阻断请求并写 audit。后续 E3/E4 可以替换 provider，而不需要再改 chat / upload / aiops 入口。

如果被问：“为什么 audit 先用 SQLite/JSONL？”

答：E2 需要可本地验证的 audit shell，而不是生产观测平台。SQLite 方便 targeted tests 或本地查询，JSONL 方便直接查看事件流；两者都在本地 `logs/`，不会进入 Git。后续可以把 `AuditSink` 替换成 Langfuse、ELK 或 OpenTelemetry 风格实现。

如果被问：“为什么没有把旧 RAG/AIOps 服务搬进企业目录？”

答：计划已经明确 E0-E9 阶段 Adapter 是正式 MVP 边界。E2 要证明治理链路能包住旧能力，而不是制造大范围 import 迁移风险。只有当 adapter 变厚、测试被旧结构阻塞、或 E9 后出现明确维护成本时，才考虑收敛旧服务目录。

## 2026-05-30：E11 Vue3 执行过程可视化升级纳入总控计划

### 为什么现在调整计划

用户确认执行过程可视化不应打断 E2-E9 主线，但希望把 `FastAPI + SSE + Vue3` 升级作为后续明确阶段，并要求前置阶段提前做好准备，避免 E9 之后才发现事件协议不统一。

本轮只调整总控计划，不改业务代码。原因是当前项目已经有 FastAPI + SSE 基础，真正的风险不是“以后能不能上 Vue3”，而是 E2-E9 期间如果没有统一 SSE 事件契约，E11 会从纯前端展示层升级变成前后端联动大改。

### 修改的文件和计划项

`docs/enterprise_assistant_development_plan.md`：

- 在目标分层中新增 `L8 Execution Visualization`，明确 Vue3 可视化属于后端协议稳定后的展示层。
- 新增 `2.7 可视化事件契约先行`，规定 `/api/chat_stream`、`/api/aiops` 和后续 gateway/tool/model/retrieval 事件必须收敛到同一套 SSE envelope。
- 把推荐执行顺序扩展为 `E9 -> E10 -> E11 Vue3 执行过程可视化升级`。
- 在参考顺序、阶段任务参考矩阵、里程碑和工作量估算中新增 E11。
- 新增“跨阶段要求：SSE 事件协议准备（E2-E9）”，把 `docs/enterprise_sse_event_contract.md` 或等价文档列为 E9 验收产物。
- 更新 E2 范围和验收，要求流式 blocked / failed / trace 事件能映射到统一 SSE envelope。
- 更新 E9 范围和验收，新增 `SSE event contract completeness check`，明确 E9 必须确认 `/api/chat_stream` 和 `/api/aiops` 的事件协议已固化。
- 新增 E11 阶段，限定为 Vue3 UI 消费既有 SSE 协议，不修改后端业务逻辑、不改变 SSE 事件语义。
- 在风险表、验收总表和“不建议现在做”中增加 E11 风险控制。

### 关键决策

E11 的边界是：

```text
Vue3 UI = 既有 SSE 协议的消费者
不是后端协议重新设计阶段
不是 RequestGateway / ToolGateway / AIOps 流程重写阶段
```

E2-E9 的前置责任是：

```text
统一事件 envelope
保留 trace_id / request_id
让 blocked / audit / tool / model / retrieval / report / done 能按同一 trace 串联
在 E9 做 event contract completeness check
```

推荐事件 envelope 写入主计划：

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

### 风险和处理

- 风险：E11 才发现 `/api/chat_stream` 和 `/api/aiops` 事件格式不统一。处理：E2-E9 增加跨阶段 SSE event contract 要求，E9 明确做 completeness check。
- 风险：Vue3 前端开发时顺手要求后端新增 UI-only 字段。处理：E11 验收写明“后端协议文件无 E11 期间的语义性变更”；如必须变更，要退回 E9/E10 补协议。
- 风险：现在提前重写前端打断治理主线。处理：主计划明确“不现在重写 Vue3 前端；只在 E2-E9 固化后端事件契约，为 E11 做准备”。

### 验证

本轮是文档计划调整，未运行业务测试。需要做的验证是文档一致性检查：

```text
rg -n "E11|SSE event contract|enterprise_sse_event_contract|Vue3|Execution Visualization" docs/enterprise_assistant_development_plan.md docs/enterprise_capability_development_record.md
```

### 如何在项目评审中解释

如果被问：“为什么不现在直接做 Vue3？”

答：现在的主线风险在治理底座和事件契约，不在前端框架。提前做 Vue3 会把未完成的 PermissionService、ToolGateway、ModelGateway 阶段画成不稳定 UI。先在 E2-E9 固化 SSE envelope 和 trace 串联，E11 再做 Vue3，就能把它限定为纯展示层升级。

如果被问：“为什么计划里现在就写 E11？”

答：因为 E11 是否低风险，取决于 E2-E9 是否提前准备好事件协议。把 E11 写进总控计划不是提前实现，而是给前置阶段增加验收约束：不能等前端升级时才发现协议不统一。

## 2026-05-30：E2.1 chat_stream RequestGateway 覆盖补齐

### 为什么现在补

E2 收口后复核发现 `/api/chat_stream` 仍直接调用 `rag_agent_service.query_stream()`，没有经过 `ChatAdapter` / `RequestGateway`。这意味着流式对话缺少 guardrail、audit 和 trace_id 传播。由于流式对话是核心 chat 场景，而且 `RequestGateway.execute_stream()` 已经存在，这个缺口应归入 E2 补齐，不应带入 E3。

### TDD 红灯

新增两个 route 级测试：

- `test_chat_stream_success_uses_gateway_trace_and_audit`
- `test_rule_guardrail_blocks_chat_stream_and_writes_audit`

首次运行失败：

```text
AssertionError: 'trace-stream-success' not found in response.text
AssertionError: 'blocked' not found in response.text
```

第二个失败还暴露了真实风险：blocked 测试没有被 guardrail 拦住，反而进入了旧 RAG streaming 路径并初始化 MCP 工具。这证明缺口不是文档问题，而是实际治理绕过。

### 代码级变更

`app/enterprise/adapters/chat_adapter.py`：

- 新增 `chat_stream()`。
- 构造 `GatewayRequest(route="chat_stream", payload=request.model_dump(by_alias=True), headers=headers)`。
- 使用 `RequestGateway.execute_stream()` 包裹旧 `rag_service.query_stream()`。
- 对流式 chunk 注入 `trace_id`。
- 捕获 `RequestBlocked` / `RateLimitBlocked` 并生成 SSE 可消费的 blocked chunk，保证阻断路径也能返回 trace_id。

`app/api/chat.py`：

- `/api/chat_stream` 签名增加 `http_request: Request`。
- 流式 generator 改为消费 `chat_adapter.chat_stream(chat_request, http_request.headers)`。
- SSE payload 在 `debug`、`tool_call`、`search_results`、`content`、`done`、`error`、`blocked` 事件中附带 `trace_id`。

`tests/test_enterprise_gateway_routes.py`：

- 增加 chat_stream success 测试：验证 SSE 文本包含 `trace-stream-success`，audit 写入 `request_completed` 且 route 为 `chat_stream`。
- 增加 chat_stream blocked 测试：验证 SSE 文本包含 `blocked` 和 trace_id，audit 写入 `GuardrailBlocked` / `blocked`，且不会进入旧 RAG 流。

### 验证

已运行：

```text
uv run python -m unittest tests.test_enterprise_gateway_routes.EnterpriseGatewayRouteTests.test_chat_stream_success_uses_gateway_trace_and_audit tests.test_enterprise_gateway_routes.EnterpriseGatewayRouteTests.test_rule_guardrail_blocks_chat_stream_and_writes_audit -v
uv run ruff check app/enterprise app/api/chat.py tests/test_enterprise_gateway_routes.py tests/test_enterprise_request_gateway.py
uv run python -m unittest tests.test_enterprise_request_gateway tests.test_enterprise_gateway_routes -v
uv run python -m compileall app tests
uv run python -m unittest tests.test_retrieval_service tests.test_p5_planner_memory_integration tests.test_memory_ingestion_aiops_hook tests.test_document_ingestion_service tests.test_p1_4_regression -v
make deps-check
uv run python -c "from app.main import app; paths=sorted(route.path for route in app.routes); assert '/api/chat_stream' in paths and '/api/chat' in paths and '/api/upload' in paths and '/api/aiops' in paths; print('gateway_routes_ok')"
```

结果：

- 新增 chat_stream 红绿测试：2/2 通过。
- E2 targeted tests：8/8 通过。
- 旧 RAG / Memory / Upload 回归切片：21/21 通过。
- `compileall app tests` 通过。
- `make deps-check` 通过。
- route smoke 输出 `gateway_routes_ok`。
- targeted `ruff check` 通过；仅有 repo 既有 top-level ruff config deprecation warning。

### 阶段补齐收口

E2.1 补齐提交：`6f1c9c1c7fae323dbae5417f23705a4f71b7bd6d` (`enterprise(e2): cover chat stream gateway path`)。

E2.1 hash 已在本节补写；补写动作将作为独立收口提交进入 `enterprise` 分支历史。

## 2026-05-30：E2.2 SSE Contract Baseline

### 为什么现在补

E2.1 补齐 `/api/chat_stream` 后，继续复核新计划中的“跨阶段要求：SSE 事件协议准备（E2-E9）”。结论是：完整 envelope 统一应留到 E9 冻结，但 E3 前必须先补齐两个最小基线：

1. 流式事件必须同时带 `trace_id` 和 `request_id`。
2. 必须有一个可演进的 SSE 事件协议草案，供 E3-E8 后续事件接入时参考。

### 代码级变更

`app/enterprise/gateway/request_gateway.py`：

- `RequestBlocked` / `RateLimitBlocked` 增加 `request_id` 字段。
- `_enforce_guardrail()` 和 `_enforce_rate_limit()` 抛出阻断异常时同时携带 `trace_id` 和 `request_id`。

`app/enterprise/adapters/chat_adapter.py`：

- `chat_stream()` 对正常 streaming chunk 同时注入 `trace_id` 和 `request_id`。
- blocked chunk 同时返回 `trace_id` 和 `request_id`。

`app/enterprise/adapters/aiops_adapter.py`：

- `diagnose_stream()` 对 AIOps dict event 同时注入 `trace_id` 和 `request_id`。
- blocked event 同时返回 `trace_id` 和 `request_id`。

`app/api/chat.py`：

- `/api/chat_stream` SSE payload 映射从 `with_trace()` 扩展为 `with_context_ids()`，输出 `trace_id` 和 `request_id`。

`docs/enterprise_sse_event_contract.md`：

- 新增 Draft 文档，定义推荐 envelope、字段要求、当前 `/api/chat_stream` 和 `/api/aiops` 的 E2 映射、E2 contract smoke、E9 冻结前待办。

`tests/test_enterprise_gateway_routes.py`：

- chat_stream success / blocked 测试增加 `X-Request-Id` 并断言 SSE 文本包含 request_id。
- aiops success 测试增加 `X-Request-Id` 并断言 SSE 文本包含 request_id。

### 验证

已运行：

```text
uv run ruff check app/enterprise app/api/chat.py tests/test_enterprise_gateway_routes.py tests/test_enterprise_request_gateway.py
uv run python -m unittest tests.test_enterprise_request_gateway tests.test_enterprise_gateway_routes -v
uv run python -m compileall app tests
git diff --check
```

结果：

- targeted `ruff check` 通过；仅有 repo 既有 top-level ruff config deprecation warning。
- E2 targeted tests：8/8 通过。
- `compileall app tests` 通过。
- `git diff --check` 通过。

### 阶段补齐收口

E2.2 补齐提交：`7d44b3dcbd761cfd2b4720a65a004ae4fc7e104e` (`enterprise(e2): add sse contract baseline`)。

E2.2 hash 已在本节补写；补写动作将作为独立收口提交进入 `enterprise` 分支历史。

## 2026-05-30：E3 PermissionService + Registry MVP

### 为什么现在做

E2 已经把请求统一包进 RequestGateway，并补齐 stream trace / request_id 基线。E3 的目标是把资源权限判断从业务代码里抽出来，先形成一个可替换的 L3 Permission / Registry 边界。这样 E4 ToolGateway、E5 RAG/Upload 权限过滤和 E7 DB Gateway 后续接入时，不需要各自写一套权限判断。

本轮只做 PermissionService / registry MVP，不接真实 MySQL，不改造旧 SQLite/RAG/Memory 数据访问，也不把权限逻辑提前塞进旧 RAG retrieval。RAG/ToolGateway 的真实接入留给 E4/E5。

### 参考来源

已按计划读取：

- `/Users/cici/oncall agent/reference_repos/pycasbin/examples/rbac_with_deny_model.conf`
- `/Users/cici/oncall agent/reference_repos/pycasbin/examples/rbac_with_deny_policy.csv`
- `/Users/cici/oncall agent/reference_repos/pycasbin/examples/rbac_with_domains_model.conf`
- `/Users/cici/oncall agent/reference_repos/open-webui/backend/open_webui/models/access_grants.py`
- `/Users/cici/oncall agent/reference_repos/open-webui/backend/open_webui/utils/access_control/__init__.py`

结论：

- 采用 pycasbin 的 deny-overrides 语义：存在匹配 deny 时，即使另有 allow 也必须 deny。
- 采用 open-webui 的扁平 resource grant 形态：resource_type、resource_id、principal_type、principal_id、permission/action。
- 本轮不直接引入 pycasbin runtime 依赖，因为 E3 MVP 只需要先证明模型和本地测试；后续可以把 `PermissionService` 的 evaluator 替换为 pycasbin 或企业权限中心。

### 代码级变更

`app/enterprise/permissions/models.py`：

- 新增 `PrincipalType`：`user`、`role`、`department`、`public`。
- 新增 `GrantEffect`：`allow`、`deny`。
- 新增 `ResourceGrant`、`PermissionDecision`、`ResourceDescriptor`。

`app/enterprise/permissions/repository.py`：

- 新增 `InMemoryGovernanceRepository`。
- 该 repository 只保存企业治理 grant，不包旧 RAG / Memory / upload SQLite store。

`app/enterprise/permissions/service.py`：

- 新增 `PermissionService.check()`，默认 deny，显式 allow，deny 优先于 allow。
- 支持 user / role / department / public principal 匹配。
- 新增 permission decision cache。
- 新增 `invalidate_cache()` 显式失效接口。
- 新增 `grant_access()` / `revoke_grant()`，通过 service 变更 grant 时会主动失效对应资源缓存。
- 每次 check 都写 `permission_checked` audit，记录 allow/deny decision、reason、resource_type、resource_id、action、matched_grant_id 和 cache_hit。

`app/enterprise/permissions/registry.py`：

- 新增 `ToolRegistry`、`DocumentAccessRegistry`、`ModelEndpointRegistry`。
- registry 只保存资源描述并通过 `PermissionService.filter_allowed()` 输出当前用户可见资源。

`tests/test_enterprise_permissions.py`：

- 覆盖默认 deny + audit。
- 覆盖显式 user allow。
- 覆盖 deny overrides role allow。
- 覆盖 grant revoke 后缓存失效。
- 覆盖外部治理仓库变更后显式 `invalidate_cache()` 生效。
- 覆盖 DocumentAccessRegistry 不泄露未授权文档标题和 source_ref。
- 覆盖 ToolRegistry / ModelEndpointRegistry 只返回授权工具和模型。

### 验证

已运行：

```text
uv run python -m unittest tests.test_enterprise_permissions -v
uv run ruff check app/enterprise/permissions tests/test_enterprise_permissions.py
uv run ruff check app/enterprise app/api/chat.py app/api/file.py app/api/aiops.py tests/test_enterprise_permissions.py tests/test_enterprise_gateway_routes.py tests/test_enterprise_request_gateway.py tests/test_enterprise_auth.py tests/test_enterprise_request_context.py
uv run python -m unittest tests.test_enterprise_permissions tests.test_enterprise_request_gateway tests.test_enterprise_gateway_routes tests.test_enterprise_auth tests.test_enterprise_request_context -v
uv run python -m unittest tests.test_retrieval_service tests.test_p5_planner_memory_integration tests.test_memory_ingestion_aiops_hook tests.test_document_ingestion_service tests.test_p1_4_regression -v
uv run python -m compileall app tests
make deps-check
```

当前结果：

- E3 permission targeted tests：7/7 通过。
- E1/E2/E3 targeted tests：24/24 通过。
- 旧 RAG / Memory / Upload 回归切片：21/21 通过。
- targeted `ruff check` 通过；仅有 repo 既有 top-level ruff config deprecation warning。
- `compileall app tests` 通过。
- `make deps-check` 通过。

提交前还需要跑 staged safety check。

### 风险和处理

- 风险：E3 过早变成完整权限中心。处理：本轮只做可替换本地 evaluator 和 in-memory governance repository，不接真实企业权限中心。
- 风险：admin 被隐式放行导致默认 deny 失效。处理：E3 MVP 不做 admin bypass；admin 也必须通过显式 `role=admin` 或其他 grant 获得资源权限。
- 风险：未授权文档在过滤前已经进入 retrieval/citation。处理：E3 先提供 `DocumentAccessRegistry.list_visible()` 和 permission filter；E5 再把它接进旧 RAG retrieval 前置过滤。

### 阶段收口

E3 实现提交：`4a409e9bebeff4f754323ac1aa9bd3faf8c3670e` (`enterprise(e3): add permission registry mvp`)。

E3 hash 已在本节补写；补写动作将作为独立收口提交进入 `enterprise` 分支历史。

## 2026-05-30：E4 ToolGateway + ModelGateway MVP

### 为什么现在做

E3 已经提供 PermissionService 和 Tool / Document / Model registry 语义。E4 的目标是把“工具给不给 LLM 看、能不能执行”和“模型 endpoint 如何选择 / fallback / 记录 latency usage”从业务链路中抽成可观测 gateway。

本轮只建立 E4 gateway 边界，不批量替换旧 RAG / AIOps 内部 LLM 调用，也不改变 AIOps/RAG 业务语义。数据库工具继续默认不可见，后续 E6/E7 只能通过显式 sandbox / DB gateway 接入。

### 参考来源

已按计划读取：

- `/Users/cici/oncall agent/reference_repos/modelcontextprotocol-python-sdk/examples/clients/simple-chatbot/mcp_simple_chatbot/main.py`
- `/Users/cici/oncall agent/reference_repos/modelcontextprotocol-python-sdk/src/mcp/client/client.py`
- `/Users/cici/oncall agent/reference_repos/litellm/litellm/router.py`
- `/Users/cici/oncall agent/reference_repos/bifrost/helm-charts/bifrost/values.yaml`

结论：

- 采用 MCP SDK 的 list tools / call tool 分层边界：发现工具和执行工具要分开。
- 采用 LiteLLM 的 endpoint routing / fallback / failure tracking 语义，但不引入 LiteLLM runtime。
- 采用 Bifrost 的 provider / routing-rule / fallback 配置形态作为后续可配置化方向；E4 先用本地 dataclass 固化最小结构。

### 代码级变更

`app/enterprise/tools/models.py`：

- 新增 `ToolDefinition`，保存 resource_id、name、description、source、handler/raw_tool 和 metadata。
- `is_database_tool` 统一判断 database category 或 database source，供默认过滤使用。

`app/enterprise/tools/registry.py`：

- 新增 `ToolRegistry`，保存企业工具定义。
- `list_exposable()` 在 E4 阶段默认排除 database tools，只有显式 `include_database_tools=True` 才暴露；E7 已把显式 DB session 改成权限级可见性，见上方 E7 记录。

`app/enterprise/tools/providers.py`：

- 新增 `ToolProvider` protocol。
- 新增 `StaticToolProvider` 供本地工具和测试使用。
- 新增 `MCPToolProvider`，通过现有 `get_mcp_tools_with_retry()` 暴露 MCP 工具。

`app/enterprise/tools/gateway.py`：

- 新增 `ToolGateway.list_visible_tools()`，通过 `PermissionService.check()` 过滤可见工具，并记录 `tool_visible` audit。
- 新增 `ToolGateway.get_bindable_tools()`，只返回授权工具，防止未授权工具绑定给 LLM。
- 新增 `ToolGateway.execute()`，成功写 `tool_call` audit，未授权/默认禁用 DB 工具写 `tool_blocked`，执行失败写 `tool_failure`。
- 新增 `ToolAccessDenied` 和 `ToolExecutionError`，使调用方能区分治理阻断和 provider 执行失败。

`app/enterprise/models/models.py`：

- 新增 `ModelEndpoint`、`ModelRequest`、`ModelResponse`。

`app/enterprise/models/providers.py`：

- 新增 `ModelProvider` protocol。
- 新增 `StaticModelProvider` 供 fallback / failure 测试使用。
- 新增 `DashScopeModelProvider`，复用现有 `LLMFactory.create_chat_model()` 的 DashScope OpenAI-compatible 调用路径。

`app/enterprise/models/gateway.py`：

- 新增 `ModelGateway.generate()`，按 permission-gated endpoint 列表尝试调用 provider。
- 主 endpoint 失败时尝试后续 allowed endpoint；全部失败时抛 `ModelGatewayError` 并写结构化失败 audit。
- 成功/失败 audit 记录 `model_name`、endpoint、provider、`latency_ms`、`status`、`fallback_used`、`failed_endpoint_ids` 和 usage。
- 默认 endpoint 使用 `config.rag_model` + DashScope provider，保留现有模型调用方向。

`tests/test_enterprise_tool_gateway.py`：

- 覆盖可见工具权限过滤、database tool 默认不可见、未授权工具不进入 bindable tool list。
- 覆盖授权工具执行成功写 `tool_call` audit。
- 覆盖未授权执行写 `tool_blocked` audit。
- 覆盖 provider 执行异常写 `tool_failure` audit。

`tests/test_enterprise_model_gateway.py`：

- 覆盖模型成功时记录 model_name / latency / usage / status。
- 覆盖主 endpoint 失败后 fallback 成功。
- 覆盖所有 endpoint 失败时结构化失败 audit。
- 覆盖 denied endpoint 不会被选择。

### 验证

已运行：

```text
uv run python -m unittest tests.test_enterprise_tool_gateway tests.test_enterprise_model_gateway -v
uv run ruff check app/enterprise tests/test_enterprise_tool_gateway.py tests/test_enterprise_model_gateway.py
uv run python -m unittest tests.test_enterprise_auth tests.test_enterprise_request_context tests.test_enterprise_request_gateway tests.test_enterprise_gateway_routes tests.test_enterprise_permissions tests.test_enterprise_tool_gateway tests.test_enterprise_model_gateway -v
uv run python -m unittest tests.test_retrieval_service tests.test_p5_planner_memory_integration tests.test_memory_ingestion_aiops_hook tests.test_document_ingestion_service tests.test_p1_4_regression -v
uv run python -m compileall app tests
make deps-check
git diff --cached --check
```

结果：

- E4 targeted tests：9/9 通过。
- E1-E4 targeted tests：33/33 通过。
- 旧 RAG / Memory / Upload 回归切片：21/21 通过。
- targeted `ruff check` 通过；仅有 repo 既有 top-level ruff config deprecation warning。
- `compileall app tests` 通过。
- `make deps-check` 通过。
- staged `git diff --cached --check` 通过。

### 风险和处理

- 风险：E4 变成一次性改造所有旧 agent 调用。处理：本轮只新增 gateway/provider 边界和 targeted tests，不改旧 RAG/AIOps 业务语义。
- 风险：DB tools 提前进入默认工具池。处理：`ToolRegistry` / `ToolGateway` 默认过滤 database category/source；E6/E7 必须显式打开 database-demo / DB gateway。
- 风险：fallback 行为吞掉失败。处理：最终 audit 记录 `failed_endpoint_ids`，全部失败时抛 `ModelGatewayError` 并记录最后错误类别。

### 阶段收口

E4 实现提交：`2f5ec2a0580db3b5f31f8cea244c29c020c99831` (`enterprise(e4): add tool and model gateways`)。

E4 hash 已在本节补写；补写动作将作为独立收口提交进入 `enterprise` 分支历史。

## 2026-05-30：E5 RAG / Upload governance boundary

### 为什么现在做

E3 已经提供 PermissionService / DocumentAccessRegistry，E4 已经提供 ToolGateway / ModelGateway。E5 的目标是把旧 RAG 检索和上传入口接到企业治理边界上：上传要有可审计的 storage URI，检索要在 context / citation 形成之前过滤未授权文档。

本轮仍保持 adapter 方式，不移动旧 `rag_agent_service`、`retrieval_service`、`document_ingestion_service` 的主职责边界，也不启用 reranker 或修改 DB 工具暴露策略。

### 参考来源

本阶段按计划参考 WeKnora / Dify 的 RAG、artifact、storage 和资源访问边界，落地时只采用小形态：

- 像 WeKnora 一样把上传原件、索引记录和检索结果分成可观察边界。
- 像 Dify / OpenWebUI 类产品一样把文档可见性作为服务端过滤，不把未授权资源交给前端或 LLM。
- 不复制大型 runtime，不引入对象存储或真实企业文档库；E5 先用本地 `local://` storage provider 证明接口形态。

### 代码级变更

`app/enterprise/adapters/rag_adapter.py`：

- 新增 `RagAdapter.retrieve(context, query)`。
- 先通过 `PermissionService` 判断候选文档权限，再调用旧 `RetrievalService.retrieve(..., allowed_document_ids=...)`。
- 写 `rag_retrieval` audit，记录 `allowed_doc_ids`、`blocked_doc_ids`、`result_doc_ids` 和 `result_count`。

`app/enterprise/storage/*`：

- 新增 `StoredObject` 和 `LocalStorageService`。
- 新上传原件通过 `local://documents/<kb_id>/<doc_id>/original/<filename>` 暴露 provider URI。
- `read_bytes()` 支持 `local://`，并保留 legacy absolute / relative path fallback，避免旧索引读取路径被一次性打断。

`app/services/document_ingestion_service.py`：

- 接受可注入 `storage_service`。
- 新上传先写入 `StorageService`，再保留 `DocumentRecord.original_path` 为本地文件路径，兼容旧 index / parser 路径。
- `metadata` 和 `status_evidence` 同步写入 `storage_uri` / `storage_provider`。

`app/enterprise/adapters/upload_adapter.py`：

- 上传响应增加 `storage_uri`。
- 写 `upload_saved` audit，包含 `user_id`、`department_id`、`kb_id`、`doc_id` 和 `storage_uri`。

`app/services/retrieval_service.py`：

- `retrieve()` 增加 `allowed_document_ids` 参数。
- 未授权 doc 在 result / context / citation 构造前被过滤，防止标题、source_ref、chunk text 通过检索输出泄露。

`app/tools/knowledge_tool.py`：

- 如果存在 enterprise `RequestContext`，走 `RagAdapter.retrieve(...)`。
- 没有 enterprise context 时保留旧 `retrieval_service.retrieve(...)` fallback，保证旧工具调用路径不被 E5 强制改变。

`app/enterprise/gateway/models.py`：

- `GatewayRequest.from_headers()` 增加 `X-User-Id`、`X-Username`、`X-Department-Id`、`X-Department-Name`、`X-Roles` 读取。
- 无 header 时回退到当前 `RequestContext` / default 值，便于 route、tool 和 adapter 共享身份上下文。

`tests/test_enterprise_rag_upload_e5.py`：

- 覆盖未授权文档在 retrieval result / context / citation 中不泄露。
- 覆盖 `StorageService` 的 `local://` URI、读取和 legacy path fallback。
- 覆盖 upload adapter 返回 `storage_uri` 并写 `upload_saved` audit。

### 验证

本轮收口复验已运行：

```text
.venv/bin/python -m pytest -q tests/test_enterprise_rag_upload_e5.py
.venv/bin/python -m pytest -q tests/test_enterprise_auth.py tests/test_enterprise_request_context.py tests/test_enterprise_request_gateway.py tests/test_enterprise_gateway_routes.py tests/test_enterprise_permissions.py tests/test_enterprise_tool_gateway.py tests/test_enterprise_model_gateway.py tests/test_enterprise_rag_upload_e5.py
.venv/bin/python -m ruff check app/enterprise app/services/document_ingestion_service.py app/services/retrieval_service.py app/tools/knowledge_tool.py tests/test_enterprise_rag_upload_e5.py
```

结果：

- E5 targeted tests：3/3 通过。
- E1-E5 enterprise targeted tests：36/36 通过。
- targeted `ruff check` 通过；仅有 repo 既有 top-level ruff config deprecation warning。

### 风险和处理

- 风险：为了接企业权限而重写旧 RAG 主链路。处理：E5 只加 adapter 和检索过滤参数，旧服务仍保留原职责。
- 风险：`storage_uri` 引入后破坏旧 parser/index 的本地 path 假设。处理：`original_path` 继续保存本地文件路径，`storage_uri` 作为新增证据字段和外部 provider URI。
- 风险：未授权文档在 filtering 前已经进入 prompt / citation。处理：`RetrievalService` 在结果、上下文和 citation 构造前应用 `allowed_document_ids`。
- 风险：E5 顺手启用 reranker 或改变检索质量策略。处理：本阶段只做治理边界，不改 reranker 默认状态。

### 阶段收口

E5 实现提交：`9f0f0a97436fae9bbfc6ebb74d4e05b6b35b0e39` (`enterprise(e5): add rag upload governance boundary`)。

E5 hash 已在本节补写；补写动作将作为独立收口提交进入 `enterprise` 分支历史。

## 2026-05-30：E10-A / AIOps-1 MCP metrics observability

### 为什么现在做

E10 是触发式 production readiness backlog，不应该把所有成熟化项当作默认编码队列。本轮只做 AIOps-1，是因为已有明确触发证据：

- MCP cache slice 已经落地，并且 P6 rerun 恢复到 `overall=7/12`。
- `docs/项目与成熟项目做法差距.md` 明确记录当前缺口是缺少 cache hit/miss、`get_tools()` latency、fresh retry count / failure count。
- 当时没有先改 replanner timeout 的充分证据；AIOps-2 需要 child-run artifacts 和 sample-level log diff，已在后续 E10-B 中补做。

### 参考来源

本阶段按 E10 规则先读取本项目差距文档，而不是直接搬成熟仓库代码。采用的成熟做法是：缓存/复用之后必须有可聚合指标，才能判断 tool discovery 是否仍是热路径瓶颈。

结论：

- 指标应贴近 `get_mcp_tools_with_retry()`，因为缓存、fresh retry 和 `get_tools()` 调用都在这里发生。
- 本轮不改 planner / executor / replanner graph，不引入 wrapper pattern，不把默认路径改为 stateful session。
- 先提供可测试的本地 snapshot + info logs，后续如果 P6 eval report 需要字段化导出，再从 `get_mcp_tools_metrics()` 接出。

### 代码级变更

`app/agent/mcp_client.py`：

- 新增 `_mcp_tools_metrics` 进程内 metrics state。
- 新增 `_reset_mcp_tools_metrics()`，供 targeted tests 和 eval setup 清空状态。
- 新增 `get_mcp_tools_metrics()`，返回 JSON-friendly snapshot：
  - `cache_hits` / `cache_misses`
  - `get_tools_attempts` / `get_tools_successes` / `get_tools_failures`
  - `fresh_retries` / `fresh_retry_successes` / `fresh_retry_failures`
  - `last_tool_count` / `last_error`
  - `get_tools_latency_ms.count/last/avg/min/max`
- 新增 `_get_tools_with_metrics()`，只包住 `client.get_tools()` 的计时和成功/失败记录，保持原有异常传播语义。
- `get_mcp_tools_with_retry()` 现在在默认 cache path 记录 hit/miss，在 stale-client fallback path 记录 fresh retry，并在 info logs 输出 metrics snapshot。
- 为了让本文件通过 targeted `ruff check`，同步修正了同文件内既有 import 顺序、`typing.Optional/Dict/List` 旧注解和空白行问题；没有改变业务语义。

`tests/test_aiops_mcp_tool_cache.py`：

- setUp / tearDown 同时清理 cache 和 metrics。
- 新增 `test_default_path_records_cache_hit_miss_and_latency_metrics`，锁住默认路径第一次 miss、第二次 hit、一次 `get_tools()` 调用和 latency summary。
- 扩展 fresh retry success 测试，验证 first failure + fresh success 的计数。
- 新增 fresh retry failure 测试，验证 second failure 在 re-raise 之前也记录 metrics。

### 验证

已运行：

```text
.venv/bin/python -m unittest tests.test_aiops_mcp_tool_cache -v
.venv/bin/python -m unittest tests.test_aiops_mcp_tool_cache tests.test_p6_memory_eval_infra tests.test_p5_planner_memory_integration tests.test_memory_ingestion_aiops_hook -v
.venv/bin/python -m ruff check app/agent/mcp_client.py tests/test_aiops_mcp_tool_cache.py
.venv/bin/python -m compileall -q app tests
make deps-check
git diff --cached --check
```

结果：

- E10-A targeted tests：5/5 通过。
- AIOps regression bundle：48/48 通过。
- targeted `ruff check` 通过；仅有 repo 既有 top-level ruff config deprecation warning。
- `compileall` 通过。
- `make deps-check` 通过。
- staged `git diff --cached --check` 通过。

### 风险和处理

- 风险：metrics 记录改变缓存/重试行为。处理：只把 `client.get_tools()` 替换为等价的 `_get_tools_with_metrics()` 调用，原有 cache TTL、fresh retry、异常抛出和成功后 cache store 逻辑保持不变。
- 风险：E10-A 顺手改 AIOps graph。处理：本轮没有修改 planner、executor、replanner 或 state schema。
- 风险：日志过度复杂。处理：先输出 snapshot 便于 P6/eval 日志确认，后续如需长期生产采集再接正式 metrics sink。

### 阶段收口

- E10-A 实现提交：`df02495261d2a56d92d30c97c95eb542dba41e18` (`enterprise(e10): add aiops mcp metrics`)。
- E10 不是整体完成状态；本轮只关闭 AIOps-1 MCP metrics。AIOps-2 replanner timeout 当时仍是待分析项，已在后续 E10-B 中按 evidence-only 方式关闭。

### 如何在项目评审中解释

如果被问：“为什么 E10 先做 MCP metrics，而不是直接修 replanner timeout？”

答：MCP metrics 是已触发且缺口清晰的可观测性债：cache 已经改变了 hot path，但还缺少 hit/miss、latency 和 fresh retry 指标，无法判断 tool discovery 是否长期稳定。replanner timeout 还只有一个长尾现象，必须先读 child-run artifacts 和 sample-level logs，否则容易在没有根因的情况下改 prompt 或 timeout。

如果被问：“为什么 metrics 放在 `mcp_client.py`，没有新建观测服务？”

答：这组指标的事实源就在 `get_mcp_tools_with_retry()`：cache 是否命中、是否调用 `get_tools()`、是否进入 fresh retry、调用耗时和异常都在这里发生。把 v1 metrics 放在同一模块，接口只暴露 `get_mcp_tools_metrics()`，比新建跨模块观测框架更小、更容易测试，也更符合 E10-A 的触发式补强边界。

## 2026-05-30：E10-B / AIOps-2 replanner timeout evidence analysis

### 为什么现在做

用户明确继续 E10 后，E10-A 已经完成 MCP metrics。按照 `docs/项目与成熟项目做法差距.md` 的顺序，下一步不是立刻编码，而是先分析 P6 rerun 暴露的 `p6_plan_004` replanner structured-output timeout。

### 证据

读取的核心 artifact：

```text
evals/memory/child_runs/20260530_010747/p6_guidance_p6_plan_004.log
evals/memory/child_runs/20260530_010747/p6_guidance_p6_plan_004.events.jsonl
evals/memory/child_runs/20260530_010747/p6_guidance_p6_plan_004.record.json
evals/memory/child_runs/20260530_010747/p6_guidance_p6_plan_004.payload.json
evals/memory/child_runs/20260530_010747/p6_baseline_p6_plan_004.*
evals/memory/p6_memory_eval_20260530_015555.json
```

关键事实：

- guidance payload 使用 `eval_node_timeout_seconds=25`、`sample_timeout_seconds=120`、`eval_max_steps=3`。
- guidance log 中第一次 replanner 在 `past_steps=1`、`remaining plan steps=3` 时进入 structured-output。
- primary structured-output 触发 `replanner structured output timed out after 25.000s`。
- json-mode fallback 成功，replanner 决策为 `continue`，后续第二次 replanner 决策为 `respond`。
- guidance record 为 `has_error=false`、`has_degradation=false`、`infra_failure_events=[]`、`degradation_events=[]`。
- 同一 P6 summary 只记录了 `p6_plan_002` 的 executor degradation，没有记录 `p6_plan_004` 的 recovered primary fallback。

### 结论

E10-B 结论是 evidence-only：

- `p6_plan_004` 不是 hard failure。
- timeout 发生在 replanner primary structured-output provider call / parser path，fallback 已恢复。
- 当前 record/report 漏掉 recovered primary structured-output fallback，因此 P6 的 degradation summary 低估了此类长尾。
- 现有证据不支持直接改 prompt、扩大 timeout 或简化 schema。

### 后续边界

如果继续 AIOps 编码，下一步应先做 recovered structured-output fallback observability：

- primary fallback warning 要从 logger-only 变成 structured degradation evidence。
- fallback 成功时样本仍应 `has_error=false`，但 `has_degradation=true`。
- 增加 targeted test 后再决定是否重跑目标样本或 full P6。

本轮没有运行代码测试，因为没有运行时代码变更；验证方式是 artifact 读取、JSON 字段核对、source path 核对和 `git diff --check`。

## 2026-05-31：E10-C / AIOps-3 recovered structured-output fallback observability

### 为什么现在做

E10-B 已经把 `p6_guidance_p6_plan_004` 定位成 recovered primary structured-output fallback。验收缺口不是行为失败，而是可观测性缺失：logger warning 没有进入 stream event、P6 record 或 degradation summary。

### 代码变更

- `app/agent/aiops/utils.py`：`invoke_structured_with_fallback()` 增加 `return_diagnostics` 可选参数。默认行为保持原样；显式开启时返回 recovered fallback metadata。
- `app/agent/aiops/replanner.py`：replanner 调用 diagnostics path，并把 `structured_output_*` 字段合并进 state update。
- `app/agent/aiops/state.py`：声明 recovered structured-output fallback metadata 字段，标记为 observability-only。
- `app/services/aiops_service.py`：stream event 和 legacy diagnose complete wrapper 保留 `structured_output_*` 字段。
- `evals/memory/run_p6_memory_eval.py`：把 `structured_output_recovered` 识别为 non-hard degradation evidence，保持 `has_error=false`。
- `tests/test_p6_memory_eval_infra.py`：新增 diagnostics、event metadata、degradation-not-hard-failure 三类 targeted tests。

### 验收结果

已运行：

```text
PYTHONPATH=. .venv/bin/pytest tests/test_p6_memory_eval_infra.py -q
PYTHONPATH=. .venv/bin/python -m ruff check --select F401 app/agent/aiops/replanner.py app/agent/aiops/utils.py app/agent/aiops/state.py app/services/aiops_service.py evals/memory/run_p6_memory_eval.py tests/test_p6_memory_eval_infra.py
PYTHONPATH=. .venv/bin/python -m compileall -q app/agent/aiops app/services/aiops_service.py evals/memory/run_p6_memory_eval.py tests/test_p6_memory_eval_infra.py
git diff --check -- app/agent/aiops/utils.py app/agent/aiops/replanner.py app/agent/aiops/state.py app/services/aiops_service.py evals/memory/run_p6_memory_eval.py tests/test_p6_memory_eval_infra.py
```

结果：

- E10-C targeted tests：42/42 通过。
- focused F401 `ruff check` 通过；仅有 repo 既有 top-level ruff config deprecation warning。
- `compileall` 通过。
- `git diff --check` 通过。

### 边界

- 不修改 replanner prompt。
- 不修改 timeout 值。
- 不简化 structured-output schema。
- 不改变 fallback 顺序或 graph routing。
- 不把 recovered fallback 当作 hard failure。

### 阶段收口

- E10-C 实现提交：`cb82c6ce42020b4375ba90b8e8913ee4e54c0c9a` (`enterprise(e10): surface recovered structured output fallback`)。

### 面试追问怎么答

**追问：为什么 fallback 成功还要记录 degradation？**

答：因为这是“用户结果成功、内部主路径降级恢复”的场景。`has_error=false` 保留业务完成事实，`has_degradation=true` 保留 primary structured-output timeout 这个稳定性信号。这样后续可以聚合长尾，而不会把成功样本误判成 hard failure。

## 2026-05-31：E11 Vue3 执行过程可视化升级

### 为什么现在做

E9 已冻结 `/api/chat_stream` 和 `/api/aiops` 的 SSE envelope，E11 可以作为纯展示层升级推进。此阶段的风险不是后端能力不足，而是前端为了展示便利反向修改事件语义；因此 E11 明确只消费既有协议。

### 代码变更

- `static/enterprise-dashboard.html`：新增并行 Vue3 入口，不替换现有 `/` 静态前端。
- `static/enterprise-dashboard.js`：新增 UI-side SSE parser、`normalizeEvent()`、run state reducer、fetch POST consumer，支持 chat_stream 与 aiops。
- `static/enterprise-dashboard.css`：新增运维控制台风格布局，展示 trace/request、实时输出、阶段时间线和终态。
- `tests/test_enterprise_dashboard_e11.py`：验证静态文件可通过 FastAPI static mount 访问，并调用 Node helper tests。
- `tests/js/test_enterprise_dashboard_e11.mjs`：验证 split SSE frame parsing、legacy/top-level event normalization、aiops report/complete、blocked/error terminal state。

### 验收结果

已运行：

```text
uv run pytest tests/test_enterprise_dashboard_e11.py tests/test_enterprise_observability_e9.py
node --test tests/js/test_enterprise_dashboard_e11.mjs
node --check static/enterprise-dashboard.js
uv run ruff check tests/test_enterprise_dashboard_e11.py
uv run python -m compileall -q app tests
make deps-check
git diff --check
```

结果：

- E11 + E9 targeted tests：8/8 通过。
- Node helper tests：4/4 通过。
- `node --check` 通过。
- targeted `ruff check` 通过；仅有 repo 既有 top-level ruff config deprecation warning。
- `compileall`、`make deps-check`、`git diff --check` 通过。
- Playwright CLI browser smoke 通过：本地 FastAPI static/SSE stub 下，Chat Stream 显示 `trace-smoke-chat` / `request-smoke-chat`、content/tool/done；AIOps 显示 `trace-smoke-aiops` / `request-smoke-aiops`、plan/report/complete；browser console 0 errors / 0 warnings。

### 边界

- 不修改 `/api/chat_stream` 或 `/api/aiops` 后端事件语义。
- 不修改 `docs/enterprise_sse_event_contract.md` 的 E9 frozen contract。
- 不替换旧 `/` 静态前端；新页面通过 `/static/enterprise-dashboard.html` 访问。
- 不把 Vue3 阶段扩展成管理 UI、权限 UI 或 DB UI。

### 阶段收口

- E11 实现提交：`28a8e28ddcca8d4c743061c0cd17ed5af8906a2f` (`enterprise(e11): add vue execution dashboard`)。

## 2026-05-31 (Enterprise 2.0 F4 structured verifiers)

- F4 这一步不是再加一个“智能判断”层，而是把关键输出前的确定性自检显式化：`PlanVerifier`、`CitationVerifier`、`SqlResultVerifier` 和 `VerificationService` 组成统一的 verifier MVP。这样 audit 能追踪“为什么判定通过/失败”，但不会把长链式思维塞进 trace。
- `AIOpsAdapter` 在显式 `task_contract` 场景下，对 `plan` 事件做 `PlanVerifier` 检查，失败时返回结构化 `error` 事件并终止后续流式输出；`RagAdapter` 在 retrieval 后对 `source_ref` 做 citation verifier audit；`DatabaseDemoToolProvider` 在 `safe_select` 后用 `SqlResultVerifier` 检查 SafeSqlKernel provenance 和授权列。
- `SafeSqlKernel` 的成功返回显式补了 `safe_sql_verified=True`，让 SQL 自检不需要靠隐式约定猜 provenance。`CitationVerifier` 只看结构化 `source_ref.doc_id`，不看展示文本 `citation_text`，避免把 UI 文本误当证据。
- 验证覆盖：
  - `tests/test_enterprise_verifiers.py`
  - `tests/test_enterprise_rag_upload_e5.py`
  - `tests/test_enterprise_database_e6.py`
  - `tests/test_enterprise_database_e7.py`
  - `tests/test_enterprise_task_contract.py`
  - `tests/test_enterprise_trace_eval.py`
  - `tests/test_enterprise_*.py`
  - `uv run ruff check app/enterprise/verifiers app/enterprise/adapters/aiops_adapter.py app/enterprise/adapters/rag_adapter.py app/enterprise/database/provider.py app/enterprise/database/safe_sql.py tests/test_enterprise_verifiers.py`
  - `uv run python -m compileall -q app tests evals`
  - `make deps-check`
  - `git diff --check`
- 阶段边界：不改旧 planner 内部，不做无限修订循环，不把 citation_text 当作授权依据，不绕开 SafeSqlKernel / PermissionService / task contract 这些已有边界。
- 实现提交：`6ee1744 enterprise2(f4): add structured verifiers mvp`。

### 面试追问怎么答

**追问：为什么 E11 不顺手改 SSE 协议，让前端更好写？**

答：E11 的前置条件就是 E9 已经冻结事件协议。前端只需要 `type/trace_id/request_id/stage/status/message/data` 就能展示执行过程；如果 E11 再改后端语义，会把“展示层升级”变成前后端协议重构，破坏 E9 的验收边界。

## 2026-05-31 (Enterprise 2.0 F5 unified failure handling)

### 为什么现在做

F2/E9 已经有 request audit、trace 和 SSE envelope，F4 又把关键输出前的 verifier 结果结构化。F5 的目的不是改业务路径，而是把失败从“原始异常名 + generic error”收敛成稳定的企业侧错误合同：前端能展示，audit 能区分安全阻断 / 系统失败 / 降级完成，后续 F6/F3/F8 能复用同一套决策字段。

### 代码变更

- 新增 `app/enterprise/errors/*`：
  - `models.py`：定义 `ErrorClass`、`ErrorContext`、`RecoveryDecision`、`RecoveryPlan`。
  - `recovery.py`：实现确定性 `RecoveryStrategy.decide()`。
  - `mapper.py`：提供异常到 error class 的映射、audit metadata 和 SSE error event helper。
  - `exceptions.py`：提供携带 recovery metadata 的 `EnterpriseError`。
- `RequestGateway` 的 `request_failed` audit 顶层 `error_class` 改为 F5 稳定分类，原始异常类保留到 `metadata.source_error_class`。
- `ChatAdapter` / `AIOpsAdapter` 的 blocked stream path 输出稳定 `error` envelope，不再只返回字符串。
- `ModelGateway` 的 fallback success 写 `decision=degraded`、`error_class=model_unavailable`、`recovery_decision=fallback`；所有 endpoint 失败写 `recovery_decision=abort`。
- `ToolGateway` 的执行失败写 `error_class=tool_failed` 和 user-safe `user_message`，未授权工具写 `permission_denied`。
- `SafeSqlKernel`、`DatabaseSandboxService`、`DatabaseDemoToolProvider` 的阻断 audit 写 `error_class=sql_blocked`，不对 SQL 安全阻断做自动恢复。
- `docs/enterprise_sse_event_contract.md` 增加 F5 error envelope，失败事件必须携带 `error_class`、`decision`、`user_message`。

### 验收结果

已运行：

```text
uv run pytest -q tests/test_enterprise_error_recovery.py
uv run pytest -q tests/test_enterprise_request_gateway.py tests/test_enterprise_gateway_routes.py tests/test_enterprise_model_gateway.py tests/test_enterprise_tool_gateway.py tests/test_enterprise_database_e6.py tests/test_enterprise_database_e7.py tests/test_enterprise_observability_e9.py tests/test_enterprise_task_contract.py tests/test_enterprise_verifiers.py tests/test_enterprise_error_recovery.py
uv run pytest -q tests/test_enterprise_*.py
uv run ruff check app/enterprise/errors app/enterprise/gateway/request_gateway.py app/enterprise/models/gateway.py app/enterprise/tools/gateway.py app/enterprise/database/safe_sql.py app/enterprise/database/service.py app/enterprise/database/provider.py app/enterprise/adapters/chat_adapter.py app/enterprise/adapters/aiops_adapter.py app/api/chat.py app/api/aiops.py app/enterprise/observability/sse_contract.py tests/test_enterprise_error_recovery.py tests/test_enterprise_request_gateway.py tests/test_enterprise_gateway_routes.py tests/test_enterprise_model_gateway.py tests/test_enterprise_tool_gateway.py
uv run python -m compileall -q app tests evals
make deps-check
git diff --check
```

结果：

- F5 targeted tests：20/20 通过。
- 受影响 gateway/model/tool/db/SSE/task/verifier 回归：54/54 通过。
- `tests/test_enterprise_*.py` 全部通过。
- targeted `ruff check` 通过；仅有 repo 既有 top-level ruff config deprecation warning。
- `compileall`、`make deps-check`、`git diff --check` 通过。

### 边界

- 不对安全阻断做 retry/fallback。
- 不把所有错误归成 generic error；也不直接把 Python 原始异常名暴露为企业错误合同。
- 不新增无限恢复循环；F5 只记录恢复决策，不改变旧 planner/retrieval/tool 调用策略。
- 不接真实 DB；DB 仍只在 sandbox/database-demo 权限路径内。

### 阶段收口

- F5 实现提交：`c9646ef enterprise2(f5): add structured error recovery`。

## 2026-05-31 (Enterprise 2.0 F6 human review MVP)

### 为什么现在做

F1 已经能创建 task contract 并把高风险任务挡在执行前；F5 已经把失败和恢复决策结构化。F6 的目的不是做一个聊天里的“是否确认”提示，而是把高风险、低置信度或审批型任务变成可查询、可审计、可由 Admin approve/reject 的 human review workflow。

第一版只做“阻断、登记、审批、审计”。审批通过后的执行方式采用重新提交同一 `task_id` / `review_id`，不做 checkpointer resume，也不试图恢复原 trace 内部运行时状态。

### 代码变更

- 新增 `app/enterprise/reviews/*`：
  - `models.py`：定义 `HumanReviewRequest`、`HumanReviewDecision`、`ReviewStatus` 和 `RiskDetectionResult`。
  - `risk_detector.py`：实现确定性风险触发规则，覆盖 high/critical、显式审批、DB 写请求、敏感文档、授权变更、疑似 PII、低置信度生产影响。
  - `repository.py`：提供 in-memory 和 SQLite review repository，支持 create/get/get_by_task/list_pending/update。
  - `service.py`：提供 `register_pending_review()`、`approve()`、`reject()`，并写 `human_review_requested` / `human_review_approved` / `human_review_rejected` audit。
- 新增 `app/api/admin_reviews.py`，暴露：
  - `GET /api/admin/reviews/pending`
  - `POST /api/admin/reviews/{review_id}/approve`
  - `POST /api/admin/reviews/{review_id}/reject`
- `app/main.py` 挂载 admin review router；所有 review admin API 复用 E8 的 admin role dependency。
- `app/models/aiops.py` 在 task contract input 上增加 `task_id` / `review_id`，作为 F6 重新提交同一任务的定位字段。
- `app/enterprise/adapters/aiops_adapter.py` 在显式 task contract 路径上接入 human review：
  - 新任务命中风险时返回 SSE `pending_approval`，登记 review，不调用旧 AIOps service。
  - 带 approved `review_id` / `task_id` 的重提请求会以原 `task_contract_id` 执行。
  - rejected review 重提时返回 `stage=human_review,status=rejected` 的结构化 error，不进入执行。
- `docs/enterprise_sse_event_contract.md` 补充 `pending_approval` event，保持 E9 envelope 和 F5 error envelope 兼容。

### 验收结果

已运行：

```text
uv run pytest -q tests/test_enterprise_human_review.py
uv run pytest -q tests/test_enterprise_human_review.py tests/test_enterprise_task_contract.py tests/test_enterprise_admin_e8.py tests/test_enterprise_gateway_routes.py tests/test_enterprise_request_gateway.py
uv run pytest -q tests/test_enterprise_*.py
uv run ruff check app/enterprise/reviews app/api/admin_reviews.py app/enterprise/adapters/aiops_adapter.py app/models/aiops.py tests/test_enterprise_human_review.py
uv run python -m compileall -q app tests
make deps-check
git diff --check
```

结果：

- F6 targeted tests：6/6 通过。
- 受影响 admin/task/gateway 回归：26/26 通过。
- `tests/test_enterprise_*.py` 全部通过。
- targeted `ruff check` 通过；仅有 repo 既有 top-level ruff config deprecation warning。
- `compileall`、`make deps-check`、`git diff --check` 通过。

### 边界

- 不做聊天里的临时确认句。
- 不绕过 PermissionService；F6 只在 task contract / AIOps adapter 边界增加审批门。
- 不实现 DB 写操作；DB 写请求只是风险触发信号。
- 不把 database tools 放入默认 AIOps/RAG 工具池。
- 不实现 checkpointer resume；审批后用 `review_id` / `task_id` 重新提交同一任务。

### 阶段收口

- F6 实现提交：`814d9cc enterprise2(f6): add human review mvp`。

## 2026-05-31 (Enterprise 2.0 F3 strategy routing shadow)

### 为什么现在做

F1 已经让 task contract 成为显式输入，F5 已经把失败和恢复决策结构化，F6 已经给高风险任务一条 human-review 路径。F3 此时只需要补“可解释路由建议”这一层观测能力：chat / rag / aiops / database / admin / human_review 都能被评分和审计，但不改变现有主路径。

### 代码变更

- 新增 `app/enterprise/routing/*`：
  - `models.py`：定义 `RoutingDecision`、`RoutingComparisonReport` 和 confusion case 模型。
  - `providers.py`：实现 `RuleRoutingProvider`、`KeywordRoutingProvider`、`LlmShadowRoutingProvider`。
  - `router.py`：实现 `StrategyRouter.record_shadow_decision()` 和 `build_routing_comparison_report()`。
- `RuleRoutingProvider` 第一版覆盖 admin、database、high-risk、AIOps、RAG 和 chat。高风险 task contract 会建议 `human_review`；数据库意图只建议 route，不执行 SQL。
- `KeywordRoutingProvider` 只做轻量关键词 shadow；`LlmShadowRoutingProvider` 是 disabled placeholder，不调用网络 LLM。
- `ChatAdapter` 和 `AIOpsAdapter` 在 RequestGateway guardrail 通过后写 `routing_decision` audit。旧 RAG / AIOps service 调用路径、响应结构、工具池和 human-review 执行门都不改变。
- 新增 `tests/test_enterprise_strategy_router.py`，覆盖 route 分类、shadow audit、comparison report，以及 chat/AIOps response 不变。

### 验收结果

已运行：

```text
uv run pytest -q tests/test_enterprise_strategy_router.py
uv run pytest -q tests/test_enterprise_gateway_routes.py tests/test_enterprise_request_gateway.py tests/test_enterprise_human_review.py tests/test_enterprise_task_contract.py
uv run pytest -q tests/test_enterprise_*.py
uv run ruff check app/enterprise/routing app/enterprise/adapters/chat_adapter.py app/enterprise/adapters/aiops_adapter.py tests/test_enterprise_strategy_router.py
uv run python -m compileall -q app tests evals
make deps-check
git diff --check
```

结果：

- F3 targeted tests：4/4 通过。
- 受影响 gateway/request/human-review/task-contract 回归：20/20 通过。
- `tests/test_enterprise_*.py` 全部通过。
- targeted `ruff check` 通过；仅有 repo 既有 top-level ruff config deprecation warning。
- `compileall`、`make deps-check`、`git diff --check` 通过。

### 边界

- shadow only，不改变用户响应或实际 route。
- 不做多 Agent 协调器。
- 不让路由器直接执行工具。
- 不新增网络 LLM router。
- DB 请求仍不能绕过 SafeSqlKernel。
- promote 条件未满足：当前没有 100 条覆盖样本，也没有团队设定的 route match rate 阈值，因此 F3 不能进入默认路径。

### 阶段收口

- F3 实现提交：`17a99bd enterprise2(f3): add strategy routing shadow`。

## 2026-05-31 (Enterprise 2.0 F7 advanced guardrail trigger audit)

### 为什么只做 evidence-only

F7 在详细设计里是 gated 阶段：只有 audit 出现 PII / 敏感输出风险样本、业务明确提出 DLP/content safety 审计，或 F2/F4/F5 报告证明当前规则 guardrail 不足时，才应实现高级 provider。当前没有这些触发条件。

### 已读取证据

- `logs/enterprise_audit.jsonl` 当前有 56 条本地审计记录。
- 对 `logs/enterprise_audit.jsonl` 和 `logs/app_2026-05-31.log` 执行 PII / sensitive regex 搜索，没有命中。
- `logs/enterprise_audit.sqlite` 当前只有 `request_started`、`request_completed`、`request_failed`、`upload_saved` 这几类本地记录；查询 `pii` / `sensitive` / `敏感` 返回空。
- F2/F4/F5 记录没有证明现有规则 guardrail 不足；已有证据只是计划性提到 F7 可做 PII/output shadow。

完整证据记录见 `docs/enterprise2_f7_guardrail_trigger_audit.md`。

### 决策

- 不实现 PII regex provider。
- 不实现 output DLP / content-safety provider。
- 不把 LLM-as-Judge 放进 shadow 或热路径。
- 不改变 E2 RequestGateway guardrail 和 E9 SSE / trace 行为。

后续若要重启 F7，必须先提供真实或模拟且可复核的 PII / sensitive-output 样本，或者明确合规需求，并建立误报 / 漏报复核记录。

### 阶段收口

- F7 evidence-only 提交：`d5c6d9e enterprise2(f7): record guardrail trigger audit`。

## 2026-05-31 (Enterprise 2.0 F8 resource trigger audit)

### 为什么只做 evidence-only

F8 也是 gated 阶段。它需要稳定的 latency / token / tool / DB 指标和明确成本或延迟瓶颈，才能开始改变模型、检索、DB 或工具策略。当前只有前置能力存在，缺少真实优化触发证据。

### 已读取证据

- `logs/enterprise_audit.sqlite` 当前本地 snapshot 只有 `request_started`、`request_completed`、`request_failed`、`upload_saved` event groups。
- 查询 `database_query`、`tool_call`、model event、token、usage、row_count、fallback、degraded 等资源指标返回 0。
- 当前本地 enterprise audit latency 很小：`request_completed` max `5.179 ms`，`request_failed` max `1.635 ms`。
- 日志和文档搜索能看到 E10 的 MCP metrics / replanner timeout 历史，但这些不是当前 F8 的稳定 enterprise audit 资源基线，也没有指向默认策略应调整的具体瓶颈。

完整证据记录见 `docs/enterprise2_f8_resource_trigger_audit.md`。

### 决策

- 不新增 `app/enterprise/resources/*`。
- 不新增 budget enforcement 或 `StrategySelector`。
- 不改公开 request schema。
- 不改默认模型、检索、DB 或工具策略。

后续若要重启 F8，必须先积累稳定 token/tool/DB/resource audit 基线，并指出具体瓶颈和优化前后对照方式。

### 阶段收口

- F8 evidence-only 提交：`297a45f enterprise2(f8): record resource trigger audit`。

## 2026-06-02 (Database operation capability permission model)

### 为什么现在补充

Post-Stage-6 C2 已经把 `safe_select` 暴露成真实 HTTP 入口，但它仍是只读能力。继续讨论数据库写入、删除和 DDL 前，需要先把“操作权限、用户确认、管理员后台”三者边界写清楚，避免后续把数据库操作确认误做成权限管理审批，或把后台权限管理开放给普通用户。

### 决策

- 数据库操作和权限管理分开。
- 只读查询和元数据查看仍然直接执行，不需要确认，但必须继续经过 ToolGateway、PermissionService、表列 allowlist、SQL AST 校验和 audit。
- `INSERT`、`UPDATE`、批量导入、数据修复、回填等写入/修改类操作需要进入用户后台确认。
- `DELETE`、`TRUNCATE`、`DROP TABLE`、`ALTER TABLE DROP COLUMN` 等删除类操作也进入用户后台确认。
- 确认动作不是一套额外审批权限。只有一类操作权限：`database_operation/<database_id>.<operation_type>/execute`。例如用户有 `database_operation/sandbox_sales.delete/execute`，就可以发起对应库的删除类操作并到自己的后台确认；没有对应 operation resource 时直接拒绝，不生成确认项。
- 授权、撤权、角色、部门 scope、资源 scope 属于管理员专职后台，不进入普通用户数据库操作确认流。

### 文档落点

新增 `docs/数据库操作能力.md`，作为后续数据库操作能力的分级和确认方案。该文档明确当前代码只支持 sandbox/database-demo 只读链路；C2 commit `201252e` 的 `POST /api/database/safe-select` 只覆盖 L1 只读查询的 HTTP 产品面，写入、删除和 DDL 仍是后续实现，不应被误读为已经可执行。

### 后续实现边界

后续如果实现写入或删除能力，必须先补：

- 操作分类器，能区分 L1/L2 只读、L3 写入修改、L4 删除、L5 DDL。
- 操作权限模型必须落到 `database_operation/<database_id>.<operation_type>/execute`，不新增 `database_update` / `database_delete` / `database_ddl` 这种全局平行权限。
- 用户后台确认项，绑定 SQL hash、参数 hash、目标表列、dry-run 摘要和过期时间。
- 执行前复核，确认权限、SQL hash、参数 hash、目标范围和 dry-run 摘要未变化。
- 完整审计，区分数据库操作 audit 和管理员后台权限管理 audit。

### 执行清单

补充 `docs/数据库操作能力执行步骤清单.md`，把上面的能力分级拆成可执行阶段：

- DB-Ops-0 / DB-Ops-1 固化当前只读边界，明确 C2 已完成，不重新开工。
- DB-MySQL-1 明确下一步优先接入 MySQL 做真实只读验证，只开放 L1/L2，不顺手开放写入、删除或 DDL。
- DB-Ops-2 只在需要 function calling 时给 `ToolDefinition` 增加 `input_schema` / strict schema 输出。
- DB-Ops-3 先做 SQL 操作分类器，避免后续靠字符串判断 SQL 风险。
- DB-Ops-4 再设计 `database_operation` 权限资源，避免 update / delete / ddl 语义变成全局平行权限系统。
- DB-Ops-5 先冻结 dry-run 和影响评估方案，特别说明 MySQL 不能沿用 SQLite dry-run。
- DB-Ops-5.5 先冻结 confirmation lifecycle、expiration、cleanup、failed、retry、multi-table permission、SQL hash version、audit retention 以及 Stage 5 / F6 边界。
- DB-Ops-6 到 DB-Ops-8 才进入 prepare confirmation、用户后台确认和 confirm 后执行管线；confirmation 第一版必须使用 SQLite 持久化，不再把内存仓库作为正式方案。
- DB-Ops-9 / DB-Ops-10 收口 audit、测试和真服务 smoke。

这份清单仍是文档计划，不代表 L3-L5 已实现；马上接入 MySQL 时，应先按 DB-MySQL-1 做真实只读验证。后续如果正式做写入、删除或 DDL，应从 DB-Ops-3 操作分类器、DB-Ops-4 权限资源模型和 DB-Ops-5 dry-run 方案开始，不应直接写用户后台 UI 或执行 SQL。

### 评审 follow-up

收到合并评审后，补齐两份文档之间的口径差异：

- `docs/数据库操作能力.md` 不再把 `database_delete` / `database_update` 写成粗粒度全局权限，而是统一到 `database_operation/<database_id>.<operation_type>/execute`。
- C2 只读 HTTP 入口标注 commit `201252e`，明确它已经完成，但只覆盖 L1 `safe_select`。
- dry-run 明确分 SQLite sandbox 和 MySQL：MySQL 下一阶段只做 L1/L2 真实只读验证，不继承 SQLite 的事务预演假设。
- confirmation 第一版必须持久化，补充 expiration、cleanup、failed、retry、SQL hash version、audit retention 和多表权限规则。
- Stage 5 permission request 是申请权限，F6 HITL 是任务治理；用户后台 confirmation 是已有权限后的执行确认，三者不能互相替代。
- MySQL provider 与 sandbox provider 采用共存模型，分别使用不同 `database_id` 和 tool resource_id 前缀；现有 `SafeSqlKernel` 仍是 SQLite sandbox kernel，MySQL 需要独立 dialect-aware read-only kernel，而不是直接复用 `read="sqlite"`。
- DB-Ops-2 / DB-Ops-5 / DB-Ops-5.5 的阶段性写法是设计 gate，不是代码实现完成度；DB-MySQL-1 仍是当前优先开工项。
- DB-Ops-7 需要有前端文件计划，至少覆盖普通用户入口、状态列表和 confirm/cancel 交互，不能只停留在接口级。

## 2026-06-02 (DB-MySQL-1 read-only provider code-ready)

### 为什么现在做

数据库操作能力文档已经明确“马上要接入 MySQL 做真实数据库验证”，但不能直接从 sandbox SQLite 跳到写入、删除或 DDL。DB-MySQL-1 本轮只把 L1/L2 只读链路接到 MySQL provider：真实执行仍走 ToolGateway、PermissionService、表列 allowlist、MySQL dialect SQL kernel 和 database_query audit；L3-L5 confirmation、operation 权限和写操作仍不实现。

### 本轮变更

- `pyproject.toml` / `uv.lock`：加入 `pymysql`，让真服务配置到位后能连接 MySQL。
- `app/config.py`：新增 `enterprise_mysql_*` 配置，包括 enabled、database_id、host、port、database、username、password、timeout、pool_size、limit 和 allowlist JSON。
- `app/enterprise/database/mysql.py`：新增 `PooledMySqlReadonlyConnector`、`build_mysql_provider_from_config()` 和 allowlist registry parser；完善 `MySqlSafeSqlKernel` 的 MySQL dialect、`LIMIT` 上限、locking read 阻断和 audit。
- `app/enterprise/database/routes.py`：`build_database_tool_gateway()` 默认仍创建 sandbox provider；只有 `enterprise_mysql_enabled=true` 且 MySQL 配置/allowlist 完整时，才附加 `DatabaseMySqlToolProvider`。
- `app/enterprise/database/permissions.py`：`DatabasePermissionFilter` 保留 dialect 参数，MySQL provider 使用 `dialect="mysql"` 解析权限目标。
- `tests/test_enterprise_database_mysql.py`：覆盖 MySQL `safe_select` HTTP 分发、DML/DDL 阻断、超限 LIMIT 阻断、`FOR UPDATE` 阻断、只读连接器事务包裹、配置构建 provider、list/describe 权限过滤和默认 gateway 附加 provider。
- `tests/test_enterprise_database_http.py`：保留 C2 兼容测试，确认不传 `database_id` 仍走 `sandbox_sales`，未知 database_id 不回落到 sandbox。

### 代码级证据

- MySQL 工具 ID 使用 `database_mysql.<database_id>.list_tables`、`database_mysql.<database_id>.describe_table`、`database_mysql.<database_id>.safe_select`，不复用 `database_demo.*`。
- `MySqlSafeSqlKernel._parse_one()` 使用 `sqlglot.parse(..., read="mysql")`，不再沿用 SQLite dialect。
- `MySqlSafeSqlKernel._validate_select()` 只允许单条非锁定 `SELECT`，新增 `locking_select_not_allowed`，因此 `SELECT ... FOR UPDATE` 不会进入连接器。
- `MySqlSafeSqlKernel._build_sql_with_limit()` 对已有 `LIMIT` 做上限检查，超过 `max_limit` 返回 `limit_exceeds_max`，不会把 `LIMIT 999` 传给 MySQL。
- `PooledMySqlReadonlyConnector.execute_readonly()` 每次执行顺序为 `START TRANSACTION READ ONLY` -> sanitized SQL -> `COMMIT`，异常时 rollback；连接池懒创建且固定上限。
- `build_mysql_provider_from_config()` 在缺 enabled、host、database、username 或 allowlist 时返回 `None`，所以未配置 MySQL 不会影响现有 sandbox route。

### 风险和处理

- 风险：MySQL provider 被默认暴露到 AIOps/RAG 工具池。处理：只挂在 `app/enterprise/database/routes.py` 的显式 database gateway，不改全局 `config.mcp_servers`，不把通用 database MCP server 放入默认工具池。
- 风险：MySQL `SELECT ... FOR UPDATE` 名义上是 SELECT 但会加锁。处理：读取 sqlglot MySQL AST 的 `locks` 参数并在 kernel 阶段阻断。
- 风险：配置打开后不小心替代 sandbox。处理：sandbox provider 始终先注册；MySQL provider 只在配置完整时附加，`database_id` 分发不传仍是 `sandbox_sales`。
- 风险：自动化 fake connector 通过但真库仍未验证。处理：文档状态写为 `code-ready`，不标记 DB-MySQL-1 完成；真实 MySQL 只读账号、allowlist、grant 和 curl smoke 仍是退出条件。

### 验证

已运行：

```text
uv run pytest tests/test_enterprise_database_mysql.py -q
uv run pytest tests/test_enterprise_database_http.py -q
```

结果：

- MySQL targeted tests：8/8 通过。
- C2 HTTP 回归：8/8 通过。
- 已验证 PyMySQL 依赖安装并锁定，`pymysql==1.2.0`。

待执行：

- 真实 MySQL 只读账号 smoke：配置 `enterprise_mysql_*` 和 allowlist 后，用普通用户 grant MySQL tool/table/column 资源，再通过 `/api/database/safe-select` 验证授权 SELECT、未授权列拒绝、`UPDATE` / `DELETE` / `DROP TABLE` / `FOR UPDATE` 阻断和 audit。

### 面试追问怎么答

**追问: 为什么 MySQL 第一版没有直接做 UPDATE/DELETE/DROP？**

答：

> 因为这一步的目标是把现有 L1/L2 只读治理链路从 SQLite sandbox 验证到真实 MySQL，而不是扩写操作能力。我们先保证 MySQL provider、database_id、权限、allowlist、dialect、连接器和 audit 都能在只读路径上成立；写入、删除和 DDL 要进入后续 DB-Ops-3 到 DB-Ops-8，包括操作分类、operation 权限、dry-run、confirmation lifecycle 和执行前复核。这样不会把“真实 MySQL 能 SELECT”误读成“真实 MySQL 可以写库”。

## 2026-06-02 (DB-MySQL-1 live smoke closeout)

### 为什么继续做

DB-MySQL-1 代码已经通过自动化测试，但还没有跑真实 MySQL 凭据 smoke。用户已经拉取并启动本地 MySQL 8.0 容器，本轮目标是用真实 FastAPI + Milvus + MySQL 服务确认 MySQL L1/L2 只读链路，不进入写入、删除、DDL 或 confirmation flow。

### 过程中发现的问题

1. MySQL provider 已能挂到 `/api/database/safe-select`，但 Admin resource catalog 仍只暴露 `database_demo.*` 和 `sandbox_sales.*`。结果是 `/api/admin/grants` 给 `database_mysql.mysql_sales_readonly.safe_select` 授权时返回 `Grant validation failed: resource_exists`。修复方式不是放松 `GrantValidator`，而是让 `ResourceCatalogService` 在 `enterprise_mysql_enabled=true` 且 allowlist 完整时，把 MySQL registry 转成 tool/table/column 资源。
2. 真实 PyMySQL 返回的 `DECIMAL` 值是 Python `Decimal`。`MySqlSafeSqlKernel.safe_select()` 在计算 `result_size_bytes` 时直接 `json.dumps(masked_rows)`，导致 TypeError 并返回 `database_execution_failed`。修复方式是在 `_mask_rows()` 边界把 MySQL 返回值转成 JSON-safe 值，`Decimal` 以字符串返回，避免精度丢失。

### 本轮变更

- `app/enterprise/database/mysql.py`：新增 `build_mysql_registry_from_config()`，让 provider 构建和 Admin catalog 使用同一个 MySQL allowlist registry 解析路径；`_mask_rows()` 返回 JSON-safe rows，支持 `Decimal`、日期时间和 bytes。
- `app/enterprise/admin/resources.py`：新增 MySQL registry 列表，默认配置启用时自动暴露 `database_mysql.<database_id>.list_tables/describe_table/safe_select`、`database_table` 和 `database_column` 资源；sandbox catalog 保持不变。
- `tests/test_enterprise_database_mysql.py`：新增 Admin catalog MySQL resource 测试和 MySQL `Decimal` 序列化测试，锁定两个 live smoke 发现的问题。

### 验证

已运行：

```text
uv run pytest tests/test_enterprise_database_mysql.py tests/test_enterprise_admin_e8.py tests/test_enterprise_database_http.py -q
uv run ruff check app/enterprise/admin/resources.py app/enterprise/database/mysql.py tests/test_enterprise_database_mysql.py tests/test_enterprise_database_http.py
uv run python -m compileall -q app/enterprise/admin/resources.py app/enterprise/database/mysql.py tests/test_enterprise_database_mysql.py tests/test_enterprise_database_http.py
```

结果：

- 自动化回归：33/33 passed。
- Ruff：All checks passed（仅既有 top-level lint 配置弃用 warning）。
- compileall：通过。

真服务 smoke：

- Docker MySQL 8.0 容器初始化 `sales.orders`；只读账号可 `SELECT`，直接 `UPDATE` 被 MySQL 权限拒绝。
- FastAPI 以 `enterprise_mysql_*` 环境变量启动，Milvus 和 MySQL 均连接成功。
- `/api/admin/resources` 暴露 MySQL tool/table/column 资源；`/api/admin/grants` 成功授予 `demo_user_dept1` MySQL safe_select、orders table、order_id/total_amount columns。
- curl trace `mysql-live-smoke-20260602132804` 覆盖：未授 DB tool 的账号 403 `default_deny`；授权 SELECT 200 并返回 `total_amount` 字符串；未授权列 403 `database_column_denied`；未知表 403 `unauthorized_table`；`UPDATE` / `DROP TABLE` 403 `non_select_statement_not_allowed`；`SELECT ... FOR UPDATE` 403 `locking_select_not_allowed`。
- 同 trace 的 `database_query` audit 包含 1 条 allowed 和 5 条 denied，均带 `database_id=mysql_sales_readonly`、`dialect=mysql`。

### 面试追问怎么答

**追问: 为什么 live smoke 会发现自动化测试没覆盖的问题？**

答：

> 自动化测试里 MySQL HTTP 用的是注入的 fake gateway，权限 grant 直接写 `PermissionService`，所以能证明 provider / kernel / route 逻辑，但没有证明真实 Admin API 能授 MySQL 资源。真实 smoke 通过 `/api/admin/grants` 走了 `GrantValidator.resource_exists`，才暴露 Admin catalog 没包含 MySQL allowlist 资源。另一个差异是 fake connector 返回 float，而 PyMySQL 对 DECIMAL 返回 Decimal，所以真实库才暴露 JSON 序列化问题。修复后我们把这两个差异都变成了回归测试。

## 2026-06-02 (DB-Ops-5/5.5 L3-L5 design gate closeout)

### 为什么现在做

用户明确要求“开 L3-L5”，但也明确纠正：L3-L5 不能直接写代码，必须先做 DB-Ops-5/5.5 设计 gate。原因是 DB-MySQL-1 只证明真实 MySQL L1/L2 只读链路成立；写入、删除和 DDL 的风险面不同，必须先冻结 dry-run、影响评估、confirmation 生命周期、失败恢复、重放防护和审计边界。

### 本轮变更

- `docs/数据库操作能力执行步骤清单.md`：DB-Ops-5 / DB-Ops-5.5 从 pending 改为 `completed (design gate)`，并把待决问题改成明确决策。
- `docs/数据库操作能力.md`：同步总方案口径，说明 L3-L5 gate 已冻结，但没有写入、删除或 DDL 运行时代码。
- `PROJECT_STATE.md` / `task_plan.md` / `progress.md`：同步当前状态和下一步，明确后续代码只能从 DB-Ops-2 tool schema 或 DB-Ops-3 SQL 操作分类器开始，不能跳到 DB-Ops-6 prepare/confirm。

### 冻结的 dry-run / 影响评估决策

- 用户可见 dry-run 不默认使用“执行后 rollback”。SQLite sandbox 的 rollback 型预演只允许作为 sandbox-only 实验或测试，不得宣称无副作用，因为它仍可能触发 trigger、锁、自增 ID 消耗或其他副作用。
- MySQL L3-L5 不能沿用 SQLite rollback 方案。第一版 MySQL preview 只能走 read-only 路径：AST 分析、allowlist 检查、`SELECT COUNT(*)` 估算、schema metadata 摘要、`EXPLAIN FORMAT=JSON` 计划信息。
- `EXPLAIN` 只进入 `plan_summary`，不能写入 `estimated_affected_rows`。
- `UPDATE` / `DELETE` 的影响行数估算优先由 AST 重写出等价 `SELECT COUNT(*)`，但只表示直接命中的目标行；trigger、cascade、外键、索引维护和锁等待写入 `estimate_notes`。
- `INSERT ... VALUES` 用 values 行数估算；`INSERT ... SELECT` 只有 source SELECT 能被只读 kernel 安全验证时才给 count preview。
- DDL 只给 schema impact summary；`CREATE TABLE`、`ALTER TABLE`、`DROP TABLE` 都不能伪装成 affected rows。
- 无法可靠估算时必须写 `estimated_affected_rows=null`、`estimate_reliable=false` 和 `estimate_reason`，不能展示伪精确数字。
- DB-Ops-6 首个实现切片应优先在 sandbox / 非生产 writable fixture 上验证；真实 MySQL 写入、删除和 DDL 要等非生产 writable MySQL、备份/恢复说明、data owner、operation resource 和 smoke 计划齐备后再开。

### 冻结的 confirmation 生命周期决策

- 第一版 confirmation 使用 SQLite 持久化，不用内存仓库作为正式方案。
- 状态机为 `pending` / `confirmed` / `cancelled` / `expired` / `executing` / `executed` / `failed`。
- `pending` 默认 15 分钟 TTL；cleanup 把超时 pending 标为 `expired`，不是静默删除。
- `executing` 默认 2 分钟 deadline；超时未完成标为 `failed`，reason 为 `execution_timeout`。
- confirm 必须用原子条件更新抢占 pending，防止重复点击、并发请求和重放。
- `cancelled`、`expired`、`executed`、`failed` 是终态，不能再次 confirm。
- failed confirmation 默认不能复用；重试必须重新 prepare。
- confirmation 记录必须保存 SQL hash、参数 hash、`sql_hash_version`、`normalization_version`、dry-run 摘要、权限快照、trace_id 和 request_id。
- confirm 前重新校验 owner、operation 权限、table/column 权限、provider/database、allowlist、SQL hash、参数 hash、dry-run 摘要和过期状态。
- audit retention 和 confirmation cleanup 分开；清理 confirmation 不能删除 audit。

### 风险和处理

- 风险：把 DB-Ops-5/5.5 gate 误读成 L3-L5 已可执行。处理：所有状态文件都写明 docs-only，没有运行时代码。
- 风险：真实 MySQL 因为 DB-MySQL-1 smoke 通过就开放写库。处理：文档明确 MySQL L3-L5 第一版只能 read-only preview，写入/删除/DDL 需要非生产 writable fixture 和 owner/backup/smoke 前置。
- 风险：确认流退化成前端按钮安全。处理：confirm-time 必须后端复核 owner、权限、hash、allowlist、dry-run 摘要和状态。

### 验证

本轮是设计 gate，不运行代码测试。完成的校验是文档一致性和状态同步：

- `docs/数据库操作能力执行步骤清单.md` 中 DB-Ops-5 / 5.5 已从 pending gate 改为 completed design gate。
- `docs/数据库操作能力.md`、`PROJECT_STATE.md`、`task_plan.md`、`progress.md` 已同步“不写代码、只冻结 gate、下一步从 DB-Ops-2/3 开始”的口径。

### 面试追问怎么答

**追问: 为什么不直接从 MySQL UPDATE/DELETE 开始？**

答：

> DB-MySQL-1 只证明真实 MySQL 的只读治理链路成立，不能外推到写入、删除和 DDL。L3-L5 需要先冻结两类高风险语义：一是 dry-run 到底能不能可信地估算影响，二是用户确认项如何持久化、过期、失败、重放防护和审计。我们把 rollback dry-run 排除在用户可见默认方案之外，让 MySQL preview 只走 read-only count/schema/plan，并要求 confirm 时重新校验权限、hash 和 dry-run 摘要。这样后续写 DB-Ops-2/3/4/6 时不会边写边改安全语义。

## 2026-06-02 (DB-Ops-3 SQL operation classifier)

### 为什么现在做

DB-Ops-5/5.5 design gate 验收后，下一步有 DB-Ops-2 tool schema 和 DB-Ops-3 SQL classifier 两个入口。选择 DB-Ops-3 是因为它是数据库模块内的 standalone 能力，不改全局 `ToolDefinition`，也不触碰现有 tool/MCP 路径；DB-Ops-2 会影响所有 tool consumer，适合靠近 DB-Ops-6 prepare_operation 时再做。

### TDD 红绿过程

第一轮红灯：

```text
uv run pytest tests/test_enterprise_database_operation_classifier.py -q
```

失败原因：

```text
ModuleNotFoundError: No module named 'app.enterprise.database.operation_classifier'
```

实现最小模块后，核心分类用例转绿。随后补第二轮红灯：`SHOW TABLES` / `SHOW COLUMNS FROM orders` 仍被判为 `unknown`。补充 `exp.Show` handling 和 `SHOW COLUMNS` target 表名提取后，targeted tests 全绿。

### 本轮变更

- 新增 `app/enterprise/database/operation_classifier.py`。
- 新增 `tests/test_enterprise_database_operation_classifier.py`。
- 同步 `docs/数据库操作能力执行步骤清单.md`、`docs/数据库操作能力.md`、`PROJECT_STATE.md`、`task_plan.md`、`progress.md`。

### 代码级证据

- `DatabaseOperationClassification` 返回 `operation_level`、`operation_type`、`database_id`、`tables`、`columns`、`is_delete_like`、`requires_confirmation`、`denied_reason`。
- `classify_sql_operation(sql, database_id, dialect)` 使用 `sqlglot.parse(..., read=dialect)`，不是字符串包含匹配。
- `SELECT` 分类为 L1 / `select`。
- `EXPLAIN`、`SHOW`、`DESCRIBE` 分类为 L2 / `metadata`。
- `INSERT` / `UPDATE` 分类为 L3 且 `requires_confirmation=True`。
- `DELETE` / `TRUNCATE` / `DROP TABLE` / `ALTER TABLE DROP COLUMN` 分类为 L4，`is_delete_like=True`。
- `CREATE TABLE` / 非删除类 `ALTER TABLE` 分类为 L5。
- `GRANT` / `REVOKE` 分类为 M1，`denied_reason="permission_management_not_database_operation"`，不进入普通数据库操作确认流。
- parse failure / multi-statement 返回 unknown denied classification，不进入确认流。

### 边界

这不是 DB-Ops-6 prepare_operation：

- 没有新增 confirmation model。
- 没有新增 operation permission resource。
- 没有修改 `SafeSqlKernel` / `MySqlSafeSqlKernel`。
- 没有修改 `ToolGateway`、HTTP route 或 audit。
- 没有开放写入、删除或 DDL 执行。

分类器和 kernel 的关系保持不变：分类器只为后续路由判断提供基础分类，kernel 仍是只读执行前安全权威。后续如果分类器判 L1 但 kernel 因 JOIN、函数、未授权表列、锁定 SELECT 等原因阻断，必须以 kernel 阻断为准。

### 验证

已运行：

```text
uv run pytest tests/test_enterprise_database_operation_classifier.py -q
uv run pytest tests/test_enterprise_database_operation_classifier.py tests/test_enterprise_database_e6.py tests/test_enterprise_database_e7.py tests/test_enterprise_database_http.py tests/test_enterprise_database_mysql.py -q
uv run ruff check app/enterprise/database/operation_classifier.py tests/test_enterprise_database_operation_classifier.py
uv run python -m compileall -q app/enterprise/database/operation_classifier.py tests/test_enterprise_database_operation_classifier.py
```

结果：

- classifier targeted tests：13 assertions passed。
- database regression：53/53 passed。
- Ruff：All checks passed（仅既有 top-level lint 配置弃用 warning）。
- compileall：通过。

### 面试追问怎么答

**追问: 为什么分类器不直接复用 SafeSqlKernel？**

答：

> SafeSqlKernel 是只读执行前安全校验器，它的职责是决定某条 SELECT 能不能执行，比如单语句、allowlist、LIMIT、结果大小、敏感字段。DB-Ops-3 分类器的职责不同：它要在执行前判断 SQL 是 L1、L2、L3、L4、L5 还是 M1，用来决定未来是走只读 kernel、prepare confirmation，还是直接拒绝权限管理 SQL。两者不能合并，否则会把“能不能执行”跟“应该走哪条治理路径”混在一起。当前实现故意 standalone，不改变现有 safe_select 行为。

## 2026-06-02 (DB-Ops-4 operation permission resources)

### 为什么现在做

DB-Ops-3 已经能把 SQL 分成 L3/L4/L5，但还没有把这些分类映射到当前权限系统。DB-Ops-4 先做 operation 权限资源，是为了让后续 DB-Ops-6 prepare operation 只负责生成确认项和 dry-run 摘要，而不是同时补权限模型。

### TDD 红绿过程

第一轮红灯：

```text
uv run pytest tests/test_enterprise_database_operation_permissions.py -q
```

失败原因：

```text
ModuleNotFoundError: No module named 'app.enterprise.database.operation_permissions'
```

第二轮红灯：后台测试导入 `database_operation_resource_id` 失败，说明 operation resource helper 尚未落到既有 `database/permissions.py` 边界；随后 catalog/preview/scope 测试证明 Admin resource catalog 还没有 `database_operation`。

第三轮红灯：`INSERT INTO orders (order_id, total_amount)` 的 inserted columns 没被检查；`DELETE ... WHERE customer_id IN (SELECT id FROM customers ...)` 的多表列归属被旧逻辑过度保守处理。修复后，列权限检查改为基于 AST + registry 解析 owner table。

### 本轮变更

- `app/enterprise/database/permissions.py`
  - 新增 `DATABASE_OPERATION_RESOURCE_TYPE = "database_operation"`。
  - 新增 `DATABASE_OPERATION_EXECUTE_ACTION = "execute"`。
  - 新增 `database_operation_resource_id(database_id, operation_type)`。
- `app/enterprise/admin/resources.py`
  - `STAGE3_ACTIONS_BY_RESOURCE_TYPE` 支持 `database_operation: ["execute"]`。
  - Admin catalog 为 sandbox 和 enabled MySQL registry 暴露 `<database_id>.update`、`<database_id>.delete`、`<database_id>.ddl`。
- `app/enterprise/database/operation_permissions.py`
  - 新增 `DatabaseOperationPermissionChecker`。
  - L3 -> `update`，L4 -> `delete`，L5 -> `ddl`。
  - 先查 operation execute，再查 table read，再查 column read。
  - 支持 `INSERT` column list 和子查询 table/column owner 解析。

### 边界

这仍然不是 DB-Ops-6：

- 没有新增 confirmation 持久化模型。
- 没有新增 prepare/confirm HTTP API。
- 没有修改 `ToolGateway` 或 `safe_select` route。
- 没有修改 `SafeSqlKernel` / `MySqlSafeSqlKernel`。
- 没有开放写入、删除或 DDL 执行。

### 验证

已运行：

```text
uv run pytest tests/test_enterprise_database_operation_permissions.py tests/test_enterprise_admin_e8.py::EnterpriseAdminE8Tests::test_admin_resource_catalog_lists_indexed_documents_tools_and_database_resources tests/test_enterprise_admin_e8.py::EnterpriseAdminE8Tests::test_grant_preview_passes_for_database_operation_execute_resource tests/test_enterprise_admin_stage4_scope.py::EnterpriseAdminStage4ScopeTests::test_department_admin_can_grant_database_operation_only_inside_scope tests/test_enterprise_database_mysql.py::EnterpriseDatabaseMySqlTests::test_admin_resource_catalog_includes_mysql_resources_when_enabled -q
uv run pytest tests/test_enterprise_database_operation_classifier.py tests/test_enterprise_database_operation_permissions.py -q
uv run ruff check app/enterprise/admin/resources.py app/enterprise/database/operation_classifier.py app/enterprise/database/operation_permissions.py app/enterprise/database/permissions.py tests/test_enterprise_admin_e8.py tests/test_enterprise_admin_stage4_scope.py tests/test_enterprise_database_mysql.py tests/test_enterprise_database_operation_classifier.py tests/test_enterprise_database_operation_permissions.py
uv run python -m compileall -q app/enterprise/admin/resources.py app/enterprise/database/operation_classifier.py app/enterprise/database/operation_permissions.py app/enterprise/database/permissions.py tests/test_enterprise_admin_e8.py tests/test_enterprise_admin_stage4_scope.py tests/test_enterprise_database_mysql.py tests/test_enterprise_database_operation_classifier.py tests/test_enterprise_database_operation_permissions.py
```

结果：

- DB-Ops-4 targeted tests：9/9 passed。
- classifier + operation permission tests：19/19 passed。
- Ruff：All checks passed（仅既有 top-level lint 配置弃用 warning）。
- compileall：通过。

### 面试追问怎么答

**追问: 有 delete 权限为什么还要 table/column read 权限？**

答：

> `database_operation/<db>.delete/execute` 只说明用户被允许发起删除类操作的确认流程，不代表他可以触达任意表和列。删除语句里的目标表、WHERE、JOIN、子查询、RETURNING 仍可能引用敏感表列，所以 DB-Ops-4 保留最小授权面：operation 权限决定能不能进入高风险操作流程，table/column read 权限决定这条 SQL 触及的数据范围是否在用户可见范围内。这样不会因为用户有删除能力，就绕开已有表列 scope。

## 2026-06-02 (DB-Ops-2 tool schema foundation)

### 为什么现在做

DB-Ops-4 验收后，L3-L5 的分类器和 operation 权限边界都已经落地。继续 DB-Ops-6 prepare operation 前，还差 function calling 的 schema 承载点；如果直接写 prepare tool，会把 schema、权限、confirmation 持久化混在一个提交里。因此本轮先完成 DB-Ops-2，只做 tool schema 基础，不接执行路径。

### TDD 红绿过程

第一轮红灯：

```text
uv run pytest tests/test_enterprise_tool_schema.py -q
```

失败原因：

```text
ModuleNotFoundError: No module named 'app.enterprise.database.tool_schemas'
```

这证明当前没有 database tool input schema 模块，也没有可复用的 prepare schema。

第二轮红灯：实现 schema 模块后，MySQL provider fixture 用 `object()` 当 kernel，初始化 `DatabaseSandboxService` 时缺 `audit_service`。这是测试夹具问题，不是生产行为问题；修正为最小 `FakeKernel` 后进入绿色。

### 本轮变更

- `app/enterprise/tools/models.py`
  - `ToolDefinition` 新增 `input_schema: dict[str, Any] | None`。
  - `ToolDefinition` 新增 `strict: bool = True`。
- `app/enterprise/tools/schema.py`
  - 新增 `openai_function_name(tool)`。
  - 新增 `to_openai_function_tool(tool)` / `to_openai_function_tools(tools)`。
  - function name 使用 `resource_id` 规范化，而不是展示名 `name`，避免 sandbox / MySQL 工具都叫 `safe_select` 时冲突。
- `app/enterprise/database/tool_schemas.py`
  - 新增 `database_list_tables_input_schema()`。
  - 新增 `database_describe_table_input_schema()`。
  - 新增 `database_safe_select_input_schema()`。
  - 新增 `database_prepare_operation_input_schema()`。
- `app/enterprise/database/provider.py`
  - `database_demo.list_tables` / `describe_table` / `safe_select` 挂载严格 schema。
- `app/enterprise/database/mysql.py`
  - `database_mysql.<database_id>.list_tables` / `describe_table` / `safe_select` 挂载同一组严格 schema。

### 边界

这仍然不是 DB-Ops-6：

- 没有注册 `database_demo.prepare_operation` tool。
- 没有新增 confirmation 持久化模型。
- 没有新增 prepare/confirm HTTP API。
- 没有修改 `ToolGateway.execute()`、`POST /api/database/safe-select` 或 MCP provider 执行行为。
- `ToolDefinition.bindable_tool` 仍优先返回 `raw_tool`，MCP raw tool 不被本地 schema 包装破坏。
- 没有开放写入、删除或 DDL 执行。

### 验证

已运行：

```text
uv run pytest tests/test_enterprise_tool_schema.py -q
uv run pytest tests/test_enterprise_tool_schema.py tests/test_enterprise_tool_gateway.py tests/test_enterprise_database_e6.py tests/test_enterprise_database_e7.py tests/test_enterprise_database_http.py tests/test_enterprise_database_mysql.py -q
```

结果：

- DB-Ops-2 targeted tests：7/7 passed。
- tool gateway + database regression：52/52 passed。

### 面试追问怎么答

**追问: 为什么 OpenAI function name 不直接用 ToolDefinition.name？**

答：

> `ToolDefinition.name` 是展示名，多个 provider 可能相同，比如 sandbox 和 MySQL 都有 `safe_select`。function calling 需要稳定且唯一的函数名，否则模型返回 `safe_select` 时无法判断要执行哪个 provider。DB-Ops-2 用 `resource_id` 规范化生成 function name，例如 `database_demo.safe_select` 变成 `database_demo_safe_select`，`database_mysql.mysql_sales_readonly.safe_select` 变成 `database_mysql_mysql_sales_readonly_safe_select`。这样既满足 OpenAI function name 字符限制，又保留权限和审计里原有的 resource 边界。

## 2026-06-02 (DB-Ops-6 prepare operation backend)

### 为什么现在做

DB-Ops-2/3/4/5/5.5 已经把 prepare 所需的 schema、SQL 分类、operation/table/column 权限和 confirmation 生命周期语义冻结。继续 DB-Ops-6 的目标是把这些基础设施接成一个后端 prepare 入口，但仍然只生成确认项，不执行高风险 SQL。

这一步必须先于用户后台和 confirm 执行管线，否则前端会没有可信的 pending confirmation 数据源，也无法在 confirm 前复核 SQL hash、权限和 preview 摘要。

### TDD 红绿过程

第一轮红灯：

```text
uv run pytest tests/test_enterprise_database_operation_prepare.py -q
```

失败原因：

```text
AttributeError: module 'app.enterprise.database.routes' has no attribute 'database_operation_prepare_service'
```

这证明当前缺的是 DB-Ops-6 的真实 HTTP/service/repository 边界，而不是 classifier 或 permission checker。

随后按竖切片补测试：

- 有权限的 `UPDATE` 生成 `pending` confirmation，并且 `orders.total_amount` 不变。
- 无 operation 权限返回 403 `default_deny`，repository 为空。
- 缺 column 权限返回 403 `database_column_denied`，repository 为空。
- 有权限的 `DELETE` 生成 high risk confirmation，并且目标行仍存在。
- 有权限的 `DROP TABLE` 生成 high risk confirmation，`estimated_affected_rows=null`，表仍存在。

### 本轮变更

- `app/enterprise/database/confirmations.py`
  - 新增 `DatabaseOperationConfirmationStatus`，状态包含 `pending/confirmed/cancelled/expired/executing/executed/failed`。
  - 新增 `DatabaseOperationRiskSummary`。
  - 新增 `DatabaseOperationConfirmationRecord`，持有 `sql_hash`、`parameters_hash`、`sql_hash_version="dbops-sql-hash-v1"`、`normalization_version="sqlglot-normalize-v1"`、`created_at`、`expires_at`、目标表列和 risk summary。
  - 新增 `SQLiteDatabaseOperationConfirmationRepository`，表名为 `enterprise_database_operation_confirmations`，按 `user_id/status` 建索引。
  - 新增 `DatabaseOperationPrepareService`，先调用 `DatabaseOperationPermissionChecker.check_sql()`，再生成 preview、hash、TTL 和 confirmation。
- `app/enterprise/database/routes.py`
  - 新增 `DatabaseOperationPrepareRequest`。
  - 新增 `build_database_operation_prepare_service()` / `get_database_operation_prepare_service()`。
  - 新增 `POST /api/database/operations/prepare`。
- `app/config.py`
  - 新增 `enterprise_database_confirmation_sqlite_path`，默认 `logs/enterprise_database_confirmations.sqlite`。
- `tests/test_enterprise_database_operation_prepare.py`
  - 新增 5 条 HTTP prepare 行为测试。

### Preview 和权限边界

`UPDATE` / `DELETE` 的第一版 sandbox preview 没有执行原始 SQL，而是从 sqlglot AST 取目标表和 `WHERE`，生成 read-only `SELECT COUNT(*) FROM "<table>" WHERE ...`。这个查询只用于估算影响行数，不能替代 confirm-time 复核。

`DROP TABLE` 等无法可靠估算的操作不会返回伪精确值，而是返回：

```text
estimated_affected_rows = null
estimate_reliable = false
estimate_reason = "preview_not_supported_for_operation"
```

权限检查顺序复用 DB-Ops-4：

```text
classify_sql_operation
  -> database_operation/<database_id>.<operation>/execute
  -> database_table/<database_id>.<table>/read
  -> database_column/<database_id>.<table>.<column>/read
  -> create pending confirmation
```

无权限时直接 403，并写 `database_operation_prepare_rejected` audit；不会生成 confirmation。

### 边界

这仍然不是完整 L3-L5 执行能力：

- 没有注册 `database_demo.prepare_operation` function tool。
- 没有新增 confirm HTTP API。
- 没有新增用户后台确认页面。
- 没有执行 `INSERT` / `UPDATE` / `DELETE` / `DROP TABLE` 等原始 SQL。
- 没有开放真实 MySQL 写入、删除或 DDL。

当前只把高风险操作从“无法表达”推进到“可生成可审计的 pending confirmation”。

### 验证

已运行：

```text
uv run pytest tests/test_enterprise_database_operation_prepare.py -q
uv run ruff check app/enterprise/database/routes.py app/enterprise/database/confirmations.py tests/test_enterprise_database_operation_prepare.py app/config.py
```

结果：

- DB-Ops-6 prepare tests：5/5 passed。
- Ruff：All checks passed（仅既有 top-level lint 配置弃用 warning）。

### 面试追问怎么答

**追问: prepare 阶段为什么可以生成 DROP TABLE confirmation，但不能执行？**

答：

> DB-Ops-6 只负责把“用户有这个 operation 权限，并且 SQL 触及的表列在权限 scope 内”固化成一个可审计的 pending confirmation。它不执行高风险 SQL，因为执行必须等用户后台 confirm 后，再重新校验 SQL hash、参数 hash、权限、目标范围和 preview 摘要。这样 `database_operation/<db>.delete/execute` 的语义是“允许进入删除类确认流”，不是“立即删除”。`DROP TABLE` 的 preview 也不会伪造影响行数，无法可靠估算时明确标成 `estimate_reliable=false`。

## 2026-06-02 (DB-Ops-7/8 user confirmation + sandbox execution)

### 为什么现在做

DB-Ops-6 已经能生成 SQLite 持久化 `pending` confirmation，但没有用户确认入口和执行管线。继续 DB-Ops-7/8 的目标是把“有权限后仍需用户确认”的数据库操作闭环做出来：用户只能处理自己的 confirmation，confirm 后后端重新复核并执行，而不是相信前端传来的确认标记。

这一步合并 DB-Ops-7 和 DB-Ops-8，是因为只有列表/按钮但没有执行管线没有业务效果；只有执行管线但没有用户可见入口又无法证明“普通用户后台确认、管理员后台只做权限管理”的产品边界。

### TDD 红绿过程

第一轮红灯围绕 `tests/test_enterprise_database_operation_confirm.py` 建立：

```text
uv run pytest tests/test_enterprise_database_operation_confirm.py -q
```

红灯证明当前缺的是 confirmation list/detail/cancel/confirm API、owner-scoped repository 查询和原子执行状态转换，而不是 DB-Ops-6 prepare 本身。

随后按风险分支补测试：

- 用户只能列出自己的 confirmation，不能读取别人的 detail。
- cancel 后不能 confirm。
- confirm 后 `UPDATE` / `DELETE` 真正改变 sandbox 数据，且重放不二次执行。
- confirm 后 `DROP TABLE` 只在 sandbox 中执行。
- confirm 时权限被撤销、confirmation 过期、SQL hash 被篡改都会拒绝执行，并保持数据库不变。

### 本轮变更

- `app/enterprise/database/confirmations.py`
  - `DatabaseOperationConfirmationRecord` 增加 `confirmed_at`、`cancelled_at`、`executing_at`、`executed_at`、`failed_at`、`execution_deadline_at`、`failure_reason`、`execution_result`。
  - `SQLiteDatabaseOperationConfirmationRepository` 增加 `list_for_user()`、`update()` 和 `transition_pending_to_executing()`；后者用 `UPDATE ... WHERE confirmation_id=? AND user_id=? AND status='pending'` 做原子抢占，防止重复 confirm 或并发重放。
  - `DatabaseOperationPrepareService` 增加 `list_confirmations()`、`get_confirmation()`、`cancel()`、`confirm()`。
  - `confirm()` 会重新校验 owner、pending 状态、TTL、SQL hash、参数 hash、operation/table/column 权限、目标表列和可靠 preview row count，然后只对 `sandbox_sales` 执行 SQLite transaction。
- `app/enterprise/database/routes.py`
  - 新增 `GET /api/database/confirmations`。
  - 新增 `GET /api/database/confirmations/{confirmation_id}`。
  - 新增 `POST /api/database/confirmations/{confirmation_id}/cancel`。
  - 新增 `POST /api/database/confirmations/{confirmation_id}/confirm`。
- `static/app.js`
  - “我的权限”弹层新增 `databaseConfirmations` 状态、加载、渲染、confirm/cancel action 和状态/risk 展示。
- `static/styles.css`
  - 新增 confirmation list、row、status、action 和窄屏布局样式。
- `static/index.html`
  - cache-bust 更新为 `20260602-db-confirm`。
- `tests/test_enterprise_database_operation_confirm.py`
  - 新增 9 条后端 confirmation/execution 测试。
- `tests/test_assistant_frontend_optimization.py`
  - 新增静态断言，锁定普通用户确认区、关键字段、状态展示和 confirm/cancel 按钮。

### 安全边界

confirm 不是 function calling tool。模型或工具最多只能 prepare；真正 confirm 只能由用户 HTTP/UI 触发。

该阶段完成时 MySQL L3-L5 仍关闭，执行函数只允许 `sandbox_sales`，真实 MySQL 只开放 L1/L2 read-only `list_tables`、`describe_table`、`safe_select`。后续 DB-MySQL-2 已单独开放非生产 UPDATE/DELETE。

管理员后台仍只负责权限管理：授权、撤权、角色、部门 scope 和 `database_operation` grant。普通用户“我的权限”弹层只处理自己已有权限的数据库操作确认，不替代管理员授权。

### 风险和处理

- 风险 1: 用户重复点击 confirm 导致二次执行。处理方式是 repository 用原子 `pending -> executing` 更新抢占，第二次 confirm 读到非 pending 后拒绝。
- 风险 2: prepare 到 confirm 之间权限被撤销。处理方式是 confirm-time 重新调用 `DatabaseOperationPermissionChecker.check_sql()`，撤权后直接 403 并标记 `failed`。
- 风险 3: confirmation 被篡改或旧 hash 复用。处理方式是 confirm-time 重新计算 SQL hash 和参数 hash，并保留 `sql_hash_version` / `normalization_version`。
- 风险 4: SQLite sandbox 结论被误外推到 MySQL。DB-Ops-7/8 当时的处理方式是保留 `SANDBOX_EXECUTION_DATABASE_ID = "sandbox_sales"` 边界，文档明确 MySQL L3-L5 未开放；后续 DB-MySQL-2 已把该硬边界替换为 pluggable executor，并只在非生产 MySQL 上开放 UPDATE/DELETE 第一切片。
- 风险 5: 前端确认被当作安全依据。处理方式是前端只触发 API；所有 owner、权限、hash、TTL 和 preview 复核都在后端完成。

### 验证

已运行：

```text
uv run pytest tests/test_enterprise_database_operation_confirm.py -q
uv run pytest tests/test_enterprise_database_operation_prepare.py tests/test_enterprise_database_operation_confirm.py tests/test_enterprise_database_operation_permissions.py tests/test_enterprise_database_operation_classifier.py tests/test_enterprise_database_http.py tests/test_enterprise_database_mysql.py tests/test_enterprise_tool_schema.py -q
uv run pytest tests/test_assistant_frontend_optimization.py -q
uv run ruff check app/enterprise/database/routes.py app/enterprise/database/confirmations.py tests/test_enterprise_database_operation_confirm.py tests/test_enterprise_database_operation_prepare.py tests/test_assistant_frontend_optimization.py
uv run python -m compileall -q app/enterprise/database/routes.py app/enterprise/database/confirmations.py tests/test_enterprise_database_operation_confirm.py tests/test_enterprise_database_operation_prepare.py
node --check static/app.js
git diff --check
```

结果：

- DB-Ops-7/8 confirmation tests：9/9 passed。
- Database operation bundle：59/59 passed。
- Frontend static tests：23/23 passed。
- Ruff、compileall、node check、git diff whitespace check passed。

### 剩余缺口

- 没有 executing timeout cleanup job。
- 没有历史状态筛选 UI。
- 没有更新/删除前样例。
- 没有 trace_id / request_id 前端展示。
- 没有最大影响行数阈值。
- 没有 DDL allowlist 细化。
- 该阶段没有开放真实 MySQL L3-L5；后续 DB-MySQL-2 已单独开放非生产 UPDATE/DELETE。

### 面试追问怎么答

**追问: 为什么允许用户自己确认删除，而不是让管理员审批？**

答：

> 这里的确认不是授权审批，而是执行前的显式确认。权限已经由管理员通过 `database_operation/<database_id>.delete/execute`、table、column grant 授出；没有这些权限的用户在 prepare 阶段就会 403，根本不会生成 confirmation。有权限的用户 confirm 时，后端还会重新校验权限、SQL hash、目标表列和 preview 摘要，所以用户确认的是“我现在执行这条已获授权的高风险操作”，不是“我申请管理员给我授权”。这能把权限管理和操作确认分开：管理员后台管 grant/revoke，普通用户后台管自己已有权限的执行确认。

## 2026-06-02 (DB-RAG-1 read-only database tools in RAG agent)

### 为什么现在做

DB-Ops-7/8 后，数据库权限、只读执行、高风险确认都已经有了完整后端边界。用户下一步最直接的体验不是继续扩大写入能力，而是让 RAG Agent 能用自然语言调用现有只读数据库工具，例如“有哪些表”“orders 表有哪些字段”“查一下订单金额”。

这一步只接只读工具，不接 `prepare_operation` 和 `confirm`。原因是 confirm 是用户 UI/HTTP 触发的显式动作，不应该进入模型 function calling。

### TDD 红绿过程

新增 `tests/test_rag_database_tools.py` 后第一轮红灯：

```text
uv run pytest tests/test_rag_database_tools.py -q
```

失败点：

- `ModuleNotFoundError: No module named 'app.tools.database_tool'`
- `RagAgentService().tools` 只有 `retrieve_knowledge`、`list_knowledge_documents`、`get_current_time`

这证明缺的是 RAG Agent 可绑定工具包装器，而不是 database provider 或 ToolGateway。

实现后第一次运行又暴露循环 import：

```text
database.routes -> admin.resources -> app.tools -> database_tool -> database.routes
```

修复方式是 `database_tool.py` 顶层不导入 `database.routes`，只在执行时 lazy import `get_database_tool_gateway()`。这样保留现有 HTTP route 的 gateway 单例和测试 patch 入口，同时不破坏 admin resource catalog 的 import 路径。

### 本轮变更

- `app/tools/database_tool.py`
  - 新增 async LangChain tool `list_database_tables(database_id="sandbox_sales")`。
  - 新增 async LangChain tool `describe_database_table(table_name, database_id="sandbox_sales")`。
  - 新增 async LangChain tool `safe_select_database(sql, database_id="sandbox_sales")`。
  - 新增 `_database_tool_id()`：`sandbox_sales` 映射到 `database_demo.*`，其他 database_id 映射到 `database_mysql.<database_id>.*`。
  - 新增 `_execute_read_only_database_tool()`：获取当前 `RequestContext`，调用 `ToolGateway.execute()`，把无权限、安全阻断、数据库执行失败转成结构化 tool result。
- `app/tools/__init__.py`
  - 导出三个 database read-only tools。
- `app/services/rag_agent_service.py`
  - `RagAgentService.tools` 追加 `list_database_tables`、`describe_database_table`、`safe_select_database`。
- `tests/test_rag_database_tools.py`
  - 验证 RAG Agent 默认绑定三个只读 database tools，且不绑定 `prepare_database_operation` / `confirm_database_operation`。
  - 验证工具调用通过真实 `ToolGateway`、`PermissionService`、`DatabaseDemoToolProvider`、`SafeSqlKernel` 执行。
  - 验证无 tool grant 时返回 `status=denied`，并写 `tool_blocked` audit。

### 安全边界

数据库工具包装器不直连 SQLite、MySQL、provider 或 kernel。它只负责把 LangChain tool 调用转换为 `ToolGateway.execute(context, tool_id, args)`。

没有权限时不让模型“申请执行”，而是返回结构化 denied；后端 audit 仍记录 `tool_blocked`。缺 table/column 权限或 DML/DDL 仍由现有 database provider / SQL kernel 阻断。

本阶段没有注册 `database_demo.prepare_operation`，没有注册 confirm function，没有改变 DB-Ops-7/8 用户后台确认管线，也没有开放真实 MySQL 写入、删除或 DDL。

### 验证

阶段内已运行：

```text
uv run pytest tests/test_rag_database_tools.py -q
```

结果：

- 3/3 passed。

补充 closeout 验证：

```text
uv run pytest tests/test_rag_database_tools.py tests/test_memory_tool.py tests/test_enterprise_database_e6.py tests/test_enterprise_database_e7.py tests/test_enterprise_database_http.py tests/test_enterprise_database_mysql.py tests/test_assistant_frontend_optimization.py -q
uv run ruff check app/tools/database_tool.py app/tools/__init__.py app/services/rag_agent_service.py tests/test_rag_database_tools.py
uv run python -m compileall -q app/tools/database_tool.py app/tools/__init__.py app/services/rag_agent_service.py tests/test_rag_database_tools.py
node --check static/app.js
git diff --check
```

结果：

- RAG/database/frontend 组合：69/69 passed。
- Ruff、compileall、node check、git diff whitespace check passed。

### 面试追问怎么答

**追问: 为什么不直接把 `ToolDefinition` 传给 LangChain Agent？**

答：

> `ToolDefinition` 是企业治理层对象，里面有 `resource_id`、metadata、input schema 和 handler，但当前 `RagAgentService` 绑定的是 LangChain `@tool` 工具，比如 `retrieve_knowledge` 和 `get_current_time`。直接把治理对象塞给 `create_agent` 会混淆两层职责。DB-RAG-1 选择加一层薄包装：LangChain 看到的是三个只读工具，包装器内部仍然走 `ToolGateway.execute()`。这样模型工具层和权限治理层分开，既符合现有 RAG Agent 模式，也不会绕过 ToolGateway、PermissionService、SQL kernel 和 audit。

## 2026-06-02 (DB-Ops-9 audit regression gate)

### 为什么现在做

DB-Ops-7/8 已经有 prepare、confirm、execute 和 failed/expired/cancelled 的审计事件，但 closeout 前需要确认这些事件能被审计人员稳定串起来。只知道有 event_type 不够，排障时必须能按同一个 `confirmation_id`、`sql_hash`、`parameters_hash` 和资源范围追踪“谁准备了什么 SQL、当时依赖哪些权限、confirm 前是否被撤权、最后是否执行”。

这一步不改变 SQL 分类、权限检查或执行逻辑，只补审计门禁。

### TDD 红绿过程

新增 `tests/test_enterprise_database_operation_audit.py` 后先跑红灯：

```text
uv run pytest tests/test_enterprise_database_operation_audit.py -q
```

红灯集中在三处：

- `database_operation_prepare_created` 缺 `parameters_hash` 和 `resource_ids`。
- `database_operation_confirmation_cancelled` 只记录了 `confirmation_id` / `database_id` / `operation_type` / `sql_hash`，缺稳定链路字段。
- `database_operation_confirmation_expired` 和 `database_operation_execution_failed` 缺 `parameters_hash`。

这证明问题是审计 metadata 不一致，而不是权限或 SQL 执行失败。

### 本轮变更

- `app/enterprise/database/confirmations.py`
  - `_confirmation_audit_metadata()` 增加 `parameters_hash` 和 `resource_ids`。
  - 新增 `_confirmation_resource_ids()`，按 confirmation 的 `database_id`、`operation_type`、`target_tables`、`target_columns` 生成 operation/table/column resource id 列表。
  - `database_operation_prepare_created` 改为复用 `_confirmation_audit_metadata()` 并追加 `summary`。
  - `database_operation_confirmation_cancelled` 改为复用 `_confirmation_audit_metadata()`，避免 cancel 事件字段漂移。
- `tests/test_enterprise_database_operation_audit.py`
  - 覆盖 prepare -> confirm -> execute 成功链路审计字段。
  - 覆盖 prepare denied 和 cancel audit 与 admin audit 分离。
  - 覆盖 expired 和 permission-revoked failed confirm 都带 reason 与稳定 hash 字段。

### 事件名口径

文档草案曾写过 `database_operation_prepare_allowed`、`database_operation_prepare_denied`、`database_operation_confirmation_created` 等建议名。本轮没有为了命名重写运行时事件，原因是现有事件已经表达同一语义并被测试覆盖：

```text
database_operation_prepare_rejected
database_operation_prepare_created
database_operation_confirmation_cancelled
database_operation_confirmation_expired
database_operation_confirmation_confirmed
database_operation_execution_failed
database_operation_executed
```

后续如果要统一 event taxonomy，应作为独立兼容迁移，而不是 DB-Ops-9 的小修。

### 验证

已运行：

```text
uv run pytest tests/test_enterprise_database_operation_audit.py -q
uv run pytest tests/test_enterprise_database_operation_audit.py tests/test_enterprise_database_operation_prepare.py tests/test_enterprise_database_operation_confirm.py tests/test_enterprise_database_operation_permissions.py tests/test_enterprise_database_operation_classifier.py tests/test_enterprise_database_http.py tests/test_enterprise_database_mysql.py tests/test_enterprise_tool_schema.py -q
uv run ruff check app/enterprise/database/confirmations.py tests/test_enterprise_database_operation_audit.py
uv run python -m compileall -q app/enterprise/database/confirmations.py tests/test_enterprise_database_operation_audit.py
git diff --check
```

结果：

- DB-Ops-9 audit tests：3/3 passed。
- Database operation bundle：62/62 passed。
- Ruff、compileall、git diff whitespace check passed。

### 面试追问怎么答

**追问: 为什么 audit 里还要放 `resource_ids`，权限检查不是已经写了 `permission_checked` 吗？**

答：

> `permission_checked` 是逐次权限判断审计，适合看某一次 check 为什么 allow/deny；`database_operation_*` 是业务操作审计，适合按 confirmation 串起 prepare、confirm、execute。把 operation/table/column 的 `resource_ids` 放进 operation audit，可以让审计人员不必回放所有 permission events，也能知道这条高风险 SQL 依赖哪些资源授权。它不替代权限审计，而是给操作审计提供稳定索引。

## 2026-06-02 (DB-Ops-10 true-service smoke)

### 为什么现在做

单元和 HTTP route 测试已经覆盖了确认执行链路，但数据库操作能力 closeout 还需要确认真实 HTTP 服务下的 auth、admin grant/revoke、database prepare/confirm 和 audit 查询能一起工作。DB-Ops-10 目标是跑产品路径，而不是再加一个内部 service 测试。

主应用 `app.main` 的 lifespan 会连接 Milvus。数据库操作 smoke 与 Milvus 无关，所以本轮启动一个临时 FastAPI app，只挂载真实的 `auth/admin/database` routes，并通过 uvicorn 监听真实本地端口。这样可以验证真实 socket / HTTP / dependency / router 行为，又不会把 smoke 变成 Milvus 可用性测试。

### Smoke 覆盖

本轮使用临时 SQLite sandbox、confirmation DB 和 audit DB，流程如下：

1. 管理员和普通用户通过 `/api/auth/login` 登录。
2. 普通用户无 `database_operation/sandbox_sales.delete/execute` 时，`POST /api/database/operations/prepare` 执行 `DELETE` 返回 403 `default_deny`。
3. 管理员通过 `/api/admin/grants` 授予 operation、table、column 权限。
4. 普通用户再次 prepare `DELETE`，生成 pending confirmation，数据库行仍存在。
5. 普通用户通过 `GET /api/database/confirmations?status=pending` 能看到自己的 confirmation。
6. 管理员撤销 operation grant 后，普通用户 confirm 旧 confirmation 返回 403 `default_deny`，数据库行仍存在。
7. 管理员重新授予 operation 权限，普通用户 prepare 新 confirmation。
8. 普通用户 confirm 新 confirmation，`rows_affected=1`，数据库行被删除。
9. 重放同一个 confirmation，返回 409 `confirmation_not_pending`。
10. `/api/admin/audit` 能查到用户侧 `prepare_rejected`、`prepare_created`、`execution_failed`、`confirmation_confirmed`、`executed`。
11. `/api/admin/audit?event_type=admin_operation` 能查到 `grant_access` 和 `revoke_grant`，不混入普通用户 confirmation audit。

### 实测输出

```text
DB-Ops-10 live smoke passed
unauthorized_status=403:default_deny
revoked_confirm=403:default_deny
rows_affected=1
replay=409:confirmation_not_pending
```

用户审计事件包含：

```text
database_operation_prepare_rejected
database_operation_prepare_created
database_operation_execution_failed
database_operation_confirmation_confirmed
database_operation_executed
```

管理员审计操作包含：

```text
grant_access
revoke_grant
```

### 边界

这不是打开真实 MySQL 写入、删除或 DDL。DB-Ops-10 只验证 `sandbox_sales` 的 L3-L5 confirmation 执行链路，以及真实 MySQL 继续只读的既定边界。

### 面试追问怎么答

**追问: 为什么 smoke 不直接启动完整 `app.main`？**

答：

> 完整 `app.main` 的 lifespan 会连接 Milvus，而 DB-Ops-10 要验证的是 auth/admin/database 的高风险操作链路。把 Milvus 拉进来会让 smoke 的失败原因变成外部向量库可用性，而不是数据库操作能力本身。本轮仍然用 uvicorn 和真实 HTTP 端口，只是挂载相关真实路由并注入临时 SQLite 存储，所以验证的是产品 API 路径，不是 `TestClient` 内部调用。

## 2026-06-02 (DB-MySQL-2 non-production writable UPDATE/DELETE)

### 为什么现在做

DB-MySQL-1 把真实 MySQL 做成只读验证，DB-Ops-7/8 把高风险操作确认流做成 `sandbox_sales` SQLite 执行。用户明确指出这不符合“真实场景”的目标：真实场景不是直接动生产库，但必须至少在“真实 MySQL 协议、真实事务、真实表结构、可写账号、非生产数据”的环境里验证写入和删除。因此本轮开启 DB-MySQL-2，先做 UPDATE/DELETE 第一切片。

### 代码变化

- `app/enterprise/database/confirmations.py`
  - 删除 `SANDBOX_EXECUTION_DATABASE_ID` 硬编码执行边界。
  - 新增 `DatabaseOperationExecutor` protocol。
  - 新增 `SQLiteDatabaseOperationExecutor`，把原来的 SQLite preview count 和 transaction execute 从 service 方法中搬到 executor。
  - `DatabaseOperationPrepareService` 增加 `operation_executor` 注入，confirm 仍统一执行 owner/pending/TTL/SQL hash/参数 hash/权限/目标范围/preview 复核，然后调用 executor。
- `app/enterprise/database/mysql.py`
  - 新增 `MySqlWritableConnector` protocol。
  - 新增 `PooledMySqlWritableConnector`，用 `START TRANSACTION` -> SQL -> `COMMIT` 执行确认后的写操作，异常 rollback。
  - 新增 `MySqlDatabaseOperationExecutor`，第一切片只支持 UPDATE/DELETE；preview 对 UPDATE/DELETE 生成 read-only `SELECT COUNT(*) AS affected_count ...`。
  - `DatabaseOperationPrepareService.prepare()` 增加 executor support 检查；DB-MySQL-2 当时不支持的 `INSERT` / DDL 在 prepare 阶段直接 403，不生成 confirmation。该 `INSERT` 边界已被 DB-MySQL-3 direct execute 切片覆盖。
- `app/enterprise/database/routes.py`
  - `build_database_operation_prepare_service()` 增加 `dialect` 和 `operation_executor` 参数，让同一个 HTTP prepare/confirm route 可以挂 MySQL registry/database_id。
- `tests/test_enterprise_database_mysql_writable.py`
  - 通过真实 HTTP route + fake MySQL connector 验证 UPDATE prepare/confirm 执行、DELETE 无权限 403 不生成 confirmation、撤权后 confirm 403 且不执行、重放 409。
  - 补一条 TDD 红灯：给用户 L3 `update` operation 权限后，`INSERT INTO orders ...` 一开始会生成 confirmation。DB-MySQL-2 修复后返回 403 `database_operation_execution_unsupported_for_database`，且 repository 无 pending confirmation；DB-MySQL-3 后续把 `INSERT` 改为 direct execute。
- `tests/test_enterprise_database_mysql.py`
  - 补 `PooledMySqlWritableConnector` 普通事务执行测试，避免可写 connector 误用 read-only transaction。

### 真实 MySQL smoke

使用用户本地 Docker MySQL `127.0.0.1:3307` / `sales` / `RootSmoke123`，重建非生产 `orders` 表并通过真实 uvicorn HTTP 端口执行：

```text
DB-MySQL-2 live smoke passed
update_total=0.00
delete_count=0
revoked_confirm=403:default_deny
replay=409:confirmation_not_pending
```

用户侧 operation audit 包含：

```text
database_operation_prepare_created
database_operation_confirmation_confirmed
database_operation_executed
database_operation_execution_failed
```

### 验证

```text
uv run pytest tests/test_enterprise_database_mysql_writable.py -q
uv run pytest tests/test_enterprise_database_mysql.py tests/test_enterprise_database_mysql_writable.py tests/test_enterprise_database_operation_prepare.py tests/test_enterprise_database_operation_confirm.py tests/test_enterprise_database_operation_audit.py -q
uv run pytest tests/test_enterprise_database_operation_prepare.py tests/test_enterprise_database_operation_confirm.py tests/test_enterprise_database_operation_audit.py tests/test_enterprise_database_operation_permissions.py tests/test_enterprise_database_mysql.py -q
uv run ruff check app/enterprise/database/confirmations.py app/enterprise/database/mysql.py app/enterprise/database/routes.py tests/test_enterprise_database_mysql.py tests/test_enterprise_database_mysql_writable.py
uv run python -m compileall -q app/enterprise/database/confirmations.py app/enterprise/database/mysql.py app/enterprise/database/routes.py tests/test_enterprise_database_mysql.py tests/test_enterprise_database_mysql_writable.py
git diff --check
```

结果：

- MySQL writable tests：4/4 passed。
- DB-MySQL-2 / DB-Ops regression bundle：39/39 passed。
- Ruff、compileall、git diff whitespace check passed。

### 边界

本轮不是生产库上线。DB-MySQL-2 第一切片只验证非生产 MySQL 的 UPDATE/DELETE。`INSERT` 在 DB-MySQL-2 的 prepare 阶段显式拒绝，不会生成 confirmation；该边界已被 DB-MySQL-3 更正为 direct execute。`DROP TABLE`、`CREATE TABLE`、`ALTER TABLE` 和生产 MySQL 接入策略仍是后续独立切片。

### 面试追问怎么答

**追问: 为什么不用前端 confirm=true 直接执行 MySQL？**

答：

> confirm 不是前端布尔值，而是后端持久化 confirmation 的状态转换。用户只能在有 `database_operation/<db>.update|delete/execute`、table、column 权限后生成 confirmation；confirm 时后端重新校验 SQL hash、参数 hash、权限、目标表列和 preview 摘要，然后做原子 `pending -> executing`，最后由 executor 在事务里执行。前端按钮只是触发 confirm API，不是安全依据。

**追问: 这次为什么敢打开 MySQL 写入？**

答：

> 打开的是非生产 writable MySQL，不是生产库。这个环境仍然是真 MySQL 协议、真事务、真表结构和真可写账号，所以能验证真实执行语义；但数据是 smoke 数据，可以重建。生产库需要另写 owner、备份/恢复、影响阈值、审批/变更窗口和审计保留策略，不能从 Docker smoke 自动外推。

## 2026-06-02 (DB-MySQL-3 direct non-delete MySQL operations)

### 为什么现在做

用户纠正了一个关键产品规则：不是所有数据库写操作都需要用户后台确认。真正需要确认的是删除类操作，因为它们恢复成本高；`INSERT` / `UPDATE` 这类非删除写操作只要用户已经有对应 `database_operation/<database_id>.update/execute`、table、column 权限，就应该直接执行并审计。DB-MySQL-2 把 UPDATE 也放进 confirmation，是一个过保守的历史切片，本轮用 DB-MySQL-3 更正。

### 代码变化

- `app/enterprise/database/confirmations.py`
  - 新增 `DatabaseOperationDirectExecuteDenied`、`DatabaseOperationDirectExecuteResult`、`DatabaseOperationDirectExecutor` 和 `DatabaseOperationDirectExecuteService`。
  - direct execute 入口复用 `DatabaseOperationPermissionChecker.check_sql()`，先做 SQL 分类、operation 权限、table 权限、column 权限检查。
  - `classification.is_delete_like=True` 时直接拒绝，reason 为 `database_operation_requires_confirmation`，不会执行 SQL，也不会生成 confirmation。
  - 非删除写操作执行前生成 normalized SQL、`sql_hash`、`parameters_hash`、`resource_ids`，执行成功写 `database_operation_direct_executed`；执行失败写 `database_operation_direct_execution_failed`。
  - `DatabaseOperationPrepareService.prepare()` 对 MySQL 非确认操作返回 `database_operation_does_not_require_confirmation`，避免 `UPDATE` / `INSERT` 继续走旧 confirmation 流。
- `app/enterprise/database/mysql.py`
  - `MySqlDatabaseOperationExecutor.supports_operation()` 只保留 `delete`，表示 MySQL 确认流只服务删除类。
  - 新增 `supports_direct_operation()`，只允许 `insert` / `update`。
  - 新增 `execute_sql()`，通过 `PooledMySqlWritableConnector.execute_transaction()` 在 MySQL transaction 中执行 normalized SQL。
- `app/enterprise/database/routes.py`
  - 新增 `DatabaseOperationExecuteRequest`。
  - 新增 `build_database_operation_direct_execute_service()` / `get_database_operation_direct_execute_service()`。
  - 新增 `POST /api/database/operations/execute`，它是普通 authenticated HTTP route，不是 function calling confirm。
- `tests/test_enterprise_database_mysql_writable.py`
  - 扩展 fake connector 以支持 insert/update/delete 写入样本。
  - 锁定 MySQL UPDATE direct execute，不生成 confirmation，写 `database_operation_direct_executed`。
  - 锁定 MySQL UPDATE prepare 返回 `database_operation_does_not_require_confirmation`。
  - 锁定 MySQL INSERT direct execute。
  - 锁定 MySQL DELETE direct execute 返回 `database_operation_requires_confirmation`。
  - 保留 DELETE 无权限 prepare 403、prepare 后撤权 confirm 403 且不执行。

### 验证

```text
uv run pytest tests/test_enterprise_database_mysql_writable.py -q
uv run pytest tests/test_enterprise_database_mysql.py tests/test_enterprise_database_mysql_writable.py tests/test_enterprise_database_operation_prepare.py tests/test_enterprise_database_operation_confirm.py tests/test_enterprise_database_operation_audit.py tests/test_enterprise_database_operation_permissions.py -q
uv run ruff check app/enterprise/database/confirmations.py app/enterprise/database/mysql.py app/enterprise/database/routes.py tests/test_enterprise_database_mysql.py tests/test_enterprise_database_mysql_writable.py
uv run python -m compileall -q app/enterprise/database/confirmations.py app/enterprise/database/mysql.py app/enterprise/database/routes.py tests/test_enterprise_database_mysql.py tests/test_enterprise_database_mysql_writable.py
git diff --check
```

结果：

- MySQL writable tests：6/6 passed。
- DB-MySQL / DB-Ops regression bundle：41/41 passed。
- Ruff、compileall、git diff whitespace check passed。
- DB-MySQL-3d live smoke passed against Docker MySQL over a real uvicorn HTTP port: `insert_total=16.50`、`update_total=0.00`、`delete_exists_after_confirm=false`、`revoked_confirm=403:default_deny`、`replay=409:confirmation_not_pending`。

### 边界

本轮仍然不是生产库上线。DB-MySQL-3 只针对非生产 writable MySQL 打开 `INSERT` / `UPDATE` direct execute，并保留删除类 confirmation。DDL 仍未开放；DB-MySQL-3d 已用真实 Docker MySQL 验证 INSERT、UPDATE、DELETE confirmation、撤权、重放和 audit。

### 面试追问怎么答

**追问: 为什么 UPDATE 不需要后台确认，而 DELETE 需要？**

答：

> 这里的后台确认不是授权审批，而是高风险执行确认。权限已经由 `database_operation/<db>.<op>/execute`、table、column grant 表达。UPDATE 属于非删除写操作，有权限就直接执行并审计；DELETE / DROP / ALTER DROP COLUMN 属于删除类，恢复成本更高，所以即使用户有 delete 权限，也要先生成 confirmation，再由本人在用户后台确认。没有权限的人在第一步就 403，不会生成确认项。

**追问: 直接执行会不会绕过安全链路？**

答：

> 不会。`POST /api/database/operations/execute` 仍然依赖登录用户和 `RequestContext`，后端复用同一个 `DatabaseOperationPermissionChecker` 做 SQL 分类、operation/table/column 权限检查，并写 audit。它绕过的是“确认项生命周期”，不是绕过权限、表列范围或审计。

## 2026-06-02 (DB-MySQL-4 L5 DDL rule update)

### 为什么现在做

用户继续纠正 L5 规则：表结构变更不应该全部进入后台确认。真正需要确认的是删除类操作；非删除 DDL 和 `INSERT` / `UPDATE` 一样，只要用户已有对应 operation 权限和对象 scope，就应该直接执行并审计。这样规则从“写操作直接、删除确认”扩展为“非删除操作直接、删除确认”。

### 文档变化

- `docs/数据库操作能力.md`
  - 总状态改为 DB-MySQL-4 已开启文档规则 gate。
  - 新增 `DB-MySQL-4 非生产 MySQL L5 DDL 计划`。
  - 明确 `CREATE TABLE`、`ALTER TABLE ADD COLUMN`、`ALTER TABLE MODIFY COLUMN`、`RENAME TABLE`、`RENAME COLUMN`、`CREATE INDEX`、`DROP INDEX` 属于非删除 DDL，有 `database_operation/<db>.ddl/execute` 后 direct execute。
  - 明确 `DROP TABLE`、`ALTER TABLE DROP COLUMN`、`TRUNCATE` 属于删除类，继续走用户后台 confirmation。
- `docs/数据库操作能力执行步骤清单.md`
  - 总阶段表新增 DB-MySQL-4a/4b/4c/4d。
  - 新增 `DB-MySQL-4：MySQL L5 非删除 DDL 直接执行` 章节，列出 direct DDL、confirmation DDL、权限规则、审计要求和建议测试。
- `task_plan.md`
  - 当前活动轨道从 DB-MySQL-3 closeout 改为 DB-MySQL-4 L5 DDL planning。
- `PROJECT_STATE.md` / `progress.md`
  - 记录 DB-MySQL-4a 为 docs-only planning gate；还没有运行时代码。

### 冻结规则

- 非删除 DDL：`database_operation/<db>.ddl/execute` + table/column 或 DDL allowlist scope 通过后，直接执行并审计，不生成 confirmation。
- 删除类 DDL：`database_operation/<db>.delete/execute` 通过后只生成 confirmation，必须用户后台 confirm 后执行。
- 无对应 operation 权限：直接 403，不生成 confirmation。
- 生产库 DDL 不随 DB-MySQL-4 自动开放；本阶段仍只面向 Docker / 非生产 writable MySQL。

### 边界

本轮是文档和计划更新，没有新增 Python 运行时代码、route、executor 或测试。下一步 DB-MySQL-4b/4c 才进入实现：扩展 classifier / permission checker / MySQL executor allowlist，并用 Docker MySQL 做 DDL live smoke。

### 面试追问怎么答

**追问: 为什么 DROP INDEX 不需要确认，但 DROP TABLE 需要？**

答：

> 这里按“是否删除业务数据或不可轻易恢复的结构”分流。`DROP TABLE` 和 `ALTER TABLE DROP COLUMN` 会删除数据或字段承载的数据，恢复成本高，所以必须 confirmation。`DROP INDEX` 不删除业务数据，索引可以重建，属于可恢复的结构调整，所以在有 ddl operation 权限和 scope 检查后直接执行并审计。

**追问: 这是不是等于可以改生产库结构？**

答：

> 不是。DB-MySQL-4 只打开非生产 writable MySQL 的 DDL 验证，目的是验证真实 MySQL 协议、事务、DDL 语义和审计链路。生产库结构变更还需要单独的生产接入策略，包括 owner、备份/恢复、变更窗口、影响阈值、审计保留和回滚方案。

## 2026-06-02 (DB-MySQL-4 L5 DDL runtime + live smoke)

### 为什么现在做

上一节只冻结了 L5 规则，用户随后明确要求“先更新文件，然后按照计划开始开发”。本轮把 DB-MySQL-4 从 docs gate 推进到真实非生产 MySQL runtime：非删除 DDL 直接执行，删除类 DDL 继续用户后台 confirmation。这样数据库能力不再停留在只读或 UPDATE/DELETE 第一切片，而是能覆盖真实业务里常见的建表、加列、改列、改名、建索引和删索引。

### 代码变化

- `app/enterprise/database/operation_classifier.py`
  - L3 `INSERT` / `UPDATE` 和 L5 非删除 DDL 的 `requires_confirmation` 保持 `False`，删除类 L4 仍为 `True`。
  - 新增 `CREATE INDEX`、`DROP INDEX`、`RENAME TABLE` 分类；`DROP TABLE` 仍归 L4 `drop_table`。
  - `_column_names()` 现在从 `ColumnDef` 提取 `CREATE TABLE` / `ALTER TABLE ADD COLUMN` / `ALTER TABLE MODIFY COLUMN` 声明列，避免 DDL 绕过 column scope。
- `app/enterprise/database/operation_permissions.py`
  - `_column_refs()` 对 `exp.Alter` / `exp.Create` 的 `ColumnDef` 生成 table.column 引用；`ALTER TABLE orders ADD COLUMN status ...` 没有 `orders.status` grant 时返回 `database_column_denied`。
- `app/enterprise/database/mysql.py`
  - `MySqlDatabaseOperationExecutor.supports_direct_operation()` 新增 `create_table`、`alter_table`、`create_index`、`drop_index`、`rename_table`。
  - `supports_operation()` 保留 `delete`、`truncate`、`drop_table`、`alter_table_drop_column`，表示这些只能走 confirmation executor。
  - 新增 `build_mysql_operation_executor_from_config(app_config=...)`，从配置构造 MySQL registry + writable executor，供默认 HTTP operation services 使用。
- `app/enterprise/database/routes.py`
  - 新增 `build_default_database_operation_services()`，当 `enterprise_mysql_enabled=true` 时，默认 prepare/direct service 一起绑定到 MySQL registry/executor，避免 route 仍落到 sandbox operation services。
- `app/enterprise/admin/resources.py`
  - operation catalog metadata 对齐产品规则：`update.requires_confirmation=false`、`delete.requires_confirmation=true`、`ddl.requires_confirmation=false`。

### 验证

```text
uv run pytest tests/test_enterprise_database_mysql.py tests/test_enterprise_database_mysql_writable.py tests/test_enterprise_database_operation_prepare.py tests/test_enterprise_database_operation_confirm.py tests/test_enterprise_database_operation_audit.py tests/test_enterprise_database_operation_permissions.py tests/test_enterprise_database_operation_classifier.py -q
uv run ruff check app/enterprise/database/mysql.py app/enterprise/database/routes.py app/enterprise/database/operation_classifier.py app/enterprise/database/operation_permissions.py app/enterprise/admin/resources.py tests/test_enterprise_database_mysql.py tests/test_enterprise_database_mysql_writable.py tests/test_enterprise_database_operation_classifier.py tests/test_enterprise_database_operation_permissions.py
```

已完成的 targeted 结果：

- MySQL / database operation bundle：61/61 passed。
- `tests/test_enterprise_database_mysql_writable.py`：11/11 passed。
- `tests/test_enterprise_database_operation_classifier.py`：7/7 passed。
- `tests/test_enterprise_database_operation_permissions.py`：8/8 passed。
- targeted `ruff check` passed。

### Live smoke

Docker MySQL 非生产库 trace：`mysql-ddl-smoke-202606022317`。

覆盖结果：

- 无 `ddl` operation 权限时，非删除 DDL 直接 403 `default_deny`，不生成 confirmation。
- `CREATE TABLE archived_orders` direct execute。
- `ALTER TABLE orders ADD COLUMN state` direct execute。
- `ALTER TABLE orders MODIFY COLUMN status` direct execute。
- `ALTER TABLE orders RENAME COLUMN state TO state2` direct execute。
- `CREATE INDEX idx_orders_total` / `DROP INDEX idx_orders_total` direct execute。
- `RENAME TABLE archived_orders TO renamed_orders` direct execute。
- `DROP TABLE renamed_orders` direct execute 返回 403 `database_operation_requires_confirmation`。
- `DROP TABLE` prepare 后撤销 delete grant，confirm 返回 403 `default_deny`，不执行。
- 重新授权后 fresh prepare + confirm 执行成功。
- 同一个 confirmation 重放返回 409 `confirmation_not_pending`。
- audit 包含 `database_operation_direct_executed`、`database_operation_prepare_created`、`database_operation_executed`，以及 rejected/failed/admin/permission 事件。

### 边界

这仍然不是生产库结构变更上线。DB-MySQL-4 使用真实 MySQL 协议、真实事务、真实 DDL 语义和可写账号，但目标库是 Docker 非生产 smoke 数据。生产接入必须另开策略，至少覆盖 owner、备份/恢复、变更窗口、影响阈值、审计保留和回滚方案。

### 面试追问怎么答

**追问: 你怎么防止模型直接改库结构？**

答：

> 这条链路不是模型直接执行 SQL。当前 direct execute 是 authenticated HTTP route，后端从 `CurrentUser` 拿 `RequestContext`，再用 `DatabaseOperationPermissionChecker` 检查 SQL 分类、`database_operation/<db>.ddl/execute`、table scope 和 column scope。模型侧仍没有 confirm function，普通用户没有权限时直接 403，不会生成 confirmation，也不会执行。

**追问: 为什么新增列也要 column grant，它本来还不存在？**

答：

> 第一版用 registry / allowlist 表达“这个环境允许哪些对象被操作”。新增列如果完全不进 registry，就会出现用户有表权限就能随便加任意列的漏洞。所以 `operation_classifier` 从 `ColumnDef` 提取声明列，`operation_permissions` 再把它变成 `orders.status` 这种 column resource 检查。这样新增列也要先被治理面纳入可授权范围。

**追问: 为什么 `DROP INDEX` direct execute，但 `DROP TABLE` confirmation？**

答：

> 分界不是 SQL 动词里有没有 DROP，而是是否删除业务数据或不可轻易恢复的结构。`DROP INDEX` 不删除业务数据，索引可以重建；`DROP TABLE` 会删除整张表及其数据，恢复成本高。所以前者有 ddl 权限和 scope 后 direct execute，后者必须 prepare、用户后台 confirm、confirm-time 复核后执行。
