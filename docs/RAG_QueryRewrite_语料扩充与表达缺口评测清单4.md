# RAG Query Rewrite 语料扩充与表达缺口评测清单 4

日期：2026-06-09

状态：S4-P3 expression_gap_observation_dense_probe_done_insufficient

适用范围：清单 3 已阶段性收口后，继续推进 RAG 检索增强、Query Rewrite shadow、hybrid / rerank 价值证明时使用。

---

## 0. 一句话结论

下一阶段不继续在当前 3 个 indexed 文档上硬推 hybrid / rerank / rewrite。

正确顺序是：

1. 先扩充到 10+ 更复杂 indexed 文档。
2. 再补齐 mixed Markdown+PDF RAG eval readiness。
3. S4-P1.7 已完成首批 reviewed PDF import/index；当前有 6 个 indexed PDF，PDF corpus/artifact gate 已通过。
4. AWS 827 页长 PDF 暂缓，不纳入首版 mixed baseline。
5. 10q pilot 已完成 source-support / expected keywords / table_id 修正，dense-only pilot baseline 复跑为 10/10 passed。
6. Mixed 50q 逐题 source-support 候选矩阵已人工 review 通过，并已转成正式 JSONL。
7. 正式 mixed 50q readiness 已通过，dense-only baseline 已完成。
8. 初始 baseline 结果是 32/50 passed、18 failed；安全边界没有退化。
9. 已新增 S4-P2.1 三层评测体系总规范，固定 retrieval / answer / agent_behavior 三层评测对象和门禁。
10. 已完成 S4-P2.2 统一失败分流矩阵：9 个 `eval_design_issue`、8 个 `rank_gap`、1 个 `confirmed_expression_gap`、0 个 `retrieval_gap`、0 个 `pdf_artifact_issue`。
11. 9 个 `eval_design_issue` 已修复并复跑 dense-only mixed 50q，结果为 41/50 passed、9 failed；安全边界仍未退化。
12. S4-P2.3 observation-only C-probe 已完成：8 个 `rank_gap` 样本中 `rank_lift_proven=0`、`rank_observation_only=4`、`no_rank_lift=4`，低于 6/8 门槛，不能升级正式 C evalset。
13. 已创建 S4-P3 expression-gap review-only 候选扩充矩阵，并对来源 B 的 12 个 pending 候选完成 observation-only dense probe：10 个 dense-only 已命中 expected doc，2 个出现 expected doc no-hit。人工 review 后，`S4P3-EG-010` 计入 `confirmed_expression_gap`，`S4P3-EG-006` 转为 `conditional_pending_benefit_b_probe`；当前正式可计数 expression-gap 为 2，保守 2、乐观 3，仍不足 10，不能创建正式 expression-gap JSONL。
14. 已创建 Benefit-B hybrid review-only 候选扩充矩阵；当前有历史 `RAG-02` seed 需要在当前 mixed corpus 重验，另有 `S4P3-EG-006` follow-up observation：原 query dense no-hit，`sparse_only` / `hybrid` 均命中 expected doc rank 1 且 source_ref/scope clean。P2.6 Benefit-B probe 曾为 `0/15`，所以当前仍不能创建正式 Benefit-B JSONL。
15. Query Rewrite 只做 shadow 候选与评测，不替换真实检索 query。

当前默认配置必须保持：

```text
rag_default_retrieval_mode = dense_only
rag_query_rewrite_mode = off
rerank_enabled = false
default_switch_eligibility = not_eligible_for_default_switch
```

---

## 1. 为什么需要清单 4

清单 3 已经证明了几件事：

- 当前检索 / source_ref / scope 门禁可以被评测。
- Benefit-A 20q 是健康的 content-recall evalset。
- Benefit-B/C 当前候选没有形成稳定收益证据。
- 当前评测没有调用 LLM 生成最终答案，也不是完整真实聊天验收。

但清单 3 的最大限制也很清楚：

- 当前 indexed corpus 只有 3 个文档。
- 当前 indexed PDF 只有 1 个。
- A-20q 四模式都能命中 expected doc，因此不能证明 sparse / hybrid / rerank 比 dense-only 更好。
- B/C probe 是 observation-only，不应升级成正式 evalset。
- Query Rewrite 还没有 expression-gap failure-class 证据。

所以清单 4 的目标不是马上写 rewrite，而是先把“证据池”补足。

---

## 2. 当前事实基线

当前 `data/knowledge_ingestion/current_import_state.json`（2026-06-10 state repair 后）：

| 指标 | 当前值 |
|---|---:|
| total_documents | 19 |
| indexed | 18 |
| parsing | 1 |
| indexed_markdown | 12 |
| indexed_pdf | 6 |

当前 indexed 文档：

