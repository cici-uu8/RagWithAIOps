---
feature_ids:
  - agent-evaluation-system-054
topics:
  - agent-evaluation
  - rag-evaluation
  - trace-evaluation
  - governance
  - badcase-rca
doc_kind: design
created: 2026-07-07
status: documentation_only
---

# Agent 评测体系设计：基于 054 文章的 SuperBizAgent 落地版

## 1. 文档定位

本文基于资料 `054_Agent评测方法论与体系设计`，把其中的 Agent 评测方法论映射到 SuperBizAgent 当前项目。

本文不是原文摘要，也不是新一轮实现计划。它的目标是回答：

- 这篇文章对 SuperBizAgent 的评测体系有什么具体启发。
- 当前项目已经有哪些评测资产，不应重复建设什么。
- 哪些能力只是 smoke、shadow 或 observation，不能误当发布门禁。
- 下一步如果要建设项目级 Agent 评测体系，应该先补哪几块。

本文只做设计和盘点，不改变运行时代码，不改变 RAG / AIOps / 数据库默认路径，不引入新的评测框架或线上依赖。

## 2. 原文核心判断

054 文章最重要的观点不是“用某个评测工具打分”，而是：

```text
Agent 评测是把不稳定的智能行为持续收敛成可发布的工程质量。
```

这对 SuperBizAgent 很关键。因为本项目不是单轮问答 demo，而是包含：

- RAG 知识问答。
- AIOps 多步诊断。
- 数据库工具调用。
- 权限、审计、人工审核和 confirmation。
- 多轮会话和桌面端产品流程。

如果只看最终答案是否像样，会漏掉生产级 Agent 最危险的问题：

- 最终答案看起来对，但引用来源不可回查。
- 工具调用顺序错误，但模型把结果包装成合理解释。
- SQL 被模型生成出来，但没有经过 SafeSqlKernel 或权限边界。
- 高风险操作没有进入 human review 或 confirmation。
- 评测通过了离线样本，但真实 beta 反馈暴露表达方式、语料覆盖或多跳问题。

因此，SuperBizAgent 的评测体系应该按以下闭环组织：

```text
Golden Set / 真实反馈 / badcase
  -> 执行评测并采集 Trace
  -> Scorer 分层判定
  -> Badcase RCA
  -> 结构化行动项
  -> 回归集和发布门禁
```

## 3. 当前项目已有基础

当前项目不是从零开始。已有评测资产分散在 RAG、enterprise trace eval、verifier、数据库、安全治理和 beta 反馈中。

### 3.1 RAG 评测资产

当前 RAG 侧已有较完整的基础线：

| 资产 | 当前状态 | 应该如何使用 |
|---|---|---|
| Mixed 54q retrieval baseline | `45/54 = 83.3%`，source_ref / scope gate 干净 | 可作为当前 RAG retrieval Golden Set 的主基线之一 |
| Answer 30q | `18/30` 已接受为当前阶段 Answer 基线 | 只能说明当前 Answer 覆盖有限，不应作为 GA 通过证据 |
| beta readiness smoke | `7/7`，覆盖 auth、受控 RAG、source_ref、权限过滤、audit、默认配置、反馈 schema | 可作为 beta 前置 smoke，不是线上质量充分证明 |
| Beta Week 1 feedback | 3 个角色、11 条真实反馈，retrieval success 9/11，权限/source_ref 问题 0 | 应作为真实反馈入口，不要和 AI 模拟反馈混用 |
| Boundary 12Q | post-fix PASS 5 / PARTIAL 4 / FAIL 3，权限/source_ref 仍干净 | 是边界压力集，不是真实 beta 阈值证据 |
| top_k / rerank shadow matrix | 保持 shadow，未证明可提升默认值 | 只能用于候选比较，不授权默认配置变更 |

当前 RAG 默认值仍应保持：

```text
rag_default_retrieval_mode = dense_only
rag_query_rewrite_mode = off
rerank_enabled = false
rag_top_k = 3
```

054 文章给 RAG 侧的直接启发是：不能只看 Answer pass rate，要拆成 retrieval、source_ref、citation、scope、answer completeness、真实反馈、RCA 和回归集。

### 3.2 Enterprise Trace Eval

`evals/enterprise/*` 已经提供 deterministic trace trajectory eval 的基础：

