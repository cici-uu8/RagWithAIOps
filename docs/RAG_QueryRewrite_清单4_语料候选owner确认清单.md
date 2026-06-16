# RAG Query Rewrite 清单 4 语料候选 owner 确认清单

日期：2026-06-09

状态：approved_imported_indexed_with_pdf_diversity_gap

对应清单：

- `docs/RAG_QueryRewrite_语料扩充与表达缺口评测清单4.md`
- `docs/RAG_QueryRewrite_清单4_语料候选review矩阵.md`

---

## 0. 结论

本轮从本地文件和本地资产数据库中找到了 7+ 个更适合当前阶段的候选。Owner 已批准其中 10 个进入 S4-P1 reviewed import / index，并已完成导入索引。

推荐先批准一批 `process_digital_dept` / oncall 运维类文档，原因是：

- 它们和当前助手的 oncall / AIOps / 运维排障能力直接相关。
- 它们能制造更丰富的 expression-gap 样本，例如口语化故障描述、缩写、中英混用、症状不含标准术语。
- 它们比环保/合规/监测 PDF 更符合当前 KB 范围。
- 当前本地已经有 5 个 Markdown runbook 和 1 个 Prometheus runbook 压缩包，不需要马上依赖外网。

Owner 批准范围：

```text
approve_import_batch = S4-LOCAL-A + S4-ARCHIVE-B selected 5
target_new_docs = 10
target_kb_id = process_digital_dept
rag_query_rewrite_mode = off
```

执行结果：

```text
s4_p1_status = import_index_complete_with_pdf_diversity_gap
new_indexed_documents = 10
total_indexed_documents = 13
source_ref_resolvable = true
rag_query_rewrite_mode = off
rag_default_retrieval_mode = dense_only
rerank_enabled = false
```

注意：本批 10 个新增文档均为 Markdown runbook，因此满足 `10+ indexed` 语料扩充最低门槛，但不满足 `indexed_pdf_count >= 2` 的 PDF 多样性门槛。

---

## 1. 当前不能再用的候选

以下资料继续排除出当前 KB，除非你明确批准一个新的独立 KB 范围：

- 温室气体排放报告
- 友商合规承诺书
- 土壤地下水自行监测方案
- 环境信息依法披露临时报告
- 监测报告

原因：它们属于环保、合规、监测域，不适合作为当前 oncall / craft / process_digital 的检索增强证据。

---

## 2. 推荐批准候选 A：本地 Markdown runbooks

这些文件已经在本地存在，可以作为第一批候选。

| candidate_id | source_path | proposed_kb_id | domain_fit | complexity_tags | owner_decision | import_ready | 推荐 |
|---|---|---|---|---|---|---|---|
| `S4-LOCAL-A-001` | `aiops-docs/cpu_high_usage.md` | `process_digital_dept` | oncall / aiops | `runbook`, `cpu`, `query_logs`, `expression_gap_seed` | `approve_current_kb_imported` | indexed | 是 |
| `S4-LOCAL-A-002` | `aiops-docs/memory_high_usage.md` | `process_digital_dept` | oncall / aiops | `runbook`, `memory`, `oom`, `jvm`, `expression_gap_seed` | `approve_current_kb_imported` | indexed | 是 |
| `S4-LOCAL-A-003` | `aiops-docs/disk_high_usage.md` | `process_digital_dept` | oncall / aiops | `runbook`, `disk`, `filesystem`, `commands`, `expression_gap_seed` | `approve_current_kb_imported` | indexed | 是 |
| `S4-LOCAL-A-004` | `aiops-docs/service_unavailable.md` | `process_digital_dept` | oncall / aiops | `runbook`, `service_down`, `dependency`, `escalation`, `expression_gap_seed` | `approve_current_kb_imported` | indexed | 是 |
| `S4-LOCAL-A-005` | `aiops-docs/slow_response.md` | `process_digital_dept` | oncall / aiops | `runbook`, `latency`, `slow_query`, `api_timeout`, `expression_gap_seed` | `approve_current_kb_imported` | indexed | 是 |

适合产生的 expression-gap：

- “服务卡死了怎么办”
- “页面一直转圈”
- “接口慢是数据库问题吗”
- “机器快满了怎么查”
- “内存爆了要先重启吗”

---

## 3. 推荐批准候选 B：Prometheus / Kubernetes runbook 压缩包

来源：

```text
原始文件/05_调研记录/downloaded_archives/prometheus-operator-runbooks-main.zip
```

该压缩包本地存在，包含 Kubernetes、Node、Prometheus、Alertmanager、etcd 等大量 runbook。建议先选 5-8 个最贴近 oncall 的文档，解包后再导入。