| doc_id | kb_id | 文件 |
|---|---|---|
| `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `craft_dept` | `线上故障处理_现场设备工艺版.pdf` |
| `doc_6cc9b0b1-d8b7-58d4-a7a0-6213f7717375` | `process_digital_dept` | `2024_人民网聚焦中车长客数字化转型成果.md` |
| `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `process_digital_dept` | `superbiz_oncall_handbook.md` |
| `doc_3b15644b-9560-5846-ad86-832321f6c4aa` | `process_digital_dept` | `cpu_high_usage.md` |
| `doc_31a0a4e4-d5a6-536e-8bfa-47ecd70bef85` | `process_digital_dept` | `memory_high_usage.md` |
| `doc_83f63bdc-b99b-5e9e-aba4-d293764584a4` | `process_digital_dept` | `disk_high_usage.md` |
| `doc_68714517-c470-55c9-b94d-b483ebc0e45c` | `process_digital_dept` | `service_unavailable.md` |
| `doc_3c49ecb5-fc61-5869-a847-055176b07393` | `process_digital_dept` | `slow_response.md` |
| `doc_67a5deac-6b7f-5598-bdc9-e8345ec539f6` | `process_digital_dept` | `KubePodCrashLooping.md` |
| `doc_8ad1b6b2-93b5-50b2-90c9-78dbcb31301b` | `process_digital_dept` | `KubePodNotReady.md` |
| `doc_e0307122-ea4c-5459-82bb-9101ee7ab4f4` | `process_digital_dept` | `KubeNodeNotReady.md` |
| `doc_5bf080aa-1fda-5e71-8563-4c55c15d75de` | `process_digital_dept` | `CPUThrottlingHigh.md` |
| `doc_13936d70-e931-53f7-9b5e-1e6aee0dff72` | `process_digital_dept` | `KubePersistentVolumeFillingUp.md` |
| `doc_af00144f-20e0-5716-a9e4-9f4b490def6c` | `process_digital_dept` | `online_handbook_1_pagerduty_incident_response_documentation.pdf` |
| `doc_c89a35d0-1ac4-5a41-b098-6f38a66db450` | `process_digital_dept` | `pdf_2__un_reliability_budgets.pdf` |
| `doc_8aa24d1f-1521-56c9-b5e7-ce4146dff8ed` | `process_digital_dept` | `pdf_3_capacity_planning.pdf` |
| `doc_9b7841d2-e181-5afc-bc54-daaa5639b979` | `process_digital_dept` | `github_repo_6_scoutflo_sre_playbooks.pdf` |
| `doc_48d65565-db05-522e-9186-b76e6925370c` | `process_digital_dept` | `pdf_7_systems_performance__enterprise_and_the_cloud___cp.pdf` |

暂缓文档：

| doc_id | kb_id | 状态 | 文件 | 决策 |
|---|---|---|---|---|
| `doc_2e11a6bb-770c-583c-9a32-84454985f7a6` | `process_digital_dept` | `parsing` | `github_repo_5_aws_incident_response_runbooks.pdf` | 827 页长 PDF，暂缓；不继续解析，不纳入首版 50q baseline |

重要边界：

- `original_files_manifest*.tsv` 中的环保、合规、监测 PDF 仍不能直接导入当前 oncall / craft 小样本 KB。
- 如果要使用这些资料，必须先由 owner 明确批准为新的 KB 范围或单独评测域。
- 不能把清单 3 里已经证明无收益的 B/C 候选改个文件名继续当正式证据。
- S4-P1 owner 批准的 10 个 Markdown runbook 已完成导入和索引。
- S4-P1.7 owner 批准的首批 PDF 已完成 reviewed import/index；当前 6 个 PDF 已 indexed，PDF artifact inventory 为 `ready_for_expansion`。
- S4-P1.5 mixed Markdown+PDF RAG eval readiness 在 S4-P1.7 后曾为 `blocked_mixed_evalset_incomplete`，blocker 是正式 mixed 50q evalset 缺失，不是 PDF corpus。该 blocker 已在正式 50q JSONL 创建后解除，当前 readiness 为 `ready_for_mixed_baseline`。

---

## 3. 硬边界

本清单执行期间禁止：

1. 修改 `app/config.py` 默认值来启用 hybrid / rerank / rewrite。
2. 修改 `.env` 来扩大生产或 staging 行为。
3. 将 `rag_query_rewrite_mode` 改成 active。
4. 将 `rag_default_retrieval_mode` 改成 `hybrid` 或 `hybrid_rerank`。
5. 将 `rerank_enabled` 改成全局 true。
6. 把 `retrieval_mode` 暴露给模型工具参数。
7. 直接导入已拒绝的环保 / 合规 / 监测 PDF 到当前 KB。
8. 把 LLM 生成的 rewrite 候选当成 ground truth。
9. 在没有 source_ref / citation / scope 回归报告时声称 retrieval 方案可默认切换。

允许：

- 做只读 inventory。
- 做 reviewed corpus import。
- 做 shadow report。
- 做 expression-gap evalset 设计。
- 在单个评测进程内临时启用 rerank 或 rewrite candidate，用于对照评测，并在结束后恢复。

---

## 4. S4-P0：语料候选 inventory 与 owner review

目标：先确认有哪些文档有资格进入下一阶段 corpus，而不是先跑索引。

输入：

- `data/knowledge_ingestion/current_import_state.json`
- `data/knowledge_ingestion/original_files_manifest.tsv`
- `data/knowledge_ingestion/original_files_manifest_review.tsv`
- 用户或 owner 新提供的候选文档

输出：

- `docs/RAG_QueryRewrite_清单4_语料候选review矩阵.md`

矩阵字段：

| 字段 | 含义 |
|---|---|
| `candidate_id` | 候选文档稳定 ID |
| `source_path` | 原始文件路径 |
| `file_name` | 文件名 |
| `doc_type` | `md/pdf/docx/xlsx/txt` |
| `proposed_kb_id` | 建议 KB |
| `owner_decision` | `approve_current_kb` / `approve_separate_kb` / `reject_current_kb` / `needs_owner_review` |
| `domain_fit` | `oncall` / `craft` / `process_digital` / `environmental` / `compliance` / `other` |
| `complexity_tags` | `long_pdf` / `multi_table` / `near_neighbor_terms` / `acronyms` / `mixed_cn_en` / `manual` / `news` |
| `import_ready` | 是否具备导入条件 |
| `risk_note` | 权限、范围、重复、敏感内容或 out-of-scope 风险 |

