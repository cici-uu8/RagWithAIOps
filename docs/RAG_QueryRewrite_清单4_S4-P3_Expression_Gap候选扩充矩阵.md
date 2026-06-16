# RAG Query Rewrite 清单 4 S4-P3 Expression-Gap 候选扩充矩阵

日期：2026-06-11

状态：`review_only_candidate_matrix`

```text
formal_jsonl_created = no
dense_only_baseline_run = no
observation_dense_probe_run = yes
followup_observation_probe_run = yes
query_rewrite_shadow_run = no
rag_query_rewrite_mode = off
rag_default_retrieval_mode = dense_only
rerank_enabled = false
confirmed_expression_gap_count_conservative = 2
confirmed_expression_gap_count_optimistic = 3
formal_countable_expression_gap_count = 2
conditional_pending_benefit_b_probe_count = 1
ready_for_expression_gap_jsonl = false
default_switch_eligibility = not_eligible_for_default_switch
```

---

## 0. 结论

本文件只做人工 review 候选扩充，不创建 JSONL。

当前只有 `S4M-E-010` 一个已确认 expression-gap 样本：原始 query 是隐含 scope + 口语化，dense-only 完全 no-hit，且目标文档已经 indexed、source support 清楚。

2026-06-11 对来源 B 的 12 个 pending 候选做了 observation-only dense probe。该 probe 没有创建正式 JSONL，没有运行正式 baseline，只在一次 Python 进程里构造候选样本并调用现有 `evaluate_case(...)`，用空 `expected_answer_keywords` 聚焦 expected doc hit，不把严格关键词缺失当作 confirmed expression-gap。

人工 review 后结论：

- `S4P3-EG-010` 计为 `confirmed_expression_gap`：原 query dense no-hit，用户口语“预算烧完 / 发版”和文档术语 `unreliability budget consumed / releases / new pushes` 存在明确表达缺口；手工 rewrite 后 dense-only 命中 expected doc rank 1，说明 rewrite recoverability 存在。
- `S4P3-EG-006` 不计入正式 expression-gap：原 query dense no-hit，但 follow-up probe 显示 `sparse_only` 和 `hybrid` 都能把 expected doc 排到 rank 1，更像 Benefit-B lexical/hybrid 候选。它保留为 `conditional_pending_benefit_b_probe`，不进入 expression-gap 正式计数。

Probe 结果：

```text
probed_pending_candidates = 12
expected_doc_hit = 10
expected_doc_no_hit = 2
probe_confirmed_candidates = S4P3-EG-006, S4P3-EG-010
confirmed_seed_before_probe = 1
confirmed_after_human_review_conservative = 2
confirmed_after_human_review_optimistic = 3
formal_countable_expression_gap_count = 2
formal_jsonl_allowed_now = no
```

`S4M-E-001` 到 `S4M-E-009` 虽然题面属于口语化、缩写、中英混用或症状描述，但它们不能直接作为 confirmed expression-gap：

- 多数已经在 dense-only baseline 通过。
- `S4M-E-004` 和 `S4M-E-006` 的 expected doc 已命中，残余问题是 rank/context/keyword 覆盖，不是 doc-level no-hit。
- 因此它们只能作为“表达类型覆盖样例”，不能当 Query Rewrite 收益证据。

下一步规则：

```text
if confirmed_expression_gap_count >= 10 after human_review:
    create evals/knowledge_base/evalsets/department_rag_expression_gap_candidate_10q.jsonl
    run dense_only baseline
else:
    keep review_only
```

只有这些样本在 dense-only 下稳定失败，且失败不是 eval 设计、语料缺失、权限/scope 或 PDF artifact 问题，才进入 Query Rewrite shadow。

---

## 1. 入选规则

Confirmed expression-gap 必须同时满足：

1. 原始 query 是用户可能真实说出来的差表达。
2. 人工能确认真实意图和 expected doc。
3. expected doc 已 indexed，source support 可回查。
4. dense-only 对原始 query 稳定失败，最好是 expected doc no-hit；如果只是 chunk/keyword 不全，不能直接算 confirmed expression-gap。
5. 失败不是 `eval_design_issue`：关键词、source_support、expected page/table 字段没有明显设计错误。
6. 失败不是 `corpus_missing`：目标知识确实在当前 indexed corpus 中。
7. 改写方向可以定义 protected terms，不会扩大 scope 或改坏专有名词。