- `ExpectedTrajectory` 定义期望执行轨迹。
- `AuditTraceExtractor` 支持 inline / JSONL / SQLite trace 来源。
- `TrajectoryMatcher` 检查 final status、required audit events、required stages、forbidden tools、SSE contract、task contract、database expectations、AIOps expectations。
- 已有 chat、AIOps、SSE、DB、Admin 等 evalset。

这非常接近原文所说的 Trace 层评测。它的价值不是“再打一个分”，而是能证明：

- 该调用是否走了正确 gateway。
- 是否出现必要 audit 事件。
- 是否调用了正确工具。
- 是否没有调用 forbidden tool。
- 是否保留了 trace_id / request_id。
- SQL / AIOps / task contract 是否满足结构化期望。

当前缺口是：trace eval 还没有完全并入统一质量资产库，也没有统一连接到 badcase RCA、owner、修复动作和回归门禁。

### 3.3 结构化 Verifier

`app/enterprise/verifiers/*` 已有三类结构化 verifier：

| Verifier | 当前职责 | 对应 054 文章里的角色 |
|---|---|---|
| `PlanVerifier` | 检查 task contract 下计划是否越界、是否使用未授权 tool / data source | 规则 Scorer / 过程 Scorer |
| `CitationVerifier` | 只信任结构化 source_ref，检查 doc_id、chunk evidence、授权文档范围 | 规则 Scorer / P0 引用门禁 |
| `SqlResultVerifier` | 要求 SQL 结果来自 SafeSqlKernel，且列在授权范围内 | 规则 Scorer / P0 数据安全门禁 |

这说明项目方向是对的：P0 风险用规则和结构化证据判，不交给 LLM Judge。

下一步不应先扩 Judge，而应先判断是否缺少这些确定性 verifier：

- Tool trajectory verifier：必需工具是否调用，禁止工具是否未调用。
- Audit evidence verifier：allow / deny / blocked 是否有足够证据字段。
- Human review verifier：高风险任务是否进入 pending_review，reject 后是否未执行。
- Database operation verifier：direct execute / confirmation 是否符合当前操作分类规则。

### 3.4 治理和审计资产

项目已有本地治理主干：

- `RequestGateway`
- `ToolGateway`
- `ModelGateway`
- `PermissionService`
- `SafeSqlKernel`
- `DatabaseOperationConfirmationService`
- `HumanReviewService`
- `AuditService`

并已有治理文档：

- `docs/agent_governance_policy_contract.md`
- `docs/agent_governance_audit_evidence_design.md`
- `docs/mcp_server_admission_checklist.md`
- `docs/agent_governance_execution_plan.md`

这与 054 文章强调的 P0 门禁、Trace、Scorer、RCA 是一致的。项目真正要补的是“评测平台化”和“质量资产化”，不是再引入一套并行治理框架。

## 4. 项目级 Agent 类型划分

054 文章强调：先分清 Agent 类型，再设计指标。SuperBizAgent 不应该用一个总分评所有能力。

### 4.1 RAG 知识问答 Agent

| 层级 | 指标 | 优先级 | 当前资产 | 缺口 |
|---|---|---|---|---|
| Retrieval | doc hit、chunk hit、scope 正确、source_ref 可回查 | P0 | Mixed 54q、retrieval reports | 失败样本 RCA 还不够结构化 |
| Citation | source_ref 完整、doc_id/chunk_id 一致、授权文档内 | P0 | `CitationVerifier`、source_ref smoke | citation verifier 尚未作为统一发布门禁汇总 |
| Answer | 忠实性、完整性、拒答边界、直接性 | P1 | Answer 30q、beta feedback | Judge 校准集和人工金标不足 |
| User Feedback | 真实 query、缺失事实、满意度、followup decision | P1/P2 | `RAG_Beta_User_Feedback_Log.md` | 反馈到 RCA / 回归集的自动化不足 |

RAG 的 P0 不应该是“回答看起来对”，而应该是：

- 没有权限越界。
- source_ref 可回查。
- citation 不编造。
- 检索结果在用户可见范围内。
- 默认配置没有未经 gate 变更。

### 4.2 AIOps 诊断 Agent

| 层级 | 指标 | 优先级 | 当前资产 | 缺口 |
|---|---|---|---|---|
| Tool Coverage | 必需工具是否调用，如 alerts、metrics、logs、CMDB | P0/P1 | AIOps lab smoke、failure semantics、trace eval | 需要把三故障 smoke 和 trace eval 纳入同一资产表 |
| Evidence Chain | 根因是否有 metric / log / alert 证据 | P0/P1 | `aiops_required_evidence_categories` | 证据质量和最终报告忠实性仍需更细 scorer |
| Failure Semantics | hard failure / recovered / degraded 是否正确标注 | P0 | failure semantics | 可进一步绑定发布门禁 |
| Outcome | 根因、处理建议、是否可执行 | P1 | smoke / lab reports | 缺少人工金标和线上真实 AIOps feedback |

