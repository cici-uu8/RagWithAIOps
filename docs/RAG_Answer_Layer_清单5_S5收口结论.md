# RAG Answer Layer 清单5 S5 收口结论

日期：2026-06-11

状态：`s5_closed_answer_layer_pilot_baseline_65_percent_with_residual_observations`

结论：S5 Answer Pilot 已完成阶段性验证，但未通过 70% 门槛。当前接受 `13/20 (65%)` 作为 answer-layer pilot baseline 和限制记录，不继续为了 1 个样本做全局调参，也不进入 Answer 50q、RAGAS 扩充或 agent_behavior 层。

---

## 1. 阶段结果

| 阶段 | 动作 | 结果 | 判定 |
|---|---|---:|---|
| S5-P2 | 首次 Answer baseline | `2/20` | baseline 失败，进入分流 |
| S5-P3 | 失败分流矩阵 | 18 个失败分类 | 先修 eval 标准，不调系统 |
| S5-P3.1 | 修正 eval 标准后重跑 | `13/20` | 仍低于 `14/20` 门槛 |
| S5-P4 | 残余失败 observation-only probe | 无统一修复方向 | 不改默认配置 |

S5-P3.1 的正式报告是：

`evals/knowledge_base/reports/department_rag_answer_pilot_20q_baseline_after_s5_p31_repair_20260611.json`

核心数字：

```text
total = 20
passed = 13
failed = 7
pass_rate = 0.65
threshold = 14/20
answer_missing_facts = 4
context_missing_facts = 3
```

---

## 2. 硬门禁结果

安全和引用边界是本阶段最重要的正向结果：

| 硬门禁 | 结果 |
|---|---:|
| `citation_required_but_missing` | 0 |
| `unsupported_claim_count` | 0 |
| `permission_leak_count` | 0 |
| `source_ref_unresolvable_count` | 0 |
| `retrieval_layer_failed_count` | 0 |

解释：S5 没有证明 Answer 层已经足够稳定，但已经证明 answer eval runner、citation/source_ref/permission/unsupported-claim hard gate 可以工作，且本轮没有发现安全边界退化。

---

## 3. S5-P4 探针结论

S5-P4 的报告是：

`evals/knowledge_base/reports/checklist5_s5_p4_residual_failure_probe_20260611.json`

探针结果：

| 探针 | 样本 | 结果 | 决策 |
|---|---:|---|---|
| Prompt/policy shadow | 2 | `0/2` 修复 | 不全局改 prompt |
| Top-k / doc-level context | 1 | `top_k=5` 覆盖 context，但 answer 仍失败 | 不改默认 `top_k` |
| Scoutflo PDF chunk/source-support | 2 | artifacts 有支撑，但 top-10 context 仍不全 | 仅保留 PDF 局部观察 |
| Generation variance | 2 | 两题均 `2/5` 通过 | 不把波动样本算通过 |

S5-P4 是 observation-only。它调用了真实 dense retrieval / Milvus / DashScope embedding 和部分 `qwen-max` 生成，但没有使用 RAGAS / LLM-as-judge，也没有修改 runtime config、prompt、默认 `top_k`、retrieval mode、rerank 或 query rewrite。

---

## 4. 为什么现在收口

本阶段不继续优化，是因为剩余失败没有统一修复方向：

- 2 个样本疑似 prompt/policy，但 prompt shadow `0/2` 修复。
- 1 个样本 `top_k=5` 让 context 覆盖变好，但最终 answer 仍失败。
- 2 个 Scoutflo PDF 样本更像局部 chunk targeting / retrieval observation。
- 2 个 PDF 样本存在生成波动，但不是稳定通过证据。

继续逐题修很容易过拟合这 20 题，并且可能影响已经通过的 13 题。当前更有价值的下一步不是把 S5 硬推到 70%，而是在更真实的 corpus 上重新观察 retrieval 和 answer failure shape。

---

## 5. 明确不做

基于当前证据，以下动作都不做：

- 不降低 S5 通过线，不把 65% 改成通过标准。
- 不扩 Answer 50q。
- 不使用 RAGAS 扩充正式 evalset。
- 不把 LLM-as-judge 作为 hard gate。
- 不进入 agent_behavior 层验收。
- 不全局修改 answer prompt。
- 不修改默认 `top_k=3`。
- 不切换 `rag_default_retrieval_mode=dense_only`。
- 不启用 `rag_query_rewrite_mode`。
- 不启用 `rerank_enabled`。

默认配置继续保持：

```text
rag_default_retrieval_mode = dense_only
rag_query_rewrite_mode = off
rerank_enabled = false
```

---

## 6. 下一阶段方向

下一阶段建议转向 Corpus 扩充第二轮，而不是继续 S5 局部调参。

目标：

- 从当前约 18 个 indexed 文档扩到 30-50 个更真实的 oncall / craft / process / monitoring 文档。
- 优先使用真实业务范围内的 Markdown、PDF、DOCX、XLSX 或工艺/运维材料。
- 扩充后先重跑 retrieval-layer baseline，再观察 answer-layer 是否出现新的稳定失败模式。

重启 Answer 层优化的触发条件：

- corpus 达到 30-50 个 indexed 文档；
- retrieval baseline 在更大 corpus 上安全边界仍干净；
- 新 corpus 中出现可复现的 answer-layer 失败模式；
- 有足够样本支持新的 Answer 50q、prompt shadow、PDF chunk targeting 或 agent_behavior eval。

如果只想继续 S5，也只能另开窄 follow-up：

- `S5P1-MD-002`：`top_k=5 + answer completeness` 组合 shadow；
- Scoutflo 两题：局部 PDF chunk targeting probe。

这两个 follow-up 都不能直接改生产默认。
