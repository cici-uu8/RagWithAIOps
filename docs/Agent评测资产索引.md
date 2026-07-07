---
feature_ids:
  - agent-eval-assets-index
topics:
  - agent-evaluation
  - rag-evaluation
  - trace-evaluation
  - governance
  - model-comparison
  - finetuning-planning
doc_kind: asset-index
created: 2026-07-07
status: documentation_only
---

# Agent 评测资产索引

## 1. 文档定位

本文是 SuperBizAgent 当前评测资产的项目级索引，不是新的评测方法论，也不是新实验计划。

它回答四个问题：

- 项目里已经有哪些真实评测资产。
- 每个资产现在属于 `gate`、`baseline`、`shadow`、`observation`、`historical` 还是 `smoke`。
- 每个资产对应哪些文件、命令、指标和报告。
- 哪些资产可以阻断发布或默认策略提升，哪些只能作为观察材料。

本次只整理文档，不改代码、不改 RAG / AIOps / 数据库默认配置、不训练模型、不接生产链路。

## 2. 资产分级

| 分级 | 含义 | 是否可阻断发布 / 默认提升 |
|---|---|---|
| `gate` | 规则稳定、结果可复验、和 P0/P1 风险直接相关的门禁。 | 可以。失败时应阻断发布或阻断默认策略提升。 |
| `baseline` | 当前阶段接受的能力基线，用来比较后续候选。 | 通常不直接阻断发布，但可阻断“变更默认值”。 |
| `shadow` | 离线或旁路比较，不影响生产路径。 | 不能直接阻断发布，但可阻断候选 promotion。 |
| `observation` | 真实反馈或人工观察材料，样本量通常不够大。 | 不能单条阻断；聚类达到阈值后可触发 triage。 |
| `historical` | 历史证据、旧阶段结果、负例或已被新结论覆盖的记录。 | 不能直接阻断当前发布，但可作为决策背景。 |
| `smoke` | 小范围关键路径冒烟，确认最小闭环可用。 | 可以阻断 beta / demo 启动，但不能证明完整质量。 |

## 3. RAG 与 Answer 资产

| asset_id | 资产 | 分级 | 路径 / 报告 | 命令或 runner | 关键指标 | 是否阻断 |
|---|---|---|---|---|---|---|
| `rag_mixed_54q` | RAG Mixed 54q retrieval baseline | `gate` / `baseline` | `evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_54q_after_c6_p2.jsonl`; `docs/RAG_Corpus_清单6_C6-P3_Mixed_54q_retrieval_baseline.md`; `docs/RAG_MVP_Baseline_20260612.md` | `uv run python -m evals.knowledge_base.run_department_rag_eval --evalset evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_54q_after_c6_p2.jsonl` | `45/54`; `wrong_scope_count=0`; `citation_unresolvable_count=0`; `all_source_ref_resolvable=true` | 可以阻断 RAG 默认策略提升；source_ref / scope 回归应阻断。 |
| `answer_30q` | Answer 30q 当前阶段基线 | `baseline` / `limitation_record` | `evals/knowledge_base/evalsets/department_rag_answer_30q_after_c6.jsonl`; `docs/RAG_Answer_Layer_C6_Answer_30q_Revisit.md`; `docs/RAG_Answer_Layer_C6_Answer_30q_Failure_Triage.md` | `uv run python -m evals.knowledge_base.run_department_rag_answer_eval --evalset evals/knowledge_base/evalsets/department_rag_answer_30q_after_c6.jsonl` | 当前接受基线 `18/30`；低于此前 21/30 continuation threshold | 不能作为 GA 通过证明；可阻断 Answer 50q、agent_behavior、OpenJudge-as-gate 的过早推进。 |
| `boundary_12q` | Boundary 12Q 边界压力集 | `shadow` / `edge_pressure_set` | `evals/knowledge_base/evalsets/boundary_test_12q.jsonl`; `evals/knowledge_base/boundary_test_12q_manual.md`; post-fix 报告 `evals/knowledge_base/reports/boundary_test_12q_20260613_081304.{json,md}` | `uv run python -m evals.knowledge_base.run_boundary_test_12q --base-url http://127.0.0.1:9900/api` | post-fix `PASS 5 / PARTIAL 4 / FAIL 3`; `intent_misroute=0`; `permission_or_scope_issue=0` | 可阻断边界风险声明；不能直接授权默认 retrieval 改动。 |
| `beta_feedback` | Beta Week 1 真实反馈 | `observation` / `real_feedback_set` | `docs/RAG_Beta_User_Feedback_Log.md`; schema `docs/schemas/rag_user_feedback.schema.json` | 手工写入反馈日志；按 runbook 周审 | 3 个角色 / 11 条真实 query；retrieval success `9/11`; satisfaction `4.09/5`; source_ref issue `0`; permission/scope issue `0` | 单条不阻断；同类问题聚类达到 runbook 阈值后触发 triage。 |
| `beta_readiness_smoke` | Beta readiness 最小冒烟 | `smoke` | `evals/knowledge_base/beta_readiness_smoke.py`; `docs/RAG_Beta_Readiness_生产试运行闭环.md` | `uv run python -m evals.knowledge_base.beta_readiness_smoke --output evals/knowledge_base/reports/beta_readiness_smoke_YYYYMMDD.json` | `7/7`; 覆盖 auth、受控 RAG、source_ref、权限过滤、audit、默认配置、反馈 schema | 可阻断 beta/demo 启动；不能证明线上质量充分。 |
| `desktop_smoke_acceptance` | 桌面端技术冒烟与验收 | `smoke` / `acceptance_evidence` | `docs/技术冒烟测试报告_20260614.md`; `docs/项目全功能验收_20260613.md`; `docs/RAG_桌面端_Beta_测试计划_20260614.md` | `uv run python smoke_test_desktop_beta.py`; 桌面 Beta 测试计划手工执行 | 技术 smoke `21/21`; 桌面验收 `51 PASS / 0 FAIL / 2 PARTIAL` | 可阻断桌面 beta 启动；普通 AIOps MCP 诊断和 Memory ingestion 仍是 PARTIAL。 |

