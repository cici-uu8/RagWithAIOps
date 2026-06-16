# RAG Answer Layer 清单5 S5-P4 残余失败探针设计

状态：`s5_p4_observation_probe_run_complete_no_default_change`

日期：2026-06-11

## 1. 范围

本文件定义 S5-P3.1 后 7 个残余失败样本的 observation-only 探针。它不是新 evalset，不是生产 prompt 变更方案，也不是 top_k、retrieval mode、rerank 或 query rewrite 的默认切换依据。

输入：

- Evalset: `evals/knowledge_base/evalsets/department_rag_answer_pilot_20q.jsonl`
- Baseline report: `evals/knowledge_base/reports/department_rag_answer_pilot_20q_baseline_after_s5_p31_repair_20260611.json`
- S5-P3 triage: `docs/RAG_Answer_Layer_清单5_S5-P3_失败分流矩阵.md`

边界：

- 不修改 `app/config.py` 或 `.env`
- 不修改 `rag_default_retrieval_mode=dense_only`
- 不修改 `rag_query_rewrite_mode=off`
- 不修改 `rerank_enabled=false`
- 不修改正式 answer prompt
- 不修改默认 `top_k=3`
- 不创建 Answer 50q
- 不创建 RAGAS / LLM-as-judge 门禁
- 不进入 agent_behavior 层验收

## 2. S5-P3.1 基线事实

| 指标 | 数值 |
|---|---:|
| total | 20 |
| passed | 13 |
| failed | 7 |
| pass_rate | 0.65 |
| threshold | 0.70 |
| gap_to_threshold | 1 sample |
| not_ready | 0 |
| answer_missing_facts | 4 |
| context_missing_facts | 3 |
| citation_required_but_missing | 0 |
| unsupported_claim_count | 0 |
| permission_leak_count | 0 |
| source_ref_unresolvable_count | 0 |
| retrieval_layer_failed_count | 0 |

结论：S5-P3.1 修正有效，但 Answer Pilot 仍未过线。剩余失败不是安全、越权、引用不可回查或检索层失败；下一步只能做小样本 observation-only 探针，不能直接调全局能力。

## 3. 残余失败样本

| sample_id | failure_category | query | 主要假设 | S5-P4 探针 |
|---|---|---|---|---|
| `S5P1-MD-001` | `answer_missing_facts` | CPU使用率持续超过80%怎么排查 | context 有事实，但答案漏写关键排查事实 | Prompt/policy shadow |
| `S5P1-MD-002` | `context_missing_facts` | 服务不可用时应该先检查什么 | top-3 context 不足，排查步骤可能在 top-5 或 doc-level context | Top-k / doc-level context shadow |
| `S5P1-MD-007` | `answer_missing_facts` | 中车长客数字化转型有哪些成果 | context 有事实，但答案漏写成果点 | Prompt/policy shadow |
| `S5P1-PDF-001` | `answer_missing_facts` | PagerDuty 文档的主要内容是什么 | 真实生成漏事实，可能是短 PDF 概览题的输出波动 | Generation variance observation |
| `S5P1-PDF-002` | `answer_missing_facts` | Unreliability Budgets 的定义是什么 | 真实生成漏事实，可能是英文术语定义题的输出波动 | Generation variance observation |
| `S5P1-PDF-004` | `context_missing_facts` | Scoutflo SRE Playbooks 支持哪些平台 | Scoutflo overview chunk/source_support 定位不稳 | PDF chunk/source-support probe |
| `S5P1-PDF-009` | `context_missing_facts` | Scoutflo 文档中 Kubernetes 章节在哪 | Scoutflo folder structure chunk/source_support 定位不稳 | PDF chunk/source-support probe |

## 4. 探针 1：Answer Prompt/Policy Shadow

目标样本：

- `S5P1-MD-001`
- `S5P1-MD-007`

假设：当前 answer prompt 没有足够约束模型覆盖 context 中的所有关键事实，所以在 context 已包含 required facts 时仍出现 `answer_missing_facts`。

测试方法：

1. 只对目标样本构造临时增强 prompt。
2. 使用同一 retrieval 输出、同一 Answer hard gate、同一 JSONL ground truth。
3. 对比 current prompt 与 enhanced prompt 的通过情况。
4. 不写入生产 prompt，不修改配置。

建议的增强 prompt 方向：

```text
请只基于给定检索上下文回答。
必须覆盖与问题直接相关的关键事实点；如果上下文中列出步骤、指标、对象或结果，不要只做笼统总结。
不要编造上下文中没有的信息。
回答后保留必要引用。
```

判定：

| 结果 | 解释 | 下一步 |
|---|---|---|
| 2/2 repaired | prompt/policy 假设成立 | 进入正式 prompt change proposal，但仍需回归 20q |
| 1/2 repaired | 有弱信号 | 保持 observation-only，扩大到更多 answer_missing 样本后再决定 |
| 0/2 repaired | prompt/policy 假设不成立 | 不调 prompt，回看 context 或 eval facts |

