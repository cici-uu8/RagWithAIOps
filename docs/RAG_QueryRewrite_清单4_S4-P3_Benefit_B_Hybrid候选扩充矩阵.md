# RAG Query Rewrite 清单 4 S4-P3 Benefit-B Hybrid 候选扩充矩阵

日期：2026-06-11

状态：`review_only_candidate_matrix`

```text
formal_benefit_b_jsonl_created = no
four_mode_probe_run = no
targeted_followup_probe_run = yes
rag_default_retrieval_mode = dense_only
rag_query_rewrite_mode = off
rerank_enabled = false
confirmed_benefit_b_count = 0
observation_benefit_b_candidate_count = 1
historical_seed_count = 1
ready_for_hybrid_default_discussion = false
default_switch_eligibility = not_eligible_for_default_switch
```

---

## 0. 结论

本文件专门回答一个问题：如果要证明 hybrid 有用，应该找什么样的样本。

答案不是“所有项目都用 hybrid，所以这里也直接开”。Benefit-B 的硬定义是：

```text
dense_only miss
sparse_only or hybrid hit
wrong_scope = 0
source_ref / citation clean
```

当前证据还不够：

- 清单 3 的 18q 四模式对比里只有 `RAG-02 线上故障怎么处理` 这 1 个 historical seed 符合 dense miss、sparse/hybrid hit。
- P2.6 后续专门设计的 15 个 Benefit-B 候选 probe 结果是 `effective_lift_count=0/15`。
- Mixed 50q S4-P2.2 结果里 `retrieval_gap=0`，残余失败不是“dense 找不到文档但 hybrid 能捞回”，而是 `rank_gap=8` 和 `confirmed_expression_gap=1`。
- S4-P2.3 rerank C-probe 已证明当前 8 个 rank_gap 样本不能支撑 rerank 价值：`rank_lift_proven=0/8`。
- S4-P3 follow-up observation probe 新增 1 个 Benefit-B observation 候选：`S4P3-EG-006 PVC 快撑爆了怎么办` 原 query dense no-hit，但 `sparse_only` 和 `hybrid` 都命中 expected doc rank 1，且 source_ref/scope clean。它仍只是单样本 observation，不足以创建正式 Benefit-B JSONL。

所以当前不能创建正式 Benefit-B JSONL，也不能讨论把默认检索切到 hybrid。

---

## 1. 为什么别的项目常用 hybrid/rerank，而这里不能直接开

不是因为 hybrid/rerank 没用，也不是因为这个项目永远用不到。

更准确的说法是：

> 其他项目常用 hybrid/rerank，是因为它们经常面对词面编号、缩写、专有名词、长文档噪声、跨文档相似内容等问题。你的项目现在也有这些潜在风险，但当前评测失败分布还没有证明“默认 dense-only 的主要问题正是 hybrid/rerank 能修的那类问题”。

当前 mixed 50q 的事实是：

| 现象 | 当前证据 | 对 hybrid/rerank 的含义 |
|---|---|---|
| 安全边界 | wrong_scope=0，citation/source_ref 可回查 | 先不动默认，安全基线干净 |
| dense-only 修复后 | 41/50 passed | 评测体系已经能暴露失败，但不是默认切换证据 |
| retrieval_gap | 0 | 暂无“dense 找不到文档、hybrid 找到”的正式样本 |
| rank_gap | 8 | 更像 chunk/context/table/page 排名或关键词覆盖问题 |
| C-probe | rank_lift_proven=0/8 | 当前 local rerank 没证明能修这 8 个问题 |
| expression_gap | 1 | 真正新问题更像用户表达差，需要先扩样本 |

这说明：当前评测体系不是“不够完善”，而是已经开始变得更能分辨问题。它告诉我们现在不能把所有失败都粗暴归因到“该开 hybrid/rerank”。

但 Benefit-B 的评测还不够难：还缺一批专门设计来检验词面召回收益的 dense-miss 样本。这个文件就是为下一轮 Benefit-B 证明做候选池。

---

## 2. Benefit-B 入选规则

Confirmed Benefit-B 必须同时满足：

1. 原始 query 有真实业务语义，不是为了打败 dense 而硬造。
2. expected doc 已 indexed。
3. dense-only 的 expected doc no-hit。
4. sparse-only 或 hybrid 命中 expected doc。
5. 结果没有 wrong_scope。
6. source_ref / citation 可解析。
7. 不是 eval_design_issue。
8. 不是 corpus_missing。
9. 不是 query expression-gap 主导的问题。
10. 至少复跑一次稳定。

正式升级门槛：

```text
confirmed_benefit_b_count >= 10
all_wrong_scope_count = 0
all_source_ref_resolvable = true
hybrid_latency_p95_delta <= accepted_threshold
```

不满足时只能是 observation-only。

---

## 3. 已有证据复核

