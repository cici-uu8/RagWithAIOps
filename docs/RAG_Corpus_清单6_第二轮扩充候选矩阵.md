# RAG Corpus 清单6 第二轮扩充候选矩阵

日期：2026-06-11（更新：2026-06-12）

状态：`c6_final_closeout_complete_after_mixed_54q`

C6-P0 候选矩阵已完成 owner review 的第一批收口。C6-P1a 批准并导入 10 个本地文件，28-doc observation-only Mixed 50q baseline 与 18-doc 修复后基线一致。C6-P1b 已补充 Redis high memory 和 MySQL slow query 两个 owner-approved 真实业务 Markdown，当前 corpus 达到 30 indexed docs，正式 Mixed 50q dense-only baseline 保持 41/50 且无样本级退化。C6-P2 已用独立 4q pilot 验证 Redis/MySQL 新文档 dense-only retrieval，结果 4/4 通过。C6-P3 已创建派生 Mixed 54q baseline，结果 45/54，原 50q 样本状态变化为 0。Final closeout 已记录在 `docs/RAG_Corpus_清单6_Final_Closeout.md`。

C6-P0 初始目标：在不改变 RAG 默认配置、不创建新 evalset、不运行 baseline 的前提下，先建立第二轮 corpus 扩充候选池。候选通过 owner review 后，才进入 reviewed import / index。后续 C6-P1/C6-P2 已在 owner approval 后进入 reviewed import、正式 Mixed 50q 复验和独立 Redis/MySQL 4q retrieval pilot。

---

## 1. 当前基线

当前 S4/S5 基线 corpus：

```text
indexed_documents = 18
indexed_markdown = 12
indexed_pdf = 6
parsing_deferred = 1  # AWS IR 827-page long PDF
```

目标 corpus：

```text
target_indexed_documents = 30-50
target_indexed_markdown = 20-30
target_indexed_pdf = 10-20
```

因此至少需要新增：

```text
min_new_indexed_documents = 12
preferred_new_markdown = 8-18
preferred_new_pdf = 4-14
```

---

## 2. 本轮边界

本文件是 review-only 候选矩阵。

本轮不做：

- 不导入文档
- 不 index 文档
- 不创建新 evalset
- 不运行 retrieval baseline
- 不运行 answer baseline
- 不调用 LLM
- 不修改 `rag_default_retrieval_mode`
- 不修改 `rag_query_rewrite_mode`
- 不修改 `rerank_enabled`

默认配置继续保持：

```text
rag_default_retrieval_mode = dense_only
rag_query_rewrite_mode = off
rerank_enabled = false
```

---

## 3. 候选进入 reviewed import 的条件

每个候选进入 import/index 前必须满足：

| 条件 | 要求 |
|---|---|
| owner approval | owner 明确批准 `kb_id`、scope、权限边界和导入用途 |
| source control | 文件复制到受控原始文件目录，例如 `原始文件/12_清单6_corpus_expansion_round2/` |
| no duplicate | 不重复当前 18 个 indexed 文档 |
| scope fit | 属于 oncall / craft / process / monitoring / incident response / SRE ops |
| safety | 不包含 secret、账号、token、生产敏感配置、个人隐私 |
| format validity | PDF 可打开；MD/TXT 可解析；DOCX/XLSX 需先通过解析能力检查 |
| artifact expectation | PDF 需要能生成 source_ref/page/table 或明确标记为 non-table PDF |
| eval value | 能产生真实 query、故障处理、流程决策、权限/scope 或引用测试价值 |

---

## 4. 已在当前 corpus 中的文档（不重复导入）

这些文档已经属于当前 baseline，不作为 C6 新增候选重复导入：

