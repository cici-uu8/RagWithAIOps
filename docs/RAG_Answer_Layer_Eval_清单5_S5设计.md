# RAG Answer Layer Eval 清单 5 S5 设计

日期：2026-06-11

状态：`s5_closed_answer_layer_pilot_baseline_65_percent_with_residual_observations`

前置清单：`docs/RAG_QueryRewrite_清单4_S4_Closeout.md`

---

## 0. 一句话目标

从 mixed 50q 挑 20-30 题做 answer eval pilot，检查 LLM 基于检索上下文的回答质量（忠实、相关、完整、无编造），用硬门禁（citation / claim / permission）+ LLM-as-judge 观察指标。

---

## 1. 为什么需要 S5

### 1.1 Retrieval 层 Passed ≠ Answer 层 Passed

**S4 只检查了 retrieval 层**：
- Mixed 50q baseline: 41/50 (82%) retrieval passed
- 只验证 expected doc 是否命中 top-3
- 只验证 source_ref 是否可回查
- 只验证 scope / citation 是否越界

**未检查 answer 层**：
- ❌ LLM 是否忠实使用检索上下文
- ❌ 回答是否遗漏关键事实
- ❌ 回答是否编造不存在的内容
- ❌ Citation 是否正确格式化并可追溯

### 1.2 三层评测体系的第二层

根据 S4-P2.1 三层评测体系总规范：

```text
retrieval (S4)  → 检索、排序、chunk、source_ref、scope
answer (S5)     → 基于检索上下文生成的回答质量
agent_behavior  → 工具调用、多步计划、审计、权限、AIOps 证据
```

S4 已完成 retrieval 层，现在进入 answer 层。

---

## 2. S5 输入

### 2.1 从 S4 继承

| 产物 | 说明 |
|---|---|
| Mixed 50q evalset | 50 个 retrieval 层样本 |
| Dense-only baseline | 41/50 retrieval passed |
| 18-doc indexed corpus | 12 Markdown + 6 PDF |
| 三层评测体系总规范 | Answer 层字段和门禁定义 |

### 2.2 S5 新增需求

**从 50q 中挑选 20-30 题**，优先选择：
- ✅ Retrieval passed (expected doc 已命中)
- ✅ 覆盖多种 query 类型（how-to / what-is / troubleshooting）
- ✅ 覆盖 Markdown + PDF
- ✅ 覆盖 page/table/citation 样本
- ❌ 不优先选 retrieval failed 的题（先修 retrieval）

---

## 3. Answer 层最小字段

基于 S4-P2.1 三层总规范 §4.3，每个 answer 样本必须包含：

### 3.1 通用字段（继承自 retrieval 层）

| 字段 | 说明 |
|---|---|
| `sample_id` | 唯一 ID |
| `layer` | `answer` |
| `query` | 用户问题 |
| `allowed_kb_ids` | 权限 scope |
| `expected_doc_ids` | Retrieval 层验证用 |

### 3.2 Answer 层新增字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `reference_answer` | string | 是 | 人工审过的参考答案，不要求唯一措辞 |
| `must_include_facts` | list[string] | 是 | 必须出现的事实点（关键信息） |
| `must_not_include_claims` | list[string] | 是 | 不得编造或泄露的内容 |
| `required_citations` | list[dict] | 是 | 必须能追溯的 source_ref |
| `context_policy` | string | 是 | `retrieved_context_only` (默认) |
| `judge_policy` | string | 否 | `deterministic_only` / `ragas_shadow` / `llm_judge_shadow` |

### 3.3 字段设计原则

**`reference_answer`**：
- 人工写的参考答案，用于 LLM-as-judge 对比
- 不要求 LLM 回答与参考答案逐字相同
- 允许措辞差异，只要覆盖关键事实

**`must_include_facts`**：
- 必须出现的事实点，用于硬门禁
- 示例：`["CPU throttling 不一定需要增加 limit", "应检查 requests 是否合理"]`
- 判定：LLM 回答必须包含这些事实（允许改写，但语义必须一致）

**`must_not_include_claims`**：
- 不得编造的内容，用于硬门禁
- 示例：`["其他部门的 runbook", "未在 context 中出现的工具", "编造的页码"]`
- 判定：LLM 回答不得出现这些内容

