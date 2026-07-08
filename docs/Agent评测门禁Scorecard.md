---
feature_ids:
  - agent-eval-gate-scorecard
topics:
  - agent-evaluation
  - release-gate
  - governance
  - scorecard
doc_kind: scorecard
created: 2026-07-07
status: documentation_only
---

# Agent 评测门禁 Scorecard

## 1. 文档定位

本文把 `Agent评测资产索引.md` 和 `Agent评测RCA标签体系.md` 收敛成一页可执行门禁表。

它不是新的测试框架，也不是上线证明。它只回答：

- 哪些证据可以阻断发布或默认策略提升。
- 哪些证据只能触发 shadow / observation / triage。
- 哪些风险必须由确定性规则判断，不能交给 LLM Judge。

本文件不训练模型、不改变生产默认值。`G-P0-AUDIT-EVIDENCE`
已有第一版离线 verifier / gate runner，定位是发布前检查项，不是生产链路拦截器。

## 2. 门禁层级

| 层级 | 含义 | 决策动作 |
|---|---|---|
| P0 deterministic gate | source_ref、权限、SafeSQL、human review、audit 等安全/治理硬边界。 | 失败时阻断发布或阻断对应能力开启。 |
| P1 promotion gate | RAG retrieval、trace trajectory、Answer coverage 等能力质量门禁。 | 失败时阻断默认策略提升或阻断 GA 质量声明。 |
| Shadow gate | embedding、rerank、router candidate、fine-tune candidate 等旁路候选。 | 只能决定 keep-shadow / reject / continue-shadow，不能改生产。 |
| Observation trigger | beta feedback、人工 review、真实使用问题。 | 达到聚类阈值后开 triage；单条不直接改默认值。 |
| Smoke gate | beta/demo 前最小闭环。 | 可阻断 beta/demo 启动；不能证明完整质量。 |

## 3. 当前门禁表