通过条件：

- 至少 10 个候选文档获得 `approve_current_kb` 或明确的 `approve_separate_kb`。
- 至少覆盖 2 个 KB。
- 至少包含 3 种文档复杂度标签。
- PDF 样本不能只有当前 1 个 indexed PDF。

阻塞条件：

- 候选不足 10 个。
- 大部分候选来自同一文档拆分。
- owner 未批准当前 KB 范围。
- 候选主要是环保 / 合规 / 监测资料，但没有新 KB 范围批准。

---

## 5. S4-P1：reviewed corpus import / index

目标：只把 S4-P0 通过 review 的文档导入并索引。

动作：

1. 使用项目现有 ingestion / indexing 路径导入。
2. 每个新文档必须生成可追踪 `doc_id`、`kb_id`、`status`。
3. PDF / Office 文档必须保留 artifact 状态。
4. 更新 `current_import_state.json` 或对应 import state 记录。
5. 生成 indexed corpus inventory report。

验收：

```text
indexed_document_count >= 10
indexed_kb_count >= 2
indexed_pdf_count >= 2
artifact_missing_count = 0
source_ref_resolvable = true
```

注意：

- `indexed_document_count >= 10` 是进入下一步的最低门槛，不是默认切换资格。
- 如果新增文档导致 parser / artifact / permission 问题，先修 corpus 质量，不进入 Query Rewrite。

### S4-P1 当时执行结果

Owner 于 2026-06-09 批准以下 10 个 `process_digital_dept` 文档进入 reviewed import / index：

- `S4-LOCAL-A-001..005`: `aiops-docs/cpu_high_usage.md`, `memory_high_usage.md`, `disk_high_usage.md`, `service_unavailable.md`, `slow_response.md`
- `S4-ARCHIVE-B-001..005`: `KubePodCrashLooping.md`, `KubePodNotReady.md`, `KubeNodeNotReady.md`, `CPUThrottlingHigh.md`, `KubePersistentVolumeFillingUp.md`

执行产物：

- 受控原始目录：`原始文件/10_清单4_query_rewrite_corpus/`
- S4-P1 manifest：`data/knowledge_ingestion/checklist4_s4_p1/original_files_manifest.json`
- S4-P1 review：`data/knowledge_ingestion/checklist4_s4_p1/original_files_manifest_review.tsv`
- 当前 indexed corpus inventory：`data/knowledge_ingestion/checklist4_s4_p1/indexed_corpus_inventory_20260609.json`
- 当前 import state：`data/knowledge_ingestion/current_import_state.json`

结果：

```text
s4_p1_status = import_index_complete_with_pdf_diversity_gap
new_indexed_documents = 10
indexed_document_count = 13
indexed_kb_count = 2
indexed_pdf_count = 1
artifact_missing_count = 0
source_ref_resolvable = true
```

解释：

- `indexed_document_count >= 10` 已满足，但不能直接进入 redesigned B/C probe 或 expression-gap baseline；必须先通过 S4-P1.5 mixed Markdown+PDF readiness。
- `indexed_pdf_count >= 2` 未满足，因为本批 owner 批准语料均为 Markdown。PDF 多文档 gate 仍 pending，不能把本批结果外推为 PDF coverage 已完成。
- 默认仍保持 `rag_default_retrieval_mode=dense_only`、`rag_query_rewrite_mode=off`、`rerank_enabled=false`。

当前状态已由 S4-P1.7 更新：首批 reviewed PDF import/index 后，`indexed_pdf_count=6`，PDF corpus/artifact gate 已通过；S4-P1 的 `indexed_pdf_count=1` 只保留为历史阶段证据。

---

## 6. S4-P1.5：Mixed Markdown+PDF RAG eval readiness

目标：先构建能代表真实混合知识库的 RAG 评测体系，再决定是否进入 B/C、Query Rewrite 或 PDF 修复。

设计文档：

```text
docs/RAG_QueryRewrite_清单4_Mixed_RAG评测体系设计.md
```

只读 readiness runner：

```text
evals/knowledge_base/checklist4_mixed_rag_eval_readiness_report.py
```

当前真实报告（正式 50q JSONL 创建后）：

```text
status = ready_for_mixed_baseline
ready_for_mixed_baseline = true
indexed_document_count = 18
indexed_markdown_count = 12
indexed_pdf_count = 6
mixed_evalset_status = loaded
mixed_evalset_samples = 50
markdown_samples = 24
pdf_samples = 26
expression_gap_samples = 10
permission_scope_samples = 5
gaps = []
```

进入 mixed baseline 前必须满足：

| Gate | 最低要求 |
|---|---:|
| indexed documents | >= 10 |
| indexed KB count | >= 2 |
| indexed Markdown docs | >= 5 |
| indexed PDF docs | >= 5 |
| source_ref resolvable | true |
| PDF artifact missing | 0 |
| mixed evalset total samples | >= 50 |
| Markdown samples | >= 20 |
| PDF samples | >= 15 |
| expression-gap samples | >= 10 |
| permission/scope samples | >= 5 |

当前结论：

