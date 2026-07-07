---
feature_ids:
  - agent-eval-rca-taxonomy
topics:
  - agent-evaluation
  - badcase-rca
  - regression
  - governance
doc_kind: rca-taxonomy
created: 2026-07-07
status: documentation_only
---

# Agent 评测 RCA 标签体系

## 1. 文档定位

本文定义 SuperBizAgent 项目级 badcase RCA 标签。它不是错误码全集，也不是用户展示文案。

它的用途是把 RAG、AIOps、数据库、治理链路里的失败统一成可复盘、可归责、可回归的项目标签：

```text
失败样本 -> RCA 标签 -> 候选模块 -> 主责判断 -> 修复动作 -> 是否进回归集
```

本次只做标签设计，不改 `evals/enterprise`，不新增 verifier，不修改运行时代码。

## 2. RCA 使用流程

1. 先确认失败来自哪个资产：RAG Mixed 54q、Answer 30q、Boundary 12Q、Beta feedback、AIOps trace eval、database Q-SQL、enterprise trace eval、verifier tests。
2. 再贴一个主标签，只允许一个 `primary_rca_label`。
3. 必要时贴多个辅助标签，例如 `answer_incomplete` 可同时带 `retrieval_wrong_doc`。
4. 判断主责模块，不能把所有问题都归到 LLM。
5. 写出修复动作：补语料、修 eval、调 scorer、补 verifier、修 router、修 tool gateway、修 audit field。
6. 判断是否进回归集：P0/P1 或真实反馈聚类必须进；孤立观察样本可先进入 watchlist。

## 3. 标签总览

| 标签 | 主要场景 | 主责候选模块 | 发布风险 |
|---|---|---|---|
| `retrieval_wrong_doc` | 检索到不该排前的文档，或 expected doc 被相似文档压下去。 | RetrievalService、embedding、chunk、rerank、corpus | P1，若引发 wrong scope 则 P0。 |
| `retrieval_no_hit` | 相关文档完全没召回，或 corpus 中本来没有资料。 | corpus、retrieval、query expression | P1；缺资料应进入 corpus backlog。 |
| `answer_incomplete` | 检索有依据，但最终回答缺关键事实、步骤或约束。 | answer prompt、context packing、LLM answer layer、eval reference | P1/P2，按业务影响判断。 |
| `source_ref_unresolvable` | 答案或检索结果引用无法回查到结构化 source_ref。 | citation layer、ChunkEvidenceMapper、metadata store | P0。 |
| `permission_scope_issue` | 权限过滤、KB scope、表列 scope 或跨部门隔离失败。 | PermissionService、DocumentAccessService、RagAdapter、DatabasePermissionFilter | P0。 |
| `intent_misroute` | 路由到错误链路，例如 RAG 问题进 DB，安全问题进普通 chat。 | QueryIntentRouter、Strategy Routing Shadow、router candidate set | P0/P1，取决于误路由后果。 |
| `tool_not_called` | 期望工具没有调用，导致 trace 或结果缺证据。 | ToolGateway、planner、executor、trace eval matcher | P1。 |
| `aiops_evidence_missing` | AIOps 诊断没有告警、日志、指标、CMDB 或工具证据链。 | AIOps planner/executor/replanner、MCP tool catalog、AIOps Lab | P1。 |
| `sql_blocked` | SQL 被 SafeSQL / permission 阻断，需判断是正确阻断还是生成/权限问题。 | SafeSqlKernel、SQL generator、DatabasePermissionFilter、Q-SQL examples | P0/P1，取决于是否该阻断。 |
| `audit_missing` | allow/deny/block/execute 没有足够审计事件或关键字段。 | AuditService、RequestGateway、ToolGateway、operation services | P0/P1。 |
| `human_review_bypassed` | 高风险任务没有进入 human review / confirmation，或 reject 后仍执行。 | HumanReviewService、TaskContractService、DatabaseOperationConfirmationService | P0。 |

