# RAG Query Rewrite 清单 4 S4-P2.2 Mixed 50q 失败样本分流分析

日期：2026-06-10

状态：`triage_done_eval_design_repaired_and_rerun_followed_by_s4_p23_probe`

对应规范：`docs/RAG_QueryRewrite_清单4_S4-P2.1_三层评测体系总规范.md`

---

## 0. 结论

本轮先分析 retrieval 层的 18 个失败样本，再修复其中 9 个 `eval_design_issue` 样本的
`expected_answer_keywords` / `source_support` 设计问题，并复跑 dense-only baseline。
本轮没有运行新的检索模式对比，没有启用 hybrid / rerank / Query Rewrite。

输入：

```text
evalset = evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_50q.jsonl
baseline = evals/knowledge_base/reports/department_rag_mixed_markdown_pdf_50q_dense_baseline_20260610.json
post_repair_baseline = evals/knowledge_base/reports/department_rag_mixed_markdown_pdf_50q_dense_baseline_after_s4_p23_repair_20260610.json
```

Baseline 已知结果：

```text
total = 50
passed = 32
failed = 18
answer_wrong = 17
no_retrieval_hit = 1
wrong_scope_count = 0
citation_unresolvable_count = 0
all_source_ref_resolvable = true
```

修复 9 个 `eval_design_issue` 后复跑 dense-only 的结果：

```text
total = 50
passed = 41
failed = 9
answer_wrong = 8
no_retrieval_hit = 1
wrong_scope_count = 0
citation_unresolvable_count = 0
all_source_ref_resolvable = true
```

统一分流结论：

| triage_category | 数量 | 说明 |
|---|---:|---|
| `eval_design_issue` | 9 | expected doc/chunk 已基本命中，但关键词、source_support 或评分字段过严 |
| `rank_gap` | 8 | expected doc 命中，但目标 chunk/table/page 没稳定进入 top-3 |
| `confirmed_expression_gap` | 1 | 原始差表达导致 dense-only 完全 no-hit，可进入 rewrite 候选 |
| `retrieval_gap` | 0 | 没有确认纯粹的 dense doc-level retrieval gap；唯一 no-hit 被归入 expression-gap |
| `pdf_artifact_issue` | 0 | 未发现 artifact 缺失、source_ref 不可回查或 table_id 不存在 |

修复复跑后的残余失败：

| triage_category | 残余数量 | 样本 |
|---|---:|---|
| `rank_gap` | 8 | `S4M-A-012`, `S4M-B-001`, `S4M-B-008`, `S4M-B-009`, `S4M-C-003`, `S4M-D-001`, `S4M-E-004`, `S4M-E-006` |
| `confirmed_expression_gap` | 1 | `S4M-E-010` |
| `eval_design_issue` | 0 | 原 9 个样本已通过修复后的 dense-only rerun |
| `retrieval_gap` | 0 | 无确认样本 |
| `pdf_artifact_issue` | 0 | 无确认样本 |

当前决策：

```text
s4_p22_status = triage_done_eval_design_repaired
s4_p23_followup = completed_observation_only_negative
rank_lift_proven = 0/8
rank_observation_only = 4/8
no_rank_lift = 4/8
primary_next = expand_expression_gap_candidates_before_query_rewrite_shadow
secondary_next = do_not_create_formal_bc_evalset_from_current_rank_gap_pool
query_rewrite_next = record_s4m_e_010_only_not_formal_evalset
pdf_fix_next = not_required_from_current_evidence
default_switch_eligibility = not_eligible_for_default_switch
```

后续 S4-P2.3 结果：

- `evals/knowledge_base/checklist4_s4_p23_rank_gap_c_probe.py` 已对 8 个残余 `rank_gap` 样本运行 dense / hybrid / hybrid_rerank observation-only probe。
- 报告 `evals/knowledge_base/reports/checklist4_s4_p23_rank_gap_c_probe_20260610.json` 结论为 `status=observation_only`、`rank_lift_proven_count=0`、`rank_observation_only_count=4`、`no_rank_lift_count=4`、`eligible_for_formal_evalset=false`。
- 该结果说明当前 8 个样本不能证明 rerank 对 doc-level expected_doc 排序有稳定收益；下一步应扩充 expression-gap 候选，而不是升级 B/C 或切换默认配置。

判断：