```text
ready_for_s4_p2_bc_probe = observation_only_c_probe_candidates
ready_for_s4_p3_expression_gap_evalset = false
s4_p23_rank_gap_c_probe = done_observation_only_negative
next_required = expression_gap_candidate_expansion
```

说明：

- 当前可以说“mixed RAG readiness 已通过”：12 个 indexed Markdown + 6 个 indexed PDF，正式 50q JSONL 可加载，expected docs 均已 indexed。
- 当前也可以说“dense-only mixed baseline 已执行并完成第一轮修复复跑”：初始 50q 里 32 个 passed、18 个 failed；修复后 41 个 passed、9 个 failed。
- S4-P2.2 已把 18 个失败分流完毕，并已修复 9 个评测设计/source-support 问题；残余问题是 8 个 rank/context 问题和 1 个 confirmed expression-gap。
- 但不能说“hybrid / rerank / Query Rewrite 可以启用”：没有纯 `retrieval_gap`，S4-P2.3 C-probe 没有证明 rerank rank lift，`confirmed_expression_gap` 只有 1 个，且 PDF artifact 没有缺失证据。
- 下一步只能做 expression-gap 候选扩充；正式 S4-P3 仍必须由更稳定的表达缺口证据触发。

---

## 7. S4-P1.6：Mixed RAG PDF 候选 owner review

目标：先找足够多的 in-scope PDF 候选，让 owner 决定哪些可以进入 reviewed import/index。

候选清单：

```text
docs/RAG_QueryRewrite_清单4_Mixed_RAG_PDF候选owner确认清单.md
```

当时执行结果：

```text
pdf_candidate_inventory_status = done_pending_owner_review
recommended_web_pdf_candidates = 9
recommended_first_batch = 5
local_import_or_index_started = false
network_pdf_download_started = false
```

首批推荐 owner review 的 PDF 候选覆盖：

| 方向 | 候选来源 |
|---|---|
| operations / reliability | AWS Operational Excellence Pillar, AWS Reliability Pillar |
| Kubernetes / platform ops | AWS EKS User Guide, Red Hat OpenShift Nodes |
| monitoring / logging | Red Hat OpenShift Monitoring, Red Hat OpenShift Logging |
| recovery / automation | OpenShift Backup and Restore, AWS Systems Manager |

当时暂停点：

- 等待 owner 从候选中批准 4+ 个 PDF。
- 等待 owner 继续补充更多 PDF。
- 不下载、不导入、不索引。
- 不创建 mixed 50q evalset。
- 不运行 S4-P2 / S4-P3。

批准后才能做：

1. 下载批准 PDF 到 `原始文件/11_清单4_mixed_pdf_corpus/`。
2. 生成 manifest / review TSV。
3. 执行 reviewed import / index。
4. 复跑 S4-P1.5 readiness。

当前状态已由 S4-P1.7 更新：owner 已批准首批 PDF，受控导入/索引已完成。S4-P1.6 不再是 active blocker。

---

## 8. S4-P1.7：reviewed PDF import/index gate closeout

目标：收口首批 in-scope PDF corpus，不继续追长文档，也不做功能增强。

输入：

```text
原始文件/11_清单4_mixed_pdf_corpus/
data/knowledge_ingestion/checklist4_s4_p17_pdf/original_files_manifest.json
data/knowledge_ingestion/checklist4_s4_p17_pdf/original_files_manifest_review.tsv
```

执行结果：

```text
review_rows = 6
eligible = 6
imported = 6
failed = 0
indexed_pdf_count = 6
artifact_present_count = 6
page_sample_candidates = 6
table_sample_candidates = 4
readiness_status = blocked_mixed_evalset_incomplete
ready_for_mixed_baseline = false
```

当前 6 个 indexed PDF：

