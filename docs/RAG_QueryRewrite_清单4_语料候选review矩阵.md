# RAG Query Rewrite 清单 4 语料候选 review 矩阵

日期：2026-06-09

状态：owner_approved_s4_p1_import_index_complete_with_pdf_diversity_gap

对应清单：`docs/RAG_QueryRewrite_语料扩充与表达缺口评测清单4.md`

---

## 0. 结论

S4-P0 的原始结论是：在 owner 未批准前，不能直接进入 S4-P1 import / index。

当前最新状态：owner 已批准 10 个 oncall / AIOps / Kubernetes runbook 候选进入 S4-P1，并已完成 reviewed import / index。

原因：

- 当前只有 3 个 indexed 文档。
- 清单 4 的下一阶段最低门槛是 10+ 更复杂 indexed 文档。
- 现有 manifest 中可见的 12 条 pending PDF 记录，按 SHA 去重后只有 6 个唯一文件组。
- 这 6 个唯一文件组都属于环保、合规或监测资料，之前已经不纳入当前 oncall / craft 小样本 KB。
- 没有 owner 新批准前，不能把这些文件导入当前 KB 来证明 hybrid / rerank / query rewrite。

当前状态：

```text
current_indexed_documents = 13
target_indexed_documents = 10+
additional_approved_current_kb_candidates = 10
additional_owner_review_required_groups = 0 for the approved S4-P1 batch
ready_for_s4_p1_import = completed
pdf_diversity_gate = pending
rag_query_rewrite_mode = off
```

下一步：

```text
基于 13 个 indexed 文档进入 S4-P2 redesigned B/C probe 和 S4-P3 expression-gap 候选草案。
如果要关闭 PDF 多样性 gate，仍需另行批准更多 in-scope PDF。
```

补充盘点：

- 已新增 owner 确认清单：`docs/RAG_QueryRewrite_清单4_语料候选owner确认清单.md`
- 该清单从本地文件和本地资产数据库中整理出 10 个推荐候选：
  - `aiops-docs/*.md` 5 个本地 AIOps runbook。
  - `prometheus-operator-runbooks-main.zip` 中 5 个 Kubernetes / Prometheus runbook。
- 这些候选仍需 owner 批准后才能进入 S4-P1 import / index。

---

## 1. 当前 indexed 基线

来源：`data/knowledge_ingestion/current_import_state.json`

| doc_id | kb_id | status | file_name | 是否计入当前基线 |
|---|---|---|---|---|
| `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `craft_dept` | `indexed` | `线上故障处理_现场设备工艺版.pdf` | 是 |
| `doc_6cc9b0b1-d8b7-58d4-a7a0-6213f7717375` | `process_digital_dept` | `indexed` | `2024_人民网聚焦中车长客数字化转型成果.md` | 是 |
| `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `process_digital_dept` | `indexed` | `superbiz_oncall_handbook.md` | 是 |

基线判断：

- 文档数不足以重新证明 hybrid / rerank 长期收益。
- PDF 样本只有 1 个，不足以扩展 PDF page/table/source_ref 多文档门禁。
- 可以继续作为 regression baseline，但不能作为清单 4 的完整 corpus。

---

## 2. Manifest pending 候选去重结果

来源：

- `data/knowledge_ingestion/original_files_manifest.tsv`
- `data/knowledge_ingestion/original_files_manifest_review.tsv`

盘点结果：

| 指标 | 数量 |
|---|---:|
| manifest rows | 12 |
| unique SHA groups | 6 |
| review_status=pending | 12 |
| import_enabled=false | 12 |
| metadata_only=false | 12 |

这些文件目前只能作为 owner-review 候选，不能直接导入。

---

## 3. 候选 review 矩阵

