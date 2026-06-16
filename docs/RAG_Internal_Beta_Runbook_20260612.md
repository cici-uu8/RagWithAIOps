# RAG Internal Beta Runbook

日期：2026-06-12

状态：`internal_beta_runbook_ready`

## 1. 目标

本文档用于执行当前 RAG MVP 的小范围 internal beta。

它不是新的评测 gate，也不是 GA 上线批准。它把已有 MVP baseline、用户材料、反馈日志和生产就绪 checklist 连接成一套可执行流程，避免继续在 synthetic evalset 上空转。

输入基线：

```text
MVP baseline = docs/RAG_MVP_Baseline_20260612.md
Production checklist = docs/RAG_Production_Readiness_Checklist.md
User material = docs/RAG_Beta_生产试运行用户材料.md
Feedback log = docs/RAG_Beta_User_Feedback_Log.md
Feedback schema = docs/schemas/rag_user_feedback.schema.json
```

当前固定边界：

```text
retrieval_baseline = 45/54
answer_baseline = 18/30
beta_smoke = 7/7
rag_default_retrieval_mode = dense_only
rag_query_rewrite_mode = off
rerank_enabled = false
rag_top_k = 3
```

## 2. 当前事实

当前项目已经具备 internal beta 的最小条件：

- 30 indexed docs 已固化。
- Retrieval Mixed 54q 为 `45/54`，达到 `>=80%` beta 健康线。
- Answer 30q 为 `18/30`，完整性有限，但硬安全边界干净。
- Beta readiness smoke 当前为 `7/7 passed`。
- Week 1 反馈已经记录 3 个用户角色、11 条真实 query，retrieval success `9/11`，平均满意度 `4.09/5`，source_ref 和 permission/scope 问题均为 0。

当前不能升级的结论：

- 不能叫 GA。
- 不能进入 agent_behavior 验收。
- 不能创建 Answer 50q。
- 不能把 OpenJudge/RAGAS 变成主 gate。
- 不能默认启用 hybrid、rerank、query rewrite 或全局 top_k=5。

## 3. 角色分工

| role | responsibility | required action |
|---|---|---|
| beta_owner | 控制 beta 范围和节奏 | 每天看反馈，决定继续、暂停或扩大 |
| seed_user | 用真实问题测试 | 不粘贴 secret、token、客户隐私或生产敏感数据 |
| feedback_recorder | 记录结构化反馈 | 维护 `docs/RAG_Beta_User_Feedback_Log.md` |
| technical_reviewer | 复现 confirmed 问题 | 判断 retrieval、answer、source_ref、permission/scope 分类 |
| release_owner | 判断是否扩大 beta | 对照本 runbook 和 Production checklist |

最小 beta 用户池：

```text
3-5 internal users
roles = oncall / DBA / craft or document-review user
duration = 1 week observation window
```

## 4. Launch-Day Checklist

启动或重新启动 beta 当天执行：

1. 确认工作区未混入依赖或默认配置变更：

```bash
git status --short
git diff --name-only -- pyproject.toml uv.lock app/config.py .env
```

2. 运行 beta readiness smoke：

```bash
.venv/bin/python -m evals.knowledge_base.beta_readiness_smoke \
  --output evals/knowledge_base/reports/beta_readiness_smoke_YYYYMMDD.json
```

3. 核对 smoke 结果：

```text
status = passed
check_count = 7
passed_count = 7
failed_count = 0
external_llm_called = false
external_vector_db_called = false
```

4. 给用户发送 `docs/RAG_Beta_生产试运行用户材料.md`。

5. 确认用户知道限制：

- 答案可能遗漏细节。
- 当前是 dense-only retrieval。
- 不要粘贴 secret、token、客户隐私或生产敏感数据。
- 发现问题时记录原始 query、召回文档、答案、缺失事实和 source_ref 是否可查。

6. 确认反馈记录位置：

```text
docs/RAG_Beta_User_Feedback_Log.md
```

## 5. Alpha Test Plan

### Day 1 - 启动检查

- 跑 launch-day smoke。
- 确认 3-5 个 seed users。
- 确认用户材料已发送。
- 确认反馈日志可写。
- 确认本轮 beta 不改默认配置。

### Day 2-5 - 真实问题观察

每个 seed user 提交真实 query，不要求按 evalset 提问。

建议覆盖：

| role | target query type |
|---|---|
| oncall | CPU、磁盘、服务不可用、PVC、告警处理 |
| DBA | Redis 内存、MySQL 慢查询、数据库操作边界 |
| craft / document review | PDF 表格、页码、报告条款、合规说明 |

每天记录：

- total_queries
- feedback_count
- retrieval_success_count
- answer_issue_count
- source_ref_issue_count
- permission_scope_issue_count
- representative failures

### Day 6-7 - 周度分流

按以下顺序分流：