| gate_id | 覆盖风险 | 证据资产 | 当前状态 | 阻断条件 | 下一步 |
|---|---|---|---|---|---|
| `G-P0-SOURCE-REF` | 引用不可回查、citation/source_ref 断裂 | `rag_mixed_54q`; `beta_readiness_smoke`; `verifier_tests` / `CitationVerifier` | 当前 Mixed 54q `citation_unresolvable_count=0`, `all_source_ref_resolvable=true` | 任一发布路径出现 `source_ref_unresolvable`；citation 只有展示文本但缺结构化 `source_ref` | 保持 deterministic verifier；不要用 LLM Judge 代替。 |
| `G-P0-PERMISSION-SCOPE` | KB scope、跨部门、数据库表列权限泄露 | `rag_mixed_54q`; `boundary_12q`; `database_safe_select_tool`; `verifier_tests` | 当前 Mixed 54q `wrong_scope_count=0`; Boundary post-fix `permission_or_scope_issue=0` | 出现 wrong scope、未授权文档/表/列/工具结果泄露 | 必须进 regression；需要时补权限 verifier。 |
| `G-P0-SAFE-SQL` | SQL 绕过 SafeSQL 或权限边界 | `database_safe_select_tool`; `database_operations_confirmation`; `database_qsql_examples` | SafeSQL / permission / confirmation 已有测试资产；Q-SQL 只是示例证据 | SQL 直接执行绕过 `SafeSqlKernel`；未授权表列未被阻断；危险操作绕过 confirmation | 保持 `sql_blocked` 正负样本分开；不做 Q-SQL 生产生成。 |
| `G-P0-HUMAN-REVIEW` | 高风险任务绕过人工审核或确认 | `verifier_tests`; `tests/test_enterprise_human_review.py`; `database_operations_confirmation` | Human review 和 DB confirmation 有确定性测试资产 | high-risk false negative；reject 后仍执行；需要 confirmation 的操作被直接执行 | 若缺覆盖，再补 `HumanReviewVerifier` 或 trace forbidden-tool case。 |
| `G-P0-AUDIT-EVIDENCE` | allow / deny / block / execute 决策缺审计证据 | `audit_database_tests`; `enterprise_trace_eval`; gateway/tool tests; `run_audit_evidence_gate.py` | `AuditEvidenceVerifier`、离线 gate runner、trace source 输入和 scorecard 聚合入口已实现；未接生产入口 | P0 决策缺 `trace_id/request_id/resource_id/reason/decision metadata` 等关键字段 | 继续保持离线发布前检查项；不改 `AuditService.record()`。 |
| `G-P1-TRACE-TRAJECTORY` | 工具调用轨迹、required stages、forbidden tools 不符合预期 | `enterprise_trace_eval`; `trace_evalsets`; `aiops_trace_eval` | 当前是 `deterministic_gate_candidate`，已可被 scorecard runner 聚合 | 关键 trace eval 中 required tool/stage 缺失，或 forbidden tool 出现 | 先用 scorecard runner 编排；必要时再补 `ToolTrajectoryVerifier`。 |
| `G-P1-RAG-RETRIEVAL` | RAG retrieval 质量回退、默认策略提升证据不足 | `rag_mixed_54q`; `topk_rerank_matrix`; `retrieval_mode_history` | 当前 baseline `45/54`; top_k/rerank 仅 keep-shadow / reject | 默认策略候选低于 baseline，或 source_ref/scope 回归 | 不改 `dense_only / off / false / top_k=3`。 |
| `G-P1-ANSWER-COVERAGE` | Answer 完整性不足、过早 GA / Answer 50q | `answer_30q`; `beta_feedback`; `Boundary 12Q` | 当前 Answer 30q `18/30` 是 limitation record | 把 `18/30` 误写为成熟 Answer；真实反馈聚类到 answer_incomplete | 只从真实反馈或窄 Answer pilot 重开。 |
| `G-SHADOW-MODEL-COMPARE` | 模型/检索候选被过早提升 | `bge_m3_shadow_54q`; `topk_rerank_matrix`; `model_comparison_overview` | BGE-M3 `38/54 keep-shadow`; rerank reject | 候选未超过 baseline 或成本/安全不满足却试图切默认 | 继续 shadow，不跑第二模型堆材料。 |
| `G-SHADOW-ROUTER-FINETUNE` | router 微调候选被误当训练完成 | `router_classifier_candidates_52`; `router_finetuning_plan` | 52 条为 `quality_status=candidate`; 无 reviewed samples；未训练 | 生成/接入生产 router classifier；把 candidate 当训练集成果 | 观察期证明路由错误是瓶颈后，再生成 reviewed samples。 |
| `G-OBS-BETA-FEEDBACK` | 真实用户反馈未进入质量闭环 | `beta_feedback`; `docs/RAG_Internal_Beta_Runbook_20260612.md` | 3 角色 / 11 query；source_ref 和 permission issue 为 0 | 同类 confirmed issue 达到 runbook 阈值但未 triage | 周审进入 RCA；单条不改默认值。 |
| `G-SMOKE-BETA-DESKTOP` | beta/demo 最小闭环不可用 | `beta_readiness_smoke`; `desktop_smoke_acceptance` | beta smoke `7/7`; desktop smoke `21/21`; acceptance `51 PASS / 0 FAIL / 2 PARTIAL` | smoke 失败；目标环境配置漂移；PDF/AIOps/Memory caveat 被误写为全通过 | beta 前重跑 smoke；PARTIAL 不写成完成。 |

## 4. 当前总判定

```text
release_gate_status = documentation_scorecard_ready
runtime_code_changed = offline_verifier_only
production_defaults_changed = false
model_training_started = false
router_production_integration = false
```

当前可以声明的是：

- 项目已有一套可索引的 Agent 评测资产。
- P0 风险优先由确定性规则、trace、audit 和 verifier 判断。
- embedding / rerank / router 微调仍然是 shadow / planning-only。
- 下一步若继续实现，优先补 fixtures / trace eval 离线接入，而不是 LLM Judge 或主模型 SFT。

当前不能声明的是：

- 评测平台已经实现完成，或 Audit gate 已经接入生产链路。
- Router classifier 已训练完成。
- BGE-M3 可以替换生产 embedding。
- Answer 质量已经达到 GA。
- AIOps 生产诊断链路已经完整通过。

## 5. 可执行命令

`G-P0-AUDIT-EVIDENCE` 当前可用离线 runner 检查审计事件 JSON / JSONL，也可以从真实 trace source 读取 JSONL / SQLite 审计记录。

