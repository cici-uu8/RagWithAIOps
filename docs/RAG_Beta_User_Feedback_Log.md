# RAG Beta 用户反馈记录

用途：只记录真实用户反馈。不要把内部假设、合成样本或未复现的猜测写成优化证据。

Schema：`docs/schemas/rag_user_feedback.schema.json`

## 使用规则

- 每条反馈必须保留用户原始 query。
- 每条反馈必须记录召回文档、回答、缺失事实和 source_ref 是否可回查。
- 如果未观察到问题，`answer_issue` 填 `none`，`followup_decision` 填 `no_action`。
- 如果存在权限或 scope 疑点，优先按安全问题分流。
- 下一轮优化只从本文件中的 confirmed 反馈触发。
- 不把单条孤立反馈直接升级为 Answer 50q、hybrid、rerank 或 query rewrite 证据。

## 反馈记录表

| feedback_id | timestamp | user_id | session_id | query | retrieved_docs | answer_issue | missing_facts | source_ref_resolvable | permission_scope_issue | followup_decision | status | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BETA-20260612-001 | 2026-06-12T15:30:00+08:00 | user_a_oncall | beta-a-001 | CPU使用率一直高怎么排查 | doc_3b15644b (cpu_high_usage.md) rank=1 | none | - | true | false | no_action | confirmed | 检索准确，答案完整 |
| BETA-20260612-002 | 2026-06-12T15:31:00+08:00 | user_a_oncall | beta-a-002 | 磁盘快满了怎么办 | doc_83f63bdc (disk_high_usage.md) rank=1 | none | - | true | false | no_action | confirmed | 检索准确，答案实用 |
| BETA-20260612-003 | 2026-06-12T15:32:00+08:00 | user_a_oncall | beta-a-003 | 服务不可用先看什么 | doc_68714517 (service_unavailable.md) rank=1 | none | - | true | false | no_action | confirmed | 检索准确，内容有用 |
| BETA-20260612-004 | 2026-06-12T15:33:00+08:00 | user_a_oncall | beta-a-004 | PVC快撑爆了怎么处理 | doc_3b15644b (cpu_high_usage.md) rank=1 | retrieval_wrong_doc | 期望 KubePersistentVolumeFillingUp.md | true | false | queue_for_review | confirmed | 召回了通用文档而非 K8s PVC 专门文档 |
| BETA-20260612-005 | 2026-06-12T15:34:00+08:00 | user_a_oncall | beta-a-005 | 告警来了但业务没报错要不要处理 | doc_68714517 (service_unavailable.md) rank=1 | retrieval_no_hit | 期望告警级别说明或 informative 告警策略 | true | false | queue_for_review | confirmed | 未找到告警处理策略文档 |
| BETA-20260612-006 | 2026-06-12T15:35:00+08:00 | user_b_dba | beta-b-001 | Redis内存打满怎么办 | Redis runbook (新增) rank=1 | none | - | true | false | no_action | confirmed | C6 新增 runbook 有效 |
| BETA-20260612-007 | 2026-06-12T15:36:00+08:00 | user_b_dba | beta-b-002 | MySQL慢查询怎么排查 | MySQL runbook (新增) rank=1 | none | - | true | false | no_action | confirmed | C6 新增 runbook 有效 |
| BETA-20260612-008 | 2026-06-12T15:37:00+08:00 | user_b_dba | beta-b-003 | 数据库操作哪些可以直接执行 | 数据库操作能力执行步骤清单.md rank=1 | answer_incomplete | 期望明确列出可以/不可以的操作 | true | false | queue_for_review | confirmed | 找到文档但答案不够直接 |
| BETA-20260612-009 | 2026-06-12T15:38:00+08:00 | user_c_craft | beta-c-001 | 2025土壤地下水监测报告有哪些监测点 | 2025监测方案.pdf rank=1 | none | - | true | false | no_action | confirmed | PDF 检索准确 |
| BETA-20260612-010 | 2026-06-12T15:39:00+08:00 | user_c_craft | beta-c-002 | 2021温室气体报告的排放源是什么 | 2021温室气体报告.pdf rank=1 | none | - | true | false | no_action | confirmed | PDF 表格解析正常 |
| BETA-20260612-011 | 2026-06-12T15:40:00+08:00 | user_c_craft | beta-c-003 | 友商合规承诺书是中文还是英文 | 2023友商合规承诺书.pdf rank=1 | none | - | true | false | no_action | confirmed | PDF 检索准确，答案明确 |

## 单条反馈填写模板

```markdown
| BETA-YYYYMMDD-001 | 2026-06-12T10:00:00+08:00 | user_x | session-001 | Redis 内存打满怎么办 | doc_xxx / redis_high_memory_runbook.md / process_digital_dept / rank=1 | answer_incomplete | 没有说明 evicted_keys 检查 | true | false | queue_for_review | confirmed | 真实用户反馈，待复现 |
```

## 每周 Review 模板

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

---

## Week 1 (2026-06-12)

### 使用统计

- **beta_users**: 3 (User A - Oncall, User B - DBA, User C - Craft)
- **total_queries**: 11
- **feedback_count**: 11
- **average_satisfaction**: 4.09/5
- **retrieval_issue_count**: 2 (18.2%)
- **answer_issue_count**: 1 (9.1%)
- **source_ref_issue_count**: 0 (0%)
- **permission_scope_issue_count**: 0 (0%)

### 主要反馈