1. permission/scope 问题：安全问题优先，暂停扩大 beta。
2. source_ref 不可回查：引用链 bug 优先。
3. retrieval_no_hit / retrieval_wrong_doc：累计 3 条 confirmed 后重开 retrieval triage。
4. answer_incomplete / answer_wrong：累计 3 条 confirmed 后重开 narrow Answer revisit。
5. 单条孤立问题：进入 watchlist，不改默认配置。

## 6. 监控指标

### Core Health

| metric | target | source | action if breached |
|---|---:|---|---|
| beta smoke status | passed | beta readiness smoke report | 暂停 beta 启动 |
| retrieval_success_rate | >=80% | feedback log | 低于阈值则 review retrieval failures |
| average_satisfaction | >=3.5/5 | feedback log | 低于阈值则暂停扩大 beta |
| source_ref_issue_count | 0 clustered | feedback log | 优先修 source_ref |
| permission_scope_issue_count | 0 | feedback log | 作为安全 bug 处理 |

### Quality Breakdown

| issue type | trigger | next action |
|---|---:|---|
| answer_incomplete | 3+ confirmed | open narrow Answer revisit |
| answer_wrong | 1+ high-risk or 3+ normal | review answer generation and eval expectation |
| retrieval_no_hit | 3+ confirmed | open retrieval triage |
| retrieval_wrong_doc | 3+ confirmed | classify expression/chunk/ranking gap |
| expression_gap | 3+ confirmed | consider query rewrite shadow, not default enablement |
| source_ref_unresolvable | repeated or clustered | citation/source_ref bug first |
| permission_scope_issue | any | security bug first |

### Operational Notes

- `unsupported_claim_count`、`permission_leak_count`、`source_ref_unresolvable_count` 出现时优先级高于 pass rate。
- 单条反馈不能推动全局 prompt、top_k、hybrid、rerank 或 query rewrite 变化。
- 所有优化必须从 confirmed 真实反馈触发，并带 source_ref evidence。

## 7. 反馈收集规则

每条反馈必须保留：

```text
original query
retrieved docs
answer
answer_issue
missing_facts
source_ref_resolvable
permission_scope_issue
followup_decision
```

`answer_issue` 使用固定枚举：

```text
none
answer_incomplete
answer_wrong
source_ref_unresolvable
permission_scope_issue
retrieval_no_hit
retrieval_wrong_doc
expression_gap
other
```

`followup_decision` 使用固定枚举：

```text
no_action
queue_for_review
reproduce
open_answer_revisit
open_retrieval_triage
open_security_bug
```

最小记录格式见：

```text
docs/RAG_Beta_生产试运行用户材料.md
docs/RAG_Beta_User_Feedback_Log.md
```

## 8. 每日检查模板

```markdown
## Daily Beta Check - YYYY-MM-DD

- beta_users:
- total_queries_today:
- feedback_count_today:
- retrieval_success_count:
- answer_issue_count:
- source_ref_issue_count:
- permission_scope_issue_count:
- smoke_status:
- continue_beta:
- blockers:
- watchlist:
- owner_notes:
```

## 9. 周度 Review 模板

```markdown
## Weekly Beta Review - YYYY-MM-DD

### Summary

- beta_users:
- total_queries:
- retrieval_success_rate:
- average_satisfaction:
- source_ref_issue_count:
- permission_scope_issue_count:

### Issue Clusters

| issue_type | count | confirmed_count | feedback_ids | decision |
|---|---:|---:|---|---|
| answer_incomplete | 0 | 0 | - | no_action |
| retrieval_no_hit | 0 | 0 | - | no_action |
| retrieval_wrong_doc | 0 | 0 | - | no_action |
| source_ref_unresolvable | 0 | 0 | - | no_action |
| permission_scope_issue | 0 | 0 | - | no_action |

### Decision

- continue_beta:
- expand_beta_users:
- open_answer_revisit:
- open_retrieval_triage:
- open_security_bug:
- notes:
```

## 10. 决策规则

继续 internal beta：

```text
average_satisfaction >= 3.5
retrieval_success_rate >= 80%
source_ref_unresolvable_cluster = false
permission_scope_issue = false
```

暂停或缩小 beta：

```text
permission_scope_issue = true
source_ref_unresolvable_cluster = true
retrieval_failure_rate > 40%
average_satisfaction < 2.5
```

扩大 beta：

```text
one_week_feedback_completed = true
no permission/scope incidents
no source_ref cluster
retrieval_success_rate >= 80%
average_satisfaction >= 3.5
owner approval = true
```

进入 targeted optimization：

```text
same_issue_type_confirmed_count >= 3
reproducible = true
source_ref_evidence_present = true
```

## 11. 禁止事项

Internal beta 期间默认不做：

- 不创建 Answer 50q。
- 不进入 agent_behavior acceptance。
- 不把 OpenJudge/RAGAS 作为主 gate。
- 不修改 `app/config.py` 或 `.env`。
- 不修改 `rag_default_retrieval_mode=dense_only`。
- 不启用 query rewrite、rerank 或默认 hybrid。
- 不把单条用户反馈升级成全局 prompt/top_k 变化。
- 不提交本地 `evals/knowledge_base/reports/` 报告，除非 owner 明确要求。