| doc_id | kb_id | 文件 | 评测用途 |
|---|---|---|---|
| `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `craft_dept` | `线上故障处理_现场设备工艺版.pdf` | craft PDF page/table/source_ref |
| `doc_af00144f-20e0-5716-a9e4-9f4b490def6c` | `process_digital_dept` | `online_handbook_1_pagerduty_incident_response_documentation.pdf` | incident response PDF content/page |
| `doc_c89a35d0-1ac4-5a41-b098-6f38a66db450` | `process_digital_dept` | `pdf_2__un_reliability_budgets.pdf` | reliability/SRE concept PDF content/page |
| `doc_8aa24d1f-1521-56c9-b5e7-ce4146dff8ed` | `process_digital_dept` | `pdf_3_capacity_planning.pdf` | capacity PDF content/table |
| `doc_9b7841d2-e181-5afc-bc54-daaa5639b979` | `process_digital_dept` | `github_repo_6_scoutflo_sre_playbooks.pdf` | SRE playbook PDF content/table |
| `doc_48d65565-db05-522e-9186-b76e6925370c` | `process_digital_dept` | `pdf_7_systems_performance__enterprise_and_the_cloud___cp.pdf` | performance PDF content/table |

明确暂缓：

```text
doc_id = doc_2e11a6bb-770c-583c-9a32-84454985f7a6
file = github_repo_5_aws_incident_response_runbooks.pdf
status = parsing
decision = deferred_long_pdf_stress_eval_candidate
```

解释：

- S4-P1.7 corpus gate 已通过：`indexed_pdf_count=6`，超过 `>=5` 门槛。
- PDF artifact gate 已通过：6 个 indexed PDF artifact 均存在，page coverage 为 1.0，coverage gaps 为空。
- 首版 mixed 50q 不依赖 AWS 827 页长 PDF；该文档后续只能作为 long_pdf / stress eval 候选，不能阻塞当前 50q 设计。
- 该 blocker 已解除：50q 逐题 source-support 候选矩阵已人工 review 通过，正式 JSONL 已创建并通过 readiness。
- 当前 blocker 已切换为 baseline failure-class 分析；不能从 32/50 baseline 直接跳到功能增强或默认切换。

下一步：

```text
docs/RAG_QueryRewrite_清单4_Mixed_RAG_50q评测体系设计.md
```

桶级 coverage matrix 已 review：桶级设计通过。50 条逐题 source-support 候选矩阵已人工 review 通过。

review-only 候选矩阵：

```text
docs/RAG_QueryRewrite_清单4_Mixed_RAG_50q逐题source_support候选矩阵.md
```

正式 evalset 已创建：

```text
evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_50q.jsonl
```

readiness 报告：

```text
evals/knowledge_base/reports/checklist4_mixed_50q_readiness_20260610.json
status = ready_for_mixed_baseline
ready_for_mixed_baseline = true
gaps = []
```

dense-only baseline 报告：

```text
evals/knowledge_base/reports/department_rag_mixed_markdown_pdf_50q_dense_baseline_20260610.json
total = 50
passed = 32
failed = 18
answer_wrong = 17
no_retrieval_hit = 1
wrong_scope_count = 0
citation_unresolvable_count = 0
all_source_ref_resolvable = true
permission_filtered_passed = 2
```

按主桶拆分：

| Bucket | Passed | Failed | Pass rate | 初步结论 |
|---|---:|---:|---:|---|
| A. Markdown content recall | 9 | 6 | 60% | 不到灾难阈值，但需要区分 strict keyword 与真实召回不足 |
| B. PDF content recall | 6 | 4 | 60% | Scoutflo / PagerDuty / Capacity 局部样本需复核 |
| C. PDF page/source_ref | 4 | 1 | 80% | source_ref 基本健康，个别 Reliability 样本需复核 |
| D. PDF table | 4 | 1 | 80% | table gate 基本健康，Scoutflo `t00002` 样本需复核 |
| E. Expression-gap | 4 | 6 | 40% | 触发 expression-gap / Query Rewrite shadow 的候选分析，但不能直接 active |
| F. Permission/scope/citation | 5 | 0 | 100% | 当前 guardrail 未退化 |

Baseline 结论：

```text
mixed_50q_baseline_status = failed_with_actionable_failure_classes
default_switch_eligibility = not_eligible_for_default_switch
next_required = failure_class_analysis_before_any_hybrid_rerank_rewrite_work
```

注意：该 eval 调用真实本地检索、Milvus、embedding 和 source_ref 检查，但不调用 LLM 生成最终回答；结果代表 retrieval/context/source_ref/scope 层面的 baseline，不等价于完整真实聊天验收。

---

## 9.1 S4-P2.1：三层评测体系总规范

目标：在继续失败分流、B/C probe、Query Rewrite 或 answer eval 之前，先固定“评测对象是什么”。

规范文档：

```text
docs/RAG_QueryRewrite_清单4_S4-P2.1_三层评测体系总规范.md
```

当前决策：

```text
eval_layers = retrieval, answer, agent_behavior
retrieval_layer_baseline = done
answer_layer_eval = not_started
agent_behavior_layer_eval = not_unified
ragas_llm_judge_scope = answer_layer_supplement_only
default_switch_eligibility = not_eligible_for_default_switch
next_required = s4_p23_evalset_source_support_repair
```

三层定义：

| 层级 | 评测对象 | 硬门禁示例 | 当前状态 |
|---|---|---|---|
| retrieval | 检索、排序、chunk、source_ref、scope | wrong_scope=0、citation/source_ref 可回查、permission filtered 通过 | mixed 50q baseline 已完成 |
| answer | 基于检索上下文生成的回答 | unsupported claims=0、citation required but missing=0、permission leak=0 | 待建 answer eval |
| agent_behavior | 工具调用、多步计划、审计、AIOps 证据 | forbidden tool=0、audit missing=0、evidence missing=0、permission bypass=0 | 待统一矩阵 |

RAGAS / LLM-as-judge 边界：

- 只用于 answer 层补充 `faithfulness`、`answer relevancy`、`answer correctness` 等回答质量指标。
- 不替代 retrieval 层的 hit@k、recall@k、MRR、source_ref 可回查、wrong_scope、citation 可解析。
- 不替代 agent_behavior 层的工具调用、审计完整性、权限无绕过、AIOps 证据完整性。

解释：

- 当前 mixed 50q 只能说明 retrieval 层 baseline，不代表完整回答质量。
- S4-P2.2 已完成 18 个 retrieval 失败样本分流；只有复验后仍确认失败来自表达缺口、排序、检索模式或 PDF artifact，才进入对应后续阶段。
- 不允许用 LLM judge 的“答案看起来合理”覆盖 source_ref 不可查、scope 错误或工具越权。

---

## 9.2 S4-P2.2：Mixed 50q 统一失败分流矩阵

分流文档：

```text
docs/RAG_QueryRewrite_清单4_S4-P2.2_Mixed_50q失败样本分流分析.md
```

当前结论：

```text
s4_p22_status = triage_done_eval_design_repaired
s4_p23_status = rank_gap_c_probe_done_observation_only
initial_eval_design_issue = 9
residual_eval_design_issue = 0
rank_gap = 8
confirmed_expression_gap = 1
retrieval_gap = 0
pdf_artifact_issue = 0
post_repair_dense_baseline = 41/50 passed
rank_gap_c_probe_rank_lift_proven = 0/8
rank_gap_c_probe_observation_only = 4/8
rank_gap_c_probe_no_rank_lift = 4/8
primary_next = expression_gap_candidate_expansion
secondary_next = no_formal_bc_evalset_from_current_rank_gap_pool
default_switch_eligibility = not_eligible_for_default_switch
```

分流矩阵使用的分类：

| triage_category | 初始数量 | 修复后残余 | 当前处理 |
|---|---:|---:|---|
| `eval_design_issue` | 9 | 0 | 已修 `source_support` / `expected_keywords` / page-table scoring，并复跑 dense-only |
| `rank_gap` | 8 | 8 | S4-P2.3 probe 已跑，0/8 证明 rank lift，保留为 observation-only 负结果 |
| `confirmed_expression_gap` | 1 | 1 | 只记录单个 Query Rewrite 候选，不足以建正式 rewrite evalset |
| `retrieval_gap` | 0 | 0 | 暂无 Benefit-B sparse/hybrid lift 候选 |
| `pdf_artifact_issue` | 0 | 0 | 暂不修 PDF parser / artifact |

下一步：

```text
recommended_next_stage = S4-P3 expression_gap_candidate_expansion
rank_gap_probe_result = S4-P2.3 observation_only_negative
do_not_switch_defaults = true
```

禁止把本轮分流结果解释为：

- hybrid / sparse 有稳定收益；
- true rerank 有稳定收益；
- Query Rewrite 已有足够正式样本；
- PDF artifact 需要先修；
- 默认检索可以切换。

---

## 9.3 S4-P2 后续：重新设计 hybrid / rerank B/C 候选

目标：用扩充后的 10+ indexed 文档重新找 Benefit-B / Benefit-C 样本。

当前 S4-P2.2 / S4-P2.3 约束：

- `retrieval_gap=0`，所以 Benefit-B 暂无正式候选。
- `rank_gap=8` 已完成 S4-P2.3 observation-only C-probe：`rank_lift_proven=0/8`、`rank_observation_only=4/8`、`no_rank_lift=4/8`。
- S4-P2.3 没有达到 6/8 的 formal-value 门槛，且 dense/hybrid 多数样本的 expected doc 已经在 doc-level top-1；当前失败更像 chunk/context/keyword 覆盖问题，不是 doc-level rerank 可稳定修复的问题。
- 当前 rank-gap pool 不能创建正式 B/C JSONL，也不能作为启用 rerank 或切默认检索模式的证据。

Benefit-B 只接受：

- dense-only 没有命中 expected doc。
- sparse-only 或 hybrid 命中 expected doc。
- 没有 wrong_scope。
- source_ref 可解析。

Benefit-C 只接受：

- true rerank 确实执行，`rerank_status=applied`。
- rerank 后 expected doc 排名提升。
- 排名提升不是由 scope 泄露、重复 chunk 或 source_ref 缺失造成。
- latency / fallback 在阈值内。

若以后重新做 Benefit-C，输出：

- `docs/RAG_QueryRewrite_清单4_BC候选矩阵.md`
- 如果新的 probe 通过，再创建正式 JSONL；否则继续 observation-only。

正式升级门槛：

| 类别 | 最低有效样本 | 必须满足 |
|---|---:|---|
| Benefit-B sparse/hybrid lift | 10 | dense miss -> sparse/hybrid recover |
| Benefit-C rerank rank lift | 10 | true rerank rank lift |

不满足时：

- Benefit-B 降级为 `lexical_lift_observation_report`。
- Benefit-C 降级为 `rank_lift_observation_report`。
- 不创建正式 B/C evalset。

---

## 10. S4-P3：expression-gap eval 设计

目标：先证明“用户表达不好”确实是检索失败来源，再决定是否实现 Query Rewrite shadow。

当前 S4-P2.2 / S4-P3 约束：

- `confirmed_expression_gap=2`，当前正式可计数样本是 `S4M-E-010` 和 `S4P3-EG-010`。
- 2026-06-11 已对来源 B 的 12 个 pending 候选做 observation-only dense probe；其中 10 个 dense-only 已命中 expected doc，不能证明 rewrite 收益。
- `S4P3-EG-010` 人工 review 确认为表达缺口；手工 rewrite “unreliability budget 耗尽后是否限制 releases/new pushes” 在 dense-only 下命中 expected doc rank 1，说明 rewrite recoverability 存在。
- `S4P3-EG-006` follow-up probe 显示 `sparse_only` / `hybrid` 均可把 expected doc 排到 rank 1，因此更像 Benefit-B lexical/hybrid 候选，不计入 expression-gap 正式计数。
- 当前正式可计数 expression-gap 为 2，保守 2、乐观 3，仍不足以创建正式 expression-gap evalset，也不足以实现或启用 Query Rewrite。
- 9 个 `eval_design_issue` 已修复并复跑 baseline；S4-P3 的任务不是直接上 rewrite，而是先扩充和人工 review confirmed expression-gap 候选。
- Review-only 候选矩阵已创建：

```text
docs/RAG_QueryRewrite_清单4_S4-P3_Expression_Gap候选扩充矩阵.md
```

当前矩阵结论：

```text
confirmed_seed = 1
confirmed_expression_gap = 2
observation_dense_probe_run = yes
followup_observation_probe_run = yes
pending_dense_probe = 0
probed_pending_candidates = 12
expected_doc_hit = 10
conditional_pending_benefit_b_probe = 1
formal_countable_expression_gap_count = 2
confirmed_expression_gap_count_conservative = 2
confirmed_expression_gap_count_optimistic = 3
minimum_required_confirmed = 10
formal_jsonl_created = no
dense_only_baseline_run = no
query_rewrite_shadow_run = no
rag_query_rewrite_mode = off
```

expression-gap 样本类别：

| 类别 | 示例方向 | 风险 |
|---|---|---|
| 口语化问法 | “设备炸了怎么处理” vs 标准故障流程 | 可能扩大或误解意图 |
| 错别字 / 别名 | “告警 ack” 写成 “ak” 或使用内部别名 | 可能误改专有词 |
| 缩写 | “MCP”“SSE”“API”“RRF” | 可能把缩写展开错 |
| 中英混用 | “stream 卡住 source ref 怎么查” | 可能丢中文上下文 |
| 症状描述不含标准术语 | “页面一直转圈” 对应 SSE / tool timeout | 需要建立术语映射 |
| 隐含部门 / 文档范围 | “工艺版现场问题” 暗含 `craft_dept` | 容易串 KB |
| 过宽问题 | “数字化怎么做” | 需要 scope 锁定而不是随意扩写 |

候选字段：

| 字段 | 含义 |
|---|---|
| `sample_id` | 样本 ID |
| `raw_user_query` | 用户原始差表达 |
| `canonical_intent` | 人工确认的真实意图 |
| `rewrite_candidate` | rewrite 候选，不能作为 ground truth |
| `protected_terms` | 不允许改写的词，例如 doc_id、部门、产品名、缩写 |
| `expected_doc_ids` | 应命中的文档 |
| `expected_keywords` | 应覆盖关键词 |
| `allowed_kb_ids` | 允许检索范围 |
| `forbidden_kb_ids` | 禁止串入范围 |
| `expression_gap_type` | 上表类别 |
| `rewrite_risk` | `low` / `medium` / `high` |
| `source_support` | 样本依据来自哪个 indexed 文档或 artifact |

输出：

- `docs/RAG_QueryRewrite_清单4_S4-P3_Expression_Gap候选扩充矩阵.md`

禁止：

- 不允许用 LLM 自动生成样本后直接进入正式 evalset。
- 不允许没有 source support 的“想象型 query”进入正式 evalset。
- 不允许在 confirmed expression-gap 少于 10 个时创建 `department_rag_expression_gap_candidate_10q.jsonl`。

---

## 10.1 S4-P3 Benefit-B：Hybrid 候选扩充矩阵

目标：如果后续要证明 hybrid 有用，必须专门找 Benefit-B 样本，而不是用普通 50q 失败或 rank-gap 样本替代。

Review-only 候选矩阵：

```text
docs/RAG_QueryRewrite_清单4_S4-P3_Benefit_B_Hybrid候选扩充矩阵.md
```

当前结论：

```text
confirmed_benefit_b_count = 0
historical_seed_count = 1
formal_benefit_b_jsonl_created = no
four_mode_probe_run = no
ready_for_hybrid_default_discussion = false
```

Benefit-B 的硬定义：

```text
dense_only miss
sparse_only or hybrid hit
wrong_scope = 0
source_ref / citation clean
```

当前为什么不能直接用 hybrid：

- `retrieval_gap=0`：mixed 50q 修复后没有正式确认的“dense 找不到但 hybrid 能捞回”的样本。
- P2.6 Benefit-B probe 是 `effective_lift_count=0/15`。
- 历史 `RAG-02` 是一个有价值 seed，但只有 1 条，而且来自早期小语料，需要在当前 18-doc mixed corpus 重验。
- 当前主要新问题是 expression-gap 样本太少，而不是已证明 hybrid 能修的 dense-miss 样本太多。

正式升级门槛：

| 类别 | 最低有效样本 | 必须满足 |
|---|---:|---|
| Benefit-B sparse/hybrid lift | 10 | dense-only miss，sparse/hybrid hit，scope/source_ref/citation 干净 |

不满足时：

```text
status = benefit_b_observation_only
do_not_create_formal_benefit_b_jsonl = true
rag_default_retrieval_mode = dense_only
```

---

## 11. S4-P4：expression-gap baseline eval

目标：先用原始差表达 query 跑 baseline，确认是否真的失败。

动作：

1. 对 expression-gap 候选跑当前默认 dense-only retrieval。
2. 记录 expected-doc hit、wrong_scope、citation/source_ref、latency。
3. 如果 baseline 已经稳定命中，不把该样本计为 rewrite benefit。

关键指标：

| 指标 | 含义 |
|---|---|
| `baseline_expected_doc_hit_rate` | 原始 query 的 expected-doc 命中率 |
| `baseline_wrong_scope_count` | 原始 query 串 scope 数 |
| `baseline_citation_unresolvable_count` | 原始 query 引用不可解析数 |
| `baseline_latency_p95_ms` | baseline p95 延迟 |

结论分类：

- `confirmed_expression_gap`：原始 query 失败，人工确认 rewrite 方向合理。
- `not_expression_gap`：原始 query 已命中，或失败来自语料缺口 / 权限 / parser / source_ref。
- `scope_risk`：rewrite 可能扩大范围，必须保守。
- `needs_corpus_support`：目标文档或关键词不在 indexed corpus。

---

## 12. S4-P5：Query Rewrite shadow

进入条件：

- S4-P3 有正式 expression-gap evalset 草案。
- S4-P4 证明至少一批样本是 `confirmed_expression_gap`。
- 默认配置仍为 `rag_query_rewrite_mode=off`。

shadow 行为：

- 生成 rewrite candidate。
- 保留 `raw_user_query`。
- 记录 `protected_terms`。
- 记录 rewrite trace。
- 不替换真实检索 query。
- 不改变用户可见答案。

如果 rewrite 使用 LLM：

```json
{
  "uses_llm_for_rewrite": true,
  "rewrite_model": "...",
  "prompt_version": "...",
  "temperature": 0,
  "protected_terms_enforced": true
}
```

如果 rewrite 不使用 LLM：

```json
{
  "uses_llm_for_rewrite": false,
  "rewrite_source": "rules_or_dictionary",
  "protected_terms_enforced": true
}
```

对比指标：

| 指标 | 目标 |
|---|---|
| `expected_doc_hit_delta` | rewrite candidate 比 raw query 有稳定提升 |
| `wrong_scope_delta` | 不增加 wrong_scope |
| `citation_unresolvable_delta` | 不增加不可解析 citation |
| `rewrite_harm_count` | 必须为 0 或明确阻塞 |
| `protected_term_mutation_count` | 必须为 0 |
| `latency_p95_delta` | 可接受，默认不超过 baseline 20% |

---

## 13. S4-P6：active 资格门禁

只有同时满足以下条件，才允许讨论 active 或默认切换：

1. indexed corpus 已扩到 10+，且 source_ref / artifact gate 通过。
2. expression-gap eval 证明 rewrite 对确认表达缺口有稳定收益。
3. E1 permission / scope / citation 回归不退化。
4. PDF page / table / source_ref 回归不退化。
5. `wrong_scope_count=0`。
6. `citation_unresolvable_count=0`。
7. `protected_term_mutation_count=0`。
8. `rewrite_harm_count=0`。
9. latency p95 增量可接受。
10. 有 rollback 记录。
11. `PROJECT_STATE.md` 明确记录启用范围、环境、owner 和回滚方式。

如果任何条件不满足：

```text
query_rewrite_active_eligibility = not_eligible
rag_query_rewrite_mode = off
```

---

## 14. 推荐执行顺序

```text
S4-P0 corpus candidate inventory / owner review
  -> S4-P1 reviewed import / index to 10+ docs
  -> S4-P1.5 mixed Markdown+PDF RAG eval readiness
  -> approve/index enough in-scope PDFs
  -> S4-P1.7 PDF corpus/artifact gate closeout
  -> create mixed 50q evalset
  -> dense_only mixed baseline
  -> S4-P2.1 three-layer eval system spec
  -> S4-P2.2 mixed 50q unified failure triage
  -> S4-P2.2 eval/source_support repair and dense_only rerun
  -> S4-P2.3 observation-only C-probe for residual rank gaps (done; no formal upgrade)
  -> S4-P3 expression-gap review-only candidate expansion (observation dense probe done; 2 pending human review; insufficient for JSONL)
  -> S4-P3 Benefit-B hybrid review-only candidate expansion (done; pending human review)
  -> S4-P4 expression-gap baseline eval
  -> S4-P5 Query Rewrite shadow only
  -> S4-P6 active eligibility review