**`required_citations`**：
- 必须能追溯的 source_ref
- 示例：`[{"doc_id": "doc_xxx", "source_file": "CPUThrottlingHigh.md", "section": "Notice"}]`
- 判定：LLM 回答中的 citation 必须能回查到对应文档/页码/section

---

## 4. Answer 层硬门禁

根据 S4-P2.1 三层总规范 §5.2，answer 层硬门禁（必须为 0）：

| 指标 | 规则 | 判定方法 |
|---|---|---|
| `citation_required_but_missing` | 必须为 0 | 检查 `required_citations` 是否都出现在回答中 |
| `unsupported_claim_count` | 必须为 0 | 检查回答是否包含 `must_not_include_claims` 中的内容 |
| `permission_leak_count` | 必须为 0 | 检查回答是否泄露其他部门的信息 |
| `source_ref_unresolvable_count` | 必须为 0 | 检查回答中的 citation 是否可回查 |

**判定规则**：
```text
allow_active = citation_required_but_missing == 0
            AND unsupported_claim_count == 0
            AND permission_leak_count == 0
            AND source_ref_unresolvable_count == 0
            AND retrieval_layer_passed
```

---

## 5. Answer 层观察指标

根据 S4-P2.1 三层总规范 §5.2 和 §6，允许使用 LLM-as-judge，但仅作为**观察指标**，不替代硬门禁。

### 5.1 RAGAS 指标（shadow）

| 指标 | 说明 | 用途 |
|---|---|---|
| `faithfulness` | 回答是否忠实于检索上下文 | 检测编造 / 幻觉 |
| `answer_relevancy` | 回答是否相关于问题 | 检测答非所问 |
| `context_relevancy` | 检索上下文是否相关于问题 | 回溯检查 retrieval 质量 |

### 5.2 LLM-as-Judge 指标（shadow）

| 指标 | 说明 | Judge Prompt 要点 |
|---|---|---|
| `answer_correctness` | 回答是否正确 | 对比 reference_answer，判断语义一致性 |
| `completeness` | 回答是否完整 | 检查是否覆盖 `must_include_facts` |
| `citation_quality` | Citation 格式和可回查性 | 检查 citation 是否清晰、准确 |

### 5.3 使用边界（重要）

**允许**：
- ✅ 用 RAGAS / LLM-as-judge 作为观察指标
- ✅ 以 shadow/report 方式输出
- ✅ 结合人工抽检校准 judge prompt
- ✅ 报告 judge model / prompt version / temperature / sample count

**禁止**：
- ❌ 用 LLM-as-judge 替代 `citation_required_but_missing=0` 硬门禁
- ❌ 用 RAGAS 替代 `unsupported_claim_count=0` 硬门禁
- ❌ 用 judge 的"看起来合理"覆盖权限泄露或编造事实
- ❌ 把 LLM 自动生成的 query / answer 当作 ground truth

---

## 6. S5-P1 Pilot Evalset 设计

### 6.1 样本选择规则

从 mixed 50q 中挑选 20-30 题，按以下规则：

**必选**：
- Retrieval passed (expected doc 已命中 top-3)
- 覆盖 Markdown + PDF
- 覆盖不同 query 类型

**优先级**：
1. **高优先级** (10-15 题)：
   - Simple fact lookup（简单事实查询）
   - How-to / troubleshooting（排查步骤）
   - Markdown 样本，expected doc 在 rank 1

2. **中优先级** (5-10 题)：
   - PDF page/section 引用
   - PDF table 引用
   - 需要多 chunk 组合的问题

3. **低优先级** (0-5 题)：
   - Expression-gap 样本（如果 retrieval passed）
   - 复杂推理 / 多步骤问题

**不选**：
- ❌ Retrieval failed 的题（先修 retrieval）
- ❌ Permission/scope 边界样本（已在 retrieval 层验证）

### 6.2 字段填写指南

**`reference_answer`**：
- 人工阅读 expected doc，写出简洁的参考答案
- 1-3 句话，覆盖核心事实
- 允许引用原文，但要标注 source

**`must_include_facts`**：
- 从 reference_answer 提取关键事实点
- 每个事实点是一个独立的判断
- 示例：`["CPU throttling 是限流", "Impact 是 informative", "可以跳过处理"]`

