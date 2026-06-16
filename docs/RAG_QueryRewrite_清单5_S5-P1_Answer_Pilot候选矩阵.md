# RAG Query Rewrite 清单 5 S5-P1 Answer Pilot 候选矩阵

日期：2026-06-11

状态：`formal_jsonl_created_and_s5_p2_baseline_run`

对应设计：`docs/RAG_Answer_Layer_Eval_清单5_S5设计.md`

---

## 0. 结论

本文件最初是 review-only 候选矩阵；2026-06-11 已完成逐题人工 review，并创建正式 JSONL。

从 Mixed 50q 中挑选 20 个 retrieval passed 样本，补充 Answer 层字段，人工 review 通过后，再创建正式 `department_rag_answer_pilot_20q.jsonl`。

当前状态：

```text
formal_jsonl_created = yes
answer_baseline_run = yes
answer_baseline_passed = no
ragas_used_for_generation = no
human_review_status = approved
sample_selection_complete = yes
answer_field_templates_ready = yes
formal_jsonl_path = evals/knowledge_base/evalsets/department_rag_answer_pilot_20q.jsonl
answer_baseline_report = evals/knowledge_base/reports/department_rag_answer_pilot_20q_baseline_20260611.json
```

---

## 1. 为什么不用 RAGAS 起步

### 1.1 第一版必须是高质量 Ground Truth

**S5 目标**：测"拿到正确上下文后，答案写得对不对"

**要求**：
- 样本必须 retrieval 层稳定（expected doc 已命中）
- Answer 层字段必须人工审核过（reference_answer / must_include_facts 是标准）
- 不能让 LLM 自动生成的内容当 ground truth

**RAGAS 的问题**：
- RAGAS 生成的 query 质量 60-70%，需要大量筛选
- RAGAS 生成的 reference_answer 可能错误或不完整
- 第一版用 RAGAS 会把"定标准"和"扩量"混在一起

### 1.2 正确顺序

```text
第一版 (S5-P1): 手工挑选 20q，人工审核，定标准 ← 我们在这
第二版 (S5-P2): 跑 Answer Baseline，验证标准可行
第三版 (S5-P3): 用 RAGAS 扩充到 50q，复用已验证的标准
```

---

## 2. 样本选择规则

### 2.1 硬性要求

| 规则 | 原因 |
|---|---|
| ✅ Retrieval passed | S5 focus 是 answer 层，不测 retrieval |
| ✅ Expected doc 已命中 top-3 | 上下文稳定，失败只能归因给 answer |
| ✅ Source_ref 可回查 | Citation 验证依赖 source_ref |
| ✅ 人工可验证答案 | 必须有明确的文档依据 |

### 2.2 覆盖目标

| 维度 | 目标 | 当前 41 个 passed 分布 |
|---|---:|---:|
| **Document format** | | |
| Markdown | 8-10 | 20 可选 |
| PDF | 10-12 | 21 可选 |
| **Query type** | | |
| Fact lookup | 6-8 | content_recall: 14 |
| How-to / troubleshooting | 6-8 | (混在 content_recall 中) |
| Citation-heavy (page/table) | 4-6 | page: 4, table: 4 |
| **Answer risk** | | |
| Low (simple fact) | 8-10 | |
| Medium (multi-fact) | 6-8 | |
| High (易编造/易混淆) | 2-4 | |

### 2.3 不选的样本

| 类型 | 原因 |
|---|---|
| ❌ Retrieval failed | 先修 retrieval |
| ❌ Expression-gap passed | 虽然 passed 但 query 不标准 |
| ❌ Permission/scope 边界 | 已在 retrieval 层验证 |
| ❌ 过于简单（一个词） | 无法测 answer 质量 |
| ❌ 过于复杂（多步推理） | 超出当前 scope |

---

## 3. 候选样本矩阵

从 41 个 passed 样本中挑选 20 个。

### 3.1 Markdown 样本 (8 个)

