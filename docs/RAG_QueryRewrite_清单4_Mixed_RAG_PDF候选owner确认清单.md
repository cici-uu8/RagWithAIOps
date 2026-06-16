# RAG Query Rewrite 清单 4 Mixed RAG PDF 候选 owner 确认清单

日期：2026-06-10

状态：pdf_candidate_inventory_done_pending_owner_review

对应清单：

- `docs/RAG_QueryRewrite_语料扩充与表达缺口评测清单4.md`
- `docs/RAG_QueryRewrite_清单4_Mixed_RAG评测体系设计.md`

---

## 0. 结论

本轮只做 PDF 候选盘点，不导入、不索引、不下载大文件、不创建 mixed 50q evalset。

当前 S4-P1.5 readiness 阻塞点是：

```text
indexed_pdf_count = 1
target_indexed_pdf_count >= 5
next_required = approve_and_index_4plus_in_scope_pdfs
```

本轮找到 9 个首批推荐网络 PDF 候选，均来自 AWS 或 Red Hat 官方文档，主题覆盖 oncall / AIOps / Kubernetes / monitoring / reliability / operations。它们足够支撑 owner 从中选择 4+ 个进入 reviewed import/index。

当前动作应暂停在：

```text
owner_decision = pending_owner_confirmation
import_index = not_started
rag_default_retrieval_mode = dense_only
rag_query_rewrite_mode = off
rerank_enabled = false
```

你可以继续补充更多 PDF。等 owner 明确批准后，再进入受控下载、manifest、reviewed import/index、readiness 复跑。

---

## 1. 本轮查找范围

本地只读检查：

- `原始文件/`
- `uploads/documents/`
- `data/knowledge_assets/knowledge_assets.sqlite`
- `原始文件/06_网络获取文档/oncall_sre_guides/download_list.md`

网络只读检查：

- 对候选 URL 做 `curl -I` 或 range 请求验证。
- 只验证 URL 可达性、`Content-Type`、`Content-Length` 或 `%PDF-` 文件头。
- 没有把网络 PDF 下载进项目受控目录。

---

## 2. 首批推荐候选 A：官方 PDF，可进入 owner review

这些候选都不应自动导入。它们只是建议 owner 审核的候选池。