| status | format | kb_id | file_name |
|---|---|---|---|
| indexed | pdf | craft_dept | 线上故障处理_现场设备工艺版.pdf |
| indexed | md | process_digital_dept | 2024_人民网聚焦中车长客数字化转型成果.md |
| indexed | md | process_digital_dept | CPUThrottlingHigh.md |
| indexed | md | process_digital_dept | KubeNodeNotReady.md |
| indexed | md | process_digital_dept | KubePersistentVolumeFillingUp.md |
| indexed | md | process_digital_dept | KubePodCrashLooping.md |
| indexed | md | process_digital_dept | KubePodNotReady.md |
| indexed | md | process_digital_dept | cpu_high_usage.md |
| indexed | md | process_digital_dept | disk_high_usage.md |
| indexed | pdf | process_digital_dept | github_repo_6_scoutflo_sre_playbooks.pdf |
| indexed | md | process_digital_dept | memory_high_usage.md |
| indexed | pdf | process_digital_dept | online_handbook_1_pagerduty_incident_response_documentation.pdf |
| indexed | pdf | process_digital_dept | pdf_2__un_reliability_budgets.pdf |
| indexed | pdf | process_digital_dept | pdf_3_capacity_planning.pdf |
| indexed | pdf | process_digital_dept | pdf_7_systems_performance__enterprise_and_the_cloud___cp.pdf |
| indexed | md | process_digital_dept | service_unavailable.md |
| indexed | md | process_digital_dept | slow_response.md |
| indexed | md | process_digital_dept | superbiz_oncall_handbook.md |
| parsing | pdf | process_digital_dept | github_repo_5_aws_incident_response_runbooks.pdf |

AWS IR 827-page PDF 仍按 long-PDF/stress-eval 处理，不计入 C6 第一批 readiness。

---

## 5. 候选矩阵总览

| 来源类型 | 候选数 | 当前状态 | 说明 |
|---|---:|---|---|
| A. 本地已有文件 | 14 | 待 owner review | 有文件，但部分 scope 需要重新确认 |
| B. Owner 待提供真实业务文档 | 20 | 待 owner 提供 | 最符合“真实 oncall/craft/process”目标 |
| C. 网络公开资料待获取/转换 | 16 | 待 fetch/review | 只能补充通用 SRE/monitoring，不替代内部真实文档 |
| 合计 | 50 | review-only | 不代表可直接导入 |

推荐第一批 owner review 目标：从 A/B/C 中选 12-18 个高质量候选，优先保证新增 8-12 个 Markdown 和 4-6 个 PDF。

---

## 6. A 组：本地已有待审候选