升级门槛：不能只因为 1 个样本修复就全局调 prompt。至少要证明目标样本多数修复，且已通过样本没有明显退化。

## 5. 探针 2：Top-k / Doc-Level Context Shadow

目标样本：

- `S5P1-MD-002`

假设：`service_unavailable.md` 的关键排查步骤没有进入 top-3 context；提高 context 覆盖可能修复该题。

测试方法：

1. 固定 `dense_only`，不切 hybrid、rerank、query rewrite。
2. 比较三种只读 context：
   - current: `top_k=3`
   - shadow A: `top_k=5`
   - shadow B: expected doc-level context 或 section-level context
3. 使用同一 Answer hard gate 检查 required facts 是否进入 context，并在可行时生成 answer 观察是否通过。

判定：

| 结果 | 解释 | 下一步 |
|---|---|---|
| `top_k=5` context 覆盖并 answer 通过 | top-k/context 覆盖假设成立 | 进入 top_k 局部/全局变更评估，但需测 latency 和 20q 回归 |
| doc-level context 通过但 top_k=5 不通过 | context assembly 假设成立 | 设计 doc-level aggregation shadow，不直接改默认 |
| 两者都不通过 | 不是简单 context 数量问题 | 回到 eval/source_support 或 prompt/policy 分析 |

升级门槛：单样本 top_k 受益只能证明“值得继续 probe”，不能直接把默认 `top_k=3` 改成 `top_k=5`。

## 6. 探针 3：Scoutflo PDF Chunk / Source-Support Probe

目标样本：

- `S5P1-PDF-004`
- `S5P1-PDF-009`

假设：Scoutflo PDF 的 overview/folder structure 相关 chunk 或 source_support 不稳定，导致 required facts 没进入 top-3 context。

测试方法：

1. 回查 Scoutflo PDF artifacts：
   - `chunks.json`
   - `cleaned.md`
   - `tables.json`（如涉及 table）
2. 确认 required facts 是否确实存在于已 indexed chunks：
   - `S5P1-PDF-004`: `AWS`, `Kubernetes`, `Sentry`, `414`
   - `S5P1-PDF-009`: `Kubernetes`, `Folder Structure`, `Control-Plane`, `Pods`
3. 对目标 query 做只读 `top_k=3` / `top_k=10` retrieval 观察。
4. 标记失败原因：
   - `source_support_issue`
   - `chunk_not_indexed`
   - `chunk_indexed_but_ranked_low`
   - `eval_fact_too_broad`
   - `retrieval_context_policy_gap`

判定：

| 结果 | 解释 | 下一步 |
|---|---|---|
| fact 不在 artifacts/chunks | eval/source_support 设计问题 | 修 eval ground truth，不改系统 |
| fact 在 chunk，但 top-10 也召回不到 | retrieval/chunking 候选 | 做 PDF chunking/index probe |
| fact 在 top-10 但不在 top-3 | context/ranking 候选 | 进入 top_k/context probe，不切默认 |
| fact 在 top-3 但 answer 漏写 | answer prompt/policy 候选 | 加入 prompt shadow 候选池 |

升级门槛：只有两个 Scoutflo 样本，最多能定位 Scoutflo PDF 局部问题，不能证明全 PDF parser/chunking 需要全局重构。

## 7. 探针 4：Generation Variance Observation

目标样本：

- `S5P1-PDF-001`
- `S5P1-PDF-002`

假设：这两个样本的 failure 可能来自真实 LLM 生成波动，而不是稳定的 context 或 eval 设计问题。

测试方法：

1. 固定同一 retrieval context。
2. 对每个样本重复生成 5 次。
3. 使用同一 deterministic hard gate 判分。
4. 记录每次 answer 是否漏 fact，不使用 LLM-as-judge。

判定：

| 结果 | 解释 | 下一步 |
|---|---|---|
| 5/5 passed 或 4/5 passed | 失败可能是生成波动 | 标记 observation，不作为全局 prompt 改动依据 |
| 2/5 或 3/5 passed | 输出不稳定 | 评估 temperature / prompt policy shadow |
| 0/5 或 1/5 passed | 稳定失败 | 重新分流为 prompt/context/eval 问题 |

边界：波动观察不能单独证明当前 Answer 层通过，也不能替代正式 baseline。

## 8. S5-P4 输出格式

建议后续探针报告使用 JSON + Markdown：

```text
evals/knowledge_base/reports/checklist5_s5_p4_residual_failure_probe_20260611.json
evals/knowledge_base/reports/checklist5_s5_p4_residual_failure_probe_20260611.md
```

建议 JSON summary 字段：