**`must_not_include_claims`**：
- 列出容易编造的内容
- 示例：`["具体的 CPU 使用率阈值（如果文档未提及）", "其他部门的处理流程", "未在文档中出现的工具名"]`

**`required_citations`**：
- 列出必须引用的文档/页码/section
- 示例：`[{"doc_id": "doc_xxx", "source_file": "CPUThrottlingHigh.md", "expected_in_answer": "CPUThrottlingHigh.md 或 CPU Throttling High"}]`

---

## 7. S5-P2 Answer Baseline Runner

### 7.1 Runner 输入

| 参数 | 说明 |
|---|---|
| `evalset_path` | Answer 层 pilot evalset (20-30q JSONL) |
| `retrieval_mode` | 固定 `dense_only`（与 S4 baseline 一致） |
| `top_k` | 固定 3（与 S4 baseline 一致） |
| `answer_generator` | 真实 LLM answer generator |
| `judge_mode` | `deterministic_only` / `ragas_shadow` / `llm_judge_shadow` |

### 7.2 Runner 流程

```text
1. 加载 answer evalset
2. 对每个样本：
   a. 调用 retrieval_service.retrieve() 获取检索上下文
   b. 调用 answer_generator.generate() 获取 LLM 回答
   c. 硬门禁检查：
      - citation_required_but_missing
      - unsupported_claim_count
      - permission_leak_count
      - source_ref_unresolvable_count
   d. 观察指标（如果启用）：
      - RAGAS faithfulness / answer_relevancy
      - LLM-as-judge answer_correctness / completeness
3. 生成报告 JSON + Markdown
```

### 7.3 硬门禁判定逻辑

**`citation_required_but_missing`**：
```python
for citation in sample["required_citations"]:
    expected_ref = citation["expected_in_answer"]
    if expected_ref not in answer_text:
        citation_required_but_missing += 1
```

**`unsupported_claim_count`**：
```python
for claim in sample["must_not_include_claims"]:
    if claim in answer_text:
        unsupported_claim_count += 1
```

**`permission_leak_count`**：
```python
for forbidden_kb in all_kb_ids - sample["allowed_kb_ids"]:
    if any_reference_to(forbidden_kb, answer_text):
        permission_leak_count += 1
```

---

## 8. S5-P3 失败分流规则

Answer baseline 完成后，对失败样本分流：

| 失败类型 | 判定标准 | 下一步行动 |
|---|---|---|
| `context_missing_facts` | `must_include_facts` 不在检索上下文中 | 回到 chunk/top_k/parser 优化 |
| `answer_missing_facts` | `must_include_facts` 在上下文中，但回答未包含 | 调 answer prompt / policy |
| `answer_fabrication` | 回答包含 `must_not_include_claims` | 调 answer prompt / add grounding |
| `citation_error` | Citation 格式错或不可回查 | 修 citation assembly logic |
| `answer_irrelevant` | 回答答非所问 | 调 answer prompt / query understanding |

**判定优先级**：
1. 先查 `context_missing_facts` → 如果上下文就缺，回到 retrieval
2. 再查 `answer_missing_facts` / `answer_fabrication` → 调 answer
3. 最后查 `citation_error` → 修 citation

---

## 9. S5 不做的事

### 9.1 不调 Retrieval Mode

```text
retrieval_mode = dense_only  # 固定，不变
```

**原因**：
- S4 已证明 dense-only 41/50 (82%) retrieval passed
- S5 focus 是 answer 层，不是 retrieval 层
- 如果 S5 发现上下文缺事实，再回到 retrieval

### 9.2 不调 Query Rewrite / Hybrid / Rerank

```text
rag_query_rewrite_mode = off
rag_default_retrieval_mode = dense_only
rerank_enabled = false
```

**原因**：
- S4 已证明这些增强无正式价值
- S5 不重新验证 retrieval 层决策

### 9.3 不扩 Corpus

**原因**：
- 先在当前 18-doc corpus 上验证 answer 层质量
- 如果 answer 层稳定，再扩 corpus
- 否则会把 answer 问题和新语料噪声混在一起

### 9.4 不做完整 50q Answer Eval

**原因**：
- S5-P1 是 pilot，只做 20-30 题
- 如果 pilot 发现严重 answer 问题，先修
- 修完后再考虑全量 50q answer eval