| candidate_id | source_file | kb_id | format | priority | coverage | current_readiness | owner_approved | notes |
|---|---|---|---|---|---|---|---|---|
| C6-LOCAL-PDF-001 | `原始文件/08_长客真实资料/crrc_changchun_20260603/downloads/2024_中车长春轨道客车_土壤地下水自行监测方案.pdf` | craft_dept | pdf | P1 | craft / monitoring / compliance | local_file_exists | pending | 真实企业资料；需确认是否纳入 craft KB，而不是环境合规专项 KB |
| C6-LOCAL-PDF-002 | `原始文件/08_长客真实资料/crrc_changchun_20260603/downloads/2025_中车长春轨道客车_土壤地下水自行监测方案.pdf` | craft_dept | pdf | P1 | craft / monitoring / compliance | local_file_exists | pending | 与 2024 版本可构成版本对比；需防止过期内容混用 |
| C6-LOCAL-PDF-003 | `原始文件/08_长客真实资料/crrc_changchun_20260603/downloads/2025_中车长春轨道客车_监测报告.pdf` | craft_dept | pdf | P1 | monitoring report | local_file_exists | pending | 有表格/数据抽取价值；需确认是否允许进入当前 KB |
| C6-LOCAL-PDF-004 | `原始文件/08_长客真实资料/crrc_changchun_20260603/downloads/2025_中车长春轨道客车_环境信息依法披露临时报告1.pdf` | craft_dept | pdf | P2 | incident / disclosure | local_file_exists | pending | 更偏合规披露，评测价值需 owner 确认 |
| C6-LOCAL-PDF-005 | `原始文件/08_长客真实资料/crrc_changchun_20260603/downloads/2021_中车长春轨道客车_温室气体排放报告.pdf` | craft_dept | pdf | P2 | environmental report | local_file_exists | pending | 可能偏离 oncall，建议仅在 craft/compliance scope 批准后导入 |
| C6-LOCAL-PDF-006 | `原始文件/08_长客真实资料/crrc_changchun_20260603/downloads/2023_中车长春轨道客车_友商合规承诺书中英对照.pdf` | craft_dept | pdf | P2 | compliance / bilingual | local_file_exists | pending | 双语文档可测跨语言，但不是 oncall 主线 |
| C6-LOCAL-PDF-007 | `原始文件/06_网络获取文档/oncall_sre_guides/github_repo_5_aws_incident_response_runbooks.pdf` | process_digital_dept | pdf | P2 | incident response / long PDF | parsing_deferred | pending | 已在 S4 导入后仍 parsing；作为 long-PDF stress candidate，不进第一批 readiness |
| C6-LOCAL-PDF-008 | `原始文件/06_网络获取文档/oncall_sre_guides/Official PDF Documentation_4_postgresql_16_official_documentation__a4_pdf_.pdf` | process_digital_dept | pdf | P2 | database reference | local_file_exists | pending | 3040 页，建议单独 DB/reference KB；不建议进入第一批 mixed RAG baseline |
| C6-LOCAL-MD-001 | `docs/aiops_真实模拟执行清单.md` | process_digital_dept | md | P1 | AIOps scenario / smoke | local_file_exists | pending | 内部 AIOps 场景文档，可测故障链路但需确认是否可作为用户 KB |
| C6-LOCAL-MD-002 | `aiops_lab/README.md` | process_digital_dept | md | P1 | AIOps lab operations | local_file_exists | pending | 运维实验环境说明，适合 agent behavior 前置语料 |
| C6-LOCAL-MD-003 | `mcp_servers/README.md` | process_digital_dept | md | P2 | MCP tools / ops | local_file_exists | pending | 更偏系统操作，不是业务 oncall；owner 需确认 |
| C6-LOCAL-MD-004 | `docs/数据库操作能力.md` | process_digital_dept | md | P1 | database operations | local_file_exists | pending | 若下一阶段覆盖 DB ops，可作为 oncall/DB 安全查询语料 |
| C6-LOCAL-MD-005 | `docs/数据库操作能力执行步骤清单.md` | process_digital_dept | md | P1 | database SOP | local_file_exists | pending | SOP 结构适合 answer eval；需确认不会混入开发计划噪声 |
| C6-LOCAL-MD-006 | `docs/enterprise_sse_event_contract.md` | process_digital_dept | md | P2 | runtime event contract | local_file_exists | pending | 更偏系统 contract；可作为 agent behavior 语料，不建议优先 |

---

## 7. B 组：Owner 待提供真实业务文档候选

这组是清单6最有价值的候选。当前未发现这些文件已经在本地受控目录中，因此状态是 `source_request_pending`。它们应由业务 owner 提供或确认已有位置。