聚合发布前检查入口：

```bash
uv run python -m evals.enterprise.run_agent_eval_scorecard \
  --trace-evalset evals/enterprise/evalsets/chat_trace_evalset.jsonl \
  --audit-events evals/enterprise/fixtures/audit_evidence/pass_events.jsonl \
  --output-dir /tmp/agent_eval_scorecard_reports
```

这个入口会串联：

- `G-P1-TRACE-TRAJECTORY`：调用 `run_trace_eval.py` 检查 trace evalset。
- `G-P0-AUDIT-EVIDENCE`：调用 `run_audit_evidence_gate.py` 检查 audit evidence。

任一 gate 失败时，`run_agent_eval_scorecard.py` 返回 exit code `1`。它仍然是离线发布前检查项，不接 CI、不改生产链路、不改变 `AuditService.record()`。

手写 fixture / 导出文件模式：

```bash
uv run python -m evals.enterprise.run_audit_evidence_gate \
  --audit-events <audit-events.jsonl> \
  --output-dir evals/enterprise/reports
```

真实 trace source 模式：

```bash
uv run python -m evals.enterprise.run_audit_evidence_gate \
  --source-kind jsonl \
  --path <audit-events.jsonl> \
  --trace-id <trace-id> \
  --request-id <request-id> \
  --output-dir evals/enterprise/reports
```

```bash
uv run python -m evals.enterprise.run_audit_evidence_gate \
  --source-kind sqlite \
  --path <enterprise-audit.sqlite> \
  --trace-id <trace-id> \
  --request-id <request-id> \
  --output-dir evals/enterprise/reports
```

输入支持三种形态：

- JSONL：每行一个 audit event object。
- JSON array：整个文件是 audit event object 数组。
- JSON object：顶层包含 `audit_events: [...]`。

参数边界：

- `--audit-events` 和 `--source-kind` / `--path` / `--trace-id` / `--request-id` 互斥。
- trace source 必须提供 `--source-kind`、`--path`、`--trace-id`；`--request-id` 可选但建议提供。
- trace source 没有匹配事件时返回失败报告，不允许静默通过。

输出：

- `audit_evidence_gate_<input>_<timestamp>.json`
- `audit_evidence_gate_<input>_<timestamp>.md`
- exit code `0` 表示通过，exit code `1` 表示失败。
- report 保留 `audit_events_path` 兼容字段，并新增 `source_kind`、`source_path`、`trace_id`、`request_id`。

最小样例：

```bash
uv run python -m evals.enterprise.run_audit_evidence_gate \
  --audit-events evals/enterprise/fixtures/audit_evidence/pass_events.jsonl \
  --output-dir /tmp/audit_evidence_gate_reports
```

反例样例：

```bash
uv run python -m evals.enterprise.run_audit_evidence_gate \
  --audit-events evals/enterprise/fixtures/audit_evidence/fail_missing_evidence.json \
  --output-dir /tmp/audit_evidence_gate_reports
```

## 6. 最小后续实现候选

| 候选 | 为什么排在这里 | 是否现在做 |
|---|---|---|
| `AuditEvidenceVerifier` fixtures | 让别人不用读测试代码，也能用 pass/fail 样例理解离线 gate 怎么跑。 | 已有 `evals/enterprise/fixtures/audit_evidence/`。 |
| `ToolTrajectoryVerifier` | 服务 trace trajectory：required tool / forbidden tool 的确定性检查。 | 第二候选，适合接 `evals/enterprise`。 |
| LLM Judge | 适合解释质量、答案完整性等主观项。 | 暂不优先。P0 不交给 Judge。 |
| Router fine-tune | 需要 reviewed samples 和真实路由错误证据。 | 后置。当前只有 candidate set。 |
| Q-SQL 离线草稿 | 高风险，且样本不足。 | 后置，只能离线 + SafeSQL。 |

## 7. 使用规则

以后每次新增评测资产或 badcase，先问三个问题：

1. 它属于 `gate / baseline / shadow / observation / historical / smoke` 哪一类。
2. 它对应哪个 RCA 标签，主责模块是谁。
3. 它能阻断什么：发布、默认策略提升、候选 promotion、还是只触发 triage。

如果这三个问题答不清楚，不应直接把它写成“已完成能力”。