---

## 10. S5 成功标准

### 10.1 Pilot 通过标准

```text
answer_pilot_passed = hard_gate_passed
                   AND answer_baseline_run_complete
                   AND failure_triage_complete

hard_gate_passed = citation_required_but_missing == 0
                AND unsupported_claim_count == 0
                AND permission_leak_count == 0
                AND source_ref_unresolvable_count == 0
```

### 10.2 进入下一阶段标准

**如果 pilot passed**：
- 扩展到全量 50q answer eval
- 或进入 agent_behavior 层 eval

**如果 pilot 失败**：
- 按失败分流规则修复
- 如果是 `context_missing_facts` → 回到 chunk/parser
- 如果是 `answer_missing_facts` / `answer_fabrication` → 调 prompt
- 如果是 `citation_error` → 修 citation logic

---

## 11. S5 产物清单

### 11.1 设计文档

| 文档 | 状态 |
|---|---|
| `docs/RAG_Answer_Layer_Eval_清单5_S5设计.md` | ✅ 本文档 |

### 11.2 Evalset

| Evalset | 样本数 | 状态 |
|---|---:|---|
| `evals/knowledge_base/evalsets/department_rag_answer_pilot_20q.jsonl` | 20 | ✅ 已创建，人工 review ground truth |

### 11.3 脚本（待实现）

| 脚本 | 用途 | 状态 |
|---|---|---|
| `evals/knowledge_base/run_department_rag_answer_eval.py` | Answer baseline runner | ✅ 已实现 |
| `evals/knowledge_base/answer_eval_helpers.py` | 硬门禁判定 helper | ✅ 已实现 |

### 11.4 报告与收口文档

| 报告 | 类型 | 状态 |
|---|---|---|
| `department_rag_answer_pilot_20q_baseline_20260611.json` | Answer baseline | ✅ 已生成 |
| `department_rag_answer_pilot_20q_baseline_after_s5_p31_repair_20260611.json` | S5-P3.1 修正后 Answer baseline | ✅ 已生成，仍未过线 |
| `docs/RAG_Answer_Layer_清单5_S5-P3_失败分流矩阵.md` | Answer failure triage | ✅ 已生成，S5-P3.1 已修正并保留失败 |
| `docs/RAG_Answer_Layer_清单5_S5-P4_残余失败探针设计.md` | Residual failure probe design | ✅ 已生成 |
| `checklist5_s5_p4_residual_failure_probe_20260611.json` | Residual failure probe report | ✅ 已生成，observation-only，不改默认 |
| `docs/RAG_Answer_Layer_清单5_S5收口结论.md` | S5 closeout | ✅ 已生成，65% baseline，阶段性收口 |

### 11.5 S5-P1 人工 Review 结果

2026-06-11 已完成 S5-P1 Answer Pilot 20q 人工 review，并创建正式 JSONL。该文件包含 8 个 Markdown 样本和 12 个 PDF 样本，字段覆盖 `reference_answer`、`must_include_facts`、`must_not_include_claims`、`required_citations`、`answer_risk_type`、`context_policy` 和 `judge_policy`。

本轮只定 Answer 层 ground truth，不运行 Answer baseline，不调用 RAGAS 或 LLM-as-judge 生成标准答案，不修改 `rag_default_retrieval_mode`、`rag_query_rewrite_mode` 或 `rerank_enabled`。轻量 dense-only retrieval doc-hit precheck 已确认 20/20 expected doc hit，source_ref/scope/citation clean；该 precheck 不是 Answer baseline，只证明 pilot 输入没有混入明显 retrieval miss。

### 11.6 S5-P2 Answer Baseline Runner 结果

2026-06-11 已实现并运行 S5-P2 Answer Baseline Runner：

| 产物 | 路径 |
|---|---|
| Runner | `evals/knowledge_base/run_department_rag_answer_eval.py` |
| Helper | `evals/knowledge_base/answer_eval_helpers.py` |
| 测试 | `tests/test_department_rag_answer_eval.py` |
| JSON 报告 | `evals/knowledge_base/reports/department_rag_answer_pilot_20q_baseline_20260611.json` |
| Markdown 报告 | `evals/knowledge_base/reports/department_rag_answer_pilot_20q_baseline_20260611.md` |

