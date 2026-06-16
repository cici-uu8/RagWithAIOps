# RAG Retrieval C6 Mixed 54q Residual Failure Triage

日期：2026-06-12

状态：`retrieval_residual_triage_after_answer_60`

## 1. 背景

Answer 30q triage-fix 当前基线为 `18/30`。3q sample-local `top_k=5` Answer shadow 只有 `1/3` 通过，说明 `context coverage != answer quality`。因此当前不继续追 Answer 70%，不进入 `agent_behavior`，也不创建 Answer 50q。

本轮把注意力转回 Retrieval 层，但只做残余失败分流，不改默认检索配置。

输入证据：

```text
Mixed 54q evalset:
evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_54q_after_c6_p2.jsonl

Mixed 54q dense-only report:
evals/knowledge_base/reports/department_rag_mixed_markdown_pdf_54q_after_c6_p2_dense_20260612.json

C6-P3 baseline doc:
docs/RAG_Corpus_清单6_C6-P3_Mixed_54q_retrieval_baseline.md

S4-P2.2 original failure triage:
docs/RAG_QueryRewrite_清单4_S4-P2.2_Mixed_50q失败样本分流分析.md

S4-P2.3 rank-gap C-probe:
evals/knowledge_base/reports/checklist4_s4_p23_rank_gap_c_probe_20260610.json

S4-P3.3 dual probe:
evals/knowledge_base/reports/checklist4_s4_p33_rank_gap_dual_probe_20260611.json
```

## 2. Baseline Snapshot

Mixed 54q dense-only result:

```text
total = 54
passed = 45
failed = 9
pass_rate = 83.33%
answer_wrong = 8
no_retrieval_hit = 1
not_ready = 0
wrong_scope_count = 0
citation_unresolvable_count = 0
all_source_ref_resolvable = true
```

增量结论：

```text
c6_p2_new_samples = 4
c6_p2_new_samples_passed = 4/4
existing_50q_status_changed_count = 0
residual_failures_all_from_old_50q = true
```

这说明 C6 Redis/MySQL 新文档没有制造新的 Retrieval 退化。当前 9 个失败是 S4 Mixed 50q 的旧残留问题。

## 3. Residual Failure Split

| bucket | count | samples | current evidence |
|---|---:|---|---|
| Markdown chunk / context ranking | 3 | `S4M-A-012`, `S4M-E-004`, `S4M-E-006` | expected doc 已命中，但目标段落/关键词没有稳定覆盖 |
| PDF chunk / page / table ranking | 5 | `S4M-B-001`, `S4M-B-008`, `S4M-B-009`, `S4M-C-003`, `S4M-D-001` | expected PDF 已命中，但目标 chunk/page/table 未进入有效 top-3 |
| Expression / lexical gap | 1 | `S4M-E-010` | dense-only no-hit；sparse/hybrid 可恢复到 rank 1 |

当前不是 source_ref、scope、permission 或 artifact 缺失问题：

```text
wrong_scope_count = 0
citation_unresolvable_count = 0
all_source_ref_resolvable = true
pdf_artifact_issue = 0
```

## 4. Prior Probe Evidence

### 4.1 True Rerank C-Probe

S4-P2.3 对 8 个 residual `rank_gap` 样本做过 observation-only C-probe，并在进程内临时启用 true rerank。

结果：

```text
candidate_count = 8
rank_lift_proven_count = 0
rank_observation_only_count = 4
no_rank_lift_count = 4
guardrail_clean = true
true_rerank_applied = true
eligible_for_formal_evalset = false
```

逐样本结果：

| sample_id | verdict | dense_rank | hybrid_rank | hybrid_rerank_rank | reason |
|---|---|---:|---:|---:|---|
| `S4M-A-012` | `no_rank_lift` | 1 | 1 | - | true rerank 没把 expected doc 移入有效 top-k |
| `S4M-B-001` | `rank_observation_only` | 1 | 1 | 1 | expected doc 已在 top-k，rerank 未改善 |
| `S4M-B-008` | `rank_observation_only` | 1 | 1 | 1 | expected doc 已在 top-k，rerank 未改善 |
| `S4M-B-009` | `no_rank_lift` | 1 | 1 | - | true rerank 没把 expected doc 移入有效 top-k |
| `S4M-C-003` | `no_rank_lift` | 1 | 2 | - | true rerank 没把 expected doc 移入有效 top-k |
| `S4M-D-001` | `rank_observation_only` | 1 | 1 | 2 | expected doc 已在 top-k，rerank 未改善 |
| `S4M-E-004` | `no_rank_lift` | 1 | 1 | - | true rerank 没把 expected doc 移入有效 top-k |
| `S4M-E-006` | `rank_observation_only` | 1 | 1 | 1 | expected doc 已在 top-k，rerank 未改善 |