```json
{
  "probe_name": "checklist5_s5_p4_residual_failure_probe",
  "status": "observation_only",
  "baseline_report": "department_rag_answer_pilot_20q_baseline_after_s5_p31_repair_20260611.json",
  "sample_count": 7,
  "prompt_policy_probe": {
    "sample_count": 2,
    "repaired_count": 0
  },
  "top_k_context_probe": {
    "sample_count": 1,
    "top_k_5_context_repaired_count": 0,
    "doc_level_context_repaired_count": 0
  },
  "pdf_chunk_source_support_probe": {
    "sample_count": 2,
    "source_support_issue_count": 0,
    "chunk_indexed_but_ranked_low_count": 0
  },
  "generation_variance_probe": {
    "sample_count": 2,
    "stable_pass_count": 0,
    "unstable_count": 0,
    "stable_fail_count": 0
  },
  "changes_runtime_config": false,
  "changes_default_retrieval_mode": false,
  "changes_query_rewrite_mode": false,
  "changes_rerank_enabled": false,
  "changes_answer_prompt": false,
  "uses_ragas": false,
  "uses_llm_as_judge": false,
  "eligible_for_answer_50q": false
}
```

## 9. 决策规则

S5-P4 结束后按以下规则走：

| 条件 | 决策 |
|---|---|
| prompt/policy shadow 多数修复，且 20q 回归不退化 | 进入正式 prompt change proposal |
| top_k/doc-level context 修复 `S5P1-MD-002`，且 latency/20q 回归可接受 | 进入 context policy 方案评估 |
| Scoutflo 样本被证明是 source_support/eval 问题 | 修 eval/source_support，不改系统 |
| Scoutflo 样本被证明是 chunk/index/ranking 问题 | 进入 PDF chunking/index probe |
| generation variance 明显 | 记录波动，不直接算通过；必要时做 answer stability probe |
| 任何 probe 后正式 20q rerun 达到 `passed >= 14/20` 且 hard gate clean | 才能讨论 Answer 50q / RAGAS shadow 扩充 |
| 正式 20q 仍低于 14/20 | 不进入 Answer 50q，不进入 agent_behavior 层 |

硬边界：

- Observation-only probe 结果不能直接修改生产默认。
- RAGAS / LLM-as-judge 只能作为 Answer 层补充观察，不能替代 deterministic hard gate。
- `rag_default_retrieval_mode`、`rag_query_rewrite_mode`、`rerank_enabled` 继续保持当前默认。

## 10. 给小白解释

现在不是继续改系统，而是做小实验。

20 题考卷已经修过一次，成绩从 2 题对提高到 13 题对，但及格线是 14 题，还差 1 题。剩下 7 题不是同一种问题：有的像答案没写全，有的像给模型看的材料不够，有的像 PDF 切块定位不准，还有的可能只是模型这次发挥不稳。

所以 S5-P4 的做法是逐题验证：

- 改临时 prompt，看答案没写全的 2 题能不能补回来。
- 多给一点 context，看服务不可用那 1 题能不能补回来。
- 检查 Scoutflo PDF 的 chunk/source_support，看是不是材料定位问题。
- 同一 PDF 题多跑几次，看是不是生成波动。

这些都是只读实验。实验结果稳定后，才决定要不要正式改 prompt、context 策略或 eval 标准。

## 11. 实际运行结果

运行时间：2026-06-11

产物：

- Runner: `evals/knowledge_base/checklist5_s5_p4_residual_failure_probe.py`
- JSON: `evals/knowledge_base/reports/checklist5_s5_p4_residual_failure_probe_20260611.json`
- Markdown: `evals/knowledge_base/reports/checklist5_s5_p4_residual_failure_probe_20260611.md`

运行范围：

- 调用真实 dense retrieval / Milvus / DashScope embedding
- 对需要生成答案的 probe 调用真实 `qwen-max`
- 使用 deterministic hard gate 判分
- 不使用 RAGAS / LLM-as-judge
- 不修改正式 prompt、默认 `top_k`、检索模式、rerank、query rewrite 或配置文件

结果：

| 探针 | 结果 | 判定 |
|---|---|---|
| Prompt/policy shadow | `0/2` 通过 | `no_prompt_policy_lift` |
| Top-k=5 shadow | context 覆盖全部 facts，但 answer 仍失败 | 不足以改默认 `top_k` |
| Doc-level shadow | 未修复 | 不支持 doc-level 默认化 |
| Scoutflo PDF source-support | 2 个样本 artifacts 有支撑，但 top-10 context 仍未覆盖全部 facts | PDF retrieval/chunk targeting observation |
| Generation variance | `S5P1-PDF-001=2/5`，`S5P1-PDF-002=2/5` | 生成不稳定，不能直接算通过 |

最终结论：

`s5_p4_observation_probe_run_complete_no_default_change`

S5-P4 没有证明任何全局改动可以安全提升 Answer Pilot 到通过线。不能进入 Answer 50q、RAGAS 扩充、agent_behavior 层，也不能修改 prompt、默认 `top_k`、hybrid、rerank 或 query rewrite。