AIOps 不能只看最终报告是否流畅。必须看 Trace：

- 是否先看 active alerts。
- 是否查了必要指标。
- 是否查了相关日志。
- 是否区分工具失败、模型失败、结构化输出恢复。
- 是否在缺工具时停止或降级，而不是编造根因。

### 4.3 数据库 Agent / 数据库工具链

| 层级 | 指标 | 优先级 | 当前资产 | 缺口 |
|---|---|---|---|---|
| Trigger | 是否识别为数据库能力，而不是误路由 | P1 | query intent / DB tool tests | 需要整理正负样本 |
| SQL Safety | 是否经过 SafeSqlKernel，是否拒绝危险 SQL | P0 | DB HTTP tests、SafeSQL tests | P0 gate 可更集中展示 |
| Permission | tool/table/column/operation grant 是否正确 | P0 | PermissionService、DB tests | audit evidence 字段还可增强 |
| Operation Lifecycle | direct execute / confirmation 是否符合规则 | P0 | confirmation/direct execute tests | 与 trace eval 的质量资产映射不足 |
| UX Hint | 拒绝原因是否可理解，不自动修正 SQL | P2 | friendly error hints | 可从 beta feedback 观察是否足够 |

数据库链路必须坚持：

```text
模型生成 SQL 只是草稿。
SQL 安全权威是 SafeSqlKernel。
执行权威是 ToolGateway / PermissionService / operation permission / confirmation。
```

### 4.4 治理、审批和审计 Agent Flow

| 层级 | 指标 | 优先级 | 当前资产 | 缺口 |
|---|---|---|---|---|
| Request Boundary | 是否进入 RequestGateway | P0 | gateway tests、audit | 部分历史路径仍需持续防漂移 |
| Tool Boundary | 未授权工具是否不可见 / 不可执行 | P0 | ToolGateway tests | MCP server 准入后需扩展 |
| Human Review | 高风险任务是否 pending，不绕过执行 | P0 | HumanReviewService tests | 审批人角色/SLA 尚未产品化 |
| Audit Evidence | allow/deny/blocked 是否有证据字段 | P0/P1 | audit design、ops dashboard | 缺统一 evidence completeness gate |
| SRE Signal | degraded / failed / recovery 是否可解释 | P1 | error recovery | 还没有完整 SLO / error budget |

这类能力不适合用 LLM Judge 判断。它们应该是 deterministic gate。

## 5. Golden Set 和质量资产库

054 文章强调：评测集是质量资产，不是线上随机抽样。SuperBizAgent 可以把现有材料整理成以下资产层。

| 资产层 | 内容 | 用途 | 当前建议 |
|---|---|---|---|
| Core Golden Set | Mixed 54q、DB Q-SQL、AIOps 三故障、trace eval core cases | 发布前固定回归 | 先建立统一索引，不急于扩量 |
| Edge / Pressure Set | Boundary 12Q、PDF table cases、多跳 cases、missing corpus cases | 暴露边界问题 | 不能直接混入真实 beta 阈值 |
| Real Feedback Set | Beta Week 1 confirmed feedback 后续真实用户反馈 | 决定是否重开专项优化 | 保持真实反馈和模拟反馈隔离 |
| Shadow Candidate Set | top_k/rerank/query rewrite/OpenJudge/RAGAS shadow cases | 比较候选策略 | 不作为默认变更证据 |
| Judge Calibration Set | 人工金标样本、边界样本、高风险样本 | 校准 LLM Judge | 当前明显不足，后续可补 |
| RCA Regression Set | 已修复 badcase 的代表样本 | 防止回归 | 需要从现有 findings / reports 中抽取 |

质量资产库至少需要记录这些字段：

| 字段 | 说明 |
|---|---|
| `asset_id` | 稳定样本 ID |
| `agent_type` | RAG / AIOps / database / governance |
| `source` | evalset / beta feedback / smoke / boundary / incident |
| `risk_level` | P0 / P1 / P2 |
| `expected_trace` | 期望工具、stage、audit event、source_ref 等 |
| `scorer_type` | rule / trace / judge / human |
| `current_status` | gate / shadow / observation / historical |
| `owner_module` | RetrievalService、SafeSqlKernel、AIOps executor 等 |
| `regression_command` | 可复现命令 |
| `promotion_rule` | 是否允许影响默认配置 |