结论：不能从当前 8 个 rank-gap 样本推出 `rerank_enabled=true`，也不能创建 formal C evalset。

### 4.2 Hand Rewrite Probe

S4-P3.3 对 8 个 rank-gap 样本做过手工 rewrite dense-only probe。

结果：

```text
candidate_count = 8
rewrite_lift_proven = 0
rewrite_observation_only = 8
no_rewrite_lift = 0
expression_gap_new_confirmed = 0
```

所有 8 个样本在原 query 下 expected doc 已经是 rank 1，rewrite 后仍是 rank 1。它们不是 doc-level expression-gap 证据。

### 4.3 Sparse / Hybrid Benefit-B Probe

S4-P3.3 对 9 个失败样本做过 sparse/hybrid probe。

结果：

```text
candidate_count = 9
sparse_lift_proven = 1
hybrid_lift_proven = 0
observation_only = 8
no_lift = 0
benefit_b_eligible_for_formal_evalset = false
```

唯一 lift 样本：

```text
S4M-E-010:
dense_rank = 0
sparse_rank = 1
hybrid_rank = 1
benefit_b_verdict = sparse_lift_proven
```

结论：`S4M-E-010` 可作为 Benefit-B / expression-gap 交叉种子，但 1 个样本不足以启动 formal hybrid/default switch。

## 5. Sample Matrix

| sample_id | query | failure | actual retrieval shape | prior probe result | recommended next action |
|---|---|---|---|---|---|
| `S4M-A-012` | CPUThrottlingHigh 告警什么时候需要处理 | `answer_wrong`, score 0.50 | top-1 是 `CPUThrottlingHigh.md` Impact，后两条混入 `cpu_high_usage.md` | rerank `no_rank_lift`; rewrite observation-only; sparse/hybrid observation-only | 做 Markdown target-section probe：看 Notice/Mitigation 是否在 top-k/parent chunk 中可稳定覆盖 |
| `S4M-B-001` | PagerDuty 文档提到哪些 incident response training | `answer_wrong`, score 0.25 | PagerDuty PDF top-3 命中 training 相关 chunk，但缺完整 training course 列表 | rerank observation-only; rewrite observation-only; sparse/hybrid observation-only | 做 PDF target-chunk probe：核对 `c00009/c00010` 文本边界和 heading/table-like list 覆盖 |
| `S4M-B-008` | Scoutflo SRE Playbooks 覆盖哪些平台和用途 | `answer_wrong`, score 0.00 | Scoutflo PDF 命中 video/tutorial/clone chunks，未命中 overview chunks | rerank observation-only; rewrite observation-only; sparse/hybrid observation-only | 做 Scoutflo PDF overview chunk probe；优先看 PDF heading / Document Metadata 噪声是否挤出 overview |
| `S4M-B-009` | Scoutflo 文档里 K8s playbook 覆盖哪些主题 | `answer_wrong`, score 0.00 | Scoutflo PDF 命中 resources/clone chunks，未命中 K8s playbook chunk | rerank `no_rank_lift`; rewrite observation-only; sparse/hybrid observation-only | 做 Scoutflo K8s chunk probe；检查 target chunk 与 resources/clone chunk 的 embedding 竞争 |
| `S4M-C-003` | Unreliability Budgets 定义预算的段落在哪一页 | `answer_wrong`, score 0.25 | Reliability PDF 命中 page 3/2，但目标 page 2 定义段落不稳定 | rerank `no_rank_lift`; rewrite observation-only; sparse/hybrid observation-only | 做 PDF page-source probe；确认 page 2 definition chunk 是否需 page-aware boost 或 eval page field 分离 |
| `S4M-D-001` | Scoutflo 表格里 KubePodCrashLooping 对应哪个 playbook | `answer_wrong`, score 0.00 | Scoutflo PDF 命中 issue/contribution chunks，未命中 `table:t00002` | rerank observation-only; rewrite observation-only; sparse/hybrid observation-only | 做 table retrieval probe；优先验证 table chunk 是否进入 candidate pool，必要时设计 table-aware retrieval shadow |
| `S4M-E-004` | 页面一直转圈很慢先看哪里 | `answer_wrong`, score 0.50 | `slow_response.md` 已命中，但偏 checklist/cause/emergency，混入 MySQL runbook | rerank `no_rank_lift`; rewrite observation-only; sparse/hybrid observation-only | 做 Markdown target-section probe；确认问题描述、应用性能日志和数据库慢查询章节是否被 top-k 覆盖 |
| `S4M-E-006` | CPU throttling 很高要不要加 limit | `answer_wrong`, score 0.25 | `CPUThrottlingHigh.md` 已命中 intro/Impact/Diagnosis，缺 Notice/Mitigation 完整覆盖 | rerank observation-only; rewrite observation-only; sparse/hybrid observation-only | 做 Markdown target-section probe；重点看 Notice / When mixed with other alerts |
| `S4M-E-010` | 数字化产线那个数智医生怎么支撑运维 | `no_retrieval_hit`, score 0.00 | dense-only 无结果 | sparse/hybrid rank 1；confirmed expression-gap seed | 进入 expression/Benefit-B 候选池；继续收集到 10 个 confirmed 后再建 formal evalset |