Runner 固定使用 `dense_only` / `top_k=3` / `retrieved_context_only` / `deterministic_only`，调用真实 DashScope `qwen-max` context answer generator 生成答案；不使用 RAGAS，不使用 LLM-as-judge，不修改 `rag_default_retrieval_mode`、`rag_query_rewrite_mode` 或 `rerank_enabled`。

最终 baseline summary：

```text
total = 20
passed = 2
failed = 18
not_ready = 0
pass_rate = 0.10
failure_categories = {
  "context_missing_facts": 16,
  "answer_missing_facts": 2,
  "passed": 2
}
missing_required_fact_count = 52
context_missing_fact_count = 41
answer_missing_fact_count = 11
citation_required_but_missing = 0
unsupported_claim_count = 0
permission_leak_count = 0
source_ref_unresolvable_count = 0
retrieval_layer_failed_count = 0
```

结论：`answer_pilot_failed`。这不是 runner 阻塞：真实 answer generation 已完成，`not_ready=0`；安全/引用硬边界也没有退化。主要失败集中在检索上下文没有覆盖人工 required facts，少量为上下文中有事实但回答未包含。因此下一步应进入 S5-P3 失败分流：先复核 16 个 `context_missing_facts` 是否是 top-k/chunk/context-policy/eval fact 粒度问题，再处理 2 个 `answer_missing_facts` 的 prompt/policy 问题；暂不扩 RAGAS，也不进入 agent_behavior 层验收。

### 11.7 S5-P3 Answer 失败分流矩阵

2026-06-11 已创建 review-only 分流文档：`docs/RAG_Answer_Layer_清单5_S5-P3_失败分流矩阵.md`。

本轮没有重新生成答案，没有调用 RAGAS，没有使用 LLM-as-judge，也没有修改 `rag_default_retrieval_mode`、`rag_query_rewrite_mode` 或 `rerank_enabled`。只读复核使用现有 Answer Pilot 20q evalset 和 S5-P2 baseline report，并对 18 个失败样本重新查看 dense-only top-3/top-10 context。

分流结果：

```text
eval_fact_granularity_review = 13
answer_prompt_policy_candidate = 2
top_k_candidate = 1
mixed_context_gap = 1
mixed_context_and_answer_gap = 1
```

结论：S5-P2 的 `answer_pilot_failed` 仍成立，但 S5-P3 不支持立即上 RAGAS、进入 agent_behavior 层、切 hybrid、开 rerank、开 query rewrite 或全局调 prompt。多数失败需要先人工复核 `must_include_facts` 粒度、source_support/chunk/table 定位和 deterministic 语义匹配边界；当前只有 `S5P1-MD-002` 是明确 top-k 候选，只有 `S5P1-MD-001` / `S5P1-MD-007` 是明确 answer-prompt/policy 候选。

下一步：人工 review S5-P3 矩阵；若确认 eval fact/source_support 过严，先修 evalset ground truth 并重跑 Answer baseline。只有复核后仍出现稳定 top-k/context-policy 或 prompt/policy 失败，才进入对应 observation-only probe。

### 11.8 S5-P3.1 Eval 标准修正结果

2026-06-11 已完成 S5-P3.1：修正 `department_rag_answer_pilot_20q.jsonl` 中过细、跨语言语义匹配过严、或不适合作为主问必答点的 `must_include_facts`，并在 `answer_eval_helpers.py` 中支持显式 fact alias（`A||B`）。同时修复 deterministic hard gate 的一个误报：`must_not_include_claims` 中类似“省略隔离许可和 LOTO 安全要求”的整句禁止项不能用中文字符覆盖率做模糊命中，否则会把“答案包含 LOTO 要求”误判成 fabrication。

修正范围保持在评测标准和 deterministic gate：

- 未修改 `query` / `expected_doc_ids` / `allowed_kb_ids`
- 未修改 `retrieval_mode=dense_only` 或 `top_k=3`
- 未修改 answer prompt
- 未修改 `app/config.py` / `.env`
- 未启用 RAGAS / LLM-as-judge
- 未启用 hybrid / rerank / query rewrite

修正后真实 rerun：

