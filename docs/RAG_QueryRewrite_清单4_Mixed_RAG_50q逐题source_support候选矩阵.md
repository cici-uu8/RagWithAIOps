# RAG Query Rewrite 清单 4 Mixed RAG 50q 逐题 source_support 候选矩阵

日期：2026-06-10

状态：`approved_human_review_converted_to_formal_jsonl`

对应设计：`docs/RAG_QueryRewrite_清单4_Mixed_RAG_50q评测体系设计.md`

---

## 0. 结论

本文件是正式 mixed 50q JSONL 之前的人工 review 候选矩阵；当前已由 owner 人工 review 通过，并已转换为正式 JSONL。

当前边界：

```text
formal_jsonl_created = yes
readiness_rerun = yes
baseline_run = yes
rag_default_retrieval_mode = dense_only
rag_query_rewrite_mode = off
rerank_enabled = false
default_switch_eligibility = not_eligible_for_default_switch
review_status = approved_human_review
```

本文件只回答一件事：50 个候选样本是否逐题具备可人工复核的 `source_support`。

人工 review 通过后，已把通过的样本转成：

```text
evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_50q.jsonl
```

已复跑 mixed readiness，并已运行 dense-only baseline：

```text
readiness_report = evals/knowledge_base/reports/checklist4_mixed_50q_readiness_20260610.json
dense_baseline_report = evals/knowledge_base/reports/department_rag_mixed_markdown_pdf_50q_dense_baseline_20260610.json
baseline_result = 32_passed_18_failed
```

本文件继续保留为 review 依据，不作为 runner 输入；runner 输入以正式 JSONL 为准。

---

## 1. 使用规则

转正式 JSONL 前，每一行必须通过人工 review：

1. `expected_doc_ids` 必须全部来自当前 `data/knowledge_ingestion/current_import_state.json` 且 `status=indexed`。
2. `expected_answer_keywords` 必须能在 `source_support` 指向的原文、PDF `chunks.json`、`blocks.json` 或 `tables.json` 中找到。
3. PDF page/source_ref 样本必须保留 `expected_page`。
4. PDF table 样本必须保留真实 `expected_table_id`，不得使用描述性假 ID。
5. Expression-gap 样本必须保留差表达 query，并明确 `expression_gap_type` 与 `protected_terms`。
6. Permission/scope 样本必须明确 `allowed_kb_ids`、`target_kb_id`、`expected_failure` 或 `retrieved_must_not_contain_kb`。
7. 不允许把 AWS 827 页 `doc_2e11a6bb-770c-583c-9a32-84454985f7a6` 纳入首版 50q。
8. 不允许为了凑数把同一段 source support 改写成多道近似题。

---

## 2. 计数目标

| Bucket | 目标数量 | 本文件候选数量 |
|---|---:|---:|
| A. Markdown content recall | 15 | 15 |
| B. PDF content recall | 10 | 10 |
| C. PDF page/source_ref | 5 | 5 |
| D. PDF table/structured evidence | 5 | 5 |
| E. Expression-gap | 10 | 10 |
| F. Permission/scope/citation guardrail | 5 | 5 |
| Total | 50 | 50 |

格式覆盖候选：

```text
markdown_samples = 24
pdf_samples = 26
expression_gap_samples = 10
permission_scope_samples = 5
```

---

## 3. A 桶：Markdown Content Recall