Review 状态枚举：

| review_status | 含义 |
|---|---|
| `confirmed_seed` | 当前已有稳定失败证据，可作为种子 |
| `not_confirmed_dense_passed` | dense-only 已通过，不能证明 rewrite 收益 |
| `not_confirmed_rank_or_context_gap` | expected doc 已命中，主要是排序/context/keyword 问题 |
| `pending_dense_probe` | 候选有 source support，但还没跑 dense-only failure probe |
| `probe_confirmed_pending_human_review` | observation-only probe 已出现 expected doc no-hit，但还需人工确认不是 eval / scope / corpus 问题 |
| `confirmed_expression_gap` | 人工确认是表达缺口，且可计入 formal expression-gap 计数 |
| `conditional_pending_benefit_b_probe` | 原 query dense no-hit，但 sparse/hybrid 可恢复或需 Benefit-B 进一步归类；不计入 expression-gap 正式计数 |
| `rejected_scope_or_corpus_unclear` | 当前意图或语料范围不清，不进入候选 |

---

## 2. 来源 A：复核 S4M-E-001 到 S4M-E-010

依据：

- `evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_50q.jsonl`
- `evals/knowledge_base/reports/department_rag_mixed_markdown_pdf_50q_dense_baseline_after_s4_p23_repair_20260610.json`
- `docs/RAG_QueryRewrite_清单4_S4-P2.2_Mixed_50q失败样本分流分析.md`