| candidate_id | original_sample_id | query | expected_doc | query_type | answer_risk | 选择理由 |
|---|---|---|---|---|---|---|
| S5P1-MD-001 | S4M-A-001 | CPU使用率持续超过80%怎么排查 | cpu_high_usage.md | how-to | low | 标准排查流程，fact 清晰 |
| S5P1-MD-002 | S4M-A-002 | 服务不可用时应该先检查什么 | service_unavailable.md | how-to | low | 标准排查步骤 |
| S5P1-MD-003 | S4M-A-004 | 磁盘使用率过高应该怎么处理 | disk_high_usage.md | how-to | low | 标准排查流程 |
| S5P1-MD-004 | S4M-A-006 | KubePodNotReady 告警的含义是什么 | KubePodNotReady.md | fact-lookup | low | 单一 fact |
| S5P1-MD-005 | S4M-A-008 | KubeNodeNotReady 告警出现后怎么排查 | KubeNodeNotReady.md | how-to | medium | 多步骤排查 |
| S5P1-MD-006 | S4M-A-009 | KubePersistentVolumeFillingUp 告警什么时候会触发 | KubePersistentVolumeFillingUp.md | fact-lookup | low | 触发条件 fact |
| S5P1-MD-007 | S4M-A-013 | 中车长客数字化转型有哪些成果 | 数字化转型成果.md | fact-lookup | medium | 多 fact 组合 |
| S5P1-MD-008 | S4M-A-014 | superbiz oncall 手册是做什么的 | superbiz_oncall_handbook.md | fact-lookup | low | 文档用途说明 |

### 3.2 PDF 样本 (12 个)

| candidate_id | original_sample_id | query | expected_doc | query_type | answer_risk | 选择理由 |
|---|---|---|---|---|---|---|
| S5P1-PDF-001 | S4M-B-002 | PagerDuty 文档的主要内容是什么 | pagerduty_incident_response.pdf | fact-lookup | low | 文档概述 |
| S5P1-PDF-002 | S4M-B-003 | Unreliability Budgets 的定义是什么 | unreliability_budgets.pdf | fact-lookup | medium | 术语定义，易混淆 |
| S5P1-PDF-003 | S4M-B-004 | Capacity Planning 文档讲了哪些内容 | capacity_planning.pdf | fact-lookup | low | 文档概述 |
| S5P1-PDF-004 | S4M-B-005 | Scoutflo SRE Playbooks 支持哪些平台 | scoutflo_sre_playbooks.pdf | fact-lookup | low | 平台列表 |
| S5P1-PDF-005 | S4M-B-007 | Systems Performance 书中 CPU 分析工具有哪些 | systems_performance.pdf | fact-lookup | medium | 列表类，需 table |
| S5P1-PDF-006 | S4M-B-010 | 线上故障处理工艺版的安全注意事项是什么 | 线上故障处理_工艺版.pdf | fact-lookup | high | 安全类，不能漏 |
| S5P1-PDF-007 | S4M-C-001 | PagerDuty training 内容在第几页 | pagerduty_incident_response.pdf | citation-heavy | low | Page 引用 |
| S5P1-PDF-008 | S4M-C-002 | Capacity Planning theoretical minimum 在哪一页 | capacity_planning.pdf | citation-heavy | low | Page 引用 |
| S5P1-PDF-009 | S4M-C-004 | Scoutflo 文档中 Kubernetes 章节在哪 | scoutflo_sre_playbooks.pdf | citation-heavy | low | Section 引用 |
| S5P1-PDF-010 | S4M-C-005 | Systems Performance CPU 工具表格在第几页 | systems_performance.pdf | citation-heavy | medium | Table + page |
| S5P1-PDF-011 | S4M-D-002 | Scoutflo 表格中 KubeNodeNotReady 的 playbook 是什么 | scoutflo_sre_playbooks.pdf | table-heavy | medium | Table 内容提取；原 KubePodNotReady 候选缺 source support，已修正 |
| S5P1-PDF-012 | S4M-D-003 | Systems Performance CPU 分析工具表格有哪些内容 | systems_performance.pdf | table-heavy | medium | Table 内容提取 |

---

### 3.3 人工 Review 结论

2026-06-11 已按 expected doc 原文和 PDF artifacts 完成 20 条样本的 Answer 层字段补充：

| 指标 | 结果 |
|---|---:|
| 总样本数 | 20 |
| Markdown 样本 | 8 |
| PDF 样本 | 12 |
| `answer_risk_type=low` | 12 |
| `answer_risk_type=medium` | 7 |
| `answer_risk_type=high` | 1 |
| RAGAS 参与 ground truth 生成 | 0 |
| Answer baseline 已运行 | 是 |
| Answer baseline 通过 | 否，2/20 passed |
| dense-only retrieval doc-hit precheck | 20/20 |
| source_ref / scope / citation precheck | clean |

正式文件：

```text
evals/knowledge_base/evalsets/department_rag_answer_pilot_20q.jsonl
```

Review 期间发现 1 个候选题 source support 不成立：