| candidate_id | title | source_url | proposed_kb_id | domain_fit | complexity_tags | verified_signal | local_status | owner_decision | recommendation |
|---|---|---|---|---|---|---|---|---|---|
| `S4-PDF-WEB-A-001` | AWS Operational Excellence Pillar | `https://docs.aws.amazon.com/pdfs/wellarchitected/latest/operational-excellence-pillar/wellarchitected-operational-excellence-pillar.pdf` | `process_digital_dept` | oncall / operations | `pdf`, `ops_governance`, `incident_process`, `long_doc` | `HTTP 200`, `application/pdf`, `2816812 bytes` | not_downloaded | pending_owner_confirmation | high |
| `S4-PDF-WEB-A-002` | AWS Reliability Pillar | `https://docs.aws.amazon.com/pdfs/wellarchitected/latest/reliability-pillar/wellarchitected-reliability-pillar.pdf` | `process_digital_dept` | reliability / platform_ops | `pdf`, `resilience`, `failure_recovery`, `long_doc` | `HTTP 200`, `application/pdf`, `7094117 bytes` | not_downloaded | pending_owner_confirmation | high |
| `S4-PDF-WEB-A-003` | AWS EKS User Guide | `https://docs.aws.amazon.com/pdfs/eks/latest/userguide/eks-ug.pdf` | `process_digital_dept` | k8s / platform_ops | `pdf`, `kubernetes`, `eks`, `long_doc`, `mixed_cn_en_seed` | `HTTP 200`, `application/pdf`, `28262376 bytes` | not_downloaded | pending_owner_confirmation | high |
| `S4-PDF-WEB-A-004` | AWS Systems Manager User Guide | `https://docs.aws.amazon.com/pdfs/systems-manager/latest/userguide/systems-manager-ug.pdf` | `process_digital_dept` | operations / automation | `pdf`, `run_command`, `ops_automation`, `long_doc` | `HTTP 200`, `application/pdf`, `28329779 bytes` | not_downloaded | pending_owner_confirmation | medium |
| `S4-PDF-WEB-A-005` | AWS Well-Architected Framework | `https://docs.aws.amazon.com/pdfs/wellarchitected/latest/framework/wellarchitected-framework.pdf` | `process_digital_dept` | architecture / operations | `pdf`, `framework`, `reliability`, `operations`, `long_doc` | `HTTP 200`, `application/pdf`, `14190902 bytes` | not_downloaded | pending_owner_confirmation | medium |
| `S4-PDF-WEB-A-006` | Red Hat OpenShift Monitoring 4.15 | `https://docs.redhat.com/en/documentation/openshift_container_platform/4.15/pdf/monitoring/OpenShift_Container_Platform-4.15-Monitoring-en-US.pdf` | `process_digital_dept` | k8s / monitoring | `pdf`, `openshift`, `monitoring`, `alerting`, `long_doc` | `%PDF-` header verified, `application/pdf` | not_downloaded | pending_owner_confirmation | high |
| `S4-PDF-WEB-A-007` | Red Hat OpenShift Logging 4.15 | `https://docs.redhat.com/en/documentation/openshift_container_platform/4.15/pdf/logging/OpenShift_Container_Platform-4.15-Logging-en-US.pdf` | `process_digital_dept` | k8s / logging | `pdf`, `openshift`, `logging`, `troubleshooting`, `long_doc` | `%PDF-` header verified, `application/pdf` | not_downloaded | pending_owner_confirmation | high |
| `S4-PDF-WEB-A-008` | Red Hat OpenShift Nodes 4.15 | `https://docs.redhat.com/en/documentation/openshift_container_platform/4.15/pdf/nodes/OpenShift_Container_Platform-4.15-Nodes-en-US.pdf` | `process_digital_dept` | k8s / node_ops | `pdf`, `openshift`, `node`, `scheduling`, `long_doc` | `%PDF-` header verified, `application/pdf` | not_downloaded | pending_owner_confirmation | medium |
| `S4-PDF-WEB-A-009` | Red Hat OpenShift Backup and Restore 4.15 | `https://docs.redhat.com/en/documentation/openshift_container_platform/4.15/pdf/backup_and_restore/OpenShift_Container_Platform-4.15-Backup_and_restore-en-US.pdf` | `process_digital_dept` | k8s / recovery | `pdf`, `openshift`, `backup_restore`, `recovery`, `long_doc` | `%PDF-` header verified, `application/pdf` | not_downloaded | pending_owner_confirmation | medium |

建议首批优先选择：

```text
S4-PDF-WEB-A-001
S4-PDF-WEB-A-002
S4-PDF-WEB-A-003
S4-PDF-WEB-A-006
S4-PDF-WEB-A-007
```

原因：

- 覆盖 operations / reliability / Kubernetes / monitoring / logging 五个不同运维面。
- 能和已 indexed 的 Markdown runbook 构成 mixed Markdown+PDF corpus。
- 比只导入同一来源或同一主题的 PDF 更能降低评测偏差。

---

## 3. 备选候选 B：可二次确认或 HTML 转 PDF

这些资料与 oncall/SRE 有关，但本轮没有形成首批 import-ready PDF 结论。