| candidate_id | source | 原始 query | 用户真实意图 | expected doc | 表达缺口类型 | 当前 dense 状态 | 为什么不是 eval_design_issue | 为什么不是语料缺失 | 是否能作为 confirmed expression-gap |
|---|---|---|---|---|---|---|---|---|---|
| S4M-E-001 | 50q E 桶复核 | 服务卡死了怎么办 | 服务不可用排查流程 | `doc_68714517-c470-55c9-b94d-b483ebc0e45c` / `service_unavailable.md` | 口语化 | dense 已通过 | 已通过，不是失败样本 | 目标 runbook 已 indexed | 否，`not_confirmed_dense_passed` |
| S4M-E-002 | 50q E 桶复核 | K8s pod起不来咋整 | Kubernetes Pod NotReady 排查 | `doc_8ad1b6b2-93b5-50b2-90c9-78dbcb31301b` / `KubePodNotReady.md` | 缩写 + 口语化 | dense 已通过 | 已通过，不是失败样本 | 目标 runbook 已 indexed | 否，`not_confirmed_dense_passed` |
| S4M-E-003 | 50q E 桶复核 | reliability budget是啥意思怎么用 | 可靠性预算定义和使用 | `doc_c89a35d0-1ac4-5a41-b098-6f38a66db450` / Reliability Budgets PDF | 中英混用 + 口语化 | dense 已通过 | 已通过，不是失败样本 | 目标 PDF 已 indexed | 否，`not_confirmed_dense_passed` |
| S4M-E-004 | 50q E 桶复核 | 页面一直转圈很慢先看哪里 | 慢响应排查 | `doc_3c49ecb5-fc61-5869-a847-055176b07393` / `slow_response.md` | 口语化 + 症状描述 | 修复后仍失败，但 expected doc 已命中 | 不是 source_support 错误；残余问题是目标段落/context 覆盖不足 | 目标 runbook 已 indexed | 否，`not_confirmed_rank_or_context_gap` |
| S4M-E-005 | 50q E 桶复核 | 磁盘快爆了先删啥 | 磁盘使用率过高应急清理 | `doc_83f63bdc-b99b-5e9e-aba4-d293764584a4` / `disk_high_usage.md` | 口语化 + 症状描述 | 修复后已通过 | 原失败来自关键词过严，已修复 | 目标 runbook 已 indexed | 否，`not_confirmed_dense_passed` |
| S4M-E-006 | 50q E 桶复核 | CPU throttling 很高要不要加 limit | Kubernetes CPU throttling 处理判断 | `doc_5bf080aa-1fda-5e71-8563-4c55c15d75de` / `CPUThrottlingHigh.md` | 中英混用 + 英文术语 | 修复后仍失败，但 expected doc 已命中 | 不是 source_support 错误；残余问题是目标 Notice/Mitigation 段落覆盖不足 | 目标 runbook 已 indexed | 否，`not_confirmed_rank_or_context_gap` |
| S4M-E-007 | 50q E 桶复核 | capacity文档 source ref 页码怎么查 theoretical minimum | Capacity Planning 页码和 source_ref 查找 | `doc_8aa24d1f-1521-56c9-b5e7-ce4146dff8ed` / Capacity Planning PDF | 中英混用 + 技术术语 | 修复后已通过 | 原失败来自把 page/source_ref 当普通 keyword，已修复 | 目标 PDF 已 indexed | 否，`not_confirmed_dense_passed` |
| S4M-E-008 | 50q E 桶复核 | 工艺版现场问题先保安全怎么做 | 工艺部现场设备故障安全隔离 | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` / craft PDF | 隐含 scope + 口语化 | dense 已通过 | 已通过，不是失败样本 | 目标 PDF 已 indexed | 否，`not_confirmed_dense_passed` |
| S4M-E-009 | 50q E 桶复核 | SRE playbook 里 K8s 告警怎么找 | Scoutflo SRE Playbooks K8s 告警索引 | `doc_9b7841d2-e181-5afc-bc54-daaa5639b979` / Scoutflo SRE Playbooks PDF | 缩写 + 中英混用 | 修复后已通过 | 原失败来自 table keyword 评分，已修复 | 目标 PDF/table 已 indexed | 否，`not_confirmed_dense_passed` |
| S4M-E-010 | 50q E 桶复核 | 数字化产线那个数智医生怎么支撑运维 | 中车长客数字化转型和健康管理 | `doc_6cc9b0b1-d8b7-58d4-a7a0-6213f7717375` / 数字化转型成果 MD | 隐含 scope + 口语化 | dense no-hit | source_support 指向“数智医生”段，字段设计清楚 | 目标 MD 已 indexed，关键词存在 | 是，`confirmed_seed` |

---

## 3. 来源 B：从清单 3 / P2.6 / 清单 4 候选扩充

这些候选来自已 indexed 语料和已有候选设计。2026-06-11 已对 12 个候选做 observation-only dense probe；该 probe 只证明 expected doc 是否被 dense-only top-3 命中，不等于正式 baseline。

| candidate_id | source | 原始 query | 用户真实意图 | expected doc | 表达缺口类型 | 为什么不是 eval_design_issue | 为什么不是语料缺失 | 是否能作为 confirmed expression-gap |
|---|---|---|---|---|---|---|---|---|
| S4P3-EG-001 | 清单4 runbook 语料 | 服务又挂了先看啥 | 服务不可用排查流程 | `doc_68714517-c470-55c9-b94d-b483ebc0e45c` / `service_unavailable.md` | 口语化 + 症状描述 | source support 可指向服务状态日志、依赖检查、恢复依赖服务；仍需人工确认关键词粒度 | 目标 runbook 已 indexed | 否，dense expected doc hit |
| S4P3-EG-002 | 清单4 runbook 语料 | pod 一直起不来不是 crash 那种 | Pod NotReady 排查 | `doc_8ad1b6b2-93b5-50b2-90c9-78dbcb31301b` / `KubePodNotReady.md` | 口语化 + 缩写 + 否定描述 | query 明确排除 CrashLoop，source support 可指向 NotReady Meaning/Diagnosis | 目标 runbook 已 indexed | 否，dense expected doc hit |
| S4P3-EG-003 | 清单4 runbook 语料 | 容器 CPU 被限速了是不是该加大 limit | CPUThrottlingHigh 处理判断 | `doc_5bf080aa-1fda-5e71-8563-4c55c15d75de` / `CPUThrottlingHigh.md` | 中英混用 + 症状描述 | source support 可指向 Notice / Mitigation；正式前需避免把“该不该”设计成过宽关键词 | 目标 runbook 已 indexed | 否，dense expected doc hit |
| S4P3-EG-004 | 清单4 runbook 语料 | 页面转圈 P99 飙了先看哪 | 慢响应排查 | `doc_3c49ecb5-fc61-5869-a847-055176b07393` / `slow_response.md` | 口语化 + 中英混用 + 症状描述 | source support 可指向 response_time、应用性能日志、数据库慢查询、缓存失效；需人工确认 P99 是否硬关键词 | 目标 runbook 已 indexed | 否，dense expected doc hit |
| S4P3-EG-005 | 清单4 runbook 语料 | 盘快满了先清哪里 | 磁盘高使用率应急清理 | `doc_83f63bdc-b99b-5e9e-aba4-d293764584a4` / `disk_high_usage.md` | 口语化 + 症状描述 | source support 可指向删除大日志、清理临时文件、du/find 命令；需避免把未召回命令当硬关键词 | 目标 runbook 已 indexed | 否，dense expected doc hit |
| S4P3-EG-006 | 清单4 runbook 语料 | PVC 快撑爆了怎么办 | PersistentVolume 快满缓解 | `doc_13936d70-e931-53f7-9b5e-1e6aee0dff72` / `KubePersistentVolumeFillingUp.md` | 缩写 + 口语化 + 症状描述 | source support 可指向 Deleting data / Data export / Volume resizing；`PVC` / `PV` 是 protected terms | 目标 runbook 已 indexed | 否，`conditional_pending_benefit_b_probe`；follow-up sparse/hybrid 均 rank 1 命中 |
| S4P3-EG-007 | 清单4 runbook 语料 | 节点 not ready 先查哪条命令 | Node NotReady 命令排查 | `doc_e0307122-ea4c-5459-82bb-9101ee7ab4f4` / `KubeNodeNotReady.md` | 中英混用 + 症状描述 | source support 可指向 `kubectl get node` 和 kubelet/API 检查；需人工确认命令类关键词 | 目标 runbook 已 indexed | 否，dense expected doc hit |
| S4P3-EG-008 | 清单4 mixed PDF 语料 | 工艺现场先别伤人怎么隔离 | 工艺现场安全隔离 / LOTO | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` / craft PDF | 隐含 scope + 口语化 | source support 可指向人身安全、警戒线、LOTO、零能量状态；scope 必须锁 `craft_dept` | 目标 PDF 已 indexed | 否，dense expected doc hit |
| S4P3-EG-009 | 清单4 mixed PDF 语料 | SRE 那个表里 crashloop 的 playbook 在哪 | Scoutflo K8s alert table 定位 | `doc_9b7841d2-e181-5afc-bc54-daaa5639b979` / Scoutflo SRE Playbooks PDF | 缩写 + 口语化 + 中英混用 | source support 可指向 `t00002` 表；正式前必须验证 table_id 和 table keywords | 目标 PDF/table 已 indexed | 否，dense expected doc hit |
| S4P3-EG-010 | 清单4 mixed PDF 语料 | 预算烧完还能不能继续发版 | Reliability budget 对发布节奏的影响 | `doc_c89a35d0-1ac4-5a41-b098-6f38a66db450` / Reliability Budgets PDF | 口语化 + 隐含术语 | source support 可指向 budget consumed / new pushes may be reduced；protected terms 包括 `SLO`、`unreliability budget`、`reliability budget`、`error budget` | 目标 PDF 已 indexed | 是，`confirmed_expression_gap`；manual rewrite dense rank 1 命中 |
| S4P3-EG-011 | 清单4 mixed PDF 语料 | capacity 里理论最小容量在哪 | Capacity Planning theoretical minimum page/source_ref | `doc_8aa24d1f-1521-56c9-b5e7-ce4146dff8ed` / Capacity Planning PDF | 中英混用 + 技术术语 | source support 可指向 page 2 `THEORETICAL MINIMUM CAPACITY`；page/source_ref 要作为字段，不当普通 keyword | 目标 PDF 已 indexed | 否，dense expected doc hit |
| S4P3-EG-012 | 清单4 mixed PDF 语料 | Linux 看 CPU 该用哪些命令 | Systems Performance CPU analysis tools | `doc_48d65565-db05-522e-9186-b76e6925370c` / Systems Performance PDF | 隐含文档范围 + 中英混用 | source support 可指向 CPU analysis tools table；正式前必须校验 `t00008` 和 page 74 | 目标 PDF/table 已 indexed | 否，dense expected doc hit |