- 不需要继续先修 eval/source_support：本轮 9 个 `eval_design_issue` 已修复并复验。
- 不需要先修 PDF artifact：仍然没有 source_ref 不可回查、table_id 缺失或页码 artifact 缺失证据。
- 可以进入 B/C 方向，但只能是 observation-only C-probe：当前残余 8 个稳定 `rank_gap` 样本不足以直接证明 rerank 稳定收益。
- Query Rewrite 仍不能进入正式 shadow：当前只有 `S4M-E-010` 这 1 个确认表达缺口，需要扩充 expression-gap 候选后再建正式 rewrite eval。

---

## 1. 分流规则

| triage_category | 判定标准 | 后续动作 |
|---|---|---|
| `eval_design_issue` | expected doc / source_ref 已命中，但失败来自关键词过严、OR 字符串、页码作为关键词、source_support 范围过宽 | 先修 evalset / source_support，不进入算法增强 |
| `retrieval_gap` | dense-only 没有命中 expected doc，且不是 scope / expression / corpus 问题 | S4-P2 Benefit-B sparse/hybrid probe |
| `rank_gap` | expected doc 命中，但目标 chunk/table/page 未进入 top-k 或被邻近 chunk 挤出 | S4-P2 Benefit-C rerank / top-k / chunk probe |
| `pdf_artifact_issue` | PDF artifact 缺失、table_id 不存在、source_ref 不可回查、页码错误 | 先修 PDF parser / artifact / chunk |
| `confirmed_expression_gap` | 原始差表达导致失败，人工确认 rewrite 方向合理且 protected_terms 可定义 | S4-P3/P4 Query Rewrite shadow candidate |

硬边界：

- `wrong_scope_count=0`，所以当前没有权限/scope 阻塞。
- `citation_unresolvable_count=0` 且 `all_source_ref_resolvable=true`，所以当前没有 evidence/source_ref 阻塞。
- `pdf_artifact_issue=0`，所以当前不能把失败归因给 PDF artifact 缺失。

---

## 2. 失败样本总览

| failure_class | failed | triage 摘要 |
|---|---:|---|
| `content_recall` | 6 | 5 个 eval/source-support 问题，1 个 rank/context 问题 |
| `pdf_content_recall` | 4 | 1 个 eval/source-support 问题，3 个 PDF chunk rank/context 问题 |
| `pdf_page_source_ref` | 1 | 1 个 PDF page rank/context 问题 |
| `pdf_table` | 1 | 1 个 table rank/context 问题，artifact 本身存在 |
| `expression_gap` | 6 | 3 个 eval/source-support 问题，2 个 rank/context 问题，1 个确认表达缺口 |

---

## 3. 统一分流矩阵