| candidate_id | source_groups | proposed_kb_id | doc_type | domain_fit | complexity_tags | owner_decision | import_ready | risk_note |
|---|---:|---|---|---|---|---|---|---|
| `S4-CORPUS-ENV-001` | 2 duplicate rows | `process_digital_dept` | pdf | environmental | `report`, `greenhouse_gas`, `long_pdf` | `needs_owner_review_for_separate_kb` | no | `2021_中车长春轨道客车_温室气体排放报告.pdf`，不属于当前 oncall/craft baseline |
| `S4-CORPUS-COMPLIANCE-001` | 2 duplicate rows | `process_digital_dept` | pdf | compliance | `bilingual`, `commitment_letter`, `short_pdf` | `needs_owner_review_for_separate_kb` | no | `2023_中车长春轨道客车_友商合规承诺书中英对照.pdf`，合规范围需单独 KB/权限边界 |
| `S4-CORPUS-MONITOR-001` | 2 duplicate rows | `craft_dept` | pdf | environmental_monitoring | `monitoring_plan`, `long_pdf`, `tables_possible` | `needs_owner_review_for_separate_kb` | no | `2024_中车长春轨道客车_土壤地下水自行监测方案.pdf`，监测资料不能直接驱动当前 RAG 算法证明 |
| `S4-CORPUS-MONITOR-002` | 2 duplicate rows | `craft_dept` | pdf | environmental_monitoring | `monitoring_plan`, `long_pdf`, `tables_possible` | `needs_owner_review_for_separate_kb` | no | `2025_中车长春轨道客车_土壤地下水自行监测方案.pdf`，与 2024 方案相近，需防重复样本 |
| `S4-CORPUS-ENV-002` | 2 duplicate rows | `process_digital_dept` | pdf | environmental_disclosure | `disclosure`, `short_pdf` | `needs_owner_review_for_separate_kb` | no | `2025_中车长春轨道客车_环境信息依法披露临时报告1.pdf`，当前 KB 仍不包含环境披露任务 |
| `S4-CORPUS-MONITOR-003` | 2 duplicate rows | `craft_dept` | pdf | environmental_monitoring | `monitoring_report`, `large_pdf`, `tables_possible` | `needs_owner_review_for_separate_kb` | no | `2025_中车长春轨道客车_监测报告.pdf`，大 PDF 有解析价值，但范围仍需审批 |

---

## 4. 是否满足 S4-P0 通过条件

| 条件 | 当前结果 | 是否通过 |
|---|---:|---|
| 至少 10 个候选文档获得 `approve_current_kb` 或 `approve_separate_kb` | 0 | 否 |
| 至少覆盖 2 个 KB | 当前 indexed 覆盖 2 个，但新增候选未获批 | 否 |
| 至少包含 3 种文档复杂度标签 | pending 候选具备复杂度，但未获批 | 否 |
| PDF 样本不能只有当前 1 个 indexed PDF | 仍只有 1 个 indexed PDF | 否 |
| owner 明确批准当前 KB 范围 | 未批准 | 否 |

S4-P0 原始判定：

```text
historical_s4_p0_status = blocked_needs_owner_approved_corpus
historical_ready_for_s4_p1_import = false
```

Owner 批准后当前判定：

```text
s4_p0_status = completed_owner_approved_corpus
s4_p1_status = import_index_complete_with_pdf_diversity_gap
ready_for_s4_p2_bc_probe = true
ready_for_s4_p3_expression_gap_draft = true
pdf_diversity_gate = pending
```

---

## 9. Owner 批准后的 S4-P1 导入索引结果

批准批次：

- `S4-LOCAL-A-001..005`: 5 个本地 AIOps Markdown runbook。
- `S4-ARCHIVE-B-001..005`: 5 个 Prometheus/Kubernetes runbook 压缩包内 Markdown。

导入索引产物：

