# RAG Beta 生产试运行用户材料

日期：2026-06-12

状态：`beta_trial_launch_pack_ready`

## 1. 用途

本文档用于小范围生产 beta 试运行。目标是让 3-5 个内部用户真实使用当前 RAG 功能，并把反馈按统一格式记录到：

```text
docs/RAG_Beta_User_Feedback_Log.md
```

反馈字段必须符合：

```text
docs/schemas/rag_user_feedback.schema.json
```

本材料只启动真实用户观察，不改变任何评测 gate 或运行配置。

内部 beta 执行手册：

```text
docs/RAG_Internal_Beta_Runbook_20260612.md
```

## 2. 当前能力口径

可以对 beta 用户说明：

- 当前知识库有 30 个 indexed documents，覆盖 oncall、AIOps、Redis/MySQL runbook、数据库操作能力和 craft PDF。
- Retrieval 层在 Mixed 54q 上为 45/54，通过率 83.3%。
- source_ref、scope、citation 边界在当前 baseline 中保持干净。
- Answer 层硬安全门禁干净，没有把 citation 缺失、unsupported claim、permission leak、source_ref unresolvable 作为通过样本放过。
- Answer 覆盖率有限，可能出现回答不完整，需要用户反馈真实 case。

不要对外承诺：

- 不承诺 Answer 50q 已通过。
- 不承诺 90%+ 答案完整率。
- 不承诺复杂 agent behavior 已验收。
- 不承诺 hybrid、rerank、query rewrite 已启用。

## 3. Beta 用户选择

建议选择 3-5 个内部用户。

选择标准：

- 熟悉 oncall、DB ops、AIOps 或 craft 场景。
- 愿意记录真实 query 和结果反馈。
- 能代表常见问题表达方式，而不是只按评测题提问。
- 不在反馈中粘贴密码、token、客户隐私或生产敏感数据。

## 4. 用户使用说明

用户操作流程：

1. 输入真实问题，例如：
   - `CPU 使用率过高怎么排查`
   - `Redis 内存打满怎么办`
   - `MySQL 慢查询伴随连接池等待怎么处理`
   - `数据库操作哪些需要用户确认`
2. 查看系统回答和引用来源。
3. 如果回答中有 source_ref 或来源信息，记录它是否能回查到原文。
4. 每次发现问题时，按反馈表记录原始 query、召回文档、回答、缺失事实和 source_ref 是否可查。

使用提醒：

- 用自然语言提问，不需要刻意改成文档标题。
- 如果答案不完整，记录缺失了什么事实，而不是只写“不好用”。
- 如果检索到错误文档，记录召回的文档名或 doc_id。
- 如果怀疑看到无权限文档、跨部门内容或不可回查引用，标记为安全/权限问题。

## 5. 用户反馈表单

每条反馈至少填写以下内容：

| 字段 | 填写要求 |
|---|---|
| 日期时间 | 反馈发生时间 |
| 用户 | 用户标识，不写密码/token |
| session_id | 会话标识，若没有则写手工编号 |
| query | 用户原始 query，不能改写 |
| retrieved_docs | 召回文档 doc_id/source_file/kb_id/rank |
| answer | 系统回答原文 |
| answer_issue | 从固定分类里选择 |
| missing_facts | 答案缺失的关键事实 |
| source_refs | 回答或召回中的 source_ref |
| source_ref_resolvable | source_ref 是否可回查 |
| permission_scope_issue | 是否疑似权限或 scope 问题 |
| followup_decision | 后续处理决定 |

`answer_issue` 固定分类：

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

其中 `none` 表示本次反馈未观察到检索、答案、source_ref 或权限/scope 问题；此时 `missing_facts` 可以填写 `-` 或空列表。

`followup_decision` 固定分类：

```text
no_action
queue_for_review
reproduce
open_answer_revisit
open_retrieval_triage
open_security_bug
```

## 6. 单条反馈模板

可直接追加到 `docs/RAG_Beta_User_Feedback_Log.md`：

```markdown
| BETA-YYYYMMDD-001 | 2026-06-12T10:00:00+08:00 | user_x | session-001 | Redis 内存打满怎么办 | doc_xxx / redis_high_memory_runbook.md / process_digital_dept / rank=1 | answer_incomplete | 没有说明 evicted_keys 检查 | true | false | queue_for_review | confirmed | 真实用户反馈，待复现 |
```