| sample_id | bucket | format | query | allowed_kb_ids | expected_doc_ids | expected_answer_keywords | extra_fields | source_support | review_status |
|---|---|---|---|---|---|---|---|---|---|
| S4M-A-001 | A | md | CPU使用率持续超过80%怎么排查 | `process_digital_dept` | `doc_3b15644b-9560-5846-ad86-832321f6c4aa` | `cpu_usage > 80`; `分析CPU消耗进程`; `进程名称和PID`; `CPU占用百分比` | `failure_class=content_recall`; `retrieval_mode=dense_only`; `top_k=3` | `uploads/documents/process_digital_dept/doc_3b15644b-9560-5846-ad86-832321f6c4aa/original/cpu_high_usage.md` 排查步骤和查询示例。 | approved_human_review |
| S4M-A-002 | A | md | 内存占用过高如何定位是哪个进程 | `process_digital_dept` | `doc_31a0a4e4-d5a6-536e-8bfa-47ecd70bef85` | `memory_usage > 85`; `OutOfMemoryError`; `jmap -heap`; `jstat -gc` | `failure_class=content_recall`; `retrieval_mode=dense_only`; `top_k=3` | `uploads/documents/process_digital_dept/doc_31a0a4e4-d5a6-536e-8bfa-47ecd70bef85/original/memory_high_usage.md` 查询条件、OOM 排查和相关工具命令。 | approved_human_review |
| S4M-A-003 | A | md | 磁盘使用率超过90%时先查什么 | `process_digital_dept` | `doc_83f63bdc-b99b-5e9e-aba4-d293764584a4` | `HighDiskUsage`; `disk_usage > 80`; `No space left on device`; `哪个目录占用空间最大` | `failure_class=content_recall`; `retrieval_mode=dense_only`; `top_k=3` | `uploads/documents/process_digital_dept/doc_83f63bdc-b99b-5e9e-aba4-d293764584a4/original/disk_high_usage.md` 告警名称、查询示例和磁盘占用分析。 | approved_human_review |
| S4M-A-004 | A | md | 磁盘满了怎么快速释放空间 | `process_digital_dept` | `doc_83f63bdc-b99b-5e9e-aba4-d293764584a4` | `删除大日志文件`; `清理临时文件`; `du -ah /`; `紧急扩容` | `failure_class=content_recall`; `retrieval_mode=dense_only`; `top_k=3` | `disk_high_usage.md` 紧急处理措施和常用命令章节。 | approved_human_review |
| S4M-A-005 | A | md | 服务不可用时如何检查依赖服务 | `process_digital_dept` | `doc_68714517-c470-55c9-b94d-b483ebc0e45c` | `ServiceUnavailable`; `查询服务状态日志`; `检查依赖服务状态`; `downstream_service OR database OR redis OR mq` | `failure_class=content_recall`; `retrieval_mode=dense_only`; `top_k=3` | `uploads/documents/process_digital_dept/doc_68714517-c470-55c9-b94d-b483ebc0e45c/original/service_unavailable.md` 排查步骤。 | approved_human_review |
| S4M-A-006 | A | md | 服务不可用的15分钟内应急流程是什么 | `process_digital_dept` | `doc_68714517-c470-55c9-b94d-b483ebc0e45c` | `第一时间`; `快速定位`; `恢复服务`; `15分钟内` | `failure_class=content_recall`; `retrieval_mode=dense_only`; `top_k=3` | `service_unavailable.md` 紧急处理流程章节。 | approved_human_review |
| S4M-A-007 | A | md | 响应时间超过3秒怎么排查数据库慢查询 | `process_digital_dept` | `doc_3c49ecb5-fc61-5869-a847-055176b07393` | `SlowResponse`; `response_time > 3000`; `database-slow-query`; `EXPLAIN` | `failure_class=content_recall`; `retrieval_mode=dense_only`; `top_k=3` | `uploads/documents/process_digital_dept/doc_3c49ecb5-fc61-5869-a847-055176b07393/original/slow_response.md` 查询应用性能日志和数据库慢查询章节。 | approved_human_review |
| S4M-A-008 | A | md | 响应慢可能和缓存有什么关系 | `process_digital_dept` | `doc_3c49ecb5-fc61-5869-a847-055176b07393` | `缓存失效`; `缓存穿透`; `缓存命中率突然下降`; `布隆过滤器` | `failure_class=content_recall`; `retrieval_mode=dense_only`; `top_k=3` | `slow_response.md` 原因4“缓存失效或缓存穿透”。 | approved_human_review |
| S4M-A-009 | A | md | KubePodCrashLooping 应该看哪些 pod 信息 | `process_digital_dept` | `doc_67a5deac-6b7f-5598-bdc9-e8345ec539f6` | `KubePodCrashLooping`; `kubectl -n $NAMESPACE describe pod`; `kubectl -n $NAMESPACE logs`; `readiness and liveness probes` | `failure_class=content_recall`; `retrieval_mode=dense_only`; `top_k=3` | `uploads/documents/process_digital_dept/doc_67a5deac-6b7f-5598-bdc9-e8345ec539f6/original/KubePodCrashLooping.md` Diagnosis 段。 | approved_human_review |
| S4M-A-010 | A | md | KubePodNotReady 的 Running 但 not ready 表示什么 | `process_digital_dept` | `doc_8ad1b6b2-93b5-50b2-90c9-78dbcb31301b` | `KubePodNotReady`; `State Running but not ready`; `readiness probe fails`; `Debugging Pods` | `failure_class=content_recall`; `retrieval_mode=dense_only`; `top_k=3` | `uploads/documents/process_digital_dept/doc_8ad1b6b2-93b5-50b2-90c9-78dbcb31301b/original/KubePodNotReady.md` Meaning 和 Diagnosis。 | approved_human_review |
| S4M-A-011 | A | md | KubeNodeNotReady 需要检查什么命令 | `process_digital_dept` | `doc_e0307122-ea4c-5459-82bb-9101ee7ab4f4` | `KubeNodeNotReady`; `kubectl get node $NODE -o yaml`; `API or kubelet`; `node is not in Ready state` | `failure_class=content_recall`; `retrieval_mode=dense_only`; `top_k=3` | `uploads/documents/process_digital_dept/doc_e0307122-ea4c-5459-82bb-9101ee7ab4f4/original/KubeNodeNotReady.md` Meaning 和 Diagnosis。 | approved_human_review |
| S4M-A-012 | A | md | CPUThrottlingHigh 告警什么时候需要处理 | `process_digital_dept` | `doc_5bf080aa-1fda-5e71-8563-4c55c15d75de` | `CPU Throttling High`; `purely informative`; `application is behaving erratically`; `Give specific container in the pod more CPU limits` | `failure_class=content_recall`; `retrieval_mode=dense_only`; `top_k=3` | `uploads/documents/process_digital_dept/doc_5bf080aa-1fda-5e71-8563-4c55c15d75de/original/CPUThrottlingHigh.md` Impact 和 Mitigation。 | approved_human_review |
| S4M-A-013 | A | md | PersistentVolume 快满了有哪些缓解办法 | `process_digital_dept` | `doc_13936d70-e931-53f7-9b5e-1e6aee0dff72` | `KubePersistentVolumeFillingUp`; `Deleting no longer needed data`; `Data export`; `Direct Volume resizing` | `failure_class=content_recall`; `retrieval_mode=dense_only`; `top_k=3` | `uploads/documents/process_digital_dept/doc_13936d70-e931-53f7-9b5e-1e6aee0dff72/original/KubePersistentVolumeFillingUp.md` Mitigation 段。 | approved_human_review |
| S4M-A-014 | A | md | P0 告警的 Ack 和恢复时限是什么 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `P0`; `5 分钟内 Ack`; `1 小时内恢复`; `核心业务完全不可用` | `failure_class=content_recall`; `retrieval_mode=dense_only`; `top_k=3` | `uploads/documents/process_digital_dept/doc_6627ee79-7c85-531a-b545-55cfd5460e90/original/superbiz_oncall_handbook.md` 二、告警分级与响应 SLA。 | approved_human_review |
| S4M-A-015 | A | md | P0 或 P1 事故中 Incident Commander 要分配哪些角色 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `Incident Commander`; `Scribe`; `Operations Lead`; `Communications Lead` | `failure_class=content_recall`; `retrieval_mode=dense_only`; `top_k=3` | `superbiz_oncall_handbook.md` 六、事故 Commander 角色说明。 | approved_human_review |