| candidate_id | requested_document | kb_id | format | priority | coverage | current_readiness | owner_approved | notes |
|---|---|---|---|---|---|---|---|---|
| C6-SRC-MD-001 | Redis high memory runbook | process_digital_dept | md | P0 | Redis / memory / oncall | source_request_pending | pending | 补足 Redis 场景，适合 expression-gap 和 troubleshooting |
| C6-SRC-MD-002 | Redis queue backlog runbook | process_digital_dept | md | P0 | Redis / queue / backlog | source_request_pending | pending | 对齐 AIOps RedisQueueBacklog 场景 |
| C6-SRC-MD-003 | MySQL slow query runbook | process_digital_dept | md | P0 | MySQL / DBSlowQuery | source_request_pending | pending | 对齐 AIOps DBSlowQuery 场景 |
| C6-SRC-MD-004 | MySQL connection saturation runbook | process_digital_dept | md | P0 | MySQL / connection pool | source_request_pending | pending | 常见 oncall 语料 |
| C6-SRC-MD-005 | API 5xx spike runbook | process_digital_dept | md | P0 | service / API / 5xx | source_request_pending | pending | 补充 slow_response / unavailable 之外的 API 错误 |
| C6-SRC-MD-006 | Gateway 502/504 runbook | process_digital_dept | md | P0 | gateway / Nginx / timeout | source_request_pending | pending | 易产生真实口语 query |
| C6-SRC-MD-007 | Kafka consumer lag runbook | process_digital_dept | md | P0 | Kafka / lag | source_request_pending | pending | 当前 corpus 缺消息队列 |
| C6-SRC-MD-008 | Kubernetes ImagePullBackOff runbook | process_digital_dept | md | P0 | K8s / image pull | source_request_pending | pending | 与现有 K8s runbook 互补 |
| C6-SRC-MD-009 | Kubernetes OOMKilled runbook | process_digital_dept | md | P0 | K8s / memory / restart | source_request_pending | pending | 与 memory_high_usage / CrashLoop 互补 |
| C6-SRC-MD-010 | Kubernetes DNS failure runbook | process_digital_dept | md | P1 | K8s / DNS / networking | source_request_pending | pending | 补网络类故障 |
| C6-SRC-MD-011 | Node disk pressure runbook | process_digital_dept | md | P1 | K8s / node / disk | source_request_pending | pending | 与 disk_high_usage 区分节点层 |
| C6-SRC-MD-012 | Certificate expiry runbook | process_digital_dept | md | P1 | TLS / certificate | source_request_pending | pending | 真实 oncall 常见；适合 date/expiry query |
| C6-SRC-MD-013 | Login/auth failure runbook | process_digital_dept | md | P1 | auth / SSO / permission | source_request_pending | pending | 可扩 permission/scope eval |
| C6-SRC-MD-014 | Deployment rollback SOP | process_digital_dept | md | P1 | deploy / rollback | source_request_pending | pending | 适合 answer layer 流程题 |
| C6-SRC-MD-015 | Incident severity classification SOP | process_digital_dept | md | P1 | incident / severity | source_request_pending | pending | 补 incident process |
| C6-SRC-MD-016 | Oncall escalation SOP | process_digital_dept | md | P1 | escalation / oncall | source_request_pending | pending | 可测 agent 行为层流程 |
| C6-SRC-PDF-001 | 工艺设备点检手册 | craft_dept | pdf | P0 | craft / inspection | source_request_pending | pending | 真实 craft PDF，优先级高 |
| C6-SRC-PDF-002 | 现场设备停机应急处理手册 | craft_dept | pdf | P0 | craft / incident response | source_request_pending | pending | 与现有工艺版 PDF 互补 |
| C6-SRC-PDF-003 | 设备维护保养 SOP | craft_dept | pdf | P1 | craft / maintenance | source_request_pending | pending | 适合 table/page/source_ref eval |
| C6-SRC-XLSX-001 | 设备巡检记录样表 | craft_dept | xlsx | P2 | craft / inspection table | source_request_pending | pending | XLSX 需先验证解析链路；暂不进第一批 |

---

## 8. C 组：网络公开资料待获取/转换候选

这组只能作为通用 SRE / monitoring 补充，不替代内部真实文档。进入 import 前必须完成来源 URL、许可、下载 hash、格式有效性和 owner scope 审核。若后续长期拿不到真实 Redis/MySQL runbook，才可另开 `C6-P1c public_reference_supplement`；它只能作为补充语料，不能用来证明业务 corpus 已经成熟。