| 产物 | 路径 |
|---|---|
| 受控原始目录 | `原始文件/10_清单4_query_rewrite_corpus/` |
| S4-P1 manifest | `data/knowledge_ingestion/checklist4_s4_p1/original_files_manifest.json` |
| S4-P1 review TSV | `data/knowledge_ingestion/checklist4_s4_p1/original_files_manifest_review.tsv` |
| S4-P1 indexed inventory | `data/knowledge_ingestion/checklist4_s4_p1/indexed_corpus_inventory_20260609.json` |
| 当前 import state | `data/knowledge_ingestion/current_import_state.json` |

结果：

```text
new_indexed_documents = 10
total_indexed_documents = 13
indexed_kb_count = 2
indexed_pdf_count = 1
artifact_missing_count = 0
source_ref_resolvable = true
```

说明：

- S4-P1 的 `10+ indexed` 语料扩充目标已达到。
- 本批新增语料都是 Markdown，所以 PDF 多样性 gate 仍 pending。
- Query Rewrite / hybrid / rerank 默认配置仍未启用。

---

## 5. 推荐补充语料结构

为了让 hybrid / rerank / expression-gap eval 更像真实场景，建议新增语料不要只补同一类 PDF。

推荐目标结构：

| 类别 | 建议数量 | 目的 |
|---|---:|---|
| oncall runbook / SOP | 3-4 | 构造真实故障、告警、升级、排障表达 |
| craft 工艺/现场设备文档 | 3-4 | 构造工艺部 scope、现场设备、PDF page/table 引用 |
| process_digital 数字化/平台文档 | 2-3 | 构造相似术语、数字化平台、API/SSE/MCP 等表达 |
| PDF / DOCX / XLSX 混合格式 | 3+ | 验证 artifact/source_ref 和表格/页码 |
| 近邻术语文档 | 2+ | 专门测试 scope 锁定和 rerank 是否乱排 |

最低补充：

```text
existing_indexed = 3
minimum_new_approved_docs_needed = 7
recommended_new_docs = 10 to 12
```

---

## 6. 下一步候选来源

可以走两条路：

### 路径 A：补当前 KB 范围内的 oncall/craft/process_digital 文档

推荐。

要求：

- owner 明确这些文件属于当前助手职责范围。
- 每个文件指定 `kb_id`。
- 每个文件有权限边界。
- 文件内容能支持后续 expression-gap 或 B/C benefit 样本。

### 路径 B：把环保/合规/监测资料作为独立 KB

仅在 owner 明确批准时可走。

要求：

- 新建或明确 `environmental_compliance` 类 KB 边界。
- 单独设计 permission/scope eval。
- 不把这些资料混入当前 oncall/craft baseline。
- 不把环境资料上的收益外推到当前生产 oncall 场景。

---

## 7. 不能做的事

当前不能：

- 直接执行 import。
- 把 12 条 manifest rows 当成 12 个独立文档。
- 把 6 个环保/合规/监测唯一 PDF 当成当前 KB 补充语料。
- 为了凑够 10+，把同一 PDF 拆成多个“文档”。
- 在没有新 corpus 的情况下重跑 B/C 并期待不同结论。
- 启用 `rag_query_rewrite_mode`。

---

## 8. 给小白解释

现在像是在准备一场更靠谱的考试。

以前只有 3 本参考书，题目再怎么设计，也很容易“碰巧都答对”。这不能证明搜索系统长期真的强。

现在盘点了一下书架：

- 已经放进知识库的书：3 本。
- 书架旁边还有 6 本候选 PDF，但它们主要是环保、合规、监测资料。
- 这些资料之前已经说过不属于当前助手的本职考核范围。

所以不能偷偷把它们塞进当前考卷里凑数。

正确做法是：

1. 找到或批准 7 本以上更合适的新资料。
2. 明确每本资料属于哪个部门、哪个知识库。
3. 再导入、解析、索引。
4. 然后重新设计“搜索增强”和“用户表达不好”的测试题。

这一步的结论不是失败，而是把风险提前拦住了：现在缺的是合适语料，不是马上写 Query Rewrite。