## 4. Retrieval / Rerank / Embedding 对比资产

| asset_id | 资产 | 分级 | 路径 / 报告 | 命令或 runner | 关键指标 | 是否阻断 |
|---|---|---|---|---|---|---|
| `topk_rerank_matrix` | top_k / rerank shadow matrix | `shadow` / `compare_gate` | `evals/knowledge_base/topk_rerank_shadow_matrix_report.py`; `docs/compare-reports/compare_month1_rag_topk_rerank_matrix.md`; `docs/scorecards/scorecard_month1_rag_topk_rerank_gate.md` | `uv run python -m evals.knowledge_base.topk_rerank_shadow_matrix_report --evalset evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_54q_after_c6_p2.jsonl --output-json evals/knowledge_base/reports/month1_topk_rerank_shadow_matrix_54q_YYYYMMDD.json --output-md evals/knowledge_base/reports/month1_topk_rerank_shadow_matrix_54q_YYYYMMDD.md` | baseline `dense_k3_ctx3_default=45/54`; `dense_k20_ctx5_no_rerank` keep-shadow; lexical / Bailian rerank reject | 可以阻断 top_k/rerank promotion；不能单独证明 Answer 质量提升。 |
| `retrieval_mode_history` | dense / sparse / hybrid / rerank 历史对比 | `historical` / `shadow` | `Hybrid_vs_Dense_对比测试报告.md`; `docs/RAG_QueryRewrite_清单4_*`; `docs/RAG_Retrieval_C6_Mixed_54q_Residual_Failure_Triage.md` | 历史 runner 与探针报告 | S4-P2.3 true rerank C-probe `rank_lift_proven=0/8`; sparse/hybrid Benefit-B 仅少量观察 lift | 可作为“不默认开启 hybrid/rerank/query rewrite”的负证据。 |
| `bge_m3_shadow_54q` | BGE-M3 本地 embedding shadow 54q | `shadow` / `model_comparison_evidence` | 外部 worktree: `/Users/cici/oncall agent/.worktrees/phaseA-bge-m3-smoke/docs/compare-reports/compare_phaseA_bge_m3_embedding_54q.md`; `docs/scorecards/scorecard_phaseA_bge_m3_embedding_54q.md`; `docs/analysis/phaseA_bge_m3_54q_failure_triage.md` | 外部 shadow worktree 中执行；当前 worktree 只索引证据，不复跑 | 当前 baseline `45/54`; BGE-M3 `38/54`; decision `keep-shadow`; `wrong_scope_count=0`; source_ref 可解析 | 不能改生产 embedding；可作为模型对比履历和候选筛除证据。 |
| `model_comparison_overview` | 产品级模型 / retrieval 对比总览 | `historical` / `portfolio_evidence` | 外部 worktree: `/Users/cici/oncall agent/.worktrees/phaseA-bge-m3-smoke/docs/model_and_retrieval_comparison_overview.md` | 文档资产 | 记录 embedding、retrieval mode、top_k/rerank、微调规划的统一比较路线 | 不能阻断发布；用于解释系统性选型过程。 |

## 5. AIOps 资产