```

S4-P0 当前产物：

```text
docs/RAG_QueryRewrite_清单4_语料候选review矩阵.md
```

S4-P0 当前结论：

```text
s4_p0_status = completed_owner_approved_corpus
ready_for_s4_p1_import = completed
```

当前立即下一步：

```text
基于 S4-P2.3 rank-gap C-probe 负结果：
1. 暂不从当前 8 个 rank_gap 样本创建正式 B/C evalset。
2. `S4P3-EG-010` 已人工确认并通过手工 rewrite dense recoverability probe，计入 confirmed expression-gap。
3. `S4P3-EG-006` 已转为 Benefit-B observation 候选；不能计入 expression-gap 正式数量。
4. 继续收集更多真实表达缺口样本；只有确认 >=10 个后才创建 expression-gap candidate 10q JSONL。
5. 如要证明 hybrid，继续人工 review Benefit-B 候选矩阵；只有确认 >=10 个 dense miss -> sparse/hybrid hit 样本后才跑正式四模式收益评估。
```

不要跳到：

- 直接实现 Query Rewrite。
- 直接创建 B/C 正式 JSONL。
- 直接启用 hybrid / rerank / rewrite。
- 继续推动 AWS 827 页长 PDF 解析。
- 直接导入已拒绝的环保 / 合规 / 监测 PDF。
- 把 41/50 修复后 baseline 当作默认切换依据。

---

## 15. 给小白解释

现在不是要“让搜索变聪明一点就上线”。

现在要先补考场：

- 以前只有 3 本书，题目太少，很容易看起来分数很好。
- 现在要先扩到 10 本以上，而且要更复杂：有手册、有 PDF、有相似术语、有缩写、有跨部门边界。
- 然后专门设计一批“用户说得不标准”的题，比如口语、错别字、缩写、中英混用。
- 先看系统在这些题上到底是不是搜不好。
- 如果确实搜不好，再让 Query Rewrite 在旁边生成一个“建议改写”，但先不影响真实回答。
- 只有证明改写真的更准、没有串部门、引用还可回查、也没有变慢太多，才允许讨论打开。

所以清单 4 的核心是：

> 先补真实语料和坏表达评测，再写 rewrite；先 shadow 证明，再 active。