## 6. Scorer 分层设计

SuperBizAgent 的 Scorer 不应该单一化。建议采用 054 文章的分层思想。

### 6.1 Rule Scorer

适用 P0 硬条件：

- source_ref 是否可回查。
- citation 是否在授权文档范围内。
- SQL 是否 SafeSqlKernel verified。
- 工具是否有 `tool/use` 权限。
- forbidden tool 是否未调用。
- human review / confirmation 是否被绕过。
- audit event 是否完整。

现有可复用基础：

- `CitationVerifier`
- `SqlResultVerifier`
- `PlanVerifier`
- `TrajectoryMatcher`
- database operation tests
- gateway / permission / audit tests

### 6.2 Trace Scorer

适用过程质量：

- 是否调用了必需工具。
- 工具调用顺序是否符合 SOP。
- 是否出现无效步骤或重复重试。
- AIOps 是否保留 metric / log / alert 证据。
- DB 操作是否有 prepare / confirm / execute 生命周期证据。
- SSE 是否带 trace_id / request_id。

当前 `evals/enterprise` 已经很接近 Trace Scorer，下一步是把它纳入统一评测资产管理，而不是散落在不同报告中。

### 6.3 LLM-as-Judge

适用语义和策略判断：

- RAG answer completeness。
- 回答是否直接、清楚、可执行。
- AIOps 报告是否解释充分。
- 数据库拒绝提示是否用户可理解。
- 多轮对话是否完成用户目标。

但 LLM Judge 在本项目里应保持以下边界：

- 不替代 source_ref / permission / SafeSQL / human review。
- 不作为当前 production gate 主判。
- 先 shadow，再与人工金标对齐。
- 需要 few-shot、reason、边界样本和漂移监控。
- 需要记录与人工一致性、高风险漏判率、边界样本稳定性。

### 6.4 Human Scorer

适用：

- 高风险样本。
- 规则与 Judge 冲突。
- 低置信样本。
- 业务口径未固化。
- 新工具、新 prompt、新 schema、新模型上线观察期。

人工评分不应长期承担全量日常打分。它的核心价值是：

- 定标准。
- 校准 Judge。
- 处理争议。
- 回收业务口径。
- 反向修正规则和 RCA 标签。

## 7. Badcase RCA 设计

054 文章最适合迁移到项目里的部分是 Badcase RCA。当前项目已经有很多失败类型，但还需要统一到“问题现象 -> 候选模块 -> 责任模块 -> 修复动作”。

### 7.1 RCA 通用流程

建议流程：

```text
Badcase 输入
  -> 汇总 session / trace / eval run / feedback evidence
  -> 按问题现象收敛候选模块
  -> 分模块诊断 input / output / prompt / tool return / audit
  -> 判定主责 / 次责 / 问题枚举
  -> 生成行动项和回归样本
```

### 7.2 项目级问题现象映射

| 问题现象 | 候选模块 | 检查证据 | 可能行动 |
|---|---|---|---|
| `retrieval_wrong_doc` | corpus、chunking、RetrievalService、rerank/query rewrite shadow | retrieved_docs、source_ref、expected_doc、rank | 补语料、修 chunk、窄范围 shadow，不直接改默认 |
| `retrieval_no_hit` | corpus coverage、query expression、scope filter | direct retrieval、KB grants、query terms | 先判断缺语料还是表达 gap |
| `answer_incomplete` | AnswerGenerator、context coverage、prompt contract | retrieved context、answer markers、missing_facts | 窄 prompt/context pilot，不直接扩 Answer 50q |
| `source_ref_unresolvable` | ChunkEvidenceMapper、metadata store、indexing pipeline | source_ref lookup、chunk record | P0 citation bug，优先修 |
| `permission_scope_issue` | PermissionService、DocumentAccessService、RagAdapter | permission audit、visible docs、selected KB | P0 security bug，优先修 |
| `intent_misroute` | QueryIntentRouter、strategy routing shadow | routing_decision、matched patterns | 加负样本和路由回归 |
| `tool_not_called` | AIOps planner、executor、ToolCatalog | observed_tools、required_tools | 修 required-tool validation 或 planner |
| `aiops_evidence_missing` | AIOps tool execution、evidence extractor、report generator | metric/log/alert evidence categories | 补证据采集或报告约束 |
| `sql_blocked` | SQL generation、SafeSqlKernel、permission grants | blocked_reason、table/column/operation | 区分正常拒绝和工具生成错误 |
| `audit_missing` | AuditService、gateway integration、trace extractor | required_audit_events | 补 audit 事件或修 eval expectation |
| `human_review_bypassed` | RiskDetector、HumanReviewService、adapter | review audit、execution audit | P0 治理 bug，阻断发布 |