---

## 4. B 桶：PDF Content Recall

| sample_id | bucket | format | query | allowed_kb_ids | expected_doc_ids | expected_answer_keywords | extra_fields | source_support | review_status |
|---|---|---|---|---|---|---|---|---|---|
| S4M-B-001 | B | pdf | PagerDuty 文档提到哪些 incident response training | `process_digital_dept` | `doc_af00144f-20e0-5716-a9e4-9f4b490def6c` | `Incident Response Training Course`; `Incident Commander Training`; `Deputy Training`; `Scribe Training` | `failure_class=pdf_content_recall`; `retrieval_mode=dense_only`; `top_k=3` | `online_handbook_1_pagerduty_incident_response_documentation.pdf` chunks `c00009` and `c00010`, page 3。 | approved_human_review |
| S4M-B-002 | B | pdf | PagerDuty Incident Response home 覆盖哪些内容 | `process_digital_dept` | `doc_af00144f-20e0-5716-a9e4-9f4b490def6c` | `PagerDuty Incident Response process`; `prepare new employees`; `on-call responsibilities`; `preparing for an incident` | `failure_class=pdf_content_recall`; `retrieval_mode=dense_only`; `top_k=3` | PagerDuty PDF chunk `c00001`, page 1。 | approved_human_review |
| S4M-B-003 | B | pdf | PagerDuty 文档里 during 和 after incident 有哪些章节 | `process_digital_dept` | `doc_af00144f-20e0-5716-a9e4-9f4b490def6c` | `During an Incident`; `Security Incident Response`; `After an Incident`; `Postmortem Process` | `failure_class=pdf_content_recall`; `retrieval_mode=dense_only`; `top_k=3` | PagerDuty PDF chunks `c00005` and `c00006`, page 2。 | approved_human_review |
| S4M-B-004 | B | pdf | unreliability budget 如何由 SLO 定义 | `process_digital_dept` | `doc_c89a35d0-1ac4-5a41-b098-6f38a66db450` | `Unreliability Budgets`; `quarterly unreliability budget`; `SLO`; `objective data` | `failure_class=pdf_content_recall`; `retrieval_mode=dense_only`; `top_k=3` | `pdf_2__un_reliability_budgets.pdf` chunk `c00006`, page 2。 | approved_human_review |
| S4M-B-005 | B | pdf | 网络中断或机房故障会不会消耗 reliability budget | `process_digital_dept` | `doc_c89a35d0-1ac4-5a41-b098-6f38a66db450` | `network outage`; `datacenter failure`; `consume the budget`; `number of new pushes may be reduced` | `failure_class=pdf_content_recall`; `retrieval_mode=dense_only`; `top_k=3` | Reliability PDF chunk `c00010`, page 3。 | approved_human_review |
| S4M-B-006 | B | pdf | Capacity Planning 文档如何定义 capacity | `process_digital_dept` | `doc_8aa24d1f-1521-56c9-b5e7-ce4146dff8ed` | `What Is Capacity`; `resources required to run your service`; `context you have chosen`; `resources you need` | `failure_class=pdf_content_recall`; `retrieval_mode=dense_only`; `top_k=3` | `pdf_3_capacity_planning.pdf` chunk `c00004`, page 1。 | approved_human_review |
| S4M-B-007 | B | pdf | Capacity Planning 里 primary drivers 包含哪些指标 | `process_digital_dept` | `doc_8aa24d1f-1521-56c9-b5e7-ce4146dff8ed` | `PRIMARY DRIVERS`; `gigs of data uploaded`; `storage and bandwidth`; `Web queries per second` | `failure_class=pdf_content_recall`; `retrieval_mode=dense_only`; `top_k=3` | Capacity PDF chunks `c00007` and `c00008`, page 2。 | approved_human_review |
| S4M-B-008 | B | pdf | Scoutflo SRE Playbooks 覆盖哪些平台和用途 | `process_digital_dept` | `doc_9b7841d2-e181-5afc-bc54-daaa5639b979` | `414 comprehensive incident response playbooks`; `AWS`; `Kubernetes`; `Sentry environments` | `failure_class=pdf_content_recall`; `retrieval_mode=dense_only`; `top_k=3` | `github_repo_6_scoutflo_sre_playbooks.pdf` chunks `c00001` and `c00004`, pages 1-2。 | approved_human_review |
| S4M-B-009 | B | pdf | Scoutflo 文档里 K8s playbook 覆盖哪些主题 | `process_digital_dept` | `doc_9b7841d2-e181-5afc-bc54-daaa5639b979` | `Pod lifecycle issues`; `CrashLoopBackOff`; `Network connectivity and DNS resolution`; `Resource quota and capacity constraints` | `failure_class=pdf_content_recall`; `retrieval_mode=dense_only`; `top_k=3` | Scoutflo PDF chunk `c00010`, page 5。 | approved_human_review |
| S4M-B-010 | B | pdf | Systems Performance 这本书面向什么场景 | `process_digital_dept` | `doc_48d65565-db05-522e-9186-b76e6925370c` | `Systems Performance`; `operating systems`; `applications`; `enterprise and cloud computing environments` | `failure_class=pdf_content_recall`; `retrieval_mode=dense_only`; `top_k=3` | `pdf_7_systems_performance__enterprise_and_the_cloud___cp.pdf` chunk `c00008`, page 26。 | approved_human_review |