| asset_id | 资产 | 分级 | 路径 / 报告 | 命令或 runner | 关键指标 | 是否阻断 |
|---|---|---|---|---|---|---|
| `aiops_trace_eval` | AIOps trace evalset | `shadow` / `trace_scorer_asset` | `evals/enterprise/evalsets/aiops_trace_evalset.jsonl`; `evals/enterprise/run_trace_eval.py`; `evals/enterprise/matcher.py` | `uv run python -m evals.enterprise.run_trace_eval --evalset evals/enterprise/evalsets/aiops_trace_evalset.jsonl --mode reference` | 当前 evalset 2 条；matcher 可检查 required stages、forbidden tools、AIOps required tools、evidence categories、failure semantics | 可作为 trace gate 候选；要阻断发布前应明确 P0/P1 阈值。 |
| `aiops_lab_smoke` | AIOps Lab 本地真实模拟环境 | `smoke` / `trace_evidence` | `aiops_lab/`; `docs/aiops_mainline_development_record.md`; `tests/test_aiops_lab_mcp_tools.py`; `tests/test_aiops_lab_files_and_prompt.py` | `uv run pytest tests/test_aiops_lab_mcp_tools.py tests/test_aiops_lab_files_and_prompt.py -q`; lab smoke 脚本按文档运行 | 第一版本地 lab 可验证告警、日志、指标、CMDB 证据链；不接生产 | 可阻断“声称 AIOps lab 已验证”的表述；不能证明生产 AIOps 可用。 |
| `aiops_mainline_mcp_cache` | AIOps MCP discovery cache / recovered fallback 证据 | `historical` / `baseline` | `docs/aiops_mainline_development_record.md`; `tests/test_aiops_mcp_tool_cache.py`; `tests/test_aiops_tool_catalog.py` | `uv run pytest tests/test_aiops_mcp_tool_cache.py tests/test_aiops_tool_catalog.py -q` | MCP cache slice 已收口；recovered structured-output fallback 已被观测化 | 可作为 AIOps 稳定性历史证据；不是新增功能门禁。 |

## 6. 数据库 / Q-SQL / SafeSQL 资产

| asset_id | 资产 | 分级 | 路径 / 报告 | 命令或 runner | 关键指标 | 是否阻断 |
|---|---|---|---|---|---|---|
| `database_qsql_examples` | 门禁场景 Q-SQL 示例 | `baseline` / `safe_sql_evidence` | `docs/数据库_门禁场景_Q-SQL示例.md`; `app/enterprise/database/qsql_examples.py`; `tests/test_qsql_examples.py` | `uv run pytest tests/test_qsql_examples.py -q` | 15 条门禁场景示例；正例已按文档用 `SafeSqlKernel.safe_select(...)` 验证 | 可阻断把 Q-SQL 当训练集或生产 SQL 生成能力的误表述。 |
| `database_safe_select_tool` | RAG/local-agent database safe-select 工具链 | `gate` | `app/tools/database_tool.py`; `tests/test_rag_database_tools.py`; `tests/test_enterprise_database_e6.py`; `tests/test_enterprise_database_e7.py` | `uv run pytest tests/test_rag_database_tools.py tests/test_enterprise_database_e6.py tests/test_enterprise_database_e7.py -q` | ToolGateway、权限、表列 scope、SafeSqlKernel、审计、友好拒绝提示 | 可以阻断数据库能力发布；任何绕过 SafeSqlKernel / PermissionService 的路径应阻断。 |
| `database_operations_confirmation` | DB operation prepare / confirmation / audit | `gate` | `tests/test_enterprise_database_operation_confirm.py`; `tests/test_enterprise_database_operation_permissions.py`; `tests/test_enterprise_database_operation_audit.py` | `uv run pytest tests/test_enterprise_database_operation_confirm.py tests/test_enterprise_database_operation_permissions.py tests/test_enterprise_database_operation_audit.py -q` | pending/confirm/cancel/expired/failed、permission recheck、SQL hash、operation audit | 可以阻断涉及写操作、delete-like、DDL confirmation 的发布。 |

## 7. Enterprise Trace Eval 与治理 Verifier 资产