| candidate_id | requested_document | kb_id | format | priority | coverage | current_readiness | owner_approved | notes |
|---|---|---|---|---|---|---|---|---|
| C6-WEB-MD-001 | Kubernetes Debug Pods guide | process_digital_dept | md | P1 | K8s / pod debugging | fetch_required | pending | 公开 HTML 需转换为受控 MD |
| C6-WEB-MD-002 | Kubernetes Debug Services guide | process_digital_dept | md | P1 | K8s / service networking | fetch_required | pending | 补 service/network 场景 |
| C6-WEB-MD-003 | Kubernetes Debug DNS Resolution guide | process_digital_dept | md | P1 | K8s / DNS | fetch_required | pending | 对应 C6-SRC-MD-010 的公开补充 |
| C6-WEB-MD-004 | Kubernetes ImagePullBackOff troubleshooting | process_digital_dept | md | P1 | K8s / image pull | fetch_required | pending | 如果内部 runbook 缺失可补 |
| C6-WEB-MD-005 | Kubernetes OOMKilled troubleshooting | process_digital_dept | md | P1 | K8s / OOM | fetch_required | pending | 如果内部 runbook 缺失可补 |
| C6-WEB-MD-006 | Prometheus alerting rules guide | process_digital_dept | md | P1 | Prometheus / alert rules | fetch_required | pending | 增加 alert 配置问题 |
| C6-WEB-MD-007 | Prometheus Alertmanager notifications guide | process_digital_dept | md | P1 | Alertmanager / notification | fetch_required | pending | 适合 oncall escalation query |
| C6-WEB-MD-008 | Grafana alerting notification policies guide | process_digital_dept | md | P1 | Grafana / alert routing | fetch_required | pending | 公开通用补充 |
| C6-WEB-MD-009 | Redis latency troubleshooting guide | process_digital_dept | md | P1 | Redis / latency | fetch_required | pending | 如果无内部 Redis runbook 可补 |
| C6-WEB-MD-010 | MySQL performance troubleshooting guide | process_digital_dept | md | P1 | MySQL / performance | fetch_required | pending | DB ops 补充 |
| C6-WEB-PDF-001 | AWS Operational Excellence Pillar PDF | process_digital_dept | pdf | P1 | ops governance | fetch_required | pending | 曾在 S4 候选中推荐；适合 incident/process |
| C6-WEB-PDF-002 | AWS Reliability Pillar PDF | process_digital_dept | pdf | P1 | reliability / recovery | fetch_required | pending | 与 SRE reliability budgets 互补 |
| C6-WEB-PDF-003 | Red Hat OpenShift Monitoring PDF | process_digital_dept | pdf | P1 | K8s / monitoring | fetch_required | pending | 与 Prometheus/K8s runbooks 互补 |
| C6-WEB-PDF-004 | Red Hat OpenShift Logging PDF | process_digital_dept | pdf | P1 | logging / troubleshooting | fetch_required | pending | 补 logging 诊断链路 |
| C6-WEB-PDF-005 | Red Hat OpenShift Backup/Restore PDF | process_digital_dept | pdf | P2 | backup / recovery | fetch_required | pending | 恢复类补充 |
| C6-WEB-PDF-006 | Google SRE Workbook incident response chapter PDF/HTML export | process_digital_dept | pdf | P2 | SRE / incident | fetch_required | pending | 若无稳定 PDF，可转 MD，需许可确认 |

---

## 9. 推荐 owner review 批次

### 第一批（推荐）

更新：2026-06-12 已批准并导入 C6-P1a local-first batch，共 10 个本地文件（4 Markdown + 6 PDF）。批准记录见 `docs/RAG_Corpus_清单6_C6-P1a_第一批批准记录.md`。本节原 12-18 个第一批建议保留为后续 C6-P1b/C6-P1c 参考，不再表示当前待执行动作。

目标：新增 12-18 个高质量文档，先让 corpus 到 30+。

建议组合：