| evidence_id | 来源 | query | expected doc | dense_only | sparse_only | hybrid | 结论 | 是否可计入正式 Benefit-B |
|---|---|---|---|---|---|---|---|---|
| RAG-02 | `retrieval_4mode_comparison_20260609.json` | 线上故障怎么处理 | `superbiz_oncall_handbook.md` | miss | hit | hit | 历史 seed，符合 dense miss -> sparse/hybrid hit | 否，只有 1 条，且来自早期 3-doc 小语料，需要在当前 18-doc mixed corpus 重验 |
| P26-B-001..015 | `checklist3_p26_bc_shadow_probe_20260609.json` | P2.6 Benefit-B 15q | 多个当前 indexed docs | 未形成有效 miss/hit 差异 | 无有效 lift | 无有效 lift | `effective_lift_count=0/15` | 否，已降级 observation |
| S4-P2.2 mixed 50q | `docs/RAG_QueryRewrite_清单4_S4-P2.2_Mixed_50q失败样本分流分析.md` | 50q residual failures | mixed MD/PDF | retrieval_gap=0 | 未证明 | 未证明 | 没有正式 Benefit-B 样本 | 否 |
| S4P3-EG-006 follow-up | 一次性 observation probe | PVC 快撑爆了怎么办 | `KubePersistentVolumeFillingUp.md` | miss | hit rank 1 | hit rank 1 | 当前 corpus 中存在 dense miss -> sparse/hybrid hit，source_ref/scope clean | 否，单样本 observation，需进入 Benefit-B 候选池并累积到 >=10 |

当前可用正式计数：

```text
confirmed_benefit_b_count = 0
observation_benefit_b_candidate_count = 1
historical_seed_count = 1
minimum_required_confirmed = 10
formal_jsonl_allowed_now = no
```

---

## 4. 新 Benefit-B 候选池

这些候选只用于人工 review 和后续 probe 设计。它们还没有证明 dense miss / hybrid hit。