```text
原候选：Scoutflo 表格中 KubePodNotReady 的 playbook 是什么
问题：当前 Scoutflo PDF table t00002 没有 KubePodNotReady 行
处理：正式 JSONL 改为“Scoutflo 表格中 KubeNodeNotReady 的 playbook 是什么”
证据：table t00002/page 29 存在 KubeNodeNotReady -> 02-Nodes/KubeNodeNotReady-node.md
```

S5-P2 已运行 Answer baseline。结果为 `20` 条全部完成生成，`not_ready=0`，`passed=2`，`failed=18`；失败分布为 `context_missing_facts=16`、`answer_missing_facts=2`。安全/引用硬边界保持干净：`citation_required_but_missing=0`、`unsupported_claim_count=0`、`permission_leak_count=0`、`source_ref_unresolvable_count=0`。本轮不启用 RAGAS / LLM-as-judge，不修改 retrieval mode、rerank 或 Query Rewrite 默认配置。

注意：该 JSONL 是 Answer 层输入，不是旧 `run_department_rag_eval.py` 的 retrieval evalset；旧 runner 仍要求 `expected_answer_keywords`，后续应使用专门的 Answer Baseline Runner 或显式兼容层读取本文件。

---

## 4. Answer 层字段模板

对每个样本，补充以下字段：

### 4.1 通用字段（继承自 retrieval 层）

已有字段保持不变：
- `sample_id` → 改为 `S5P1-MD-xxx` / `S5P1-PDF-xxx`
- `layer` → 改为 `answer`
- `query`
- `allowed_kb_ids`
- `expected_doc_ids`
- `retrieval_mode` → 固定 `dense_only`
- `top_k` → 固定 3

### 4.2 Answer 层新增字段

| 字段 | 类型 | 填写指南 | 示例 |
|---|---|---|---|
| `reference_answer` | string | 人工阅读 expected doc，写 1-3 句参考答案 | "CPU使用率过高时，应先查看 top 命令确认占用进程，再检查是否有异常任务。" |
| `must_include_facts` | list[string] | 从 reference_answer 提取 2-4 个关键事实点 | `["先查看 top 命令", "确认占用进程", "检查异常任务"]` |
| `must_not_include_claims` | list[string] | 列出容易编造的内容 | `["具体的 CPU 阈值（如果文档未提及）", "其他部门的处理流程"]` |
| `required_citations` | list[dict] | 必须引用的文档/section | `[{"doc_id": "doc_xxx", "source_file": "cpu_high_usage.md", "expected_in_answer": "cpu_high_usage.md"}]` |
| `answer_risk_type` | string | `low` / `medium` / `high` | `low` (简单 fact) / `medium` (多 fact) / `high` (易编造) |
| `context_policy` | string | 固定 `retrieved_context_only` | - |
| `judge_policy` | string | 固定 `deterministic_only`（第一版不用 LLM-as-judge） | - |

### 4.3 字段填写示例

**S5P1-MD-001: CPU使用率持续超过80%怎么排查**

```json
{
  "sample_id": "S5P1-MD-001",
  "layer": "answer",
  "query": "CPU使用率持续超过80%怎么排查",
  "allowed_kb_ids": ["process_digital_dept"],
  "expected_doc_ids": ["doc_3b15644b-9560-5846-ad86-832321f6c4aa"],
  "retrieval_mode": "dense_only",
  "top_k": 3,
  
  "reference_answer": "CPU使用率过高时，应先使用 top 命令查看占用进程，检查是否有异常占用。然后分析是否为业务高峰或程序 bug 导致，必要时优化代码或增加资源。",
  
  "must_include_facts": [
    "使用 top 命令查看占用进程",
    "检查是否有异常占用",
    "分析原因（业务高峰或程序bug）"
  ],
  
  "must_not_include_claims": [
    "具体的 CPU 使用率阈值（如 85%）如果文档未明确提及",
    "其他部门的排查流程",
    "未在文档中出现的工具名"
  ],
  
  "required_citations": [{
    "doc_id": "doc_3b15644b-9560-5846-ad86-832321f6c4aa",
    "source_file": "cpu_high_usage.md",
    "expected_in_answer": "cpu_high_usage.md"
  }],
  
  "answer_risk_type": "low",
  "context_policy": "retrieved_context_only",
  "judge_policy": "deterministic_only",
  "human_review_status": "pending"
}
```

---

## 5. 人工 Review Checklist

对每个样本，必须验证：