- B 组 P0/P1 Markdown：优先 8-12 个真实 oncall runbook / SOP。
- B 组 craft PDF：优先 2-3 个真实工艺/维护/应急 PDF。
- A 组本地 craft PDF：选择 2-3 个 owner 确认 scope 的真实企业 PDF。
- C 组公开资料：最多补 2-4 个，避免 corpus 被公开通用资料主导。

### 暂缓

- AWS 827-page long PDF：保持 long-PDF/stress-eval 候选，不作为第一批 readiness 前置。
- PostgreSQL 3040-page official PDF：建议单独 DB/reference KB，不进入 mixed RAG 第一批。
- OpenViking / WeKnora / 本项目开发文档：除非明确要做“系统操作知识库”，否则不要混入业务 oncall/craft corpus。

---

## 10. 后续执行顺序

1. Owner review 本矩阵，选择第一批 12-18 个候选。
2. 将批准文件复制到 `原始文件/12_清单6_corpus_expansion_round2/`。
3. 生成 C6 reviewed import manifest。
4. 执行 reviewed import / index。
5. 跑 C6 corpus readiness gate。
6. 在扩充 corpus 上重跑 mixed 50q retrieval baseline。
7. 根据 retrieval baseline 的稳定/下降/提升，决定是否重启 Answer 50q、prompt shadow、PDF chunk targeting 或 agent_behavior。

---

## 11. 给小白解释

S4 和 S5 已经像是在 18 篇资料的小考场里考了两张卷：

- 检索卷：41/50，说明找资料能力基本稳定。
- 答题卷：13/20，说明生成答案还有限制，但安全边界干净。

现在不该继续死磕那 20 道答题题，而是先扩大考场。把资料从 18 篇扩到 30-50 篇，再看系统在更真实的资料规模下是否还能稳定找对资料。只有检索在更大 corpus 上稳定，Answer 50q 和 agent_behavior 才有意义。

---

## 12. C6-P1a 第一批批准与导入结果

日期：2026-06-12

批准记录：`docs/RAG_Corpus_清单6_C6-P1a_第一批批准记录.md`

受控目录：`原始文件/12_清单6_corpus_expansion_round2/`

manifest：

- `data/knowledge_ingestion/checklist6_c6_p1a/original_files_manifest.tsv`
- `data/knowledge_ingestion/checklist6_c6_p1a/original_files_manifest_review.tsv`
- `data/knowledge_ingestion/checklist6_c6_p1a/original_files_manifest.json`

报告：

- `evals/knowledge_base/reports/checklist6_c6_p1a_import_dry_run_20260612.json`
- `evals/knowledge_base/reports/checklist6_c6_p1a_import_apply_20260612.json`
- `evals/knowledge_base/reports/checklist6_c6_p1a_pdf_processing_20260612.json`
- `evals/knowledge_base/reports/checklist6_c6_p1a_sanity_20260612.json`
- `evals/knowledge_base/reports/checklist6_c6_p1a_sanity_20260612.md`

### 导入结果

```text
c6_p1a_imported = 10
c6_p1a_indexed = 10
c6_p1a_markdown_indexed = 4
c6_p1a_pdf_indexed = 6
c6_p1a_failed = 0
current_total_documents = 29
current_indexed_documents = 28
current_deferred_parsing = 1  # AWS IR 827-page long PDF
status = partial_corpus_expansion_28_docs_pending_2plus_owner_sources
```

说明：`current_total_documents=29` 是因为仍保留 1 个旧 AWS 827 页 PDF `parsing` 记录。C6-P1a 实际让 indexed 文档从 18 增加到 28，但 28 仍小于 C6 目标 30-50。

### Sanity 结果

```text
all_docs_exist = true
all_indexed = true
all_source_ref_resolvable = true
all_artifact_dirs_exist = true
pdf_required_files_all_present = true
docs_with_chunks = 10
kb_counts = {"craft_dept": 6, "process_digital_dept": 4}
format_counts = {"pdf": 6, "md": 4}
```