候选池小结：

```text
confirmed_seed = 1
confirmed_expression_gap = 2
conditional_pending_benefit_b_probe = 1
not_confirmed_dense_expected_doc_hit = 10
minimum_required_confirmed = 10
jsonl_creation_allowed_now = no
```

### 3.1 Observation-only dense probe 结果

Probe 方式：

- 不创建正式 evalset 文件。
- 不调用 LLM 生成答案。
- 不启用 Query Rewrite。
- 不改变默认配置。
- 直接在一次 Python 进程里构造 12 个候选样本并调用 `evaluate_case(...)`。
- `expected_answer_keywords=[]`，只观察 expected doc 是否被 dense-only top-3 命中。

结果矩阵：

| candidate_id | dense status | failure_category | result_count | expected_doc_hit | actual_doc_ids 摘要 | review 结论 |
|---|---|---|---:|---|---|---|
| S4P3-EG-001 | passed | passed | 3 | yes | `service_unavailable.md` | 不计入 confirmed |
| S4P3-EG-002 | passed | passed | 3 | yes | `KubePodNotReady.md` + Scoutflo | 不计入 confirmed |
| S4P3-EG-003 | passed | passed | 3 | yes | CPU high + `CPUThrottlingHigh.md` | 不计入 confirmed |
| S4P3-EG-004 | passed | passed | 3 | yes | `slow_response.md` + service unavailable | 不计入 confirmed |
| S4P3-EG-005 | passed | passed | 3 | yes | `disk_high_usage.md` | 不计入 confirmed |
| S4P3-EG-006 | failed | answer_wrong | 2 | no | CPU high + disk high | 不计入 expression-gap；转 Benefit-B lexical/hybrid observation 候选 |
| S4P3-EG-007 | passed | passed | 3 | yes | `KubeNodeNotReady.md` | 不计入 confirmed |
| S4P3-EG-008 | passed | passed | 3 | yes | craft PDF | 不计入 confirmed |
| S4P3-EG-009 | passed | passed | 3 | yes | Scoutflo PDF | 不计入 confirmed |
| S4P3-EG-010 | failed | answer_wrong | 2 | no | oncall handbook | 计入 confirmed expression-gap |
| S4P3-EG-011 | passed | passed | 3 | yes | Capacity Planning PDF | 不计入 confirmed |
| S4P3-EG-012 | passed | passed | 3 | yes | Systems Performance PDF | 不计入 confirmed |