### 5.1 Retrieval 层稳定性

- [ ] Expected doc 在 dense-only baseline 中已命中 top-3
- [ ] Source_ref 可回查
- [ ] 没有 wrong_scope / citation_unresolvable

### 5.2 Reference Answer 质量

- [ ] 阅读 expected doc 原文
- [ ] Reference answer 基于文档内容，不是 LLM 编造
- [ ] 1-3 句话，简洁、准确、完整
- [ ] 覆盖 query 问的核心问题

### 5.3 Must Include Facts 准确性

- [ ] 从 reference answer 提取
- [ ] 每个 fact 是独立可验证的
- [ ] 2-4 个 fact，不过多不过少
- [ ] 允许 LLM 改写措辞，但语义必须一致

### 5.4 Must Not Include Claims 合理性

- [ ] 列出容易编造的内容
- [ ] 列出易混淆的内容（其他文档/部门）
- [ ] 列出文档未明确提及的细节

### 5.5 Required Citations 正确性

- [ ] Doc_id / source_file 正确
- [ ] Expected_in_answer 是合理的引用格式
- [ ] 对 PDF 样本，包含 page / section / table_id

### 5.6 Answer Risk Type 合理性

| Risk Type | 判定标准 |
|---|---|
| `low` | 单一 fact，文档明确，不易编造 |
| `medium` | 多 fact 组合，或需要跨 chunk，或有一定推理 |
| `high` | 易编造，或易混淆，或安全关键 |

---

## 6. Review 后创建正式 JSONL

人工 review 通过后：

```bash
# 1. 将 20 个样本从候选矩阵转为正式 JSONL
# 2. 保存为：
evals/knowledge_base/evalsets/department_rag_answer_pilot_20q.jsonl

# 3. 验证格式
uv run python -c "
import json
samples = [json.loads(line) for line in open('evals/knowledge_base/evalsets/department_rag_answer_pilot_20q.jsonl')]
print(f'Total: {len(samples)}')
assert all('reference_answer' in s for s in samples)
assert all('must_include_facts' in s for s in samples)
print('✅ Format valid')
"

# 4. 然后才实现 Answer Baseline Runner
```

---

## 7. 不做的事

### 7.1 已创建 JSONL，baseline 已作为 S5-P2 跑完

- ✅ 已创建 `department_rag_answer_pilot_20q.jsonl`（人工 review 通过后）
- ✅ 已运行 Answer Baseline Runner：`evals/knowledge_base/reports/department_rag_answer_pilot_20q_baseline_20260611.json`
- ❌ 当前不把 2/20 结果升级为通过结论；下一步先做 S5-P3 失败分流

### 7.2 不使用 RAGAS

- ❌ 不用 RAGAS 生成 query / reference_answer
- ✅ 第一版完全人工审核，定标准
- ✅ RAGAS 留给第二轮扩充（S5-P3）

### 7.3 不调 Retrieval

- ❌ 不调 retrieval_mode / query_rewrite / rerank
- ✅ 固定 dense_only / off / false（与 S4 baseline 一致）

---

## 8. 状态锁定

```text
s5_p1_status = formal_jsonl_created_after_human_review
s5_p1_sample_count = 20
s5_p1_markdown_samples = 8
s5_p1_pdf_samples = 12
s5_p1_ragas_used = no
s5_p1_formal_jsonl_created = yes
s5_p1_answer_baseline_run = no
s5_p1_human_review_complete = yes
s5_p1_next = implement_or_run_answer_baseline_runner
```

---

## 9. 给小白解释

**为什么不直接用 RAGAS？**

RAGAS 像是"机器出题"，虽然快，但质量不稳定。第一版答案评测要"定标准"，必须用高质量的人工审核样本。

等第一版跑通了，证明标准可行，再用 RAGAS "批量出题"扩充到 50 题。

**现在要做什么？**

从 50 道检索题里，挑 20 道检索已经通过的，补上"参考答案"、"必须包含的事实"、"不能编造的内容"、"必须引用的文档"。

这 20 题都要人工审核，确保每题的标准答案是对的。

**审核通过后做什么？**

保存成正式测试集，然后让 LLM 生成答案，检查：
- 有没有漏答（缺关键事实）
- 有没有编造（加了文档没有的内容）
- 有没有引用错（citation 查不回去）

**什么时候用 RAGAS？**

第一版 20 题跑通，证明标准可行，再用 RAGAS 自动生成 30-40 题，扩充到 50 题。