### 7.3 RCA 输出格式

建议每条 badcase 输出结构化记录：

| 字段 | 说明 |
|---|---|
| `badcase_id` | 稳定 ID |
| `source` | eval / beta feedback / smoke / incident |
| `agent_type` | RAG / AIOps / database / governance |
| `symptom` | 问题现象 |
| `risk_level` | P0 / P1 / P2 |
| `trace_id` | 可选，但有则必须记录 |
| `evidence_refs` | 报告路径、feedback id、audit query、source_ref lookup |
| `candidate_modules` | 初筛候选模块 |
| `primary_owner_module` | 主责模块 |
| `secondary_owner_module` | 次责模块 |
| `root_cause_enum` | 稳定问题枚举 |
| `recommended_action` | 具体修复动作 |
| `regression_case` | 是否进入回归集 |
| `promotion_blocker` | 是否阻断发布或默认配置提升 |

## 8. 发布门禁分层

054 文章把指标分为 P0 / P1 / P2。SuperBizAgent 可以这样落地。

### 8.1 P0 门禁

P0 不通过，不能发布或不能提升默认配置。

| 门禁 | 判定方式 |
|---|---|
| 权限 / scope 无越界 | rule scorer + permission audit |
| source_ref 可回查 | rule scorer + metadata lookup |
| citation 不编造 | `CitationVerifier` |
| SQL 安全 | `SafeSqlKernel` + `SqlResultVerifier` |
| 高风险任务进入 review / confirmation | rule scorer + audit |
| forbidden tool 未调用 | trace scorer |
| request / trace / audit 关键字段存在 | audit evidence scorer |

### 8.2 P1 优化指标

P1 用于版本比较和工程优化，不应单独决定安全发布。

| 指标 | 用途 |
|---|---|
| retrieval pass rate | 比较 retrieval 策略 |
| answer completeness | 判断是否重开 Answer revisit |
| AIOps required tool coverage | 判断 planner / executor 是否退化 |
| DB tool trigger precision / recall | 判断数据库 agent 可用性 |
| latency / cost / retry count | 工程优化和 SRE |
| trace match rate | 判断 trajectory 是否稳定 |

P1 指标需要和 baseline 比较，不要只看单次分数。

### 8.3 P2 体验指标

P2 长期观察：

- 回答是否简洁。
- 错误提示是否可理解。
- 多轮会话是否顺畅。
- 用户满意度。
- 管理端/桌面端操作是否省心。

P2 不能覆盖 P0 失败。

## 9. 统计和连续成功率

054 文章提醒：Agent 有非确定性，不能只看一次通过。

当前项目很多 gate 是 deterministic tests 或固定 evalset，适合做规则门禁。但涉及 LLM / 多步 agent / AIOps 报告时，后续应补：

- 至少一次成功率：观察能力上限。
- 连续成功率：观察生产稳定性。
- 置信区间：避免把随机波动当提升。
- 与 baseline 的显著性判断：避免小样本误判。
- 最小可感知变化阈值：提前定义提升多少才值得发布。

短期不建议把统计显著性做成复杂平台。可以先在报告模板里增加：

```text
sample_count
repeat_count
pass_rate
continuous_success_rate
baseline_delta
minimum_detectable_change
decision = promote | keep_shadow | reject | observe
```

## 10. 质量资产入库规则

不是所有失败都应该进入回归集。建议满足以下条件再入库：

- 失败可复现，或有稳定 trace / 人工确认。
- 期望行为明确，能写成规则、Judge rubric 或人工验收标准。
- 根因标签清楚，能归到具体模块或业务流程。
- 样本有代表性，能覆盖一类问题。
- 已完成脱敏，不含密码、token、生产敏感数据。
- 不只是一次外部服务抖动。

样本治理规则：

- 同一问题簇保留代表例。
- P0 / P1 高风险长期保留。
- 多版本稳定通过且低风险的样本降级为抽样集。
- 新意图、新工具、新知识点、低置信样本优先进入人工确认。

## 11. 建议实施路线