---

## 5. C 桶：PDF Page / Source_ref

| sample_id | bucket | format | query | allowed_kb_ids | expected_doc_ids | expected_answer_keywords | expected_page | extra_fields | source_support | review_status |
|---|---|---|---|---|---|---|---:|---|---|---|
| S4M-C-001 | C | pdf | Capacity Planning 文档里 THEORETICAL MINIMUM CAPACITY 在哪一页 | `process_digital_dept` | `doc_8aa24d1f-1521-56c9-b5e7-ce4146dff8ed` | `THEORETICAL MINIMUM CAPACITY`; `capacity drivers`; `observed growth`; `Capacity Planning` | 2 | `failure_class=pdf_page_source_ref`; `retrieval_mode=dense_only`; `top_k=3` | Capacity PDF chunks `c00009` and `c00010`, page 2。 | approved_human_review |
| S4M-C-002 | C | pdf | PagerDuty Incident Commander Training 在哪一页 | `process_digital_dept` | `doc_af00144f-20e0-5716-a9e4-9f4b490def6c` | `Incident Commander Training`; `Deputy Training`; `Scribe Training`; `Training Guides` | 3 | `failure_class=pdf_page_source_ref`; `retrieval_mode=dense_only`; `top_k=3` | PagerDuty PDF chunk `c00009`, page 3。 | approved_human_review |
| S4M-C-003 | C | pdf | Unreliability Budgets 定义预算的段落在哪一页 | `process_digital_dept` | `doc_c89a35d0-1ac4-5a41-b098-6f38a66db450` | `Unreliability Budgets`; `quarterly unreliability budget`; `service's SLO`; `objective metric` | 2 | `failure_class=pdf_page_source_ref`; `retrieval_mode=dense_only`; `top_k=3` | Reliability PDF chunk `c00006`, page 2。 | approved_human_review |
| S4M-C-004 | C | pdf | Systems Performance 的 CPU analysis tools 表在哪一页 | `process_digital_dept` | `doc_48d65565-db05-522e-9186-b76e6925370c` | `CPU performance analysis tools`; `uptime`; `vmstat`; `mpstat` | 74 | `failure_class=pdf_page_source_ref`; `retrieval_mode=dense_only`; `top_k=3` | Systems PDF blocks `b00502`-`b00505` and chunk `c00101`, page 74。 | approved_human_review |
| S4M-C-005 | C | pdf | 工艺版线上故障处理里 LOTO 和现场安全在哪一页 | `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `LOTO`; `警戒线`; `零能量状态`; `现场设备工艺版` | 1 | `failure_class=pdf_page_source_ref`; `retrieval_mode=dense_only`; `top_k=3` | craft PDF chunk `c00004`, page 1。 | approved_human_review |

---

## 6. D 桶：PDF Table / Structured Evidence

| sample_id | bucket | format | query | allowed_kb_ids | expected_doc_ids | expected_answer_keywords | expected_table_id | expected_page | extra_fields | source_support | review_status |
|---|---|---|---|---|---|---|---|---:|---|---|---|
| S4M-D-001 | D | pdf | Scoutflo 表格里 KubePodCrashLooping 对应哪个 playbook | `process_digital_dept` | `doc_9b7841d2-e181-5afc-bc54-daaa5639b979` | `Alert Name`; `KubePodCrashLooping`; `KubeNodeNotReady`; `KubeAPIDown` | `t00002` | 29 | `failure_class=pdf_table`; `retrieval_mode=dense_only`; `top_k=3` | Scoutflo `artifacts/tables.json` table `t00002`, page 29。 | approved_human_review |
| S4M-D-002 | D | pdf | 工艺部 PDF 表格里的知识库场景和评测意图是什么 | `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `知识库场景`; `工艺部`; `评测意图`; `部门定向检索` | `t00001` | 1 | `failure_class=pdf_table`; `retrieval_mode=dense_only`; `top_k=3` | craft PDF `artifacts/tables.json` table `t00001`, page 1。 | approved_human_review |
| S4M-D-003 | D | pdf | Capacity Planning 表格里的资源申请流程有哪些步骤 | `process_digital_dept` | `doc_8aa24d1f-1521-56c9-b5e7-ce4146dff8ed` | `Lead Time`; `Generate planningnumbers`; `Request resources`; `Ready to serve` | `t00001` | 5 | `failure_class=pdf_table`; `retrieval_mode=dense_only`; `top_k=3` | Capacity PDF `artifacts/tables.json` table `t00001`, page 5。 | approved_human_review |
| S4M-D-004 | D | pdf | Systems Performance 的 CPU methodology 表格包含哪些方法 | `process_digital_dept` | `doc_48d65565-db05-522e-9186-b76e6925370c` | `Methodology`; `Tools method`; `USE method`; `Workload characterization` | `t00006` | 64 | `failure_class=pdf_table`; `retrieval_mode=dense_only`; `top_k=3` | Systems PDF `artifacts/tables.json` table `t00006`, page 64。 | approved_human_review |
| S4M-D-005 | D | pdf | Systems Performance 的 CPU 分析工具表列了哪些 Linux 工具 | `process_digital_dept` | `doc_48d65565-db05-522e-9186-b76e6925370c` | `Linux`; `uptime`; `vmstat`; `mpstat`; `DTrace, perf` | `t00008` | 74 | `failure_class=pdf_table`; `retrieval_mode=dense_only`; `top_k=3` | Systems PDF `artifacts/tables.json` table `t00008`, page 74。 | approved_human_review |