人工 review 后状态：

```text
S4P3-EG-006 = conditional_pending_benefit_b_probe
S4P3-EG-010 = confirmed_expression_gap
```

### 3.2 Follow-up observation probe 结果

Probe 方式：

- 不创建正式 evalset 文件。
- 不启用 Query Rewrite。
- 不改变默认配置。
- `S4P3-EG-006` 用原 query 跑 `sparse_only` / `hybrid`。
- `S4P3-EG-010` 用手工 rewrite query 跑 `dense_only`。

结果矩阵：

| probe_id | query | mode | expected_doc_hit | expected_doc_rank | source_ref clean | 结论 |
|---|---|---|---|---:|---|---|
| S4P3-EG-006-sparse-only-probe | PVC 快撑爆了怎么办 | sparse_only | yes | 1 | yes | Benefit-B lexical/hybrid observation 候选 |
| S4P3-EG-006-hybrid-probe | PVC 快撑爆了怎么办 | hybrid | yes | 1 | yes | Benefit-B lexical/hybrid observation 候选 |
| S4P3-EG-010-manual-rewrite-dense-probe | unreliability budget 耗尽后是否限制 releases/new pushes | dense_only | yes | 1 | yes | rewrite recoverability observed |

计数：

```text
confirmed_expression_gap_count_conservative = 2
confirmed_expression_gap_count_optimistic = 3
formal_countable_expression_gap_count = 2
minimum_required_confirmed = 10
ready_for_expression_gap_jsonl = false
```

---

## 4. 来源 C：真实 query log 复核

检查过的本地来源：

- `logs/enterprise_chat_sessions.sqlite`
- `logs/app_2026-06-01.log` 到 `logs/app_2026-06-11.log`