### 边界

- 不称为 C6 readiness passed。
- 不重跑正式 Mixed 50q retrieval baseline。
- 不创建 Answer 50q。
- 不进入 RAGAS / OpenJudge gate。
- 不进入 agent_behavior 层。
- 不修改 `rag_default_retrieval_mode`、`rag_query_rewrite_mode` 或 `rerank_enabled`。

### 下一步

C6-P1a 的 28-doc 缺口已由 C6-P1b 补齐。Redis high memory runbook 和 MySQL slow query runbook 已作为 owner-approved 真实业务 Markdown 导入并 indexed；当前正式状态见第 13 节。

## 13. C6-P1b owner runbook source block

日期：2026-06-12

```text
c6_p1b_status = c6_p1b_owner_runbooks_imported_30_indexed_docs
c6_p1b_required_sources = ["Redis high memory runbook", "MySQL slow query runbook"]
c6_p1b_readiness = ready_for_mixed_baseline
c6_p1b_formal_mixed_50q_baseline = 41/50
c6_p1c_public_reference_supplement = fallback_only_not_business_maturity_evidence
```

### 当前判定

- A 路线已完成：2 个真实业务 Markdown owner runbook 已收到、批准、导入并 indexed。
- C6-P1b manifest 已创建在 `data/knowledge_ingestion/checklist6_c6_p1b/`，不是 pending source block。
- Readiness 已通过：当前 indexed docs 为 30，达到 C6 的 30+ 前置门槛。
- 正式 Mixed 50q dense-only retrieval baseline 已重跑，结果保持 41/50，样本级状态无退化。
- B 组公开资料路线本轮未执行。若后续需要公开资料，只能另开 `C6-P1c public_reference_supplement`，并明确标注公开资料不等同内部业务 runbook。

### 已解除的阻塞条件

以下 2 个 Markdown 已收到并 owner 批准，C6-P1b 已进入 import/index/readiness/baseline：

- `C6-SRC-MD-001`：Redis high memory runbook
- `C6-SRC-MD-003`：MySQL slow query runbook

### C6-P1b 完成更新

用户确认进入 C6-P1b 后，2 个 B 组真实业务 Markdown runbook 已按 owner-approved 处理并导入：

- `C6-SRC-MD-001`：Redis high memory runbook -> `doc_4609992d-0697-513e-945d-7a3b0dae62f4`
- `C6-SRC-MD-003`：MySQL slow query runbook -> `doc_91ddd5b9-93bd-5c30-8a57-c7eb86a7942c`

C6-P1b manifest 位于 `data/knowledge_ingestion/checklist6_c6_p1b/`，批准记录见 `docs/RAG_Corpus_清单6_C6-P1b_owner_runbook批准记录.md`。

结果：

```text
c6_p1b_imported = 2
c6_p1b_indexed = 2
c6_p1b_current_indexed_docs = 30
c6_p1b_readiness = ready_for_mixed_baseline
c6_p1b_formal_mixed_50q_baseline = 41/50
status_changed_count_vs_before_c6_p1b = 0
```

公开资料 fallback 路线本轮未执行；不把 C 组公开资料当作内部业务成熟度证据。

## 14. 28-doc Observation-Only Mixed 50q 结果

日期：2026-06-12

Closeout：`docs/RAG_Corpus_清单6_Observation_Only_Closeout.md`

报告：`evals/knowledge_base/reports/department_rag_mixed_50q_on_28doc_observation_20260612.json`

```text
observation_only = true
c6_readiness_passed = false
formal_30plus_baseline = false
total = 50
passed = 41
failed = 9
answer_wrong = 8
no_retrieval_hit = 1
wrong_scope_count = 0
citation_unresolvable_count = 0
all_source_ref_resolvable = true
changed_status_count_vs_18doc_after_repair = 0
changed_failure_category_count_vs_18doc_after_repair = 0
```