## 4. 标签定义

### `retrieval_wrong_doc`

| 字段 | 定义 |
|---|---|
| 症状 | top_k 中出现相似但错误的文档；expected doc 排名靠后；答案依据错误文档。 |
| 候选模块 | `RetrievalService`、embedding 模型、chunk policy、rerank、corpus source_support。 |
| 主责判断 | 如果 expected doc 不在 corpus，不能标这个标签，应标 `retrieval_no_hit` 或 corpus gap；如果 expected doc 在池内但 final context 被挤掉，优先看 rerank/context packing。 |
| 证据 | sample_id、query、expected_doc_ids、actual_doc_ids、rank、source_ref、retrieval_mode、top_k。 |
| 修复动作 | 先做失败分流；可能动作是补 source_support、调整 chunk、增加表达缺口样本、重跑 shadow compare。 |
| 回归规则 | 真实反馈聚类、Boundary 12Q、高频 Mixed 54q residual 必须进回归；孤立 shadow 失败可先 watchlist。 |
| 发布阻断 | 若导致 wrong scope 或敏感越权，P0 阻断；否则阻断 retrieval 默认策略提升。 |

### `retrieval_no_hit`

| 字段 | 定义 |
|---|---|
| 症状 | 没有召回相关文档；系统回答“没有资料”；或 corpus 本身缺少对应主题。 |
| 候选模块 | corpus intake、owner-approved docs、query expression、embedding recall。 |
| 主责判断 | 先确认语料是否存在；不存在时主责是 corpus，不是模型；存在但没有召回时再看 retrieval。 |
| 证据 | query、expected topic、corpus search 结果、retrieved_docs、owner/corpus 状态。 |
| 修复动作 | 补 corpus、补 owner runbook、加 expression-gap candidate、或扩大 retrieval shadow。 |
| 回归规则 | 缺资料类进入 corpus backlog；真实 beta 高频 no_hit 进入回归。 |
| 发布阻断 | 不直接阻断当前发布；若宣传材料声称覆盖该主题，则阻断该声明。 |

### `answer_incomplete`

| 字段 | 定义 |
|---|---|
| 症状 | 检索命中正确来源，但回答漏步骤、漏风险、漏关键事实或没有按问题给出结论。 |
| 候选模块 | answer prompt、context packing、LLM answer layer、reference answer、scorer。 |
| 主责判断 | 先确认 retrieved context 是否含事实；若没有，改标 `retrieval_wrong_doc` / `retrieval_no_hit`；若有事实但没说，才归 answer layer。 |
| 证据 | retrieved context、must_include_facts、final answer、source_ref、answer score。 |
| 修复动作 | 小范围 prompt/schema/verifier；必要时做 Answer pilot；不要直接跳到主模型 SFT。 |
| 回归规则 | Answer 30q、真实 beta 聚类、Boundary 问题应进入回归。 |
| 发布阻断 | 阻断 Answer 50q / GA 质量声明；不必阻断小范围 beta。 |

### `source_ref_unresolvable`

| 字段 | 定义 |
|---|---|
| 症状 | 答案有引用文本但没有结构化 `source_ref`；或 `doc_id/chunk_id/source_uri` 无法回查。 |
| 候选模块 | `CitationVerifier`、`ChunkEvidenceMapper`、metadata store、answer assembler。 |
| 主责判断 | P0 不交给 LLM Judge；只看结构化 source_ref 是否完整、可解析、在授权范围内。 |
| 证据 | source_ref payload、metadata lookup、chunk_id、doc_id、kb_id、allowed_kb_ids。 |
| 修复动作 | 补 citation verifier、修 mapper、修 metadata 写入或 retrieval result contract。 |
| 回归规则 | 必须进 deterministic regression。 |
| 发布阻断 | P0 阻断。 |

### `permission_scope_issue`