### Phase 0：本文档完成

产物：

- `docs/Agent评测体系设计_基于054文章.md`

边界：

- 只做设计。
- 不改代码。
- 不改变默认配置。
- 不新增框架。

### Phase 1：评测资产索引

建议新增一个轻量文档或表格，统一登记现有资产：

```text
docs/Agent评测资产索引.md
```

登记对象：

- RAG Mixed 54q。
- Answer 30q。
- Boundary 12Q。
- Beta feedback。
- AIOps lab smoke。
- database Q-SQL / DB trace eval。
- enterprise trace evalsets。
- verifier tests。
- governance/audit docs。

目标不是扩样本，而是先分清：

- gate。
- shadow。
- observation。
- historical。

### Phase 2：RCA 标签和行动项模板

建议新增：

```text
docs/Agent评测RCA标签体系.md
```

先覆盖当前已知问题：

- retrieval_wrong_doc
- retrieval_no_hit
- answer_incomplete
- source_ref_unresolvable
- permission_scope_issue
- intent_misroute
- tool_not_called
- aiops_evidence_missing
- sql_blocked
- audit_missing
- human_review_bypassed

每个标签绑定：

- 候选模块。
- 主责判定规则。
- 修复动作模板。
- 回归样本入库规则。

### Phase 3：补缺失的 deterministic verifier

只有当 Phase 1/2 证明缺口明确时，再改代码。

优先候选：

- ToolTrajectoryVerifier。
- AuditEvidenceVerifier。
- HumanReviewVerifier。
- DatabaseOperationLifecycleVerifier。

这些都属于规则 / trace Scorer，不依赖 LLM Judge。

### Phase 4：LLM Judge shadow 和人工校准

仅用于 P1/P2：

- answer completeness。
- AIOps 报告质量。
- 错误提示可理解性。
- 多轮对话 outcome。

进入自动化前需要：

- 人工金标样本。
- few-shot rubric。
- 与人工一致性统计。
- 高风险漏判率。
- 边界样本重复评测稳定性。

### Phase 5：发布门禁和周度评测报告

最终形成：

- P0 gate report。
- P1 compare report。
- P2 observation report。
- badcase RCA report。
- action item report。
- regression update report。

门禁结论必须使用固定枚举：

```text
pass
fail
partial
keep_shadow
observe
not_ready
blocked
```

避免出现“看起来不错，可以上线”这类不可审计说法。

## 12. 当前不建议做的事

当前不建议：

- 直接引入新评测平台。
- 把 RAGAS / OpenJudge 作为主 gate。
- 用 LLM Judge 替代 source_ref / SafeSQL / 权限 / review。
- 因 Boundary 12Q 或单条 beta feedback 改全局 RAG 默认值。
- 重新从零设计 evalset，忽略已有 Mixed 54q / Answer 30q / trace eval。
- 把 AI 模拟反馈写入真实 beta feedback threshold。
- 在主仓库脏工作区里做大规模代码改造。

## 13. 项目复盘时可以这样讲

如果对外或面试解释，可以这样组织：

```text
我们没有把 Agent 评测做成单一分数，而是分成 RAG、AIOps、数据库工具和治理流四类。
P0 风险用规则和结构化 Trace 判定，例如 source_ref、权限、SafeSQL、human review 和 audit。
P1 用于版本比较，例如 retrieval pass rate、AIOps tool coverage、Answer completeness。
P2 才看体验和表达。

评测失败后不只记录 badcase，而是按 trace_id 汇总证据，先用问题现象映射候选模块，
再做分模块诊断，最后落到责任模块、问题枚举、owner、修复动作和回归用例。
这让评测从一次报告变成持续质量资产。
```

## 14. 结论

054 文章对 SuperBizAgent 的最大启示是：

```text
不要再把评测看成单次报告。
要把现有 evalset、trace、verifier、beta feedback、audit 和 RCA 收成质量资产库。
```

当前项目已经具备很多底座能力，尤其是：

- RAG baseline。
- trace eval。
- structured verifier。
- SafeSQL。
- PermissionService。
- Human Review。
- audit evidence design。

下一步最有价值的不是立刻扩模型评测，而是：

1. 建立统一评测资产索引。
2. 明确 P0/P1/P2 指标矩阵。
3. 固化 Scorer 分层。
4. 建立 RCA 标签体系。
5. 把 badcase 变成行动项和回归资产。

这样才能让 Agent 评测真正服务项目迭代，而不是制造更多零散报告。