| candidate_id | archive_internal_path | proposed_kb_id | domain_fit | complexity_tags | owner_decision | import_ready | 推荐 |
|---|---|---|---|---|---|---|---|
| `S4-ARCHIVE-B-001` | `runbooks-main/content/runbooks/kubernetes/KubePodCrashLooping.md` | `process_digital_dept` | oncall / k8s | `runbook`, `crashloop`, `pod`, `symptom_query` | `approve_current_kb_imported` | indexed | 是 |
| `S4-ARCHIVE-B-002` | `runbooks-main/content/runbooks/kubernetes/KubePodNotReady.md` | `process_digital_dept` | oncall / k8s | `runbook`, `pod_not_ready`, `readiness`, `scope_seed` | `approve_current_kb_imported` | indexed | 是 |
| `S4-ARCHIVE-B-003` | `runbooks-main/content/runbooks/kubernetes/KubeNodeNotReady.md` | `process_digital_dept` | oncall / k8s | `runbook`, `node_not_ready`, `node`, `symptom_query` | `approve_current_kb_imported` | indexed | 是 |
| `S4-ARCHIVE-B-004` | `runbooks-main/content/runbooks/kubernetes/CPUThrottlingHigh.md` | `process_digital_dept` | oncall / k8s | `runbook`, `cpu_throttling`, `k8s`, `acronym_seed` | `approve_current_kb_imported` | indexed | 是 |
| `S4-ARCHIVE-B-005` | `runbooks-main/content/runbooks/kubernetes/KubePersistentVolumeFillingUp.md` | `process_digital_dept` | oncall / k8s | `runbook`, `storage`, `pv`, `disk`, `acronym_seed` | `approve_current_kb_imported` | indexed | 是 |
| `S4-ARCHIVE-B-006` | `runbooks-main/content/runbooks/kubernetes/KubeDeploymentReplicasMismatch.md` | `process_digital_dept` | oncall / k8s | `runbook`, `deployment`, `replica`, `rollout` | `pending_owner_confirmation` | extract_then_yes | 备选 |
| `S4-ARCHIVE-B-007` | `runbooks-main/content/runbooks/prometheus/PrometheusTargetSyncFailure.md` | `process_digital_dept` | oncall / monitoring | `runbook`, `prometheus`, `target_sync`, `mixed_cn_en_seed` | `pending_owner_confirmation` | extract_then_yes | 备选 |
| `S4-ARCHIVE-B-008` | `runbooks-main/content/runbooks/alertmanager/AlertmanagerClusterDown.md` | `process_digital_dept` | oncall / alerting | `runbook`, `alertmanager`, `cluster_down`, `mixed_cn_en_seed` | `pending_owner_confirmation` | extract_then_yes | 备选 |

推荐先批准：

```text
S4-ARCHIVE-B-001
S4-ARCHIVE-B-002
S4-ARCHIVE-B-003
S4-ARCHIVE-B-004
S4-ARCHIVE-B-005
```

这样结合 A 组 5 个 Markdown，本轮就能形成 10 个新增候选。

---

## 4. 数据库登记候选 C：有记录但本地文件缺失

来源：`data/knowledge_assets/knowledge_assets.sqlite`

这些条目已经在资产库登记，但当前 `original_path` 对应文件不存在。它们可以作为下一轮“网上补资料”方向，但不建议放进本轮立即导入。

| candidate_id | display_name | original_path | source_kind | status | 建议 |
|---|---|---|---|---|---|
| `S4-DB-C-001` | `data_sync_service_cpu_db_runbook.md` | `原始文件/01_知识库文档/aiops_runbooks/data_sync_service_cpu_db_runbook.md` | unknown | missing_local_file | 如果能找回本地文件，优先级高 |
| `S4-DB-C-002` | `superbiz_incident_postmortems.md` | `原始文件/01_知识库文档/superbiz_incident_postmortems.md` | unknown | missing_local_file | 如果能找回本地文件，适合 expression-gap |
| `S4-DB-C-003` | `safe_database_agent_policy.md` | `原始文件/01_知识库文档/database_safety_governance/safe_database_agent_policy.md` | unknown | missing_local_file | 适合 DB 工具治理，不是首批 RAG rewrite |
| `S4-DB-C-004` | `google_sre_workbook_incident_response.html` | `原始文件/06_skill落地SOP素材/01_incident_response/google_sre_workbook_incident_response.html` | external_sop | missing_local_file | 可网上补，但需记录来源 URL |
| `S4-DB-C-005` | `pagerduty_post_mortem_process.html` | `原始文件/06_skill落地SOP素材/02_sre_oncall_postmortem/pagerduty_post_mortem_process.html` | external_sop | missing_local_file | 可网上补，适合复盘类 query |
| `S4-DB-C-006` | `mcp_security_best_practices.html` | `原始文件/06_skill落地SOP素材/07_agent_tool_governance/mcp_security_best_practices.html` | external_sop | missing_local_file | 可网上补，适合 MCP / tool expression-gap |
| `S4-DB-C-007` | `openai_agents_sdk_tools.html` | `原始文件/06_skill落地SOP素材/07_agent_tool_governance/openai_agents_sdk_tools.html` | external_sop | missing_local_file | 可网上补，适合 tool/governance |
| `S4-DB-C-008` | `openai_agents_sdk_guardrails.html` | `原始文件/06_skill落地SOP素材/07_agent_tool_governance/openai_agents_sdk_guardrails.html` | external_sop | missing_local_file | 可网上补，适合 guardrail |
| `S4-DB-C-009` | `mysql_slow_query_log.html` | `原始文件/06_skill落地SOP素材/05_database_ops/mysql_slow_query_log.html` | external_sop | missing_local_file | 可网上补，适合 slow query |
| `S4-DB-C-010` | `postgresql_explicit_locking.html` | `原始文件/06_skill落地SOP素材/05_database_ops/postgresql_explicit_locking.html` | external_sop | missing_local_file | 可网上补，适合 DB lock |