| sample_id | failure_class | failure_category | score | expected_doc_hit | actual_doc_ids 摘要 | triage_category | next_action | blocked_by |
|---|---|---|---:|---|---|---|---|---|
| S4M-A-003 | content_recall | answer_wrong | 0.75 | yes | 全部为 `disk_high_usage.md` | `eval_design_issue` | 修 `expected_keywords`，避免把原因类关键词和“先查什么”混在一题 | source_support 过宽 |
| S4M-A-005 | content_recall | answer_wrong | 0.75 | yes | 全部为 `service_unavailable.md` | `eval_design_issue` | 拆分依赖检查与 OR 表达式；不要把 `downstream_service OR database OR redis OR mq` 当单一硬关键词 | keyword 设计过严 |
| S4M-A-007 | content_recall | answer_wrong | 0.75 | yes | 全部为 `slow_response.md` | `eval_design_issue` | 复核 `database-slow-query` / `EXPLAIN` 是否应作为本题硬关键词 | 关键词与 query 粒度不一致 |
| S4M-A-010 | content_recall | answer_wrong | 0.75 | yes | 2 个 `KubePodNotReady` + 1 个 `KubeNodeNotReady` | `eval_design_issue` | 本题问 “Running but not ready 表示什么”，应降低对 Diagnosis/Debugging 关键词的强绑定 | expected_keywords 覆盖过宽 |
| S4M-A-011 | content_recall | answer_wrong | 0.75 | yes | 全部为 `KubeNodeNotReady.md` | `eval_design_issue` | 复核命令类问题是否需要 `API or kubelet` 作为硬关键词 | strict keyword |
| S4M-A-012 | content_recall | answer_wrong | 0.50 | partial | 1 个 `CPUThrottlingHigh` + 2 个 `cpu_high_usage` | `rank_gap` | 纳入 C-probe 候选；看 rerank/top-k 是否能压过 CPU high 近邻文档 | 近邻 CPU 文档干扰 |
| S4M-B-001 | pdf_content_recall | answer_wrong | 0.25 | yes | PagerDuty chunks `c00008/c00002/c00010` | `rank_gap` | 纳入 PDF rank/context 候选；目标 training chunk `c00009` 未进 top-3 | 目标 chunk 排名不足 |
| S4M-B-006 | pdf_content_recall | answer_wrong | 0.75 | yes | Capacity `c00004/c00033/c00001` | `eval_design_issue` | 复核 capacity 定义题关键词，避免把重复表述当硬匹配 | strict keyword |
| S4M-B-008 | pdf_content_recall | answer_wrong | 0.00 | yes | Scoutflo 但命中 video/tutorial/clone chunks | `rank_gap` | 纳入 C-probe 候选；目标 overview chunks `c00001/c00004` 未进 top-3 | PDF chunk 排名错误 |
| S4M-B-009 | pdf_content_recall | answer_wrong | 0.00 | yes | Scoutflo 但命中 resources/clone chunks | `rank_gap` | 纳入 C-probe 候选；目标 K8s playbook chunk 未进 top-3 | PDF chunk 排名错误 |
| S4M-C-003 | pdf_page_source_ref | answer_wrong | 0.25 | yes | Reliability page 3/3/2，目标 page 2 chunk 排名靠后 | `rank_gap` | 纳入 page/source_ref rank 候选；不是 source_ref 不可回查 | 目标 page chunk 排名不足 |
| S4M-D-001 | pdf_table | answer_wrong | 0.00 | yes | Scoutflo 文档命中，但未命中 `table:t00002` | `rank_gap` | 纳入 table retrieval/rerank 候选；table artifact 存在但 dense top-3 未召回 | table chunk 排名不足 |
| S4M-E-004 | expression_gap | answer_wrong | 0.50 | yes | 全部为 `slow_response.md`，但偏 checklist/cause/emergency | `rank_gap` | 暂不做 rewrite；先看 rank/top-k 是否能召回排查步骤 chunk | 差表达已找到文档 |
| S4M-E-005 | expression_gap | answer_wrong | 0.75 | yes | 全部为 `disk_high_usage.md`，命中 emergency/cause/prevention | `eval_design_issue` | 修关键词或拆题；当前 query 已找到目标文档和应急 chunk | 不是 confirmed rewrite |
| S4M-E-006 | expression_gap | answer_wrong | 0.25 | yes | 全部为 `CPUThrottlingHigh.md`，但未覆盖判断/mitigation 全部关键词 | `rank_gap` | 暂列 C-probe 候选；看 rerank/top-k 是否能召回 Notice/Mitigation | 目标段落排名不足 |
| S4M-E-007 | expression_gap | answer_wrong | 0.25 | yes | Capacity 正确 chunk `c00009` 已 top-1，混入 Scoutflo | `eval_design_issue` | 不把 `page 2` 当普通 keyword；将页码检查交给 source_ref/page 字段 | scoring 字段设计问题 |
| S4M-E-009 | expression_gap | answer_wrong | 0.75 | yes | Scoutflo `table:t00002` 已 top-1 | `eval_design_issue` | 修 table keyword 评分；该样本已经命中目标表 | 不是 confirmed rewrite |
| S4M-E-010 | expression_gap | no_retrieval_hit | 0.00 | no | 无结果 | `confirmed_expression_gap` | 进入 Query Rewrite candidate matrix；建议 rewrite 到 “中车长客 数智医生 安全监测 数据分析 运维支持” | 需要 protected_terms 和 shadow 验证 |

---

## 4. 分类结论

### 4.1 `eval_design_issue`：先修评测，不做算法增强

样本：

```text
S4M-A-003, S4M-A-005, S4M-A-007, S4M-A-010, S4M-A-011,
S4M-B-006,
S4M-E-005, S4M-E-007, S4M-E-009
```

共同特征：

- expected doc 已命中。
- source_ref 全部可回查。
- 失败主要来自关键词过严、source_support 范围过宽、或把页码/table metadata 当普通 context keyword。

后续动作：

```text
next_action = evalset_source_support_repair
do_not_use_for_b_c_probe = true
do_not_use_for_query_rewrite = true
```

### 4.2 `rank_gap`：可作为 C-probe 候选池，但还不够直接升级

样本：

```text
S4M-A-012,
S4M-B-001, S4M-B-008, S4M-B-009,
S4M-C-003, S4M-D-001,
S4M-E-004, S4M-E-006
```

共同特征：

- expected doc 通常已经命中。
- 失败来自目标 chunk/table/page 未稳定进入 top-3，或被近邻文档/chunk 挤出。
- 这更像 rerank/top-k/chunk ranking 问题，不是 Query Rewrite 直接证据。