| asset_id | 资产 | 分级 | 路径 / 报告 | 命令或 runner | 关键指标 | 是否阻断 |
|---|---|---|---|---|---|---|
| `enterprise_trace_eval` | Enterprise trace scorer | `shadow` / `deterministic_gate_candidate` | `evals/enterprise/run_trace_eval.py`; `evals/enterprise/models.py`; `evals/enterprise/matcher.py` | `uv run python -m evals.enterprise.run_trace_eval --evalset <evalset.jsonl> --mode reference` | 检查 final status、required audit events、required stages、forbidden tools、SSE、task contract、DB/AIOps expectations | 可升级为门禁；当前要按 evalset 指定阻断范围。 |
| `trace_evalsets` | Trace evalset 集合 | `shadow` | `evals/enterprise/evalsets/chat_trace_evalset.jsonl` 1 条；`aiops_trace_evalset.jsonl` 2 条；`db_trace_evalset.jsonl` 2 条；`admin_trace_evalset.jsonl` 1 条；`sse_contract_evalset.jsonl` 1 条；`database_agent_operations_2_0.jsonl` 2 条；`knowledge_query_intent_evalset.jsonl` 9 条 | 同上 | 覆盖 chat、AIOps、DB、Admin、SSE、数据库操作、知识意图 | 可作为 trace coverage 资产；样本量不足时不能声称完整覆盖。 |
| `verifier_tests` | P0 deterministic verifier tests | `gate` | `tests/test_enterprise_verifiers.py`; `tests/test_enterprise_human_review.py`; `tests/test_enterprise_gateway_routes.py`; `tests/test_enterprise_tool_gateway.py` | `uv run pytest tests/test_enterprise_verifiers.py tests/test_enterprise_human_review.py tests/test_enterprise_gateway_routes.py tests/test_enterprise_tool_gateway.py -q` | CitationVerifier、PlanVerifier、SqlResultVerifier、human review、gateway audit、tool blocked/audit | 可以阻断治理相关发布。 |
| `audit_database_tests` | DB audit evidence tests | `gate` | `tests/test_enterprise_database_operation_audit.py`; `tests/test_enterprise_database_operation_confirm.py`; `tests/test_enterprise_database_operation_permissions.py` | `uv run pytest tests/test_enterprise_database_operation_audit.py tests/test_enterprise_database_operation_confirm.py tests/test_enterprise_database_operation_permissions.py -q` | confirmation_id、operation/table/column、reason、prepare/confirm/execute/reject audit | 可以阻断数据库操作链路发布。 |

## 8. 微调与 Router 候选资产

| asset_id | 资产 | 分级 | 路径 / 报告 | 命令或 runner | 关键指标 | 是否阻断 |
|---|---|---|---|---|---|---|
| `router_classifier_candidates_52` | Router 分类器 52 条 candidate JSONL | `shadow` / `candidate_set` | 外部 worktree: `/Users/cici/oncall agent/.worktrees/phaseA-bge-m3-smoke/llm_finetuning_workspace/router_classifier_candidates.jsonl`; `router_classifier_candidates_field_completion_report.md`; `router_classifier_candidates_manual_review.md`; `router_classifier_samples.schema.json` | 只读统计和 schema 校验；当前 worktree 不训练、不接生产 | 52 条；分布 `knowledge_qa=12 / database=8 / permission_required=8 / plain_chat=6 / aiops=6 / high_risk=6 / out_of_scope=6`; split `31/10/11`; `quality_status=candidate`; `router_classifier_samples.jsonl` 不存在 | 不能作为训练完成证据；可作为后续实验 A 的 shadow candidate set。 |
| `router_finetuning_plan` | 实验 A：router 分类器离线计划 | `planning_only` | 外部 worktree: `/Users/cici/oncall agent/.worktrees/phaseA-bge-m3-smoke/llm_finetuning_workspace/实验A_路由分类器离线计划.md`; `实验A_路由分类器样本整理流程.md` | 无训练命令 | 目标是离线比较规则/router/prompt baseline，尤其关注 high_risk 和 permission_required false negative | 不能阻断发布；只有观察期证明路由错误是瓶颈后才启动。 |

## 9. 当前不做的事

- 不引入新评测框架。
- 不重跑第二个 embedding 模型。
- 不训练 router classifier。
- 不生成 `router_classifier_samples.jsonl`。
- 不做 Q-SQL 离线草稿实验。
- 不把 BGE-M3、rerank、hybrid、top_k 或微调候选接入生产路径。
- 不改变 `dense_only / query_rewrite=off / rerank_enabled=false / top_k=3`。

## 10. 下一步

下一步不是跑新实验，而是把失败归因统一到项目级 RCA 标签体系：

- `retrieval_wrong_doc`
- `retrieval_no_hit`
- `answer_incomplete`
- `source_ref_unresolvable`
- `permission_scope_issue`
- `intent_misroute`
- `tool_not_called`
- `aiops_evidence_missing`
- `sql_blocked`
- `audit_missing`
- `human_review_bypassed`

如果 RCA 标签显示只是证据散，继续补文档和索引；如果 trace eval 表达不了某类期望路径，再改 `evals/enterprise`；如果 P0 风险缺确定性规则，再补 verifier。