```text
report = evals/knowledge_base/reports/department_rag_answer_pilot_20q_baseline_after_s5_p31_repair_20260611.json
total = 20
passed = 13
failed = 7
not_ready = 0
pass_rate = 0.65
failure_categories = {
  "answer_missing_facts": 4,
  "context_missing_facts": 3,
  "passed": 13
}
missing_required_fact_count = 15
context_missing_fact_count = 10
answer_missing_fact_count = 5
citation_required_but_missing = 0
unsupported_claim_count = 0
permission_leak_count = 0
source_ref_unresolvable_count = 0
retrieval_layer_failed_count = 0
```

结论：`s5_p31_eval_standard_repaired_but_answer_pilot_still_failed`。S5-P3.1 已把一批 eval 标准假失败修掉，但最终真实 baseline 仍为 13/20，低于 14/20 的通过线，因此不能进入 Answer 50q、RAGAS 扩充或 agent_behavior 层。

保留的失败分流：

- `answer_prompt_policy_candidate`: `S5P1-MD-001`, `S5P1-MD-007`
- `top_k_candidate`: `S5P1-MD-002`
- `context/source-support_candidate`: `S5P1-PDF-004`, `S5P1-PDF-009`
- `answer_missing_facts` 观察项：`S5P1-PDF-001`, `S5P1-PDF-002` 在真实生成中仍有漏事实波动，暂不作为全局 prompt 调整依据

下一步应进入 S5-P4 observation-only probes：先对 `S5P1-MD-001` / `S5P1-MD-007` 做 answer prompt/policy 小样本 shadow；对 `S5P1-MD-002` 做 `top_k=5` 或 doc-level context shadow；对 Scoutflo 两题复核 source-support 和 PDF chunk 定位。所有 probe 都不改变默认配置。

### 11.9 S5-P4 残余失败探针设计

2026-06-11 已创建 S5-P4 observation-only 设计文档：`docs/RAG_Answer_Layer_清单5_S5-P4_残余失败探针设计.md`。

本阶段只定义探针，不执行探针，不改系统：

- Prompt/policy shadow：`S5P1-MD-001`, `S5P1-MD-007`
- Top-k / doc-level context shadow：`S5P1-MD-002`
- Scoutflo PDF chunk/source-support probe：`S5P1-PDF-004`, `S5P1-PDF-009`
- Generation variance observation：`S5P1-PDF-001`, `S5P1-PDF-002`

设计文档明确记录：

- 使用 S5-P3.1 repaired baseline 的 7 个残余失败样本作为输入
- probe 结果只能作为 observation，不能直接修改生产默认
- `rag_default_retrieval_mode=dense_only`、`rag_query_rewrite_mode=off`、`rerank_enabled=false` 继续保持
- 不进入 Answer 50q、RAGAS 扩充或 agent_behavior 层，除非后续正式 20q rerun 达到 `passed >= 14/20` 且 hard gate clean

### 11.10 S5-P4 残余失败探针运行结果

2026-06-11 已实现并运行 S5-P4 observation-only probe：

| 产物 | 路径 |
|---|---|
| Probe runner | `evals/knowledge_base/checklist5_s5_p4_residual_failure_probe.py` |
| 测试 | `tests/test_checklist5_s5_p4_residual_failure_probe.py` |
| JSON 报告 | `evals/knowledge_base/reports/checklist5_s5_p4_residual_failure_probe_20260611.json` |
| Markdown 报告 | `evals/knowledge_base/reports/checklist5_s5_p4_residual_failure_probe_20260611.md` |

运行边界：

- 真实调用 dense retrieval / Milvus / DashScope embedding
- 对 prompt shadow、context shadow 和 generation variance 调用真实 `qwen-max`
- 使用 deterministic hard gate 判分
- 未使用 RAGAS / LLM-as-judge
- 未修改正式 answer prompt、默认 `top_k=3`、`rag_default_retrieval_mode`、`rag_query_rewrite_mode`、`rerank_enabled`、`app/config.py` 或 `.env`

结果摘要：

```text
baseline = 13/20
probe_status = observation_only
prompt_enhanced_passed = 0/2
top_k_5_passed = false
doc_level_passed = false
pdf_source_support_verdicts = {
  "chunk_supported_but_not_retrieved_top10": 2
}
generation_variance_verdicts = {
  "unstable_generation": 2
}
eligible_for_answer_50q = false
```