如果需要保留完整结构化记录，使用 JSON：

```json
{
  "timestamp": "2026-06-12T10:00:00+08:00",
  "user_id": "user_x",
  "session_id": "session-001",
  "query": "Redis 内存打满怎么办",
  "retrieved_docs": [
    {
      "doc_id": "doc_xxx",
      "source_file": "redis_high_memory_runbook.md",
      "kb_id": "process_digital_dept",
      "rank": 1
    }
  ],
  "answer": "系统回答原文",
  "answer_issue": "answer_incomplete",
  "missing_facts": ["没有说明 evicted_keys 检查"],
  "source_refs": [
    {
      "kb_id": "process_digital_dept",
      "doc_id": "doc_xxx",
      "chunk_id": "doc_xxx:c00001",
      "source_file": "redis_high_memory_runbook.md",
      "heading_path": ["Redis 高内存使用告警处理手册"]
    }
  ],
  "source_ref_resolvable": true,
  "permission_scope_issue": false,
  "followup_decision": "queue_for_review",
  "notes": "真实用户反馈，待复现"
}
```

## 7. 每周 Review 模板

建议每周固定 review 一次。

```markdown
## Week N (YYYY-MM-DD - YYYY-MM-DD)

### 使用统计

- beta_users:
- total_queries:
- feedback_count:
- average_satisfaction:
- retrieval_issue_count:
- answer_issue_count:
- source_ref_issue_count:
- permission_scope_issue_count:

### 主要反馈

| issue_type | count | confirmed_count | representative_feedback_ids | decision |
|---|---:|---:|---|---|
| answer_incomplete | 0 | 0 | - | no_action |
| retrieval_no_hit | 0 | 0 | - | no_action |
| retrieval_wrong_doc | 0 | 0 | - | no_action |
| source_ref_unresolvable | 0 | 0 | - | no_action |
| permission_scope_issue | 0 | 0 | - | no_action |

### 本周决策

- continue_beta:
- expand_beta_users:
- open_answer_revisit:
- open_retrieval_triage:
- open_security_bug:
- notes:
```

## 8. 决策标准

继续 beta：

- 平均满意度大于等于 3.5/5。
- 检索成功率大于等于 80%。
- 没有 source_ref 不可回查集中问题。
- 没有权限/scope 安全问题。

针对性优化：

- 平均满意度在 2.5-3.5/5 之间，或检索/答案问题集中出现。
- 同一类真实反馈累计 3 条以上，并且可以复现。
- 每条反馈都有原始 query、召回文档、回答、缺失事实和 source_ref 回查结果。

暂停 beta：

- 平均满意度低于 2.5/5。
- 检索失败率高于 40%。
- 出现权限/scope 问题。
- 出现 source_ref 大量不可回查。
- 出现 unsupported claim 或用户明确指出编造事实。

## 9. 后续触发路径

如果反馈集中在 `answer_incomplete`：

1. 从真实反馈中挑 5-10 个 confirmed 样本。
2. 复现当前表现。
3. 对照 `docs/RAG_Answer_Layer_C6_Answer_30q_Failure_Triage.md` 判断是否命中已有失败类型。
4. 只做窄范围 Answer revisit，不直接创建 Answer 50q。

如果反馈集中在 `retrieval_no_hit` 或 `retrieval_wrong_doc`：

1. 收集失败 query。
2. 分类为 expression-gap、coverage-gap、chunk-gap 或 permission/scope 问题。
3. 只对 confirmed 失败创建针对性 evalset。
4. 不默认启用 hybrid、rerank 或 query rewrite。

如果反馈集中在 `source_ref_unresolvable` 或 `permission_scope_issue`：

1. 作为安全/引用 bug 优先处理。
2. 暂停扩大 beta 范围。
3. 先修复并复验 source_ref 和 permission/scope smoke。

## 10. 明确不做

本 beta 试运行不做：

- 不创建 Answer 50q。
- 不把 OpenJudge/RAGAS 作为主 gate。
- 不进入 agent_behavior acceptance。
- 不修改 `app/config.py` 或 `.env`。
- 不修改 `rag_default_retrieval_mode=dense_only`。
- 不启用 query rewrite、rerank 或默认 hybrid。
- 不用单个用户反馈直接推动全局 prompt/top_k 变化。