判定：

- 28-doc observation-only 结果与 18-doc 修复后基线一致，没有引入新退化。
- 这只证明 C6-P1a 新增 10 个本地文件未破坏既有 50q 检索卷。
- 这不是最终 C6 readiness passed，因为它发生在 C6-P1b 之前，当时 indexed docs 仍为 28。
- 后续 C6-P1b 已补齐 Redis/MySQL owner runbook 并达到 30 indexed docs；当前状态以第 13 节为准。

## 15. C6-P2 Redis/MySQL Retrieval Pilot

日期：2026-06-12

记录：`docs/RAG_Corpus_清单6_C6-P2_Redis_MySQL_retrieval_pilot.md`

evalset：

- `evals/knowledge_base/evalsets/department_rag_c6_p2_redis_mysql_retrieval_4q.jsonl`

报告：

- `evals/knowledge_base/reports/department_rag_c6_p2_redis_mysql_retrieval_4q_dense_20260612.json`

结果：

```text
total = 4
passed = 4
failed = 0
not_ready = 0
wrong_scope_count = 0
citation_unresolvable_count = 0
all_source_ref_resolvable = true
```

判定：

- Redis high memory 和 MySQL slow query 新文档均能被 dense-only top-3 稳定召回。
- 本 pilot 本身不修改正式 Mixed 50q；后续 C6-P3 已在单独决策下创建派生 Mixed 54q baseline，原 50q 文件保持不变。
- C6-P2 只证明新增语料 retrieval 覆盖，不代表 Answer 层或 agent_behavior 层通过。

## 16. C6-P3 Mixed 54q Retrieval Baseline

日期：2026-06-12

记录：`docs/RAG_Corpus_清单6_C6-P3_Mixed_54q_retrieval_baseline.md`

evalset：

- `evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_54q_after_c6_p2.jsonl`

报告：

- `evals/knowledge_base/reports/checklist6_c6_p3_mixed_54q_readiness_20260612.json`
- `evals/knowledge_base/reports/department_rag_mixed_markdown_pdf_54q_after_c6_p2_dense_20260612.json`

结果：

```text
readiness = ready_for_mixed_baseline
total = 54
passed = 45
failed = 9
answer_wrong = 8
no_retrieval_hit = 1
not_ready = 0
wrong_scope_count = 0
citation_unresolvable_count = 0
all_source_ref_resolvable = true
existing_50q_status_changed_count = 0
c6_p2_new_samples_passed = 4/4
```

判定：

- Mixed 54q 是由原 Mixed 50q 加 C6-P2 4q 派生的新 retrieval baseline；不覆盖历史 50q。
- 新增 Redis/MySQL 样本全部通过，没有引入 not_ready、wrong_scope 或 citation/source_ref 问题。
- 45/54 达到“可考虑重开 Answer 层”的 retrieval 前提，但 Answer 层仍需单独阶段启动，不能由 C6-P3 自动推进到 Answer 50q、OpenJudge/RAGAS gate 或 agent_behavior。

## 17. C6 Final Closeout

日期：2026-06-12

记录：`docs/RAG_Corpus_清单6_Final_Closeout.md`

状态：`c6_final_closeout_complete_after_mixed_54q`

最终判定：

- C6 corpus/retrieval 轨道阶段收口。
- indexed corpus 为 30 docs：18 Markdown + 12 PDF，另有 1 个 AWS long-PDF parsing record 不计入 readiness。
- Mixed 50q 历史 baseline 保持 41/50，派生 Mixed 54q 为 45/54。
- Redis/MySQL 新增样本 4/4 通过，原 50q 样本状态变化为 0。
- source_ref / scope / citation 边界干净。
- 该结论只满足“可考虑重开 Answer 层”的 retrieval 前提，不自动推进 Answer 50q、OpenJudge/RAGAS 主 gate、agent_behavior 或默认检索配置变更。