---

## 7. E 桶：Expression-gap

| sample_id | bucket | format | query | canonical_intent | expression_gap_type | protected_terms | allowed_kb_ids | expected_doc_ids | expected_answer_keywords | extra_fields | source_support | review_status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S4M-E-001 | E | md | 服务卡死了怎么办 | 服务不可用排查流程 | 口语化 | `服务卡死`; `怎么办` | `process_digital_dept` | `doc_68714517-c470-55c9-b94d-b483ebc0e45c` | `查询服务状态日志`; `application-logs`; `检查依赖服务状态`; `重启故障的依赖服务` | `failure_class=expression_gap`; `retrieval_mode=dense_only`; `top_k=3` | `service_unavailable.md` 查询服务状态日志、依赖服务状态和恢复依赖服务内容。 | approved_human_review |
| S4M-E-002 | E | md | K8s pod起不来咋整 | Kubernetes Pod NotReady 排查 | 缩写+口语化 | `K8s`; `pod`; `起不来`; `咋整` | `process_digital_dept` | `doc_8ad1b6b2-93b5-50b2-90c9-78dbcb31301b` | `KubePodNotReady`; `Debugging Pods`; `kubectl -n $NAMESPACE describe pod`; `readiness and liveness probes` | `failure_class=expression_gap`; `retrieval_mode=dense_only`; `top_k=3` | `KubePodNotReady.md` 当前 query 自然对应 Pod NotReady，不强行指向 CrashLooping。 | approved_human_review |
| S4M-E-003 | E | pdf | reliability budget是啥意思怎么用 | 可靠性预算定义和使用 | 中英混用+口语化 | `reliability budget`; `是啥`; `怎么用`; `SLO` | `process_digital_dept` | `doc_c89a35d0-1ac4-5a41-b098-6f38a66db450` | `unreliability budget`; `SLO`; `uptime`; `new pushes` | `failure_class=expression_gap`; `retrieval_mode=dense_only`; `top_k=3` | Reliability PDF chunks `c00006` and `c00010`, pages 2-3。 | approved_human_review |
| S4M-E-004 | E | md | 页面一直转圈很慢先看哪里 | 慢响应排查 | 口语化+症状描述 | `页面一直转圈`; `很慢`; `P99` | `process_digital_dept` | `doc_3c49ecb5-fc61-5869-a847-055176b07393` | `SlowResponse`; `response_time > 3000`; `数据库慢查询`; `缓存失效` | `failure_class=expression_gap`; `retrieval_mode=dense_only`; `top_k=3` | `slow_response.md` 问题描述、应用性能日志和数据库慢查询章节。 | approved_human_review |
| S4M-E-005 | E | md | 磁盘快爆了先删啥 | 磁盘使用率过高应急清理 | 口语化+症状描述 | `磁盘快爆`; `先删`; `disk_usage` | `process_digital_dept` | `doc_83f63bdc-b99b-5e9e-aba4-d293764584a4` | `删除大日志文件`; `清理临时文件`; `find /var/log`; `docker system prune` | `failure_class=expression_gap`; `retrieval_mode=dense_only`; `top_k=3` | `disk_high_usage.md` 日志文件过大、临时文件堆积和紧急清理章节。 | approved_human_review |
| S4M-E-006 | E | md | CPU throttling 很高要不要加 limit | Kubernetes CPU throttling 处理判断 | 中英混用+英文术语 | `CPU throttling`; `limit`; `CPUThrottlingHigh`; `container` | `process_digital_dept` | `doc_5bf080aa-1fda-5e71-8563-4c55c15d75de` | `CPU Throttling High`; `shouldn't increase CPU limits`; `application is behaving erratically`; `more CPU limits` | `failure_class=expression_gap`; `retrieval_mode=dense_only`; `top_k=3` | `CPUThrottlingHigh.md` Notice 和 When mixed with other alerts。 | approved_human_review |
| S4M-E-007 | E | pdf | capacity文档 source ref 页码怎么查 theoretical minimum | Capacity Planning 页码和 source_ref 查找 | 中英混用+技术术语 | `capacity`; `source_ref`; `theoretical minimum`; `page` | `process_digital_dept` | `doc_8aa24d1f-1521-56c9-b5e7-ce4146dff8ed` | `THEORETICAL MINIMUM CAPACITY`; `capacity drivers`; `observed growth`; `page 2` | `failure_class=expression_gap`; `retrieval_mode=dense_only`; `top_k=3`; `expected_page=2` | Capacity PDF chunks `c00009` and `c00010`, page 2。 | approved_human_review |
| S4M-E-008 | E | pdf | 工艺版现场问题先保安全怎么做 | 工艺部现场设备故障安全隔离 | 隐含scope+口语化 | `工艺版`; `现场问题`; `保安全`; `craft_dept`; `LOTO` | `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `人身安全`; `警戒线`; `LOTO`; `零能量状态` | `failure_class=expression_gap`; `retrieval_mode=dense_only`; `top_k=3`; `expected_page=1` | craft PDF chunk `c00004`, page 1。 | approved_human_review |
| S4M-E-009 | E | pdf | SRE playbook 里 K8s 告警怎么找 | Scoutflo SRE Playbooks K8s 告警索引 | 缩写+中英混用 | `SRE`; `playbook`; `K8s`; `KubePodCrashLooping` | `process_digital_dept` | `doc_9b7841d2-e181-5afc-bc54-daaa5639b979` | `Quick Reference`; `Alert Name`; `KubePodCrashLooping`; `KubeNodeNotReady` | `failure_class=expression_gap`; `retrieval_mode=dense_only`; `top_k=3`; `expected_table_id=t00002` | Scoutflo PDF table `t00002`, page 29。 | approved_human_review |
| S4M-E-010 | E | md | 数字化产线那个数智医生怎么支撑运维 | 中车长客数字化转型和健康管理 | 隐含scope+口语化 | `数字化产线`; `数智医生`; `运维支持`; `中车长客` | `process_digital_dept` | `doc_6cc9b0b1-d8b7-58d4-a7a0-6213f7717375` | `数智医生`; `运维支持`; `安全监测`; `数据分析` | `failure_class=expression_gap`; `retrieval_mode=dense_only`; `top_k=3` | `uploads/documents/process_digital_dept/doc_6cc9b0b1-d8b7-58d4-a7a0-6213f7717375/original/2024_人民网聚焦中车长客数字化转型成果.md` “数智医生”段。 | approved_human_review |

---

## 8. F 桶：Permission / Scope / Citation Guardrail

| sample_id | bucket | format | query | allowed_kb_ids | expected_doc_ids | expected_answer_keywords | guardrail_fields | extra_fields | source_support | review_status |
|---|---|---|---|---|---|---|---|---|---|---|
| S4M-F-001 | F | pdf | 现场设备工艺版故障处理手册在哪 | `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `工艺部`; `现场设备`; `故障处理`; `部门定向检索` | `target_kb_id=craft_dept` | `failure_class=permission_scope`; `retrieval_mode=dense_only`; `top_k=3` | craft PDF chunk `c00001` and table `t00001` prove craft-only document and source_ref path。 | approved_human_review |
| S4M-F-002 | F | md | 数字化转型的案例 | `process_digital_dept` | `doc_6cc9b0b1-d8b7-58d4-a7a0-6213f7717375` | `数字化转型`; `中车长客`; `智能扭矩系统`; `AI视觉识别技术` | `retrieved_must_not_contain_kb=craft_dept` | `failure_class=permission_scope`; `retrieval_mode=dense_only`; `top_k=3` | process_digital 原文“智能小助手”和“数字化转型”段；用于验证不串入 craft_dept。 | approved_human_review |
| S4M-F-003 | F | pdf | 我只有流程与数字化部权限，能看工艺部现场设备 PDF 吗 | `process_digital_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `permission_filtered`; `craft_dept`; `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `expected_failure=permission_filtered`; `target_kb_id=craft_dept` | `failure_class=permission_scope`; `retrieval_mode=dense_only`; `top_k=3` | Guardrail candidate: target doc is indexed under `craft_dept`, but allowed KB is only `process_digital_dept`; expected result is denial or no-leak, not content answer。 | approved_human_review |
| S4M-F-004 | F | md | 只给 craft_dept 权限时查 KubeNodeNotReady runbook | `craft_dept` | `doc_e0307122-ea4c-5459-82bb-9101ee7ab4f4` | `permission_filtered`; `process_digital_dept`; `KubeNodeNotReady` | `expected_failure=permission_filtered`; `target_kb_id=process_digital_dept` | `failure_class=permission_scope`; `retrieval_mode=dense_only`; `top_k=3` | Guardrail candidate: `KubeNodeNotReady.md` is indexed under `process_digital_dept`, but allowed KB is only `craft_dept`。 | approved_human_review |
| S4M-F-005 | F | md | process_digital_dept 查 P0 升级矩阵时不能串工艺部 PDF | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `P0`; `升级矩阵`; `SRE 团队 TL`; `War Room` | `retrieved_must_not_contain_kb=craft_dept` | `failure_class=permission_scope`; `retrieval_mode=dense_only`; `top_k=3` | `superbiz_oncall_handbook.md` 告警分级和升级矩阵；用于验证 process_digital 查询不返回 craft PDF。 | approved_human_review |

---

## 9. 人工 Review 通过后才能做的事

人工 review 通过后，下一步才是：

1. 将通过的 50 行转成正式 JSONL。
2. 跑 JSONL required fields / unique sample_id / indexed doc precheck。
3. 跑 PDF table artifact precheck。
4. 复跑 mixed readiness。
5. readiness 通过后，才跑 dense-only mixed baseline。

仍然不允许：

- 直接切换 `rag_default_retrieval_mode`。
- 直接启用 `rag_query_rewrite_mode`。
- 直接启用 `rerank_enabled`。
- 用本候选矩阵声称 hybrid / rerank / rewrite 已证明有效。