后续动作：

```text
next_action = collect_c_probe_candidates
current_candidate_count = 8
formal_c_evalset_ready = false
```

说明：

- 现有 C-probe 候选只有 8 个，低于之前正式升级门槛的 10 个有效样本。
- 下一步可以先做 observation-only C-probe，或补充 2+ 个 rank-gap 样本后再设计正式 C evalset。

### 4.3 `confirmed_expression_gap`：Query Rewrite 候选不足

样本：

```text
S4M-E-010
```

理由：

- 原始 query 是口语化 + 隐含 scope：“数字化产线那个数智医生怎么支撑运维”。
- dense-only 完全 no-hit。
- expected doc 是 process digital 的数字化转型文档，source_support 指向“数智医生”段。

后续动作：

```text
next_action = create_rewrite_candidate_for_s4m_e_010_only
formal_query_rewrite_evalset_ready = false
blocked_by = confirmed_expression_gap_count_too_small
```

说明：

- 当前只有 1 个确认表达缺口，不足以创建正式 Query Rewrite evalset。
- 可以先记录 rewrite candidate，但不能据此实现或启用 Query Rewrite。

### 4.4 `pdf_artifact_issue`：当前没有确认问题

当前没有样本进入 `pdf_artifact_issue`。

证据：

- baseline summary 中 `citation_unresolvable_count=0`。
- `all_source_ref_resolvable=true`。
- `S4M-D-001` 的 `t00002` artifact 存在，只是 dense top-3 没召回 table chunk。
- `S4M-E-009` 反而能把 `table:t00002` 放到 top-1，说明表格 artifact 本身不是缺失状态。

后续动作：

```text
pdf_parser_or_artifact_fix_required = false
```

---

## 5. 下一阶段优先级

按 S4-P2.1 三层评测体系、修复后 baseline、以及 S4-P2.3 probe 结果，下一步顺序是：

1. 不从当前 8 个 `rank_gap` 样本创建正式 C evalset：S4-P2.3 已证明 `rank_lift_proven=0/8`。
2. 将 `S4M-E-010` 单独记录为 Query Rewrite candidate，并继续扩充 expression-gap 候选；确认样本达到可评测规模后再建正式 rewrite evalset。
3. 若未来仍要验证 rerank，需要重新设计 rank-gap 候选池或回到 chunk/source_support 设计，不升级 rerank active。
4. 不做 PDF artifact 修复，因为当前没有 artifact 缺失证据。
5. 不做默认切换，因为 retrieval 层仍有 9/50 失败，answer 层和 agent_behavior 层也尚未建立正式 eval。

当前建议：

```text
recommended_next_stage = S4-P3 expression_gap_candidate_expansion
rank_gap_probe_result = S4-P2.3 observation_only_negative
do_not_switch_defaults = true
```

---

## 6. 不做事项

当前不做：

- 不启用 `rag_default_retrieval_mode=hybrid`。
- 不启用 `rerank_enabled=true`。
- 不启用 `rag_query_rewrite_mode`。
- 不运行 answer-layer RAGAS / LLM-as-judge 来覆盖 retrieval 失败。
- 不把 1 个 confirmed expression-gap 样本升级成正式 Query Rewrite evalset。
- 不把 8 个 rank-gap 候选直接解释为 rerank 有稳定收益。
- 不修 PDF parser / artifact，因为当前证据不指向 artifact 缺失。
- 不把修复后的 41/50 dense-only 结果解释为可以切默认；它只说明评测设计噪声已减少。

---

## 7. 给小白解释

这次 18 个失败不是都代表“搜索坏了”。

第一轮分下来后发现：

- 有 9 个更像题目本身太严格，比如关键词写得太死，或者把页码当成普通文字去匹配。
- 有 8 个像“资料方向找到了，但具体段落或表格没排到前 3”。
- 只有 1 个像真正的“用户说法太口语，系统完全没搜到”。
- 没有发现越权、引用不可回查、PDF 表格丢失这类硬问题。

现在 9 个题目设计问题已经修掉并复跑，结果从 32/50 提升到 41/50。
剩下 9 个失败里，8 个是“找到了文档但段落/表格/页码排得不够好”，适合做
observation-only C-probe；1 个是“用户表达不标准导致完全搜不到”，只能先做
Query Rewrite 候选扩充。默认检索和 rewrite 开关仍然不能动。

如果修完以后还剩一批 rank-gap，再看 rerank。

如果后续能找到更多真实表达缺口，再做 Query Rewrite shadow。