| 字段 | 定义 |
|---|---|
| 症状 | 返回用户无权访问的 KB 文档、数据库表列、工具结果或跨部门信息。 |
| 候选模块 | `PermissionService`、`DocumentAccessService`、`RagAdapter`、`ToolGateway`、`DatabasePermissionFilter`。 |
| 主责判断 | 看权限检查发生在哪个边界；RAG 权限应在 RAG 路径内处理，不应由 router 误跳 permission flow。 |
| 证据 | user_id、roles、grants、allowed_kb_ids、resource_id、decision audit、returned source_ref。 |
| 修复动作 | 修权限过滤、补 default deny 测试、补 audit evidence、补 verifier。 |
| 回归规则 | 必须进 P0 regression。 |
| 发布阻断 | P0 阻断。 |

### `intent_misroute`

| 字段 | 定义 |
|---|---|
| 症状 | 查询被路由到错误能力，例如知识问答进数据库、数据库问题绕过 SafeSQL、高风险请求进 plain chat。 |
| 候选模块 | `QueryIntentRouter`、Strategy Routing Shadow、router candidate JSONL、RequestGateway route mapping。 |
| 主责判断 | 先判断正确业务路径，再判断误路由风险；高风险 false negative 比普通问答误路由更严重。 |
| 证据 | query、expected_route、actual_route、routing_decision audit、must_not_route。 |
| 修复动作 | 先改规则或 shadow eval；只有规则不够且样本足够时，才启动 router 分类器离线实验。 |
| 回归规则 | high_risk、permission_required、database、aiops 误路由必须进回归。 |
| 发布阻断 | high_risk false negative 为 P0；普通分类错误通常 P1。 |

### `tool_not_called`

| 字段 | 定义 |
|---|---|
| 症状 | trace 期望工具没有出现，例如 DB 问题没有调用 `database_demo.safe_select` 或 AIOps 没有调用必要诊断工具。 |
| 候选模块 | ToolGateway、planner、executor、tool catalog、trace eval matcher。 |
| 主责判断 | 如果工具不可见，先看权限/tool catalog；如果工具可见但 planner 没选，才看 planning。 |
| 证据 | expected_tool、observed_tools、visible_tools audit、tool_call audit、trace_id。 |
| 修复动作 | 修 tool visibility、补 planner prompt、补 trace expected path、或补 ToolTrajectoryVerifier。 |
| 回归规则 | 进入 trace eval 或 tool verifier regression。 |
| 发布阻断 | 关键工具缺失时阻断对应能力发布。 |

### `aiops_evidence_missing`

| 字段 | 定义 |
|---|---|
| 症状 | AIOps 诊断缺少告警、日志、指标、CMDB 或依赖关系证据，却给出根因/动作建议。 |
| 候选模块 | AIOps planner/executor/replanner、MCP tools、AIOps Lab、trace matcher。 |
| 主责判断 | 先看 expected evidence category 是否定义；没有定义则先补 evalset，而不是改模型。 |
| 证据 | aiops_required_tools、aiops_required_evidence_categories、observed audit metadata、tool results。 |
| 修复动作 | 补 lab trace、补 required evidence matcher、修 planner 工具顺序。 |
| 回归规则 | AIOps trace eval 和 lab smoke 必须覆盖。 |
| 发布阻断 | 对 AIOps 诊断能力是 P1；涉及高风险动作时升 P0。 |

### `sql_blocked`

| 字段 | 定义 |
|---|---|
| 症状 | SQL 被 SafeSQL 或权限拒绝。该标签本身不代表 bug，必须判断阻断是否正确。 |
| 候选模块 | SafeSqlKernel、SQL classifier、DatabasePermissionFilter、Q-SQL examples、database route。 |
| 主责判断 | 如果是 `SELECT *`、JOIN、未授权列、DML/DDL 直跑，阻断是正确行为；如果正当查询被挡，才是生成或策略问题。 |
| 证据 | SQL、blocked_reason、authorized tables/columns、expected_sql_family、audit event。 |
| 修复动作 | 正确阻断只改提示或示例；误阻断才修 SafeSQL / permission / Q-SQL example。 |
| 回归规则 | 正确阻断和误阻断都应分开入库，避免后续把安全门放宽。 |
| 发布阻断 | 绕过 SafeSQL 是 P0；正确阻断不阻断发布。 |