逐项结论：

- Prompt/policy shadow：`S5P1-MD-001` 和 `S5P1-MD-007` 均未修复，不能据此全局调 prompt。
- Top-k/context shadow：`S5P1-MD-002` 在 `top_k=5` 下 context 覆盖 required facts，但答案仍漏事实；doc-level context 也未修复。不能据此改默认 `top_k`。
- Scoutflo PDF source-support：两个样本的 artifacts/chunks 中有事实支撑，但 top-10 context 仍未覆盖全部 required facts，属于 PDF retrieval/chunk targeting observation，不是 eval/source_support 缺失，也不足以全局重构 PDF parser。
- Generation variance：`S5P1-PDF-001` 和 `S5P1-PDF-002` 都是 `2/5` 通过，属于不稳定生成观察，不能直接算通过，也不能单独作为全局 prompt 改动依据。

结论：`s5_p4_observation_probe_run_complete_no_default_change`。S5-P4 没有产生足以进入 Answer 50q、RAGAS 扩充、agent_behavior 层、全局 prompt 改动、默认 top_k 改动、hybrid/rerank/query rewrite 默认切换的证据。

下一步建议：S5 可以阶段性收口为 `answer_layer_pilot_baseline_65_percent_with_residual_observations`，或另开更小的后续工作：只针对 `S5P1-MD-002` 做 answer completeness/prompt+top_k 组合 shadow，或针对 Scoutflo PDF 做局部 chunk targeting probe。二者都不能直接改生产默认。

### 11.11 S5 阶段性收口

2026-06-11 已创建 S5 closeout 文档：

`docs/RAG_Answer_Layer_清单5_S5收口结论.md`

收口状态：

`s5_closed_answer_layer_pilot_baseline_65_percent_with_residual_observations`

最终决策：

- 接受 `13/20 (65%)` 作为当前 answer-layer pilot baseline 和限制记录，但不把 65% 改成通过线。
- 硬门禁保持干净：citation missing、unsupported claim、permission leak、source_ref unresolvable、retrieval-layer failure 都是 0。
- S5-P4 没有发现统一修复方向：prompt shadow `0/2`，`top_k=5` 仅改善单题 context 但未修复 answer gate，Scoutflo PDF 是局部 chunk targeting observation，generation variance 不稳定。
- 不扩 Answer 50q，不上 RAGAS，不进入 agent_behavior 层，不全局改 prompt/top_k，也不切 hybrid、rerank、query rewrite。
- 下一阶段转向 Corpus 扩充第二轮；等 corpus 扩到 30-50 个 indexed 文档并重跑 retrieval baseline 后，再决定是否重启 Answer 50q / prompt shadow / agent_behavior。

---

## 12. 给小白解释

**S4 做了什么**：
- 考"能不能找对文档"，41/50 对了

**S5 要做什么**：
- 考"找对了文档，能不能生成好答案"
- 检查答案是不是忠实、完整、没编造、引用对

**怎么考**：
- 从 50 题里挑 20-30 题
- 人工写参考答案和必须包含的事实
- 让 LLM 生成答案，检查有没有漏答、编造、引用错

**硬门禁（必须通过）**：
- Citation 不能缺
- 不能编造文档里没有的东西
- 不能泄露其他部门的信息
- Citation 必须能查回原文

**观察指标（可以看，但不替代硬门禁）**：
- RAGAS faithfulness / answer_relevancy
- LLM-as-judge 判断答案是否正确、完整

**如果考不过**：
- 如果是上下文就缺事实 → 回去修检索/切分
- 如果是上下文有但答案漏了 → 调 prompt
- 如果是编造 → 加 grounding 约束
- 如果是引用错 → 修引用逻辑

---

## 13. Handoff 规则

**从 S4 到 S5**：
- ✅ Mixed 50q evalset
- ✅ Dense-only baseline (41/50 retrieval passed)
- ✅ 18-doc indexed corpus
- ✅ 三层评测体系总规范

**从 S5 到后续**：
- 如果 answer pilot passed → 全量 50q answer eval 或 agent_behavior 层
- 如果 `context_missing_facts` → 回到 chunk/parser 优化
- 如果 `answer_missing_facts` / `answer_fabrication` → prompt 优化
- 如果 `citation_error` → citation logic 修复