## 6. Decision

当前 Retrieval 残余失败不能直接推出默认策略变更：

```text
change_default_retrieval_mode = no
enable_rerank_default = no
enable_query_rewrite_default = no
create_formal_benefit_b_evalset = no
create_formal_benefit_c_evalset = no
run_answer_50q = no
enter_agent_behavior = no
```

原因：

- `rank_lift_proven=0/8`，当前 rank-gap 池不能证明 rerank 稳定收益。
- 8 个 rank-gap 的 hand rewrite 没有新增 expression-gap。
- sparse/hybrid 只有 `S4M-E-010` 一个 proven lift，样本数不足。
- 9 个失败没有 source_ref/scope/citation 阻塞，也没有新增 C6 Redis/MySQL 失败。

## 7. Recommended Next Slice

如果继续 Retrieval 优化，推荐不要从默认开关开始，而是做一个窄的 residual source-support/chunk probe：

```text
phase = retrieval_residual_chunk_probe
scope = 8 rank/context samples only
samples = S4M-A-012, S4M-B-001, S4M-B-008, S4M-B-009, S4M-C-003, S4M-D-001, S4M-E-004, S4M-E-006
goal = determine whether failures are target-section absence, PDF heading noise, table chunk retrieval, page field scoring, or eval keyword granularity
non_goals = no default switch, no formal B/C evalset, no Answer rerun
```

优先级：

1. `S4M-D-001` table retrieval probe：表格样本是最清晰的 retrieval surface，能快速判断 table chunk 是否进 candidate pool。
2. Scoutflo PDF cluster probe：`S4M-B-008` / `S4M-B-009` / `S4M-D-001` 同属 Scoutflo PDF，可能共享 Document Metadata 噪声和 target chunk ranking 问题。
3. Markdown target-section probe：`S4M-A-012` / `S4M-E-004` / `S4M-E-006` 验证 target section 是否在 larger top-k 或 parent chunk 中。
4. Expression/Benefit-B collection：保留 `S4M-E-010`，但等真实反馈或候选池达到 10 个后再 formalize。

## 8. Interview Notes

**追问: 为什么不直接打开 rerank？**

答：因为当前 8 个 rank-gap 已经做过 true rerank observation-only probe，`true_rerank_applied=true` 但 `rank_lift_proven=0/8`。这说明当前失败不是简单“rerank 一下就能上来”的形状。打开 rerank 会增加复杂度和成本，但没有稳定收益证据。

**追问: 为什么不直接打开 hybrid？**

答：9 个失败里只有 `S4M-E-010` 是 dense miss 后 sparse/hybrid rank 1 的明确 lift。Benefit-B 需要足够多的 dense miss -> sparse/hybrid hit 样本，当前只有 1 个，不够支撑 default switch 或 formal evalset。

**追问: 既然 Retrieval 83.3%，为什么 Answer 只有 60%？**

答：Retrieval 评的是 expected doc/source_ref 是否能召回，Answer 评的是最终生成答案是否覆盖 deterministic 必答事实。3q top_k=5 Answer shadow 已证明 context 缺失清空后，LLM 仍可能漏写关键事实。所以 Retrieval 健康是 Answer 的前提，但不是 Answer 通过的充分条件。