### `audit_missing`

| 字段 | 定义 |
|---|---|
| 症状 | allow / deny / blocked / execute 决策没有审计事件，或缺 `trace_id`、`resource_id`、`reason`、`confirmation_id` 等关键字段。 |
| 候选模块 | AuditService、RequestGateway、ToolGateway、DatabaseOperation services、HumanReviewService。 |
| 主责判断 | 先确定决策边界；哪个服务做了 allow/deny，哪个服务就应写审计。 |
| 证据 | expected audit event、actual audit events、trace_id、request_id、decision_id、metadata。 |
| 修复动作 | 补 audit field、补 deterministic test、必要时补 AuditEvidenceVerifier。 |
| 回归规则 | P0/P1 决策必须进回归。 |
| 发布阻断 | 安全、权限、SQL、human review 相关 audit 缺失为 P0/P1 阻断。 |

### `human_review_bypassed`

| 字段 | 定义 |
|---|---|
| 症状 | 高风险任务没有进入 pending review；reject 后仍调用工具；需要 confirmation 的 DB 操作被直接执行。 |
| 候选模块 | HumanReviewService、TaskContractService、AIOpsAdapter、DatabaseOperationConfirmationService。 |
| 主责判断 | 根据当前产品规则判断是否必须 review/confirmation；如果必须，任何绕过都是 P0。 |
| 证据 | risk_level、task_contract_id、review_id、confirmation_id、tool_call audit、execution audit。 |
| 修复动作 | 修 risk trigger、修 adapter gating、补 verifier、补 trace eval forbidden tool。 |
| 回归规则 | 必须进 P0 regression。 |
| 发布阻断 | P0 阻断。 |

## 5. Badcase 记录模板

```yaml
badcase_id: ""
source_asset: "rag_mixed_54q | answer_30q | boundary_12q | beta_feedback | aiops_trace_eval | database_qsql | enterprise_trace_eval | verifier_test"
sample_id: ""
query_or_task: ""
expected_behavior: ""
actual_behavior: ""
primary_rca_label: ""
secondary_rca_labels: []
candidate_modules: []
owner_rule: ""
evidence_refs:
  - path: ""
    note: ""
risk_level: "low | medium | high | p0"
fix_action: ""
regression_action: "none | watchlist | add_to_evalset | add_verifier_test | add_trace_eval"
release_blocker: false
decision_notes: ""
```

## 6. 入回归集规则

| 条件 | 动作 |
|---|---|
| P0 标签：`source_ref_unresolvable`、`permission_scope_issue`、`human_review_bypassed`、高风险 `intent_misroute`、SafeSQL 绕过 | 必须进入 deterministic regression 或 verifier test。 |
| P1 真实用户反馈聚类达到 runbook 阈值 | 进入对应 evalset，并开 triage。 |
| shadow 实验单点失败 | 先进入 watchlist，不直接改生产。 |
| eval reference 错误 | 修 evalset，并保留 historical record，避免把模型当背锅模块。 |
| 正确安全阻断 | 作为 negative control 保留，防止后续放宽门禁。 |

## 7. 后续实现判断

先用这套标签整理已有 badcase。整理后再决定是否改代码：

- 如果问题只是“证据散”，继续补资产索引、报告和 scorecard。
- 如果 trace eval 不能表达某类期望路径，再改 `evals/enterprise/models.py` / `matcher.py` / evalset。
- 如果 P0 风险没有确定性规则，再补 verifier，例如 `AuditEvidenceVerifier`、`ToolTrajectoryVerifier` 或 `HumanReviewVerifier`。
- 如果只是回答风格或格式不稳，先用 prompt / schema / verifier；微调仍后置。