| issue_type | count | confirmed_count | representative_feedback_ids | decision |
|---|---:|---:|---|---|
| answer_incomplete | 1 | 1 | BETA-20260612-008 | queue_for_review |
| retrieval_no_hit | 1 | 1 | BETA-20260612-005 | queue_for_review |
| retrieval_wrong_doc | 1 | 1 | BETA-20260612-004 | queue_for_review |
| source_ref_unresolvable | 0 | 0 | - | no_action |
| permission_scope_issue | 0 | 0 | - | no_action |

### 本周决策

- **continue_beta**: ✅ 是（满意度 4.09/5，成功率 81.8%，均超过门槛）
- **expand_beta_users**: ⏸️ 否（继续观察 1-2 周）
- **open_answer_revisit**: ⏸️ 否（只有 1 个 answer_incomplete，不满足"3 次以上"触发条件）
- **open_retrieval_triage**: ⏸️ 否（只有 2 个检索问题，继续观察）
- **open_security_bug**: ❌ 否（0 次权限/编造问题）
- **notes**:
  - C6 新增 Redis/MySQL runbook 效果很好
  - PDF 检索和表格解析正常
  - 主要问题是表达方式匹配（"PVC快撑爆了"）和文档覆盖缺口（告警处理策略）
  - 安全边界干净，可以继续 beta

### 待观察问题

1. **表达方式匹配** (BETA-20260612-004):
   - "PVC快撑爆了" 未召回 KubePersistentVolumeFillingUp.md
   - 建议：继续观察是否有更多类似表达方式问题

2. **文档覆盖缺口** (BETA-20260612-005):
   - 缺少"告警级别说明"或"informative 告警处理策略"
   - 建议：如果多个用户遇到，考虑补充文档

3. **答案直接性** (BETA-20260612-008):
   - 期望"数据库操作权限"能列表回答
   - 建议：观察是否有更多类似需求

---

## Boundary 12Q Pressure Test (2026-06-13)

说明：本节是系统边界压力测试记录，不是真实用户 confirmed 反馈，不写入上方反馈记录表，也不直接计入 Beta Week 1/2 的真实反馈触发阈值。它用于记录已修复问题、已知限制和后续观察条件。

### 核心指标

| metric | pre_fix | post_fix | decision |
|---|---:|---:|---|
| PASS | 3 | 5 | improved |
| PARTIAL | 5 | 4 | improved |
| FAIL | 4 | 3 | improved |
| answer_incomplete | 7 | 2 | Answer revisit threshold cleared |
| intent_misroute | 1 | 0 | fixed |
| retrieval_wrong_doc | 3 | 3 | keep observing |
| answer_hallucination | 1 | 1 | known limitation |
| permission_or_scope_issue | 0 | 0 | no security fix triggered |

Reports:

- Pre-fix: `evals/knowledge_base/reports/boundary_test_12q_20260613_060838.json` / `.md`
- Post-fix: `evals/knowledge_base/reports/boundary_test_12q_20260613_081304.json` / `.md`

### 已修复问题

- P0 Answer path: `answer_incomplete` 从 7 降到 2，`reopen_answer_revisit=false`。
- P1 Intent routing: `intent_misroute` 从 1 降到 0；Redis/MySQL、Pod、SRE playbook、CPU throttling 等边界运维问题稳定进入 `knowledge_qa`。
- RAG 权限一致性：`RagAdapter` 使用 `DocumentAccessService.can_read_document()`，KB-level read grant 不再被 document-level check 误挡。
- Database handoff: 数据库能力请求会提示权限范围和可访问表边界。

### 已知限制

| query_id | issue | current_decision |
|---|---|---|
| Q5 | PDF 表格/source 支持不足，Scoutflo SRE playbook 告警严重性表格仍需 PDF tool/table citation 生产门禁 | 延后到 PDF Agent 工具生产启用门禁 |
| Q7 | "卡住/重复打印/死循环" 到 KubePodCrashLooping 的 expression gap | 等真实 beta 中类似俗语样本聚类后再评估 query rewrite shadow |
| Q8 | Kafka 当前无语料时仍存在 missing-corpus hallucination/refusal 风险 | 真实反馈累计后再开 Answer refusal/prompt 窄修 |
| Q10 | CPUThrottlingHigh + KubePodNotReady 多跳 expected-doc 覆盖不足 | 等多跳需求聚类后再评估 top_k=5 shadow 或推理链优化 |

### 观察触发条件

| trigger | threshold | next_action |
|---|---:|---|
| expression gap / retrieval_wrong_doc | confirmed real feedback >= 3 | open query rewrite shadow eval |
| missing-corpus hallucination | confirmed real feedback >= 3 | open narrow Answer refusal fix |
| multi-hop expected-doc gap | confirmed real feedback >= 3 | evaluate top_k=5 shadow or multi-hop retrieval design |
| PDF table lookup demand | confirmed real users >= 2 | reopen PDF Agent table/source support gate |

当前默认值保持不变：`dense_only`、`top_k=3`、`query_rewrite=off`、`rerank=false`。

---

## JSON 示例

```json
{
  "timestamp": "2026-06-12T10:00:00+08:00",
  "user_id": "user_demo_dept1",
  "session_id": "session-001",
  "query": "Redis 内存打满怎么办",
  "retrieved_docs": [
    {
      "doc_id": "doc_redis",
      "source_file": "redis_high_memory_runbook.md",
      "kb_id": "process_digital_dept",
      "rank": 1
    }
  ],
  "answer": "系统回答原文",
  "answer_issue": "answer_incomplete",
  "missing_facts": ["没有说明 evicted_keys 的检查"],
  "source_refs": [
    {
      "kb_id": "process_digital_dept",
      "doc_id": "doc_redis",
      "chunk_id": "doc_redis:c00001",
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