| candidate_id | source | 原始 query | 用户真实意图 | expected doc | Benefit-B 假设 | 为什么不是 eval_design_issue | 为什么不是语料缺失 | 是否能作为 confirmed Benefit-B |
|---|---|---|---|---|---|---|---|---|
| S4P3-B-001 | historical seed refresh | 线上故障怎么处理 | 查 on-call 手册里的线上故障/事故处理入口 | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` / `superbiz_oncall_handbook.md` | 早期 18q 中 dense miss、sparse/hybrid hit；需要在 18-doc mixed corpus 重验 | expected doc 和 scope 明确，旧报告已有 hit/miss 差异 | 目标 MD 已 indexed | 否，`historical_seed_needs_reprobe` |
| S4P3-B-002 | 清单4 current corpus | Ack 超时后 PagerDuty 如何升级 | 查告警 Ack / escalation 规则 | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` / `superbiz_oncall_handbook.md` 或 `doc_af00144f-20e0-5716-a9e4-9f4b490def6c` / PagerDuty PDF | exact English token `Ack` / `PagerDuty` 可能更利于 sparse/hybrid | 需要人工选定单一 expected doc，避免 handbook/PagerDuty 双目标 | 相关 MD/PDF 已 indexed | 待定，`pending_four_mode_probe` |
| S4P3-B-003 | 清单4 current corpus | Alertmanager Silence 维护窗口怎么配 | 查 Silence 维护配置规则 | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` / `superbiz_oncall_handbook.md` | exact tool terms 可能形成 sparse/hybrid lift | source support 可指向 oncall handbook Silence 章节 | 目标 MD 已 indexed | 待定，`pending_four_mode_probe` |
| S4P3-B-004 | 清单4 current corpus | ArgoCD 回滚 SOP 在哪个 Runbook | 查发布回滚 runbook 索引 | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` / `superbiz_oncall_handbook.md` | product identifier + SOP 可能形成 lexical lift | 需确认 `ArgoCD` 是否真实出现在 source support；不确认则剔除 | 目标 MD 已 indexed，但关键词需复核 | 待定，`pending_source_support_review` |
| S4P3-B-005 | 清单4 current corpus | PVC FillingUp 直接扩容怎么处理 | 查 PersistentVolume 快满缓解 | `doc_13936d70-e931-53f7-9b5e-1e6aee0dff72` / `KubePersistentVolumeFillingUp.md` | `PVC` / `FillingUp` 精确词可能帮助 sparse/hybrid | expected doc 明确；需确认 PVC 缩写和 source keywords | 目标 MD 已 indexed | 待定，`pending_four_mode_probe` |
| S4P3-B-013 | S4-P3 follow-up observation | PVC 快撑爆了怎么办 | PersistentVolume 快满缓解 | `doc_13936d70-e931-53f7-9b5e-1e6aee0dff72` / `KubePersistentVolumeFillingUp.md` | 原 query dense no-hit；`PVC` 缩写和存储症状在 sparse/hybrid 下形成 lexical lift | expected doc 已 indexed；follow-up probe 显示 sparse_only/hybrid rank 1 且 source_ref clean | 目标 MD 已 indexed | 否，`observation_benefit_b_candidate_needs_pool_expansion` |
| S4P3-B-006 | 清单4 current corpus | CPUThrottlingHigh shouldn't increase CPU limits 是哪段 | 查 CPU throttling Notice | `doc_5bf080aa-1fda-5e71-8563-4c55c15d75de` / `CPUThrottlingHigh.md` | 长英文短语 exact match 可能帮助 sparse/hybrid | source support 可指向 Notice；需避免把整句设计成过严硬关键词 | 目标 MD 已 indexed | 待定，`pending_four_mode_probe` |
| S4P3-B-007 | 清单4 current corpus | KubeAPIDown 在 Scoutflo 表里在哪里 | 查 Scoutflo K8s alert 表 | `doc_9b7841d2-e181-5afc-bc54-daaa5639b979` / Scoutflo PDF | alert name exact token + table chunk 可能形成 lexical lift | 必须用真实 `expected_table_id=t00002`，避免虚构 table id | 目标 PDF/table 已 indexed | 待定，`pending_four_mode_probe` |
| S4P3-B-008 | 清单4 current corpus | vmstat mpstat uptime 那张表 | 查 Systems Performance CPU analysis tools | `doc_48d65565-db05-522e-9186-b76e6925370c` / Systems Performance PDF | Linux tool exact terms 可能帮助 sparse/hybrid | table/source support 可校验；需明确 expected table/page 字段 | 目标 PDF/table 已 indexed | 待定，`pending_four_mode_probe` |
| S4P3-B-009 | 清单4 current corpus | Scribe Training Deputy Training 在哪 | 查 PagerDuty incident response training | `doc_af00144f-20e0-5716-a9e4-9f4b490def6c` / PagerDuty PDF | training names exact match 可能帮助 sparse/hybrid | source support 可指向 page 3 training chunks | 目标 PDF 已 indexed | 待定，`pending_four_mode_probe` |
| S4P3-B-010 | 清单4 current corpus | THEORETICAL MINIMUM CAPACITY 3.12 bytes | 查 Capacity Planning 理论最小容量段 | `doc_8aa24d1f-1521-56c9-b5e7-ce4146dff8ed` / Capacity Planning PDF | 全大写标题 + 数字 exact token 可能帮助 sparse/hybrid | source support 可指向 page 2；page/source_ref 字段需单独检查 | 目标 PDF 已 indexed | 待定，`pending_four_mode_probe` |
| S4P3-B-011 | 清单4 current corpus | LOTO 零能量 DCS PLC 现场处置 | 查 craft PDF 安全隔离/现场设备 | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` / craft PDF | 缩写 + 专有安全术语可能帮助 sparse/hybrid | scope 必须锁 `craft_dept`，避免跨 KB | 目标 PDF 已 indexed | 待定，`pending_four_mode_probe` |
| S4P3-B-012 | 清单4 current corpus | Unreliability Budgets new pushes reduced | 查 reliability budget 对发版影响 | `doc_c89a35d0-1ac4-5a41-b098-6f38a66db450` / Reliability Budgets PDF | 英文 exact phrase 可能帮助 sparse/hybrid | source support 可指向 page 3；需确认 expected keywords 不过严 | 目标 PDF 已 indexed | 待定，`pending_four_mode_probe` |

---

## 5. 四模式 probe 前置检查

正式跑 Benefit-B probe 前，人工 review 必须删掉以下情况：

- expected doc 不唯一，导致 dense/hybrid 命中不同合理文档也被误判。
- 关键词不在 source support 中，只是候选人希望答案提到。
- query 本质是 expression-gap，而不是 lexical sparse/hybrid lift。
- query 本质是 table/page/source_ref artifact 检查，而不是 retrieval mode lift。
- 目标文档未 indexed 或 scope 不明确。

---

## 6. 后续执行规则

如果人工 review 后能保留 `>=10` 个高质量 Benefit-B 候选：

1. 创建临时 probe evalset 或直接使用候选 matrix 驱动 observation-only runner。
2. 跑四模式对比：

```text
dense_only
sparse_only
hybrid
hybrid_rerank
```

3. 只统计满足以下条件的样本：

```text
dense_only expected_doc_found = false
sparse_only expected_doc_found = true OR hybrid expected_doc_found = true
wrong_scope_count = 0
source_ref_resolvable = true
citation_unresolvable_count = 0
```

4. 如果 confirmed Benefit-B 达到 `>=10`，才考虑正式 JSONL 和后续默认切换门槛讨论。

如果不足 `10` 个：

```text
status = benefit_b_observation_only
do_not_create_formal_benefit_b_jsonl = true
rag_default_retrieval_mode = dense_only
```

---

## 7. 给小白解释

Hybrid 像是“语义搜索 + 关键词搜索一起查”。很多项目会开，是因为用户经常搜缩写、编号、英文专有名词，纯语义搜索可能漏。

但你的项目当前错题不是这个形状：大部分时候 dense 已经找到了目标文档，只是目标段落、表格或关键词覆盖不够；或者只有一个样本像用户表达太口语。这个时候直接开 hybrid，可能增加复杂度和延迟，却不一定修当前错题。

所以现在不是说 hybrid 不用，而是要专门找一批题证明它真的有用：dense 找不到，hybrid 找得到，而且不越权、引用也干净。凑够稳定样本后，hybrid 才有资格进入默认切换讨论。