结论：

```text
usable_real_query_log_for_expression_gap = limited
most_entries = eval_smoke_or_aiops_lab_prompts
no_new_confirmed_expression_gap_from_logs = true
```

可观察到的自然 query 很少，多数是 smoke / AIOps lab / eval runner 产生，不适合作为真实 expression-gap ground truth。下面只记录可复核线索，不计入 confirmed。

| candidate_id | source | 原始 query | 用户真实意图 | expected doc | 表达缺口类型 | 为什么不是 eval_design_issue | 为什么不是语料缺失 | 是否能作为 confirmed expression-gap |
|---|---|---|---|---|---|---|---|---|
| S4P3-LOG-001 | `logs/enterprise_chat_sessions.sqlite` / app log | CPU 告警 | CPU high runbook 或 AIOps alert 诊断 | `doc_3b15644b-9560-5846-ad86-832321f6c4aa` / `cpu_high_usage.md` 或 AIOps 工具链 | 缩写 + 过宽症状 | 还没有固定 expected doc 和 runner 字段，不能判断 eval 设计是否正确 | CPU runbook 已 indexed，但 query 也可能是 AIOps 工具意图 | 否，`rejected_scope_or_corpus_unclear` |
| S4P3-LOG-002 | app log | 参数表在哪里 | 查某个参数表或系统配置 | 暂无可靠 expected doc | 口语化 + 隐含对象 | 缺少 source_support，不能排除 eval 设计问题 | 当前 corpus 中没有明确“参数表”目标 | 否，`rejected_scope_or_corpus_unclear` |
| S4P3-LOG-003 | app log | 中车长客数字化转型 相关文件有什么 | 查数字化转型资料 | `doc_6cc9b0b1-d8b7-58d4-a7a0-6213f7717375` | 普通自然问法 | 不属于失败样本；更像已明确主题查询 | 目标 MD 已 indexed | 否，需先跑失败 probe，当前不算 expression-gap |
| S4P3-LOG-004 | `logs/enterprise_chat_sessions.sqlite` | diagnose alert | AIOps 告警诊断 | AIOps agent behavior eval，不是 RAG doc eval | 英文短 query | 不属于 mixed RAG retrieval evalset | 目标不是 KB 文档，而是工具链 | 否，移出 RAG expression-gap |

---

## 5. 人工 Review 清单

转正式 JSONL 前逐条确认：

- [ ] `original_query` 是否真实、自然，不是为了让 dense 失败而硬造。
- [ ] `canonical_intent` 是否唯一，是否会误伤其他文档。
- [ ] `expected_doc` 是否已 indexed。
- [ ] `expected_keywords` 是否来自 source support，而不是希望答案里出现的推理词。
- [ ] `expression_gap_type` 是否覆盖口语化、缩写、中英混用、症状描述、隐含 scope。
- [ ] `protected_terms` 是否能保护产品名、部门、缩写、表格 ID、doc_id、source_ref 术语。
- [ ] dense-only baseline 是否真的失败。
- [ ] 失败是否能排除 eval_design_issue、corpus_missing、permission/scope、PDF artifact。

---

## 6. 后续执行规则

如果人工 review 后确认 `>=10` 个 confirmed expression-gap：

1. 创建：

```text
evals/knowledge_base/evalsets/department_rag_expression_gap_candidate_10q.jsonl
```

2. 先跑 dense-only baseline。
3. 只有 baseline 稳定失败，才进入 Query Rewrite shadow。
4. Query Rewrite shadow 只生成 candidate，不替换真实 query。

如果不足 `10` 个：

```text
status = expression_gap_candidate_pool_insufficient
next_action = human_review_two_probe_confirmed_candidates_then_collect_more
rag_query_rewrite_mode = off
```

---

## 7. 给小白解释

现在不是说“用户说话不标准，所以马上写 Query Rewrite”。

现在只有一个错题能证明这个问题：`数字化产线那个数智医生怎么支撑运维`。其他看起来口语化的题，大多系统已经能搜到，不能拿来证明 Query Rewrite 有用。

所以这一步是在收集更多同类错题。凑够 10 个，并且这些题在 dense-only 下真的稳定失败，才有资格开始 Query Rewrite shadow。