说明：

- C 组不进入本轮首批 import。
- 如果你希望扩大 DB / tool governance 方向，我再单独做 C 组 online reacquire。
- 所有网上补回的文件都必须记录来源 URL、抓取时间、license/公开性备注。

---

## 5. 不推荐候选

| source_path | 原因 |
|---|---|
| `uploads/documents/default/doc_11ec722a-9962-508f-9c1e-7fa17c1ab5e3/original/x.md` | 2 bytes，占位文件 |
| `uploads/documents/default/doc_a6568874-6c40-5e3b-954b-54d600527764/original/x.md` | 10 bytes，占位文件 |
| `uploads/documents/default/doc_7bb617a1-c86a-5a66-aa70-a886d73b3d47/original/manual.pdf` | 13 bytes，占位/无效 PDF |
| `uploads/documents/guide/doc_85454657-8580-5aea-8101-b4ee326d809c/original/enterprise_guide_runbook.md` | 156 bytes，内容太短，可保留为 smoke，不适合作为复杂 corpus |
| `原始文件/03_日志与告警样例/loghub/*/*.log` | 日志样本适合 AIOps eval，不适合作为当前 RAG 文档 corpus 首批 |
| `原始文件/09_PDF解析基线/多栏版式/N19-1423_bert_pretraining_two_column.pdf` | PDF 解析 baseline，不属于当前业务 KB |

---

## 6. 推荐 owner 批准动作

建议批准以下 10 个新增候选进入 S4-P1：

```text
S4-LOCAL-A-001
S4-LOCAL-A-002
S4-LOCAL-A-003
S4-LOCAL-A-004
S4-LOCAL-A-005
S4-ARCHIVE-B-001
S4-ARCHIVE-B-002
S4-ARCHIVE-B-003
S4-ARCHIVE-B-004
S4-ARCHIVE-B-005
```

建议导入范围：

```text
kb_id = process_digital_dept
import_scope = local_only
source_defaults = unchanged
rag_query_rewrite_mode = off
rag_default_retrieval_mode = dense_only
rerank_enabled = false
```

已执行：

1. 将 A 组 Markdown 复制到受控原始文件目录或直接登记 manifest。
2. 从 Prometheus runbook zip 中只解出 B 组批准文件。
3. 生成清单 4 S4-P1 manifest。
4. 执行 reviewed import / index。
5. 复核 `current_import_state.json` 达到 `10+ indexed`。
6. 生成 indexed corpus inventory。

后续：

1. 基于 13 个 indexed 文档重新设计 B/C probe。
2. 设计 expression-gap 候选样本草案。
3. 继续保持 `rag_query_rewrite_mode=off`、`rag_default_retrieval_mode=dense_only`、`rerank_enabled=false`。
4. 如需关闭 PDF 多样性 gate，另行批准更多 in-scope PDF。

---

## 7. 给小白解释

现在我们不是马上把资料塞进知识库。

我们先把“书单”列出来，让你确认哪些书能进考场。

这次找到了两类好书：

- 本地已经有的 5 本运维故障处理手册。
- 一个 Prometheus/Kubernetes runbook 压缩包，里面有很多真实告警处理文档。

如果你批准其中 10 个，我们就能把知识库从 3 本扩到 13 本左右。这样再测试 hybrid、rerank、Query Rewrite，才不会像只拿 3 本书硬凑考试。

Query Rewrite 现在仍然不打开。先扩语料，再测“用户说得不标准”的问题。