| candidate_id | title | source | status | reason | recommendation |
|---|---|---|---|---|---|
| `S4-PDF-WEB-B-001` | Google SRE Book | `https://sre.google/sre-book/` | url_needs_recheck_or_html_to_pdf | PDF 请求在本轮超时，HTML 官方页面可读 | 备选 |
| `S4-PDF-WEB-B-002` | Google SRE Workbook - Incident Response | `https://sre.google/workbook/incident-response/` | html_to_pdf_candidate | 官方 HTML，不是本轮已验证 PDF | 备选 |
| `S4-PDF-WEB-B-003` | PagerDuty Incident Response Guide | `https://response.pagerduty.com/` | html_to_pdf_candidate | 官方 HTML，可转 PDF 但需记录转换过程 | 备选 |
| `S4-PDF-WEB-B-004` | Prometheus Best Practices | `https://prometheus.io/docs/practices/` | html_to_pdf_candidate | 官方 HTML，可转 PDF；已有 Markdown runbook 覆盖一部分监控场景 | 备选 |
| `S4-PDF-WEB-B-005` | PostgreSQL Performance Tips | `https://www.postgresql.org/docs/current/performance-tips.html` | html_to_pdf_candidate | 官方 HTML，更偏数据库运维；可作为后续 DB RAG eval | 备选 |

如果使用 B 组，需要额外记录：

- 抓取时间。
- 原始 URL。
- HTML 转 PDF 工具和版本。
- 转换后的页数、文本抽取质量、source_ref 是否可定位。

---

## 4. 本地 PDF 检查结果

本地 PDF 里没有足够多的可直接进入当前 mixed RAG baseline 的新增 in-scope PDF。

| source_path | status | reason | decision |
|---|---|---|---|
| `uploads/documents/craft_dept/doc_27b282ca-97c3-5170-af0a-282f2e9122a1/original/线上故障处理_现场设备工艺版.pdf` | already_indexed | 当前唯一 indexed PDF，不能重复计入新增 PDF coverage | keep_as_existing_baseline |
| `uploads/documents/default/doc_7bb617a1-c86a-5a66-aa70-a886d73b3d47/original/manual.pdf` | invalid_placeholder | 13 bytes，占位/无效 PDF | reject_current_kb |
| `原始文件/09_PDF解析基线/多栏版式/N19-1423_bert_pretraining_two_column.pdf` | parser_baseline_only | BERT 论文，适合 PDF parser 压测，不属于 oncall / craft / process_digital 业务 KB | reject_current_kb |
| `原始文件/05_调研记录/crrc_changchun_20260603/downloads/*.pdf` | out_of_scope_current_kb | 环保、合规、监测、披露类材料，不适合当前 oncall/process_digital mixed RAG baseline | reject_current_kb_unless_separate_scope |
| `原始文件/08_长客真实资料/crrc_changchun_20260603/downloads/*.pdf` | duplicate_out_of_scope_current_kb | 与 `05_调研记录` 中 CRRC PDF 重复或同域 | reject_current_kb_unless_separate_scope |

---

## 5. Owner review 建议

建议你接下来做两件事：

1. 从 A 组先批准 4-6 个 PDF。
2. 继续补充你自己找到的 PDF，我再合并到这个候选池里。

建议批准口径：

```text
approve_for_reviewed_import = yes/no
target_kb_id = process_digital_dept
source_kind = public_official_pdf
import_scope = local_reviewed_only
download_to = 原始文件/11_清单4_mixed_pdf_corpus/
defaults_locked = dense_only / rewrite_off / rerank_false
```

批准后才做：

1. 下载批准的 PDF 到受控原始文件目录。
2. 生成 PDF manifest / review TSV。
3. 执行 reviewed import / index。
4. 复跑 `checklist4_mixed_rag_eval_readiness_report.py`。
5. 若 `indexed_pdf_count >= 5` 且 artifact/source_ref 健康，再设计 mixed 50q evalset。

---

## 6. 给小白解释

现在不是把 PDF 立刻塞进知识库。

我们是在给评测考试选“教材”。以前教材里只有 1 份 PDF，太少了；如果拿它出 15 道 PDF 题，就像一本书反复出题，测不出系统处理不同 PDF 的能力。

所以这次先找了一批更像真实工作的 PDF：云平台运维、可靠性、Kubernetes、监控、日志。你先挑哪些能进这个项目的知识库，我再去下载、登记、导入、索引。

在你确认前，系统默认搜索方式不变，Query Rewrite 不打开，rerank 也不打开。
